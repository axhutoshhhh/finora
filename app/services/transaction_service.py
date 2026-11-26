"""Transaction, transfer, and lookup services (authoritative financial boundary)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, categories_repo, transactions_repo
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import utc_now_iso, validate_tx_date

ALLOWED_ENTRY_TYPES = ("expense", "income", "transfer", "refund")
ALLOWED_PHASE1_CREATE_TYPES = ("expense", "income")
VALID_PAYMENT_METHODS = ("cash", "upi", "debit_card", "credit_card", "bank_transfer", "other")
MAX_DESCRIPTION_LENGTH = 240
MAX_MERCHANT_LENGTH = 120
MAX_IDEMPOTENCY_KEY_LENGTH = 64


def _serialize_posting(row: sqlite3.Row) -> dict[str, Any]:
    signed_minor = int(row["signed_amount_minor"])
    return {
        "posting_id": int(row["posting_id"]),
        "account_id": int(row["account_id"]),
        "account_name": str(row["account_name"]),
        "account_type": str(row["account_type"]),
        "currency": str(row["currency"]),
        "category_id": int(row["category_id"]) if row["category_id"] is not None else None,
        "category_name": str(row["category_name"]) if row["category_name"] is not None else "",
        "category_slug": str(row["category_slug"]) if row["category_slug"] is not None else "",
        "category_icon": str(row["category_icon"]) if row["category_icon"] is not None else "",
        "category_color_token": (
            str(row["category_color_token"]) if row["category_color_token"] is not None else ""
        ),
        "amount_minor": abs(signed_minor),
        "signed_amount_minor": signed_minor,
        "amount_formatted": format_inr_minor(abs(signed_minor)),
        "signed_amount_formatted": format_inr_minor(signed_minor, show_plus=True),
    }


def group_and_serialize_transaction_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Group multi-posting joined SQL rows into single logical API transaction objects."""
    grouped: dict[int, list[sqlite3.Row]] = {}
    order: list[int] = []
    for r in rows:
        tx_id = int(r["id"])
        if tx_id not in grouped:
            grouped[tx_id] = []
            order.append(tx_id)
        grouped[tx_id].append(r)

    results: list[dict[str, Any]] = []
    for tx_id in order:
        tx_rows = grouped[tx_id]
        head = tx_rows[0]
        entry_type = str(head["entry_type"])
        postings = [_serialize_posting(r) for r in tx_rows]

        if entry_type == "transfer" and len(postings) == 2:
            # Ordered signed_amount_minor ASC -> index 0 is negative (source), index 1 is positive (destination)
            src = postings[0] if postings[0]["signed_amount_minor"] < 0 else postings[1]
            dst = postings[1] if postings[0]["signed_amount_minor"] < 0 else postings[0]
            abs_minor = src["amount_minor"]
            signed_minor = abs_minor
            is_repayment = dst["account_type"] == "credit_card"
            account_label = f"{src['account_name']} → {dst['account_name']}"
            cat_name = "Card Repayment" if is_repayment else "Transfer"
            results.append(
                {
                    "id": tx_id,
                    "entry_type": "transfer",
                    "transfer_subtype": "credit_card_repayment" if is_repayment else "transfer",
                    "account_id": src["account_id"],
                    "account_name": account_label,
                    "from_account_id": src["account_id"],
                    "from_account_name": src["account_name"],
                    "to_account_id": dst["account_id"],
                    "to_account_name": dst["account_name"],
                    "currency": src["currency"],
                    "category_id": None,
                    "category_name": cat_name,
                    "category_slug": "",
                    "category_icon": "arrow-left-right",
                    "category_color_token": "cat-slate",
                    "amount_minor": abs_minor,
                    "signed_amount_minor": signed_minor,
                    "amount_formatted": format_inr_minor(abs_minor),
                    "signed_amount_formatted": format_inr_minor(abs_minor),
                    "tx_date": str(head["tx_date"]),
                    "merchant": str(head["merchant"] or ""),
                    "payment_method": str(head["payment_method"] or "bank_transfer"),
                    "description": str(head["description"] or ""),
                    "related_transaction_id": head["related_transaction_id"],
                    "is_split": False,
                    "revision": int(head["revision"]),
                    "deleted_at": head["deleted_at"],
                    "postings": postings,
                    "created_at": str(head["created_at"]),
                    "updated_at": str(head["updated_at"]),
                }
            )
            continue

        total_signed = sum(p["signed_amount_minor"] for p in postings)
        abs_total = abs(total_signed)
        is_split = bool(head["is_split"]) or len(postings) > 1
        primary = postings[0]
        cat_name = (
            f"Split ({len(postings)} categories)"
            if is_split
            else (primary["category_name"] or "Uncategorized")
        )
        cat_icon = "split" if is_split else primary["category_icon"]

        results.append(
            {
                "id": tx_id,
                "entry_type": entry_type,
                "account_id": primary["account_id"],
                "account_name": primary["account_name"],
                "currency": primary["currency"],
                "category_id": None if is_split else primary["category_id"],
                "category_name": cat_name,
                "category_slug": "" if is_split else primary["category_slug"],
                "category_icon": cat_icon,
                "category_color_token": "cat-stone"
                if is_split
                else primary["category_color_token"],
                "amount_minor": abs_total,
                "signed_amount_minor": total_signed,
                "amount_formatted": format_inr_minor(abs_total),
                "signed_amount_formatted": format_inr_minor(total_signed, show_plus=True),
                "tx_date": str(head["tx_date"]),
                "merchant": str(head["merchant"] or ""),
                "payment_method": str(head["payment_method"] or "other"),
                "description": str(head["description"] or ""),
                "related_transaction_id": (
                    int(head["related_transaction_id"])
                    if head["related_transaction_id"] is not None
                    else None
                ),
                "is_split": is_split,
                "revision": int(head["revision"]),
                "deleted_at": head["deleted_at"],
                "postings": postings,
                "created_at": str(head["created_at"]),
                "updated_at": str(head["updated_at"]),
            }
        )
    return results


def serialize_transaction_row(row: sqlite3.Row) -> dict[str, Any]:
    """Serialize a single SQL row via the canonical multi-posting serializer."""
    return group_and_serialize_transaction_rows([row])[0]


def _parse_positive_int(value: object, *, field: str, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{label} is required.", field=field)
    if value <= 0:
        raise ValidationError(f"Select a valid {label.lower()}.", field=field)
    return value


def _parse_clean_text(raw_value: object, *, field: str, label: str, max_len: int) -> str:
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValidationError(f"{label} must be plain text.", field=field)
    cleaned = " ".join(raw_value.strip().splitlines())
    if len(cleaned) > max_len:
        raise ValidationError(
            f"{label} must be {max_len} characters or fewer.",
            field=field,
        )
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError(
            f"{label} contains invalid control characters.",
            field=field,
        )
    return cleaned


def _parse_payment_method(raw_value: object, *, default: str = "other") -> str:
    if raw_value is None or raw_value == "":
        return default
    if not isinstance(raw_value, str) or raw_value not in VALID_PAYMENT_METHODS:
        raise ValidationError("Select a valid payment method.", field="payment_method")
    return raw_value


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
    """Validate and record a Phase 2 single-posting expense or income transaction atomically."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    entry_type = payload.get("entry_type")
    if not isinstance(entry_type, str) or entry_type not in ALLOWED_PHASE1_CREATE_TYPES:
        raise ValidationError(
            "Transaction type must be 'expense' or 'income'.",
            field="entry_type",
        )

    account_id = _parse_positive_int(payload.get("account_id"), field="account_id", label="Account")
    category_id = _parse_positive_int(
        payload.get("category_id"), field="category_id", label="Category"
    )
    amount_minor = parse_inr_to_minor(payload.get("amount"), field="amount")
    tx_date = validate_tx_date(payload.get("tx_date"), field="tx_date", allow_future=False)
    description = _parse_clean_text(
        payload.get("description"),
        field="description",
        label="Description",
        max_len=MAX_DESCRIPTION_LENGTH,
    )
    merchant = _parse_clean_text(
        payload.get("merchant"),
        field="merchant",
        label="Merchant or payee",
        max_len=MAX_MERCHANT_LENGTH,
    )
    payment_method = _parse_payment_method(payload.get("payment_method"))
    idempotency_key = _parse_idempotency_key(payload.get("idempotency_key"))

    signed_amount_minor = -amount_minor if entry_type == "expense" else amount_minor

    with db_session(db_path, immediate=True) as conn:
        if idempotency_key is not None:
            existing_rows = transactions_repo.get_transaction_rows_by_idempotency_key(
                conn, idempotency_key
            )
            if existing_rows:
                existing = existing_rows[0]
                existing_cat_id = (
                    int(existing["category_id"]) if existing["category_id"] is not None else None
                )
                matches = (
                    len(existing_rows) == 1
                    and existing["entry_type"] == entry_type
                    and int(existing["account_id"]) == account_id
                    and existing_cat_id == category_id
                    and int(existing["signed_amount_minor"]) == signed_amount_minor
                    and str(existing["tx_date"]) == tx_date
                    and str(existing["description"]) == description
                    and str(existing["merchant"] or "") == merchant
                    and str(existing["payment_method"] or "other") == payment_method
                )
                if not matches:
                    raise ConflictError(
                        "This submission key was already used for a different transaction."
                    )
                return group_and_serialize_transaction_rows(existing_rows)[0], False

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
            merchant=merchant,
            payment_method=payment_method,
            idempotency_key=idempotency_key,
            account_id=account_id,
            category_id=category_id,
            signed_amount_minor=signed_amount_minor,
            now=now,
        )
        created_rows = transactions_repo.get_transaction_rows_by_id(conn, tx_id)
        if not created_rows:  # pragma: no cover
            raise ValidationError("Failed to reload created transaction.")
        return group_and_serialize_transaction_rows(created_rows)[0], True


def create_transfer(
    db_path: Path | str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Atomically record a balanced transfer between accounts (including credit card repayments)."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    from_account_id = _parse_positive_int(
        payload.get("from_account_id"), field="from_account_id", label="Source account"
    )
    to_account_id = _parse_positive_int(
        payload.get("to_account_id"), field="to_account_id", label="Destination account"
    )
    if from_account_id == to_account_id:
        raise ValidationError(
            "Source and destination accounts must be different.",
            field="to_account_id",
        )

    amount_minor = parse_inr_to_minor(payload.get("amount"), field="amount")
    tx_date = validate_tx_date(payload.get("tx_date"), field="tx_date", allow_future=False)
    description = _parse_clean_text(
        payload.get("description"),
        field="description",
        label="Description",
        max_len=MAX_DESCRIPTION_LENGTH,
    )
    payment_method = _parse_payment_method(payload.get("payment_method"), default="bank_transfer")
    idempotency_key = _parse_idempotency_key(payload.get("idempotency_key"))

    with db_session(db_path, immediate=True) as conn:
        if idempotency_key is not None:
            existing_rows = transactions_repo.get_transaction_rows_by_idempotency_key(
                conn, idempotency_key
            )
            if existing_rows:
                serialized = group_and_serialize_transaction_rows(existing_rows)[0]
                matches = (
                    serialized["entry_type"] == "transfer"
                    and serialized.get("from_account_id") == from_account_id
                    and serialized.get("to_account_id") == to_account_id
                    and serialized["amount_minor"] == amount_minor
                    and serialized["tx_date"] == tx_date
                    and serialized["description"] == description
                )
                if not matches:
                    raise ConflictError(
                        "This submission key was already used for a different transfer."
                    )
                return serialized, False

        src_account = accounts_repo.get_account_by_id(conn, from_account_id)
        if src_account is None or int(src_account["is_archived"]) != 0:
            raise NotFoundError(
                "Source account was not found or is archived.", field="from_account_id"
            )

        dst_account = accounts_repo.get_account_by_id(conn, to_account_id)
        if dst_account is None or int(dst_account["is_archived"]) != 0:
            raise NotFoundError(
                "Destination account was not found or is archived.", field="to_account_id"
            )

        if str(src_account["account_type"]) == "credit_card":
            raise ValidationError(
                "Outbound transfers (cash advances) from credit cards are not supported in Phase 2. "
                "To repay a credit card, choose an asset account as Source and the card as Destination.",
                status_code=422,
                field="from_account_id",
            )

        now = utc_now_iso()
        tx_id = transactions_repo.create_multi_posting_transaction(
            conn,
            entry_type="transfer",
            tx_date=tx_date,
            description=description,
            merchant="",
            payment_method=payment_method,
            idempotency_key=idempotency_key,
            postings=[
                (from_account_id, None, -amount_minor),
                (to_account_id, None, amount_minor),
            ],
            now=now,
        )
        created_rows = transactions_repo.get_transaction_rows_by_id(conn, tx_id)
        if not created_rows:  # pragma: no cover
            raise ValidationError("Failed to reload created transfer.")
        return group_and_serialize_transaction_rows(created_rows)[0], True


def list_transactions(
    db_path: Path | str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated chronological active transactions and total count."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)
    with db_session(db_path) as conn:
        rows = transactions_repo.list_transactions(conn, limit=bounded_limit, offset=bounded_offset)
        total_count = transactions_repo.count_transactions(conn)
        return {
            "transactions": group_and_serialize_transaction_rows(rows),
            "total_count": total_count,
            "limit": bounded_limit,
            "offset": bounded_offset,
        }


def list_categories(db_path: Path | str, *, kind: str | None = None) -> list[dict[str, Any]]:
    """Return active categories optionally filtered by 'expense' or 'income'."""
    if kind is not None and kind not in ALLOWED_PHASE1_CREATE_TYPES:
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
                "is_system": bool(r["is_system"]),
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
