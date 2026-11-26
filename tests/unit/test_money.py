"""Unit tests for exact monetary parsing and Indian INR formatting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.utils.errors import ValidationError
from app.utils.money import (
    MAX_AMOUNT_MINOR,
    MAX_SAFE_AGGREGATE_MINOR,
    format_inr_minor,
    parse_inr_to_minor,
    validate_aggregate_minor,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 100),
        ("1.00", 100),
        ("10.5", 1050),
        ("10.50", 1050),
        ("99.99", 9999),
        ("1,25,000.00", 12_500_000),
        ("1,250.75", 125_075),
        (" 42.10 ", 4210),
        (Decimal("250.25"), 25_025),
        (500, 50_000),
        ("999999999.99", MAX_AMOUNT_MINOR),
    ],
)
def test_parse_inr_to_minor_valid(raw: object, expected: int) -> None:
    assert parse_inr_to_minor(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        True,
        False,
        12.5,  # binary float explicitly rejected
        "0",
        "0.00",
        "-10.00",
        "+10.00",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e5",
        "10.999",
        "10.1234",
        "abc",
        "₹500",
        "10..00",
        "10,50",
        "1,23,45",
        "1,2,3",
        "1000000000.00",  # exceeds MAX_AMOUNT_MINOR
        -50,
        0,
    ],
)
def test_parse_inr_to_minor_invalid(raw: object) -> None:
    with pytest.raises(ValidationError):
        parse_inr_to_minor(raw)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("minor", "show_plus", "expected"),
    [
        (0, False, "₹0.00"),
        (100, False, "₹1.00"),
        (1050, False, "₹10.50"),
        (125000, False, "₹1,250.00"),
        (12500000, False, "₹1,25,000.00"),
        (1250000000, False, "₹1,25,00,000.00"),
        (-12500050, False, "-₹1,25,000.50"),
        (450000, True, "+₹4,500.00"),
        (0, True, "₹0.00"),
    ],
)
def test_format_inr_minor(minor: int, show_plus: bool, expected: str) -> None:
    assert format_inr_minor(minor, show_plus=show_plus) == expected


@pytest.mark.unit
def test_parse_allow_zero_and_aggregate_bounds() -> None:
    assert parse_inr_to_minor("0", allow_zero=True) == 0
    assert parse_inr_to_minor("0.00", allow_zero=True) == 0
    assert parse_inr_to_minor(0, allow_zero=True) == 0
    assert validate_aggregate_minor(MAX_SAFE_AGGREGATE_MINOR) == MAX_SAFE_AGGREGATE_MINOR
    with pytest.raises(ValidationError):
        validate_aggregate_minor(MAX_SAFE_AGGREGATE_MINOR + 1)
