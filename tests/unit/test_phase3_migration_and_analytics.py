"""Unit tests for Phase 3 migration (0003) and authoritative financial analytics."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.services import account_service, analytics_service, category_service, transaction_service


@pytest.mark.unit
def test_phase3_schema_tables_present_and_integrity_ok(isolated_db: Path) -> None:
    conn = sqlite3.connect(isolated_db)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    }
    versions = [
        r[0]
        for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version;").fetchall()
    ]
    conn.close()
    assert versions == [1, 2, 3, 4]
    for expected in (
        "savings_goals",
        "goal_allocations",
        "recurring_rules",
        "recurring_occurrences",
        "notification_events",
        "notification_preferences",
        "categorization_rules",
        "import_batches",
        "import_batch_rows",
    ):
        assert expected in tables


@pytest.mark.unit
def test_scenario_a_report_reconciliation_and_transfer_exclusion(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    bank_id = account_service.create_account(
        isolated_db, {"name": "HDFC Bank", "account_type": "bank"}
    )["id"]
    inc_cat = category_service.list_categories(isolated_db, kind="income")[0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]

    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "income",
            "account_id": bank_id,
            "category_id": inc_cat,
            "amount": "15000.00",
            "tx_date": "2026-11-05",
            "description": "Salary",
        },
    )
    exp, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": bank_id,
            "category_id": exp_cat,
            "amount": "10000.00",
            "tx_date": "2026-11-10",
            "description": "Shopping",
        },
    )
    transaction_service.create_refund(
        isolated_db,
        exp["id"],
        {"account_id": bank_id, "amount": "750.00", "tx_date": "2026-11-12"},
    )
    # Internal transfer must not affect income, expenses, or surplus
    transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank_id,
            "to_account_id": cash_id,
            "amount": "2000.00",
            "tx_date": "2026-11-15",
        },
    )

    rep = analytics_service.get_full_analytics_report(
        isolated_db, preset="current_month", today=date(2026, 11, 20)
    )
    s = rep["summary"]
    assert s["income_minor"] == 1_500_000
    assert s["gross_expense_minor"] == 1_000_000
    assert s["refund_minor"] == 75_000
    assert s["net_expense_minor"] == 925_000
    assert s["surplus_minor"] == 575_000
    assert s["savings_rate_available"] is True
    assert s["savings_rate_percent"] == pytest.approx(38.33, abs=0.01)


@pytest.mark.unit
def test_scenario_b_split_transaction_reporting(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    cats = category_service.list_categories(isolated_db, kind="expense")
    c1, c2, c3 = cats[0]["id"], cats[1]["id"], cats[2]["id"]

    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "amount": "1000.00",
            "tx_date": "2026-11-10",
            "splits": [
                {"category_id": c1, "amount": "650.00"},
                {"category_id": c2, "amount": "250.00"},
                {"category_id": c3, "amount": "100.00"},
            ],
        },
    )
    rep = analytics_service.get_full_analytics_report(
        isolated_db, preset="current_month", today=date(2026, 11, 20)
    )
    assert rep["summary"]["gross_expense_minor"] == 100_000
    by_cat = {c["category_id"]: c["gross_minor"] for c in rep["categories"]}
    assert by_cat[c1] == 65_000
    assert by_cat[c2] == 25_000
    assert by_cat[c3] == 10_000


@pytest.mark.unit
def test_scenario_c_historical_refund_and_negative_category_net(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    exp, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "500.00",
            "tx_date": "2026-10-20",
        },
    )
    transaction_service.create_refund(
        isolated_db,
        exp["id"],
        {"account_id": cash_id, "amount": "500.00", "tx_date": "2026-11-05"},
    )
    nov = analytics_service.get_full_analytics_report(
        isolated_db, preset="current_month", today=date(2026, 11, 15)
    )
    assert nov["summary"]["gross_expense_minor"] == 0
    assert nov["summary"]["refund_minor"] == 50_000
    assert nov["summary"]["net_expense_minor"] == -50_000
    cat_row = [c for c in nov["categories"] if c["category_id"] == exp_cat][0]
    assert cat_row["net_minor"] == -50_000
    assert cat_row["doughnut_eligible"] is False


@pytest.mark.unit
def test_scenario_e_zero_income_savings_rate_unavailable(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "1000.00",
            "tx_date": "2026-11-10",
        },
    )
    rep = analytics_service.get_full_analytics_report(
        isolated_db, preset="current_month", today=date(2026, 11, 20)
    )
    assert rep["summary"]["income_minor"] == 0
    assert rep["summary"]["surplus_minor"] == -100_000
    assert rep["summary"]["savings_rate_available"] is False
    assert rep["summary"]["savings_rate_percent"] is None
