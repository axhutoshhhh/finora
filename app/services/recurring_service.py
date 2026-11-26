"""Recurring transaction rules, calendar anchor math, and idempotent occurrence posting."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, categories_repo, tags_repo, transactions_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import utc_now_iso, validate_tx_date

VALID_FREQUENCIES = ("weekly", "biweekly", "monthly", "quarterly", "yearly")
MAX_CATCHUP_OCCURRENCES = 24


def advance_recurrence_date(current: date, *, frequency: str, anchor_day: int) -> date:
    """Advance a recurrence date while preserving the original anchor_day across short months."""
    if frequency == "weekly":
        return current + timedelta(days=7)
    if frequency == "biweekly":
        return current + timedelta(days=14)
    if frequency in ("monthly", "quarterly"):
        months_to_add = 1 if frequency == "monthly" else 3
        total_m = (current.year * 12 + (current.month - 1)) + months_to_add
        ny, nm = divmod(total_m, 12)
        nm += 1
        max_d = calendar.monthrange(ny, nm)[1]
        return date(ny, nm, min(anchor_day, max_d))
    if frequency == "yearly":
        ny = current.year + 1
        max_d = calendar.monthrange(ny, current.month)[1]
        return date(ny, current.month, min(anchor_day, max_d))
    raise ValidationError("Invalid recurrence frequency.", field="frequency")


def _monthly_equivalent_minor(amount_minor: int, frequency: str) -> int:
    if frequency == "weekly":
        return round((amount_minor * 52) / 12)
    if frequency == "biweekly":
        return round((amount_minor * 26) / 12)
    if frequency == "monthly":
        return amount_minor
    if frequency == "quarterly":
        return round(amount_minor / 3)
    if frequency == "yearly":
        return round(amount_minor / 12)
    return amount_minor


def create_rule(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationError("Rule name must be 1–100 characters.", field="name")
    entry_type = str(payload.get("entry_type") or "expense")
    if entry_type not in ("expense", "income", "transfer"):
        raise ValidationError("Invalid recurring entry type.", field="entry_type")
    frequency = str(payload.get("frequency") or "monthly")
    if frequency not in VALID_FREQUENCIES:
        raise ValidationError("Invalid recurrence frequency.", field="frequency")
    amount_minor = parse_inr_to_minor(payload.get("amount"), field="amount")
    start_iso = validate_tx_date(payload.get("start_date"), field="start_date", allow_future=True)
    end_raw = payload.get("end_date")
    end_iso = (
        validate_tx_date(end_raw, field="end_date", allow_future=True)
        if end_raw not in (None, "")
        else None
    )
    if end_iso and end_iso < start_iso:
        raise ValidationError("End date cannot precede start date.", field="end_date")

    account_id = int(payload.get("account_id") or 0)
    to_account_id = payload.get("to_account_id")
    category_id = payload.get("category_id")
    is_sub = 1 if payload.get("is_subscription") else 0
    auto_post = 1 if payload.get("auto_post") else 0
    merchant = str(payload.get("merchant") or "").strip()[:120]
    notes = str(payload.get("notes") or "").strip()[:240]
    anchor_day = date.fromisoformat(start_iso).day
    now = utc_now_iso()

    with db_session(db_path, immediate=True) as conn:
        acct = accounts_repo.get_account_by_id(conn, account_id)
        if acct is None or int(acct["is_archived"]) == 1:
            raise NotFoundError("Account not found.", field="account_id")
        if entry_type in ("expense", "income"):
            if category_id is None:
                raise ValidationError("Category is required.", field="category_id")
            cat = categories_repo.get_category_by_id(conn, int(category_id))
            if cat is None or str(cat["kind"]) != entry_type:
                raise ValidationError("Invalid category for recurring rule.", field="category_id")
        cur = conn.execute(
            """
            INSERT INTO recurring_rules (
                name, entry_type, is_subscription, amount_minor, account_id, to_account_id,
                category_id, merchant, payment_method, frequency, start_date, next_occurrence_date,
                end_date, anchor_day, reminder_days_before, auto_post, notes, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'other', ?, ?, ?, ?, ?, 3, ?, ?, 'active', ?, ?);
            """,
            (
                name,
                entry_type,
                is_sub,
                amount_minor,
                account_id,
                to_account_id,
                category_id,
                merchant,
                frequency,
                start_iso,
                start_iso,
                end_iso,
                anchor_day,
                auto_post,
                notes,
                now,
                now,
            ),
        )
        rid = int(cur.lastrowid)
    sync_occurrences(db_path, today=date.fromisoformat(start_iso))
    return next(r for r in list_rules(db_path)["rules"] if r["id"] == rid)


def sync_occurrences(db_path: Path | str, *, today: date | None = None) -> None:
    """Materialize bounded upcoming/due/overdue occurrences for active recurring rules."""
    ref = today or date.today()
    horizon = ref + timedelta(days=35)
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        rules = conn.execute("SELECT * FROM recurring_rules WHERE status = 'active';").fetchall()
        for rule in rules:
            rid = int(rule["id"])
            next_d = date.fromisoformat(rule["next_occurrence_date"])
            end_d = date.fromisoformat(rule["end_date"]) if rule["end_date"] else None
            generated = 0
            while next_d <= horizon and generated < MAX_CATCHUP_OCCURRENCES:
                if end_d and next_d > end_d:
                    break
                status = "overdue" if next_d < ref else ("due" if next_d == ref else "upcoming")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO recurring_occurrences (
                        rule_id, scheduled_date, amount_minor, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (rid, next_d.isoformat(), int(rule["amount_minor"]), status, now, now),
                )
                next_d = advance_recurrence_date(
                    next_d, frequency=str(rule["frequency"]), anchor_day=int(rule["anchor_day"])
                )
                generated += 1
            conn.execute(
                "UPDATE recurring_rules SET next_occurrence_date = ?, updated_at = ? WHERE id = ?;",
                (next_d.isoformat(), now, rid),
            )


def list_rules(db_path: Path | str) -> dict[str, Any]:
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT * FROM recurring_rules ORDER BY id DESC;").fetchall()
    rules = []
    sub_monthly_minor = 0
    for r in rows:
        amt = int(r["amount_minor"])
        freq = str(r["frequency"])
        m_eq = _monthly_equivalent_minor(amt, freq)
        if int(r["is_subscription"]) == 1 and r["status"] == "active":
            sub_monthly_minor += m_eq
        rules.append(
            {
                "id": int(r["id"]),
                "name": str(r["name"]),
                "entry_type": str(r["entry_type"]),
                "is_subscription": bool(int(r["is_subscription"])),
                "amount_minor": amt,
                "amount_formatted": format_inr_minor(amt),
                "monthly_equivalent_minor": m_eq,
                "monthly_equivalent_formatted": format_inr_minor(m_eq),
                "frequency": freq,
                "account_id": int(r["account_id"]),
                "category_id": r["category_id"],
                "merchant": str(r["merchant"] or ""),
                "start_date": str(r["start_date"]),
                "next_occurrence_date": str(r["next_occurrence_date"]),
                "status": str(r["status"]),
            }
        )
    return {
        "rules": rules,
        "subscription_summary": {
            "estimated_monthly_minor": sub_monthly_minor,
            "estimated_monthly_formatted": format_inr_minor(sub_monthly_minor),
            "estimated_annual_minor": sub_monthly_minor * 12,
            "estimated_annual_formatted": format_inr_minor(sub_monthly_minor * 12),
        },
    }


def list_occurrences(db_path: Path | str) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT o.*, r.name AS rule_name, r.entry_type, r.is_subscription, r.merchant
            FROM recurring_occurrences o
            JOIN recurring_rules r ON r.id = o.rule_id
            ORDER BY o.scheduled_date ASC, o.id ASC;
            """
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "rule_id": int(r["rule_id"]),
            "rule_name": str(r["rule_name"]),
            "entry_type": str(r["entry_type"]),
            "is_subscription": bool(int(r["is_subscription"])),
            "merchant": str(r["merchant"] or ""),
            "scheduled_date": str(r["scheduled_date"]),
            "amount_minor": int(r["amount_minor"]),
            "amount_formatted": format_inr_minor(int(r["amount_minor"])),
            "status": str(r["status"]),
            "posted_transaction_id": r["posted_transaction_id"],
        }
        for r in rows
    ]


def post_occurrence(db_path: Path | str, occurrence_id: int) -> dict[str, Any]:
    """Atomically and idempotently post a scheduled recurring occurrence into the ledger."""
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        occ = conn.execute(
            "SELECT * FROM recurring_occurrences WHERE id = ?;", (occurrence_id,)
        ).fetchone()
        if occ is None:
            raise NotFoundError("Recurring occurrence not found.", field="occurrence_id")
        if occ["status"] == "posted" and occ["posted_transaction_id"] is not None:
            return {
                "occurrence_id": occurrence_id,
                "transaction_id": int(occ["posted_transaction_id"]),
                "created": False,
            }
        if occ["status"] in ("skipped", "canceled"):
            raise ConflictError("Cannot post a skipped or canceled occurrence.")

        rule = conn.execute(
            "SELECT * FROM recurring_rules WHERE id = ?;", (int(occ["rule_id"]),)
        ).fetchone()
        amt = int(occ["amount_minor"])
        etype = str(rule["entry_type"])
        signed = amt if etype == "income" else -amt
        tx_id = transactions_repo.create_multi_posting_transaction(
            conn,
            entry_type=etype,
            tx_date=str(occ["scheduled_date"]),
            description=str(rule["name"]),
            merchant=str(rule["merchant"] or ""),
            payment_method=str(rule["payment_method"] or "other"),
            is_split=False,
            idempotency_key=f"recurring-occ-{occurrence_id}",
            postings=[(int(rule["account_id"]), rule["category_id"], signed)],
            now=now,
        )
        conn.execute(
            """
            UPDATE recurring_occurrences
            SET status = 'posted', posted_transaction_id = ?, resolved_at = ?, updated_at = ?
            WHERE id = ?;
            """,
            (tx_id, now, now, occurrence_id),
        )
        _ = tags_repo  # keep import clean if needed
    return {"occurrence_id": occurrence_id, "transaction_id": tx_id, "created": True}


def skip_occurrence(db_path: Path | str, occurrence_id: int) -> dict[str, Any]:
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute(
            """
            UPDATE recurring_occurrences
            SET status = 'skipped', resolved_at = ?, updated_at = ?
            WHERE id = ? AND status IN ('upcoming', 'due', 'overdue');
            """,
            (now, now, occurrence_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Pending recurring occurrence not found.", field="occurrence_id")
    return {"occurrence_id": occurrence_id, "status": "skipped"}


def update_rule_status(db_path: Path | str, rule_id: int, status: str) -> dict[str, Any]:
    if status not in ("active", "paused", "ended", "archived"):
        raise ValidationError("Invalid recurring rule status.", field="status")
    now = utc_now_iso()
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute(
            "UPDATE recurring_rules SET status = ?, updated_at = ? WHERE id = ?;",
            (status, now, rule_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Recurring rule not found.", field="rule_id")
    return {"id": rule_id, "status": status}
