"""Maps Subscription objects to and from the subscriptions table (and their price history)."""

# Annotations are evaluated lazily: the class has a method named `list`, which would
# otherwise shadow the built-in in its own type hints.
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from subtrack.data.database import Database
from subtrack.domain.models import BillingCycle, Category, Currency, PriceChange, Subscription

_COLUMNS = (
    "name, price, currency, billing_cycle, first_payment_date, category, "
    "trial_end_date, rarely_used, active, notes, shared_with, payment_method, "
    "contract_end_date, notice_days, paused_from, paused_until, promo_price, promo_until"
)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _to_row(sub: Subscription) -> tuple:
    return (
        sub.name,
        str(sub.price),
        sub.currency.value,
        sub.billing_cycle.value,
        sub.first_payment_date.isoformat(),
        sub.category.value,
        sub.trial_end_date.isoformat() if sub.trial_end_date else None,
        int(sub.rarely_used),
        int(sub.active),
        sub.notes,
        sub.shared_with,
        sub.payment_method,
        _iso(sub.contract_end_date),
        sub.notice_days,
        _iso(sub.paused_from),
        _iso(sub.paused_until),
        str(sub.promo_price) if sub.promo_price is not None else None,
        _iso(sub.promo_until),
    )


def _from_row(row: sqlite3.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        name=row["name"],
        price=Decimal(row["price"]),
        currency=Currency(row["currency"]),
        billing_cycle=BillingCycle(row["billing_cycle"]),
        first_payment_date=date.fromisoformat(row["first_payment_date"]),
        category=Category(row["category"]),
        trial_end_date=date.fromisoformat(row["trial_end_date"]) if row["trial_end_date"] else None,
        rarely_used=bool(row["rarely_used"]),
        active=bool(row["active"]),
        notes=row["notes"],
        shared_with=row["shared_with"],
        payment_method=row["payment_method"],
        contract_end_date=_date(row["contract_end_date"]),
        notice_days=row["notice_days"],
        paused_from=_date(row["paused_from"]),
        paused_until=_date(row["paused_until"]),
        promo_price=Decimal(row["promo_price"]) if row["promo_price"] is not None else None,
        promo_until=_date(row["promo_until"]),
    )


class SubscriptionRepository:
    def __init__(self, db: Database):
        self._conn = db.connection

    def list(self, include_inactive: bool = False) -> list[Subscription]:
        sql = "SELECT * FROM subscriptions"
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY name COLLATE NOCASE"
        return [_from_row(row) for row in self._conn.execute(sql)]

    def get(self, sub_id: int) -> Subscription | None:
        row = self._conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return _from_row(row) if row else None

    def insert(self, sub: Subscription) -> Subscription:
        """Insert and return the subscription with its new id set."""
        with self._conn:
            cursor = self._conn.execute(
                f"INSERT INTO subscriptions ({_COLUMNS}) VALUES ({', '.join('?' * len(_COLUMNS.split(',')))})",
                _to_row(sub),
            )
        sub.id = cursor.lastrowid
        return sub

    def update(self, sub: Subscription) -> None:
        if sub.id is None:
            raise ValueError("Cannot update a subscription that has no id")
        assignments = ", ".join(f"{col.strip()} = ?" for col in _COLUMNS.split(","))
        with self._conn:
            self._conn.execute(
                f"UPDATE subscriptions SET {assignments} WHERE id = ?",
                (*_to_row(sub), sub.id),
            )

    def delete(self, sub_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

    def payment_methods(self) -> list[str]:
        """Distinct non-empty payment methods, for the filter and the dialog's suggestions."""
        rows = self._conn.execute(
            "SELECT DISTINCT payment_method FROM subscriptions WHERE payment_method != '' "
            "ORDER BY payment_method COLLATE NOCASE"
        )
        return [row[0] for row in rows]

    # ---- price history ------------------------------------------------------

    def add_price_change(self, sub_id: int, change: PriceChange) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO price_changes "
                "(subscription_id, changed_on, old_price, old_currency, new_price, new_currency) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sub_id,
                    change.changed_on.isoformat(),
                    str(change.old_price),
                    change.old_currency.value,
                    str(change.new_price),
                    change.new_currency.value,
                ),
            )

    def price_changes(self, sub_id: int | None = None) -> dict[int, list[PriceChange]]:
        """subscription id -> its price changes, oldest first."""
        sql = "SELECT * FROM price_changes"
        params: tuple = ()
        if sub_id is not None:
            sql += " WHERE subscription_id = ?"
            params = (sub_id,)
        result: dict[int, list[PriceChange]] = {}
        for row in self._conn.execute(sql + " ORDER BY changed_on, id", params):
            result.setdefault(row["subscription_id"], []).append(
                PriceChange(
                    changed_on=date.fromisoformat(row["changed_on"]),
                    old_price=Decimal(row["old_price"]),
                    old_currency=Currency(row["old_currency"]),
                    new_price=Decimal(row["new_price"]),
                    new_currency=Currency(row["new_currency"]),
                )
            )
        return result
