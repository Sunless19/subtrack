"""Composition root: builds the database, repositories, services and windows."""

import logging
import logging.handlers
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from subtrack import __version__, paths
from subtrack.data.database import Database
from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.services.autostart_service import AutostartService
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService
from subtrack.services.reminder_service import ReminderService
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService
from subtrack.ui.icon import app_icon
from subtrack.ui.main_window import MainWindow
from subtrack.ui.notifier import set_process_app_id
from subtrack.ui.single_instance import InstanceServer, notify_running_instance
from subtrack.services import updater
from subtrack.ui.tray import TrayIcon
from subtrack.ui.update_manager import UpdateManager


def _setup_logging() -> None:
    """Log to %APPDATA%\\SubTrack\\subtrack.log (the packaged .exe has no console). Kept under ~1 MB."""
    handler = logging.handlers.RotatingFileHandler(
        paths.log_path(), maxBytes=500_000, backupCount=1, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger(__name__).info("SubTrack %s starting", __version__)


def _self_test() -> int:
    """Used by build.ps1 on the packaged .exe: can it load Qt Charts and native notifications?

    Shows nothing and changes nothing. Exit code 0 = OK; details go to the log.
    """
    log = logging.getLogger(__name__)
    try:
        from PySide6.QtCharts import QChart  # noqa: F401

        if sys.platform == "win32":
            from subtrack.ui.notifier import ToastNotifier

            app = QApplication(sys.argv)  # noqa: F841 - QObject needs an application
            ToastNotifier(register=False)
    except Exception:
        log.exception("Self-test failed")
        return 1
    log.info("Self-test passed")
    return 0


def run() -> int:
    if "--version" in sys.argv:
        print(f"SubTrack {__version__}")
        return 0
    minimized = "--minimized" in sys.argv
    _setup_logging()
    if "--self-test" in sys.argv:
        return _self_test()

    set_process_app_id()  # before any window exists, so Windows ties them to SubTrack
    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())

    # Already running: bring that window up (unless this is the startup launch) and stop.
    if notify_running_instance(show=not minimized):
        return 0
    instance = InstanceServer(app)

    db = Database(paths.database_path())
    subscription_repo = SubscriptionRepository(db)
    settings = SettingsRepository(db)

    currency = CurrencyService(settings)
    subscriptions = SubscriptionService(subscription_repo)
    stats = StatsService(subscription_repo, currency)
    reminders = ReminderService(subscription_repo, ReminderRepository(db), settings, PaymentRepository(db))
    exporter = ExportService(subscriptions)
    autostart = AutostartService()

    window = MainWindow(subscriptions, stats, currency, settings, exporter, autostart, reminders)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(window, reminders)
        tray.show()
        window.hide_on_close = True
        window.hidden_to_tray.connect(tray.notify_hidden)
        instance.show_requested.connect(tray.show_window)
        # The window being hidden must not end the app; only "Quit" in the tray does.
        app.setQuitOnLastWindowClosed(False)
    else:
        instance.show_requested.connect(window.showNormal)

        # Automatic updates need the tray (to keep running and to notify).
        updates = UpdateManager(settings, tray.notifier, window, parent=app)
        window.set_update_manager(updates)
        tray.add_update_action(lambda: window.check_for_updates())

    if "--after-update" in sys.argv:
        updater.cleanup(paths.updates_dir())
        logging.getLogger(__name__).info("Updated to %s", __version__)
        if tray:
            tray.notifier.show_summary(f"SubTrack updated to {__version__}", "See what's new on the releases page.")

    # --minimized is passed by the "start with Windows" entry: start quietly in the tray.
    if not (tray and minimized):
        window.show()
    if tray:
        tray.check_reminders()
    try:
        return app.exec()
    finally:
        db.close()
