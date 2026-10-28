"""Shared costs, price history, calendar export, and search / filter / sort of the list."""

import json
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from conftest import make_sub
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import BillingCycle, Category, Currency
from subtrack.services.calendar_export import _fold, build_calendar
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService
from subtrack.services.reminder_service import Reminder, ReminderKind
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService, ValidationError
from subtrack.ui.subscription_table_model import SubscriptionFilterModel, SubscriptionTableModel

TODAY = date(2026, 10, 28)


@pytest.fixture
def service(db):
    return SubscriptionService(SubscriptionRepository(db), today=lambda: TODAY)


# ---- shared subscriptions ---------------------------------------------------


def test_shared_costs_use_my_share():
    family = make_sub(price="60", shared_with=4)
    assert family.my_share == Decimal("15.00")
    assert billing.monthly_cost(family) == Decimal("15.00")
    assert billing.yearly_cost(family) == Decimal("180.00")
    yearly = make_sub(price="100", cycle=BillingCycle.YEARLY, shared_with=3)
    assert billing.monthly_cost(yearly) == Decimal("2.78")


def test_totals_and_upcoming_use_my_share(db, service):
    service.add(make_sub(name="Family plan", price="60", shared_with=4, first=date(2026, 1, 30)))
    service.add(make_sub(name="Solo", price="10", first=date(2026, 1, 30)))
    stats = StatsService(SubscriptionRepository(db), CurrencyService(SettingsRepository(db)))
    assert stats.monthly_total() == Decimal("25.00")
    assert [p.amount_in_base for p in stats.upcoming_payments(TODAY, 5)] == [Decimal("15.00"), Decimal("10.00")]


@pytest.mark.parametrize("people", [0, 51])
def test_shared_with_is_validated(service, people):
    with pytest.raises(ValidationError, match="1 to 50"):
        service.add(make_sub(shared_with=people))


def test_reminder_mentions_my_share():
    sub = make_sub(name="Family", price="60", shared_with=3)
    message = Reminder(ReminderKind.PAYMENT_DUE, sub, TODAY).message(TODAY)
    assert message == "60.00 RON will be charged today. Your share: 20.00 RON."


def test_shared_with_survives_export_and_old_files_import(tmp_path, service, db):
    service.add(make_sub(name="Family", shared_with=5))
    path = tmp_path / "backup.json"
    ExportService(service).export_json(path)
    assert json.loads(path.read_text(encoding="utf-8"))["subscriptions"][0]["shared_with"] == 5

    old_file = tmp_path / "v01.csv"  # no shared_with column, like files from v0.1
    old_file.write_text("name,price,currency,billing_cycle,first_payment_date\nGym,100,RON,monthly,2026-01-01\n")
    ExportService(service).import_file(old_file)
    gym = next(r.subscription for r in service.list_rows() if r.subscription.name == "Gym")
    assert gym.shared_with == 1


# ---- price history ------------------------------------------------------------


def test_price_change_is_recorded(service):
    sub = service.add(make_sub(price="39.99"))
    sub.notes = "only notes changed"
    service.update(sub)
    assert service.price_history(sub.id) == []

    sub.price = Decimal("49.99")
    service.update(sub)
    history = service.price_history(sub.id)
    assert [(h.changed_on, h.old_price, h.new_price) for h in history] == [
        (TODAY, Decimal("39.99"), Decimal("49.99"))
    ]
    row = service.list_rows()[0]
    assert row.price_change_percent == Decimal("25.0")


def test_percent_is_since_first_price(service):
    sub = service.add(make_sub(price="10"))
    for price in ("12", "15"):
        sub.price = Decimal(price)
        service.update(sub)
    assert service.list_rows()[0].price_change_percent == Decimal("50.0")


def test_currency_change_has_no_percent(service):
    sub = service.add(make_sub(price="10", currency=Currency.EUR))
    sub.price, sub.currency = Decimal("50"), Currency.RON
    service.update(sub)
    row = service.list_rows()[0]
    assert len(row.price_history) == 1 and row.price_change_percent is None


def test_price_history_is_deleted_with_subscription(db, service):
    sub = service.add(make_sub(price="10"))
    sub.price = Decimal("11")
    service.update(sub)
    service.delete(sub.id)
    assert db.connection.execute("SELECT COUNT(*) FROM price_changes").fetchone()[0] == 0


# ---- calendar export ----------------------------------------------------------


def test_calendar_has_one_event_per_payment():
    monthly = make_sub(name="Netflix", price="49.99", first=date(2026, 1, 31), id=1)
    yearly = make_sub(name="Domain", cycle=BillingCycle.YEARLY, first=date(2025, 3, 1), id=2)
    text, count = build_calendar([monthly, yearly], TODAY)
    assert count == 12 + 1
    assert "DTSTART;VALUE=DATE:20261031" in text
    assert "DTSTART;VALUE=DATE:20270228" in text  # 31st clamped to end of February
    assert "UID:subtrack-1-20261031@subtrack.local" in text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")


def test_calendar_skips_trial_payments():
    trial = make_sub(first=date(2026, 10, 1), trial_end_date=date(2026, 12, 15), id=3)
    text, _ = build_calendar([trial], TODAY, months=3)
    assert "DTSTART;VALUE=DATE:20261101" not in text
    assert "DTSTART;VALUE=DATE:20270101" in text


def test_calendar_text_is_escaped_and_folded():
    sub = make_sub(name="Ăăș; test, \\ name", notes="line one\nline two " + "x" * 120, id=4)
    text, _ = build_calendar([sub], TODAY, months=1)
    assert "SUMMARY:Ăăș\\; test\\, \\\\ name" in text.replace("\r\n ", "")
    assert "line one\\nline two" in text.replace("\r\n ", "")
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))


def test_fold_never_splits_a_multibyte_character():
    folded = _fold("SUMMARY:" + "ș" * 100)
    for line in folded.split("\r\n"):
        line.encode("utf-8").decode("utf-8")  # would raise if a character was cut
        assert len(line.encode("utf-8")) <= 75


def test_export_ics_excludes_cancelled(tmp_path, service):
    service.add(make_sub(name="Active"))
    old = service.add(make_sub(name="Old"))
    service.cancel(old.id)
    path = tmp_path / "payments.ics"
    count = ExportService(service).export_ics(path, today=TODAY)
    text = path.read_text(encoding="utf-8")
    assert count == 12 and "Active" in text and "Old" not in text


# ---- search, filter and sort ---------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def table(qapp, db, service):
    currency = CurrencyService(SettingsRepository(db))
    currency.set_rate_in_ron(Currency.EUR, Decimal("5"))
    service.add(make_sub(name="Netflix", price="50", category=Category.STREAMING, notes="family"))
    service.add(make_sub(name="Spotify", price="25", category=Category.MUSIC))
    service.add(make_sub(name="Game Pass", price="15", currency=Currency.EUR, category=Category.GAMING))
    old = service.add(make_sub(name="Old Gym", price="100", category=Category.FITNESS))
    service.cancel(old.id)
    model = SubscriptionTableModel(currency.to_base)
    model.set_rows(service.list_rows(include_inactive=True))
    proxy = SubscriptionFilterModel()
    proxy.setSourceModel(model)
    return proxy


def names(proxy):
    return [proxy.data(proxy.index(r, 0)).split("  (")[0] for r in range(proxy.rowCount())]


def test_cancelled_hidden_until_shown(table):
    assert "Old Gym" not in names(table)
    table.set_show_cancelled(True)
    assert "Old Gym" in names(table)


def test_search_matches_name_category_and_notes(table):
    table.set_search_text("spot")
    assert names(table) == ["Spotify"]
    table.set_search_text("FAMILY")  # in Netflix's notes
    assert names(table) == ["Netflix"]
    table.set_search_text("gaming pass")  # every word must match somewhere
    assert names(table) == ["Game Pass"]


def test_category_filter(table):
    table.set_category(Category.MUSIC)
    assert names(table) == ["Spotify"]


def test_sort_by_monthly_cost_converts_currencies(table):
    table.sort(4, Qt.DescendingOrder)  # Per month: 75 RON (15 EUR), 50, 25
    assert names(table) == ["Game Pass", "Netflix", "Spotify"]
