"""Automatic updates from the public releases repository.

Flow: check the latest GitHub release → if it is newer, download the installer
and SHA256SUMS.txt → verify the checksum → run the installer silently (the app
quits first; the installer starts it again afterwards).

The releases repository is public and holds installers only; the source code
repository stays private, so no token is needed (and none is ever shipped).
No Qt here: ui/update_manager.py runs this off the main thread.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from subtrack import __version__

RELEASES_REPO = "Sunless19/subtrack-releases"
LATEST_URL = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"
TIMEOUT_SECONDS = 20


class UpdateError(Exception):
    """Checking, downloading or verifying failed. The message is user-facing."""


@dataclass(frozen=True)
class Release:
    version: tuple[int, ...]
    tag: str
    page_url: str
    notes: str
    installer_url: str | None
    installer_name: str | None
    installer_size: int
    checksums_url: str | None

    @property
    def version_text(self) -> str:
        return ".".join(str(n) for n in self.version)


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.4.0' -> (0, 4, 0). Raises ValueError for anything else (e.g. '1.0-beta')."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part or 0) for part in match.groups())


def current_version() -> tuple[int, ...]:
    return parse_version(__version__)


def parse_release(payload: dict) -> Release:
    """GitHub's 'latest release' JSON -> Release."""
    try:
        tag = payload["tag_name"]
        version = parse_version(tag)
        assets = {a["name"]: a for a in payload.get("assets", [])}
    except (KeyError, TypeError, ValueError) as error:
        raise UpdateError(f"The update server sent something unexpected ({error}).") from None
    installer = next((a for name, a in assets.items() if re.fullmatch(r"SubTrack-[\d.]+-setup\.exe", name)), None)
    checksums = assets.get("SHA256SUMS.txt")
    return Release(
        version=version,
        tag=tag,
        page_url=payload.get("html_url") or RELEASES_PAGE,
        notes=payload.get("body") or "",
        installer_url=installer["browser_download_url"] if installer else None,
        installer_name=installer["name"] if installer else None,
        installer_size=int(installer.get("size", 0)) if installer else 0,
        checksums_url=checksums["browser_download_url"] if checksums else None,
    )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url, headers={"User-Agent": f"SubTrack/{__version__}", "Accept": "application/vnd.github+json"}
    )


def fetch_latest(opener=urllib.request.urlopen) -> Release | None:
    """The latest published release, or None if the repository has none yet."""
    try:
        with opener(_request(LATEST_URL), timeout=TIMEOUT_SECONDS) as response:
            return parse_release(json.load(response))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise UpdateError(f"The update server answered {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise UpdateError(f"Could not check for updates: {error}") from None


def is_newer(release: Release | None, skipped: str = "") -> bool:
    """Newer than this copy, has an installer, and not a version the user chose to skip."""
    if release is None or release.installer_url is None:
        return False
    if skipped and release.version_text == skipped:
        return False
    return release.version > current_version()


def expected_checksum(checksums_text: str, filename: str) -> str:
    """Find filename in 'hash  name' lines (the format CI writes)."""
    for line in checksums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            return parts[0].lower()
    raise UpdateError(f"{filename} is not listed in SHA256SUMS.txt.")


def download(release: Release, folder: Path, opener=urllib.request.urlopen, progress=None) -> Path:
    """Download and verify the installer. Returns its path. A file that fails the check is deleted."""
    if release.installer_url is None or release.checksums_url is None:
        raise UpdateError("This release has no installer or no checksums.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.installer_name
    try:
        with opener(_request(release.checksums_url), timeout=TIMEOUT_SECONDS) as response:
            expected = expected_checksum(response.read().decode("utf-8", "replace"), release.installer_name)

        partial = target.with_suffix(".part")
        digest = hashlib.sha256()
        done = 0
        with opener(_request(release.installer_url), timeout=TIMEOUT_SECONDS) as response, open(partial, "wb") as file:
            while chunk := response.read(256 * 1024):
                file.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, release.installer_size)
    except UpdateError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise UpdateError(f"Could not download the update: {error}") from None

    if digest.hexdigest() != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError("The downloaded update is damaged (checksum mismatch) and was deleted.")
    partial.replace(target)
    return target


def cleanup(folder: Path, keep: Path | None = None) -> None:
    """Remove old installers and partial downloads."""
    if not folder.exists():
        return
    for path in folder.iterdir():
        if path != keep and path.suffix in (".exe", ".part"):
            path.unlink(missing_ok=True)


def install_mode() -> str:
    """'installer' when running from an installed copy (can update itself),
    'portable' for the unzipped portable copy (can only point to the download page),
    'source' when run with Python (updates disabled)."""
    if not getattr(sys, "frozen", False):
        return "source"
    exe_dir = Path(sys.executable).parent
    # Inno Setup puts its uninstaller next to the installed exe.
    return "installer" if any(exe_dir.glob("unins*.exe")) else "portable"


def installer_command(installer: Path, relaunch: str) -> str:
    """cmd.exe line that waits ~3 s, then runs the installer silently.

    relaunch: 'show' (open the window afterwards), 'minimized' (back to the tray)
    or 'none' (the user quit SubTrack; leave it closed). Read by installer/subtrack.iss.
    """
    if relaunch not in ("show", "minimized", "none"):
        raise ValueError(f"unknown relaunch mode {relaunch!r}")
    return (
        f'ping -n 4 127.0.0.1 >nul & start "" "{installer}" '
        f"/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH={relaunch}"
    )


def launch_installer(installer: Path, relaunch: str) -> None:
    """Start the installer silently a moment after this process has exited.

    The short delay lets SubTrack quit and release its single-instance mutex
    first; otherwise the installer would stop and ask to close SubTrack.
    """
    command = installer_command(installer, relaunch)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    # One string, not a list: cmd strips the outer quotes and keeps the inner ones as written
    # (a list would get backslash-escaped quotes, which cmd does not understand).
    subprocess.Popen(f'cmd /c "{command}"', creationflags=flags, close_fds=True, cwd=os.path.dirname(installer))
