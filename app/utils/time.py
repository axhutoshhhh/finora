"""Calendar date and UTC timestamp helpers for Finora."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from app.utils.errors import ValidationError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_MIN_DATE = date(1900, 1, 1)
_MAX_DATE = date(2100, 12, 31)


def utc_now_iso() -> str:
    """Return a timezone-aware UTC ISO-8601 timestamp string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_today_iso() -> str:
    """Return the user's current local calendar date as YYYY-MM-DD."""
    return date.today().isoformat()


def validate_tx_date(
    raw_value: object,
    *,
    field: str = "tx_date",
    allow_future: bool = False,
) -> str:
    """Validate a local calendar transaction date in strict YYYY-MM-DD format."""
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValidationError("Transaction date is required.", field=field)
    text = raw_value.strip()
    if not _DATE_RE.fullmatch(text):
        raise ValidationError("Date must use YYYY-MM-DD format.", field=field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("Enter a valid calendar date.", field=field) from exc
    if parsed < _MIN_DATE or parsed > _MAX_DATE:
        raise ValidationError("Date must be between 1900-01-01 and 2100-12-31.", field=field)
    if not allow_future and parsed > date.today():
        raise ValidationError(
            "Future-dated transactions are reserved for scheduled entries in Phase 3.",
            field=field,
        )
    return parsed.isoformat()


def shift_month_key(month_key: str, delta_months: int) -> str:
    """Shift a YYYY-MM calendar month string cleanly across year boundaries."""
    if not _MONTH_RE.fullmatch(month_key):
        raise ValidationError("Month must use YYYY-MM format.", field="month")
    year, month = map(int, month_key.split("-"))
    total_months = year * 12 + (month - 1) + delta_months
    if total_months < 1900 * 12 or total_months > 2100 * 12 + 11:
        raise ValidationError("Target month is out of supported range.", field="month")
    new_year, zero_month = divmod(total_months, 12)
    return f"{new_year:04d}-{zero_month + 1:02d}"


def resolve_month_bounds(raw_month: str | None) -> tuple[str, str, str, str]:
    """Return (month_key, label, start_date_inclusive, end_date_exclusive)."""
    if raw_month is None or not raw_month.strip():
        target = date.today().replace(day=1)
    else:
        text = raw_month.strip()
        if not _MONTH_RE.fullmatch(text):
            raise ValidationError("Month must use YYYY-MM format.", field="month")
        try:
            year, month = map(int, text.split("-"))
            target = date(year, month, 1)
        except ValueError as exc:
            raise ValidationError("Enter a valid calendar month.", field="month") from exc

    if target.month == 12:
        next_month = date(target.year + 1, 1, 1)
    else:
        next_month = date(target.year, target.month + 1, 1)

    return (
        target.strftime("%Y-%m"),
        target.strftime("%B %Y"),
        target.isoformat(),
        next_month.isoformat(),
    )
