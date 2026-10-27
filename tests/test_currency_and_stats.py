from datetime import date
from decimal import Decimal

import pytest

from conftest import make_sub
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain.models import BillingCycle, Category, Currency
from subtrack.services.currency_service import CurrencyService
from subtrack.services.stats_service import StatsService

TODAY = date(2026, 10, 27)


@pytest.fixture
def settings(db):
    return SettingsRepository(db)


@pytest.fixture
def currency(settings):
    service = CurrencyService(settings)
    service.set_rate_in_ron(Currency.EUR, Decimal("5"))
    service.set_rate_in_ron(Currency.USD, Decimal("4"))
    return service


@pytest.fixture
def repo(db):
    return SubscriptionRepository(db)


def test_settings_get_set_and_defaults(settings):
    assert settings.get("base_currency") == "RON"
    assert settings.get("missing", "fallback") == "fallback"
    settings.set("reminder_days_before", "7")
    settings.set("new_key", "x")
    assert settings.get("reminder_days_before") == "7"
    assert settings.get("new_key") == "x"


def test_convert_between_any_currencies(currency):
    assert currency.to_base(Decimal("10"), Currency.EUR) == Decimal("50.00")
    assert currency.convert(Decimal("10"), Currency.EUR, Currency.USD) == Decimal("12.50")
    currency.set_base_currency(Currency.EUR)
    assert currency.to_base(Decimal("50"), Currency.RON) == Decimal("10.00")
    assert currency.to_base(Decimal("7.30"), Currency.EUR) == Decimal("7.30")


def test_rate_must_be_positive(currency):
    with pytest.raises(ValueError):
        currency.set_rate_in_ron(Currency.EUR, Decimal("0"))


def test_totals_in_base_currency(repo, currency):
    repo.insert(make_sub(price="20"))                                            # 20 RON / month
    repo.insert(make_sub(name="Cloud", price="120", cycle=BillingCycle.YEARLY))  # 10 RON / month
    repo.insert(make_sub(name="Game Pass", price="3", currency=Currency.EUR,
                         category=Category.GAMING))                             # 15 RON / month
    repo.insert(make_sub(name="Old", price="999", active=False))                 # ignored
    stats = StatsService(repo, currency)

    assert stats.monthly_total() == Decimal("45.00")
    assert stats.yearly_total() == Decimal("540.00")
    assert stats.monthly_total_by_category() == {
        Category.MUSIC: Decimal("30.00"),
        Category.GAMING: Decimal("15.00"),
    }


def test_upcoming_payments_lists_every_occurrence_sorted(repo, currency):
    repo.insert(make_sub(name="Weekly", price="1", cycle=BillingCycle.WEEKLY, first=date(2026, 10, 1)))
    repo.insert(make_sub(name="Monthly", price="2", currency=Currency.EUR, first=date(2026, 1, 5)))
    repo.insert(make_sub(name="Far", cycle=BillingCycle.YEARLY, first=date(2026, 6, 1)))
    stats = StatsService(repo, currency)

    upcoming = stats.upcoming_payments(TODAY, days=14)
    assert [(p.due_date, p.subscription.name) for p in upcoming] == [
        (date(2026, 10, 29), "Weekly"),
        (date(2026, 11, 5), "Monthly"),
        (date(2026, 11, 5), "Weekly"),
    ]
    assert upcoming[1].amount_in_base == Decimal("10.00")
