"""Unit tests for monthly category/overall budgets, rollover, splits, refunds, and Scenario H."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import (
    account_service,
    budget_service,
    category_service,
    overview_service,
    transaction_service,
)
from app.utils.errors import ValidationError


@pytest.mark.unit
def test_scenario_h_budget_with_refund_splits_transfers_and_overall_cap(isolated_db: Path) -> None:
    cash = account_service.list_accounts(isolated_db)["accounts"][0]
    bank = account_service.create_account(
        isolated_db, {"name": "Bank", "account_type": "bank", "opening_balance": "20000"}
    )
    cats = {
        c["slug"]: c["id"] for c in category_service.list_categories(isolated_db, kind="expense")
    }
    inc_cat_id = category_service.list_categories(isolated_db, kind="income")[0]["id"]

    # Income category cannot have expense budget
    with pytest.raises(ValidationError) as exc:
        budget_service.set_category_budget(
            isolated_db,
            {"month": "2026-11", "category_id": inc_cat_id, "limit": "5000"},
        )
    assert exc.value.status_code == 422

    # Scenario H: Food budget ₹3,000, expense ₹2,600, refund ₹200 -> net ₹2,400, remaining ₹600, 80%
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-11", "category_id": cats["food_dining"], "limit": "3000.00"},
    )
    # Explicit zero budget on entertainment; shopping remains unconfigured
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-11", "category_id": cats["entertainment"], "limit": "0"},
    )
    # Set overall monthly limit smaller than sum of category limits to verify mismatch signal
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-11", "category_id": cats["utilities_bills"], "limit": "9000"},
    )
    budget_service.set_overall_budget(isolated_db, {"month": "2026-11", "limit": "10000"})

    exp, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash["id"],
            "category_id": cats["food_dining"],
            "amount": "2600.00",
            "tx_date": "2026-11-10",
        },
    )
    transaction_service.create_refund(
        isolated_db,
        exp["id"],
        {"amount": "200.00", "tx_date": "2026-11-12"},
    )

    # Transfer Bank -> Cash must NOT affect any budget
    transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cash["id"],
            "amount": "4000.00",
            "tx_date": "2026-11-14",
        },
    )
    # Split tx in unbudgeted Shopping (₹600) + budgeted Utilities (₹400)
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": bank["id"],
            "amount": "1000.00",
            "tx_date": "2026-11-15",
            "splits": [
                {"category_id": cats["shopping"], "amount": "600.00"},
                {"category_id": cats["utilities_bills"], "amount": "400.00"},
            ],
        },
    )

    report = budget_service.get_month_budgets(isolated_db, month="2026-11")
    by_slug = {c["category_slug"]: c for c in report["categories"]}

    food = by_slug["food_dining"]
    assert food["net_spend_minor"] == 240_000
    assert food["remaining_minor"] == 60_000
    assert food["usage_percent"] == 80.0
    assert food["status"] == "approaching"

    ent = by_slug["entertainment"]
    assert ent["base_limit_minor"] == 0
    assert ent["status"] == "zero_limit"
    assert ent["usage_percent"] == 0.0

    shop = by_slug["shopping"]
    assert shop["base_limit_minor"] is None
    assert shop["remaining_minor"] is None
    assert shop["status"] == "unconfigured"
    assert shop["net_spend_minor"] == 60_000

    ov = report["overall"]
    assert ov["total_allocated_minor"] == 1_200_000  # 3000 + 0 + 9000
    assert ov["limit_minor"] == 1_000_000  # 10000
    assert ov["allocation_exceeds_overall"] is True
    assert ov["actual_spend_minor"] == 340_000  # 2400 Food + 400 Util + 600 Shop
    assert ov["unbudgeted_spend_minor"] == 60_000

    dashboard = overview_service.get_overview(isolated_db, month="2026-11")
    assert len(dashboard["budget_summary"]["categories"]) == 3


@pytest.mark.unit
def test_budget_rollover_chains_boundaries_missing_month_and_copy(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    food_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]

    # Configure consecutive months across Dec 2025 -> Jan 2026 -> Feb 2024? Let's test 2025-12 -> 2026-01 -> skip 2026-02 -> 2026-03
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2025-12", "category_id": food_id, "limit": "2000", "rollover_enabled": True},
    )
    # Spend ₹1,500 in Dec 2025 -> ₹500 unused carries into Jan 2026
    dec_exp, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "1500",
            "tx_date": "2025-12-20",
        },
    )
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-01", "category_id": food_id, "limit": "2000", "rollover_enabled": True},
    )
    jan = budget_service.get_month_budgets(isolated_db, month="2026-01")["categories"][0]
    assert jan["carry_in_minor"] == 50_000
    assert jan["effective_limit_minor"] == 250_000

    # Overspend Jan (₹3,000 > ₹2,500): overspending must NOT carry negative debt if Feb is configured
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "3000",
            "tx_date": "2026-01-15",
        },
    )
    # Copy Jan -> Feb 2026 (28 days); carry_in in Feb must be 0, NOT -500
    feb_res = budget_service.copy_previous_budgets(
        isolated_db, {"target_month": "2026-02", "source_month": "2026-01"}
    )
    feb = feb_res["categories"][0]
    assert feb["base_limit_minor"] == 200_000
    assert feb["carry_in_minor"] == 0

    # Edit Dec expense from ₹1,500 down to ₹1,000 -> Jan carry-in dynamically becomes ₹1,000!
    transaction_service.update_transaction(isolated_db, dec_exp["id"], {"amount": "1000"})
    jan_updated = budget_service.get_month_budgets(isolated_db, month="2026-01")["categories"][0]
    assert jan_updated["carry_in_minor"] == 100_000
    assert jan_updated["effective_limit_minor"] == 300_000

    # Disable rollover on Jan -> Jan carry-in immediately becomes 0
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-01", "category_id": food_id, "limit": "2000", "rollover_enabled": False},
    )
    jan_no_roll = budget_service.get_month_budgets(isolated_db, month="2026-01")["categories"][0]
    assert jan_no_roll["carry_in_minor"] == 0

    # Missing intervening month (2026-04 unconfigured) resets carry-in on 2026-05
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2026-05", "category_id": food_id, "limit": "2000", "rollover_enabled": True},
    )
    may = budget_service.get_month_budgets(isolated_db, month="2026-05")["categories"][0]
    assert may["carry_in_minor"] == 0

    # Leap-year rollover check: 2024-02 -> 2024-03
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2024-02", "category_id": food_id, "limit": "1000", "rollover_enabled": True},
    )
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "200",
            "tx_date": "2024-02-29",
        },
    )
    budget_service.set_category_budget(
        isolated_db,
        {"month": "2024-03", "category_id": food_id, "limit": "1000", "rollover_enabled": True},
    )
    mar = budget_service.get_month_budgets(isolated_db, month="2024-03")["categories"][0]
    assert mar["carry_in_minor"] == 80_000
    assert mar["effective_limit_minor"] == 180_000
