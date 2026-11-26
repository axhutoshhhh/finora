"""Overview summary and recent activity service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, transactions_repo
from app.services import account_service
from app.services.transaction_service import group_and_serialize_transaction_rows
from app.utils.money import format_inr_minor, validate_aggregate_minor
from app.utils.time import resolve_month_bounds


def get_overview(
    db_path: Path | str,
    *,
    month: str | None = None,
    recent_limit: int = 8,
) -> dict[str, Any]:
    """Compute authoritative balances, monthly totals, accounts, and recent activity."""
    month_key, month_label, start_date, end_date_exclusive = resolve_month_bounds(month)
    bounded_limit = max(1, min(recent_limit, 25))

    with db_session(db_path) as conn:
        conn.execute("BEGIN DEFERRED;")
        all_accounts = accounts_repo.list_accounts_with_balances(conn, include_archived=True)
        positions = account_service.compute_financial_positions(all_accounts)
        active_accounts = [
            account_service.serialize_account_row(r)
            for r in all_accounts
            if int(r["is_archived"]) == 0
        ]
        income_minor, gross_expense_minor, refunds_minor = (
            transactions_repo.get_month_summary_detailed(
                conn,
                start_date=start_date,
                end_date_exclusive=end_date_exclusive,
            )
        )
        net_expense_minor = gross_expense_minor - refunds_minor
        surplus_minor = income_minor - net_expense_minor
        total_tx_count = transactions_repo.count_transactions(conn)
        recent_rows = transactions_repo.list_transactions(conn, limit=bounded_limit, offset=0)

    validate_aggregate_minor(income_minor, label="Monthly income")
    validate_aggregate_minor(gross_expense_minor, label="Monthly gross expenses")
    validate_aggregate_minor(net_expense_minor, label="Monthly net expenses")
    validate_aggregate_minor(surplus_minor, label="Monthly surplus")

    return {
        "currency": "INR",
        "total_balance_minor": positions["net_worth_minor"],
        "total_balance_formatted": positions["net_worth_formatted"],
        "positions": positions,
        "accounts_summary": active_accounts,
        "month": {
            "key": month_key,
            "label": month_label,
            "income_minor": income_minor,
            "income_formatted": format_inr_minor(income_minor),
            "gross_expense_minor": gross_expense_minor,
            "gross_expense_formatted": format_inr_minor(gross_expense_minor),
            "refunds_minor": refunds_minor,
            "refunds_formatted": format_inr_minor(refunds_minor),
            "expense_minor": net_expense_minor,
            "expense_formatted": format_inr_minor(net_expense_minor),
            "net_expense_minor": net_expense_minor,
            "net_expense_formatted": format_inr_minor(net_expense_minor),
            "surplus_minor": surplus_minor,
            "surplus_formatted": format_inr_minor(surplus_minor, show_plus=True),
        },
        "has_transactions": total_tx_count > 0,
        "transaction_count": total_tx_count,
        "recent_transactions": group_and_serialize_transaction_rows(recent_rows),
    }
