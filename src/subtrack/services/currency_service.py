"""Converts amounts to the user's base currency using manual exchange rates.

Rates are stored in RON (rate_EUR = 4.97 means 1 EUR = 4.97 RON), so the base
currency can be changed without re-entering rates.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from subtrack.data.settings_repository import SettingsRepository
from subtrack.domain.models import Currency

_CENT = Decimal("0.01")


class CurrencyService:
    def __init__(self, settings: SettingsRepository):
        self._settings = settings

    def base_currency(self) -> Currency:
        return Currency(self._settings.get("base_currency", Currency.RON.value))

    def set_base_currency(self, currency: Currency) -> None:
        self._settings.set("base_currency", currency.value)

    def rate_in_ron(self, currency: Currency) -> Decimal:
        if currency is Currency.RON:
            return Decimal(1)
        return Decimal(self._settings.get(f"rate_{currency.value}", "1"))

    def set_rate_in_ron(self, currency: Currency, rate: Decimal) -> None:
        if currency is Currency.RON:
            raise ValueError("RON is the reference currency; its rate is always 1")
        if rate <= 0:
            raise ValueError("Exchange rate must be positive")
        self._settings.set(f"rate_{currency.value}", str(rate))

    def apply_online_rates(self, rates: dict[Currency, Decimal], as_of: date) -> None:
        for currency, rate in rates.items():
            self.set_rate_in_ron(currency, rate)
        self._settings.set("rates_updated_on", as_of.isoformat())

    def rates_updated_on(self) -> date | None:
        """Date of the last online update, or None if the rates were only ever typed in."""
        value = self._settings.get("rates_updated_on")
        return date.fromisoformat(value) if value else None

    def convert(self, amount: Decimal, source: Currency, target: Currency) -> Decimal:
        if source is target:
            return amount
        return (amount * self.rate_in_ron(source) / self.rate_in_ron(target)).quantize(
            _CENT, ROUND_HALF_UP
        )

    def to_base(self, amount: Decimal, currency: Currency) -> Decimal:
        return self.convert(amount, currency, self.base_currency())
