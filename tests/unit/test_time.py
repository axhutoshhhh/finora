"""Unit tests for calendar date validation and month boundary resolution."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.utils.errors import ValidationError
from app.utils.time import resolve_month_bounds, shift_month_key, utc_now_iso, validate_tx_date


@pytest.mark.unit
def test_validate_tx_date_valid() -> None:
    assert validate_tx_date("2026-11-26") == "2026-11-26"
    assert validate_tx_date("2024-02-29") == "2024-02-29"  # leap day
    future = (date.today() + timedelta(days=2)).isoformat()
    assert validate_tx_date(future, allow_future=True) == future


@pytest.mark.unit
def test_validate_tx_date_rejects_future_by_default() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError):
        validate_tx_date(tomorrow)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        12345,
        "26-11-2026",
        "2026/11/26",
        "2025-02-29",  # non-leap year
        "2026-13-01",
        "1899-12-31",
        "2101-01-01",
    ],
)
def test_validate_tx_date_invalid(raw: object) -> None:
    with pytest.raises(ValidationError):
        validate_tx_date(raw)


@pytest.mark.unit
def test_resolve_month_bounds_december_rollover() -> None:
    key, label, start, end = resolve_month_bounds("2026-12")
    assert key == "2026-12"
    assert label == "December 2026"
    assert start == "2026-12-01"
    assert end == "2027-01-01"
    assert shift_month_key("2026-12", 1) == "2027-01"
    assert shift_month_key("2026-01", -1) == "2025-12"
    assert shift_month_key("2024-02", 1) == "2024-03"


@pytest.mark.unit
def test_utc_now_iso_ends_with_z() -> None:
    ts = utc_now_iso()
    assert ts.endswith("Z")
    assert len(ts) == 20
