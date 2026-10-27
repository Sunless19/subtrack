"""Maps Subscription objects to and from the subscriptions table."""

import sqlite3
from datetime import date
from decimal import Decimal

from subtrack.data.database import Database
from subtrack.domain.models import BillingCycle, Category, Currency, Subscription

_COLUMNS = (
    "name, price, currency, billing_cycle, first_payment_date, category, "
    "trial_end_date, rarely_used, active, notes"
)


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
                f"INSERT INTO subscriptions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
