"""Runs the updater in the background and decides when to install.

- Checks 1 minute after start, then every 6 hours (Settings: "Check for updates automatically").
- A newer version is downloaded and verified in a background thread.
- "Install updates automatically" on: installs as soon as SubTrack is in the tray
  (window closed), or when the user quits. Off: a "Restart to update" button and a
  notification; the user decides.
- Portable copies can't replace themselves, so they only get a notification
  pointing to the download page. Running from source never updates.
"""

import logging
import threading
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from subtrack import paths
from subtrack.data.settings_repository import SettingsRepository
from subtrack.services import updater

log = logging.getLogger(__name__)

FIRST_CHECK_MS = 60 * 1000
CHECK_EVERY_MS = 6 * 60 * 60 * 1000


class UpdateManager(QObject):
    # Emitted on the main thread (Qt queues signals emitted from the worker thread).
    ready = Signal(object)  # Release, installer downloaded and verified
    available = Signal(object)  # Release, portable copy: download it yourself
    finished = Signal(object, str)  # Release | None, error text ("" if fine): result of every check

    def __init__(self, settings: SettingsRepository, notifier, window, parent=None, mode=None):
        super().__init__(parent)
        self._settings = settings
        self._notifier = notifier
        self._window = window
        self.mode = mode or updater.install_mode()
        self._busy = False
        self.pending: updater.Release | None = None
        self._installer = None

        self.ready.connect(self._on_ready)
        self.available.connect(self._on_available)

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.check(manual=False))
        if self.mode != "source":
            QTimer.singleShot(FIRST_CHECK_MS, lambda: self.check(manual=False))
            self._timer.start(CHECK_EVERY_MS)
        window.hidden_to_tray.connect(self._install_if_automatic)
        QApplication.instance().aboutToQuit.connect(self._install_on_quit)

    # ---- settings ------------------------------------------------------------

    def auto_check(self) -> bool:
        return self._settings.get("update_auto_check", "1") == "1"

    def auto_install(self) -> bool:
        return self._settings.get("update_auto_install", "1") == "1"

    # ---- checking and downloading -------------------------------------------

    def check(self, manual: bool) -> bool:
        """Start a check in the background. Returns False if one is already running or checks are off."""
        if self._busy or self.mode == "source" or (not manual and not self.auto_check()):
            if manual and self.mode == "source":
                self.finished.emit(None, "Updates are not available when running from source.")
            return False
        self._busy = True
        threading.Thread(target=self._work, args=(manual,), daemon=True, name="update-check").start()
        return True

    def _work(self, manual: bool) -> None:
        release, error = None, ""
        try:
            release = updater.fetch_latest()
            skipped = "" if manual else self._settings.get("update_skipped_version", "")
            if updater.is_newer(release, skipped):
                log.info("Update available: %s", release.version_text)
                if self.mode == "installer":
                    folder = paths.updates_dir()
                    installer = updater.download(release, folder)
                    updater.cleanup(folder, keep=installer)
                    self._installer = installer
                    self.ready.emit(release)
                else:
                    self.available.emit(release)
        except updater.UpdateError as exc:
            error = str(exc)
            log.warning("Update check failed: %s", error)
        finally:
            self._busy = False
            self.finished.emit(release, error)

    # ---- what to do with a new version -----------------------------------------

    def _on_ready(self, release) -> None:
        self.pending = release
        self._window.show_update_ready(release.version_text, self.install_now)
        if self.auto_install() and not self._window.isVisible():
            self.install_now(show_window_after=False)
            return
        if self.auto_install():
            text = "It will install when you close the SubTrack window, or click 'Restart to update'."
        else:
            text = "Click 'Restart to update' in SubTrack's status bar to install it."
        self._notifier.show_summary(f"SubTrack {release.version_text} is ready", text)

    def _on_available(self, release) -> None:
        if self._settings.get("update_notified_version", "") == release.version_text:
            return
        self._settings.set("update_notified_version", release.version_text)
        self._notifier.show_summary(
            f"SubTrack {release.version_text} is available",
            "This portable copy can't update itself. Open SubTrack → Check for updates to download it.",
        )

    def _install_if_automatic(self) -> None:
        if self.pending is not None and self.auto_install():
            self.install_now(show_window_after=False)

    def _install_on_quit(self) -> None:
        if self.pending is not None and self.auto_install() and self._installer is not None:
            log.info("Installing %s on quit", self.pending.version_text)
            updater.launch_installer(self._installer, relaunch="none")
            self.pending = None

    def install_now(self, show_window_after: bool = True) -> None:
        if self._installer is None or self.pending is None:
            return
        log.info("Installing %s now", self.pending.version_text)
        updater.launch_installer(self._installer, relaunch="show" if show_window_after else "minimized")
        self.pending = None  # don't launch it a second time from aboutToQuit
        QApplication.instance().quit()

    def skip(self, release) -> None:
        self._settings.set("update_skipped_version", release.version_text)

    @staticmethod
    def open_download_page(release=None) -> None:
        webbrowser.open(release.page_url if release else updater.RELEASES_PAGE)
