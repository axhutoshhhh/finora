"""Isolated demonstration workspace management and deterministic synthetic data seeding."""

from __future__ import annotations

import os
import shutil
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.migrations.runner import initialize_database
from app.services import (
    account_service,
    advisory_service,
    budget_service,
    categorization_service,
    category_service,
    goal_service,
    recurring_service,
    transaction_service,
)
from app.utils.errors import ValidationError

_WORKSPACE_LOCK = threading.RLock()


def get_workspace_paths(data_dir: Path, *, workspace: str) -> tuple[Path, Path]:
    """Return (workspace_dir, db_path) for 'primary' or 'demo'."""
    if workspace == "primary":
        return data_dir, data_dir / "finance.sqlite3"
    if workspace == "demo":
        demo_dir = data_dir / "workspaces" / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(demo_dir, 0o700)
        return demo_dir, demo_dir / "finance.sqlite3"
    raise ValidationError("Workspace must be 'primary' or 'demo'.", field="workspace")


def seed_demo_workspace(demo_db: Path, *, today: date | None = None) -> None:
    """Populate an isolated demo database with ~240 realistic synthetic records."""
    with _WORKSPACE_LOCK:
        _seed_demo_workspace_locked(demo_db, today=today)


def _seed_demo_workspace_locked(demo_db: Path, *, today: date | None = None) -> None:
    ref = today or date.today()
    initialize_database(demo_db)

    # Check if already seeded
    if transaction_service.list_transactions(demo_db)["total_count"] > 0:
        return

    cash_id = account_service.list_accounts(demo_db)["accounts"][0]["id"]
    bank = account_service.create_account(
        demo_db, {"name": "HDFC Savings", "account_type": "bank", "opening_balance": "85000.00"}
    )
    sav = account_service.create_account(
        demo_db,
        {"name": "Emergency Vault", "account_type": "savings", "opening_balance": "120000.00"},
    )
    wallet = account_service.create_account(
        demo_db, {"name": "UPI Wallet", "account_type": "wallet", "opening_balance": "4500.00"}
    )
    cc = account_service.create_account(
        demo_db,
        {
            "name": "Axis Ace Card",
            "account_type": "credit_card",
            "opening_balance": "0",
            "credit_limit": "100000.00",
        },
    )

    exp_cats = category_service.list_categories(demo_db, kind="expense")
    inc_cats = category_service.list_categories(demo_db, kind="income")
    sal_cat = inc_cats[0]["id"]

    # 8 months of salary + ~28 expenses/month = ~232 transactions
    merchants = ["Swiggy", "Uber", "BigBasket", "Airtel", "Amazon", "BookMyShow", "Apollo Pharmacy"]
    for m_off in range(7, -1, -1):
        d_anchor = ref.replace(day=1) - timedelta(days=30 * m_off)
        sal_date = min(ref, d_anchor.replace(day=1))
        transaction_service.create_transaction(
            demo_db,
            {
                "entry_type": "income",
                "account_id": bank["id"],
                "category_id": sal_cat,
                "amount": "75000.00",
                "tx_date": sal_date.isoformat(),
                "merchant": "Acme Tech Pvt Ltd",
                "description": "Monthly salary",
            },
        )
        for i in range(28):
            tx_d = d_anchor.replace(day=min(28, (i % 27) + 1))
            if tx_d > ref:
                tx_d = ref
            cat = exp_cats[i % len(exp_cats)]
            acct_id = [bank["id"], wallet["id"], cc["id"], cash_id][i % 4]
            amt = f"{180 + (i * 47) % 1800}.00"
            transaction_service.create_transaction(
                demo_db,
                {
                    "entry_type": "expense",
                    "account_id": acct_id,
                    "category_id": cat["id"],
                    "amount": amt,
                    "tx_date": tx_d.isoformat(),
                    "merchant": merchants[i % len(merchants)],
                    "description": f"{cat['name']} spend",
                },
            )

    # Transfer & CC repayment
    transaction_service.create_transfer(
        demo_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cc["id"],
            "amount": "6000.00",
            "tx_date": ref.isoformat(),
            "description": "Credit card bill payment",
        },
    )

    # Budgets for current month
    cur_m = ref.strftime("%Y-%m")
    budget_service.set_overall_budget(demo_db, {"month": cur_m, "limit": "45000.00"})
    budget_service.set_category_budget(
        demo_db, {"month": cur_m, "category_id": exp_cats[0]["id"], "limit": "8000.00"}
    )

    # Savings goals
    g1 = goal_service.create_goal(
        demo_db,
        {
            "name": "Emergency Fund",
            "target_amount": "200000.00",
            "account_id": sav["id"],
            "target_date": (ref + timedelta(days=180)).isoformat(),
        },
    )
    goal_service.add_contribution(
        demo_db, g1["id"], {"amount": "50000.00", "allocation_date": ref.isoformat()}
    )

    # Recurring & Subscriptions
    recurring_service.create_rule(
        demo_db,
        {
            "name": "Streaming Plan",
            "entry_type": "expense",
            "is_subscription": True,
            "amount": "499.00",
            "account_id": cc["id"],
            "category_id": exp_cats[0]["id"],
            "merchant": "StreamFlix",
            "frequency": "monthly",
            "start_date": ref.isoformat(),
        },
    )

    # Categorization rule
    categorization_service.create_rule(
        demo_db,
        {
            "name": "Swiggy -> Food",
            "match_field": "merchant",
            "match_type": "contains",
            "pattern": "Swiggy",
            "entry_type": "expense",
            "target_category_id": exp_cats[0]["id"],
            "priority": 10,
        },
    )

    advisory_service.evaluate_advisories(demo_db, month=cur_m, today=ref)


def reset_demo_workspace(data_dir: Path) -> dict[str, Any]:
    with _WORKSPACE_LOCK:
        demo_dir = data_dir / "workspaces" / "demo"
        if demo_dir.exists():
            shutil.rmtree(demo_dir)
        _, demo_db = get_workspace_paths(data_dir, workspace="demo")
        seed_demo_workspace(demo_db)
        return {"reset": True, "workspace": "demo"}
