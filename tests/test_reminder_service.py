from datetime import date, datetime

import pytest

from conftest import make_sub
from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.services.reminder_service import ReminderKind, ReminderService, TimelineStatus

TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 10, 0)

SOON, DUE, TRIAL = ReminderKind.PAYMENT_SOON, ReminderKind.PAYMENT_DUE, ReminderKind.TRIAL_ENDING


@pytest.fixture
def repo(db):
    return SubscriptionRepository(db)


@pytest.fixture
def service(db, repo):
    return ReminderService(repo, ReminderRepository(db), SettingsRepository(db), PaymentRepository(db))


def kinds(reminders):
    return [(r.kind, r.subscription.name, r.due_date) for r in reminders]


def show_all(service, now=NOW):
    shown = service.due_reminders(now)
    for reminder in shown:
        service.mark_shown(reminder, now)
    return shown


def test_payment_inside_window_is_due(repo, service):
    repo.insert(make_sub(name="Soon", first=date(2026, 1, 29)))   # next: 29 Oct, in 2 days
    repo.insert(make_sub(name="Later", first=date(2026, 1, 15)))  # next: 15 Nov
    assert kinds(service.due_reminders(NOW)) == [(SOON, "Soon", date(2026, 10, 29))]


def test_payment_today_gives_day_of_reminder(repo, service):
    repo.insert(make_sub(name="Today", first=date(2026, 1, 27)))
    assert kinds(service.due_reminders(NOW)) == [(DUE, "Today", TODAY)]


def test_early_and_day_of_reminders_are_separate(repo, service):
    repo.insert(make_sub(name="Netflix", first=date(2026, 1, 29)))
    assert kinds(show_all(service)) == [(SOON, "Netflix", date(2026, 10, 29))]
    assert service.due_reminders(datetime(2026, 10, 28, 9)) == []          # early one already shown
    on_the_day = datetime(2026, 10, 29, 8)
    assert kinds(service.due_reminders(on_the_day)) == [(DUE, "Netflix", date(2026, 10, 29))]


def test_trial_ending_reminder(repo, service):
    repo.insert(make_sub(name="Trial", first=date(2026, 11, 20), trial_end_date=date(2026, 10, 28)))
    assert kinds(service.due_reminders(NOW)) == [(TRIAL, "Trial", date(2026, 10, 28))]


def test_reminder_is_shown_only_once(repo, service):
    repo.insert(make_sub(first=date(2026, 1, 27)))
    assert len(show_all(service)) == 1
    assert service.due_reminders(NOW) == []


def test_snooze_brings_reminder_back_later(repo, service):
    sub = repo.insert(make_sub(first=date(2026, 1, 27)))
    show_all(service)
    service.snooze(sub.id, DUE, TODAY, datetime(2026, 10, 27, 11, 0))
    assert service.due_reminders(datetime(2026, 10, 27, 10, 59)) == []
    again = service.due_reminders(datetime(2026, 10, 27, 11, 0))
    assert kinds(again) == [(DUE, sub.name, TODAY)]
    service.mark_shown(again[0], datetime(2026, 10, 27, 11, 0))
    assert service.due_reminders(datetime(2026, 10, 27, 12, 0)) == []


def test_snooze_targets():
    assert ReminderService.snooze_target("1h", datetime(2026, 10, 27, 23, 30, 15, 99)) == datetime(2026, 10, 28, 0, 30, 15)
    assert ReminderService.snooze_target("tomorrow", NOW) == datetime(2026, 10, 28, 9, 0)
    with pytest.raises(ValueError):
        ReminderService.snooze_target("never", NOW)


def test_paid_payment_has_no_reminders(repo, service):
    sub = repo.insert(make_sub(first=date(2026, 1, 29)))
    service.mark_paid(sub.id, date(2026, 10, 29), NOW)
    assert service.due_reminders(NOW) == []
    assert service.due_reminders(datetime(2026, 10, 29, 9)) == []  # no day-of either
    service.unmark_paid(sub.id, date(2026, 10, 29))
    assert len(service.due_reminders(NOW)) == 1


def test_window_follows_setting(db, repo, service):
    repo.insert(make_sub(first=date(2026, 1, 3)))  # next: 3 Nov, 7 days away
    assert service.due_reminders(NOW) == []
    SettingsRepository(db).set("reminder_days_before", "7")
    assert len(service.due_reminders(NOW)) == 1


def test_zero_days_before_means_only_day_of(db, repo, service):
    SettingsRepository(db).set("reminder_days_before", "0")
    repo.insert(make_sub(name="Tomorrow", first=date(2026, 1, 28)))
    repo.insert(make_sub(name="Today", first=date(2026, 1, 27)))
    assert kinds(service.due_reminders(NOW)) == [(DUE, "Today", TODAY)]


def test_deleting_subscription_cleans_up(db, repo, service):
    sub = repo.insert(make_sub(first=date(2026, 1, 27)))
    show_all(service)
    service.mark_paid(sub.id, TODAY, NOW)
    repo.delete(sub.id)
    for table in ("shown_reminders", "payments"):
        assert db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_messages(repo, service):
    repo.insert(make_sub(name="Netflix", price="49.99", first=date(2026, 1, 28), rarely_used=True))
    repo.insert(make_sub(name="Gym", price="150", first=date(2026, 1, 27)))
    due, soon = service.due_reminders(NOW)
    assert (due.title(), due.message(TODAY)) == ("Gym: payment due today", "150.00 RON will be charged today.")
    assert soon.message(TODAY) == "49.99 RON will be charged tomorrow. You marked it as rarely used."


def test_timeline_statuses(repo, service):
    netflix = repo.insert(make_sub(name="Netflix", first=date(2026, 9, 20)))  # 20 Oct (past), 20 Nov
    gym = repo.insert(make_sub(name="Gym", first=date(2026, 1, 27)))          # 27 Sep, 27 Oct (27 Nov is past the window)
    repo.insert(make_sub(name="Cloud", first=date(2026, 11, 20), trial_end_date=date(2026, 10, 29)))
    service.mark_paid(gym.id, date(2026, 9, 27), datetime(2026, 9, 27, 8, 0))
    service.snooze(netflix.id, SOON, date(2026, 11, 20), datetime(2026, 11, 18, 9, 0))
    show_all(service)  # shows Gym day-of and the Cloud trial reminder

    rows = [(e.subscription.name, e.date, e.is_trial_end, e.status, e.detail) for e in service.timeline(NOW)]
    assert rows == [
        ("Gym", date(2026, 9, 27), False, TimelineStatus.PAID, "on 27 Sep 08:00"),
        ("Netflix", date(2026, 10, 20), False, TimelineStatus.NOT_MARKED_PAID, ""),
        ("Gym", date(2026, 10, 27), False, TimelineStatus.REMINDED, "on 27 Oct 10:00"),
        ("Cloud", date(2026, 10, 29), True, TimelineStatus.REMINDED, "on 27 Oct 10:00"),
        ("Cloud", date(2026, 11, 20), False, TimelineStatus.UPCOMING, ""),
        ("Netflix", date(2026, 11, 20), False, TimelineStatus.SNOOZED, "until Wed 18 Nov 09:00"),
    ]
