"""Transparent, deterministic merchant-based automatic categorization service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import categories_repo
from app.utils.errors import NotFoundError, ValidationError
from app.utils.time import utc_now_iso


def list_rules(db_path: Path | str) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT cr.*, c.name AS category_name, c.is_archived AS category_archived
            FROM categorization_rules cr
            JOIN categories c ON c.id = cr.target_category_id
            ORDER BY cr.priority ASC, cr.id ASC;
            """
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "name": str(r["name"]),
            "match_field": str(r["match_field"]),
            "match_type": str(r["match_type"]),
            "pattern": str(r["pattern"]),
            "entry_type": str(r["entry_type"]),
            "target_category_id": int(r["target_category_id"]),
            "category_name": str(r["category_name"]),
            "priority": int(r["priority"]),
            "is_enabled": bool(int(r["is_enabled"])),
        }
        for r in rows
    ]


def create_rule(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationError("Rule name must be 1–100 characters.", field="name")
    match_field = str(payload.get("match_field") or "merchant")
    if match_field not in ("merchant", "description"):
        raise ValidationError("Invalid match field.", field="match_field")
    match_type = str(payload.get("match_type") or "contains")
    if match_type not in ("exact", "contains", "starts_with"):
        raise ValidationError("Invalid match type.", field="match_type")
    pattern = str(payload.get("pattern") or "").strip()
    if not pattern or len(pattern) > 120:
        raise ValidationError("Pattern must be 1–120 characters.", field="pattern")
    entry_type = str(payload.get("entry_type") or "expense")
    if entry_type not in ("expense", "income"):
        raise ValidationError("Entry type must be expense or income.", field="entry_type")
    target_category_id = int(payload.get("target_category_id") or 0)
    priority = int(payload.get("priority") or 100)
    if priority < 1 or priority > 10000:
        raise ValidationError("Priority must be between 1 and 10000.", field="priority")
    now = utc_now_iso()

    with db_session(db_path, immediate=True) as conn:
        cat = categories_repo.get_category_by_id(conn, target_category_id)
        if cat is None or int(cat["is_archived"]) == 1:
            raise NotFoundError("Target category not found.", field="target_category_id")
        if str(cat["kind"]) != entry_type:
            raise ValidationError(
                "Target category kind must match rule entry_type.", field="target_category_id"
            )
        cur = conn.execute(
            """
            INSERT INTO categorization_rules (
                name, match_field, match_type, pattern, entry_type,
                target_category_id, priority, is_enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
            """,
            (
                name,
                match_field,
                match_type,
                pattern,
                entry_type,
                target_category_id,
                priority,
                now,
                now,
            ),
        )
        rid = int(cur.lastrowid)
    return next(r for r in list_rules(db_path) if r["id"] == rid)


def delete_rule(db_path: Path | str, rule_id: int) -> dict[str, Any]:
    with db_session(db_path, immediate=True) as conn:
        cur = conn.execute("DELETE FROM categorization_rules WHERE id = ?;", (rule_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Categorization rule not found.", field="rule_id")
    return {"deleted": True, "id": rule_id}


def suggest_category(
    db_path: Path | str,
    *,
    entry_type: str = "expense",
    merchant: str = "",
    description: str = "",
) -> dict[str, Any] | None:
    """Return highest-priority matching active category suggestion, or None."""
    if entry_type not in ("expense", "income"):
        return None
    m_low = merchant.strip().lower()
    d_low = description.strip().lower()
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT cr.*, c.name AS category_name
            FROM categorization_rules cr
            JOIN categories c ON c.id = cr.target_category_id
            WHERE cr.is_enabled = 1
              AND cr.entry_type = ?
              AND c.is_archived = 0
              AND c.kind = ?
            ORDER BY cr.priority ASC, cr.id ASC;
            """,
            (entry_type, entry_type),
        ).fetchall()

    for r in rows:
        haystack = m_low if r["match_field"] == "merchant" else d_low
        needle = str(r["pattern"]).strip().lower()
        if not haystack or not needle:
            continue
        mt = str(r["match_type"])
        matched = (
            (mt == "exact" and haystack == needle)
            or (mt == "contains" and needle in haystack)
            or (mt == "starts_with" and haystack.startswith(needle))
        )
        if matched:
            return {
                "category_id": int(r["target_category_id"]),
                "category_name": str(r["category_name"]),
                "rule_id": int(r["id"]),
                "rule_name": str(r["name"]),
            }
    return None
