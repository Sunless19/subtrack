import csv
import json
from datetime import date
from decimal import Decimal

import pytest

from conftest import make_sub
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain.models import BillingCycle, Category, Currency
from subtrack.services.export_service import ExportService, ImportFailed
from subtrack.services.subscription_service import SubscriptionService

TODAY = date(2026, 10, 27)


def make_service(db):
    return SubscriptionService(SubscriptionRepository(db), today=lambda: TODAY)


@pytest.fixture
def subscriptions(db):
    return make_service(db)


@pytest.fixture
def exporter(subscriptions):
    return ExportService(subscriptions)


@pytest.fixture
def other_db():
    from subtrack.data.database import Database

    database = Database(":memory:")
    yield database
    database.close()


def fill(subscriptions):
    subscriptions.add(make_sub(name="Spotify Familie ăîșț", notes='has "quotes", commas'))
    subscriptions.add(make_sub(name="Cloud", price="99.99", currency=Currency.EUR, cycle=BillingCycle.YEARLY,
                               category=Category.CLOUD, trial_end_date=date(2026, 11, 1), rarely_used=True))
    old = subscriptions.add(make_sub(name="Old gym", category=Category.FITNESS))
    subscriptions.cancel(old.id)


def comparable(subscriptions):
    return sorted(
        (s.name, s.price, s.currency, s.billing_cycle, s.first_payment_date, s.category,
         s.trial_end_date, s.rarely_used, s.active, s.notes)
        for s in (row.subscription for row in subscriptions.list_rows(include_inactive=True))
    )


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_round_trip_keeps_everything(tmp_path, subscriptions, exporter, other_db, suffix):
    fill(subscriptions)
    path = tmp_path / f"backup{suffix}"
    count = (exporter.export_csv if suffix == ".csv" else exporter.export_json)(path)
    assert count == 3

    target = make_service(other_db)
    result = ExportService(target).import_file(path)
    assert result.imported == 3 and result.skipped_duplicates == 0
    assert comparable(target) == comparable(subscriptions)


def test_reimporting_skips_duplicates(tmp_path, subscriptions, exporter):
    fill(subscriptions)
    path = tmp_path / "backup.json"
    exporter.export_json(path)
    result = exporter.import_file(path)
    assert (result.imported, result.skipped_duplicates) == (0, 3)


def test_csv_has_next_payment_and_opens_in_excel(tmp_path, subscriptions, exporter):
    subscriptions.add(make_sub(first=date(2026, 1, 10)))
    path = tmp_path / "out.csv"
    exporter.export_csv(path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    with open(path, encoding="utf-8-sig", newline="") as file:
        row = next(csv.DictReader(file))
    assert row["next_payment_date"] == "2026-11-10"
    assert row["active"] == "yes"


def test_hand_written_csv_is_forgiving(tmp_path, subscriptions, exporter):
    path = tmp_path / "manual.csv"
    path.write_text(
        "name,price,currency,billing_cycle,first_payment_date\n"
        "Netflix,\"49,99\",ron,Monthly,2026-03-05\n",
        encoding="utf-8",
    )
    assert exporter.import_file(path).imported == 1
    sub = subscriptions.list_rows()[0].subscription
    assert (sub.price, sub.currency, sub.billing_cycle, sub.category, sub.active) == (
        Decimal("49.99"), Currency.RON, BillingCycle.MONTHLY, Category.OTHER, True,
    )


def test_bad_row_imports_nothing(tmp_path, subscriptions, exporter):
    path = tmp_path / "bad.csv"
    path.write_text(
        "name,price,currency,billing_cycle,first_payment_date\n"
        "Good,10,RON,monthly,2026-01-01\n"
        "Bad,10,GBP,monthly,2026-01-01\n",
        encoding="utf-8",
    )
    with pytest.raises(ImportFailed, match="Row 3: 'GBP' is not one of"):
        exporter.import_file(path)
    assert subscriptions.list_rows() == []


@pytest.mark.parametrize(
    "content, message",
    [
        ("not json", "Could not read"),
        ('{"hello": 1}', "not a SubTrack backup"),
        ('{"format_version": 99, "subscriptions": []}', "newer version"),
        ('{"subscriptions": [{"name": "  ", "price": "1", "currency": "RON", '
         '"billing_cycle": "monthly", "first_payment_date": "2026-01-01"}]}', "missing name"),
    ],
)
def test_invalid_json(tmp_path, exporter, content, message):
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ImportFailed, match=message):
        exporter.import_file(path)


def test_unknown_extension(tmp_path, exporter):
    with pytest.raises(ImportFailed, match="Only .csv and .json"):
        exporter.import_file(tmp_path / "x.xlsx")
