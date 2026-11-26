"""Authoritative savings goals and ledger-backed allocation service."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import utc_now_iso, validate_tx_date


def _serialize_goal(
    row: Any,
    *,
    allocated_minor: int,
    account_name: str | None,
    account_balance_minor: int | None,
    total_account_allocated_minor: int,
    today: date,
) -> dict[str, Any]:
    target_minor = int(row["target_minor"])
    remaining_minor = max(0, target_minor - allocated_minor)
    pct = round((allocated_minor / target_minor) * 100.0, 1) if target_minor > 0 else 0.0
    tdate = row["target_date"]
    overdue = bool(tdate and row["status"] == "active" and date.fromisoformat(tdate) < today)
    underfunded = bool(
        account_balance_minor is not None and total_account_allocated_minor > account_balance_minor
    )
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "target_minor": target_minor,
        "target_formatted": format_inr_minor(target_minor),
        "allocated_minor": allocated_minor,
        "allocated_formatted": format_inr_minor(allocated_minor),
        "remaining_minor": remaining_minor,
        "remaining_formatted": format_inr_minor(remaining_minor),
        "progress_percent": pct,
        "target_date": tdate,
        "description": str(row["description"] or ""),
        "priority": int(row["priority"]),
        "account_id": row["account_id"],
        "account_name": account_name,
        "status": str(row["status"]),
        "overdue": overdue,
        "underfunded": underfunded,
        "created_at": str(row["created_at"]),
    }


def list_goals(
    db_path: Path | str, *, include_archived: bool = False, today: date | None = None
) -> dict[str, Any]:
    ref = today or date.today()
    with db_session(db_path) as conn:
        accts = {
            int(a["id"]): a
            for a in accounts_repo.list_accounts_with_balances(conn, include_archived=True)
        }
        alloc_by_goal = {
            int(r["goal_id"]): int(r["total"])
            for r in conn.execute(
                "SELECT goal_id, COALESCE(SUM(signed_amount_minor), 0) AS total FROM goal_allocations GROUP BY goal_id;"
            ).fetchall()
        }
        alloc_by_acct = {
            int(r["account_id"]): int(r["total"])
            for r in conn.execute(
                """
                SELECT ga.account_id, COALESCE(SUM(ga.signed_amount_minor), 0) AS total
                FROM goal_allocations ga
                JOIN savings_goals g ON g.id = ga.goal_id
                WHERE ga.account_id IS NOT NULL AND g.status != 'archived'
                GROUP BY ga.account_id;
                """
            ).fetchall()
        }
        rows = conn.execute(
            """
            SELECT * FROM savings_goals
            WHERE (? = 1 OR status != 'archived')
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END, priority ASC, id DESC;
            """,
            (1 if include_archived else 0,),
        ).fetchall()

    goals = []
    total_target = 0
    total_allocated = 0
    for r in rows:
        gid = int(r["id"])
        aid = r["account_id"]
        acct = accts.get(int(aid)) if aid is not None else None
        alloc_m = max(0, alloc_by_goal.get(gid, 0))
        if r["status"] != "archived":
            total_target += int(r["target_minor"])
            total_allocated += alloc_m
        goals.append(
            _serialize_goal(
                r,
                allocated_minor=alloc_m,
                account_name=str(acct["name"]) if acct else None,
                account_balance_minor=int(acct["balance_minor"]) if acct else None,
                total_account_allocated_minor=alloc_by_acct.get(int(aid), 0) if aid else 0,
                today=ref,
            )
        )
    return {
        "goals": goals,
        "summary": {
            "total_target_minor": total_target,
            "total_target_formatted": format_inr_minor(total_target),
            "total_allocated_minor": total_allocated,
            "total_allocated_formatted": format_inr_minor(total_allocated),
        },
    }


def create_goal(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationError("Goal name must be 1–100 characters.", field="name")
    target_minor = parse_inr_to_minor(payload.get("target_amount"), field="target_amount")
    tdate_raw = payload.get("target_date")
    tdate = (
        validate_tx_date(tdate_raw, field="target_date", allow_future=True)
        if tdate_raw not in (None, "")
        else None
    )
    desc = str(payload.get("description") or "").strip()[:240]
    priority = int(payload.get("priority") or 2)
    if priority not in (1, 2, 3):
        raise ValidationError("Priority must be 1, 2, or 3.", field="priority")
    account_id = payload.get("account_id")
    now = utc_now_iso()

    with db_session(db_path, immediate=True) as conn:
        if account_id is not None:
            acct = accounts_repo.get_account_by_id(conn, int(account_id))
            if acct is None or int(acct["is_archived"]) == 1:
                raise NotFoundError("Funding account not found.", field="account_id")
            if acct["account_type"] == "credit_card":
                raise ValidationError(
                    "Credit card limits cannot be used as savings goal funding.",
                    field="account_id",
                )
        cur = conn.execute(
            """
            INSERT INTO savings_goals (
                name, target_minor, target_date, description, priority, account_id,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?);
            """,
            (name, target_minor, tdate, desc, priority, account_id, now, now),
        )
        gid = int(cur.lastrowid)
    return get_goal_detail(db_path, gid)["goal"]


def get_goal_detail(db_path: Path | str, goal_id: int) -> dict[str, Any]:
    all_goals = list_goals(db_path, include_archived=True)["goals"]
    goal = next((g for g in all_goals if g["id"] == goal_id), None)
    if goal is None:
        raise NotFoundError("Savings goal not found.", field="goal_id")
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM goal_allocations WHERE goal_id = ? ORDER BY allocation_date DESC, id DESC;",
            (goal_id,),
        ).fetchall()
    contributions = [
        {
            "id": int(r["id"]),
            "goal_id": int(r["goal_id"]),
            "account_id": r["account_id"],
            "signed_amount_minor": int(r["signed_amount_minor"]),
            "amount_formatted": format_inr_minor(int(r["signed_amount_minor"]), show_plus=True),
            "allocation_date": str(r["allocation_date"]),
            "note": str(r["note"] or ""),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]
    return {"goal": goal, "contributions": contributions}


def add_contribution(
    db_path: Path | str, goal_id: int, payload: dict[str, Any], *, is_withdrawal: bool = False
) -> dict[str, Any]:
    amt_minor = parse_inr_to_minor(payload.get("amount"), field="amount")
    alloc_date = validate_tx_date(
        payload.get("allocation_date") or date.today().isoformat(),
        field="allocation_date",
        allow_future=False,
    )
    note = str(payload.get("note") or "").strip()[:240]
    signed = -amt_minor if is_withdrawal else amt_minor
    now = utc_now_iso()

    with db_session(db_path, immediate=True) as conn:
        g_row = conn.execute("SELECT * FROM savings_goals WHERE id = ?;", (goal_id,)).fetchone()
        if g_row is None:
            raise NotFoundError("Savings goal not found.", field="goal_id")
        if g_row["status"] == "archived":
            raise ConflictError("Cannot modify contributions on an archived goal.")
        cur_alloc = int(
            conn.execute(
                "SELECT COALESCE(SUM(signed_amount_minor), 0) FROM goal_allocations WHERE goal_id = ?;",
                (goal_id,),
            ).fetchone()[0]
        )
        if is_withdrawal and amt_minor > cur_alloc:
            raise ValidationError("Withdrawal exceeds current goal allocation.", field="amount")
        aid = (
            payload.get("account_id")
            if payload.get("account_id") is not None
            else g_row["account_id"]
        )
        if not is_withdrawal and aid is not None:
            accts = {
                int(a["id"]): a
                for a in accounts_repo.list_accounts_with_balances(conn, include_archived=False)
            }
            acct = accts.get(int(aid))
            if acct is None:
                raise NotFoundError("Funding account not found.", field="account_id")
            if acct["account_type"] == "credit_card":
                raise ValidationError("Cannot allocate from a credit card.", field="account_id")
            already_alloc = int(
                conn.execute(
                    """
                    SELECT COALESCE(SUM(ga.signed_amount_minor), 0)
                    FROM goal_allocations ga
                    JOIN savings_goals g ON g.id = ga.goal_id
                    WHERE ga.account_id = ? AND g.status != 'archived';
                    """,
                    (int(aid),),
                ).fetchone()[0]
            )
            if already_alloc + amt_minor > int(acct["balance_minor"]):
                raise ConflictError(
                    "Insufficient unallocated account balance for this goal contribution.",
                    code="insufficient_unallocated_balance",
                )

        conn.execute(
            """
            INSERT INTO goal_allocations (goal_id, account_id, signed_amount_minor, allocation_date, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (goal_id, aid, signed, alloc_date, note, now),
        )
        conn.execute("UPDATE savings_goals SET updated_at = ? WHERE id = ?;", (now, goal_id))
    return get_goal_detail(db_path, goal_id)


def update_goal_status(db_path: Path | str, goal_id: int, status: str) -> dict[str, Any]:
    if status not in ("active", "completed", "archived"):
        raise ValidationError("Invalid goal status.", field="status")
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute(
            """
            UPDATE savings_goals
            SET status = ?,
                completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END,
                archived_at = CASE WHEN ? = 'archived' THEN ? ELSE NULL END,
                updated_at = ?
            WHERE id = ?;
            """,
            (status, status, now, status, now, now, goal_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Savings goal not found.", field="goal_id")
    return get_goal_detail(db_path, goal_id)["goal"]
