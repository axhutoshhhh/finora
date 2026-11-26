"""Financial calendar service combining posted ledger activity, recurring schedules, and goal dates."""

from __future__ import annotations

import calendar
from pathlib import Path
from typing import Any

from app.database import db_session
from app.utils.errors import ValidationError
from app.utils.money import format_inr_minor


def get_month_calendar(db_path: Path | str, *, month: str) -> dict[str, Any]:
    """Return all posted transactions, pending recurring occurrences, and goal target dates for YYYY-MM."""
    if len(month) != 7 or month[4] != "-" or not (month[:4].isdigit() and month[5:7].isdigit()):
        raise ValidationError("Month must be YYYY-MM.", field="month")
    y, m = int(month[:4]), int(month[5:7])
    if m < 1 or m > 12:
        raise ValidationError("Month must be 01..12.", field="month")
    days_in_month = calendar.monthrange(y, m)[1]
    start_iso = f"{month}-01"
    end_iso = f"{month}-{days_in_month:02d}"

    with db_session(db_path) as conn:
        tx_rows = conn.execute(
            """
            SELECT
                t.id, t.entry_type, t.tx_date, t.description, t.merchant,
                COALESCE(SUM(CASE WHEN t.entry_type = 'transfer' THEN ABS(p.signed_amount_minor)
                                  ELSE ABS(p.signed_amount_minor) END), 0) AS raw_amount_minor,
                t.entry_type AS etype
            FROM transactions t
            JOIN postings p ON p.transaction_id = t.id
            WHERE t.deleted_at IS NULL AND t.tx_date >= ? AND t.tx_date <= ?
            GROUP BY t.id
            ORDER BY t.tx_date ASC, t.id ASC;
            """,
            (start_iso, end_iso),
        ).fetchall()

        occ_rows = conn.execute(
            """
            SELECT o.id, o.scheduled_date, o.amount_minor, o.status, r.name, r.entry_type, r.is_subscription
            FROM recurring_occurrences o
            JOIN recurring_rules r ON r.id = o.rule_id
            WHERE o.scheduled_date >= ? AND o.scheduled_date <= ?
              AND o.status IN ('upcoming', 'due', 'overdue')
            ORDER BY o.scheduled_date ASC, o.id ASC;
            """,
            (start_iso, end_iso),
        ).fetchall()

        goal_rows = conn.execute(
            """
            SELECT id, name, target_date, target_minor, status
            FROM savings_goals
            WHERE target_date IS NOT NULL AND target_date >= ? AND target_date <= ?
              AND status != 'archived'
            ORDER BY target_date ASC;
            """,
            (start_iso, end_iso),
        ).fetchall()

    days: dict[str, dict[str, Any]] = {}
    for d in range(1, days_in_month + 1):
        iso = f"{month}-{d:02d}"
        days[iso] = {
            "date": iso,
            "posted_count": 0,
            "scheduled_count": 0,
            "goal_count": 0,
            "posted": [],
            "scheduled": [],
            "goals": [],
        }

    for r in tx_rows:
        iso = str(r["tx_date"])
        if iso in days:
            raw_amt = int(r["raw_amount_minor"])
            amt = raw_amt // 2 if r["etype"] == "transfer" else raw_amt
            days[iso]["posted_count"] += 1
            days[iso]["posted"].append(
                {
                    "id": int(r["id"]),
                    "entry_type": str(r["entry_type"]),
                    "description": str(r["description"] or ""),
                    "merchant": str(r["merchant"] or ""),
                    "amount_minor": amt,
                    "amount_formatted": format_inr_minor(amt),
                }
            )

    for r in occ_rows:
        iso = str(r["scheduled_date"])
        if iso in days:
            amt = int(r["amount_minor"])
            days[iso]["scheduled_count"] += 1
            days[iso]["scheduled"].append(
                {
                    "occurrence_id": int(r["id"]),
                    "name": str(r["name"]),
                    "entry_type": str(r["entry_type"]),
                    "is_subscription": bool(int(r["is_subscription"])),
                    "status": str(r["status"]),
                    "amount_minor": amt,
                    "amount_formatted": format_inr_minor(amt),
                }
            )

    for r in goal_rows:
        iso = str(r["target_date"])
        if iso in days:
            days[iso]["goal_count"] += 1
            days[iso]["goals"].append(
                {
                    "goal_id": int(r["id"]),
                    "name": str(r["name"]),
                    "target_formatted": format_inr_minor(int(r["target_minor"])),
                    "status": str(r["status"]),
                }
            )

    return {
        "month": month,
        "first_weekday": calendar.monthrange(y, m)[0],  # 0=Mon..6=Sun
        "days_in_month": days_in_month,
        "days": list(days.values()),
    }
