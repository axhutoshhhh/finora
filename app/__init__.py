"""Flask application factory, security headers, and error normalization."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from app.config import (
    APP_VERSION,
    MAX_ATTACHMENT_HTTP_BYTES,
    FinoraSettings,
    get_bundle_root,
)
from app.migrations.runner import initialize_database
from app.routes.api import api_bp
from app.routes.health import health_bp
from app.routes.pages import pages_bp
from app.utils.errors import FinoraError

logger = logging.getLogger("finora")

CSP_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)


def _is_valid_host(host_header: str | None, allowed_hosts: frozenset[str]) -> bool:
    if not host_header:
        return False
    return host_header.strip().lower() in allowed_hosts


def create_app(
    *,
    data_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    api_token: str | None = None,
    server_port: int | None = None,
    testing: bool = False,
    initialize_db: bool = True,
    appearance_callback: Callable[[str], None] | None = None,
) -> Flask:
    """Create and configure a secured Finora Flask application instance."""
    settings = FinoraSettings.build(
        data_dir=data_dir,
        db_path=db_path,
        api_token=api_token,
        server_port=server_port,
        testing=testing,
    )

    bundle_root = get_bundle_root()
    app = Flask(
        __name__,
        template_folder=str(bundle_root / "app" / "templates"),
        static_folder=str(bundle_root / "app" / "static"),
        static_url_path="/static",
    )

    app.config.update(
        TESTING=settings.testing,
        DEBUG=False,
        PROPAGATE_EXCEPTIONS=False,
        MAX_CONTENT_LENGTH=MAX_ATTACHMENT_HTTP_BYTES,
        FINORA_APP_VERSION=APP_VERSION,
        FINORA_DATA_DIR=settings.data_dir,
        FINORA_DB_PATH=settings.db_path,
        FINORA_API_TOKEN=settings.api_token,
        FINORA_ALLOWED_HOSTS=settings.allowed_hosts,
        FINORA_ALLOWED_ORIGINS=settings.allowed_origins,
        FINORA_WORKSPACE_GEN=1,
        FINORA_ACTIVE_WORKSPACE="primary",
    )
    app.extensions["finora_workspace_lock"] = threading.RLock()

    if appearance_callback is not None:
        app.extensions["finora_appearance_callback"] = appearance_callback

    if initialize_db:
        migrations_dir = bundle_root / "app" / "migrations" / "sql"
        initialize_database(settings.db_path, migrations_dir=migrations_dir)

    @app.before_request
    def _enforce_host_header() -> Response | tuple[Response, int] | None:
        allowed_hosts: frozenset[str] = app.config["FINORA_ALLOWED_HOSTS"]
        if not _is_valid_host(request.headers.get("Host"), allowed_hosts):
            return jsonify(
                {
                    "error": {
                        "code": "invalid_host",
                        "message": "Forbidden host header.",
                    }
                }
            ), 403
        return None

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(FinoraError)
    def _handle_finora_error(exc: FinoraError) -> tuple[Response, int]:
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(404)
    def _handle_not_found(_exc: Any) -> tuple[Response, int]:
        return jsonify({"error": {"code": "not_found", "message": "Resource not found."}}), 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(_exc: Any) -> tuple[Response, int]:
        return jsonify(
            {"error": {"code": "method_not_allowed", "message": "HTTP method not allowed."}}
        ), 405

    @app.errorhandler(413)
    def _handle_payload_too_large(_exc: Any) -> tuple[Response, int]:
        return jsonify(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": "Request payload exceeds the allowed size limit.",
                }
            }
        ), 413

    @app.errorhandler(Exception)
    def _handle_unexpected_error(exc: Exception) -> tuple[Response, int]:
        logger.exception("Unhandled backend exception: %s", type(exc).__name__)
        return jsonify(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected local error occurred.",
                }
            }
        ), 500

    app.register_blueprint(health_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    return app
