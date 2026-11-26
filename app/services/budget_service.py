"""Monthly category and overall budgeting services with deterministic rollover."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import budgets_repo, categories_repo, transactions_repo
from app.utils.errors import NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor, validate_aggregate_minor
from app.utils.time import resolve_month_bounds, shift_month_key, utc_now_iso

MAX_ROLLOVER_LOOKBACK_MONTHS = 60


def _classify_budget_state(
    *,
    base_limit_minor: int | None,
    effective_limit_minor: int | None,
    net_spend_minor: int,
) -> tuple[str, str, float | None]:
    """Determine unambiguous budget state, label, and safe usage percentage (no zero-division)."""
    if base_limit_minor is None or effective_limit_minor is None:
        return "unconfigured", "Not set", None

    if effective_limit_minor == 0:
        if net_spend_minor > 0:
            return "exceeded", "Over zero limit", None
        return "zero_limit", "Zero limit (₹0.00)", 0.0

    pct = round((net_spend_minor / effective_limit_minor) * 100.0, 1)
    if net_spend_minor > effective_limit_minor:
        return "exceeded", "Over budget", pct
    if net_spend_minor == effective_limit_minor:
        return "reached", "Limit reached", pct
    if net_spend_minor * 100 >= effective_limit_minor * 80:
        return "approaching", "Approaching limit", pct
    return "on_track", "On track", pct


def _compute_rollover_chain(
    *,
    category_id: int,
    target_month: str,
    budget_map: dict[tuple[str, int], tuple[int, bool]],
    spend_map: dict[tuple[str, int], tuple[int, int]],
) -> int:
    """Compute carry-in minor units from consecutive preceding months with rollover_enabled=True.

    Missing intervening months or rollover_enabled=False reset carry-in to 0.
    """
    current = budget_map.get((target_month, category_id))
    if current is None or not current[1]:
        return 0

    chain: list[str] = []
    cursor_month = shift_month_key(target_month, -1)
    while len(chain) < MAX_ROLLOVER_LOOKBACK_MONTHS:
        entry = budget_map.get((cursor_month, category_id))
        if entry is None or not entry[1]:
            break
        chain.append(cursor_month)
        cursor_month = shift_month_key(cursor_month, -1)

    if not chain:
        return 0

    chain.reverse()
    carry = 0
    for month in chain:
        base_limit, _ = budget_map[(month, category_id)]
        effective = base_limit + carry
        gross, refund = spend_map.get((month, category_id), (0, 0))
        net_spend = gross - refund
        # Positive unused budget carries forward; refund bonuses never exceed effective_limit.
        carry = max(0, effective - max(0, net_spend))
    return carry


def _build_month_budgets_from_conn(
    conn: sqlite3.Connection, month_key: str, month_label: str, start_date: str, end_excl: str
) -> dict[str, Any]:
    return get_month_budgets_from_conn(conn, month_key, month_label, start_date, end_excl)


def get_month_budgets_from_conn(
    conn: sqlite3.Connection, month_key: str, month_label: str, start_date: str, end_excl: str
) -> dict[str, Any]:
    """Build monthly budget snapshot from an active SQLite connection."""
    earliest_month = shift_month_key(month_key, -MAX_ROLLOVER_LOOKBACK_MONTHS)
    _, _, earliest_start, _ = resolve_month_bounds(earliest_month)

    raw_budgets = budgets_repo.list_category_budgets_up_to_month(
        conn, min_month=earliest_month, max_month=month_key
    )
    budget_map: dict[tuple[str, int], tuple[int, bool]] = {}
    budget_id_for_month: dict[int, int] = {}
    for row in raw_budgets:
        m = str(row["month"])
        cid = int(row["category_id"])
        budget_map[(m, cid)] = (int(row["limit_minor"]), bool(row["rollover_enabled"]))
        if m == month_key:
            budget_id_for_month[cid] = int(row["id"])

    spend_map = budgets_repo.get_category_monthly_spend_map(
        conn, start_date=earliest_start, end_date_exclusive=end_excl
    )
    _, total_gross_minor, total_refunds_minor = transactions_repo.get_month_summary_detailed(
        conn, start_date=start_date, end_date_exclusive=end_excl
    )
    total_actual_spend_minor = total_gross_minor - total_refunds_minor

    active_expense_cats = categories_repo.list_categories(
        conn, kind="expense", include_archived=False
    )
    active_ids = {int(c["id"]) for c in active_expense_cats}

    # Include archived categories that already had a budget configured for this historical month
    archived_configured_rows = [
        r
        for r in budgets_repo.list_configured_categories_with_archive(conn, month_key)
        if int(r["category_id"]) not in active_ids
    ]

    category_rows: list[dict[str, Any]] = []
    total_allocated_base_minor = 0
    total_effective_budget_minor = 0
    budgeted_spend_minor = 0
    configured_count = 0
    approaching_count = 0
    exceeded_count = 0

    def _append_row(
        *,
        cid: int,
        name: str,
        slug: str,
        icon: str,
        color_style: str,
        is_archived: bool,
    ) -> None:
        nonlocal total_allocated_base_minor, total_effective_budget_minor
        nonlocal budgeted_spend_minor, configured_count, approaching_count, exceeded_count

        cfg = budget_map.get((month_key, cid))
        gross_minor, refund_minor = spend_map.get((month_key, cid), (0, 0))
        net_spend_minor = gross_minor - refund_minor

        if cfg is not None:
            base_limit_minor, rollover_enabled = cfg
            carry_in_minor = _compute_rollover_chain(
                category_id=cid,
                target_month=month_key,
                budget_map=budget_map,
                spend_map=spend_map,
            )
            effective_limit_minor = base_limit_minor + carry_in_minor
            remaining_minor: int | None = effective_limit_minor - net_spend_minor
            configured_count += 1
            total_allocated_base_minor += base_limit_minor
            total_effective_budget_minor += effective_limit_minor
            budgeted_spend_minor += net_spend_minor
        else:
            base_limit_minor = None
            rollover_enabled = False
            carry_in_minor = 0
            effective_limit_minor = None
            remaining_minor = None

        status, status_label, usage_pct = _classify_budget_state(
            base_limit_minor=base_limit_minor,
            effective_limit_minor=effective_limit_minor,
            net_spend_minor=net_spend_minor,
        )
        if status == "approaching":
            approaching_count += 1
        elif status == "exceeded":
            exceeded_count += 1

        category_rows.append(
            {
                "budget_id": budget_id_for_month.get(cid),
                "category_id": cid,
                "category_name": name,
                "category_slug": slug,
                "category_icon": icon,
                "category_color_token": color_style,
                "category_is_archived": is_archived,
                "base_limit_minor": base_limit_minor,
                "base_limit_formatted": (
                    format_inr_minor(base_limit_minor) if base_limit_minor is not None else None
                ),
                "rollover_enabled": rollover_enabled,
                "carry_in_minor": carry_in_minor,
                "carry_in_formatted": format_inr_minor(carry_in_minor),
                "effective_limit_minor": effective_limit_minor,
                "effective_limit_formatted": (
                    format_inr_minor(effective_limit_minor)
                    if effective_limit_minor is not None
                    else None
                ),
                "gross_spend_minor": gross_minor,
                "gross_spend_formatted": format_inr_minor(gross_minor),
                "refund_minor": refund_minor,
                "refund_formatted": format_inr_minor(refund_minor),
                "net_spend_minor": net_spend_minor,
                "net_spend_formatted": format_inr_minor(net_spend_minor),
                "remaining_minor": remaining_minor,
                "remaining_formatted": (
                    format_inr_minor(remaining_minor) if remaining_minor is not None else None
                ),
                "exceeded_minor": (max(0, -remaining_minor) if remaining_minor is not None else 0),
                "exceeded_formatted": (
                    format_inr_minor(max(0, -remaining_minor))
                    if remaining_minor is not None
                    else None
                ),
                "usage_percent": usage_pct,
                "status": status,
                "status_label": status_label,
            }
        )

    for cat in active_expense_cats:
        _append_row(
            cid=int(cat["id"]),
            name=str(cat["name"]),
            slug=str(cat["slug"]),
            icon=str(cat["icon"]),
            color_style=str(cat["color_token"]),
            is_archived=False,
        )
    for row in archived_configured_rows:
        _append_row(
            cid=int(row["category_id"]),
            name=f"{row['category_name']} (Archived)",
            slug=str(row["category_slug"]),
            icon=str(row["category_icon"]),
            color_style=str(row["category_color_token"]),
            is_archived=True,
        )

    overall_row = budgets_repo.get_overall_budget(conn, month_key)
    overall_limit_minor = int(overall_row["limit_minor"]) if overall_row is not None else None
    overall_remaining_minor = (
        overall_limit_minor - total_actual_spend_minor if overall_limit_minor is not None else None
    )
    overall_status, overall_status_label, overall_usage_pct = _classify_budget_state(
        base_limit_minor=overall_limit_minor,
        effective_limit_minor=overall_limit_minor,
        net_spend_minor=total_actual_spend_minor,
    )
    unbudgeted_spend_minor = total_actual_spend_minor - budgeted_spend_minor
    allocation_exceeds_overall = (
        overall_limit_minor is not None and total_allocated_base_minor > overall_limit_minor
    )
    allocation_gap_minor = (
        total_allocated_base_minor - overall_limit_minor if overall_limit_minor is not None else 0
    )

    validate_aggregate_minor(total_allocated_base_minor, label="Allocated budgets")
    validate_aggregate_minor(total_actual_spend_minor, label="Monthly spending")

    return {
        "month": month_key,
        "month_label": month_label,
        "previous_month": shift_month_key(month_key, -1),
        "next_month": shift_month_key(month_key, 1),
        "overall": {
            "configured": overall_limit_minor is not None,
            "limit_minor": overall_limit_minor,
            "limit_formatted": (
                format_inr_minor(overall_limit_minor) if overall_limit_minor is not None else None
            ),
            "actual_spend_minor": total_actual_spend_minor,
            "actual_spend_formatted": format_inr_minor(total_actual_spend_minor),
            "gross_spend_minor": total_gross_minor,
            "refunds_minor": total_refunds_minor,
            "remaining_minor": overall_remaining_minor,
            "remaining_formatted": (
                format_inr_minor(overall_remaining_minor)
                if overall_remaining_minor is not None
                else None
            ),
            "usage_percent": overall_usage_pct,
            "status": overall_status,
            "status_label": overall_status_label,
            "total_allocated_minor": total_allocated_base_minor,
            "total_allocated_formatted": format_inr_minor(total_allocated_base_minor),
            "total_effective_allocated_minor": total_effective_budget_minor,
            "total_effective_allocated_formatted": format_inr_minor(total_effective_budget_minor),
            "budgeted_spend_minor": budgeted_spend_minor,
            "budgeted_spend_formatted": format_inr_minor(budgeted_spend_minor),
            "unbudgeted_spend_minor": unbudgeted_spend_minor,
            "unbudgeted_spend_formatted": format_inr_minor(unbudgeted_spend_minor),
            "allocation_exceeds_overall": allocation_exceeds_overall,
            "allocation_gap_minor": allocation_gap_minor,
            "allocation_gap_formatted": format_inr_minor(abs(allocation_gap_minor)),
        },
        "summary": {
            "configured_categories": configured_count,
            "approaching_count": approaching_count,
            "exceeded_count": exceeded_count,
        },
        "categories": category_rows,
    }


def get_month_budgets(db_path: Path | str, *, month: str | None = None) -> dict[str, Any]:
    """Return full monthly budget calculations including rollover and overall cap checks."""
    month_key, month_label, start_date, end_excl = resolve_month_bounds(month)
    with db_session(db_path) as conn:
        conn.execute("BEGIN DEFERRED;")
        return _build_month_budgets_from_conn(conn, month_key, month_label, start_date, end_excl)


def set_category_budget(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a monthly spending limit for an active expense category."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    month_key, _, _, _ = resolve_month_bounds(
        payload.get("month") if isinstance(payload.get("month"), str) else None
    )
    raw_cid = payload.get("category_id")
    if isinstance(raw_cid, bool) or not isinstance(raw_cid, int) or raw_cid <= 0:
        raise ValidationError("Valid category is required.", field="category_id")
    limit_minor = parse_inr_to_minor(payload.get("limit"), field="limit", allow_zero=True)
    rollover_raw = payload.get("rollover_enabled", False)
    if not isinstance(rollover_raw, bool):
        raise ValidationError("Rollover flag must be true or false.", field="rollover_enabled")

    with db_session(db_path, immediate=True) as conn:
        cat = categories_repo.get_category_by_id(conn, raw_cid)
        if cat is None or int(cat["is_archived"]) != 0:
            raise NotFoundError(
                "Selected category was not found or is archived.", field="category_id"
            )
        if str(cat["kind"]) != "expense":
            raise ValidationError(
                "Budgets can only be set for expense categories.",
                status_code=422,
                field="category_id",
            )
        budgets_repo.upsert_category_budget(
            conn,
            category_id=raw_cid,
            month=month_key,
            limit_minor=limit_minor,
            rollover_enabled=rollover_raw,
            now=utc_now_iso(),
        )
    return get_month_budgets(db_path, month=month_key)


def delete_category_budget(
    db_path: Path | str, *, category_id: int, month: str | None
) -> dict[str, Any]:
    """Remove a category budget for a month (reverting to unconfigured state)."""
    month_key, _, _, _ = resolve_month_bounds(month)
    with db_session(db_path, immediate=True) as conn:
        deleted = budgets_repo.delete_category_budget(
            conn, category_id=category_id, month=month_key
        )
        if deleted == 0:
            raise NotFoundError("No budget configured for that category and month.")
    return get_month_budgets(db_path, month=month_key)


def set_overall_budget(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update an independent overall monthly spending limit."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    month_key, _, _, _ = resolve_month_bounds(
        payload.get("month") if isinstance(payload.get("month"), str) else None
    )
    limit_minor = parse_inr_to_minor(payload.get("limit"), field="limit", allow_zero=True)
    with db_session(db_path, immediate=True) as conn:
        budgets_repo.upsert_overall_budget(
            conn, month=month_key, limit_minor=limit_minor, now=utc_now_iso()
        )
    return get_month_budgets(db_path, month=month_key)


def delete_overall_budget(db_path: Path | str, *, month: str | None) -> dict[str, Any]:
    """Remove the independent overall spending cap for a month."""
    month_key, _, _, _ = resolve_month_bounds(month)
    with db_session(db_path, immediate=True) as conn:
        deleted = budgets_repo.delete_overall_budget(conn, month=month_key)
        if deleted == 0:
            raise NotFoundError("No overall monthly budget configured for that month.")
    return get_month_budgets(db_path, month=month_key)


def copy_previous_budgets(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy category and overall budgets from the preceding (or specified) month."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    target_month, _, _, _ = resolve_month_bounds(
        payload.get("target_month") if isinstance(payload.get("target_month"), str) else None
    )
    raw_source = payload.get("source_month")
    source_month = (
        resolve_month_bounds(raw_source)[0]
        if isinstance(raw_source, str) and raw_source.strip()
        else shift_month_key(target_month, -1)
    )
    if source_month == target_month:
        raise ValidationError("Source and target months must differ.", field="source_month")
    overwrite = bool(payload.get("overwrite", True))

    with db_session(db_path, immediate=True) as conn:
        src_cats = [
            r
            for r in budgets_repo.list_configured_categories_with_archive(conn, source_month)
            if int(r["category_is_archived"]) == 0
        ]
        src_overall = budgets_repo.get_overall_budget(conn, source_month)
        if not src_cats and src_overall is None:
            raise NotFoundError(f"No budgets were configured in {source_month} to copy.")

        existing_target_cats = {
            int(r["category_id"])
            for r in budgets_repo.list_category_budgets_up_to_month(
                conn, min_month=target_month, max_month=target_month
            )
        }
        now = utc_now_iso()
        for row in src_cats:
            cid = int(row["category_id"])
            if not overwrite and cid in existing_target_cats:
                continue
            budgets_repo.upsert_category_budget(
                conn,
                category_id=cid,
                month=target_month,
                limit_minor=int(row["limit_minor"]),
                rollover_enabled=bool(row["rollover_enabled"]),
                now=now,
            )

        if src_overall is not None:
            existing_overall = budgets_repo.get_overall_budget(conn, target_month)
            if overwrite or existing_overall is None:
                budgets_repo.upsert_overall_budget(
                    conn,
                    month=target_month,
                    limit_minor=int(src_overall["limit_minor"]),
                    now=now,
                )

    return get_month_budgets(db_path, month=target_month)
