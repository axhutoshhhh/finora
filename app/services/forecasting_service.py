"""Lightweight, explainable monthly spending forecast service."""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import Any

from app.services import budget_service
from app.utils.money import format_inr_minor


def compute_monthly_forecast(
    db_path: Path | str,
    *,
    month: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Estimate end-of-month net spending from month-to-date pace.

    Uses net expenses (gross expenses minus refunds) divided by elapsed days,
    multiplied by actual days in the month. Clearly labeled as an estimate.
    """
    ref = today or date.today()
    target_month = month or f"{ref.year:04d}-{ref.month:02d}"
    year_i, month_i = int(target_month[:4]), int(target_month[5:7])
    days_in_month = calendar.monthrange(year_i, month_i)[1]

    if year_i == ref.year and month_i == ref.month:
        elapsed_days = max(1, ref.day)
    elif (year_i, month_i) < (ref.year, ref.month):
        elapsed_days = days_in_month
    else:
        elapsed_days = 0

    budgets = budget_service.get_month_budgets(db_path, month=target_month)
    overall = budgets["overall"]
    spent_minor = int(overall.get("actual_spend_minor", overall.get("net_spend_minor", 0)))
    budget_limit_minor = overall["limit_minor"]

    insufficient_data = elapsed_days == 0 or (elapsed_days < 3 and spent_minor <= 0)
    if insufficient_data:
        projected_minor = max(0, spent_minor)
        assumption = "Insufficient month-to-date data for pace projection."
    elif spent_minor <= 0:
        projected_minor = 0
        assumption = "Net spending is zero or negative (refunds exceed expenses) so far."
    else:
        projected_minor = round((spent_minor / elapsed_days) * days_in_month)
        assumption = (
            f"Estimated from {elapsed_days} of {days_in_month} days "
            f"at {format_inr_minor(round(spent_minor / elapsed_days))}/day net pace."
        )

    est_variance_minor = (
        (budget_limit_minor - projected_minor) if budget_limit_minor is not None else None
    )

    return {
        "month": target_month,
        "is_estimate": True,
        "insufficient_data": insufficient_data,
        "elapsed_days": elapsed_days,
        "days_in_month": days_in_month,
        "current_net_spend_minor": spent_minor,
        "current_net_spend_formatted": format_inr_minor(spent_minor),
        "projected_spend_minor": projected_minor,
        "projected_spend_formatted": format_inr_minor(projected_minor),
        "budget_limit_minor": budget_limit_minor,
        "budget_limit_formatted": (
            format_inr_minor(budget_limit_minor) if budget_limit_minor is not None else None
        ),
        "estimated_remaining_minor": est_variance_minor,
        "estimated_remaining_formatted": (
            format_inr_minor(est_variance_minor, show_plus=True)
            if est_variance_minor is not None
            else None
        ),
        "assumption": assumption,
    }
