from datetime import date

import pytest

from conftest import make_sub
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.services.reminder_service import ReminderKind, ReminderService

TODAY = date(2026, 10, 27)


@pytest.fixture
def repo(db):
    return SubscriptionRepository(db)


@pytest.fixture
def service(db, repo):
    return ReminderService(repo, ReminderRepository(db), SettingsRepository(db))


def kinds(reminders):
    return [(r.kind, r.subscription.name, r.due_date) for r in reminders]


def test_payment_inside_window_is_due(repo, service):
    repo.insert(make_sub(name="Soon", first=date(2026, 1, 29)))   # next: 29 Oct, in 2 days
    repo.insert(make_sub(name="Later", first=date(2026, 1, 15)))  # next: 15 Nov
    assert kinds(service.due_reminders(TODAY)) == [(ReminderKind.PAYMENT, "Soon", date(2026, 10, 29))]


def test_trial_ending_reminder(repo, service):
    repo.insert(make_sub(name="Trial", first=date(2026, 11, 20), trial_end_date=date(2026, 10, 28)))
    assert kinds(service.due_reminders(TODAY)) == [(ReminderKind.TRIAL_ENDING, "Trial", date(2026, 10, 28))]


def test_reminder_is_shown_only_once(repo, service):
    repo.insert(make_sub(first=date(2026, 1, 27)))  # due today
    first = service.due_reminders(TODAY)
    assert len(first) == 1
    service.mark_shown(first[0])
    assert service.due_reminders(TODAY) == []


def test_window_follows_setting(db, repo, service):
    repo.insert(make_sub(first=date(2026, 1, 3)))  # next: 3 Nov, 7 days away
    assert service.due_reminders(TODAY) == []
    SettingsRepository(db).set("reminder_days_before", "7")
    assert len(service.due_reminders(TODAY)) == 1


def test_deleting_subscription_cleans_up_shown_reminders(db, repo, service):
    sub = repo.insert(make_sub(first=date(2026, 1, 27)))
    service.mark_shown(service.due_reminders(TODAY)[0])
    repo.delete(sub.id)
    assert db.connection.execute("SELECT COUNT(*) FROM shown_reminders").fetchone()[0] == 0


def test_message_wording(repo, service):
    repo.insert(make_sub(name="Netflix", price="49.99", first=date(2026, 1, 28), rarely_used=True))
    reminder = service.due_reminders(TODAY)[0]
    assert reminder.message(TODAY) == "49.99 RON will be charged tomorrow. You marked it as rarely used."
