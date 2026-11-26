"""Secured JSON API routes for Phase 1 Finora functionality."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, jsonify, request

from app.config import MAX_CONTENT_LENGTH_BYTES
from app.services import (
    account_service,
    overview_service,
    settings_service,
    transaction_service,
)
from app.utils.errors import ValidationError

api_bp = Blueprint("api", __name__, url_prefix="/api")

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ATTACHMENT_UPLOAD_ENDPOINT = "api.upload_transaction_attachment"


def _reject(code: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


@api_bp.before_request
def _enforce_api_security() -> tuple[Response, int] | None:
    sec_fetch_site = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site is not None and sec_fetch_site.strip().lower() not in {"same-origin", "none"}:
        return _reject("cross_site_blocked", "Cross-site requests are prohibited.", 403)

    allowed_origins: frozenset[str] = current_app.config["FINORA_ALLOWED_ORIGINS"]
    origin = request.headers.get("Origin")
    if origin is not None and origin.strip().lower() not in allowed_origins:
        return _reject("invalid_origin", "Request origin is not permitted.", 403)

    if request.method in _MUTATING_METHODS and origin is None:
        referer = request.headers.get("Referer")
        if referer is not None:
            parsed = urlparse(referer.strip())
            ref_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            if ref_origin not in allowed_origins:
                return _reject("invalid_origin", "Request referer is not permitted.", 403)

    expected_token: str = current_app.config["FINORA_API_TOKEN"]
    provided_token = request.headers.get("X-Finora-Token", "")
    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        return _reject("unauthorized", "Valid launch authorization token required.", 401)

    if request.endpoint != _ATTACHMENT_UPLOAD_ENDPOINT:
        content_len = request.content_length or 0
        if content_len > MAX_CONTENT_LENGTH_BYTES:
            return _reject(
                "payload_too_large",
                "Request body exceeds the 64 KiB local safety limit.",
                413,
            )
        if request.method in _MUTATING_METHODS and content_len > 0 and not request.is_json:
            return _reject(
                "unsupported_media_type",
                "Request Content-Type must be application/json.",
                415,
            )

    return None


def _parse_json_object() -> dict[str, object]:
    if not request.is_json:
        raise ValidationError(
            "Request Content-Type must be application/json.",
            code="unsupported_media_type",
            status_code=415,
        )
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a valid JSON object.")
    return payload


@api_bp.get("/overview")
def get_overview() -> tuple[Response, int]:
    """Return authoritative balance, selected-month totals, and recent transactions."""
    month = request.args.get("month")
    db_path = current_app.config["FINORA_DB_PATH"]
    data = overview_service.get_overview(db_path, month=month)
    return jsonify(data), 200


@api_bp.get("/transactions")
def list_transactions() -> tuple[Response, int]:
    """Return filtered, sorted, paginated chronological transactions."""
    raw_limit = request.args.get("limit", "100")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except ValueError as exc:
        raise ValidationError("Pagination parameters must be integers.") from exc
    if limit <= 0 or offset < 0:
        raise ValidationError("Pagination parameters out of range.")
    db_path = current_app.config["FINORA_DB_PATH"]
    data = transaction_service.list_transactions(
        db_path,
        limit=limit,
        offset=offset,
        query=request.args.get("q"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
        month=request.args.get("month"),
        account_id=request.args.get("account_id"),
        category_id=request.args.get("category_id"),
        entry_type=request.args.get("entry_type"),
        payment_method=request.args.get("payment_method"),
        tag_id=request.args.get("tag_id"),
        min_amount=request.args.get("min_amount"),
        max_amount=request.args.get("max_amount"),
        deleted=request.args.get("deleted"),
        sort=request.args.get("sort"),
    )
    return jsonify(data), 200


@api_bp.get("/transactions/<int:transaction_id>")
def get_transaction(transaction_id: int) -> tuple[Response, int]:
    """Fetch a single logical transaction with postings, tags, and attachments."""
    db_path = current_app.config["FINORA_DB_PATH"]
    tx = transaction_service.get_transaction_detail(db_path, transaction_id)
    return jsonify({"transaction": tx}), 200


@api_bp.post("/transactions")
def create_transaction() -> tuple[Response, int]:
    """Create a Phase 2 single or split expense/income transaction."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tx, created = transaction_service.create_transaction(db_path, payload)
    status = 201 if created else 200
    return jsonify({"transaction": tx, "created": created}), status


@api_bp.patch("/transactions/<int:transaction_id>")
def update_transaction(transaction_id: int) -> tuple[Response, int]:
    """Atomically edit a transaction, its split postings, transfer sides, or tags."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tx = transaction_service.update_transaction(db_path, transaction_id, payload)
    return jsonify({"transaction": tx}), 200


@api_bp.delete("/transactions/<int:transaction_id>")
def delete_transaction(transaction_id: int) -> tuple[Response, int]:
    """Soft-delete an active transaction while preserving recovery and attachments."""
    db_path = current_app.config["FINORA_DB_PATH"]
    tx = transaction_service.soft_delete_transaction(db_path, transaction_id)
    return jsonify({"transaction": tx}), 200


@api_bp.post("/transactions/<int:transaction_id>/restore")
def restore_transaction(transaction_id: int) -> tuple[Response, int]:
    """Restore a soft-deleted transaction back into active ledger totals."""
    db_path = current_app.config["FINORA_DB_PATH"]
    tx = transaction_service.restore_transaction(db_path, transaction_id)
    return jsonify({"transaction": tx}), 200


@api_bp.delete("/transactions/<int:transaction_id>/purge")
def purge_transaction(transaction_id: int) -> tuple[Response, int]:
    """Permanently purge a soft-deleted transaction."""
    db_path = current_app.config["FINORA_DB_PATH"]
    res = transaction_service.purge_transaction(db_path, transaction_id)
    return jsonify(res), 200


@api_bp.post("/transactions/bulk")
def bulk_transactions() -> tuple[Response, int]:
    """Apply atomic bulk category, tag, delete, or restore operations."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    res = transaction_service.bulk_action(db_path, payload)
    return jsonify(res), 200


@api_bp.get("/transactions/<int:transaction_id>/refunds")
def list_transaction_refunds(transaction_id: int) -> tuple[Response, int]:
    """List active refunds and remaining refundable amounts for an expense."""
    db_path = current_app.config["FINORA_DB_PATH"]
    data = transaction_service.list_refunds_for_transaction(db_path, transaction_id)
    return jsonify(data), 200


@api_bp.post("/transactions/<int:transaction_id>/refunds")
def create_transaction_refund(transaction_id: int) -> tuple[Response, int]:
    """Record a linked partial or full refund for an active expense."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tx, created = transaction_service.create_refund(db_path, transaction_id, payload)
    return jsonify({"transaction": tx, "created": created}), (201 if created else 200)


@api_bp.post("/transfers")
def create_transfer() -> tuple[Response, int]:
    """Record an atomic internal account transfer or credit card repayment."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tx, created = transaction_service.create_transfer(db_path, payload)
    return jsonify({"transaction": tx, "created": created}), (201 if created else 200)


@api_bp.get("/categories")
def list_categories() -> tuple[Response, int]:
    """Return active seeded categories, optionally filtered by kind."""
    kind = request.args.get("kind")
    db_path = current_app.config["FINORA_DB_PATH"]
    categories = transaction_service.list_categories(db_path, kind=kind)
    return jsonify({"categories": categories}), 200


@api_bp.get("/accounts")
def list_accounts() -> tuple[Response, int]:
    """Return financial accounts with authoritative balances and net worth summary."""
    include_archived = request.args.get("include_archived", "0").lower() in {"1", "true", "yes"}
    db_path = current_app.config["FINORA_DB_PATH"]
    data = account_service.list_accounts(db_path, include_archived=include_archived)
    return jsonify(data), 200


@api_bp.post("/accounts")
def create_account() -> tuple[Response, int]:
    """Create a new financial account (cash, bank, savings, wallet, or credit_card)."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    account = account_service.create_account(db_path, payload)
    return jsonify({"account": account}), 201


@api_bp.get("/accounts/<int:account_id>")
def get_account_detail(account_id: int) -> tuple[Response, int]:
    """Return detailed account view with activity stats and recent entries."""
    db_path = current_app.config["FINORA_DB_PATH"]
    detail = account_service.get_account_detail(db_path, account_id)
    return jsonify(detail), 200


@api_bp.patch("/accounts/<int:account_id>")
def update_account(account_id: int) -> tuple[Response, int]:
    """Update editable account metadata, opening balance, or credit limit."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    account = account_service.update_account(db_path, account_id, payload)
    return jsonify({"account": account}), 200


@api_bp.post("/accounts/<int:account_id>/archive")
def archive_account(account_id: int) -> tuple[Response, int]:
    """Archive an account while preserving historical ledger records."""
    payload = request.get_json(silent=True)
    confirm_nonzero = bool(isinstance(payload, dict) and payload.get("confirm_nonzero") is True)
    db_path = current_app.config["FINORA_DB_PATH"]
    account = account_service.archive_account(db_path, account_id, confirm_nonzero=confirm_nonzero)
    return jsonify({"account": account}), 200


@api_bp.post("/accounts/<int:account_id>/restore")
def restore_account(account_id: int) -> tuple[Response, int]:
    """Restore an archived account."""
    db_path = current_app.config["FINORA_DB_PATH"]
    account = account_service.restore_account(db_path, account_id)
    return jsonify({"account": account}), 200


@api_bp.get("/settings")
def get_settings() -> tuple[Response, int]:
    """Return current application preferences and local storage metadata."""
    db_path = current_app.config["FINORA_DB_PATH"]
    data = settings_service.get_settings(
        db_path,
        app_version=current_app.config["FINORA_APP_VERSION"],
        data_dir=current_app.config["FINORA_DATA_DIR"],
    )
    return jsonify(data), 200


@api_bp.put("/settings/appearance")
def update_appearance() -> tuple[Response, int]:
    """Update and persist application appearance preference."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    updated = settings_service.update_appearance(db_path, payload.get("appearance"))
    callback: Callable[[str], None] | None = current_app.extensions.get(
        "finora_appearance_callback"
    )
    if callback is not None:
        callback(updated["appearance"])
    return jsonify(updated), 200
