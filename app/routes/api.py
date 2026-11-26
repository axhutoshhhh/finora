"""Secured JSON API routes for Phase 1 Finora functionality."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from urllib.parse import urlparse

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from app.config import MAX_CONTENT_LENGTH_BYTES
from app.services import (
    account_service,
    attachment_service,
    budget_service,
    category_service,
    overview_service,
    settings_service,
    tag_service,
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
        content_len = request.content_length
        if content_len is not None and content_len > MAX_CONTENT_LENGTH_BYTES:
            return _reject(
                "payload_too_large",
                "Request body exceeds the 64 KiB local safety limit.",
                413,
            )
        raw_body = request.get_data(cache=True, as_text=False) if content_len is None else b""
        effective_len = len(raw_body) if content_len is None else content_len
        if effective_len > MAX_CONTENT_LENGTH_BYTES:
            return _reject(
                "payload_too_large",
                "Request body exceeds the 64 KiB local safety limit.",
                413,
            )
        if request.method in _MUTATING_METHODS and effective_len > 0 and not request.is_json:
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
    """Return seeded and custom categories, optionally filtered by kind and archive state."""
    kind = request.args.get("kind")
    include_archived = request.args.get("include_archived", "0").lower() in {"1", "true", "yes"}
    db_path = current_app.config["FINORA_DB_PATH"]
    categories = category_service.list_categories(
        db_path, kind=kind, include_archived=include_archived
    )
    return jsonify({"categories": categories}), 200


@api_bp.post("/categories")
def create_category() -> tuple[Response, int]:
    """Create a custom expense or income category."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    cat = category_service.create_category(db_path, payload)
    return jsonify({"category": cat}), 201


@api_bp.patch("/categories/<int:category_id>")
def update_category(category_id: int) -> tuple[Response, int]:
    """Rename or customize an existing category."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    cat = category_service.update_category(db_path, category_id, payload)
    return jsonify({"category": cat}), 200


@api_bp.post("/categories/<int:category_id>/archive")
def archive_category(category_id: int) -> tuple[Response, int]:
    """Archive a category without altering historical transactions."""
    db_path = current_app.config["FINORA_DB_PATH"]
    cat = category_service.archive_category(db_path, category_id)
    return jsonify({"category": cat}), 200


@api_bp.post("/categories/<int:category_id>/restore")
def restore_category(category_id: int) -> tuple[Response, int]:
    """Restore an archived category."""
    db_path = current_app.config["FINORA_DB_PATH"]
    cat = category_service.restore_category(db_path, category_id)
    return jsonify({"category": cat}), 200


@api_bp.get("/tags")
def list_tags() -> tuple[Response, int]:
    """Return user-defined tags ordered alphabetically."""
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"tags": tag_service.list_tags(db_path)}), 200


@api_bp.post("/tags")
def create_tag() -> tuple[Response, int]:
    """Create a new transaction tag."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tag, created = tag_service.create_tag(db_path, payload)
    return jsonify({"tag": tag, "created": created}), 201


@api_bp.patch("/tags/<int:tag_id>")
def update_tag(tag_id: int) -> tuple[Response, int]:
    """Rename a tag safely."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    tag = tag_service.update_tag(db_path, tag_id, payload)
    return jsonify({"tag": tag}), 200


@api_bp.delete("/tags/<int:tag_id>")
def delete_tag(tag_id: int) -> tuple[Response, int]:
    """Delete a tag while preserving all transactions."""
    db_path = current_app.config["FINORA_DB_PATH"]
    res = tag_service.delete_tag(db_path, tag_id)
    return jsonify(res), 200


@api_bp.post("/transactions/<int:transaction_id>/attachments")
def upload_transaction_attachment(transaction_id: int) -> tuple[Response, int]:
    """Upload a bounded PNG, JPEG, or PDF receipt attachment for a transaction."""
    if request.mimetype != "multipart/form-data":
        raise ValidationError(
            "Attachment uploads must use multipart/form-data.",
            code="unsupported_media_type",
            status_code=415,
            field="file",
        )
    upload = request.files.get("file")
    if upload is None:
        raise ValidationError("No file provided in upload request.", field="file")
    raw_bytes = upload.stream.read(attachment_service.MAX_ATTACHMENT_BYTES + 1)
    db_path = current_app.config["FINORA_DB_PATH"]
    att = attachment_service.save_attachment(
        db_path,
        transaction_id=transaction_id,
        original_filename=upload.filename,
        raw_bytes=raw_bytes,
    )
    return jsonify({"attachment": att}), 201


@api_bp.get("/attachments/<int:attachment_id>")
def download_attachment(attachment_id: int) -> Response:
    """Serve a validated local attachment with strict download/sandbox headers."""
    db_path = current_app.config["FINORA_DB_PATH"]
    meta, file_path = attachment_service.get_attachment_for_download(db_path, attachment_id)
    resp = send_file(
        file_path,
        mimetype=str(meta["mime_type"]),
        as_attachment=True,
        download_name=str(meta["original_filename"]),
    )
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@api_bp.delete("/attachments/<int:attachment_id>")
def delete_attachment(attachment_id: int) -> tuple[Response, int]:
    """Remove an attachment record and unlink its stored file."""
    db_path = current_app.config["FINORA_DB_PATH"]
    res = attachment_service.delete_attachment(db_path, attachment_id)
    return jsonify(res), 200


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


@api_bp.get("/budgets")
def get_budgets() -> tuple[Response, int]:
    """Return monthly category budgets, overall limit, spend, and rollover state."""
    month = request.args.get("month")
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(budget_service.get_month_budgets(db_path, month=month)), 200


@api_bp.put("/budgets")
@api_bp.put("/budgets/category")
def put_category_budget() -> tuple[Response, int]:
    """Create or update a category spending limit for a month."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    data = budget_service.set_category_budget(db_path, payload)
    return jsonify(data), 200


@api_bp.delete("/budgets/<int:category_id>")
@api_bp.delete("/budgets/category/<int:category_id>")
def delete_category_budget(category_id: int) -> tuple[Response, int]:
    """Remove a category's monthly budget limit."""
    month = request.args.get("month")
    db_path = current_app.config["FINORA_DB_PATH"]
    data = budget_service.delete_category_budget(db_path, category_id=category_id, month=month)
    return jsonify(data), 200


@api_bp.put("/budgets/overall")
def put_overall_budget() -> tuple[Response, int]:
    """Create or update an overall monthly spending limit."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(budget_service.set_overall_budget(db_path, payload)), 200


@api_bp.delete("/budgets/overall")
def delete_overall_budget() -> tuple[Response, int]:
    """Remove the overall monthly spending limit."""
    month = request.args.get("month")
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(budget_service.delete_overall_budget(db_path, month=month)), 200


@api_bp.post("/budgets/copy")
def copy_budgets() -> tuple[Response, int]:
    """Copy configured budgets from previous (or specified) month into target month."""
    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(budget_service.copy_previous_budgets(db_path, payload)), 200


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


# ---------------------------------------------------------------------------
# Phase 3: Analytics & Reports
# ---------------------------------------------------------------------------


def _parse_int_list_arg(name: str) -> list[int] | None:
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    out: list[int] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if not p.isdigit() or int(p) <= 0:
            raise ValidationError(f"Invalid {name} filter.", field=name)
        out.append(int(p))
    return out or None


def _analytics_report_from_args() -> dict[str, object]:
    from app.services import analytics_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return analytics_service.get_full_analytics_report(
        db_path,
        preset=request.args.get("preset", "current_month"),
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        account_ids=_parse_int_list_arg("account_ids"),
        category_ids=_parse_int_list_arg("category_ids"),
    )


@api_bp.get("/analytics/report")
def get_analytics_report() -> tuple[Response, int]:
    """Return complete reconciled analytics payload for Reports."""
    return jsonify(_analytics_report_from_args()), 200


@api_bp.get("/analytics/summary")
def get_analytics_summary() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify(
        {"period": rep["period"], "summary": rep["summary"], "comparison": rep["comparison"]}
    ), 200


@api_bp.get("/analytics/income-expense")
def get_analytics_income_expense() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify({"period": rep["period"], "monthly_series": rep["monthly_series"]}), 200


@api_bp.get("/analytics/categories")
def get_analytics_categories() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify({"period": rep["period"], "categories": rep["categories"]}), 200


@api_bp.get("/analytics/merchants")
def get_analytics_merchants() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify({"period": rep["period"], "merchants": rep["merchants"]}), 200


@api_bp.get("/analytics/balance-history")
def get_analytics_balance_history() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify({"period": rep["period"], "balance_history": rep["balance_history"]}), 200


@api_bp.get("/analytics/budgets")
def get_analytics_budgets() -> tuple[Response, int]:
    rep = _analytics_report_from_args()
    return jsonify({"period": rep["period"], "budget_performance": rep["budget_performance"]}), 200


@api_bp.get("/analytics/forecast")
def get_analytics_forecast() -> tuple[Response, int]:
    from app.services import forecasting_service

    db_path = current_app.config["FINORA_DB_PATH"]
    month = request.args.get("month")
    return jsonify(forecasting_service.compute_monthly_forecast(db_path, month=month)), 200


# ---------------------------------------------------------------------------
# Phase 3: Insights & Notifications
# ---------------------------------------------------------------------------


@api_bp.get("/insights")
@api_bp.get("/notifications")
def get_insights() -> tuple[Response, int]:
    from app.services import advisory_service

    db_path = current_app.config["FINORA_DB_PATH"]
    advisory_service.evaluate_advisories(db_path)
    items = advisory_service.list_notifications(db_path)
    unread_count = sum(1 for item in items if not item["is_read"])
    return jsonify({"notifications": items, "unread_count": unread_count}), 200


@api_bp.post("/notifications/<int:notification_id>/read")
def mark_notification_read(notification_id: int) -> tuple[Response, int]:
    from app.services import advisory_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(advisory_service.mark_notification_read(db_path, notification_id)), 200


@api_bp.post("/notifications/read-all")
def mark_all_notifications_read() -> tuple[Response, int]:
    from app.services import advisory_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(advisory_service.mark_all_notifications_read(db_path)), 200


@api_bp.post("/notifications/<int:notification_id>/dismiss")
def dismiss_notification(notification_id: int) -> tuple[Response, int]:
    from app.services import advisory_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(advisory_service.dismiss_notification(db_path, notification_id)), 200


@api_bp.get("/notification-preferences")
def get_notification_preferences() -> tuple[Response, int]:
    from app.services import advisory_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"preferences": advisory_service.get_notification_preferences(db_path)}), 200


@api_bp.put("/notification-preferences")
def update_notification_preferences() -> tuple[Response, int]:
    from app.services import advisory_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    items = payload.get("preferences")
    if not isinstance(items, list):
        raise ValidationError("Preferences list is required.", field="preferences")
    return jsonify(
        {"preferences": advisory_service.update_notification_preferences(db_path, items)}
    ), 200


# ---------------------------------------------------------------------------
# Phase 3: Savings Goals, Recurring, Calendar & Categorization
# ---------------------------------------------------------------------------


@api_bp.get("/goals")
def list_goals() -> tuple[Response, int]:
    from app.services import goal_service

    db_path = current_app.config["FINORA_DB_PATH"]
    inc_arch = request.args.get("include_archived", "0") == "1"
    return jsonify(goal_service.list_goals(db_path, include_archived=inc_arch)), 200


@api_bp.post("/goals")
def create_goal() -> tuple[Response, int]:
    from app.services import goal_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"goal": goal_service.create_goal(db_path, payload)}), 201


@api_bp.get("/goals/<int:goal_id>")
def get_goal_detail(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(goal_service.get_goal_detail(db_path, goal_id)), 200


@api_bp.post("/goals/<int:goal_id>/contributions")
def add_goal_contribution(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(
        goal_service.add_contribution(db_path, goal_id, payload, is_withdrawal=False)
    ), 201


@api_bp.post("/goals/<int:goal_id>/withdrawals")
def withdraw_goal_contribution(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(
        goal_service.add_contribution(db_path, goal_id, payload, is_withdrawal=True)
    ), 201


@api_bp.post("/goals/<int:goal_id>/complete")
def complete_goal(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"goal": goal_service.update_goal_status(db_path, goal_id, "completed")}), 200


@api_bp.post("/goals/<int:goal_id>/archive")
def archive_goal(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"goal": goal_service.update_goal_status(db_path, goal_id, "archived")}), 200


@api_bp.post("/goals/<int:goal_id>/restore")
def restore_goal(goal_id: int) -> tuple[Response, int]:
    from app.services import goal_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"goal": goal_service.update_goal_status(db_path, goal_id, "active")}), 200


@api_bp.get("/recurring")
def list_recurring_rules() -> tuple[Response, int]:
    from app.services import recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    recurring_service.sync_occurrences(db_path)
    data = recurring_service.list_rules(db_path)
    data["occurrences"] = recurring_service.list_occurrences(db_path)
    return jsonify(data), 200


@api_bp.post("/recurring")
def create_recurring_rule() -> tuple[Response, int]:
    from app.services import recurring_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"rule": recurring_service.create_rule(db_path, payload)}), 201


@api_bp.post("/recurring/<int:rule_id>/pause")
def pause_recurring_rule(rule_id: int) -> tuple[Response, int]:
    from app.services import recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(recurring_service.update_rule_status(db_path, rule_id, "paused")), 200


@api_bp.post("/recurring/<int:rule_id>/resume")
def resume_recurring_rule(rule_id: int) -> tuple[Response, int]:
    from app.services import recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(recurring_service.update_rule_status(db_path, rule_id, "active")), 200


@api_bp.post("/recurring/occurrences/<int:occurrence_id>/post")
def post_recurring_occurrence(occurrence_id: int) -> tuple[Response, int]:
    from app.services import recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(recurring_service.post_occurrence(db_path, occurrence_id)), 200


@api_bp.post("/recurring/occurrences/<int:occurrence_id>/skip")
def skip_recurring_occurrence(occurrence_id: int) -> tuple[Response, int]:
    from app.services import recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(recurring_service.skip_occurrence(db_path, occurrence_id)), 200


@api_bp.get("/calendar")
def get_calendar_month() -> tuple[Response, int]:
    from datetime import date

    from app.services import calendar_service, recurring_service

    db_path = current_app.config["FINORA_DB_PATH"]
    recurring_service.sync_occurrences(db_path)
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    return jsonify(calendar_service.get_month_calendar(db_path, month=month)), 200


@api_bp.get("/categorization-rules")
def list_categorization_rules() -> tuple[Response, int]:
    from app.services import categorization_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"rules": categorization_service.list_rules(db_path)}), 200


@api_bp.post("/categorization-rules")
def create_categorization_rule() -> tuple[Response, int]:
    from app.services import categorization_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"rule": categorization_service.create_rule(db_path, payload)}), 201


@api_bp.delete("/categorization-rules/<int:rule_id>")
def delete_categorization_rule(rule_id: int) -> tuple[Response, int]:
    from app.services import categorization_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify(categorization_service.delete_rule(db_path, rule_id)), 200


@api_bp.get("/categorization/suggest")
def suggest_categorization() -> tuple[Response, int]:
    from app.services import categorization_service

    db_path = current_app.config["FINORA_DB_PATH"]
    suggestion = categorization_service.suggest_category(
        db_path,
        entry_type=request.args.get("entry_type", "expense"),
        merchant=request.args.get("merchant", ""),
        description=request.args.get("description", ""),
    )
    return jsonify({"suggestion": suggestion}), 200


# ---------------------------------------------------------------------------
# Phase 3: CSV Import, CSV/PDF Export & Backup/Restore
# ---------------------------------------------------------------------------


@api_bp.post("/import/preview")
def preview_csv_import() -> tuple[Response, int]:
    from app.services import import_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    csv_text = str(payload.get("csv_text") or "")
    account_id = int(payload.get("account_id") or 0)
    mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else {}
    date_format = str(payload.get("date_format") or "auto")
    res = import_service.preview_csv_import(
        db_path,
        csv_bytes=csv_text.encode("utf-8"),
        account_id=account_id,
        mapping=mapping,
        date_format=date_format,
    )
    return jsonify(res), 200


@api_bp.post("/import/commit")
def commit_csv_import() -> tuple[Response, int]:
    from app.services import import_service

    payload = _parse_json_object()
    db_path = current_app.config["FINORA_DB_PATH"]
    res = import_service.commit_csv_import(
        db_path,
        batch_uuid=str(payload.get("batch_uuid") or ""),
        source_filename=str(payload.get("source_filename") or "import.csv"),
        account_id=int(payload.get("account_id") or 0),
        rows=payload.get("rows") if isinstance(payload.get("rows"), list) else [],
    )
    return jsonify(res), 201


@api_bp.get("/import/history")
def list_import_history() -> tuple[Response, int]:
    from app.services import import_service

    db_path = current_app.config["FINORA_DB_PATH"]
    return jsonify({"batches": import_service.list_import_history(db_path)}), 200


@api_bp.get("/export/csv")
def export_csv() -> Response:
    from app.services import export_service

    db_path = current_app.config["FINORA_DB_PATH"]
    csv_data = export_service.export_transactions_csv(db_path)
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=finora-transactions.csv"},
    )


@api_bp.get("/export/pdf")
def export_pdf() -> Response:
    from app.services import export_service

    db_path = current_app.config["FINORA_DB_PATH"]
    pdf_bytes = export_service.export_pdf_report(
        db_path,
        preset=request.args.get("preset", "current_month"),
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
    )
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=finora-report.pdf"},
    )


@api_bp.post("/backups")
def create_backup() -> tuple[Response, int]:
    from pathlib import Path

    from app.services import backup_service

    data_dir = Path(current_app.config["FINORA_DATA_DIR"])
    db_path = Path(current_app.config["FINORA_DB_PATH"])
    return jsonify(backup_service.create_workspace_backup(data_dir, db_path)), 201


@api_bp.post("/backups/restore")
def restore_backup() -> tuple[Response, int]:
    from pathlib import Path

    from app.services import backup_service

    payload = _parse_json_object()
    data_dir = Path(current_app.config["FINORA_DATA_DIR"])
    db_path = Path(current_app.config["FINORA_DB_PATH"])
    bpath = Path(str(payload.get("backup_path") or ""))
    # Restrict restore to files inside data_dir/backups for API safety
    backups_root = (data_dir / "backups").resolve()
    if backups_root not in bpath.resolve().parents:
        raise ValidationError(
            "Backup path must reside inside the Finora backups folder.", field="backup_path"
        )
    return jsonify(backup_service.restore_workspace_backup(data_dir, db_path, bpath)), 200


# ---------------------------------------------------------------------------
# Phase 3: Isolated Demo Workspace
# ---------------------------------------------------------------------------


@api_bp.get("/workspaces")
def get_workspace_status() -> tuple[Response, int]:
    active = str(current_app.config.get("FINORA_ACTIVE_WORKSPACE") or "primary")
    return jsonify({"active_workspace": active}), 200


@api_bp.post("/workspaces/switch")
def switch_workspace() -> tuple[Response, int]:
    from pathlib import Path

    from app.services import workspace_service

    payload = _parse_json_object()
    target = str(payload.get("workspace") or "")
    data_dir = Path(current_app.config["FINORA_DATA_DIR"])
    _, target_db = workspace_service.get_workspace_paths(data_dir, workspace=target)
    if target == "demo":
        workspace_service.seed_demo_workspace(target_db)
    current_app.config["FINORA_DB_PATH"] = target_db
    current_app.config["FINORA_ACTIVE_WORKSPACE"] = target
    return jsonify({"active_workspace": target}), 200


@api_bp.post("/workspaces/demo/reset")
def reset_demo_workspace() -> tuple[Response, int]:
    from pathlib import Path

    from app.services import workspace_service

    data_dir = Path(current_app.config["FINORA_DATA_DIR"])
    return jsonify(workspace_service.reset_demo_workspace(data_dir)), 200
