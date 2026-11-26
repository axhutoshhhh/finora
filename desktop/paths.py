"""Path resolution and bundled-resource verification for source and frozen runs."""

from __future__ import annotations

from pathlib import Path

from app.config import DB_FILENAME, get_bundle_root, resolve_default_data_dir

REQUIRED_BUNDLED_PATHS: tuple[str, ...] = (
    "app/templates/base.html",
    "app/templates/app.html",
    "app/static/css/tokens.css",
    "app/static/js/main.js",
    "app/migrations/sql/0001_initial_schema.sql",
)


class AssetMissingError(RuntimeError):
    """Raised when required bundled templates, scripts, or migrations are absent."""


def get_data_dir() -> Path:
    """Return Finora's mutable user data directory outside the repo and .app bundle."""
    return resolve_default_data_dir()


def get_db_path(data_dir: Path | None = None) -> Path:
    """Return the SQLite database file path."""
    base = data_dir if data_dir is not None else get_data_dir()
    return base / DB_FILENAME


def get_lock_path(data_dir: Path | None = None) -> Path:
    """Return the single-instance flock file path."""
    base = data_dir if data_dir is not None else get_data_dir()
    return base / ".finora.lock"


def get_icon_path() -> Path | None:
    """Return path to the macOS Finora.icns asset if present."""
    candidate = get_bundle_root() / "assets" / "branding" / "Finora.icns"
    return candidate if candidate.is_file() else None


def verify_bundled_assets() -> Path:
    """Ensure required bundled templates, CSS/JS, and SQL migrations exist."""
    root = get_bundle_root()
    missing = [rel for rel in REQUIRED_BUNDLED_PATHS if not (root / rel).is_file()]
    if missing:
        raise AssetMissingError(
            "Required Finora application files are missing from the bundle: " + ", ".join(missing)
        )
    return root
