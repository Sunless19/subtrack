"""Contract / notice period, missed-reminder catch-up, payment method, spending history and
forecast, pause / skip, introductory price, templates, badges and online exchange rates."""

import io
import json
import os
from datetime import date, datetime
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from conftest import make_sub
from subtrack.data.database import MIGRATIONS, Database
from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing, templates
from subtrack.domain.models import BillingCycle, Category, Currency, PriceChange
from subtrack.services import online_rates
from subtrack.services.calendar_export import build_calendar
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService
from subtrack.services.reminder_service import (
    Reminder,
    ReminderKind,
    ReminderService,
    TimelineEvent,
    TimelineStatus,
)
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService, ValidationError

TODAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 28, 10, 0)


@pytest.fixture
def repo(db):
    return SubscriptionRepository(db)


@pytest.fixture
def service(repo):
    return SubscriptionService(repo, today=lambda: TODAY)


@pytest.fixture
def reminders(db, repo):
    return ReminderService(repo, ReminderRepository(db), SettingsRepository(db), PaymentRepository(db))


@pytest.fixture
def stats(db, repo):
    currency = CurrencyService(SettingsRepository(db))
    currency.set_rate_in_ron(Currency.EUR, Decimal("5"))
    return StatsService(repo, currency, today=lambda: TODAY)


def kinds(found):
    return [(r.kind, r.subscription.name, r.due_date) for r in found]


# ---- storage --------------------------------------------------------------------


def test_new_fields_round_trip(repo):
    sub = repo.insert(make_sub(
        payment_method="Revolut card", contract_end_date=date(2027, 3, 1), notice_days=30,
        paused_from=date(2026, 12, 1), paused_until=date(2027, 1, 31),
        promo_price=Decimal("9.99"), promo_until=date(2026, 12, 31),
    ))
    assert repo.get(sub.id) == sub
    assert repo.payment_methods() == ["Revolut card"]


def test_v02_database_upgrades(tmp_path):
    path = tmp_path / "v02.db"
    import sqlite3

    conn = sqlite3.connect(path)
    for script in MIGRATIONS[:4]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 4")
    conn.execute(
        "INSERT INTO subscriptions (name, price, currency, billing_cycle, first_payment_date, category, shared_with) "
        "VALUES ('Old', '5', 'RON', 'monthly', '2026-01-28', 'other', 2)"
    )
    conn.commit()
    conn.close()
    db = Database(path)
    old = SubscriptionRepository(db).get(1)
    assert (old.shared_with, old.payment_method, old.notice_days, old.promo_price) == (2, "", 0, None)
    db.close()


# ---- validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields, message",
    [
        (dict(paused_from=date(2026, 12, 1)), "both a start and an end"),
        (dict(paused_from=date(2026, 12, 2), paused_until=date(2026, 12, 1)), "cannot end before"),
        (dict(promo_price=Decimal("5")), "both an amount and an end date"),
        (dict(notice_days=400), "between 0 and 365"),
        (dict(payment_method="x" * 61), "at most 60"),
    ],
)
def test_validation(service, fields, message):
    with pytest.raises(ValidationError, match=message):
        service.add(make_sub(**fields))


# ---- contract end / notice period -------------------------------------------------------


def test_cancel_by_reminder(reminders, repo):
    repo.insert(make_sub(name="Phone", first=date(2026, 1, 15), contract_end_date=date(2026, 11, 29), notice_days=30))
    # cancel by 30 Oct = in 2 days, inside the default 3-day window
    assert kinds(reminders.due_reminders(NOW)) == [(ReminderKind.CANCEL_BY, "Phone", date(2026, 10, 30))]
    reminder = reminders.due_reminders(NOW)[0]
    assert reminder.message(TODAY) == "To stop it renewing on 29 Nov 2026, cancel by Fri 30 Oct (in 2 days)."


def test_timeline_shows_contract_and_promo_dates(reminders, repo):
    repo.insert(make_sub(name="Phone", first=date(2026, 1, 15), contract_end_date=date(2026, 11, 29), notice_days=30,
                         promo_price=Decimal("10"), promo_until=date(2026, 11, 5)))
    events = {(e.event, e.date) for e in reminders.timeline(NOW)}
    assert (TimelineEvent.CANCEL_BY, date(2026, 10, 30)) in events
    assert (TimelineEvent.PROMO_END, date(2026, 11, 5)) in events


# ---- missed reminders while the PC was off ----------------------------------------------


def test_missed_payments_since_last_check(reminders, repo):
    repo.insert(make_sub(name="Gym", first=date(2026, 1, 26)))      # 26 Oct, while away
    repo.insert(make_sub(name="Old", first=date(2026, 1, 10)))      # 10 Oct, before the last check
    reminders.record_check(datetime(2026, 10, 24, 22, 0))
    assert kinds(reminders.due_reminders(NOW)) == [(ReminderKind.PAYMENT_MISSED, "Gym", date(2026, 10, 26))]


def test_no_catch_up_on_first_run_or_when_paid(reminders, repo):
    gym = repo.insert(make_sub(name="Gym", first=date(2026, 1, 26)))
    assert reminders.due_reminders(NOW) == []  # never checked before: nothing to catch up
    reminders.record_check(datetime(2026, 10, 24))
    reminders.mark_paid(gym.id, date(2026, 10, 26), NOW)
    assert reminders.due_reminders(NOW) == []


def test_catch_up_is_limited_to_a_week(reminders, repo):
    repo.insert(make_sub(name="Weekly", cycle=BillingCycle.WEEKLY, first=date(2026, 1, 1)))
    reminders.record_check(datetime(2026, 9, 1))
    missed = [r for r in reminders.due_reminders(NOW) if r.kind is ReminderKind.PAYMENT_MISSED]
    assert all(r.due_date >= date(2026, 10, 21) for r in missed) and len(missed) == 1


# ---- pause / skip ------------------------------------------------------------------------


def test_pause_skips_payments():
    sub = make_sub(first=date(2026, 1, 15), paused_from=date(2026, 11, 1), paused_until=date(2027, 1, 31))
    assert billing.next_payment_date(sub, TODAY) == date(2027, 2, 15)
    assert billing.payment_dates(sub, date(2026, 10, 1), date(2027, 3, 31)) == [
        date(2026, 10, 15), date(2027, 2, 15), date(2027, 3, 15)
    ]


def test_skip_next_payment_and_resume(service, reminders):
    sub = service.add(make_sub(name="Gym", first=date(2026, 1, 30)))
    assert service.skip_next_payment(sub.id) == date(2026, 10, 30)
    row = service.list_rows()[0]
    assert row.paused and row.next_payment == date(2026, 11, 30)
    skipped = [e for e in reminders.timeline(NOW) if e.status is TimelineStatus.SKIPPED]
    assert [(e.date, e.can_mark_paid) for e in skipped] == [(date(2026, 10, 30), False)]
    service.resume(sub.id)
    assert service.list_rows()[0].next_payment == date(2026, 10, 30)


# ---- introductory price -------------------------------------------------------------------


def test_promo_price_until_date():
    sub = make_sub(price="50", promo_price=Decimal("10"), promo_until=date(2026, 12, 31))
    assert billing.amount_on(sub, date(2026, 12, 31)) == (Decimal("10"), Currency.RON)
    assert billing.amount_on(sub, date(2027, 1, 1)) == (Decimal("50"), Currency.RON)
    assert billing.monthly_cost(sub, on=TODAY) == Decimal("10.00")
    assert billing.monthly_cost(sub) == Decimal("50.00")


def test_promo_ending_reminder_and_message(reminders, repo):
    repo.insert(make_sub(name="Stream", price="50", first=date(2026, 1, 5),
                         promo_price=Decimal("10"), promo_until=date(2026, 10, 30)))
    promo = [r for r in reminders.due_reminders(NOW) if r.kind is ReminderKind.PROMO_ENDING]
    assert promo[0].message(TODAY) == "The introductory price of 10.00 ends on Fri 30 Oct (in 2 days); then it costs 50.00 RON."


def test_calendar_uses_promo_price_then_regular():
    sub = make_sub(name="Stream", price="50", first=date(2026, 1, 5), promo_price=Decimal("10"),
                   promo_until=date(2026, 11, 30), id=9)
    text, _ = build_calendar([sub], TODAY, months=2)
    assert "SUMMARY:Stream – 10.00 RON" in text and "SUMMARY:Stream – 50.00 RON" in text


# ---- spending history and forecast --------------------------------------------------------


def test_amount_on_uses_price_history():
    sub = make_sub(price="15")
    history = [PriceChange(date(2026, 6, 1), Decimal("10"), Currency.RON, Decimal("12"), Currency.RON),
               PriceChange(date(2026, 9, 1), Decimal("12"), Currency.RON, Decimal("15"), Currency.RON)]
    assert billing.amount_on(sub, date(2026, 5, 31), history)[0] == Decimal("10")
    assert billing.amount_on(sub, date(2026, 6, 1), history)[0] == Decimal("12")
    assert billing.amount_on(sub, date(2026, 10, 1), history)[0] == Decimal("15")


def test_spent_so_far_uses_prices_at_the_time(service, stats):
    sub = service.add(make_sub(name="Gym", price="10", first=date(2026, 8, 1)))   # Aug, Sep, Oct
    sub.price = Decimal("20")
    service.update(sub)  # changed today (28 Oct), so all three past payments were 10
    assert stats.spent_so_far()[sub.id] == Decimal("30.00")


def test_monthly_spending_buckets(service, stats):
    service.add(make_sub(name="Monthly", price="10", first=date(2026, 9, 15)))
    service.add(make_sub(name="Yearly EUR", price="12", currency=Currency.EUR, cycle=BillingCycle.YEARLY,
                         first=date(2026, 12, 1)))
    months = stats.monthly_spending(months_back=2, months_ahead=3)
    assert [(m.month, m.amount, m.is_forecast) for m in months] == [
        (date(2026, 8, 1), Decimal("0.00"), False),
        (date(2026, 9, 1), Decimal("10.00"), False),
        (date(2026, 10, 1), Decimal("10.00"), True),
        (date(2026, 11, 1), Decimal("10.00"), True),
        (date(2026, 12, 1), Decimal("70.00"), True),  # 10 + 12 EUR × 5
    ]


# ---- export / import of the new fields ------------------------------------------------------


def test_new_fields_survive_json_and_csv(tmp_path, service, db):
    service.add(make_sub(name="Phone", payment_method="Card", contract_end_date=date(2027, 3, 1), notice_days=30,
                         paused_from=date(2026, 12, 1), paused_until=date(2026, 12, 31),
                         promo_price=Decimal("9.99"), promo_until=date(2026, 11, 30)))
    for name, export in (("b.json", "export_json"), ("b.csv", "export_csv")):
        path = tmp_path / name
        getattr(ExportService(service), export)(path)
        target_db = Database(":memory:")
        target = SubscriptionService(SubscriptionRepository(target_db), today=lambda: TODAY)
        ExportService(target).import_file(path)
        a, b = service.list_rows()[0].subscription, target.list_rows()[0].subscription
        a_fields = {k: v for k, v in vars(a).items() if k != "id"}
        assert a_fields == {k: v for k, v in vars(b).items() if k != "id"}
        target_db.close()


# ---- templates and badges -------------------------------------------------------------------


def test_templates():
    assert templates.find("  netflix ").category is Category.STREAMING
    assert templates.find("Microsoft 365").billing_cycle is BillingCycle.YEARLY
    assert templates.find("Something else") is None
    assert len(set(templates.names())) == len(templates.names())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_dialog_template_fills_category_and_cycle(qapp):
    from subtrack.ui.subscription_dialog import SubscriptionDialog

    dialog = SubscriptionDialog()
    dialog._apply_template("xbox game pass")
    sub = dialog.subscription()
    assert (sub.name, sub.category, sub.billing_cycle) == ("Xbox Game Pass", Category.GAMING, BillingCycle.MONTHLY)


def test_dialog_round_trips_new_fields(qapp):
    from subtrack.ui.subscription_dialog import SubscriptionDialog

    original = make_sub(id=5, payment_method="PayPal", contract_end_date=date(2027, 3, 1), notice_days=14,
                        paused_from=date(2026, 12, 1), paused_until=date(2026, 12, 31),
                        promo_price=Decimal("4.99"), promo_until=date(2026, 11, 30))
    dialog = SubscriptionDialog(None, original, payment_methods=["PayPal"])
    assert dialog.more_button.isChecked()
    assert dialog.subscription() == original


def test_badge_colour_is_stable(qapp):
    from subtrack.ui.badge import _initials, badge_colour, badge_icon

    assert badge_colour("Netflix") == badge_colour(" netflix ")
    assert (_initials("Netflix"), _initials("Xbox Game Pass"), _initials("iCloud+"), _initials("+")) == ("N", "XG", "I", "?")
    assert not badge_icon("Netflix").isNull()


# ---- online exchange rates -----------------------------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_online_rates_are_converted_to_ron():
    payload = {"amount": 1.0, "base": "EUR", "date": "2026-10-28", "rates": {"RON": 5.3508, "USD": 1.1133}}
    opener = lambda request, timeout: _Response(json.dumps(payload).encode())
    result = online_rates.fetch(opener)
    assert result.as_of == date(2026, 10, 28)
    assert result.rates_in_ron == {Currency.EUR: Decimal("5.3508"), Currency.USD: Decimal("4.8063")}


def test_online_rates_errors_are_user_facing():
    def offline(request, timeout):
        raise OSError("no network")

    with pytest.raises(online_rates.RatesUnavailable, match="Could not reach"):
        online_rates.fetch(offline)
    with pytest.raises(online_rates.RatesUnavailable, match="unexpected"):
        online_rates.parse({"base": "USD", "date": "2026-10-28", "rates": {}})


def test_applied_online_rates_are_remembered(db):
    currency = CurrencyService(SettingsRepository(db))
    assert currency.rates_updated_on() is None
    currency.apply_online_rates({Currency.EUR: Decimal("5.35")}, date(2026, 10, 28))
    assert currency.rate_in_ron(Currency.EUR) == Decimal("5.35")
    assert currency.rates_updated_on() == date(2026, 10, 28)
