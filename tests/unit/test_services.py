"""Service-layer tests covering transactions, overview math, idempotency, and settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import overview_service, settings_service, transaction_service
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from tests.fixtures.sample_transactions import SYNTHETIC_TRANSACTIONS


@pytest.mark.unit
def test_transaction_and_overview_lifecycle(isolated_db: Path) -> None:
    accounts = transaction_service.list_accounts(isolated_db)
    assert len(accounts) == 1
    cash_id = accounts[0]["id"]

    exp_cats = {
        c["slug"]: c["id"] for c in transaction_service.list_categories(isolated_db, kind="expense")
    }
    inc_cats = {
        c["slug"]: c["id"] for c in transaction_service.list_categories(isolated_db, kind="income")
    }
    assert len(exp_cats) == 10
    assert len(inc_cats) == 7

    for idx, sample in enumerate(SYNTHETIC_TRANSACTIONS):
        entry_type = str(sample["entry_type"])
        cat_map = inc_cats if entry_type == "income" else exp_cats
        tx, created = transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": entry_type,
                "account_id": cash_id,
                "category_id": cat_map[str(sample["category_slug"])],
                "amount": sample["amount"],
                "tx_date": sample["tx_date"],
                "description": sample["description"],
                "idempotency_key": f"seed-key-{idx}",
            },
        )
        assert created is True
        assert tx["entry_type"] == entry_type

    # Income: 85000.00 + 12500.75 = 97500.75 (9750075 minor)
    # Expense: 24500.00 + 645.50 + 1499.00 + 320.25 = 26964.75 (2696475 minor)
    # Balance / Surplus: 97500.75 - 26964.75 = 70536.00 (7053600 minor)
    overview = overview_service.get_overview(isolated_db, month="2026-11")
    assert overview["total_balance_minor"] == 7_053_600
    assert overview["total_balance_formatted"] == "₹70,536.00"
    assert overview["month"]["income_minor"] == 9_750_075
    assert overview["month"]["expense_minor"] == 2_696_475
    assert overview["month"]["surplus_minor"] == 7_053_600
    assert overview["month"]["surplus_formatted"] == "+₹70,536.00"
    assert overview["transaction_count"] == len(SYNTHETIC_TRANSACTIONS)


@pytest.mark.unit
def test_idempotency_and_category_kind_validation(isolated_db: Path) -> None:
    cash_id = transaction_service.list_accounts(isolated_db)[0]["id"]
    expense_cat_id = transaction_service.list_categories(isolated_db, kind="expense")[0]["id"]
    income_cat_id = transaction_service.list_categories(isolated_db, kind="income")[0]["id"]

    # Reject expense using income category
    with pytest.raises(ValidationError) as exc_info:
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": cash_id,
                "category_id": income_cat_id,
                "amount": "150.00",
                "tx_date": "2026-11-26",
            },
        )
    assert exc_info.value.status_code == 422

    # Reject unknown account
    with pytest.raises(NotFoundError):
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": 999,
                "category_id": expense_cat_id,
                "amount": "150.00",
                "tx_date": "2026-11-26",
            },
        )

    payload = {
        "entry_type": "expense",
        "account_id": cash_id,
        "category_id": expense_cat_id,
        "amount": "200.00",
        "tx_date": "2026-11-26",
        "description": "Coffee beans",
        "idempotency_key": "req-123",
    }
    first, created1 = transaction_service.create_transaction(isolated_db, payload)
    second, created2 = transaction_service.create_transaction(isolated_db, payload)
    assert created1 is True
    assert created2 is False
    assert first["id"] == second["id"]

    # Reusing the same idempotency key with different amount must conflict
    with pytest.raises(ConflictError):
        transaction_service.create_transaction(
            isolated_db,
            {**payload, "amount": "250.00"},
        )


@pytest.mark.unit
def test_settings_appearance_persistence(isolated_db: Path, tmp_path: Path) -> None:
    assert settings_service.get_appearance(isolated_db) == "system"
    updated = settings_service.update_appearance(isolated_db, "dark")
    assert updated == {"appearance": "dark", "color_scheme_meta": "dark"}
    assert settings_service.get_appearance(isolated_db) == "dark"

    with pytest.raises(ValidationError):
        settings_service.update_appearance(isolated_db, "neon-purple")

    full = settings_service.get_settings(isolated_db, app_version="0.1.0", data_dir=tmp_path)
    assert full["appearance"] == "dark"
    assert full["currency"] == "INR"
