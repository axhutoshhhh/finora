"""Unit & accounting tests for financial accounts, transfers, credit cards, and Scenario B/C/I."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.repositories import transactions_repo
from app.services import account_service, overview_service, transaction_service
from app.utils.errors import ConflictError, NotFoundError, ValidationError


@pytest.mark.unit
def test_scenario_b_internal_transfer_bank_to_cash(isolated_db: Path) -> None:
    # Seed Cash to ₹2,000 via opening balance adjustment and create Bank with ₹10,000
    cash = account_service.list_accounts(isolated_db)["accounts"][0]
    account_service.update_account(isolated_db, cash["id"], {"opening_balance": "2000.00"})
    bank = account_service.create_account(
        isolated_db,
        {
            "name": "HDFC Bank",
            "account_type": "bank",
            "opening_balance": "10000.00",
            "opening_balance_date": "2026-11-01",
        },
    )

    xfer, created = transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cash["id"],
            "amount": "1000.00",
            "tx_date": "2026-11-15",
            "description": "ATM withdrawal",
            "idempotency_key": "xfer-b-1",
        },
    )
    assert created is True
    assert xfer["entry_type"] == "transfer"
    assert xfer["amount_minor"] == 100_000

    # Idempotency replay
    xfer_dup, created_dup = transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cash["id"],
            "amount": "1000.00",
            "tx_date": "2026-11-15",
            "description": "ATM withdrawal",
            "idempotency_key": "xfer-b-1",
        },
    )
    assert created_dup is False
    assert xfer_dup["id"] == xfer["id"]

    acct_state = account_service.list_accounts(isolated_db)
    by_id = {a["id"]: a for a in acct_state["accounts"]}
    assert by_id[bank["id"]]["balance_minor"] == 900_000  # ₹9,000
    assert by_id[cash["id"]]["balance_minor"] == 300_000  # ₹3,000
    assert acct_state["summary"]["total_assets_minor"] == 1_200_000  # ₹12,000
    assert acct_state["summary"]["net_worth_minor"] == 1_200_000

    overview = overview_service.get_overview(isolated_db, month="2026-11")
    # Opening balances & transfers must NEVER inflate monthly income or expenses
    assert overview["month"]["income_minor"] == 0
    assert overview["month"]["expense_minor"] == 0
    assert overview["positions"]["total_assets_minor"] == 1_200_000


@pytest.mark.unit
def test_scenario_c_and_credit_card_overpayment_and_limits(isolated_db: Path) -> None:
    bank = account_service.create_account(
        isolated_db,
        {
            "name": "Salary Bank",
            "account_type": "bank",
            "opening_balance": "9000.00",
        },
    )
    cc = account_service.create_account(
        isolated_db,
        {
            "name": "Millennia Card",
            "account_type": "credit_card",
            "opening_balance": "0.00",
            "credit_limit": "50000.00",
        },
    )
    exp_cat_id = transaction_service.list_categories(isolated_db, kind="expense")[0]["id"]

    # Purchase ₹2,000 on Credit Card
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cc["id"],
            "category_id": exp_cat_id,
            "amount": "2000.00",
            "tx_date": "2026-11-10",
            "description": "Electronics purchase",
            "payment_method": "credit_card",
        },
    )

    # Partial repayment ₹1,500 from Bank -> Credit Card
    repay, _ = transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cc["id"],
            "amount": "1500.00",
            "tx_date": "2026-11-20",
            "description": "CC Bill Pay",
        },
    )
    assert repay["transfer_subtype"] == "credit_card_repayment"

    ov = overview_service.get_overview(isolated_db, month="2026-11")
    # Recorded expense is strictly ₹2,000; ₹1,500 repayment does NOT add expense
    assert ov["month"]["expense_minor"] == 200_000
    assert ov["positions"]["total_assets_minor"] == 750_000  # Bank ₹9,000 - ₹1,500 = ₹7,500
    assert ov["positions"]["total_liabilities_minor"] == 50_000  # ₹500 owed
    assert ov["positions"]["net_worth_minor"] == 700_000  # ₹7,500 - ₹500 = ₹7,000

    cc_detail = account_service.get_account_detail(isolated_db, cc["id"])["account"]
    assert cc_detail["outstanding_liability_minor"] == 50_000
    assert cc_detail["available_credit_minor"] == 4_950_000
    assert cc_detail["utilization_percent"] == 1.0

    # Overpay card by ₹700 (₹200 positive credit balance surplus)
    transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank["id"],
            "to_account_id": cc["id"],
            "amount": "700.00",
            "tx_date": "2026-11-21",
            "description": "Extra card payment",
        },
    )
    cc_overpaid = account_service.get_account_detail(isolated_db, cc["id"])["account"]
    assert cc_overpaid["outstanding_liability_minor"] == 0
    assert cc_overpaid["credit_balance_surplus_minor"] == 20_000
    assert cc_overpaid["balance_minor"] == 20_000

    # Outbound transfer from Credit Card must be explicitly blocked
    with pytest.raises(ValidationError) as exc:
        transaction_service.create_transfer(
            isolated_db,
            {
                "from_account_id": cc["id"],
                "to_account_id": bank["id"],
                "amount": "100.00",
                "tx_date": "2026-11-22",
            },
        )
    assert exc.value.status_code == 422


@pytest.mark.unit
def test_scenario_i_failed_transfer_rolls_back_atomically(isolated_db: Path) -> None:
    cash = account_service.list_accounts(isolated_db)["accounts"][0]
    account_service.update_account(isolated_db, cash["id"], {"opening_balance": "5000.00"})
    bank = account_service.create_account(
        isolated_db,
        {"name": "Savings", "account_type": "savings", "opening_balance": "1000.00"},
    )

    real_insert = transactions_repo.create_multi_posting_transaction

    def failing_mid_transfer(conn, **kwargs):
        real_insert(conn, **kwargs)
        raise RuntimeError("Simulated mid-transfer failure after postings")

    with (
        patch.object(
            transactions_repo, "create_multi_posting_transaction", side_effect=failing_mid_transfer
        ),
        pytest.raises(RuntimeError, match="Simulated mid-transfer failure"),
    ):
        transaction_service.create_transfer(
            isolated_db,
            {
                "from_account_id": cash["id"],
                "to_account_id": bank["id"],
                "amount": "500.00",
                "tx_date": "2026-11-25",
            },
        )

    accts = {a["id"]: a for a in account_service.list_accounts(isolated_db)["accounts"]}
    assert accts[cash["id"]]["balance_minor"] == 500_000
    assert accts[bank["id"]]["balance_minor"] == 100_000
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 0


@pytest.mark.unit
def test_account_types_archiving_type_lock_and_negative_warning(isolated_db: Path) -> None:
    wallet = account_service.create_account(
        isolated_db,
        {"name": "UPI Wallet", "account_type": "wallet", "opening_balance": "1500.00"},
    )
    savings = account_service.create_account(
        isolated_db,
        {"name": "Emergency Savings", "account_type": "savings", "opening_balance": "0"},
    )
    assert wallet["account_type"] == "wallet"
    assert savings["account_type"] == "savings"

    exp_cat_id = transaction_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": savings["id"],
            "category_id": exp_cat_id,
            "amount": "250.00",
            "tx_date": "2026-11-20",
        },
    )
    savings_detail = account_service.get_account_detail(isolated_db, savings["id"])["account"]
    assert savings_detail["balance_minor"] == -25_000
    assert savings_detail["negative_balance_warning"] is True

    # Cannot change account_type once postings exist
    with pytest.raises(ConflictError):
        account_service.update_account(isolated_db, savings["id"], {"account_type": "bank"})

    # Nonzero account archival requires explicit confirm_nonzero=True
    with pytest.raises(ConflictError) as exc:
        account_service.archive_account(isolated_db, wallet["id"], confirm_nonzero=False)
    assert exc.value.code == "confirm_nonzero_archive"

    archived = account_service.archive_account(isolated_db, wallet["id"], confirm_nonzero=True)
    assert archived["is_archived"] is True

    # Archived account cannot receive new transactions or transfers
    with pytest.raises(NotFoundError):
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": wallet["id"],
                "category_id": exp_cat_id,
                "amount": "50.00",
                "tx_date": "2026-11-25",
            },
        )

    # Historical balance stays represented in total_assets_minor
    summary = account_service.list_accounts(isolated_db)["summary"]
    assert summary["total_assets_minor"] == 125_000  # Wallet ₹1,500 + Savings -₹250

    restored = account_service.restore_account(isolated_db, wallet["id"])
    assert restored["is_archived"] is False

    # Updating opening_balance_direction alone on a credit card preserves existing absolute opening balance
    cc = account_service.create_account(
        isolated_db,
        {
            "name": "Axis Card",
            "account_type": "credit_card",
            "opening_balance": "1500.00",
            "opening_balance_direction": "debt",
            "credit_limit": "50000.00",
        },
    )
    assert cc["opening_balance_minor"] == -150_000
    flipped = account_service.update_account(
        isolated_db,
        cc["id"],
        {"opening_balance_direction": "credit"},
    )
    assert flipped["opening_balance_minor"] == 150_000
