"""Overview summary and recent activity service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, transactions_repo
from app.services.transaction_service import serialize_transaction_row
from app.utils.money import format_inr_minor
from app.utils.time import resolve_month_bounds


def get_overview(
    db_path: Path | str,
    *,
    month: str | None = None,
    recent_limit: int = 8,
) -> dict[str, Any]:
    """Compute authoritative current balance, monthly totals, and recent activity."""
    month_key, month_label, start_date, end_date_exclusive = resolve_month_bounds(month)
    bounded_limit = max(1, min(recent_limit, 25))

    with db_session(db_path) as conn:
        conn.execute("BEGIN DEFERRED;")
        total_balance_minor = accounts_repo.get_total_balance_minor(conn)
        income_minor, expense_minor = transactions_repo.get_month_summary(
            conn,
            start_date=start_date,
            end_date_exclusive=end_date_exclusive,
        )
        surplus_minor = income_minor - expense_minor
        total_tx_count = transactions_repo.count_transactions(conn)
        recent_rows = transactions_repo.list_transactions(conn, limit=bounded_limit, offset=0)

    return {
        "currency": "INR",
        "total_balance_minor": total_balance_minor,
        "total_balance_formatted": format_inr_minor(total_balance_minor),
        "month": {
            "key": month_key,
            "label": month_label,
            "income_minor": income_minor,
            "income_formatted": format_inr_minor(income_minor),
            "expense_minor": expense_minor,
            "expense_formatted": format_inr_minor(expense_minor),
            "surplus_minor": surplus_minor,
            "surplus_formatted": format_inr_minor(surplus_minor, show_plus=True),
        },
        "has_transactions": total_tx_count > 0,
        "transaction_count": total_tx_count,
        "recent_transactions": [serialize_transaction_row(r) for r in recent_rows],
    }
