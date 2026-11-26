"""Repository for persistent application settings."""

from __future__ import annotations

import sqlite3


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """Retrieve a single setting value or None if absent."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)).fetchone()
    return str(row["value"]) if row is not None else None


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """Return all key-value pairs stored in settings."""
    rows = conn.execute("SELECT key, value FROM settings;").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def upsert_setting(conn: sqlite3.Connection, key: str, value: str, updated_at: str) -> None:
    """Insert or update a setting value."""
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at;
        """,
        (key, value, updated_at),
    )
