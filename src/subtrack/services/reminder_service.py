"""Decides which reminders are due, and handles snoozing and marking payments paid.

Showing reminders is the notifier's job (ui/notifier.py).

Reminder kinds:
- PAYMENT_SOON   a few days before a payment (Settings: reminder_days_before)
- PAYMENT_DUE    on the payment day
- PAYMENT_MISSED a payment that fell due while SubTrack was not running
                 (only since the last check, at most CATCH_UP_DAYS back)
- TRIAL_ENDING   before a free trial ends
- CANCEL_BY      before the last day to cancel a contract (end date minus notice period)
- PROMO_ENDING   before an introductory price ends and the regular price starts

Each reminder is shown once, unless the user snoozes it, in which case it comes
back when the snooze runs out. Marking a payment as paid silences its reminders.
"""

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

from subtrack.data.payment_repository import PaymentRepository
from subtrack.data.reminder_repository import ReminderRepository, ReminderState
from subtrack.data.settings_repository import SettingsRepository
from subtrack.data.subscription_repository import SubscriptionRepository
from subtrack.domain import billing
from subtrack.domain.models import Subscription

TOMORROW_AT = time(9, 0)  # "Remind me tomorrow" fires at this time
CATCH_UP_DAYS = 7
LAST_CHECK_KEY = "last_reminder_check"


class ReminderKind(Enum):
    PAYMENT_SOON = "payment"  # value kept from v0.1 so existing rows still match
    PAYMENT_DUE = "payment_due"
    PAYMENT_MISSED = "payment_missed"
    TRIAL_ENDING = "trial_ending"
    CANCEL_BY = "cancel_by"
    PROMO_ENDING = "promo_ending"

    @property
    def is_payment(self) -> bool:
        """Payment reminders get Mark as paid / snooze buttons."""
        return self in (ReminderKind.PAYMENT_SOON, ReminderKind.PAYMENT_DUE, ReminderKind.PAYMENT_MISSED)


def _when(due: date, today: date) -> str:
    days = (due - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 0:
        return f"on {due.strftime('%a %d %b')}"
    return f"on {due.strftime('%a %d %b')} (in {days} days)"


@dataclass(frozen=True)
class Reminder:
    kind: ReminderKind
    subscription: Subscription
    due_date: date

    def title(self) -> str:
        name = self.subscription.name
        return {
            ReminderKind.TRIAL_ENDING: f"{name}: free trial ending",
            ReminderKind.PAYMENT_DUE: f"{name}: payment due today",
            ReminderKind.PAYMENT_MISSED: f"{name}: payment while you were away",
            ReminderKind.CANCEL_BY: f"{name}: last day to cancel coming up",
            ReminderKind.PROMO_ENDING: f"{name}: introductory price ending",
        }.get(self.kind, f"{name}: payment coming up")

    def message(self, today: date) -> str:
        sub = self.subscription
        amount, currency = billing.amount_on(sub, self.due_date)
        price = f"{amount:.2f} {currency.value}"
        regular = f"{sub.price:.2f} {sub.currency.value}"
        when = _when(self.due_date, today)
        if self.kind is ReminderKind.TRIAL_ENDING:
            return f"The free trial ends {when}. Cancel before then to avoid paying {regular}."
        if self.kind is ReminderKind.CANCEL_BY:
            renews = sub.contract_end_date.strftime("%d %b %Y")
            deadline = when if when in ("today", "tomorrow") else when.removeprefix("on ")
            return f"To stop it renewing on {renews}, cancel by {deadline}."
        if self.kind is ReminderKind.PROMO_ENDING:
            return f"The introductory price of {sub.promo_price:.2f} ends {when}; then it costs {regular}."
        share = ""
        if sub.is_shared:
            my_share, _ = billing.share_on(sub, self.due_date)
            share = f" Your share: {my_share:.2f} {currency.value}."
        hint = " You marked it as rarely used." if sub.rarely_used else ""
        if self.kind is ReminderKind.PAYMENT_MISSED:
            return f"{price} was due {when}. Mark it paid if it went through.{share}"
        return f"{price} will be charged {when}.{share}{hint}"


class TimelineEvent(Enum):
    PAYMENT = "Payment"
    TRIAL_END = "Free trial ends"
    CANCEL_BY = "Last day to cancel"
    PROMO_END = "Introductory price ends"


class TimelineStatus(Enum):
    PAID = "Paid"
    SNOOZED = "Snoozed"
    REMINDED = "Reminded"
    DUE_TODAY = "Due today"
    UPCOMING = "Upcoming"
    NOT_MARKED_PAID = "Not marked as paid"
    SKIPPED = "Skipped (paused)"
    PASSED = "Passed"
    TRIAL_ENDED = "Trial ended"


@dataclass(frozen=True)
class TimelineEntry:
    """One payment or date to remember, for the Reminders tab."""

    event: TimelineEvent
    subscription: Subscription
    date: date
    status: TimelineStatus
    detail: str = ""  # e.g. "until Tue 28 Oct 09:00", "on 27 Oct 10:15"

    @property
    def is_trial_end(self) -> bool:
        return self.event is TimelineEvent.TRIAL_END

    @property
    def is_payment(self) -> bool:
        return self.event is TimelineEvent.PAYMENT

    @property
    def can_mark_paid(self) -> bool:
        return self.is_payment and self.status not in (TimelineStatus.PAID, TimelineStatus.SKIPPED)


# Date-type reminders: which date to watch, the reminder kind, and the timeline event.
_DATE_EVENTS = [
    (lambda s: s.trial_end_date, ReminderKind.TRIAL_ENDING, TimelineEvent.TRIAL_END),
    (lambda s: s.cancel_by_date, ReminderKind.CANCEL_BY, TimelineEvent.CANCEL_BY),
    (lambda s: s.promo_until if s.promo_price is not None else None, ReminderKind.PROMO_ENDING, TimelineEvent.PROMO_END),
]


class ReminderService:
    def __init__(
        self,
        subscriptions: SubscriptionRepository,
        reminders: ReminderRepository,
        settings: SettingsRepository,
        payments: PaymentRepository,
    ):
        self._subscriptions = subscriptions
        self._reminders = reminders
        self._settings = settings
        self._payments = payments

    def days_before(self) -> int:
        return int(self._settings.get("reminder_days_before", "3"))

    # ---- what to show now ------------------------------------------------

    def due_reminders(self, now: datetime) -> list[Reminder]:
        """Reminders to show right now: not shown yet, or snoozed until a time that has passed."""
        today = now.date()
        window_end = today + timedelta(days=self.days_before())
        states = self._reminders.all_states()
        paid = self._payments.paid()
        last_check = self.last_check()

        candidates: list[Reminder] = []
        for sub in self._subscriptions.list():
            for get_date, kind, _ in _DATE_EVENTS:
                day = get_date(sub)
                if day is not None and today <= day <= window_end:
                    candidates.append(Reminder(kind, sub, day))

            payment = billing.next_payment_date(sub, today)
            if (sub.id, payment) not in paid:
                if payment == today:
                    candidates.append(Reminder(ReminderKind.PAYMENT_DUE, sub, payment))
                elif payment <= window_end:
                    candidates.append(Reminder(ReminderKind.PAYMENT_SOON, sub, payment))

            # Catch up on payment days that passed while the app was not running.
            if last_check is not None:
                since = max(last_check.date() + timedelta(days=1), today - timedelta(days=CATCH_UP_DAYS))
                for missed in billing.payment_dates(sub, since, today - timedelta(days=1)):
                    already = (sub.id, ReminderKind.PAYMENT_DUE.value, missed) in states
                    if (sub.id, missed) not in paid and not already:
                        candidates.append(Reminder(ReminderKind.PAYMENT_MISSED, sub, missed))

        due = []
        for reminder in candidates:
            state = states.get((reminder.subscription.id, reminder.kind.value, reminder.due_date))
            snooze_over = state is not None and state.snoozed_until is not None and state.snoozed_until <= now
            if state is None or snooze_over:
                due.append(reminder)
        return sorted(due, key=lambda r: (r.due_date, r.subscription.name.lower(), r.kind.value))

    def mark_shown(self, reminder: Reminder, now: datetime) -> None:
        self._reminders.mark_shown(reminder.subscription.id, reminder.kind.value, reminder.due_date, now)

    def last_check(self) -> datetime | None:
        value = self._settings.get(LAST_CHECK_KEY)
        return datetime.fromisoformat(value) if value else None

    def record_check(self, now: datetime) -> None:
        """Called after each check, so the next start knows which days were missed."""
        self._settings.set(LAST_CHECK_KEY, now.isoformat(timespec="seconds"))

    # ---- actions from notification buttons and the Reminders tab ----------

    def snooze(self, subscription_id: int, kind: ReminderKind, due_date: date, until: datetime) -> None:
        self._reminders.snooze(subscription_id, kind.value, due_date, until)

    @staticmethod
    def snooze_target(option: str, now: datetime) -> datetime:
        """'1h' -> an hour from now; 'tomorrow' -> tomorrow at 09:00."""
        if option == "1h":
            return now.replace(microsecond=0) + timedelta(hours=1)
        if option == "tomorrow":
            return datetime.combine(now.date() + timedelta(days=1), TOMORROW_AT)
        raise ValueError(f"unknown snooze option {option!r}")

    def mark_paid(self, subscription_id: int, due_date: date, now: datetime) -> None:
        self._payments.mark_paid(subscription_id, due_date, now)

    def unmark_paid(self, subscription_id: int, due_date: date) -> None:
        self._payments.unmark_paid(subscription_id, due_date)

    # ---- Reminders tab -----------------------------------------------------

    def timeline(self, now: datetime, days_back: int = 30, days_ahead: int = 30) -> list[TimelineEntry]:
        """Every payment and date to remember from days_back ago to days_ahead from now, oldest first."""
        today = now.date()
        start, end = today - timedelta(days=days_back), today + timedelta(days=days_ahead)
        states = self._reminders.all_states()
        paid = self._payments.paid()
        entries: list[TimelineEntry] = []

        for sub in self._subscriptions.list():
            for due in billing.payment_dates(sub, start, end):
                entries.append(self._payment_entry(sub, due, today, now, states, paid))

            if sub.paused_from is not None:
                unpaused = dataclasses.replace(sub, paused_from=None, paused_until=None)
                window = (max(start, sub.paused_from), min(end, sub.paused_until))
                for skipped in billing.payment_dates(unpaused, *window):
                    entries.append(TimelineEntry(TimelineEvent.PAYMENT, sub, skipped, TimelineStatus.SKIPPED))

            for get_date, kind, event in _DATE_EVENTS:
                day = get_date(sub)
                if day is None or not start <= day <= end:
                    continue
                if day < today:
                    status = TimelineStatus.TRIAL_ENDED if event is TimelineEvent.TRIAL_END else TimelineStatus.PASSED
                    entries.append(TimelineEntry(event, sub, day, status))
                else:
                    state = states.get((sub.id, kind.value, day))
                    status, detail = self._reminder_status(state, now) or (TimelineStatus.UPCOMING, "")
                    entries.append(TimelineEntry(event, sub, day, status, detail))

        entries.sort(key=lambda e: (e.date, e.subscription.name.lower(), e.event.value))
        return entries

    def _payment_entry(self, sub, due, today, now, states, paid) -> TimelineEntry:
        payment = TimelineEvent.PAYMENT
        paid_at = paid.get((sub.id, due))
        if paid_at is not None:
            return TimelineEntry(payment, sub, due, TimelineStatus.PAID, f"on {paid_at:%d %b %H:%M}")
        if due < today:
            return TimelineEntry(payment, sub, due, TimelineStatus.NOT_MARKED_PAID)
        # The latest thing that happened to either of this payment's reminders.
        found = [
            self._reminder_status(states.get((sub.id, kind.value, due)), now)
            for kind in (ReminderKind.PAYMENT_DUE, ReminderKind.PAYMENT_SOON)
        ]
        found = [f for f in found if f]
        if found:
            status, detail = found[0]
            return TimelineEntry(payment, sub, due, status, detail)
        status = TimelineStatus.DUE_TODAY if due == today else TimelineStatus.UPCOMING
        return TimelineEntry(payment, sub, due, status)

    @staticmethod
    def _reminder_status(state: ReminderState | None, now: datetime):
        if state is None:
            return None
        if state.snoozed_until is not None and state.snoozed_until > now:
            return TimelineStatus.SNOOZED, f"until {state.snoozed_until:%a %d %b %H:%M}"
        if state.shown_at is not None:
            return TimelineStatus.REMINDED, f"on {state.shown_at:%d %b %H:%M}"
        return None
