"""Tracks which reminders were shown and which are snoozed."""

from dataclasses import dataclass
from datetime import date, datetime

from subtrack.data.database import Database


@dataclass(frozen=True)
class ReminderState:
    shown_at: datetime | None
    snoozed_until: datetime | None


ReminderKey = tuple[int, str, date]  # (subscription_id, kind, due_date)


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ReminderRepository:
    def __init__(self, db: Database):
        self._conn = db.connection

    def all_states(self) -> dict[ReminderKey, ReminderState]:
        rows = self._conn.execute(
            "SELECT subscription_id, kind, due_date, shown_at, snoozed_until FROM shown_reminders"
        )
        return {
            (row["subscription_id"], row["kind"], date.fromisoformat(row["due_date"])): ReminderState(
                _parse(row["shown_at"]), _parse(row["snoozed_until"])
            )
            for row in rows
        }

    def mark_shown(self, subscription_id: int, kind: str, due_date: date, shown_at: datetime) -> None:
        """Record that the reminder was shown. Clears any snooze, since it has now fired."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO shown_reminders (subscription_id, kind, due_date, shown_at, snoozed_until) "
                "VALUES (?, ?, ?, ?, NULL) "
                "ON CONFLICT DO UPDATE SET shown_at = excluded.shown_at, snoozed_until = NULL",
                (subscription_id, kind, due_date.isoformat(), shown_at.isoformat(timespec="seconds")),
            )

    def snooze(self, subscription_id: int, kind: str, due_date: date, until: datetime) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO shown_reminders (subscription_id, kind, due_date, snoozed_until) VALUES (?, ?, ?, ?) "
                "ON CONFLICT DO UPDATE SET snoozed_until = excluded.snoozed_until",
                (subscription_id, kind, due_date.isoformat(), until.isoformat(timespec="seconds")),
            )
