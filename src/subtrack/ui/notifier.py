"""Shows reminders as desktop notifications.

On Windows 10/11 reminders are native toasts with buttons (Mark as paid,
Remind me in 1 hour, Remind me tomorrow) through the windows-toasts library.
Anywhere else, or if that fails, they fall back to the tray icon's plain
balloon messages, which have no buttons.

Button clicks arrive on a Windows thread; they are passed on through the
action_requested signal, which Qt delivers on the main thread.
"""

import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from subtrack import paths
from subtrack.services.reminder_service import Reminder, ReminderKind
from subtrack.ui.icon import draw_icon

log = logging.getLogger(__name__)

APP_ID = "SubTrack.App"  # Windows AppUserModelID; also in installer/subtrack.iss

OPEN = "open"
MARK_PAID = "paid"
SNOOZE_1H = "snooze:1h"
SNOOZE_TOMORROW = "snooze:tomorrow"


@dataclass(frozen=True)
class NotificationAction:
    action: str
    subscription_id: int | None = None
    kind: ReminderKind | None = None
    due_date: date | None = None


def encode(action: str, reminder: Reminder) -> str:
    return f"{action}|{reminder.subscription.id}|{reminder.kind.value}|{reminder.due_date.isoformat()}"


def decode(arguments: str | None) -> NotificationAction:
    """Anything unexpected (e.g. a click on an old toast) just opens the app."""
    try:
        action, sub_id, kind, due = (arguments or "").split("|")
        return NotificationAction(action, int(sub_id), ReminderKind(kind), date.fromisoformat(due))
    except ValueError:
        return NotificationAction(OPEN)


class Notifier(QObject):
    action_requested = Signal(object)  # NotificationAction

    has_buttons = False

    def show(self, reminder: Reminder, today: date) -> None:
        raise NotImplementedError

    def show_summary(self, title: str, text: str) -> None:
        raise NotImplementedError


class TrayNotifier(Notifier):
    """Fallback: plain tray balloon, clicking it opens the app."""

    def __init__(self, tray: QSystemTrayIcon, parent=None):
        super().__init__(parent)
        self._tray = tray
        tray.messageClicked.connect(lambda: self.action_requested.emit(NotificationAction(OPEN)))

    def show(self, reminder: Reminder, today: date) -> None:
        self._tray.showMessage(reminder.title(), reminder.message(today))

    def show_summary(self, title: str, text: str) -> None:
        self._tray.showMessage(title, text)


class ToastNotifier(Notifier):
    """Native Windows toasts with action buttons."""

    has_buttons = True

    def __init__(self, parent=None, register: bool = True):
        super().__init__(parent)
        from windows_toasts import InteractableWindowsToaster

        if register:
            register_app_id()
        self._toaster = InteractableWindowsToaster("SubTrack", APP_ID)

    def show(self, reminder: Reminder, today: date) -> None:
        from windows_toasts import Toast, ToastButton, ToastScenario

        toast = Toast(text_fields=[reminder.title(), reminder.message(today)], group="subtrack")
        # Same tag for the same reminder, so a snoozed one replaces its old toast.
        # Clicking the body (not a button) reports the tag, which decode() turns into OPEN.
        toast.tag = f"{reminder.subscription.id}-{reminder.kind.value}-{reminder.due_date:%Y%m%d}"
        # Gone from the Action Center the day after it no longer matters.
        toast.expiration_time = datetime.combine(reminder.due_date + timedelta(days=1), time(23, 59))
        if reminder.kind is ReminderKind.PAYMENT_DUE:
            # Stays on screen until the user does something with it.
            toast.scenario = ToastScenario.Reminder
        if reminder.kind.is_payment:
            toast.AddAction(ToastButton("Mark as paid", encode(MARK_PAID, reminder)))
            toast.AddAction(ToastButton("Remind me in 1 hour", encode(SNOOZE_1H, reminder)))
        toast.AddAction(ToastButton("Remind me tomorrow", encode(SNOOZE_TOMORROW, reminder)))
        toast.on_activated = lambda event: self.action_requested.emit(decode(event.arguments))
        self._toaster.show_toast(toast)

    def show_summary(self, title: str, text: str) -> None:
        from windows_toasts import Toast

        toast = Toast(text_fields=[title, text], group="subtrack")
        toast.tag = "summary"
        toast.on_activated = lambda event: self.action_requested.emit(NotificationAction(OPEN))
        self._toaster.show_toast(toast)


def register_app_id() -> None:
    """Give SubTrack its own name and icon in Windows notifications.

    Writes HKCU\\Software\\Classes\\AppUserModelId\\SubTrack.App (per user, no
    admin needed). Toast buttons only report clicks for a registered app ID.
    """
    import winreg

    icon_path = paths.data_dir() / "notification-icon.png"
    if not icon_path.exists():
        draw_icon(256).save(str(icon_path), "PNG")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}") as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "SubTrack")
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
        winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "FF2F6FDF")


def set_process_app_id() -> None:
    """Tie this process (taskbar button, notifications) to SubTrack's app ID."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def create_notifier(tray: QSystemTrayIcon, parent=None) -> Notifier:
    if sys.platform == "win32":
        try:
            notifier = ToastNotifier(parent)
            log.info("Notifications: Windows toasts with buttons")
            return notifier
        except Exception:  # library missing, old Windows, registry blocked, ...
            log.exception("Windows toasts unavailable, falling back to tray balloons")
    log.info("Notifications: tray balloons")
    return TrayNotifier(tray, parent)
