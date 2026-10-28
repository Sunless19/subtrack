"""SQLite connection and schema migrations.

Each migration is a SQL script. The number of applied migrations is stored in
PRAGMA user_version, so adding a new entry to MIGRATIONS upgrades existing
databases on the next start.
"""

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1 - initial schema
    """
    CREATE TABLE subscriptions (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        name               TEXT    NOT NULL,
        price              TEXT    NOT NULL,
        currency           TEXT    NOT NULL,
        billing_cycle      TEXT    NOT NULL,
        first_payment_date TEXT    NOT NULL,
        category           TEXT    NOT NULL,
        trial_end_date     TEXT,
        rarely_used        INTEGER NOT NULL DEFAULT 0,
        active             INTEGER NOT NULL DEFAULT 1,
        notes              TEXT    NOT NULL DEFAULT ''
    );

    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    INSERT INTO settings (key, value) VALUES
        ('base_currency', 'RON'),
        ('reminder_days_before', '3'),
        ('rate_EUR', '4.97'),
        ('rate_USD', '4.60'),
        ('start_with_windows', '0');
    """,
    # 2 - remember which reminders were already shown, so each appears once
    """
    CREATE TABLE shown_reminders (
        subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
        kind            TEXT    NOT NULL,
        due_date        TEXT    NOT NULL,
        PRIMARY KEY (subscription_id, kind, due_date)
    );
    """,
    # 3 - snoozing reminders and marking payments as paid
    """
    ALTER TABLE shown_reminders ADD COLUMN shown_at TEXT;
    ALTER TABLE shown_reminders ADD COLUMN snoozed_until TEXT;
    -- Rows from v0.1 were shown but have no time; use their due date so they are not shown again.
    UPDATE shown_reminders SET shown_at = due_date || 'T00:00:00';

    CREATE TABLE payments (
        subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
        due_date        TEXT    NOT NULL,
        paid_at         TEXT    NOT NULL,
        PRIMARY KEY (subscription_id, due_date)
    );
    """,
    # 4 - shared subscriptions and price history
    """
    ALTER TABLE subscriptions ADD COLUMN shared_with INTEGER NOT NULL DEFAULT 1;

    CREATE TABLE price_changes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
        changed_on      TEXT    NOT NULL,
        old_price       TEXT    NOT NULL,
        old_currency    TEXT    NOT NULL,
        new_price       TEXT    NOT NULL,
        new_currency    TEXT    NOT NULL
    );
    """,
    # 5 - payment method, contract end / notice period, pause, introductory price
    """
    ALTER TABLE subscriptions ADD COLUMN payment_method    TEXT    NOT NULL DEFAULT '';
    ALTER TABLE subscriptions ADD COLUMN contract_end_date TEXT;
    ALTER TABLE subscriptions ADD COLUMN notice_days       INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE subscriptions ADD COLUMN paused_from       TEXT;
    ALTER TABLE subscriptions ADD COLUMN paused_until      TEXT;
    ALTER TABLE subscriptions ADD COLUMN promo_price       TEXT;
    ALTER TABLE subscriptions ADD COLUMN promo_until       TEXT;
    """,
]


class Database:
    def __init__(self, path: Path | str):
        """Open the database at path (":memory:" works for tests) and migrate it."""
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    @property
    def schema_version(self) -> int:
        return self.connection.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        for version in range(self.schema_version, len(MIGRATIONS)):
            with self.connection:
                self.connection.executescript(MIGRATIONS[version])
                self.connection.execute(f"PRAGMA user_version = {version + 1}")

    def close(self) -> None:
        self.connection.close()
