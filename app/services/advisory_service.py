"""Deterministic, explainable financial advisory & notification service."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.database import db_session
from app.services import account_service, analytics_service, budget_service, forecasting_service
from app.utils.errors import NotFoundError, ValidationError
from app.utils.money import format_inr_minor
from app.utils.time import utc_now_iso

DEFAULT_RULES: list[dict[str, Any]] = [
    {"rule_id": "budget_approaching", "enabled": True, "threshold_value": 80},
    {"rule_id": "budget_reached", "enabled": True, "threshold_value": 100},
    {"rule_id": "budget_exceeded", "enabled": True, "threshold_value": 100},
    {"rule_id": "overall_budget_warning", "enabled": True, "threshold_value": 80},
    {"rule_id": "low_account_balance", "enabled": True, "threshold_value": 100_000},
    {"rule_id": "credit_utilization", "enabled": True, "threshold_value": 75},
    {"rule_id": "negative_cash_flow", "enabled": True, "threshold_value": None},
    {"rule_id": "projected_overspending", "enabled": True, "threshold_value": None},
    {"rule_id": "upcoming_payment", "enabled": True, "threshold_value": 3},
    {"rule_id": "savings_milestone", "enabled": True, "threshold_value": None},
]


def _get_pref_map(conn: Any) -> dict[str, dict[str, Any]]:
    prefs = {
        r["rule_id"]: {"enabled": bool(r["enabled"]), "threshold_value": r["threshold_value"]}
        for r in DEFAULT_RULES
    }
    rows = conn.execute(
        "SELECT rule_id, enabled, threshold_value, native_enabled FROM notification_preferences;"
    ).fetchall()
    for r in rows:
        prefs[str(r["rule_id"])] = {
            "enabled": bool(int(r["enabled"])),
            "threshold_value": r["threshold_value"],
            "native_enabled": bool(int(r["native_enabled"])),
        }
    return prefs


def _upsert_event(
    conn: Any,
    *,
    rule_id: str,
    dedup_key: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    supporting: dict[str, Any],
    period_key: str,
    entity_type: str = "",
    entity_id: int | None = None,
    nav_target: str = "insights",
    now: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO notification_events (
            rule_id, rule_version, dedup_key, category, severity, title, message,
            supporting_json, period_key, entity_type, entity_id, nav_target,
            is_read, is_dismissed, created_at, updated_at
        )
        VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?);
        """,
        (
            rule_id,
            dedup_key,
            category,
            severity,
            title[:160],
            message[:600],
            json.dumps(supporting),
            period_key,
            entity_type,
            entity_id,
            nav_target,
            now,
            now,
        ),
    )


def evaluate_advisories(
    db_path: Path | str,
    *,
    month: str | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Evaluate deterministic advisory rules and persist deduplicated notifications."""
    ref = today or date.today()
    target_month = month or f"{ref.year:04d}-{ref.month:02d}"
    now = utc_now_iso()

    budgets = budget_service.get_month_budgets(db_path, month=target_month)
    accts = account_service.list_accounts(db_path)["accounts"]
    forecast = forecasting_service.compute_monthly_forecast(db_path, month=target_month, today=ref)
    rep = analytics_service.get_full_analytics_report(db_path, preset="current_month", today=ref)

    with db_session(db_path, immediate=True) as conn:
        prefs = _get_pref_map(conn)

        # 1. Category budget rules (approaching 80%, reached 100%, exceeded >100%)
        for cat in budgets["categories"]:
            eff = cat["effective_limit_minor"]
            spent = int(cat["net_spend_minor"])
            if eff is None or eff <= 0:
                continue
            pct = (spent * 100) / eff
            cid = int(cat["category_id"])
            cname = cat["category_name"]
            if pct > 100 and prefs["budget_exceeded"]["enabled"]:
                _upsert_event(
                    conn,
                    rule_id="budget_exceeded",
                    dedup_key=f"budget_exceeded:{target_month}:{cid}",
                    category="budget",
                    severity="alert",
                    title=f"{cname} budget exceeded",
                    message=(
                        f"{cname} spending is {format_inr_minor(spent)} against your "
                        f"{format_inr_minor(eff)} {target_month} budget."
                    ),
                    supporting={"spent_minor": spent, "limit_minor": eff},
                    period_key=target_month,
                    entity_type="category",
                    entity_id=cid,
                    nav_target="budgets",
                    now=now,
                )
            elif pct == 100 and prefs["budget_reached"]["enabled"]:
                _upsert_event(
                    conn,
                    rule_id="budget_reached",
                    dedup_key=f"budget_reached:{target_month}:{cid}",
                    category="budget",
                    severity="warning",
                    title=f"{cname} budget reached",
                    message=f"{cname} spending has reached 100% of your {format_inr_minor(eff)} budget.",
                    supporting={"spent_minor": spent, "limit_minor": eff},
                    period_key=target_month,
                    entity_type="category",
                    entity_id=cid,
                    nav_target="budgets",
                    now=now,
                )
            elif pct < 100:
                thresh = int(prefs["budget_approaching"].get("threshold_value") or 80)
                if pct >= thresh and prefs["budget_approaching"]["enabled"]:
                    rem = eff - spent
                    _upsert_event(
                        conn,
                        rule_id="budget_approaching",
                        dedup_key=f"budget_approaching:{target_month}:{cid}",
                        category="budget",
                        severity="warning",
                        title=f"{cname} approaching budget",
                        message=(
                            f"{cname} spending has reached {format_inr_minor(spent)} of your "
                            f"{format_inr_minor(eff)} {target_month} budget. {format_inr_minor(rem)} remains."
                        ),
                        supporting={
                            "spent_minor": spent,
                            "limit_minor": eff,
                            "remaining_minor": rem,
                        },
                        period_key=target_month,
                        entity_type="category",
                        entity_id=cid,
                        nav_target="budgets",
                        now=now,
                    )

        # 2. Low asset balance & credit utilization
        low_thresh = int(prefs["low_account_balance"].get("threshold_value") or 100_000)
        util_thresh = int(prefs["credit_utilization"].get("threshold_value") or 75)
        for a in accts:
            if a["is_archived"]:
                continue
            aid = int(a["id"])
            if a["account_type"] == "credit_card":
                limit_m = a.get("credit_limit_minor")
                owed_m = int(a.get("outstanding_liability_minor") or 0)
                if (
                    limit_m
                    and limit_m > 0
                    and (owed_m * 100) >= (limit_m * util_thresh)
                    and prefs["credit_utilization"]["enabled"]
                ):
                    _upsert_event(
                        conn,
                        rule_id="credit_utilization",
                        dedup_key=f"credit_utilization:{target_month}:{aid}",
                        category="spending",
                        severity="warning",
                        title=f"High credit utilization on {a['name']}",
                        message=(
                            f"{a['name']} balance owed is {format_inr_minor(owed_m)} "
                            f"of {format_inr_minor(limit_m)} limit."
                        ),
                        supporting={"owed_minor": owed_m, "limit_minor": limit_m},
                        period_key=target_month,
                        entity_type="account",
                        entity_id=aid,
                        nav_target="accounts",
                        now=now,
                    )
            else:
                bal = int(a["balance_minor"])
                if bal < low_thresh and bal != 0 and prefs["low_account_balance"]["enabled"]:
                    _upsert_event(
                        conn,
                        rule_id="low_account_balance",
                        dedup_key=f"low_account_balance:{target_month}:{aid}",
                        category="spending",
                        severity="info",
                        title=f"Low balance in {a['name']}",
                        message=f"{a['name']} balance is {format_inr_minor(bal)}.",
                        supporting={"balance_minor": bal, "threshold_minor": low_thresh},
                        period_key=target_month,
                        entity_type="account",
                        entity_id=aid,
                        nav_target="accounts",
                        now=now,
                    )

        # 3. Negative monthly cash flow (only when income > 0 and net_expense > income)
        s = rep["summary"]
        if (
            s["income_minor"] > 0
            and s["net_expense_minor"] > s["income_minor"]
            and prefs["negative_cash_flow"]["enabled"]
        ):
            _upsert_event(
                conn,
                rule_id="negative_cash_flow",
                dedup_key=f"negative_cash_flow:{target_month}",
                category="spending",
                severity="warning",
                title="Negative monthly cash flow",
                message=(
                    f"Net expenses ({s['net_expense_formatted']}) exceed recorded income "
                    f"({s['income_formatted']}) for {target_month}."
                ),
                supporting={
                    "income_minor": s["income_minor"],
                    "net_expense_minor": s["net_expense_minor"],
                },
                period_key=target_month,
                nav_target="reports",
                now=now,
            )

        # 4. Projected budget overspending
        if (
            not forecast["insufficient_data"]
            and forecast["budget_limit_minor"] is not None
            and forecast["projected_spend_minor"] > forecast["budget_limit_minor"]
            and prefs["projected_overspending"]["enabled"]
        ):
            _upsert_event(
                conn,
                rule_id="projected_overspending",
                dedup_key=f"projected_overspending:{target_month}",
                category="budget",
                severity="info",
                title="Projected to exceed monthly budget",
                message=(
                    f"At current pace, projected {target_month} spending is "
                    f"{forecast['projected_spend_formatted']} vs {forecast['budget_limit_formatted']} limit."
                ),
                supporting={
                    "projected_minor": forecast["projected_spend_minor"],
                    "limit_minor": forecast["budget_limit_minor"],
                },
                period_key=target_month,
                nav_target="budgets",
                now=now,
            )

    return list_notifications(db_path)


def list_notifications(
    db_path: Path | str, *, include_dismissed: bool = False
) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM notification_events
            WHERE (? = 1 OR is_dismissed = 0)
            ORDER BY is_read ASC, created_at DESC, id DESC;
            """,
            (1 if include_dismissed else 0,),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "rule_id": str(r["rule_id"]),
            "category": str(r["category"]),
            "severity": str(r["severity"]),
            "title": str(r["title"]),
            "message": str(r["message"]),
            "supporting": json.loads(r["supporting_json"] or "{}"),
            "period_key": str(r["period_key"]),
            "entity_type": str(r["entity_type"]),
            "entity_id": r["entity_id"],
            "nav_target": str(r["nav_target"]),
            "is_read": bool(int(r["is_read"])),
            "is_dismissed": bool(int(r["is_dismissed"])),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def mark_notification_read(db_path: Path | str, notification_id: int) -> dict[str, Any]:
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute(
            "UPDATE notification_events SET is_read = 1, updated_at = ? WHERE id = ?;",
            (now, notification_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Notification not found.", field="notification_id")
    return {"id": notification_id, "is_read": True}


def mark_all_notifications_read(db_path: Path | str) -> dict[str, Any]:
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        conn.execute("UPDATE notification_events SET is_read = 1, updated_at = ?;", (now,))
    return {"marked_all_read": True}


def dismiss_notification(db_path: Path | str, notification_id: int) -> dict[str, Any]:
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute(
            "UPDATE notification_events SET is_dismissed = 1, updated_at = ? WHERE id = ?;",
            (now, notification_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Notification not found.", field="notification_id")
    return {"id": notification_id, "is_dismissed": True}


def get_notification_preferences(db_path: Path | str) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        pmap = _get_pref_map(conn)
    return [
        {
            "rule_id": r["rule_id"],
            "enabled": pmap[r["rule_id"]]["enabled"],
            "threshold_value": pmap[r["rule_id"]]["threshold_value"],
            "native_enabled": pmap[r["rule_id"]].get("native_enabled", False),
        }
        for r in DEFAULT_RULES
    ]


def update_notification_preferences(
    db_path: Path | str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    now = utc_now_iso()
    valid_ids = {r["rule_id"] for r in DEFAULT_RULES}
    with db_session(db_path, immediate=True) as conn:
        for item in items:
            rid = str(item.get("rule_id") or "")
            if rid not in valid_ids:
                continue
            enabled = 1 if item.get("enabled", True) else 0
            native = 1 if item.get("native_enabled", False) else 0
            thresh = item.get("threshold_value")
            if thresh is not None and (
                isinstance(thresh, bool) or not isinstance(thresh, int) or thresh < 0
            ):
                raise ValidationError(
                    "threshold_value must be a non-negative integer or null.",
                    field="threshold_value",
                )
            conn.execute(
                """
                INSERT INTO notification_preferences (rule_id, enabled, threshold_value, native_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    threshold_value = excluded.threshold_value,
                    native_enabled = excluded.native_enabled,
                    updated_at = excluded.updated_at;
                """,
                (rid, enabled, thresh, native, now),
            )
    return get_notification_preferences(db_path)
