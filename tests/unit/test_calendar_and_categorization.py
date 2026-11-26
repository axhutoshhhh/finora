"""Unit tests for Phase 3 financial calendar and automatic categorization."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import (
    account_service,
    calendar_service,
    categorization_service,
    category_service,
    transaction_service,
)


@pytest.mark.unit
def test_calendar_leap_year_and_posted_vs_scheduled(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "250.00",
            "tx_date": "2024-02-29",
            "description": "Leap day coffee",
        },
    )
    cal = calendar_service.get_month_calendar(isolated_db, month="2024-02")
    assert cal["days_in_month"] == 29
    day_29 = cal["days"][28]
    assert day_29["date"] == "2024-02-29"
    assert day_29["posted_count"] == 1
    assert day_29["scheduled_count"] == 0


@pytest.mark.unit
def test_categorization_rules_priority_and_kind_guard(isolated_db: Path) -> None:
    cats = category_service.list_categories(isolated_db, kind="expense")
    food_id = cats[0]["id"]
    other_id = cats[1]["id"]

    categorization_service.create_rule(
        isolated_db,
        {
            "name": "Swiggy Food",
            "match_field": "merchant",
            "match_type": "contains",
            "pattern": "Swiggy",
            "entry_type": "expense",
            "target_category_id": food_id,
            "priority": 10,
        },
    )
    categorization_service.create_rule(
        isolated_db,
        {
            "name": "Lower Priority",
            "match_field": "merchant",
            "match_type": "contains",
            "pattern": "Swiggy",
            "entry_type": "expense",
            "target_category_id": other_id,
            "priority": 50,
        },
    )
    sug = categorization_service.suggest_category(
        isolated_db, entry_type="expense", merchant="Swiggy Instamart"
    )
    assert sug is not None
    assert sug["category_id"] == food_id
    # Income must not match expense rule
    assert (
        categorization_service.suggest_category(isolated_db, entry_type="income", merchant="Swiggy")
        is None
    )
