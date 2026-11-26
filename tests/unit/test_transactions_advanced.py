"""Unit & scenario tests for editing, soft-delete/restore, refunds, splits, search, and bulk ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import account_service, overview_service, transaction_service
from app.utils.errors import ConflictError, ValidationError


@pytest.mark.unit
def test_scenario_a_basic_cash_flow(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    inc_cat = transaction_service.list_categories(isolated_db, kind="income")[0]["id"]
    exp_cat = transaction_service.list_categories(isolated_db, kind="expense")[0]["id"]

    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "income",
            "account_id": cash_id,
            "category_id": inc_cat,
            "amount": "10000",
            "tx_date": "2026-11-01",
            "description": "Grant",
        },
    )
    for amt in ("250.50", "1499", "150"):
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": cash_id,
                "category_id": exp_cat,
                "amount": amt,
                "tx_date": "2026-11-10",
            },
        )

    ov = overview_service.get_overview(isolated_db, month="2026-11")
    assert ov["month"]["income_minor"] == 1_000_000
    assert ov["month"]["net_expense_minor"] == 189_950
    assert ov["total_balance_minor"] == 810_050
    assert ov["month"]["surplus_minor"] == 810_050


@pytest.mark.unit
def test_scenario_d_partial_refunds_cross_month_and_delete_guards(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = transaction_service.list_categories(isolated_db, kind="expense")[0]["id"]

    expense, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "1000.00",
            "tx_date": "2026-10-20",
            "merchant": "Flipkart",
            "description": "Headphones",
        },
    )
    r1, _ = transaction_service.create_refund(
        isolated_db, expense["id"], {"amount": "300.00", "tx_date": "2026-11-02"}
    )
    r2, _ = transaction_service.create_refund(
        isolated_db, expense["id"], {"amount": "200.00", "tx_date": "2026-11-05"}
    )
    assert r1["entry_type"] == "refund" and r2["entry_type"] == "refund"

    info = transaction_service.list_refunds_for_transaction(isolated_db, expense["id"])
    assert info["total_refunded_minor"] == 50_000
    assert info["remaining_refundable_minor"] == 50_000

    # ₹501 extra refund exceeds remaining ₹500 -> rejected
    with pytest.raises(ValidationError) as exc:
        transaction_service.create_refund(
            isolated_db, expense["id"], {"amount": "501.00", "tx_date": "2026-11-10"}
        )
    assert exc.value.status_code == 422

    # Deleting parent while active refund exists -> blocked
    with pytest.raises(ConflictError):
        transaction_service.soft_delete_transaction(isolated_db, expense["id"])

    # Shrinking parent below active ₹500 refunded -> blocked
    with pytest.raises(ConflictError):
        transaction_service.update_transaction(isolated_db, expense["id"], {"amount": "450.00"})

    # Cross-month check: Oct shows ₹1,000 gross/net spend; Nov shows ₹500 refunds (-₹500 net spend)
    oct_ov = overview_service.get_overview(isolated_db, month="2026-10")
    nov_ov = overview_service.get_overview(isolated_db, month="2026-11")
    assert oct_ov["month"]["gross_expense_minor"] == 100_000
    assert oct_ov["month"]["net_expense_minor"] == 100_000
    assert nov_ov["month"]["refunds_minor"] == 50_000
    assert nov_ov["month"]["net_expense_minor"] == -50_000
    assert nov_ov["total_balance_minor"] == -50_000  # Net cash impact = -₹1000 + ₹500 = -₹500

    # Soft-deleting r2 (₹200) allows a replacement ₹600 refund (total ₹900), which then blocks restoring r2!
    transaction_service.soft_delete_transaction(isolated_db, r2["id"])
    transaction_service.create_refund(
        isolated_db, expense["id"], {"amount": "600.00", "tx_date": "2026-11-12"}
    )
    with pytest.raises(ConflictError):
        transaction_service.restore_transaction(isolated_db, r2["id"])


@pytest.mark.unit
def test_scenario_e_split_transaction_and_split_refund(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    cats = {
        c["slug"]: c["id"] for c in transaction_service.list_categories(isolated_db, kind="expense")
    }

    # Exact ₹1,000 split mismatch must fail
    with pytest.raises(ValidationError):
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": cash_id,
                "amount": "1000.00",
                "tx_date": "2026-11-14",
                "splits": [
                    {"category_id": cats["food_dining"], "amount": "650.00"},
                    {"category_id": cats["shopping"], "amount": "200.00"},
                ],
            },
        )

    split_tx, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "amount": "1000.00",
            "tx_date": "2026-11-14",
            "merchant": "Supermarket",
            "splits": [
                {"category_id": cats["food_dining"], "amount": "650.00"},
                {"category_id": cats["shopping"], "amount": "250.00"},
                {"category_id": cats["miscellaneous"], "amount": "100.00"},
            ],
        },
    )
    assert split_tx["is_split"] is True
    assert split_tx["amount_minor"] == 100_000
    assert len(split_tx["postings"]) == 3
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 1
    assert account_service.list_accounts(isolated_db)["accounts"][0]["balance_minor"] == -100_000

    # Split refund exceeding one category's allocation (₹101 against ₹100 Misc) must be rejected
    with pytest.raises(ValidationError) as exc:
        transaction_service.create_refund(
            isolated_db,
            split_tx["id"],
            {
                "amount": "101.00",
                "tx_date": "2026-11-16",
                "allocations": [{"category_id": cats["miscellaneous"], "amount": "101.00"}],
            },
        )
    assert exc.value.status_code == 422

    # Valid split refund across Shopping (₹150) & Misc (₹50)
    ref_tx, _ = transaction_service.create_refund(
        isolated_db,
        split_tx["id"],
        {
            "amount": "200.00",
            "tx_date": "2026-11-16",
            "allocations": [
                {"category_id": cats["shopping"], "amount": "150.00"},
                {"category_id": cats["miscellaneous"], "amount": "50.00"},
            ],
        },
    )
    assert ref_tx["amount_minor"] == 20_000
    assert account_service.list_accounts(isolated_db)["accounts"][0]["balance_minor"] == -80_000


@pytest.mark.unit
def test_scenario_f_and_g_edit_revision_delete_restore_and_purge(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    bank = account_service.create_account(
        isolated_db, {"name": "HDFC", "account_type": "bank", "opening_balance": "0"}
    )
    cats = transaction_service.list_categories(isolated_db, kind="expense")
    c1, c2 = cats[0]["id"], cats[1]["id"]

    tx, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": c1,
            "amount": "500.00",
            "tx_date": "2026-11-10",
            "description": "Original",
        },
    )
    assert tx["revision"] == 1

    # Scenario F: edit ₹500 -> ₹650, move account Cash -> HDFC, change category & month
    edited = transaction_service.update_transaction(
        isolated_db,
        tx["id"],
        {
            "expected_revision": 1,
            "account_id": bank["id"],
            "category_id": c2,
            "amount": "650.00",
            "tx_date": "2026-10-31",
            "description": "Updated",
        },
    )
    assert edited["revision"] == 2
    assert edited["amount_minor"] == 65_000
    assert edited["account_id"] == bank["id"]
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 1

    # Stale revision rejected
    with pytest.raises(ConflictError) as rev_err:
        transaction_service.update_transaction(
            isolated_db, tx["id"], {"expected_revision": 1, "amount": "700.00"}
        )
    assert rev_err.value.code == "revision_conflict"

    # Scenario G: soft-delete removes ₹650 from active totals; restore brings it back once
    deleted = transaction_service.soft_delete_transaction(isolated_db, tx["id"])
    assert deleted["deleted_at"] is not None
    assert (
        account_service.get_account_detail(isolated_db, bank["id"])["account"]["balance_minor"] == 0
    )
    assert (
        overview_service.get_overview(isolated_db, month="2026-10")["month"]["net_expense_minor"]
        == 0
    )

    restored = transaction_service.restore_transaction(isolated_db, tx["id"])
    assert restored["deleted_at"] is None
    assert (
        account_service.get_account_detail(isolated_db, bank["id"])["account"]["balance_minor"]
        == -65_000
    )
    assert (
        overview_service.get_overview(isolated_db, month="2026-10")["month"]["net_expense_minor"]
        == 65_000
    )

    # Permanent purge requires soft delete first
    with pytest.raises(ConflictError):
        transaction_service.purge_transaction(isolated_db, tx["id"])
    transaction_service.soft_delete_transaction(isolated_db, tx["id"])
    purged = transaction_service.purge_transaction(isolated_db, tx["id"])
    assert purged["deleted_permanently"] is True
    assert transaction_service.list_transactions(isolated_db, deleted="all")["total_count"] == 0


@pytest.mark.unit
def test_search_filter_sort_pagination_and_atomic_bulk_rollback(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    bank = account_service.create_account(
        isolated_db, {"name": "Axis Bank", "account_type": "bank", "opening_balance": "5000"}
    )
    exp_cats = transaction_service.list_categories(isolated_db, kind="expense")
    inc_cats = transaction_service.list_categories(isolated_db, kind="income")

    t1, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cats[0]["id"],
            "amount": "150.00",
            "tx_date": "2026-11-05",
            "merchant": "Café ₹ O'Connor_100%",
            "payment_method": "upi",
        },
    )
    t2, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": bank["id"],
            "category_id": exp_cats[0]["id"],
            "amount": "900.00",
            "tx_date": "2026-11-06",
            "merchant": "Metro Mart",
            "payment_method": "debit_card",
        },
    )
    t3, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "income",
            "account_id": bank["id"],
            "category_id": inc_cats[0]["id"],
            "amount": "3000.00",
            "tx_date": "2026-11-06",
            "merchant": "Stipend Desk",
        },
    )

    # SQL injection payload & LIKE wildcard test
    res_sqli = transaction_service.list_transactions(
        isolated_db, query="'; DROP TABLE transactions; --"
    )
    assert res_sqli["total_count"] == 0
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 3

    res_like = transaction_service.list_transactions(isolated_db, query="O'Connor_100%")
    assert [r["id"] for r in res_like["transactions"]] == [t1["id"]]

    # Combined filters + amount sort + pagination
    res_sorted = transaction_service.list_transactions(
        isolated_db, sort="amount_desc", limit=2, offset=0
    )
    assert [r["id"] for r in res_sorted["transactions"]] == [t3["id"], t2["id"]]
    res_page2 = transaction_service.list_transactions(
        isolated_db, sort="amount_desc", limit=2, offset=2
    )
    assert [r["id"] for r in res_page2["transactions"]] == [t1["id"]]

    # Atomic bulk failure: trying to set expense category on selection containing t3 (income) -> rolls back ALL
    with pytest.raises(ValidationError):
        transaction_service.bulk_action(
            isolated_db,
            {
                "action": "set_category",
                "transaction_ids": [t1["id"], t3["id"]],
                "category_id": exp_cats[1]["id"],
            },
        )
    assert (
        transaction_service.get_transaction_detail(isolated_db, t1["id"])["category_id"]
        == exp_cats[0]["id"]
    )

    # Valid bulk category change on t1 + t2
    bulk_ok = transaction_service.bulk_action(
        isolated_db,
        {
            "action": "set_category",
            "transaction_ids": [t1["id"], t2["id"]],
            "category_id": exp_cats[1]["id"],
        },
    )
    assert bulk_ok["affected_count"] == 2
    assert (
        transaction_service.get_transaction_detail(isolated_db, t2["id"])["category_id"]
        == exp_cats[1]["id"]
    )
