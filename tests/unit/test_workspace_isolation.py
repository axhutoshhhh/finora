"""Unit tests for Phase 3 isolated demonstration workspace (Scenario L)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import account_service, category_service, transaction_service, workspace_service


@pytest.mark.unit
def test_scenario_l_workspace_isolation_and_demo_reset(isolated_db: Path) -> None:
    data_dir = isolated_db.parent
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "123.00",
            "tx_date": "2026-11-10",
            "description": "Real user record",
        },
    )

    _, demo_db = workspace_service.get_workspace_paths(data_dir, workspace="demo")
    workspace_service.seed_demo_workspace(demo_db)
    assert transaction_service.list_transactions(demo_db)["total_count"] > 200
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 1

    # Resetting demo must not affect primary DB
    workspace_service.reset_demo_workspace(data_dir)
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 1
    assert transaction_service.list_transactions(demo_db)["total_count"] > 200
