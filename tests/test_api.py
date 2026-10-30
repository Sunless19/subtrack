"""The HTTP API, driven through FastAPI's TestClient against a temporary database."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from subtrack.api.app import create_app

TODAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 10, 0)

NETFLIX = {"name": "Netflix", "price": "49.99", "currency": "RON", "billing_cycle": "monthly",
           "first_payment_date": "2026-01-31", "category": "streaming"}


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "api.db", today=lambda: TODAY, now=lambda: NOW)
    with TestClient(app) as c:
        yield c


def add(client, **overrides):
    response = client.post("/subscriptions", json={**NETFLIX, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_docs(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    assert "/subscriptions" in client.get("/openapi.json").json()["paths"]


def test_create_read_update_delete(client):
    created = add(client)
    assert created["id"] == 1 and created["next_payment"] == "2026-10-31"
    assert created["monthly_cost"] == "49.99" and created["price"] == "49.99"  # money as strings

    assert client.get("/subscriptions/1").json()["name"] == "Netflix"
    assert len(client.get("/subscriptions").json()) == 1

    updated = client.put("/subscriptions/1", json={**NETFLIX, "price": "59.99"}).json()
    assert updated["price"] == "59.99" and updated["price_change_percent"] == "20.0"
    assert updated["price_history"][0]["old_price"] == "49.99"

    assert client.delete("/subscriptions/1").status_code == 204
    assert client.get("/subscriptions/1").status_code == 404


def test_validation_errors_are_422(client):
    bad_name = client.post("/subscriptions", json={**NETFLIX, "name": "  "})
    assert bad_name.status_code == 422 and bad_name.json()["detail"] == "Name is required."
    assert client.post("/subscriptions", json={**NETFLIX, "currency": "GBP"}).status_code == 422
    assert client.post("/subscriptions", json={**NETFLIX, "surprise": 1}).status_code == 422


def test_cancel_reactivate_skip_resume(client):
    add(client)
    assert client.post("/subscriptions/1/skip-next").json()["next_payment"] == "2026-11-30"
    assert client.post("/subscriptions/1/resume").json()["next_payment"] == "2026-10-31"
    assert client.post("/subscriptions/1/cancel").json()["active"] is False
    assert client.get("/subscriptions").json() == []
    assert len(client.get("/subscriptions?include_cancelled=true").json()) == 1
    assert client.post("/subscriptions/1/skip-next").status_code == 409
    assert client.post("/subscriptions/1/reactivate").json()["active"] is True


def test_stats(client):
    add(client)
    add(client, name="Spotify Family", price="40", shared_with=4, category="music", first_payment_date="2026-01-05")
    summary = client.get("/stats/summary").json()
    assert summary == {"base_currency": "RON", "monthly_total": "59.99", "yearly_total": "719.88",
                       "active_subscriptions": 2}
    assert [c["category"] for c in client.get("/stats/by-category").json()] == ["streaming", "music"]
    upcoming = client.get("/stats/upcoming?days=10").json()
    assert [(p["name"], p["amount"]) for p in upcoming] == [("Netflix", "49.99"), ("Spotify Family", "10.00")]
    months = client.get("/stats/monthly?back=1&ahead=2").json()
    assert [m["month"] for m in months] == ["2026-09-01", "2026-10-01", "2026-11-01"]
    assert {s["name"] for s in client.get("/stats/spent").json()} == {"Netflix", "Spotify Family"}


def test_reminders_and_payments(client):
    add(client)  # due tomorrow (31 Oct)
    due = client.get("/reminders/due").json()
    assert [(r["kind"], r["due_date"]) for r in due] == [("payment", "2026-10-31")]
    assert due[0]["message"] == "49.99 RON will be charged tomorrow."
    client.get("/reminders/due?mark_shown=true")
    assert client.get("/reminders/due").json() == []

    assert client.put("/payments/1/2026-10-31").status_code == 204
    entry = next(e for e in client.get("/reminders/timeline").json() if e["date"] == "2026-10-31")
    assert entry["status"] == "Paid" and entry["can_mark_paid"] is False
    client.delete("/payments/1/2026-10-31")
    entry = next(e for e in client.get("/reminders/timeline").json() if e["date"] == "2026-10-31")
    assert entry["status"] == "Reminded"


def test_snooze(client):
    add(client, first_payment_date="2026-01-30")  # due today
    client.get("/reminders/due?mark_shown=true")
    body = {"subscription_id": 1, "kind": "payment_due", "due_date": "2026-10-30", "option": "1h"}
    assert client.post("/reminders/snooze", json=body).status_code == 204
    entry = next(e for e in client.get("/reminders/timeline").json() if e["date"] == "2026-10-30")
    assert entry["status"] == "Snoozed" and "11:00" in entry["detail"]
    assert client.post("/reminders/snooze", json={**body, "option": "never"}).status_code == 422


def test_settings(client):
    assert client.get("/settings").json()["base_currency"] == "RON"
    changed = client.patch("/settings", json={"base_currency": "EUR", "rates_in_ron": {"EUR": "5"},
                                              "reminder_days_before": 7}).json()
    assert changed["base_currency"] == "EUR" and changed["rates_in_ron"]["EUR"] == "5"
    assert changed["reminder_days_before"] == 7
    assert client.patch("/settings", json={"rates_in_ron": {"EUR": "0"}}).status_code == 422


def test_export_and_import(client):
    add(client)
    csv_text = client.get("/export/csv").text
    assert "Netflix" in csv_text
    ics = client.get("/export/ics")
    assert ics.headers["content-type"].startswith("text/calendar") and "BEGIN:VCALENDAR" in ics.text
    backup = client.get("/export/json").content
    assert client.get("/export/pdf").status_code == 404

    result = client.post("/import", files={"file": ("backup.json", backup, "application/json")}).json()
    assert result == {"imported": 0, "skipped_duplicates": 1}
    bad = client.post("/import", files={"file": ("x.csv", b"name,price\nA,1\n", "text/csv")})
    assert bad.status_code == 422 and "missing" in bad.json()["detail"]


def test_templates(client):
    names = [t["name"] for t in client.get("/templates").json()]
    assert "Netflix" in names and "Microsoft 365" in names


def test_api_key(tmp_path):
    app = create_app(tmp_path / "k.db", api_key="s3cret")
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200  # open, so you can check it is running
        assert c.get("/subscriptions").status_code == 401
        assert c.get("/subscriptions", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/subscriptions", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_parallel_requests(client):
    """Browsers load several endpoints at once; each request's connection may hop threads."""
    from concurrent.futures import ThreadPoolExecutor

    add(client)
    paths = ["/subscriptions", "/stats/summary", "/stats/spent", "/settings", "/reminders/due", "/stats/monthly"] * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda p: client.get(p).status_code, paths))
    assert codes == [200] * len(paths)


def test_web_interface_is_served(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/web/"
    page = client.get("/web/")
    assert page.status_code == 200 and "<title>SubTrack</title>" in page.text
    for asset in ("app.js", "styles.css", "icon.svg"):
        assert client.get(f"/web/{asset}").status_code == 200


def test_web_pages_stay_open_when_a_key_is_required(tmp_path):
    with TestClient(create_app(tmp_path / "k.db", api_key="s3cret")) as c:
        assert c.get("/web/").status_code == 200
        assert c.get("/health/key").json() == {"api_key_required": True}
        assert c.get("/stats/summary").status_code == 401
