"""Exact monetary parsing and Indian Rupee (INR) formatting utilities."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.utils.errors import ValidationError

MAX_AMOUNT_MINOR = 99_999_999_999  # ₹99,99,99,999.99 (999,999,999.99 INR in paise)
MAX_SAFE_AGGREGATE_MINOR = 9_000_000_000_000_000  # Within JS Number.MAX_SAFE_INTEGER (9.007e15)

# Accepts plain digits ("1250", "1250.50"), Western grouping ("1,250.00"), or Indian grouping ("1,25,000.50").
_AMOUNT_PATTERN = re.compile(
    r"^(?:\d{1,12}|(?:\d{1,3}(?:,\d{3})+)|(?:\d{1,2}(?:,\d{2})*,\d{3}))(?:\.\d{1,2})?$"
)


def validate_aggregate_minor(total_minor: int, *, label: str = "Total") -> int:
    """Ensure aggregate minor-unit totals stay safely within JS & SQLite integer precision."""
    if isinstance(total_minor, bool) or not isinstance(total_minor, int):
        raise TypeError("total_minor must be an integer")
    if abs(total_minor) > MAX_SAFE_AGGREGATE_MINOR:
        raise ValidationError(f"{label} exceeds safe arithmetic bounds.")
    return total_minor


def parse_inr_to_minor(
    raw_value: object,
    *,
    field: str = "amount",
    allow_zero: bool = False,
) -> int:
    """Parse a non-negative or positive INR monetary input into exact integer minor units (paise).

    Binary floats are explicitly rejected so floating-point inaccuracies never enter
    the financial pipeline.
    """
    if isinstance(raw_value, bool) or raw_value is None:
        raise ValidationError("Amount is required.", field=field)
    if isinstance(raw_value, float):
        raise ValidationError(
            "Monetary amounts must be passed as exact strings or integers, not floats.",
            field=field,
        )

    if isinstance(raw_value, int):
        if raw_value < 0 or (raw_value == 0 and not allow_zero):
            msg = (
                "Amount cannot be negative." if allow_zero else "Amount must be greater than zero."
            )
            raise ValidationError(msg, field=field)
        minor = raw_value * 100
        if minor > MAX_AMOUNT_MINOR:
            raise ValidationError(
                "Amount exceeds the maximum supported value of ₹99,99,99,999.99.",
                field=field,
            )
        return minor

    if isinstance(raw_value, Decimal):
        text = format(raw_value, "f")
    elif isinstance(raw_value, str):
        text = raw_value.strip()
    else:
        raise ValidationError("Amount must be a valid decimal string.", field=field)

    if not text:
        raise ValidationError("Amount is required.", field=field)

    if not _AMOUNT_PATTERN.fullmatch(text):
        raise ValidationError(
            "Enter a valid amount with up to two decimal places (for example 250.50).",
            field=field,
        )

    normalized = text.replace(",", "")
    try:
        dec = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValidationError("Invalid monetary amount.", field=field) from exc

    if not dec.is_finite() or dec.is_nan():
        raise ValidationError("Invalid monetary amount.", field=field)

    if dec < Decimal("0") or (dec == Decimal("0") and not allow_zero):
        msg = "Amount cannot be negative." if allow_zero else "Amount must be greater than zero."
        raise ValidationError(msg, field=field)

    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValidationError(
            "Amount supports at most two decimal places (paise).",
            field=field,
        )

    minor = int((dec * 100).to_integral_exact())
    if minor > MAX_AMOUNT_MINOR or (minor <= 0 and not allow_zero) or minor < 0:
        raise ValidationError(
            "Amount exceeds the maximum supported value of ₹99,99,99,999.99.",
            field=field,
        )
    return minor


def _group_indian_integer(digits: str) -> str:
    """Apply Indian numbering system grouping (3 trailing digits, then pairs of 2)."""
    if len(digits) <= 3:
        return digits
    last_three = digits[-3:]
    prefix = digits[:-3]
    groups: list[str] = []
    while len(prefix) > 2:
        groups.append(prefix[-2:])
        prefix = prefix[:-2]
    if prefix:
        groups.append(prefix)
    groups.reverse()
    return f"{','.join(groups)},{last_three}"


def format_inr_minor(
    amount_minor: int,
    *,
    include_symbol: bool = True,
    show_plus: bool = False,
) -> str:
    """Format integer paise into an Indian-grouped INR currency string."""
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor must be an integer")

    abs_minor = abs(amount_minor)
    rupees, paise = divmod(abs_minor, 100)
    grouped = _group_indian_integer(str(rupees))
    sign = "-" if amount_minor < 0 else ("+" if show_plus and amount_minor > 0 else "")
    symbol = "₹" if include_symbol else ""
    return f"{sign}{symbol}{grouped}.{paise:02d}"
