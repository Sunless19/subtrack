import os
import sqlite3
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from conftest import make_sub
from subtrack.data.database import MIGRATIONS, Database
from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.services.reminder_service import Reminder, ReminderKind, ReminderService, TimelineStatus
from subtrack.ui import notifier
from subtrack.ui.notifier import NotificationAction, Notifier
from subtrack.ui.tray import TrayIcon

NOW = datetime(2026, 10, 27, 10, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeNotifier(Notifier):
    def __init__(self):
        super().__init__()
        self.shown, self.summaries = [], []

    def show(self, reminder, today):
        self.shown.append(reminder)

    def show_summary(self, title, text):
        self.summaries.append(title)


class FakeWindow:
    def __init__(self):
        self.refreshes = 0
        self.reminders_tab = False

    def refresh(self):
        self.refreshes += 1

    def show_reminders_tab(self):
        self.reminders_tab = True

    def showNormal(self): ...
    def raise_(self): ...
    def activateWindow(self): ...


@pytest.fixture
def setup(qapp, db):
    repo = SubscriptionRepository(db)
    service = ReminderService(repo, ReminderRepository(db), SettingsRepository(db), PaymentRepository(db))
    window, fake = FakeWindow(), FakeNotifier()
    clock = {"now": NOW}
    tray = TrayIcon(window, service, now=lambda: clock["now"], notifier=fake)
    return repo, service, tray, fake, window, clock


def test_encode_decode_round_trip():
    sub = make_sub(id=7)
    reminder = Reminder(ReminderKind.PAYMENT_DUE, sub, date(2026, 10, 27))
    assert notifier.decode(notifier.encode(notifier.SNOOZE_1H, reminder)) == NotificationAction(
        notifier.SNOOZE_1H, 7, ReminderKind.PAYMENT_DUE, date(2026, 10, 27)
    )


@pytest.mark.parametrize("junk", [None, "", "open", "a|b|c|d", "paid|1|nope|2026-01-01"])
def test_unexpected_arguments_just_open_the_app(junk):
    assert notifier.decode(junk) == NotificationAction(notifier.OPEN)


def test_tray_shows_each_reminder_once(setup):
    repo, service, tray, fake, window, clock = setup
    repo.insert(make_sub(name="Gym", first=date(2026, 1, 27)))
    tray.check_reminders()
    tray.check_reminders()
    assert [r.kind for r in fake.shown] == [ReminderKind.PAYMENT_DUE]


def test_many_reminders_become_one_summary(setup):
    repo, service, tray, fake, window, clock = setup
    for i in range(6):
        repo.insert(make_sub(name=f"Sub {i}", first=date(2026, 1, 27)))
    tray.check_reminders()
    assert fake.shown == [] and fake.summaries == ["6 subscription reminders"]
    tray.check_reminders()
    assert fake.summaries == ["6 subscription reminders"]  # all marked shown


def test_mark_paid_button(setup):
    repo, service, tray, fake, window, clock = setup
    sub = repo.insert(make_sub(first=date(2026, 1, 27)))
    tray.check_reminders()
    tray.handle_action(notifier.decode(notifier.encode(notifier.MARK_PAID, fake.shown[0])))
    entry = next(e for e in service.timeline(NOW) if e.date == date(2026, 10, 27))
    assert entry.status is TimelineStatus.PAID
    assert window.refreshes >= 2


def test_snooze_button_shows_reminder_again_an_hour_later(setup):
    repo, service, tray, fake, window, clock = setup
    repo.insert(make_sub(first=date(2026, 1, 27)))
    tray.check_reminders()
    tray.handle_action(notifier.decode(notifier.encode(notifier.SNOOZE_1H, fake.shown[0])))
    clock["now"] = datetime(2026, 10, 27, 10, 55)
    tray.check_reminders()
    assert len(fake.shown) == 1
    clock["now"] = datetime(2026, 10, 27, 11, 0)
    tray.check_reminders()
    assert len(fake.shown) == 2


def test_clicking_the_notification_opens_reminders_tab(setup):
    repo, service, tray, fake, window, clock = setup
    tray.handle_action(NotificationAction(notifier.OPEN))
    assert window.reminders_tab


def test_upgrade_from_v0_1_database(tmp_path):
    """A database created by v0.1 (2 migrations) keeps its data after upgrading."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for script in MIGRATIONS[:2]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 2")
    conn.execute(
        "INSERT INTO subscriptions (name, price, currency, billing_cycle, first_payment_date, category) "
        "VALUES ('Old', '5', 'RON', 'monthly', '2026-01-28', 'other')"
    )
    conn.execute("INSERT INTO shown_reminders VALUES (1, 'payment', '2026-10-28')")
    conn.commit()
    conn.close()

    db = Database(path)
    assert db.schema_version == len(MIGRATIONS)
    service = ReminderService(
        SubscriptionRepository(db), ReminderRepository(db), SettingsRepository(db), PaymentRepository(db)
    )
    # The early reminder shown by v0.1 is not repeated; the new day-of reminder still comes.
    assert service.due_reminders(NOW) == []
    assert [r.kind for r in service.due_reminders(datetime(2026, 10, 28, 9))] == [ReminderKind.PAYMENT_DUE]
    old = next(e for e in service.timeline(NOW) if e.date == date(2026, 10, 28))
    assert (old.status, old.detail) == (TimelineStatus.REMINDED, "on 28 Oct 00:00")
    db.close()
