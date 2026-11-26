"""Runtime, testing, and frozen-bundle configuration for Finora."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Finora"
APP_VERSION = "0.3.0"
BUNDLE_IDENTIFIER = "app.finora.desktop"
DEFAULT_DATA_DIR_NAME = "Finora"
DB_FILENAME = "finance.sqlite3"
MAX_CONTENT_LENGTH_BYTES = 64 * 1024  # 64 KiB for JSON endpoints
MAX_ATTACHMENT_HTTP_BYTES = 5 * 1024 * 1024 + 64 * 1024  # 5 MiB file + multipart overhead


def get_bundle_root() -> Path:
    """Return the root path for bundled templates, static files, and migrations."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def resolve_default_data_dir() -> Path:
    """Resolve Finora's mutable runtime directory outside the repo and .app bundle."""
    env_override = os.environ.get("FINORA_DATA_DIR")
    if env_override and env_override.strip():
        return Path(env_override.strip()).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / DEFAULT_DATA_DIR_NAME
    return Path.home() / ".local" / "share" / "finora"


@dataclass(frozen=True)
class FinoraSettings:
    """Resolved Flask application configuration."""

    data_dir: Path
    db_path: Path
    api_token: str
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]
    testing: bool = False
    debug: bool = False

    @classmethod
    def build(
        cls,
        *,
        data_dir: Path | str | None = None,
        db_path: Path | str | None = None,
        api_token: str | None = None,
        server_port: int | None = None,
        testing: bool = False,
    ) -> FinoraSettings:
        resolved_data_dir = Path(data_dir) if data_dir is not None else resolve_default_data_dir()
        resolved_db_path = (
            Path(db_path) if db_path is not None else (resolved_data_dir / DB_FILENAME)
        )
        resolved_token = api_token if api_token else secrets.token_urlsafe(32)

        if server_port is not None:
            hosts = frozenset({f"127.0.0.1:{server_port}"})
            origins = frozenset({f"http://127.0.0.1:{server_port}"})
        elif testing:
            hosts = frozenset({"127.0.0.1", "localhost"})
            origins = frozenset({"http://127.0.0.1", "http://localhost"})
        else:
            hosts = frozenset({"127.0.0.1"})
            origins = frozenset({"http://127.0.0.1"})

        return cls(
            data_dir=resolved_data_dir,
            db_path=resolved_db_path,
            api_token=resolved_token,
            allowed_hosts=hosts,
            allowed_origins=origins,
            testing=testing,
            debug=False,
        )
