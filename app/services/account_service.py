"""Authoritative financial account and asset/liability position services."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import accounts_repo, transactions_repo
from app.services.transaction_service import hydrate_and_serialize_rows
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.money import format_inr_minor, parse_inr_to_minor, validate_aggregate_minor
from app.utils.time import local_today_iso, validate_tx_date

VALID_ACCOUNT_TYPES = ("cash", "bank", "savings", "wallet", "credit_card")
VALID_ACCOUNT_ICONS = (
    "wallet",
    "landmark",
    "piggy-bank",
    "credit-card",
    "coins",
    "building-2",
    "briefcase",
)
VALID_COLOR_TOKENS = (
    "cat-forest",
    "cat-slate",
    "cat-teal",
    "cat-indigo",
    "cat-amber",
    "cat-sage",
    "cat-stone",
)
DEFAULT_ICON_BY_TYPE = {
    "cash": "wallet",
    "bank": "landmark",
    "savings": "piggy-bank",
    "wallet": "coins",
    "credit_card": "credit-card",
}
DEFAULT_COLOR_BY_TYPE = {
    "cash": "cat-forest",
    "bank": "cat-slate",
    "savings": "cat-teal",
    "wallet": "cat-amber",
    "credit_card": "cat-indigo",
}
ACCOUNT_TYPE_LABELS = {
    "cash": "Cash",
    "bank": "Bank Account",
    "savings": "Savings Account",
    "wallet": "Digital Wallet",
    "credit_card": "Credit Card",
}


def _parse_account_name(raw_value: object) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValidationError("Account name is required.", field="name")
    cleaned = " ".join(raw_value.strip().split())
    if len(cleaned) > 60:
        raise ValidationError("Account name must be 60 characters or fewer.", field="name")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Account name contains invalid characters.", field="name")
    return cleaned


def _parse_account_description(raw_value: object) -> str:
    if raw_value is None:
        return ""
    if not isinstance(raw_value, str):
        raise ValidationError("Description must be plain text.", field="description")
    cleaned = " ".join(raw_value.strip().splitlines())
    if len(cleaned) > 240:
        raise ValidationError("Description must be 240 characters or fewer.", field="description")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationError("Description contains invalid characters.", field="description")
    return cleaned


def _parse_opening_balance_minor(
    payload: dict[str, Any],
    *,
    account_type: str,
) -> int:
    raw_val = payload.get("opening_balance", "0")
    if raw_val in ("", None):
        return 0
    minor = parse_inr_to_minor(raw_val, field="opening_balance", allow_zero=True)
    if account_type == "credit_card":
        direction = payload.get("opening_balance_direction", "debt")
        if direction not in ("debt", "credit"):
            raise ValidationError(
                "Credit card opening balance direction must be 'debt' or 'credit'.",
                field="opening_balance_direction",
            )
        return -minor if direction == "debt" and minor > 0 else minor
    return minor


def serialize_account_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert an account query row into an authoritative API dictionary."""
    acct_type = str(row["account_type"])
    balance_minor = validate_aggregate_minor(int(row["balance_minor"]), label="Account balance")
    opening_minor = int(row["opening_balance_minor"])
    credit_limit_minor = (
        int(row["credit_limit_minor"]) if row["credit_limit_minor"] is not None else None
    )

    is_credit_card = acct_type == "credit_card"
    outstanding_liability_minor = max(0, -balance_minor) if is_credit_card else 0
    credit_surplus_minor = max(0, balance_minor) if is_credit_card else 0
    available_credit_minor: int | None = None
    utilization_percent: float | None = None
    if is_credit_card and credit_limit_minor is not None:
        available_credit_minor = max(0, credit_limit_minor + balance_minor)
        if credit_limit_minor > 0:
            utilization_percent = round(
                min(999.9, (outstanding_liability_minor / credit_limit_minor) * 100.0), 1
            )
        else:
            utilization_percent = 0.0 if outstanding_liability_minor == 0 else 100.0

    display_balance_minor = outstanding_liability_minor if is_credit_card else balance_minor
    negative_warning = (not is_credit_card) and balance_minor < 0

    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "account_type": acct_type,
        "account_type_label": ACCOUNT_TYPE_LABELS.get(acct_type, acct_type.title()),
        "is_liability": is_credit_card,
        "currency": str(row["currency"]),
        "is_default": bool(row["is_default"]),
        "is_archived": bool(row["is_archived"]),
        "opening_balance_minor": opening_minor,
        "opening_balance_formatted": format_inr_minor(opening_minor),
        "opening_balance_date": str(row["opening_balance_date"] or row["created_at"][:10]),
        "description": str(row["description"] or ""),
        "icon": str(row["icon"] or DEFAULT_ICON_BY_TYPE.get(acct_type, "wallet")),
        "color_token": str(
            row["color_token"] or DEFAULT_COLOR_BY_TYPE.get(acct_type, "cat-forest")
        ),
        "balance_minor": balance_minor,
        "balance_formatted": format_inr_minor(balance_minor),
        "display_balance_minor": display_balance_minor,
        "display_balance_formatted": format_inr_minor(display_balance_minor),
        "outstanding_liability_minor": outstanding_liability_minor,
        "outstanding_liability_formatted": format_inr_minor(outstanding_liability_minor),
        "credit_balance_surplus_minor": credit_surplus_minor,
        "credit_balance_surplus_formatted": format_inr_minor(credit_surplus_minor),
        "credit_limit_minor": credit_limit_minor,
        "credit_limit_formatted": (
            format_inr_minor(credit_limit_minor) if credit_limit_minor is not None else None
        ),
        "available_credit_minor": available_credit_minor,
        "available_credit_formatted": (
            format_inr_minor(available_credit_minor) if available_credit_minor is not None else None
        ),
        "utilization_percent": utilization_percent,
        "negative_balance_warning": negative_warning,
        "active_transaction_count": int(row["active_transaction_count"]),
        "total_posting_count": int(row["total_posting_count"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def compute_financial_positions(rows: list[sqlite3.Row]) -> dict[str, Any]:
    """Compute authoritative asset, liability, credit surplus, and net worth totals."""
    total_assets_minor = 0
    total_liabilities_minor = 0
    total_credit_surplus_minor = 0

    for r in rows:
        bal = int(r["balance_minor"])
        if str(r["account_type"]) == "credit_card":
            if bal < 0:
                total_liabilities_minor += -bal
            elif bal > 0:
                total_credit_surplus_minor += bal
        else:
            total_assets_minor += bal

    net_worth_minor = total_assets_minor + total_credit_surplus_minor - total_liabilities_minor
    validate_aggregate_minor(total_assets_minor, label="Total assets")
    validate_aggregate_minor(total_liabilities_minor, label="Total liabilities")
    validate_aggregate_minor(net_worth_minor, label="Net financial position")

    return {
        "total_assets_minor": total_assets_minor,
        "total_assets_formatted": format_inr_minor(total_assets_minor),
        "total_liabilities_minor": total_liabilities_minor,
        "total_liabilities_formatted": format_inr_minor(total_liabilities_minor),
        "total_credit_surplus_minor": total_credit_surplus_minor,
        "total_credit_surplus_formatted": format_inr_minor(total_credit_surplus_minor),
        "net_worth_minor": net_worth_minor,
        "net_worth_formatted": format_inr_minor(net_worth_minor),
    }


def list_accounts(
    db_path: Path | str,
    *,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Return active (and optionally archived) accounts plus authoritative position summary."""
    with db_session(db_path) as conn:
        all_rows = accounts_repo.list_accounts_with_balances(conn, include_archived=True)
        positions = compute_financial_positions(all_rows)
        visible_rows = (
            all_rows if include_archived else [r for r in all_rows if int(r["is_archived"]) == 0]
        )
        return {
            "accounts": [serialize_account_row(r) for r in visible_rows],
            "summary": positions,
        }


def create_account(db_path: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a new financial account cleanly without counting opening balance as income."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    name = _parse_account_name(payload.get("name"))
    acct_type = payload.get("account_type")
    if not isinstance(acct_type, str) or acct_type not in VALID_ACCOUNT_TYPES:
        raise ValidationError(
            "Select a valid account type (cash, bank, savings, wallet, credit_card).",
            field="account_type",
        )

    opening_balance_minor = _parse_opening_balance_minor(payload, account_type=acct_type)
    raw_date = payload.get("opening_balance_date") or local_today_iso()
    opening_balance_date = validate_tx_date(
        raw_date, field="opening_balance_date", allow_future=False
    )
    description = _parse_account_description(payload.get("description"))

    icon = payload.get("icon") or DEFAULT_ICON_BY_TYPE[acct_type]
    if not isinstance(icon, str) or icon not in VALID_ACCOUNT_ICONS:
        raise ValidationError("Invalid account icon.", field="icon")

    color_token = payload.get("color_token") or DEFAULT_COLOR_BY_TYPE[acct_type]
    if not isinstance(color_token, str) or color_token not in VALID_COLOR_TOKENS:
        raise ValidationError("Invalid account color.", field="color_token")

    credit_limit_minor: int | None = None
    if acct_type == "credit_card":
        raw_limit = payload.get("credit_limit")
        if raw_limit not in (None, ""):
            credit_limit_minor = parse_inr_to_minor(
                raw_limit, field="credit_limit", allow_zero=True
            )
    elif payload.get("credit_limit") not in (None, ""):
        raise ValidationError(
            "Credit limit is only supported for credit card accounts.",
            field="credit_limit",
        )

    with db_session(db_path, immediate=True) as conn:
        dup = accounts_repo.get_active_account_by_name_ci(conn, name)
        if dup is not None:
            raise ConflictError(
                f"An active account named '{dup['name']}' already exists.",
                field="name",
            )
        from app.utils.time import utc_now_iso

        now = utc_now_iso()
        new_id = accounts_repo.create_account(
            conn,
            name=name,
            account_type=acct_type,
            opening_balance_minor=opening_balance_minor,
            opening_balance_date=opening_balance_date,
            description=description,
            icon=icon,
            color_token=color_token,
            credit_limit_minor=credit_limit_minor,
            currency="INR",
            now=now,
        )
        created = accounts_repo.get_account_by_id(conn, new_id)
        if created is None:  # pragma: no cover
            raise NotFoundError("Created account could not be loaded.")
        return serialize_account_row(created)


def update_account(
    db_path: Path | str,
    account_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Edit account metadata, opening balance, or credit limit while protecting history."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    with db_session(db_path, immediate=True) as conn:
        existing = accounts_repo.get_account_by_id(conn, account_id)
        if existing is None:
            raise NotFoundError("Account not found.", field="account_id")

        current_type = str(existing["account_type"])
        next_type = payload.get("account_type", current_type)
        if not isinstance(next_type, str) or next_type not in VALID_ACCOUNT_TYPES:
            raise ValidationError("Invalid account type.", field="account_type")
        if next_type != current_type and int(existing["total_posting_count"]) > 0:
            raise ConflictError(
                "Account type cannot be changed after transactions have been recorded.",
                field="account_type",
            )

        name = _parse_account_name(payload["name"]) if "name" in payload else str(existing["name"])
        dup = accounts_repo.get_active_account_by_name_ci(conn, name, exclude_account_id=account_id)
        if dup is not None and int(existing["is_archived"]) == 0:
            raise ConflictError(
                f"An active account named '{dup['name']}' already exists.",
                field="name",
            )

        description = (
            _parse_account_description(payload["description"])
            if "description" in payload
            else str(existing["description"] or "")
        )
        icon = str(payload.get("icon") or existing["icon"] or DEFAULT_ICON_BY_TYPE[next_type])
        if icon not in VALID_ACCOUNT_ICONS:
            raise ValidationError("Invalid account icon.", field="icon")

        color_token = str(
            payload.get("color_token")
            or existing["color_token"]
            or DEFAULT_COLOR_BY_TYPE[next_type]
        )
        if color_token not in VALID_COLOR_TOKENS:
            raise ValidationError("Invalid account color.", field="color_token")

        if "opening_balance" in payload or "opening_balance_direction" in payload:
            opening_balance_minor = _parse_opening_balance_minor(payload, account_type=next_type)
        else:
            opening_balance_minor = int(existing["opening_balance_minor"])

        if "opening_balance_date" in payload and payload["opening_balance_date"] not in (None, ""):
            opening_balance_date = validate_tx_date(
                payload["opening_balance_date"],
                field="opening_balance_date",
                allow_future=False,
            )
        else:
            opening_balance_date = str(
                existing["opening_balance_date"] or existing["created_at"][:10]
            )

        if next_type == "credit_card":
            if "credit_limit" in payload:
                raw_limit = payload["credit_limit"]
                credit_limit_minor = (
                    None
                    if raw_limit in (None, "")
                    else parse_inr_to_minor(raw_limit, field="credit_limit", allow_zero=True)
                )
            else:
                credit_limit_minor = (
                    int(existing["credit_limit_minor"])
                    if existing["credit_limit_minor"] is not None
                    else None
                )
        else:
            if payload.get("credit_limit") not in (None, ""):
                raise ValidationError(
                    "Credit limit is only supported for credit card accounts.",
                    field="credit_limit",
                )
            credit_limit_minor = None

        from app.utils.time import utc_now_iso

        accounts_repo.update_account(
            conn,
            account_id=account_id,
            name=name,
            account_type=next_type,
            opening_balance_minor=opening_balance_minor,
            opening_balance_date=opening_balance_date,
            description=description,
            icon=icon,
            color_token=color_token,
            credit_limit_minor=credit_limit_minor,
            now=utc_now_iso(),
        )
        updated = accounts_repo.get_account_by_id(conn, account_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Account not found.", field="account_id")
        return serialize_account_row(updated)


def archive_account(
    db_path: Path | str,
    account_id: int,
    *,
    confirm_nonzero: bool = False,
) -> dict[str, Any]:
    """Archive an account while preserving historical transactions and non-zero awareness."""
    with db_session(db_path, immediate=True) as conn:
        existing = accounts_repo.get_account_by_id(conn, account_id)
        if existing is None:
            raise NotFoundError("Account not found.", field="account_id")
        if int(existing["is_archived"]) == 1:
            return serialize_account_row(existing)

        if accounts_repo.count_active_accounts(conn) <= 1:
            raise ConflictError(
                "At least one active account must remain available.",
                code="last_active_account",
            )

        bal_minor = int(existing["balance_minor"])
        if bal_minor != 0 and not confirm_nonzero:
            raise ConflictError(
                f"Account '{existing['name']}' still has a balance of {format_inr_minor(bal_minor)}. "
                "Archiving hides it from new entries while keeping its balance in total net worth. "
                "Confirm archival or transfer the remaining balance first.",
                code="confirm_nonzero_archive",
            )

        from app.utils.time import utc_now_iso

        now = utc_now_iso()
        if int(existing["is_default"]) == 1:
            candidates = [
                r
                for r in accounts_repo.list_active_accounts_with_balances(conn)
                if int(r["id"]) != account_id
            ]
            if candidates:
                accounts_repo.reassign_default_account(conn, int(candidates[0]["id"]), now)

        accounts_repo.set_account_archived(conn, account_id=account_id, archived=True, now=now)
        updated = accounts_repo.get_account_by_id(conn, account_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Account not found.", field="account_id")
        return serialize_account_row(updated)


def restore_account(db_path: Path | str, account_id: int) -> dict[str, Any]:
    """Restore an archived account back to active selection."""
    with db_session(db_path, immediate=True) as conn:
        existing = accounts_repo.get_account_by_id(conn, account_id)
        if existing is None:
            raise NotFoundError("Account not found.", field="account_id")
        if int(existing["is_archived"]) == 0:
            return serialize_account_row(existing)

        dup = accounts_repo.get_active_account_by_name_ci(
            conn, str(existing["name"]), exclude_account_id=account_id
        )
        if dup is not None:
            raise ConflictError(
                f"Cannot restore because an active account named '{dup['name']}' already exists.",
                field="name",
            )

        from app.utils.time import utc_now_iso

        accounts_repo.set_account_archived(
            conn, account_id=account_id, archived=False, now=utc_now_iso()
        )
        updated = accounts_repo.get_account_by_id(conn, account_id)
        if updated is None:  # pragma: no cover
            raise NotFoundError("Account not found.", field="account_id")
        return serialize_account_row(updated)


def get_account_detail(db_path: Path | str, account_id: int, *, limit: int = 25) -> dict[str, Any]:
    """Return authoritative account details, activity totals, and recent transactions."""
    bounded_limit = max(1, min(limit, 100))
    with db_session(db_path) as conn:
        acct_row = accounts_repo.get_account_by_id(conn, account_id)
        if acct_row is None:
            raise NotFoundError("Account not found.", field="account_id")

        inc_minor, exp_minor, ref_minor, xfer_net_minor = accounts_repo.get_account_activity_totals(
            conn, account_id
        )
        recent_rows = transactions_repo.list_transactions_for_account(
            conn, account_id=account_id, limit=bounded_limit
        )
        recent_serialized = hydrate_and_serialize_rows(conn, recent_rows)
        return {
            "account": serialize_account_row(acct_row),
            "activity": {
                "income_minor": inc_minor,
                "income_formatted": format_inr_minor(inc_minor),
                "gross_expense_minor": exp_minor,
                "gross_expense_formatted": format_inr_minor(exp_minor),
                "refund_minor": ref_minor,
                "refund_formatted": format_inr_minor(ref_minor),
                "net_expense_minor": exp_minor - ref_minor,
                "net_expense_formatted": format_inr_minor(exp_minor - ref_minor),
                "net_transfer_minor": xfer_net_minor,
                "net_transfer_formatted": format_inr_minor(xfer_net_minor, show_plus=True),
            },
            "recent_transactions": recent_serialized,
        }
