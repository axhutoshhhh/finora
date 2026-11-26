"""Unit tests for Phase 3 savings goals and recurring payment engine (Scenarios F, G, H)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services import (
    account_service,
    analytics_service,
    category_service,
    goal_service,
    recurring_service,
)


@pytest.mark.unit
def test_scenario_f_savings_allocation_preserves_ledger_and_net_worth(isolated_db: Path) -> None:
    savings = account_service.create_account(
        isolated_db,
        {"name": "Savings", "account_type": "savings", "opening_balance": "10000.00"},
    )
    goal = goal_service.create_goal(
        isolated_db,
        {"name": "Emergency Fund", "target_amount": "5000.00", "account_id": savings["id"]},
    )
    res = goal_service.add_contribution(
        isolated_db,
        goal["id"],
        {"amount": "3000.00", "allocation_date": "2026-11-10"},
    )
    assert res["goal"]["allocated_minor"] == 300_000
    assert res["goal"]["remaining_minor"] == 200_000

    # Account balance, income, expenses, and net worth must be unchanged
    acct = account_service.get_account_detail(isolated_db, savings["id"])["account"]
    assert acct["balance_minor"] == 1_000_000
    rep = analytics_service.get_full_analytics_report(
        isolated_db, preset="current_month", today=date(2026, 11, 20)
    )
    assert rep["summary"]["income_minor"] == 0
    assert rep["summary"]["net_expense_minor"] == 0


@pytest.mark.unit
def test_scenario_g_recurring_subscription_and_idempotent_posting(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    rule = recurring_service.create_rule(
        isolated_db,
        {
            "name": "Music Plan",
            "entry_type": "expense",
            "is_subscription": True,
            "amount": "199.00",
            "account_id": cash_id,
            "category_id": exp_cat,
            "frequency": "monthly",
            "start_date": "2026-11-15",
        },
    )
    assert rule["is_subscription"] is True
    # Upcoming occurrence must not change balance
    assert account_service.list_accounts(isolated_db)["accounts"][0]["balance_minor"] == 0

    occ = recurring_service.list_occurrences(isolated_db)[0]
    first = recurring_service.post_occurrence(isolated_db, occ["id"])
    second = recurring_service.post_occurrence(isolated_db, occ["id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["transaction_id"] == second["transaction_id"]
    assert account_service.list_accounts(isolated_db)["accounts"][0]["balance_minor"] == -19_900


@pytest.mark.unit
def test_scenario_h_recurring_jan_31_anchor_preservation() -> None:
    d1 = date(2025, 1, 31)
    d2 = recurring_service.advance_recurrence_date(d1, frequency="monthly", anchor_day=31)
    assert d2 == date(2025, 2, 28)
    d3 = recurring_service.advance_recurrence_date(d2, frequency="monthly", anchor_day=31)
    assert d3 == date(2025, 3, 31)

    # Leap year Feb 29 -> Feb 28 next year
    ly1 = date(2024, 2, 29)
    ly2 = recurring_service.advance_recurrence_date(ly1, frequency="yearly", anchor_day=29)
    assert ly2 == date(2025, 2, 28)
