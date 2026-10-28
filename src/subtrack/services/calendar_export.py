"""Upcoming payments as an iCalendar (.ics) file for Google Calendar, Outlook, etc.

One all-day event per payment for the next 12 months, each with a reminder the
day before. Event UIDs are stable (subscription + date), so importing a newer
file updates events instead of duplicating them in most calendar apps.
Follows RFC 5545: CRLF line endings, escaped text, lines folded at 75 octets.
"""

from datetime import date, datetime, timedelta, timezone

from subtrack.domain import billing
from subtrack.domain.models import Subscription

PRODID = "-//SubTrack//Subscription payments//EN"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Split lines longer than 75 octets; continuation lines start with a space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        piece = char.encode("utf-8")
        limit = 75 if not parts else 74  # continuation lines lose one octet to the leading space
        if len(current) + len(piece) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += piece
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def build_calendar(subscriptions: list[Subscription], today: date, months: int = 12) -> tuple[str, int]:
    """The .ics text and the number of events in it."""
    end = billing.add_months(today, months)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Subscription payments",
    ]
    count = 0
    for sub in subscriptions:
        for due in billing.payment_dates(sub, today, end):
            amount, currency = billing.amount_on(sub, due)  # introductory price if it applies
            price = f"{amount:.2f} {currency.value}"
            details = [f"{sub.name}: {price} ({sub.billing_cycle.label.lower()})"]
            if sub.is_shared:
                share, _ = billing.share_on(sub, due)
                details.append(f"Your share: {share:.2f} {currency.value} (split {sub.shared_with} ways)")
            if sub.payment_method:
                details.append(f"Paid with: {sub.payment_method}")
            if sub.notes:
                details.append(sub.notes)
            count += 1
            lines += [
                "BEGIN:VEVENT",
                f"UID:subtrack-{sub.id}-{due:%Y%m%d}@subtrack.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{due:%Y%m%d}",
                f"DTEND;VALUE=DATE:{due + timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{_escape(f'{sub.name} – {price}')}",
                f"DESCRIPTION:{_escape(chr(10).join(details))}",
                f"CATEGORIES:{_escape(sub.category.label)}",
                "TRANSP:TRANSPARENT",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(f'{sub.name} is charged tomorrow ({price})')}",
                "TRIGGER:-PT15H",  # 09:00 the day before an all-day event
                "END:VALARM",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n", count
