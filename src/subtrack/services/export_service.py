"""Export / import of subscriptions as CSV (for spreadsheets) or JSON (for backups),
plus export of upcoming payments as a calendar file (.ics, export only).

Both formats contain every subscription, including cancelled ones. Imports are
all-or-nothing: every entry is parsed and validated before anything is saved,
and entries identical to an existing subscription are skipped, so importing the
same backup twice does not create duplicates.
"""

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from subtrack.domain.models import BillingCycle, Category, Currency, Subscription
from subtrack.services.calendar_export import build_calendar
from subtrack.services.subscription_service import SubscriptionService, ValidationError

FORMAT_VERSION = 1

FIELDS = [
    "name",
    "price",
    "currency",
    "billing_cycle",
    "first_payment_date",
    "category",
    "trial_end_date",
    "rarely_used",
    "active",
    "notes",
    "shared_with",
    "payment_method",
    "contract_end_date",
    "notice_days",
    "paused_from",
    "paused_until",
    "promo_price",
    "promo_until",
]
# Written to CSV for convenience; ignored on import because it is always computed.
CSV_EXTRA_FIELDS = ["next_payment_date"]


class ImportFailed(ValueError):
    """The file could not be imported. The message is user-facing."""


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped_duplicates: int


def _to_record(sub: Subscription) -> dict:
    return {
        "name": sub.name,
        "price": str(sub.price),
        "currency": sub.currency.value,
        "billing_cycle": sub.billing_cycle.value,
        "first_payment_date": sub.first_payment_date.isoformat(),
        "category": sub.category.value,
        "trial_end_date": sub.trial_end_date.isoformat() if sub.trial_end_date else "",
        "rarely_used": sub.rarely_used,
        "active": sub.active,
        "notes": sub.notes,
        "shared_with": sub.shared_with,
        "payment_method": sub.payment_method,
        "contract_end_date": _iso(sub.contract_end_date),
        "notice_days": sub.notice_days,
        "paused_from": _iso(sub.paused_from),
        "paused_until": _iso(sub.paused_until),
        "promo_price": str(sub.promo_price) if sub.promo_price is not None else "",
        "promo_until": _iso(sub.promo_until),
    }


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def _optional_date(record: dict, field: str) -> date | None:
    text = str(record.get(field) or "").strip()
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        raise ValueError(f"{field} '{text}' is not a date (YYYY-MM-DD)") from None


def _whole_number(record: dict, field: str, default: int) -> int:
    """Fields added in later versions are missing from older files; they get the default."""
    text = str(record.get(field) if record.get(field) is not None else "").strip()
    if not text:
        return default
    if not text.isdigit():
        raise ValueError(f"{field} '{text}' is not a whole number")
    return int(text)


def _parse_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "":
        return default
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"'{value}' is not yes/no")


def _parse_enum(enum_type, value):
    text = str(value).strip()
    for member in enum_type:
        if text.lower() == member.value.lower():
            return member
    allowed = ", ".join(m.value for m in enum_type)
    raise ValueError(f"'{value}' is not one of: {allowed}")


def _from_record(record: dict) -> Subscription:
    """Build a Subscription from a CSV row or JSON object. Raises ValueError on bad data."""
    missing = [f for f in ("name", "price", "currency", "billing_cycle", "first_payment_date") if not str(record.get(f) or "").strip()]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    try:
        price = Decimal(str(record["price"]).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"price '{record['price']}' is not a number") from None
    trial = str(record.get("trial_end_date") or "").strip()
    promo_text = str(record.get("promo_price") or "").strip()
    try:
        promo_price = Decimal(promo_text.replace(",", ".")) if promo_text else None
    except InvalidOperation:
        raise ValueError(f"promo_price '{promo_text}' is not a number") from None
    return Subscription(
        name=str(record["name"]),
        price=price,
        currency=_parse_enum(Currency, record["currency"]),
        billing_cycle=_parse_enum(BillingCycle, record["billing_cycle"]),
        first_payment_date=date.fromisoformat(str(record["first_payment_date"]).strip()),
        category=_parse_enum(Category, record.get("category") or Category.OTHER.value),
        trial_end_date=date.fromisoformat(trial) if trial else None,
        rarely_used=_parse_bool(record.get("rarely_used", ""), default=False),
        active=_parse_bool(record.get("active", ""), default=True),
        notes=str(record.get("notes") or ""),
        shared_with=_whole_number(record, "shared_with", 1),
        payment_method=str(record.get("payment_method") or ""),
        contract_end_date=_optional_date(record, "contract_end_date"),
        notice_days=_whole_number(record, "notice_days", 0),
        paused_from=_optional_date(record, "paused_from"),
        paused_until=_optional_date(record, "paused_until"),
        promo_price=promo_price,
        promo_until=_optional_date(record, "promo_until"),
    )


def _identity(sub: Subscription) -> tuple:
    """What makes two subscriptions 'the same' when importing."""
    return (sub.name.strip().lower(), sub.price, sub.currency, sub.billing_cycle, sub.first_payment_date)


class ExportService:
    def __init__(self, subscriptions: SubscriptionService):
        self._subscriptions = subscriptions

    # ---- export ---------------------------------------------------------

    def export_csv(self, path: Path) -> int:
        rows = self._subscriptions.list_rows(include_inactive=True)
        # utf-8-sig so Excel shows diacritics (ă, ș, ț) correctly
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS + CSV_EXTRA_FIELDS)
            writer.writeheader()
            for row in rows:
                record = _to_record(row.subscription)
                record["rarely_used"] = "yes" if record["rarely_used"] else "no"
                record["active"] = "yes" if record["active"] else "no"
                record["next_payment_date"] = row.next_payment.isoformat()
                writer.writerow(record)
        return len(rows)

    def export_json(self, path: Path) -> int:
        rows = self._subscriptions.list_rows(include_inactive=True)
        document = {
            "app": "SubTrack",
            "format_version": FORMAT_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "subscriptions": [_to_record(row.subscription) for row in rows],
        }
        with open(path, "w", encoding="utf-8") as file:
            json.dump(document, file, ensure_ascii=False, indent=2)
        return len(rows)

    def export_ics(self, path: Path, today: date | None = None, months: int = 12) -> int:
        """Calendar file with every payment of active subscriptions in the next `months`.

        Returns the number of payment events written.
        """
        active = [row.subscription for row in self._subscriptions.list_rows()]
        text, count = build_calendar(active, today or date.today(), months)
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        return count

    # ---- import ---------------------------------------------------------

    def import_file(self, path: Path) -> ImportResult:
        """Import a .csv or .json file, chosen by extension."""
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return self.import_csv(path)
        if suffix == ".json":
            return self.import_json(path)
        raise ImportFailed("Only .csv and .json files can be imported.")

    def import_csv(self, path: Path) -> ImportResult:
        try:
            with open(path, newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                records = list(reader)
        except (OSError, UnicodeDecodeError, csv.Error) as error:
            raise ImportFailed(f"Could not read the CSV file: {error}") from None
        # Row 1 is the header, so data starts at row 2.
        return self._import_records(records, first_label=2, label="Row")

    def import_json(self, path: Path) -> ImportResult:
        try:
            with open(path, encoding="utf-8") as file:
                document = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImportFailed(f"Could not read the JSON file: {error}") from None
        if not isinstance(document, dict) or not isinstance(document.get("subscriptions"), list):
            raise ImportFailed("This is not a SubTrack backup (no 'subscriptions' list).")
        if document.get("format_version", FORMAT_VERSION) > FORMAT_VERSION:
            raise ImportFailed("This backup was made by a newer version of SubTrack.")
        records = document["subscriptions"]
        if not all(isinstance(r, dict) for r in records):
            raise ImportFailed("Every entry in 'subscriptions' must be an object.")
        return self._import_records(records, first_label=1, label="Entry")

    def _import_records(self, records: list[dict], first_label: int, label: str) -> ImportResult:
        parsed: list[Subscription] = []
        for number, record in enumerate(records, start=first_label):
            try:
                sub = _from_record(record)
                self._subscriptions.validate(sub)
            except (ValueError, ValidationError) as error:
                raise ImportFailed(f"{label} {number}: {error}") from None
            parsed.append(sub)

        seen = {_identity(row.subscription) for row in self._subscriptions.list_rows(include_inactive=True)}
        imported = skipped = 0
        for sub in parsed:
            key = _identity(sub)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            self._subscriptions.add(sub)
            imported += 1
        return ImportResult(imported, skipped)
