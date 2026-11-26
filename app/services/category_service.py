"""Category management services (system preservation, custom creation, safe archival)."""

from __future__ import annotations

import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import categories_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.time import utc_now_iso

VALID_CATEGORY_KINDS = ("expense", "income")
APPROVED_CATEGORY_ICONS = (
    "utensils",
    "house",
    "car",
    "shopping-bag",
    "book-open",
    "heart-pulse",
    "film",
    "repeat",
    "zap",
    "circle-ellipsis",
    "briefcase",
    "coins",
    "laptop",
    "graduation-cap",
    "building-2",
    "gift",
    "plus-circle",
    "tag",
    "folder",
    "shield-check",
)
APPROVED_COLOR_CLASSES = (
    "cat-forest",
    "cat-amber",
    "cat-slate",
    "cat-teal",
    "cat-clay",
    "cat-indigo",
    "cat-rose",
    "cat-plum",
    "cat-sage",
    "cat-ochre",
    "cat-stone",
)


def _serialize_category(row: sqlite3.Row) -> dict[str, Any]:
    tx_count = int(row["transaction_count"]) if "transaction_count" in row.keys() else 0  # noqa: SIM118
    return {
        "id": int(row["id"]),
        "slug": str(row["slug"]),
        "name": str(row["name"]),
        "kind": str(row["kind"]),
        "icon": str(row["icon"]),
        "color_token": str(row["color_token"]),
        "sort_order": int(row["sort_order"]),
        "is_system": bool(row["is_system"]),
        "is_archived": bool(row["is_archived"]),
        "transaction_count": tx_count,
    }


def _parse_category_name(raw_value: object) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValidationError("Category name is required.", field="name")
    cleaned = " ".join(raw_value.strip().split())
    if len(cleaned) > 48:
        raise ValidationError("Category name must be 48 characters or fewer.", field="name")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Category name contains invalid characters.", field="name")
    return cleaned


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:28] or "category"
    return f"custom_{base}_{secrets.token_hex(3)}"


def list_categories(
    db_path: Path | str,
    *,
    kind: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Return categories filtered optionally by kind and archive flag."""
    if kind is not None and kind not in VALID_CATEGORY_KINDS:
        raise ValidationError("Category kind must be 'expense' or 'income'.", field="kind")
    with db_session(db_path) as conn:
        rows = categories_repo.list_categories(conn, kind=kind, include_archived=include_archived)
        return [_serialize_category(r) for r in rows]


def create_category(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a custom expense or income category without mixing kinds."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in VALID_CATEGORY_KINDS:
        raise ValidationError("Category kind must be 'expense' or 'income'.", field="kind")
    name = _parse_category_name(payload.get("name"))

    icon = payload.get("icon") or ("circle-ellipsis" if kind == "expense" else "plus-circle")
    if not isinstance(icon, str) or icon not in APPROVED_CATEGORY_ICONS:
        raise ValidationError("Select an approved local category icon.", field="icon")

    color_style = payload.get("color_token") or ("cat-stone" if kind == "expense" else "cat-forest")
    if not isinstance(color_style, str) or color_style not in APPROVED_COLOR_CLASSES:
        raise ValidationError("Select an approved color choice.", field="color_token")

    with db_session(db_path, immediate=True) as conn:
        dup = categories_repo.get_active_category_by_name_ci(conn, kind=kind, name=name)
        if dup is not None:
            raise ConflictError(
                f"An active {kind} category named '{dup['name']}' already exists.",
                field="name",
            )
        sort_order_raw = payload.get("sort_order")
        if sort_order_raw is not None:
            if (
                isinstance(sort_order_raw, bool)
                or not isinstance(sort_order_raw, int)
                or sort_order_raw < 1
            ):
                raise ValidationError("Sort order must be a positive integer.", field="sort_order")
            sort_order = sort_order_raw
        else:
            sort_order = categories_repo.get_next_sort_order(conn, kind)

        new_id = categories_repo.create_category(
            conn,
            slug=_slugify(name),
            name=name,
            kind=kind,
            icon=icon,
            color_token=color_style,
            sort_order=sort_order,
            now=utc_now_iso(),
        )
        created = categories_repo.get_category_by_id(conn, new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Created category could not be loaded.")
        return _serialize_category(created)


def update_category(
    db_path: Path | str,
    category_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Rename or customize a category while keeping its stable slug and kind immutable."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    with db_session(db_path, immediate=True) as conn:
        existing = categories_repo.get_category_by_id(conn, category_id)
        if existing is None:
            raise NotFoundError("Category not found.", field="category_id")

        kind = str(existing["kind"])
        if "kind" in payload and payload["kind"] != kind:
            raise ValidationError(
                "Changing a category between expense and income is not allowed.",
                status_code=422,
                field="kind",
            )

        name = _parse_category_name(payload["name"]) if "name" in payload else str(existing["name"])
        if int(existing["is_archived"]) == 0:
            dup = categories_repo.get_active_category_by_name_ci(
                conn, kind=kind, name=name, exclude_category_id=category_id
            )
            if dup is not None:
                raise ConflictError(
                    f"An active {kind} category named '{dup['name']}' already exists.",
                    field="name",
                )

        icon = str(payload.get("icon") or existing["icon"])
        if icon not in APPROVED_CATEGORY_ICONS:
            raise ValidationError("Select an approved local category icon.", field="icon")

        color_style = str(payload.get("color_token") or existing["color_token"])
        if color_style not in APPROVED_COLOR_CLASSES:
            raise ValidationError("Select an approved color choice.", field="color_token")

        sort_order_raw = payload.get("sort_order", int(existing["sort_order"]))
        if (
            isinstance(sort_order_raw, bool)
            or not isinstance(sort_order_raw, int)
            or sort_order_raw < 1
        ):
            raise ValidationError("Sort order must be a positive integer.", field="sort_order")

        categories_repo.update_category(
            conn,
            category_id=category_id,
            name=name,
            icon=icon,
            color_token=color_style,
            sort_order=sort_order_raw,
        )
        updated = categories_repo.get_category_by_id(conn, category_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Category not found.")
        return _serialize_category(updated)


def archive_category(db_path: Path | str, category_id: int) -> dict[str, Any]:
    """Archive a category without altering historical transactions."""
    with db_session(db_path, immediate=True) as conn:
        existing = categories_repo.get_category_by_id(conn, category_id)
        if existing is None:
            raise NotFoundError("Category not found.", field="category_id")
        if int(existing["is_archived"]) == 1:
            return _serialize_category(existing)

        kind = str(existing["kind"])
        if categories_repo.count_active_categories_of_kind(conn, kind) <= 1:
            raise ConflictError(
                f"At least one active {kind} category must remain available.",
                code="last_active_category",
            )
        categories_repo.set_category_archived(conn, category_id=category_id, archived=True)
        updated = categories_repo.get_category_by_id(conn, category_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Category not found.")
        return _serialize_category(updated)


def restore_category(db_path: Path | str, category_id: int) -> dict[str, Any]:
    """Restore an archived category."""
    with db_session(db_path, immediate=True) as conn:
        existing = categories_repo.get_category_by_id(conn, category_id)
        if existing is None:
            raise NotFoundError("Category not found.", field="category_id")
        if int(existing["is_archived"]) == 0:
            return _serialize_category(existing)

        dup = categories_repo.get_active_category_by_name_ci(
            conn,
            kind=str(existing["kind"]),
            name=str(existing["name"]),
            exclude_category_id=category_id,
        )
        if dup is not None:
            raise ConflictError(
                f"An active {existing['kind']} category named '{dup['name']}' already exists.",
                field="name",
            )
        categories_repo.set_category_archived(conn, category_id=category_id, archived=False)
        updated = categories_repo.get_category_by_id(conn, category_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Category not found.")
        return _serialize_category(updated)
