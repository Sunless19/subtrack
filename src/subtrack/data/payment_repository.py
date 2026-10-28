"""Payments the user marked as paid (one row per subscription and due date)."""

from datetime import date, datetime

from subtrack.data.database import Database


class PaymentRepository:
    def __init__(self, db: Database):
        self._conn = db.connection

    def paid(self) -> dict[tuple[int, date], datetime]:
        """(subscription_id, due_date) -> when it was marked paid."""
        rows = self._conn.execute("SELECT subscription_id, due_date, paid_at FROM payments")
        return {
            (row["subscription_id"], date.fromisoformat(row["due_date"])): datetime.fromisoformat(row["paid_at"])
            for row in rows
        }

    def mark_paid(self, subscription_id: int, due_date: date, paid_at: datetime) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO payments (subscription_id, due_date, paid_at) VALUES (?, ?, ?)",
                (subscription_id, due_date.isoformat(), paid_at.isoformat(timespec="seconds")),
            )

    def unmark_paid(self, subscription_id: int, due_date: date) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM payments WHERE subscription_id = ? AND due_date = ?",
                (subscription_id, due_date.isoformat()),
            )
