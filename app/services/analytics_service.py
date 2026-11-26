"""Authoritative financial analytics and reporting service."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, analytics_repo
from app.services import budget_service
from app.utils.errors import ValidationError
from app.utils.money import format_inr_minor
from app.utils.time import shift_month_key, validate_tx_date

VALID_PRESETS = {
    "current_month",
    "previous_month",
    "last_3_months",
    "last_6_months",
    "current_year",
    "all_time",
    "custom",
}


def resolve_date_range(
    *,
    preset: str = "current_month",
    start_date: str | None = None,
    end_date: str | None = None,
    today: date | None = None,
) -> tuple[str | None, str | None, str]:
    """Resolve a reporting preset or custom date range into inclusive YYYY-MM-DD bounds."""
    if preset not in VALID_PRESETS:
        raise ValidationError("Invalid reporting period preset.", field="preset")
    ref = today or date.today()

    if preset == "all_time":
        return None, None, "All time"
    if preset == "current_month":
        s = date(ref.year, ref.month, 1)
        return s.isoformat(), ref.isoformat(), f"{s.strftime('%b %Y')} (month-to-date)"
    if preset == "previous_month":
        first_cur = date(ref.year, ref.month, 1)
        last_prev = first_cur - timedelta(days=1)
        first_prev = date(last_prev.year, last_prev.month, 1)
        return first_prev.isoformat(), last_prev.isoformat(), first_prev.strftime("%b %Y")
    if preset == "last_3_months":
        cur_mk = f"{ref.year:04d}-{ref.month:02d}"
        start_mk = shift_month_key(cur_mk, -2)
        return f"{start_mk}-01", ref.isoformat(), "Last 3 months"
    if preset == "last_6_months":
        cur_mk = f"{ref.year:04d}-{ref.month:02d}"
        start_mk = shift_month_key(cur_mk, -5)
        return f"{start_mk}-01", ref.isoformat(), "Last 6 months"
    if preset == "current_year":
        return f"{ref.year:04d}-01-01", ref.isoformat(), f"{ref.year} (year-to-date)"

    if not start_date or not end_date:
        raise ValidationError(
            "Custom date range requires both start_date and end_date.",
            field="start_date",
        )
    s_iso = validate_tx_date(start_date, field="start_date", allow_future=True)
    e_iso = validate_tx_date(end_date, field="end_date", allow_future=True)
    if s_iso > e_iso:
        raise ValidationError("Start date cannot be after end date.", field="start_date")
    return s_iso, e_iso, f"{s_iso} to {e_iso}"


def _compute_savings_rate(income_minor: int, surplus_minor: int) -> float | None:
    if income_minor <= 0:
        return None
    return round((surplus_minor / income_minor) * 100.0, 2)


def _format_summary_block(totals: dict[str, int]) -> dict[str, Any]:
    inc = int(totals["income_minor"])
    gross = int(totals["gross_expense_minor"])
    refund = int(totals["refund_minor"])
    net = gross - refund
    surplus = inc - net
    rate = _compute_savings_rate(inc, surplus)
    return {
        "income_minor": inc,
        "income_formatted": format_inr_minor(inc),
        "gross_expense_minor": gross,
        "gross_expense_formatted": format_inr_minor(gross),
        "refund_minor": refund,
        "refund_formatted": format_inr_minor(refund),
        "net_expense_minor": net,
        "net_expense_formatted": format_inr_minor(net),
        "surplus_minor": surplus,
        "surplus_formatted": format_inr_minor(surplus, show_plus=True),
        "savings_rate_percent": rate,
        "savings_rate_available": rate is not None,
    }


def _previous_equivalent_range(start_iso: str, end_iso: str) -> tuple[str, str]:
    s = date.fromisoformat(start_iso)
    e = date.fromisoformat(end_iso)
    span_days = (e - s).days + 1
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span_days - 1)
    return prev_start.isoformat(), prev_end.isoformat()


def _pct_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round(((current - previous) / previous) * 100.0, 2)


def get_full_analytics_report(
    db_path: Path | str,
    *,
    preset: str = "current_month",
    start_date: str | None = None,
    end_date: str | None = None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return complete, reconciled analytics payload for Reports & Overview."""
    ref = today or date.today()
    s_iso, e_iso, period_label = resolve_date_range(
        preset=preset, start_date=start_date, end_date=end_date, today=ref
    )

    with db_session(db_path) as conn:
        totals = analytics_repo.get_period_totals(
            conn,
            start_date=s_iso,
            end_date=e_iso,
            account_ids=account_ids,
            category_ids=category_ids,
        )
        summary = _format_summary_block(totals)

        comparison: dict[str, Any] | None = None
        if s_iso and e_iso:
            ps, pe = _previous_equivalent_range(s_iso, e_iso)
            prev_totals = analytics_repo.get_period_totals(
                conn,
                start_date=ps,
                end_date=pe,
                account_ids=account_ids,
                category_ids=category_ids,
            )
            prev_summary = _format_summary_block(prev_totals)
            comparison = {
                "previous_start_date": ps,
                "previous_end_date": pe,
                "income_delta_minor": summary["income_minor"] - prev_summary["income_minor"],
                "income_delta_pct": _pct_change(
                    summary["income_minor"], prev_summary["income_minor"]
                ),
                "net_expense_delta_minor": (
                    summary["net_expense_minor"] - prev_summary["net_expense_minor"]
                ),
                "net_expense_delta_pct": _pct_change(
                    summary["net_expense_minor"], prev_summary["net_expense_minor"]
                ),
                "surplus_delta_minor": summary["surplus_minor"] - prev_summary["surplus_minor"],
            }

        monthly_raw = analytics_repo.get_monthly_series(
            conn,
            start_date=s_iso,
            end_date=e_iso,
            account_ids=account_ids,
            category_ids=category_ids,
        )
        monthly_series = []
        for row in monthly_raw:
            blk = _format_summary_block(row)
            monthly_series.append({"month": row["month"], **blk})

        cat_raw = analytics_repo.get_category_breakdown(
            conn,
            start_date=s_iso,
            end_date=e_iso,
            account_ids=account_ids,
            category_ids=category_ids,
        )
        categories = []
        for row in cat_raw:
            gross = int(row["gross_minor"])
            refund = int(row["refund_minor"])
            net = gross - refund
            categories.append(
                {
                    "category_id": int(row["category_id"]),
                    "category_name": str(row["category_name"]),
                    "category_slug": str(row["category_slug"]),
                    "color_token": str(row["color_token"]),
                    "is_archived": bool(int(row["is_archived"])),
                    "gross_minor": gross,
                    "gross_formatted": format_inr_minor(gross),
                    "refund_minor": refund,
                    "refund_formatted": format_inr_minor(refund),
                    "net_minor": net,
                    "net_formatted": format_inr_minor(net),
                    "doughnut_eligible": gross > 0,
                }
            )

        merchants_raw = analytics_repo.get_top_merchants(
            conn,
            start_date=s_iso,
            end_date=e_iso,
            account_ids=account_ids,
            category_ids=category_ids,
            limit=10,
        )
        merchants = [
            {
                "merchant": str(r["merchant"]),
                "tx_count": int(r["tx_count"]),
                "net_spend_minor": int(r["net_spend_minor"]),
                "net_spend_formatted": format_inr_minor(int(r["net_spend_minor"])),
            }
            for r in merchants_raw
        ]

        daily_raw = analytics_repo.get_daily_activity(
            conn,
            start_date=s_iso,
            end_date=e_iso,
            account_ids=account_ids,
            category_ids=category_ids,
        )
        weekday_totals = [0] * 7  # 0=Mon..6=Sun
        weekday_counts = [0] * 7
        for drow in daily_raw:
            wd = date.fromisoformat(drow["date"]).weekday()
            weekday_totals[wd] += int(drow["net_expense_minor"])
            weekday_counts[wd] += int(drow["tx_count"])
        weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        weekday_spending = [
            {
                "weekday": weekday_names[i],
                "net_expense_minor": weekday_totals[i],
                "net_expense_formatted": format_inr_minor(weekday_totals[i]),
                "tx_count": weekday_counts[i],
            }
            for i in range(7)
        ]

        # Historical account balance & net worth by month
        accts = accounts_repo.list_accounts_with_balances(conn, include_archived=True)
        if account_ids:
            acct_set = set(account_ids)
            accts = [a for a in accts if int(a["id"]) in acct_set]
        deltas = analytics_repo.get_account_balance_deltas_by_month(conn, account_ids=account_ids)
        months_all = sorted({d["month"] for d in deltas} | {m["month"] for m in monthly_series})
        delta_map: dict[tuple[int, str], int] = {
            (int(d["account_id"]), str(d["month"])): int(d["delta_minor"]) for d in deltas
        }
        running_by_acct = {int(a["id"]): int(a["opening_balance_minor"]) for a in accts}
        balance_history = []
        for mk in months_all:
            assets = 0
            liabilities = 0
            for a in accts:
                aid = int(a["id"])
                running_by_acct[aid] += delta_map.get((aid, mk), 0)
                bal = running_by_acct[aid]
                if a["account_type"] == "credit_card":
                    if bal < 0:
                        liabilities += abs(bal)
                    else:
                        assets += bal
                else:
                    assets += bal
            net_worth = assets - liabilities
            balance_history.append(
                {
                    "month": mk,
                    "assets_minor": assets,
                    "liabilities_minor": liabilities,
                    "net_worth_minor": net_worth,
                    "net_worth_formatted": format_inr_minor(net_worth),
                }
            )

    target_month = (e_iso or ref.isoformat())[:7]
    budget_perf = budget_service.get_month_budgets(db_path, month=target_month)

    return {
        "period": {
            "preset": preset,
            "start_date": s_iso,
            "end_date": e_iso,
            "label": period_label,
        },
        "summary": summary,
        "comparison": comparison,
        "monthly_series": monthly_series,
        "categories": categories,
        "merchants": merchants,
        "daily_activity": daily_raw,
        "weekday_spending": weekday_spending,
        "balance_history": balance_history,
        "budget_performance": budget_perf,
    }
