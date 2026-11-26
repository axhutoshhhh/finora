"""Application settings and appearance preference service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import db_session
from app.repositories import settings_repo
from app.utils.errors import ValidationError
from app.utils.time import utc_now_iso

VALID_APPEARANCES = ("system", "light", "dark")


def appearance_to_color_scheme_meta(appearance: str) -> str:
    """Map stored appearance setting to <meta name='color-scheme'> value."""
    if appearance == "light":
        return "light"
    if appearance == "dark":
        return "dark"
    return "light dark"


def get_appearance(db_path: Path | str) -> str:
    """Return the persisted appearance mode ('system', 'light', or 'dark')."""
    with db_session(db_path) as conn:
        value = settings_repo.get_setting(conn, "appearance")
    if value in VALID_APPEARANCES:
        return value
    return "system"


def update_appearance(db_path: Path | str, raw_appearance: object) -> dict[str, str]:
    """Validate and persist the application appearance preference."""
    if not isinstance(raw_appearance, str):
        raise ValidationError(
            "Appearance must be 'system', 'light', or 'dark'.", field="appearance"
        )
    cleaned = raw_appearance.strip().lower()
    if cleaned not in VALID_APPEARANCES:
        raise ValidationError(
            "Appearance must be 'system', 'light', or 'dark'.", field="appearance"
        )
    now = utc_now_iso()
    with db_session(db_path) as conn:
        settings_repo.upsert_setting(conn, "appearance", cleaned, now)
    return {
        "appearance": cleaned,
        "color_scheme_meta": appearance_to_color_scheme_meta(cleaned),
    }


def get_settings(
    db_path: Path | str,
    *,
    app_version: str,
    data_dir: Path,
) -> dict[str, Any]:
    """Return persisted application settings and transparent local storage metadata."""
    with db_session(db_path) as conn:
        raw_settings = settings_repo.get_all_settings(conn)
    appearance = raw_settings.get("appearance", "system")
    if appearance not in VALID_APPEARANCES:
        appearance = "system"
    currency = raw_settings.get("currency", "INR")
    return {
        "appearance": appearance,
        "color_scheme_meta": appearance_to_color_scheme_meta(appearance),
        "currency": currency,
        "version": app_version,
        "storage": {
            "data_dir": str(data_dir),
            "database_path": str(db_path),
            "encryption_note": (
                "Stored locally in SQLite with owner-only file permissions (0600); "
                "not encrypted by the application at rest—macOS FileVault protects the disk."
            ),
        },
    }
