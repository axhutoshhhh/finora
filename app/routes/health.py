"""Minimal health probe route for local server readiness verification."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health_check() -> tuple[Response, int]:
    """Return minimal readiness payload without exposing paths or financial data."""
    return jsonify({"status": "ok"}), 200
