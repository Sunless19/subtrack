"""HTTP API over SubTrack's services (FastAPI).

Every endpoint calls the same services the desktop app uses, so both always
calculate the same way. By default it reads and writes the desktop app's own
database (%APPDATA%\\SubTrack\\subtrack.db), so both see the same data.

Each request opens its own database connection: SQLite connections cannot be
shared between FastAPI's worker threads.

Interactive documentation: http://127.0.0.1:8765/docs
"""

import os
import secrets
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from subtrack import __version__, paths
from subtrack.api import schemas
from subtrack.data.database import Database
from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import templates
from subtrack.domain.models import Currency
from subtrack.services.currency_service import CurrencyService
from subtrack.services.export_service import ExportService, ImportFailed
from subtrack.services.reminder_service import ReminderKind, ReminderService
from subtrack.services.stats_service import StatsService
from subtrack.services.subscription_service import SubscriptionService, ValidationError

API_KEY_HEADER = "X-API-Key"


@dataclass
class Services:
    """Everything one request needs, built on one database connection."""

    subscriptions: SubscriptionService
    stats: StatsService
    currency: CurrencyService
    reminders: ReminderService
    exporter: ExportService
    settings: SettingsRepository


def create_app(db_path: Path | str | None = None, api_key: str | None = None, today=date.today, now=datetime.now) -> FastAPI:
    """db_path: SQLite file (default: the desktop app's database).
    api_key: if set, every request must send it in the X-API-Key header.
    today / now: injectable clocks for tests."""
    database_path = Path(db_path) if db_path else paths.database_path()

    app = FastAPI(
        title="SubTrack API",
        version=__version__,
        description="Subscriptions, totals, forecasts and reminders. Money values are decimal strings.",
    )

    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        open_paths = ("/health", "/docs", "/redoc", "/openapi.json")
        if api_key and request.url.path not in open_paths:
            if not secrets.compare_digest(request.headers.get(API_KEY_HEADER, ""), api_key):
                return JSONResponse({"detail": f"Missing or wrong {API_KEY_HEADER} header."}, status_code=401)
        return await call_next(request)

    @app.exception_handler(ValidationError)
    async def validation_error(request: Request, error: ValidationError):
        return JSONResponse({"detail": str(error)}, status_code=422)

    def services() -> Iterator[Services]:
        db = Database(database_path)
        try:
            subscription_repo = SubscriptionRepository(db)
            settings = SettingsRepository(db)
            currency = CurrencyService(settings)
            subscriptions = SubscriptionService(subscription_repo, today=today)
            yield Services(
                subscriptions=subscriptions,
                stats=StatsService(subscription_repo, currency, today=today),
                currency=currency,
                reminders=ReminderService(subscription_repo, ReminderRepository(db), settings, PaymentRepository(db)),
                exporter=ExportService(subscriptions),
                settings=settings,
            )
        finally:
            db.close()

    def find_row(s: Services, sub_id: int):
        for row in s.subscriptions.list_rows(include_inactive=True):
            if row.subscription.id == sub_id:
                return row
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Subscription {sub_id} not found.")

    # ---- general ---------------------------------------------------------------

    @app.get("/health", tags=["general"])
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/templates", response_model=list[schemas.TemplateOut], tags=["general"])
    def list_templates():
        """Common services with their usual category and billing cycle."""
        return [schemas.TemplateOut(**vars(t)) for t in templates.TEMPLATES]

    # ---- subscriptions -----------------------------------------------------------

    @app.get("/subscriptions", response_model=list[schemas.SubscriptionOut], tags=["subscriptions"])
    def list_subscriptions(include_cancelled: bool = False, s: Services = Depends(services)):
        return [schemas.SubscriptionOut.from_row(r) for r in s.subscriptions.list_rows(include_cancelled)]

    @app.post("/subscriptions", response_model=schemas.SubscriptionOut, status_code=201, tags=["subscriptions"])
    def create_subscription(body: schemas.SubscriptionIn, s: Services = Depends(services)):
        created = s.subscriptions.add(body.to_domain())
        return schemas.SubscriptionOut.from_row(find_row(s, created.id))

    @app.get("/subscriptions/{sub_id}", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def get_subscription(sub_id: int, s: Services = Depends(services)):
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    @app.put("/subscriptions/{sub_id}", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def replace_subscription(sub_id: int, body: schemas.SubscriptionIn, s: Services = Depends(services)):
        """Replace every field. A changed price or currency is added to the price history."""
        find_row(s, sub_id)
        s.subscriptions.update(body.to_domain(sub_id))
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    @app.delete("/subscriptions/{sub_id}", status_code=204, tags=["subscriptions"])
    def delete_subscription(sub_id: int, s: Services = Depends(services)):
        find_row(s, sub_id)
        s.subscriptions.delete(sub_id)
        return Response(status_code=204)

    @app.post("/subscriptions/{sub_id}/cancel", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def cancel_subscription(sub_id: int, s: Services = Depends(services)):
        find_row(s, sub_id)
        s.subscriptions.cancel(sub_id)
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    @app.post("/subscriptions/{sub_id}/reactivate", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def reactivate_subscription(sub_id: int, s: Services = Depends(services)):
        find_row(s, sub_id)
        s.subscriptions.reactivate(sub_id)
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    @app.post("/subscriptions/{sub_id}/skip-next", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def skip_next_payment(sub_id: int, s: Services = Depends(services)):
        if not find_row(s, sub_id).subscription.active:
            raise HTTPException(409, "A cancelled subscription has no next payment to skip.")
        s.subscriptions.skip_next_payment(sub_id)
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    @app.post("/subscriptions/{sub_id}/resume", response_model=schemas.SubscriptionOut, tags=["subscriptions"])
    def resume_subscription(sub_id: int, s: Services = Depends(services)):
        find_row(s, sub_id)
        s.subscriptions.resume(sub_id)
        return schemas.SubscriptionOut.from_row(find_row(s, sub_id))

    # ---- statistics ----------------------------------------------------------------

    @app.get("/stats/summary", response_model=schemas.Summary, tags=["stats"])
    def summary(s: Services = Depends(services)):
        return schemas.Summary(
            base_currency=s.currency.base_currency(),
            monthly_total=s.stats.monthly_total(),
            yearly_total=s.stats.yearly_total(),
            active_subscriptions=len(s.subscriptions.list_rows()),
        )

    @app.get("/stats/by-category", response_model=list[schemas.CategoryTotal], tags=["stats"])
    def by_category(s: Services = Depends(services)):
        return [schemas.CategoryTotal(category=c, monthly=a) for c, a in s.stats.monthly_total_by_category().items()]

    @app.get("/stats/upcoming", response_model=list[schemas.UpcomingPaymentOut], tags=["stats"])
    def upcoming(days: int = Query(30, ge=1, le=366), s: Services = Depends(services)):
        return [
            schemas.UpcomingPaymentOut(due_date=p.due_date, subscription_id=p.subscription.id,
                                       name=p.subscription.name, amount=p.amount_in_base)
            for p in s.stats.upcoming_payments(today(), days)
        ]

    @app.get("/stats/monthly", response_model=list[schemas.MonthTotalOut], tags=["stats"])
    def monthly(back: int = Query(12, ge=0, le=60), ahead: int = Query(12, ge=1, le=60), s: Services = Depends(services)):
        """Spending per month: `back` past months, then the current month and later as a forecast."""
        return [schemas.MonthTotalOut(**vars(m)) for m in s.stats.monthly_spending(back, ahead)]

    @app.get("/stats/spent", response_model=list[schemas.SpentOut], tags=["stats"])
    def spent(s: Services = Depends(services)):
        names = {r.subscription.id: r.subscription.name for r in s.subscriptions.list_rows()}
        return [schemas.SpentOut(subscription_id=i, name=names[i], spent=v) for i, v in s.stats.spent_so_far().items()]

    # ---- reminders and payments -----------------------------------------------------

    @app.get("/reminders/due", response_model=list[schemas.ReminderOut], tags=["reminders"])
    def due_reminders(mark_shown: bool = False, s: Services = Depends(services)):
        """Reminders due right now. With mark_shown=true they count as delivered and won't come back."""
        moment = now()
        due = s.reminders.due_reminders(moment)
        if mark_shown:
            for reminder in due:
                s.reminders.mark_shown(reminder, moment)
            s.reminders.record_check(moment)
        return [schemas.ReminderOut.from_reminder(r, moment.date()) for r in due]

    @app.get("/reminders/timeline", response_model=list[schemas.TimelineEntryOut], tags=["reminders"])
    def timeline(days_back: int = Query(30, ge=0, le=366), days_ahead: int = Query(30, ge=0, le=366),
                 s: Services = Depends(services)):
        return [schemas.TimelineEntryOut.from_entry(e) for e in s.reminders.timeline(now(), days_back, days_ahead)]

    @app.post("/reminders/snooze", status_code=204, tags=["reminders"])
    def snooze(body: schemas.SnoozeIn, s: Services = Depends(services)):
        try:
            kind = ReminderKind(body.kind)
            until = body.until or s.reminders.snooze_target(body.option or "", now())
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        s.reminders.snooze(body.subscription_id, kind, body.due_date, until)
        return Response(status_code=204)

    @app.put("/payments/{sub_id}/{due_date}", status_code=204, tags=["reminders"])
    def mark_paid(sub_id: int, due_date: date, s: Services = Depends(services)):
        find_row(s, sub_id)
        s.reminders.mark_paid(sub_id, due_date, now())
        return Response(status_code=204)

    @app.delete("/payments/{sub_id}/{due_date}", status_code=204, tags=["reminders"])
    def unmark_paid(sub_id: int, due_date: date, s: Services = Depends(services)):
        s.reminders.unmark_paid(sub_id, due_date)
        return Response(status_code=204)

    # ---- settings ---------------------------------------------------------------------

    def settings_out(s: Services) -> schemas.SettingsOut:
        return schemas.SettingsOut(
            base_currency=s.currency.base_currency(),
            rates_in_ron={c: s.currency.rate_in_ron(c) for c in Currency if c is not Currency.RON},
            rates_updated_on=s.currency.rates_updated_on(),
            reminder_days_before=s.reminders.days_before(),
        )

    @app.get("/settings", response_model=schemas.SettingsOut, tags=["settings"])
    def get_settings(s: Services = Depends(services)):
        return settings_out(s)

    @app.patch("/settings", response_model=schemas.SettingsOut, tags=["settings"])
    def update_settings(body: schemas.SettingsIn, s: Services = Depends(services)):
        """Change only the fields that are sent."""
        try:
            for currency, rate in (body.rates_in_ron or {}).items():
                s.currency.set_rate_in_ron(currency, rate)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if body.base_currency is not None:
            s.currency.set_base_currency(body.base_currency)
        if body.reminder_days_before is not None:
            s.settings.set("reminder_days_before", str(body.reminder_days_before))
        return settings_out(s)

    # ---- export / import ---------------------------------------------------------------

    @app.get("/export/{fmt}", tags=["export"])
    def export(fmt: str, s: Services = Depends(services)):
        """fmt: csv (Excel), json (backup) or ics (calendar, next 12 months)."""
        formats = {"csv": ("text/csv", s.exporter.export_csv),
                   "json": ("application/json", s.exporter.export_json),
                   "ics": ("text/calendar", lambda p: s.exporter.export_ics(p, today=today()))}
        if fmt not in formats:
            raise HTTPException(404, "Format must be csv, json or ics.")
        media_type, write = formats[fmt]
        handle, temp = tempfile.mkstemp(suffix=f".{fmt}")
        os.close(handle)
        write(Path(temp))
        return FileResponse(temp, media_type=media_type, filename=f"subtrack-{today().isoformat()}.{fmt}",
                            background=BackgroundTask(os.remove, temp))

    @app.post("/import", response_model=schemas.ImportResultOut, tags=["export"])
    def import_file(file: UploadFile = File(...), s: Services = Depends(services)):
        """Upload a .csv or .json exported by SubTrack. All-or-nothing; duplicates are skipped."""
        suffix = Path(file.filename or "").suffix.lower()
        handle, temp = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(file.file.read())
            result = s.exporter.import_file(Path(temp))
        except ImportFailed as error:
            raise HTTPException(422, str(error)) from None
        finally:
            os.remove(temp)
        return schemas.ImportResultOut(imported=result.imported, skipped_duplicates=result.skipped_duplicates)

    return app
