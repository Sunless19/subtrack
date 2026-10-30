"""System tray icon: keeps the app alive when the window is closed and shows reminders."""

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from subtrack.services.reminder_service import ReminderService
from subtrack.ui.icon import app_icon
from subtrack.ui.notifier import MARK_PAID, SNOOZE_1H, SNOOZE_TOMORROW, NotificationAction, create_notifier

# Often enough that "Remind me in 1 hour" fires close to the hour; the check is a cheap query.
CHECK_INTERVAL_MS = 5 * 60 * 1000
# More reminders than this at once are combined into one summary notification.
MAX_SEPARATE_NOTIFICATIONS = 4


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, reminders: ReminderService, now=datetime.now, notifier=None, parent=None):
        super().__init__(app_icon(), parent)
        self._window = window
        self._reminders = reminders
        self._now = now
        self._told_about_tray = False
        self.setToolTip("SubTrack")

        self.notifier = notifier or create_notifier(self, self)
        self.notifier.action_requested.connect(self.handle_action)

        menu = QMenu()
        menu.addAction(QAction("Open SubTrack", menu, triggered=self.show_window))
        menu.addAction(QAction("Check reminders now", menu, triggered=self.check_reminders))
        self._quit_separator = menu.addSeparator()
        menu.addAction(QAction("Quit", menu, triggered=QApplication.quit))
        self._menu = menu  # keep a reference; Qt does not own it
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self.show_window)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_reminders)
        self._timer.start(CHECK_INTERVAL_MS)

    def add_update_action(self, check) -> None:
        self._menu.insertAction(self._quit_separator, QAction("Check for updates", self._menu, triggered=check))

    def show_window(self, reminders_tab: bool = False) -> None:
        self._window.refresh()
        if reminders_tab:
            self._window.show_reminders_tab()
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def notify_hidden(self) -> None:
        """Called the first time the window is closed, so the user knows the app still runs."""
        if not self._told_about_tray:
            self._told_about_tray = True
            self.showMessage("SubTrack is still running", "Reminders keep working. Right-click the tray icon to quit.")

    def check_reminders(self) -> None:
        now = self._now()
        today = now.date()
        due = self._reminders.due_reminders(now)
        self._reminders.record_check(now)
        if not due:
            return
        if len(due) <= MAX_SEPARATE_NOTIFICATIONS:
            for reminder in due:
                self.notifier.show(reminder, today)
        else:
            lines = [f"{r.subscription.name}: {r.message(today)}" for r in due[:3]]
            lines.append(f"…and {len(due) - 3} more. Open SubTrack to see them all.")
            self.notifier.show_summary(f"{len(due)} subscription reminders", "\n".join(lines))
        for reminder in due:
            self._reminders.mark_shown(reminder, now)
        self._window.refresh()

    def handle_action(self, action: NotificationAction) -> None:
        """A button (or the body) of a notification was clicked."""
        now = self._now()
        if action.action == MARK_PAID:
            self._reminders.mark_paid(action.subscription_id, action.due_date, now)
        elif action.action in (SNOOZE_1H, SNOOZE_TOMORROW):
            until = self._reminders.snooze_target(action.action.split(":")[1], now)
            self._reminders.snooze(action.subscription_id, action.kind, action.due_date, until)
        else:
            self.show_window(reminders_tab=True)
            return
        self._window.refresh()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()
