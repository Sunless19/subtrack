"""Automatic updates: version checks, download + checksum verification, and when to install."""

import hashlib
import io
import json
import os
import urllib.error
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from subtrack import __version__
from subtrack.data.settings_repository import SettingsRepository
from subtrack.services import updater

INSTALLER = b"MZ fake installer bytes" * 1000
INSTALLER_HASH = hashlib.sha256(INSTALLER).hexdigest()


def release_json(tag="v99.0.0", with_installer=True):
    assets = [{"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt", "size": 100}]
    if with_installer:
        name = f"SubTrack-{tag.lstrip('v')}-setup.exe"
        assets.append({"name": name, "browser_download_url": f"https://x/{name}", "size": len(INSTALLER)})
    assets.append({"name": f"SubTrack-{tag.lstrip('v')}-portable.zip", "browser_download_url": "https://x/p.zip", "size": 1})
    return {"tag_name": tag, "html_url": f"https://github.com/r/releases/tag/{tag}", "body": "notes", "assets": assets}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_server(routes: dict):
    """An opener that serves bytes (or raises) per URL suffix."""

    def opener(request, timeout):
        url = request.full_url
        for suffix, body in routes.items():
            if url.endswith(suffix):
                if isinstance(body, Exception):
                    raise body
                return _Response(body)
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    return opener


# ---- versions and the release feed ---------------------------------------------------


@pytest.mark.parametrize("text, expected", [("v0.4.0", (0, 4, 0)), ("1.2", (1, 2, 0)), ("10.0.3", (10, 0, 3))])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "v1", "1.0-beta", "latest"])
def test_parse_version_rejects(text):
    with pytest.raises(ValueError):
        updater.parse_version(text)


def test_parse_release_picks_the_setup_exe():
    release = updater.parse_release(release_json("v1.2.3"))
    assert release.version == (1, 2, 3) and release.version_text == "1.2.3"
    assert release.installer_name == "SubTrack-1.2.3-setup.exe"
    assert release.checksums_url.endswith("SHA256SUMS.txt")


def test_is_newer():
    current = updater.current_version()
    newer = updater.parse_release(release_json("v99.0.0"))
    same = updater.parse_release(release_json("v" + __version__))
    assert updater.is_newer(newer) and not updater.is_newer(same) and not updater.is_newer(None)
    assert not updater.is_newer(newer, skipped="99.0.0")
    assert not updater.is_newer(updater.parse_release(release_json("v99.0.0", with_installer=False)))
    assert current == updater.parse_version(__version__)


def test_fetch_latest():
    opener = fake_server({"/releases/latest": json.dumps(release_json()).encode()})
    assert updater.fetch_latest(opener).version == (99, 0, 0)
    assert updater.fetch_latest(fake_server({})) is None  # repo has no releases yet (404)
    with pytest.raises(updater.UpdateError, match="Could not check"):
        updater.fetch_latest(fake_server({"/releases/latest": OSError("offline")}))
    with pytest.raises(updater.UpdateError, match="unexpected"):
        updater.fetch_latest(fake_server({"/releases/latest": b'{"tag_name": "nightly"}'}))


# ---- download and verification ---------------------------------------------------------


def test_download_verifies_checksum(tmp_path):
    release = updater.parse_release(release_json())
    sums = f"{INSTALLER_HASH}  SubTrack-99.0.0-setup.exe\n0000  other.zip\n".encode()
    seen = []
    path = updater.download(release, tmp_path, fake_server({"SHA256SUMS.txt": sums, "setup.exe": INSTALLER}),
                            progress=lambda done, total: seen.append((done, total)))
    assert path.read_bytes() == INSTALLER and path.name == "SubTrack-99.0.0-setup.exe"
    assert seen[-1] == (len(INSTALLER), len(INSTALLER))
    assert not list(tmp_path.glob("*.part"))


def test_damaged_download_is_deleted(tmp_path):
    release = updater.parse_release(release_json())
    sums = b"0" * 64 + b"  SubTrack-99.0.0-setup.exe\n"
    with pytest.raises(updater.UpdateError, match="damaged"):
        updater.download(release, tmp_path, fake_server({"SHA256SUMS.txt": sums, "setup.exe": INSTALLER}))
    assert list(tmp_path.iterdir()) == []


def test_installer_missing_from_checksums(tmp_path):
    release = updater.parse_release(release_json())
    with pytest.raises(updater.UpdateError, match="not listed"):
        updater.download(release, tmp_path, fake_server({"SHA256SUMS.txt": b"abc  other.exe\n"}))


def test_cleanup_keeps_only_the_current_installer(tmp_path):
    keep = tmp_path / "SubTrack-2.0.0-setup.exe"
    for name in ("SubTrack-1.0.0-setup.exe", "x.part", keep.name, "notes.txt"):
        (tmp_path / name).write_text("x")
    updater.cleanup(tmp_path, keep=keep)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SubTrack-2.0.0-setup.exe", "notes.txt"]


# ---- installing -----------------------------------------------------------------------------


def test_installer_command():
    command = updater.installer_command(Path(r"C:\Users\A B\SubTrack-1.0.0-setup.exe"), "minimized")
    assert command == (
        'ping -n 4 127.0.0.1 >nul & start "" "C:\\Users\\A B\\SubTrack-1.0.0-setup.exe" '
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=minimized"
    )
    with pytest.raises(ValueError):
        updater.installer_command(Path("x.exe"), "later")


def test_install_mode(tmp_path, monkeypatch):
    assert updater.install_mode() == "source"
    exe = tmp_path / "SubTrack.exe"
    exe.write_text("")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater.install_mode() == "portable"
    (tmp_path / "unins000.exe").write_text("")
    assert updater.install_mode() == "installer"


# ---- when the app installs ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeWindow(QObject):
    hidden_to_tray = Signal()

    def __init__(self, visible):
        super().__init__()
        self.visible = visible
        self.ready_version = None

    def isVisible(self):
        return self.visible

    def show_update_ready(self, version, install):
        self.ready_version = version


class FakeNotifier:
    def __init__(self):
        self.summaries = []

    def show_summary(self, title, text):
        self.summaries.append(title)


@pytest.fixture
def manager_factory(qapp, db, monkeypatch, tmp_path):
    from subtrack.ui import update_manager

    launched = []
    monkeypatch.setattr(update_manager.updater, "launch_installer", lambda path, relaunch: launched.append(relaunch))
    monkeypatch.setattr(update_manager.QApplication, "quit", staticmethod(lambda: None))

    def make(visible, auto_install="1", mode="installer"):
        settings = SettingsRepository(db)
        settings.set("update_auto_install", auto_install)
        window, notifier = FakeWindow(visible), FakeNotifier()
        manager = update_manager.UpdateManager(settings, notifier, window, mode=mode)
        manager._timer.stop()
        manager._installer = tmp_path / "SubTrack-99.0.0-setup.exe"
        return manager, window, notifier, launched

    return make


def test_installs_at_once_when_in_tray(manager_factory):
    manager, window, notifier, launched = manager_factory(visible=False)
    manager._on_ready(updater.parse_release(release_json()))
    assert launched == ["minimized"] and manager.pending is None


def test_waits_while_window_is_open_then_installs_when_hidden(manager_factory):
    manager, window, notifier, launched = manager_factory(visible=True)
    manager._on_ready(updater.parse_release(release_json()))
    assert launched == [] and window.ready_version == "99.0.0" and notifier.summaries == ["SubTrack 99.0.0 is ready"]
    window.hidden_to_tray.emit()
    assert launched == ["minimized"]


def test_manual_mode_never_installs_by_itself(manager_factory):
    manager, window, notifier, launched = manager_factory(visible=False, auto_install="0")
    manager._on_ready(updater.parse_release(release_json()))
    window.hidden_to_tray.emit()
    manager._install_on_quit()
    assert launched == [] and window.ready_version == "99.0.0"
    manager.install_now(show_window_after=True)
    assert launched == ["show"]


def test_installs_on_quit_without_relaunching(manager_factory):
    manager, window, notifier, launched = manager_factory(visible=True)
    manager._on_ready(updater.parse_release(release_json()))
    manager._install_on_quit()
    assert launched == ["none"]


def test_portable_copy_is_told_once(manager_factory):
    manager, window, notifier, launched = manager_factory(visible=True, mode="portable")
    release = updater.parse_release(release_json())
    manager._on_available(release)
    manager._on_available(release)
    assert notifier.summaries == ["SubTrack 99.0.0 is available"] and launched == []


def test_source_checkout_never_checks(manager_factory):
    manager, *_ = manager_factory(visible=True, mode="source")
    assert manager.check(manual=False) is False
