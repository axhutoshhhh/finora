"""Transaction, transfer, split, refund, search, recovery, and bulk services."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import (
    accounts_repo,
    attachments_repo,
    categories_repo,
    tags_repo,
    transactions_repo,
)
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor
from app.utils.time import resolve_month_bounds, utc_now_iso, validate_tx_date

ALLOWED_ENTRY_TYPES = ("expense", "income", "transfer", "refund")
ALLOWED_CREATE_TYPES = ("expense", "income")
VALID_PAYMENT_METHODS = ("cash", "upi", "debit_card", "credit_card", "bank_transfer", "other")
VALID_SORT_KEYS = ("newest", "oldest", "amount_desc", "amount_asc", "merchant_asc")
VALID_DELETED_MODES = ("active", "deleted", "all")
MAX_DESCRIPTION_LENGTH = 240
MAX_MERCHANT_LENGTH = 120
MAX_IDEMPOTENCY_KEY_LENGTH = 64
MAX_SPLIT_ROWS = 20
MAX_BULK_IDS = 200
_STYLE_TRANSFER = "cat-slate"
_STYLE_SPLIT = "cat-stone"
_STYLE_REFUND = "cat-sage"


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


def group_and_serialize_transaction_rows(
    rows: list[sqlite3.Row],
    *,
    tags_map: dict[int, list[dict[str, object]]] | None = None,
    attachments_map: dict[int, list[dict[str, object]]] | None = None,
    refund_totals_map: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Group multi-posting SQL rows into authoritative logical transaction objects."""
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
        tags = (tags_map or {}).get(tx_id, [])
        attachments = (attachments_map or {}).get(tx_id, [])

        if entry_type == "transfer" and len(postings) == 2:
            src = postings[0] if postings[0]["signed_amount_minor"] < 0 else postings[1]
            dst = postings[1] if postings[0]["signed_amount_minor"] < 0 else postings[0]
            abs_minor = src["amount_minor"]
            is_repayment = dst["account_type"] == "credit_card"
            results.append(
                {
                    "id": tx_id,
                    "entry_type": "transfer",
                    "transfer_subtype": "credit_card_repayment" if is_repayment else "transfer",
                    "account_id": src["account_id"],
                    "account_name": f"{src['account_name']} → {dst['account_name']}",
                    "from_account_id": src["account_id"],
                    "from_account_name": src["account_name"],
                    "to_account_id": dst["account_id"],
                    "to_account_name": dst["account_name"],
                    "currency": src["currency"],
                    "category_id": None,
                    "category_name": "Card Repayment" if is_repayment else "Transfer",
                    "category_slug": "",
                    "category_icon": "arrow-left-right",
                    "category_color_token": _STYLE_TRANSFER,
                    "amount_minor": abs_minor,
                    "signed_amount_minor": abs_minor,
                    "amount_formatted": format_inr_minor(abs_minor),
                    "signed_amount_formatted": format_inr_minor(abs_minor),
                    "tx_date": str(head["tx_date"]),
                    "merchant": str(head["merchant"] or ""),
                    "payment_method": str(head["payment_method"] or "bank_transfer"),
                    "description": str(head["description"] or ""),
                    "related_transaction_id": None,
                    "refunded_minor": 0,
                    "refunded_formatted": "₹0.00",
                    "is_split": False,
                    "revision": int(head["revision"]),
                    "deleted_at": head["deleted_at"],
                    "postings": postings,
                    "tags": tags,
                    "attachments": attachments,
                    "created_at": str(head["created_at"]),
                    "updated_at": str(head["updated_at"]),
                }
            )
            continue

        total_signed = sum(p["signed_amount_minor"] for p in postings)
        abs_total = abs(total_signed)
        is_split = bool(head["is_split"]) or len(postings) > 1
        primary = postings[0]
        if is_split:
            cat_name = f"Split ({len(postings)} categories)"
            cat_icon = "split"
            cat_slug = ""
            cat_color = _STYLE_SPLIT
            cat_id = None
        elif entry_type == "refund" and not primary["category_name"]:
            cat_name = "Refund"
            cat_icon = "undo-2"
            cat_slug = ""
            cat_color = _STYLE_REFUND
            cat_id = primary["category_id"]
        else:
            cat_name = primary["category_name"] or "Uncategorized"
            cat_icon = primary["category_icon"]
            cat_slug = primary["category_slug"]
            cat_color = primary["category_color_token"]
            cat_id = primary["category_id"]

        refunded_minor = (refund_totals_map or {}).get(tx_id, 0)
        results.append(
            {
                "id": tx_id,
                "entry_type": entry_type,
                "account_id": primary["account_id"],
                "account_name": primary["account_name"],
                "currency": primary["currency"],
                "category_id": cat_id,
                "category_name": cat_name,
                "category_slug": cat_slug,
                "category_icon": cat_icon,
                "category_color_token": cat_color,
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
                "refunded_minor": refunded_minor,
                "refunded_formatted": format_inr_minor(refunded_minor),
                "is_split": is_split,
                "revision": int(head["revision"]),
                "deleted_at": head["deleted_at"],
                "postings": postings,
                "tags": tags,
                "attachments": attachments,
                "created_at": str(head["created_at"]),
                "updated_at": str(head["updated_at"]),
            }
        )
    return results


def hydrate_and_serialize_rows(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> list[dict[str, Any]]:
    """Load tags and attachment metadata in batch and serialize rows cleanly."""
    if not rows:
        return []
    tx_ids = list({int(r["id"]) for r in rows})
    tags_map = tags_repo.get_tags_for_transactions(conn, tx_ids)
    attachments_map = attachments_repo.get_attachments_for_transactions(conn, tx_ids)
    refund_totals = _get_active_refund_totals_by_parents(conn, tx_ids)
    return group_and_serialize_transaction_rows(
        rows,
        tags_map=tags_map,
        attachments_map=attachments_map,
        refund_totals_map=refund_totals,
    )


def _get_active_refund_totals_by_parents(
    conn: sqlite3.Connection, parent_ids: list[int]
) -> dict[int, int]:
    if not parent_ids:
        return {}
    rows = conn.execute(
        """
        SELECT t.related_transaction_id AS parent_id, COALESCE(SUM(p.signed_amount_minor), 0) AS refunded_minor
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        WHERE t.entry_type = 'refund'
          AND t.deleted_at IS NULL
          AND t.related_transaction_id IN (SELECT value FROM json_each(?))
        GROUP BY t.related_transaction_id;
        """,
        (json.dumps(parent_ids),),
    ).fetchall()
    return {int(r["parent_id"]): int(r["refunded_minor"]) for r in rows}


def serialize_transaction_row(row: sqlite3.Row) -> dict[str, Any]:
    """Serialize a single SQL row without extra queries."""
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
        raise ValidationError(f"{label} must be {max_len} characters or fewer.", field=field)
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError(f"{label} contains invalid control characters.", field=field)
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


def _parse_tag_ids(conn: sqlite3.Connection, raw_tag_ids: object) -> list[int]:
    if raw_tag_ids is None:
        return []
    if not isinstance(raw_tag_ids, list):
        raise ValidationError("Tags must be provided as a list of IDs.", field="tag_ids")
    seen: list[int] = []
    for item in raw_tag_ids:
        tid = _parse_positive_int(item, field="tag_ids", label="Tag")
        if tid not in seen:
            row = tags_repo.get_tag_by_id(conn, tid)
            if row is None:
                raise NotFoundError("Selected tag was not found.", field="tag_ids")
            seen.append(tid)
    return seen


def _validate_and_build_entry_postings(
    conn: sqlite3.Connection,
    *,
    entry_type: str,
    account_id: int,
    amount_minor: int,
    category_id_raw: object,
    splits_raw: object,
) -> tuple[bool, list[tuple[int, int | None, int]]]:
    """Validate category/splits rules and construct signed posting tuples."""
    account = accounts_repo.get_account_by_id(conn, account_id)
    if account is None or int(account["is_archived"]) != 0:
        raise NotFoundError("Selected account was not found or is archived.", field="account_id")

    sign = -1 if entry_type == "expense" else 1
    if splits_raw is not None:
        if not isinstance(splits_raw, list) or len(splits_raw) < 2:
            raise ValidationError(
                "A split transaction must have at least two category allocations.",
                field="splits",
            )
        if len(splits_raw) > MAX_SPLIT_ROWS:
            raise ValidationError(
                f"A split transaction supports at most {MAX_SPLIT_ROWS} rows.",
                field="splits",
            )
        postings: list[tuple[int, int | None, int]] = []
        split_sum = 0
        for idx, item in enumerate(splits_raw):
            if not isinstance(item, dict):
                raise ValidationError("Invalid split allocation row.", field="splits")
            cat_id = _parse_positive_int(
                item.get("category_id"), field="splits", label=f"Split row {idx + 1} category"
            )
            split_amt = parse_inr_to_minor(item.get("amount"), field="splits")
            category = categories_repo.get_category_by_id(conn, cat_id)
            if category is None or int(category["is_archived"]) != 0:
                raise NotFoundError(
                    "One of the split categories was not found or is archived.",
                    field="splits",
                )
            if str(category["kind"]) != entry_type:
                raise ValidationError(
                    f"Split category '{category['name']}' is not valid for {entry_type} entries.",
                    status_code=422,
                    field="splits",
                )
            split_sum += split_amt
            postings.append((account_id, cat_id, sign * split_amt))

        if split_sum != amount_minor:
            raise ValidationError(
                f"Split allocations ({format_inr_minor(split_sum)}) must equal total amount "
                f"({format_inr_minor(amount_minor)}).",
                field="splits",
            )
        return True, postings

    category_id = _parse_positive_int(category_id_raw, field="category_id", label="Category")
    category = categories_repo.get_category_by_id(conn, category_id)
    if category is None or int(category["is_archived"]) != 0:
        raise NotFoundError("Selected category was not found or is archived.", field="category_id")
    if str(category["kind"]) != entry_type:
        raise ValidationError(
            f"Selected category '{category['name']}' is not valid for {entry_type} entries.",
            status_code=422,
            field="category_id",
        )
    return False, [(account_id, category_id, sign * amount_minor)]


def create_transaction(
    db_path: Path | str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Create a single or split expense/income transaction atomically."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    entry_type = payload.get("entry_type")
    if not isinstance(entry_type, str) or entry_type not in ALLOWED_CREATE_TYPES:
        raise ValidationError(
            "Transaction type must be 'expense' or 'income'.",
            field="entry_type",
        )

    account_id = _parse_positive_int(payload.get("account_id"), field="account_id", label="Account")
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
    splits_raw = payload.get("splits")
    category_id_raw = payload.get("category_id")

    with db_session(db_path, immediate=True) as conn:
        if idempotency_key is not None:
            existing_rows = transactions_repo.get_transaction_rows_by_idempotency_key(
                conn, idempotency_key
            )
            if existing_rows:
                serialized = hydrate_and_serialize_rows(conn, existing_rows)[0]
                existing_postings = [
                    (p["account_id"], p["category_id"], p["signed_amount_minor"])
                    for p in serialized["postings"]
                ]
                sign = 1 if entry_type == "income" else -1
                if splits_raw is not None:
                    req_postings: list[tuple[int, int, int]] | None = None
                    if isinstance(splits_raw, list):
                        try:
                            req_postings = [
                                (
                                    account_id,
                                    _parse_positive_int(
                                        item.get("category_id"),
                                        field="splits.category_id",
                                        label="Split category",
                                    ),
                                    sign
                                    * parse_inr_to_minor(item.get("amount"), field="splits.amount"),
                                )
                                for item in splits_raw
                                if isinstance(item, dict)
                            ]
                            if len(req_postings) != len(splits_raw):
                                req_postings = None
                        except ValidationError:
                            req_postings = None
                else:
                    try:
                        cat_id = _parse_positive_int(
                            category_id_raw, field="category_id", label="Category"
                        )
                        req_postings = [(account_id, cat_id, sign * amount_minor)]
                    except ValidationError:
                        req_postings = None

                matches = (
                    serialized["entry_type"] == entry_type
                    and req_postings is not None
                    and existing_postings == req_postings
                    and serialized["tx_date"] == tx_date
                    and serialized["description"] == description
                    and serialized["merchant"] == merchant
                    and serialized["payment_method"] == payment_method
                )
                if not matches:
                    raise ConflictError(
                        "This submission key was already used for a different transaction."
                    )
                return serialized, False

        is_split, postings = _validate_and_build_entry_postings(
            conn,
            entry_type=entry_type,
            account_id=account_id,
            amount_minor=amount_minor,
            category_id_raw=category_id_raw,
            splits_raw=splits_raw,
        )
        tag_ids = _parse_tag_ids(conn, payload.get("tag_ids"))

        now = utc_now_iso()
        tx_id = transactions_repo.create_multi_posting_transaction(
            conn,
            entry_type=entry_type,
            tx_date=tx_date,
            description=description,
            merchant=merchant,
            payment_method=payment_method,
            is_split=is_split,
            idempotency_key=idempotency_key,
            postings=postings,
            now=now,
        )
        if tag_ids:
            tags_repo.set_transaction_tags(conn, transaction_id=tx_id, tag_ids=tag_ids, now=now)
        created_rows = transactions_repo.get_transaction_rows_by_id(conn, tx_id)
        if not created_rows:  # pragma: no cover
            raise ValidationError("Failed to reload created transaction.")
        return hydrate_and_serialize_rows(conn, created_rows)[0], True


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
            "Source and destination accounts must be different.", field="to_account_id"
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
                serialized = hydrate_and_serialize_rows(conn, existing_rows)[0]
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

        tag_ids = _parse_tag_ids(conn, payload.get("tag_ids"))
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
        if tag_ids:
            tags_repo.set_transaction_tags(conn, transaction_id=tx_id, tag_ids=tag_ids, now=now)
        created_rows = transactions_repo.get_transaction_rows_by_id(conn, tx_id)
        if not created_rows:  # pragma: no cover
            raise ValidationError("Failed to reload created transfer.")
        return hydrate_and_serialize_rows(conn, created_rows)[0], True


def _compute_refund_allowance_summary(
    conn: sqlite3.Connection,
    parent_rows: list[sqlite3.Row],
    *,
    exclude_refund_id: int | None = None,
) -> tuple[int, dict[int, int], list[dict[str, Any]]]:
    """Compute remaining refundable total and per-category remaining allowance for an expense."""
    parent_id = int(parent_rows[0]["id"])
    orig_by_cat: dict[int, int] = {}
    cat_meta: dict[int, sqlite3.Row] = {}
    orig_total = 0
    for r in parent_rows:
        amt = abs(int(r["signed_amount_minor"]))
        orig_total += amt
        if r["category_id"] is not None:
            cid = int(r["category_id"])
            orig_by_cat[cid] = orig_by_cat.get(cid, 0) + amt
            cat_meta[cid] = r

    refund_rows = transactions_repo.list_active_refund_rows_for_parent(
        conn, parent_id, exclude_refund_id=exclude_refund_id
    )
    refunded_total = 0
    refunded_by_cat: dict[int, int] = {}
    for r in refund_rows:
        amt = int(r["signed_amount_minor"])
        refunded_total += amt
        if r["category_id"] is not None:
            cid = int(r["category_id"])
            refunded_by_cat[cid] = refunded_by_cat.get(cid, 0) + amt

    remaining_total = max(0, orig_total - refunded_total)
    remaining_by_cat = {
        cid: max(0, orig_amt - refunded_by_cat.get(cid, 0)) for cid, orig_amt in orig_by_cat.items()
    }
    allocation_details = [
        {
            "category_id": cid,
            "category_name": str(cat_meta[cid]["category_name"] or ""),
            "original_minor": orig_by_cat[cid],
            "refunded_minor": refunded_by_cat.get(cid, 0),
            "remaining_minor": remaining_by_cat[cid],
            "remaining_formatted": format_inr_minor(remaining_by_cat[cid]),
        }
        for cid in orig_by_cat
    ]
    return remaining_total, remaining_by_cat, allocation_details


def _validate_and_build_refund_postings(
    conn: sqlite3.Connection,
    *,
    parent_rows: list[sqlite3.Row],
    account_id: int,
    amount_minor: int,
    refund_tx_date: str,
    allocations_raw: object,
    exclude_refund_id: int | None = None,
) -> tuple[bool, list[tuple[int, int | None, int]]]:
    head = parent_rows[0]
    if str(head["entry_type"]) != "expense":
        raise ValidationError(
            "Only expense transactions can receive refunds.", field="related_transaction_id"
        )
    if head["deleted_at"] is not None:
        raise ConflictError("Cannot refund a deleted expense transaction.")
    if refund_tx_date < str(head["tx_date"]):
        raise ValidationError(
            "Refund date cannot be earlier than the original expense date.",
            field="tx_date",
        )

    account = accounts_repo.get_account_by_id(conn, account_id)
    if account is None or int(account["is_archived"]) != 0:
        raise NotFoundError(
            "Refund destination account was not found or is archived.", field="account_id"
        )

    remaining_total, remaining_by_cat, _ = _compute_refund_allowance_summary(
        conn, parent_rows, exclude_refund_id=exclude_refund_id
    )
    if amount_minor > remaining_total:
        raise ValidationError(
            f"Refund amount exceeds remaining refundable limit ({format_inr_minor(remaining_total)}).",
            status_code=422,
            field="amount",
        )

    orig_is_split = bool(head["is_split"]) or len(parent_rows) > 1
    if not orig_is_split and allocations_raw is None:
        orig_cat_id = int(head["category_id"]) if head["category_id"] is not None else None
        return False, [(account_id, orig_cat_id, amount_minor)]

    if not isinstance(allocations_raw, list) or not allocations_raw:
        if len(remaining_by_cat) == 1:
            only_cat = next(iter(remaining_by_cat))
            return False, [(account_id, only_cat, amount_minor)]
        raise ValidationError(
            "Specify category allocations when refunding a split expense.",
            field="allocations",
        )

    postings: list[tuple[int, int | None, int]] = []
    alloc_sum = 0
    per_cat_new: dict[int, int] = {}
    for idx, item in enumerate(allocations_raw):
        if not isinstance(item, dict):
            raise ValidationError("Invalid refund category allocation.", field="allocations")
        cid = _parse_positive_int(
            item.get("category_id"), field="allocations", label=f"Refund allocation {idx + 1}"
        )
        amt = parse_inr_to_minor(item.get("amount"), field="allocations")
        if cid not in remaining_by_cat:
            raise ValidationError(
                "Refund category must match one of the original expense's categories.",
                status_code=422,
                field="allocations",
            )
        per_cat_new[cid] = per_cat_new.get(cid, 0) + amt
        if per_cat_new[cid] > remaining_by_cat[cid]:
            raise ValidationError(
                f"Category refund exceeds remaining eligible amount ({format_inr_minor(remaining_by_cat[cid])}).",
                status_code=422,
                field="allocations",
            )
        alloc_sum += amt
        postings.append((account_id, cid, amt))

    if alloc_sum != amount_minor:
        raise ValidationError(
            "Refund category allocations must equal the total refund amount.",
            field="allocations",
        )
    return len(postings) > 1, postings


def create_refund(
    db_path: Path | str,
    parent_transaction_id: int,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Create a linked refund against an existing active expense inside an immediate lock."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

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

    with db_session(db_path, immediate=True) as conn:
        parent_rows = transactions_repo.get_transaction_rows_by_id(conn, parent_transaction_id)
        if not parent_rows:
            raise NotFoundError("Original expense transaction not found.", field="transaction_id")

        default_account_id = int(parent_rows[0]["account_id"])
        raw_acct = payload.get("account_id", default_account_id)
        account_id = _parse_positive_int(raw_acct, field="account_id", label="Account")

        if idempotency_key is not None:
            existing_rows = transactions_repo.get_transaction_rows_by_idempotency_key(
                conn, idempotency_key
            )
            if existing_rows:
                serialized = hydrate_and_serialize_rows(conn, existing_rows)[0]
                if (
                    serialized["entry_type"] != "refund"
                    or serialized["related_transaction_id"] != parent_transaction_id
                    or serialized["amount_minor"] != amount_minor
                ):
                    raise ConflictError(
                        "This submission key was already used for a different refund."
                    )
                return serialized, False

        is_split, postings = _validate_and_build_refund_postings(
            conn,
            parent_rows=parent_rows,
            account_id=account_id,
            amount_minor=amount_minor,
            refund_tx_date=tx_date,
            allocations_raw=payload.get("allocations"),
        )
        tag_ids = _parse_tag_ids(conn, payload.get("tag_ids"))
        now = utc_now_iso()
        tx_id = transactions_repo.create_multi_posting_transaction(
            conn,
            entry_type="refund",
            tx_date=tx_date,
            description=description,
            merchant=merchant or str(parent_rows[0]["merchant"] or ""),
            payment_method=payment_method,
            related_transaction_id=parent_transaction_id,
            is_split=is_split,
            idempotency_key=idempotency_key,
            postings=postings,
            now=now,
        )
        if tag_ids:
            tags_repo.set_transaction_tags(conn, transaction_id=tx_id, tag_ids=tag_ids, now=now)
        created_rows = transactions_repo.get_transaction_rows_by_id(conn, tx_id)
        return hydrate_and_serialize_rows(conn, created_rows)[0], True


def list_refunds_for_transaction(db_path: Path | str, parent_transaction_id: int) -> dict[str, Any]:
    """Return linked active refunds and remaining refundable balance/allocations."""
    with db_session(db_path) as conn:
        parent_rows = transactions_repo.get_transaction_rows_by_id(conn, parent_transaction_id)
        if not parent_rows:
            raise NotFoundError("Transaction not found.")
        parent_tx = hydrate_and_serialize_rows(conn, parent_rows)[0]
        remaining_total, _, allocations = _compute_refund_allowance_summary(conn, parent_rows)
        refund_rows = transactions_repo.list_active_refund_rows_for_parent(
            conn, parent_transaction_id
        )
        refunds = hydrate_and_serialize_rows(conn, refund_rows)
        refunded_total = sum(r["amount_minor"] for r in refunds)
        return {
            "original_transaction": parent_tx,
            "total_refunded_minor": refunded_total,
            "total_refunded_formatted": format_inr_minor(refunded_total),
            "remaining_refundable_minor": remaining_total,
            "remaining_refundable_formatted": format_inr_minor(remaining_total),
            "allocations": allocations,
            "refunds": refunds,
        }


def get_transaction_detail(db_path: Path | str, transaction_id: int) -> dict[str, Any]:
    """Fetch full serialized details for a single transaction."""
    with db_session(db_path) as conn:
        rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        if not rows:
            raise NotFoundError("Transaction not found.")
        return hydrate_and_serialize_rows(conn, rows)[0]


def update_transaction(
    db_path: Path | str,
    transaction_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Atomically edit an active expense, income, transfer, or refund with revision guard."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    with db_session(db_path, immediate=True) as conn:
        existing_rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        if not existing_rows:
            raise NotFoundError("Transaction not found.")
        head = existing_rows[0]
        if head["deleted_at"] is not None:
            raise ConflictError("Deleted transactions must be restored before editing.")

        expected_rev = payload.get("expected_revision")
        current_rev = int(head["revision"])
        if expected_rev is not None:
            if isinstance(expected_rev, bool) or not isinstance(expected_rev, int):
                raise ValidationError("Invalid expected revision.", field="expected_revision")
            if expected_rev != current_rev:
                raise ConflictError(
                    "This transaction was updated elsewhere. Reload and review before saving.",
                    code="revision_conflict",
                )

        existing_tx = hydrate_and_serialize_rows(conn, existing_rows)[0]
        entry_type = existing_tx["entry_type"]
        if "entry_type" in payload and payload["entry_type"] != entry_type:
            raise ValidationError(
                "Changing an existing entry's fundamental transaction type is not allowed.",
                field="entry_type",
            )

        tx_date = (
            validate_tx_date(payload["tx_date"], field="tx_date", allow_future=False)
            if "tx_date" in payload
            else existing_tx["tx_date"]
        )
        description = (
            _parse_clean_text(
                payload["description"],
                field="description",
                label="Description",
                max_len=MAX_DESCRIPTION_LENGTH,
            )
            if "description" in payload
            else existing_tx["description"]
        )
        merchant = (
            _parse_clean_text(
                payload["merchant"],
                field="merchant",
                label="Merchant or payee",
                max_len=MAX_MERCHANT_LENGTH,
            )
            if "merchant" in payload
            else existing_tx["merchant"]
        )
        payment_method = (
            _parse_payment_method(payload["payment_method"])
            if "payment_method" in payload
            else existing_tx["payment_method"]
        )

        now = utc_now_iso()
        tag_ids = _parse_tag_ids(conn, payload["tag_ids"]) if "tag_ids" in payload else None

        if entry_type == "transfer":
            from_id = (
                _parse_positive_int(
                    payload["from_account_id"], field="from_account_id", label="Source account"
                )
                if "from_account_id" in payload
                else int(existing_tx["from_account_id"])
            )
            to_id = (
                _parse_positive_int(
                    payload["to_account_id"], field="to_account_id", label="Destination account"
                )
                if "to_account_id" in payload
                else int(existing_tx["to_account_id"])
            )
            if from_id == to_id:
                raise ValidationError(
                    "Source and destination accounts must be different.", field="to_account_id"
                )
            amt_minor = (
                parse_inr_to_minor(payload["amount"], field="amount")
                if "amount" in payload
                else int(existing_tx["amount_minor"])
            )
            src = accounts_repo.get_account_by_id(conn, from_id)
            if src is None or int(src["is_archived"]) != 0:
                raise NotFoundError(
                    "Source account was not found or is archived.", field="from_account_id"
                )
            dst = accounts_repo.get_account_by_id(conn, to_id)
            if dst is None or int(dst["is_archived"]) != 0:
                raise NotFoundError(
                    "Destination account was not found or is archived.", field="to_account_id"
                )
            if str(src["account_type"]) == "credit_card":
                raise ValidationError(
                    "Credit cards cannot be the source of a transfer.",
                    status_code=422,
                    field="from_account_id",
                )
            is_split = False
            postings = [(from_id, None, -amt_minor), (to_id, None, amt_minor)]
        elif entry_type == "refund":
            parent_id = int(head["related_transaction_id"])
            parent_rows = transactions_repo.get_transaction_rows_by_id(conn, parent_id)
            if not parent_rows:
                raise NotFoundError("Original expense transaction not found.")
            amt_minor = (
                parse_inr_to_minor(payload["amount"], field="amount")
                if "amount" in payload
                else int(existing_tx["amount_minor"])
            )
            acct_id = (
                _parse_positive_int(payload["account_id"], field="account_id", label="Account")
                if "account_id" in payload
                else int(existing_tx["account_id"])
            )
            allocs = payload.get("allocations")
            if allocs is None and "amount" not in payload:
                allocs = [
                    {
                        "category_id": p["category_id"],
                        "amount": f"{p['amount_minor'] // 100}.{p['amount_minor'] % 100:02d}",
                    }
                    for p in existing_tx["postings"]
                ]
            is_split, postings = _validate_and_build_refund_postings(
                conn,
                parent_rows=parent_rows,
                account_id=acct_id,
                amount_minor=amt_minor,
                refund_tx_date=tx_date,
                allocations_raw=allocs,
                exclude_refund_id=transaction_id,
            )
        else:
            amt_minor = (
                parse_inr_to_minor(payload["amount"], field="amount")
                if "amount" in payload
                else int(existing_tx["amount_minor"])
            )
            acct_id = (
                _parse_positive_int(payload["account_id"], field="account_id", label="Account")
                if "account_id" in payload
                else int(existing_tx["account_id"])
            )
            if "splits" in payload:
                splits_raw = payload["splits"]
                cat_raw = payload.get("category_id")
            elif "category_id" in payload:
                splits_raw = None
                cat_raw = payload["category_id"]
            elif existing_tx["is_split"]:
                splits_raw = [
                    {
                        "category_id": p["category_id"],
                        "amount": f"{p['amount_minor'] // 100}.{p['amount_minor'] % 100:02d}",
                    }
                    for p in existing_tx["postings"]
                ]
                cat_raw = None
            else:
                splits_raw = None
                cat_raw = existing_tx["category_id"]

            is_split, postings = _validate_and_build_entry_postings(
                conn,
                entry_type=entry_type,
                account_id=acct_id,
                amount_minor=amt_minor,
                category_id_raw=cat_raw,
                splits_raw=splits_raw,
            )

            if entry_type == "expense":
                refund_rows = transactions_repo.list_active_refund_rows_for_parent(
                    conn, transaction_id
                )
                if refund_rows:
                    refunded_total = sum(int(r["signed_amount_minor"]) for r in refund_rows)
                    if amt_minor < refunded_total:
                        raise ConflictError(
                            f"Edited expense ({format_inr_minor(amt_minor)}) cannot be less than "
                            f"existing active refunds ({format_inr_minor(refunded_total)}).",
                            field="amount",
                        )
                    new_by_cat: dict[int, int] = {}
                    for _, cid, signed in postings:
                        if cid is not None:
                            new_by_cat[cid] = new_by_cat.get(cid, 0) + abs(signed)
                    refunded_by_cat: dict[int, int] = {}
                    for r in refund_rows:
                        if r["category_id"] is not None:
                            cid = int(r["category_id"])
                            refunded_by_cat[cid] = refunded_by_cat.get(cid, 0) + int(
                                r["signed_amount_minor"]
                            )
                    for cid, ref_amt in refunded_by_cat.items():
                        if new_by_cat.get(cid, 0) < ref_amt:
                            raise ConflictError(
                                "Edited category allocation cannot drop below already refunded amounts.",
                                field="splits" if is_split else "category_id",
                            )
                    earliest_refund_date = min(str(r["tx_date"]) for r in refund_rows)
                    if tx_date > earliest_refund_date:
                        raise ConflictError(
                            f"Expense date cannot be moved after its linked refund date ({earliest_refund_date}).",
                            field="tx_date",
                        )

        transactions_repo.replace_transaction_header_and_postings(
            conn,
            transaction_id=transaction_id,
            entry_type=entry_type,
            tx_date=tx_date,
            description=description,
            merchant=merchant,
            payment_method=payment_method,
            is_split=is_split,
            postings=postings,
            now=now,
        )
        if tag_ids is not None:
            tags_repo.set_transaction_tags(
                conn, transaction_id=transaction_id, tag_ids=tag_ids, now=now
            )
        updated_rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        return hydrate_and_serialize_rows(conn, updated_rows)[0]


def soft_delete_transaction(db_path: Path | str, transaction_id: int) -> dict[str, Any]:
    """Soft-delete an active transaction cleanly (blocking deletion while active refunds exist)."""
    with db_session(db_path, immediate=True) as conn:
        rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        if not rows:
            raise NotFoundError("Transaction not found.")
        head = rows[0]
        if head["deleted_at"] is not None:
            raise ConflictError("Transaction is already deleted.")
        if transactions_repo.count_active_refunds_for_parent(conn, transaction_id) > 0:
            raise ConflictError(
                "Cannot delete an expense that still has active linked refunds. "
                "Delete the refund entries first."
            )
        transactions_repo.soft_delete_transaction(
            conn, transaction_id=transaction_id, now=utc_now_iso()
        )
        updated = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        return hydrate_and_serialize_rows(conn, updated)[0]


def restore_transaction(db_path: Path | str, transaction_id: int) -> dict[str, Any]:
    """Restore a soft-deleted transaction back into active totals after invariant checks."""
    with db_session(db_path, immediate=True) as conn:
        rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        if not rows:
            raise NotFoundError("Transaction not found.")
        head = rows[0]
        if head["deleted_at"] is None:
            raise ConflictError("Transaction is already active.")

        if str(head["entry_type"]) == "refund" and head["related_transaction_id"] is not None:
            parent_id = int(head["related_transaction_id"])
            parent_rows = transactions_repo.get_transaction_rows_by_id(conn, parent_id)
            if not parent_rows or parent_rows[0]["deleted_at"] is not None:
                raise ConflictError("Restore the original expense before restoring this refund.")
            remaining_total, remaining_by_cat, _ = _compute_refund_allowance_summary(
                conn, parent_rows
            )
            refund_amt = sum(int(r["signed_amount_minor"]) for r in rows)
            if refund_amt > remaining_total:
                raise ConflictError(
                    "Restoring this refund would exceed the original expense's refundable amount."
                )
            for r in rows:
                cid = int(r["category_id"]) if r["category_id"] is not None else None
                if cid is not None and int(r["signed_amount_minor"]) > remaining_by_cat.get(cid, 0):
                    raise ConflictError(
                        "Restoring this refund would exceed remaining category refundable allowance."
                    )

        transactions_repo.restore_transaction(
            conn, transaction_id=transaction_id, now=utc_now_iso()
        )
        updated = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        return hydrate_and_serialize_rows(conn, updated)[0]


def purge_transaction(db_path: Path | str, transaction_id: int) -> dict[str, Any]:
    """Permanently delete an already soft-deleted transaction and unlink its files."""
    files_to_remove: list[Path] = []
    with db_session(db_path, immediate=True) as conn:
        rows = transactions_repo.get_transaction_rows_by_id(conn, transaction_id)
        if not rows:
            raise NotFoundError("Transaction not found.")
        head = rows[0]
        if head["deleted_at"] is None:
            raise ConflictError("Move the transaction to Trash before permanently deleting it.")
        has_refunds = (
            conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE related_transaction_id = ?;",
                (transaction_id,),
            ).fetchone()[0]
            > 0
        )
        if has_refunds:
            raise ConflictError(
                "Cannot permanently delete an expense while linked refunds exist (even in Trash)."
            )
        att_rows = attachments_repo.list_attachments_for_transaction(conn, transaction_id)
        data_dir = Path(db_path).parent
        files_to_remove = [data_dir / "attachments" / str(r["stored_filename"]) for r in att_rows]
        transactions_repo.purge_transaction(conn, transaction_id=transaction_id)

    for path in files_to_remove:
        path.unlink(missing_ok=True)
    return {"deleted_permanently": True, "id": transaction_id}


def bulk_action(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and apply an atomic bulk action across selected transaction IDs."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    action = payload.get("action")
    if action not in {"set_category", "add_tag", "delete", "restore"}:
        raise ValidationError(
            "Bulk action must be 'set_category', 'add_tag', 'delete', or 'restore'.",
            field="action",
        )

    raw_ids = payload.get("transaction_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValidationError("Select at least one transaction.", field="transaction_ids")
    if len(raw_ids) > MAX_BULK_IDS:
        raise ValidationError(
            f"Bulk operations support at most {MAX_BULK_IDS} transactions at a time.",
            field="transaction_ids",
        )
    tx_ids: list[int] = []
    for item in raw_ids:
        tid = _parse_positive_int(item, field="transaction_ids", label="Transaction")
        if tid not in tx_ids:
            tx_ids.append(tid)

    with db_session(db_path, immediate=True) as conn:
        now = utc_now_iso()
        grouped_rows: dict[int, list[sqlite3.Row]] = {}
        for tid in tx_ids:
            rows = transactions_repo.get_transaction_rows_by_id(conn, tid)
            if not rows:
                raise NotFoundError(f"Transaction #{tid} was not found.", field="transaction_ids")
            grouped_rows[tid] = rows

        if action == "set_category":
            cat_id = _parse_positive_int(
                payload.get("category_id"), field="category_id", label="Category"
            )
            cat = categories_repo.get_category_by_id(conn, cat_id)
            if cat is None or int(cat["is_archived"]) != 0:
                raise NotFoundError(
                    "Selected category was not found or is archived.", field="category_id"
                )
            cat_kind = str(cat["kind"])
            for tid in tx_ids:
                head = grouped_rows[tid][0]
                if head["deleted_at"] is not None:
                    raise ConflictError(
                        f"Transaction #{tid} is deleted; bulk category update aborted with no changes."
                    )
                etype = str(head["entry_type"])
                if etype in {"transfer", "refund"} or int(head["is_split"]) == 1:
                    raise ValidationError(
                        f"Transaction #{tid} ({etype if not int(head['is_split']) else 'split'}) "
                        "cannot receive a single bulk category. Deselect incompatible items.",
                        status_code=422,
                    )
                if etype != cat_kind:
                    raise ValidationError(
                        f"Category '{cat['name']}' ({cat_kind}) does not match {etype} transaction #{tid}.",
                        status_code=422,
                    )
            transactions_repo.update_single_posting_category_bulk(
                conn, transaction_ids=tx_ids, category_id=cat_id, now=now
            )
        elif action == "add_tag":
            tag_id = _parse_positive_int(payload.get("tag_id"), field="tag_id", label="Tag")
            tag = tags_repo.get_tag_by_id(conn, tag_id)
            if tag is None:
                raise NotFoundError("Selected tag was not found.", field="tag_id")
            for tid in tx_ids:
                if grouped_rows[tid][0]["deleted_at"] is not None:
                    raise ConflictError(
                        f"Transaction #{tid} is deleted and cannot be tagged in an active batch."
                    )
            for tid in tx_ids:
                tags_repo.attach_tag_to_transaction(
                    conn, transaction_id=tid, tag_id=tag_id, now=now
                )
        elif action == "delete":
            tx_id_set = set(tx_ids)
            for tid in tx_ids:
                head = grouped_rows[tid][0]
                if head["deleted_at"] is not None:
                    raise ConflictError(f"Transaction #{tid} is already deleted.")
                active_refunds = transactions_repo.list_active_refund_rows_for_parent(conn, tid)
                unresolved = {int(r["id"]) for r in active_refunds} - tx_id_set
                if unresolved:
                    raise ConflictError(
                        f"Transaction #{tid} has active linked refund(s) not included in selection."
                    )
            for tid in tx_ids:
                transactions_repo.soft_delete_transaction(conn, transaction_id=tid, now=now)
        elif action == "restore":
            for tid in tx_ids:
                if grouped_rows[tid][0]["deleted_at"] is None:
                    raise ConflictError(f"Transaction #{tid} is already active.")
            # Restore expenses/transfers/income before linked refunds in the same batch
            ordered = sorted(
                tx_ids,
                key=lambda t: 1 if str(grouped_rows[t][0]["entry_type"]) == "refund" else 0,
            )
            for tid in ordered:
                head = grouped_rows[tid][0]
                if (
                    str(head["entry_type"]) == "refund"
                    and head["related_transaction_id"] is not None
                ):
                    parent_id = int(head["related_transaction_id"])
                    parent_rows = transactions_repo.get_transaction_rows_by_id(conn, parent_id)
                    if not parent_rows or parent_rows[0]["deleted_at"] is not None:
                        raise ConflictError(
                            f"Refund #{tid} requires its original expense to be active first."
                        )
                    remaining_total, remaining_by_cat, _ = _compute_refund_allowance_summary(
                        conn, parent_rows
                    )
                    refund_amt = sum(int(r["signed_amount_minor"]) for r in grouped_rows[tid])
                    if refund_amt > remaining_total:
                        raise ConflictError(
                            f"Restoring refund #{tid} would exceed its original expense amount."
                        )
                    for r in grouped_rows[tid]:
                        cid = int(r["category_id"]) if r["category_id"] is not None else None
                        if cid is not None and int(r["signed_amount_minor"]) > remaining_by_cat.get(
                            cid, 0
                        ):
                            raise ConflictError(
                                f"Restoring refund #{tid} would exceed category refundable limit."
                            )
                transactions_repo.restore_transaction(conn, transaction_id=tid, now=now)

        return {"action": action, "affected_count": len(tx_ids), "transaction_ids": tx_ids}


def _parse_optional_positive_int_query(raw: str | None, *, field: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        val = int(raw.strip())
    except ValueError as exc:
        raise ValidationError(f"Invalid {field} filter.", field=field) from exc
    if val <= 0:
        raise ValidationError(f"Invalid {field} filter.", field=field)
    return val


def list_transactions(
    db_path: Path | str,
    *,
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    month: str | None = None,
    account_id: str | int | None = None,
    category_id: str | int | None = None,
    entry_type: str | None = None,
    payment_method: str | None = None,
    tag_id: str | int | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    deleted: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    """Return filtered, sorted, paginated transactions with hydrated tags and attachments."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)

    parsed_date_from = (
        validate_tx_date(date_from, field="date_from", allow_future=True)
        if date_from and date_from.strip()
        else None
    )
    parsed_date_to = (
        validate_tx_date(date_to, field="date_to", allow_future=True)
        if date_to and date_to.strip()
        else None
    )
    if month and month.strip():
        _, _, month_start, month_end_excl = resolve_month_bounds(month)
        parsed_date_from = parsed_date_from or month_start
        if parsed_date_to is None:
            from datetime import date, timedelta

            parsed_date_to = (date.fromisoformat(month_end_excl) - timedelta(days=1)).isoformat()

    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        raise ValidationError("Start date cannot be after end date.", field="date_from")

    parsed_acct = (
        account_id
        if isinstance(account_id, int)
        else _parse_optional_positive_int_query(account_id, field="account_id")
    )
    parsed_cat = (
        category_id
        if isinstance(category_id, int)
        else _parse_optional_positive_int_query(category_id, field="category_id")
    )
    parsed_tag = (
        tag_id
        if isinstance(tag_id, int)
        else _parse_optional_positive_int_query(tag_id, field="tag_id")
    )

    clean_type = entry_type.strip() if isinstance(entry_type, str) and entry_type.strip() else None
    if clean_type is not None and clean_type not in ALLOWED_ENTRY_TYPES:
        raise ValidationError("Invalid transaction type filter.", field="entry_type")

    clean_pm = (
        payment_method.strip()
        if isinstance(payment_method, str) and payment_method.strip()
        else None
    )
    if clean_pm is not None and clean_pm not in VALID_PAYMENT_METHODS:
        raise ValidationError("Invalid payment method filter.", field="payment_method")

    min_minor = (
        parse_inr_to_minor(min_amount, field="min_amount", allow_zero=True)
        if min_amount is not None and min_amount.strip() != ""
        else None
    )
    max_minor = (
        parse_inr_to_minor(max_amount, field="max_amount", allow_zero=True)
        if max_amount is not None and max_amount.strip() != ""
        else None
    )
    if min_minor is not None and max_minor is not None and min_minor > max_minor:
        raise ValidationError("Minimum amount cannot exceed maximum amount.", field="min_amount")

    deleted_mode = deleted.strip() if isinstance(deleted, str) and deleted.strip() else "active"
    if deleted_mode not in VALID_DELETED_MODES:
        raise ValidationError("Invalid deleted view filter.", field="deleted")

    sort_key = sort.strip() if isinstance(sort, str) and sort.strip() else "newest"
    if sort_key not in VALID_SORT_KEYS:
        raise ValidationError("Invalid sort order.", field="sort")

    clean_query = query.strip() if isinstance(query, str) and query.strip() else None
    if clean_query and len(clean_query) > 120:
        clean_query = clean_query[:120]

    flt = transactions_repo.TransactionFilter(
        query=clean_query,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        account_id=parsed_acct,
        category_id=parsed_cat,
        entry_type=clean_type,
        payment_method=clean_pm,
        tag_id=parsed_tag,
        min_amount_minor=min_minor,
        max_amount_minor=max_minor,
        deleted_mode=deleted_mode,
        sort=sort_key,
    )

    with db_session(db_path) as conn:
        rows, total_count = transactions_repo.search_transactions(
            conn, flt=flt, limit=bounded_limit, offset=bounded_offset
        )
        return {
            "transactions": hydrate_and_serialize_rows(conn, rows),
            "total_count": total_count,
            "limit": bounded_limit,
            "offset": bounded_offset,
        }


def list_categories(db_path: Path | str, *, kind: str | None = None) -> list[dict[str, Any]]:
    """Return active categories optionally filtered by 'expense' or 'income'."""
    if kind is not None and kind not in ALLOWED_CREATE_TYPES:
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
