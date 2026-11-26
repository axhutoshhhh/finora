"""Transaction, account, and category services (authoritative financial boundary)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, categories_repo, transactions_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import utc_now_iso, validate_tx_date

ALLOWED_PHASE1_ENTRY_TYPES = ("expense", "income")
MAX_DESCRIPTION_LENGTH = 240
MAX_IDEMPOTENCY_KEY_LENGTH = 64


def serialize_transaction_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a joined transaction database row into an API dictionary."""
    signed_minor = int(row["signed_amount_minor"])
    abs_minor = abs(signed_minor)
    return {
        "id": int(row["id"]),
        "entry_type": str(row["entry_type"]),
        "account_id": int(row["account_id"]),
        "account_name": str(row["account_name"]),
        "currency": str(row["currency"]),
        "category_id": int(row["category_id"]) if row["category_id"] is not None else None,
        "category_name": str(row["category_name"]) if row["category_name"] is not None else "",
        "category_slug": str(row["category_slug"]) if row["category_slug"] is not None else "",
        "category_icon": str(row["category_icon"]) if row["category_icon"] is not None else "",
        "category_color_token": (
            str(row["category_color_token"]) if row["category_color_token"] is not None else ""
        ),
        "amount_minor": abs_minor,
        "signed_amount_minor": signed_minor,
        "amount_formatted": format_inr_minor(abs_minor),
        "signed_amount_formatted": format_inr_minor(signed_minor, show_plus=True),
        "tx_date": str(row["tx_date"]),
        "description": str(row["description"]),
        "created_at": str(row["created_at"]),
    }


def _parse_positive_int(value: object, *, field: str, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{label} is required.", field=field)
    if value <= 0:
        raise ValidationError(f"Select a valid {label.lower()}.", field=field)
    return value


def _parse_description(raw_value: object) -> str:
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValidationError("Description must be plain text.", field="description")
    cleaned = " ".join(raw_value.strip().splitlines())
    if len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.",
            field="description",
        )
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError(
            "Description contains invalid control characters.", field="description"
        )
    return cleaned


def _parse_idempotency_key(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValidationError("Invalid submission key.", field="idempotency_key")
    key = raw_value.strip()
    if not key:
        return None
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise ValidationError("Invalid submission key format.", field="idempotency_key")
    return key


def create_transaction(
    db_path: Path | str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Validate and record a Phase 1 expense or income transaction atomically.

    Returns (transaction_dict, created_new). If an identical request arrives with
    the same idempotency_key, returns (existing_tx, False) rather than duplicating.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    entry_type = payload.get("entry_type")
    if not isinstance(entry_type, str) or entry_type not in ALLOWED_PHASE1_ENTRY_TYPES:
        raise ValidationError(
            "Transaction type must be 'expense' or 'income'.",
            field="entry_type",
        )

    account_id = _parse_positive_int(payload.get("account_id"), field="account_id", label="Account")
    category_id = _parse_positive_int(
        payload.get("category_id"), field="category_id", label="Category"
    )
    amount_minor = parse_inr_to_minor(payload.get("amount"), field="amount")
    tx_date = validate_tx_date(payload.get("tx_date"), field="tx_date")
    description = _parse_description(payload.get("description"))
    idempotency_key = _parse_idempotency_key(payload.get("idempotency_key"))

    signed_amount_minor = -amount_minor if entry_type == "expense" else amount_minor

    with db_session(db_path, immediate=True) as conn:
        if idempotency_key is not None:
            existing = transactions_repo.get_transaction_by_idempotency_key(conn, idempotency_key)
            if existing is not None:
                existing_cat_id = (
                    int(existing["category_id"]) if existing["category_id"] is not None else None
                )
                matches = (
                    existing["entry_type"] == entry_type
                    and int(existing["account_id"]) == account_id
                    and existing_cat_id == category_id
                    and int(existing["signed_amount_minor"]) == signed_amount_minor
                    and str(existing["tx_date"]) == tx_date
                    and str(existing["description"]) == description
                )
                if not matches:
                    raise ConflictError(
                        "This submission key was already used for a different transaction."
                    )
                return serialize_transaction_row(existing), False

        account = accounts_repo.get_account_by_id(conn, account_id)
        if account is None or int(account["is_archived"]) != 0:
            raise NotFoundError(
                "Selected account was not found or is archived.", field="account_id"
            )

        category = categories_repo.get_category_by_id(conn, category_id)
        if category is None or int(category["is_archived"]) != 0:
            raise NotFoundError(
                "Selected category was not found or is archived.",
                field="category_id",
            )

        if str(category["kind"]) != entry_type:
            raise ValidationError(
                f"Selected category '{category['name']}' is not valid for {entry_type} entries.",
                status_code=422,
                field="category_id",
            )

        now = utc_now_iso()
        tx_id = transactions_repo.create_single_posting_transaction(
            conn,
            entry_type=entry_type,
            tx_date=tx_date,
            description=description,
            idempotency_key=idempotency_key,
            account_id=account_id,
            category_id=category_id,
            signed_amount_minor=signed_amount_minor,
            now=now,
        )
        created = transactions_repo.get_transaction_by_id(conn, tx_id)
        if created is None:  # pragma: no cover - defensive invariant check
            raise ValidationError("Failed to reload created transaction.")
        return serialize_transaction_row(created), True


def list_transactions(
    db_path: Path | str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated chronological transactions and total count."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)
    with db_session(db_path) as conn:
        rows = transactions_repo.list_transactions(conn, limit=bounded_limit, offset=bounded_offset)
        total_count = transactions_repo.count_transactions(conn)
        return {
            "transactions": [serialize_transaction_row(r) for r in rows],
            "total_count": total_count,
            "limit": bounded_limit,
            "offset": bounded_offset,
        }


def list_categories(db_path: Path | str, *, kind: str | None = None) -> list[dict[str, Any]]:
    """Return active categories optionally filtered by 'expense' or 'income'."""
    if kind is not None and kind not in ALLOWED_PHASE1_ENTRY_TYPES:
        raise ValidationError("Category kind must be 'expense' or 'income'.", field="kind")
    with db_session(db_path) as conn:
        rows = categories_repo.list_active_categories(conn, kind=kind)
        return [
            {
                "id": int(r["id"]),
                "slug": str(r["slug"]),
                "name": str(r["name"]),
                "kind": str(r["kind"]),
                "icon": str(r["icon"]),
                "color_token": str(r["color_token"]),
                "sort_order": int(r["sort_order"]),
            }
            for r in rows
        ]


def list_accounts(db_path: Path | str) -> list[dict[str, Any]]:
    """Return active accounts with authoritative computed balances."""
    with db_session(db_path) as conn:
        rows = accounts_repo.list_active_accounts_with_balances(conn)
        return [
            {
                "id": int(r["id"]),
                "name": str(r["name"]),
                "account_type": str(r["account_type"]),
                "currency": str(r["currency"]),
                "is_default": bool(r["is_default"]),
                "opening_balance_minor": int(r["opening_balance_minor"]),
                "balance_minor": int(r["balance_minor"]),
                "balance_formatted": format_inr_minor(int(r["balance_minor"])),
            }
            for r in rows
        ]
