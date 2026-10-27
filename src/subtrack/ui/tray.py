"""System tray icon: keeps the app alive when the window is closed and shows reminders."""

from datetime import date

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from subtrack.services.reminder_service import ReminderService
from subtrack.ui.icon import app_icon

CHECK_INTERVAL_MS = 60 * 60 * 1000  # one hour


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, reminders: ReminderService, today=date.today, parent=None):
        super().__init__(app_icon(), parent)
        self._window = window
        self._reminders = reminders
        self._today = today
        self._told_about_tray = False
        self.setToolTip("SubTrack")

        menu = QMenu()
        menu.addAction(QAction("Open SubTrack", menu, triggered=self.show_window))
        menu.addAction(QAction("Check reminders now", menu, triggered=self.check_reminders))
        menu.addSeparator()
        menu.addAction(QAction("Quit", menu, triggered=QApplication.quit))
        self._menu = menu  # keep a reference; Qt does not own it
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self.show_window)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_reminders)
        self._timer.start(CHECK_INTERVAL_MS)

    def show_window(self) -> None:
        self._window.refresh()
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def notify_hidden(self) -> None:
        """Called the first time the window is closed, so the user knows the app still runs."""
        if not self._told_about_tray:
            self._told_about_tray = True
            self.showMessage("SubTrack is still running", "Reminders keep working. Right-click the tray icon to quit.")

    def check_reminders(self) -> None:
        today = self._today()
        due = self._reminders.due_reminders(today)
        if not due:
            return
        if len(due) == 1:
            self.showMessage(due[0].title(), due[0].message(today))
        else:
            lines = [f"- {r.subscription.name}: {r.message(today)}" for r in due[:5]]
            if len(due) > 5:
                lines.append(f"... and {len(due) - 5} more")
            self.showMessage(f"{len(due)} subscription reminders", "\n".join(lines))
        for reminder in due:
            self._reminders.mark_shown(reminder)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()
