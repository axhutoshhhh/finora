"""Unit tests for Phase 3 advisory engine, deduplication, and forecasting."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services import (
    account_service,
    advisory_service,
    budget_service,
    category_service,
    forecasting_service,
    transaction_service,
)


@pytest.mark.unit
def test_scenario_d_budget_approaching_and_deduplication(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    food_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    budget_service.set_category_budget(
        isolated_db, {"month": "2026-11", "category_id": food_id, "limit": "3000.00"}
    )
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "2300.00",
            "tx_date": "2026-11-10",
        },
    )
    first_run = advisory_service.evaluate_advisories(
        isolated_db, month="2026-11", today=date(2026, 11, 15)
    )
    assert not any(n["rule_id"] == "budget_approaching" for n in first_run)

    # Crossing 80% (₹2,400 / ₹3,000) generates exactly one alert
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "100.00",
            "tx_date": "2026-11-12",
        },
    )
    second_run = advisory_service.evaluate_advisories(
        isolated_db, month="2026-11", today=date(2026, 11, 15)
    )
    approaching = [n for n in second_run if n["rule_id"] == "budget_approaching"]
    assert len(approaching) == 1

    # Repeated evaluation must not duplicate
    third_run = advisory_service.evaluate_advisories(
        isolated_db, month="2026-11", today=date(2026, 11, 15)
    )
    assert len([n for n in third_run if n["rule_id"] == "budget_approaching"]) == 1


@pytest.mark.unit
def test_forecasting_edge_cases(isolated_db: Path) -> None:
    # Day 1 with 0 spend -> insufficient_data=True
    f1 = forecasting_service.compute_monthly_forecast(
        isolated_db, month="2024-02", today=date(2024, 2, 1)
    )
    assert f1["days_in_month"] == 29  # Leap year
    assert f1["insufficient_data"] is True
    assert f1["projected_spend_minor"] == 0

    # Last day of Feb 2024 with spending
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    food_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "2900.00",
            "tx_date": "2024-02-15",
        },
    )
    f2 = forecasting_service.compute_monthly_forecast(
        isolated_db, month="2024-02", today=date(2024, 2, 29)
    )
    assert f2["insufficient_data"] is False
    assert f2["projected_spend_minor"] == 290_000
