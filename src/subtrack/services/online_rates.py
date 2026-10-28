"""Optional: fetch current exchange rates from the European Central Bank.

Uses the free Frankfurter API (https://frankfurter.dev, no key, ECB reference
rates, updated on working days). Only called when the user clicks "Update rates
online" in Settings; SubTrack never goes online on its own.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from subtrack import __version__
from subtrack.domain.models import Currency

API_URL = "https://api.frankfurter.dev/v1/latest?base=EUR&symbols={symbols}"
TIMEOUT_SECONDS = 10


class RatesUnavailable(Exception):
    """The rates could not be fetched. The message is user-facing."""


@dataclass(frozen=True)
class OnlineRates:
    rates_in_ron: dict[Currency, Decimal]  # 1 unit of the currency = x RON
    as_of: date


def parse(payload: dict) -> OnlineRates:
    """Turn {'base': 'EUR', 'date': ..., 'rates': {'RON': 5.35, 'USD': 1.11}} into rates in RON."""
    try:
        if payload["base"] != "EUR":
            raise ValueError("unexpected base currency")
        per_eur = {code: Decimal(str(value)) for code, value in payload["rates"].items()}
        ron_per_eur = per_eur["RON"]
        rates = {}
        for currency in Currency:
            if currency is Currency.RON:
                continue
            if currency is Currency.EUR:
                rates[currency] = ron_per_eur
            else:
                rates[currency] = (ron_per_eur / per_eur[currency.value]).quantize(Decimal("0.0001"))
        return OnlineRates(rates, date.fromisoformat(payload["date"]))
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise RatesUnavailable(f"The rates service sent something unexpected ({error}).") from None


def fetch(opener=urllib.request.urlopen) -> OnlineRates:
    symbols = ",".join(c.value for c in Currency if c is not Currency.EUR)
    request = urllib.request.Request(
        API_URL.format(symbols=symbols), headers={"User-Agent": f"SubTrack/{__version__}"}
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            return parse(json.load(response))
    except RatesUnavailable:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RatesUnavailable(f"Could not reach the rates service: {error}") from None
