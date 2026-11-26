"""Property-style deterministic invariant tests across multi-step ledger sequences."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.database import db_session
from app.services import account_service, overview_service, transaction_service
from app.utils.errors import ValidationError


@pytest.mark.unit
def test_random_ledger_sequence_preserves_double_entry_invariants(isolated_db: Path) -> None:
    rng = random.Random(20261126)  # noqa: S311 - deterministic synthetic test sequence
    cash = account_service.list_accounts(isolated_db)["accounts"][0]
    bank = account_service.create_account(
        isolated_db, {"name": "HDFC Bank", "account_type": "bank", "opening_balance": "50000"}
    )
    cc = account_service.create_account(
        isolated_db,
        {
            "name": "Axis Card",
            "account_type": "credit_card",
            "opening_balance": "0",
            "credit_limit": "100000",
        },
    )
    asset_ids = [cash["id"], bank["id"]]
    all_ids = [cash["id"], bank["id"], cc["id"]]
    exp_cats = [c["id"] for c in transaction_service.list_categories(isolated_db, kind="expense")]
    inc_cats = [c["id"] for c in transaction_service.list_categories(isolated_db, kind="income")]

    created_expenses: list[tuple[int, int]] = []

    for step in range(45):
        day = f"2026-11-{(step % 25) + 1:02d}"
        roll = rng.random()
        if roll < 0.30:
            # Income onto random asset
            amt_paise = rng.randint(1000, 200_000)
            transaction_service.create_transaction(
                isolated_db,
                {
                    "entry_type": "income",
                    "account_id": rng.choice(asset_ids),
                    "category_id": rng.choice(inc_cats),
                    "amount": f"{amt_paise // 100}.{amt_paise % 100:02d}",
                    "tx_date": day,
                },
            )
        elif roll < 0.65:
            # Expense (possibly split) on any account
            amt_paise = rng.randint(500, 50_000)
            acct = rng.choice(all_ids)
            if step % 4 == 0 and amt_paise >= 400:
                part1 = amt_paise // 2
                part2 = amt_paise - part1
                c1, c2 = rng.sample(exp_cats, 2)
                tx, _ = transaction_service.create_transaction(
                    isolated_db,
                    {
                        "entry_type": "expense",
                        "account_id": acct,
                        "amount": f"{amt_paise // 100}.{amt_paise % 100:02d}",
                        "tx_date": day,
                        "splits": [
                            {"category_id": c1, "amount": f"{part1 // 100}.{part1 % 100:02d}"},
                            {"category_id": c2, "amount": f"{part2 // 100}.{part2 % 100:02d}"},
                        ],
                    },
                )
            else:
                tx, _ = transaction_service.create_transaction(
                    isolated_db,
                    {
                        "entry_type": "expense",
                        "account_id": acct,
                        "category_id": rng.choice(exp_cats),
                        "amount": f"{amt_paise // 100}.{amt_paise % 100:02d}",
                        "tx_date": day,
                    },
                )
                created_expenses.append((tx["id"], amt_paise))
        elif roll < 0.85:
            # Internal transfer / CC repayment MUST preserve exact net worth
            before_ov = overview_service.get_overview(isolated_db, month="2026-11")
            src = rng.choice(asset_ids)
            dst = rng.choice([a for a in all_ids if a != src])
            amt_paise = rng.randint(100, 20_000)
            tx, _ = transaction_service.create_transfer(
                isolated_db,
                {
                    "from_account_id": src,
                    "to_account_id": dst,
                    "amount": f"{amt_paise // 100}.{amt_paise % 100:02d}",
                    "tx_date": day,
                },
            )
            after_ov = overview_service.get_overview(isolated_db, month="2026-11")
            assert (
                after_ov["positions"]["net_worth_minor"]
                == before_ov["positions"]["net_worth_minor"]
            )
            assert after_ov["month"]["income_minor"] == before_ov["month"]["income_minor"]
            assert after_ov["month"]["net_expense_minor"] == before_ov["month"]["net_expense_minor"]
        elif created_expenses:
            # Refund against an expense: partial valid + excessive rejected
            parent_id, parent_amt = rng.choice(created_expenses)
            ref_info = transaction_service.list_refunds_for_transaction(isolated_db, parent_id)
            refund_day = max(day, str(ref_info["original_transaction"]["tx_date"]))
            rem = ref_info["remaining_refundable_minor"]
            if rem > 0:
                ref_amt = max(1, rem // 2)
                transaction_service.create_refund(
                    isolated_db,
                    parent_id,
                    {"amount": f"{ref_amt // 100}.{ref_amt % 100:02d}", "tx_date": refund_day},
                )
                after_info = transaction_service.list_refunds_for_transaction(
                    isolated_db, parent_id
                )
                assert after_info["total_refunded_minor"] <= parent_amt
            else:
                with pytest.raises(ValidationError):
                    transaction_service.create_refund(
                        isolated_db, parent_id, {"amount": "1.00", "tx_date": refund_day}
                    )

    # Final database-level invariant verification
    ov = overview_service.get_overview(isolated_db, month="2026-11")
    acct_res = account_service.list_accounts(isolated_db, include_archived=True)
    assert ov["positions"]["net_worth_minor"] == acct_res["summary"]["net_worth_minor"]

    with db_session(isolated_db) as conn:
        # Every transfer sums to 0 across postings
        bad_xfers = conn.execute(
            """
            SELECT t.id, SUM(p.signed_amount_minor) AS s
            FROM transactions t
            JOIN postings p ON p.transaction_id = t.id
            WHERE t.entry_type = 'transfer'
            GROUP BY t.id
            HAVING s != 0;
            """
        ).fetchall()
        assert bad_xfers == []

        # Reversibility: soft-delete then restore any latest active transaction restores identical totals
        latest = transaction_service.list_transactions(isolated_db, limit=1)["transactions"][0]
        if latest["entry_type"] != "expense" or latest["refunded_minor"] == 0:
            snap_nw = ov["positions"]["net_worth_minor"]
            snap_exp = ov["month"]["net_expense_minor"]
            transaction_service.soft_delete_transaction(isolated_db, latest["id"])
            transaction_service.restore_transaction(isolated_db, latest["id"])
            ov_after = overview_service.get_overview(isolated_db, month="2026-11")
            assert ov_after["positions"]["net_worth_minor"] == snap_nw
            assert ov_after["month"]["net_expense_minor"] == snap_exp
