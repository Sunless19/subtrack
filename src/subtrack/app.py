"""Composition root: builds the database, repositories, services and windows."""

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from subtrack import __version__, paths
from subtrack.data.database import Database
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
from subtrack.ui.single_instance import InstanceServer, notify_running_instance
from subtrack.ui.tray import TrayIcon


def run() -> int:
    if "--version" in sys.argv:
        print(f"SubTrack {__version__}")
        return 0
    minimized = "--minimized" in sys.argv

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
    reminders = ReminderService(subscription_repo, ReminderRepository(db), settings)
    exporter = ExportService(subscriptions)
    autostart = AutostartService()

    window = MainWindow(subscriptions, stats, currency, settings, exporter, autostart)

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

    # --minimized is passed by the "start with Windows" entry: start quietly in the tray.
    if not (tray and minimized):
        window.show()
    if tray:
        tray.check_reminders()
    try:
        return app.exec()
    finally:
        db.close()
