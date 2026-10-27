"""Tracks which reminders have already been shown to the user."""

from datetime import date

from subtrack.data.database import Database


class ReminderRepository:
    def __init__(self, db: Database):
        self._conn = db.connection

    def was_shown(self, subscription_id: int, kind: str, due_date: date) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM shown_reminders WHERE subscription_id = ? AND kind = ? AND due_date = ?",
            (subscription_id, kind, due_date.isoformat()),
        ).fetchone()
        return row is not None

    def mark_shown(self, subscription_id: int, kind: str, due_date: date) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO shown_reminders (subscription_id, kind, due_date) VALUES (?, ?, ?)",
                (subscription_id, kind, due_date.isoformat()),
            )
