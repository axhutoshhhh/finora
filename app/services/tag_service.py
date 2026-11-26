"""User-defined transaction tag services."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import tags_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.time import utc_now_iso


def _serialize_tag(row: sqlite3.Row) -> dict[str, Any]:
    count = int(row["transaction_count"]) if "transaction_count" in row.keys() else 0  # noqa: SIM118
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "transaction_count": count,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _parse_tag_name(raw_value: object) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValidationError("Tag name is required.", field="name")
    cleaned = " ".join(raw_value.strip().split())
    if len(cleaned) > 40:
        raise ValidationError("Tag name must be 40 characters or fewer.", field="name")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Tag name contains invalid characters.", field="name")
    return cleaned


def list_tags(db_path: Path | str) -> list[dict[str, Any]]:
    """Return all user-defined tags ordered alphabetically."""
    with db_session(db_path) as conn:
        return [_serialize_tag(r) for r in tags_repo.list_tags(conn)]


def create_tag(db_path: Path | str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Create a tag or raise ConflictError if name already exists (case-insensitive)."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    name = _parse_tag_name(payload.get("name"))
    with db_session(db_path, immediate=True) as conn:
        existing = tags_repo.get_tag_by_name_ci(conn, name)
        if existing is not None:
            raise ConflictError(f"Tag '{existing['name']}' already exists.", field="name")
        now = utc_now_iso()
        tag_id = tags_repo.create_tag(conn, name=name, now=now)
        row = tags_repo.get_tag_by_id(conn, tag_id)
        if row is None:  # pragma: no cover
            raise NotFoundError("Created tag not found.")
        return _serialize_tag(row), True


def update_tag(db_path: Path | str, tag_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Rename an existing tag safely."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    name = _parse_tag_name(payload.get("name"))
    with db_session(db_path, immediate=True) as conn:
        existing = tags_repo.get_tag_by_id(conn, tag_id)
        if existing is None:
            raise NotFoundError("Tag not found.", field="tag_id")
        dup = tags_repo.get_tag_by_name_ci(conn, name, exclude_tag_id=tag_id)
        if dup is not None:
            raise ConflictError(f"Tag '{dup['name']}' already exists.", field="name")
        tags_repo.rename_tag(conn, tag_id=tag_id, name=name, now=utc_now_iso())
        updated = tags_repo.get_tag_by_id(conn, tag_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Tag not found.")
        return _serialize_tag(updated)


def delete_tag(db_path: Path | str, tag_id: int) -> dict[str, Any]:
    """Delete a tag while preserving all transactions."""
    with db_session(db_path, immediate=True) as conn:
        existing = tags_repo.get_tag_by_id(conn, tag_id)
        if existing is None:
            raise NotFoundError("Tag not found.", field="tag_id")
        tags_repo.delete_tag(conn, tag_id=tag_id)
        return {"deleted": True, "id": tag_id}
