"""Versioned SQLite migration runner and idempotent baseline seeding."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.database import db_session
from app.utils.errors import DatabaseError
from app.utils.time import utc_now_iso

_MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

DEFAULT_EXPENSE_CATEGORIES: tuple[tuple[str, str, str, str, int], ...] = (
    ("food_dining", "Food & Dining", "utensils", "cat-amber", 1),
    ("housing_rent", "Housing & Rent", "house", "cat-slate", 2),
    ("transportation", "Transportation", "car", "cat-teal", 3),
    ("shopping", "Shopping", "shopping-bag", "cat-clay", 4),
    ("education", "Education", "book-open", "cat-indigo", 5),
    ("healthcare", "Healthcare", "heart-pulse", "cat-rose", 6),
    ("entertainment", "Entertainment", "film", "cat-plum", 7),
    ("subscriptions", "Subscriptions", "repeat", "cat-sage", 8),
    ("utilities_bills", "Utilities & Bills", "zap", "cat-ochre", 9),
    ("miscellaneous", "Miscellaneous", "circle-ellipsis", "cat-stone", 10),
)

DEFAULT_INCOME_CATEGORIES: tuple[tuple[str, str, str, str, int], ...] = (
    ("salary", "Salary", "briefcase", "cat-forest", 1),
    ("allowance", "Allowance", "coins", "cat-sage", 2),
    ("freelance_income", "Freelance Income", "laptop", "cat-teal", 3),
    ("scholarship", "Scholarship", "graduation-cap", "cat-indigo", 4),
    ("business_income", "Business Income", "building-2", "cat-slate", 5),
    ("gifts", "Gifts", "gift", "cat-amber", 6),
    ("other_income", "Other Income", "plus-circle", "cat-stone", 7),
)


def default_migrations_dir() -> Path:
    """Return the path containing bundled SQL migration files."""
    return Path(__file__).resolve().parent / "sql"


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split a SQL script into individual complete statements without implicit commits."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        candidate = "\n".join(buffer)
        if sqlite3.complete_statement(candidate):
            cleaned = candidate.strip()
            if cleaned:
                statements.append(cleaned)
            buffer.clear()
    leftover = "\n".join(buffer).strip()
    if leftover:
        statements.append(leftover)
    return statements


def _discover_migrations(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    if not migrations_dir.is_dir():
        raise DatabaseError("Bundled database migration directory is missing.")
    found: list[tuple[int, str, Path]] = []
    for path in sorted(migrations_dir.iterdir()):
        if not path.is_file():
            continue
        match = _MIGRATION_FILE_RE.fullmatch(path.name)
        if match:
            version = int(match.group(1))
            name = match.group(2)
            found.append((version, name, path))
    return found


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[int]:
    """Apply all pending SQL migrations atomically inside the caller's transaction."""
    sql_dir = migrations_dir or default_migrations_dir()
    migrations = _discover_migrations(sql_dir)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        """
    )
    applied_rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
    applied_versions = {int(row["version"]) for row in applied_rows}

    newly_applied: list[int] = []
    for version, name, sql_path in migrations:
        if version in applied_versions:
            continue
        sql_text = sql_path.read_text(encoding="utf-8")
        for stmt in _split_sql_statements(sql_text):
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
            (version, name, utc_now_iso()),
        )
        newly_applied.append(version)
    return newly_applied


def seed_defaults(conn: sqlite3.Connection) -> None:
    """Seed baseline categories, default Cash account, and default settings idempotently."""
    now = utc_now_iso()

    for slug, name, icon, color_token, sort_order in DEFAULT_EXPENSE_CATEGORIES:
        conn.execute(
            """
            INSERT INTO categories (slug, name, kind, icon, color_token, sort_order, is_system, is_archived, created_at)
            VALUES (?, ?, 'expense', ?, ?, ?, 1, 0, ?)
            ON CONFLICT(slug) DO NOTHING;
            """,
            (slug, name, icon, color_token, sort_order, now),
        )

    for slug, name, icon, color_token, sort_order in DEFAULT_INCOME_CATEGORIES:
        conn.execute(
            """
            INSERT INTO categories (slug, name, kind, icon, color_token, sort_order, is_system, is_archived, created_at)
            VALUES (?, ?, 'income', ?, ?, ?, 1, 0, ?)
            ON CONFLICT(slug) DO NOTHING;
            """,
            (slug, name, icon, color_token, sort_order, now),
        )

    existing_accounts = conn.execute("SELECT COUNT(*) FROM accounts;").fetchone()[0]
    if existing_accounts == 0:
        conn.execute(
            """
            INSERT INTO accounts (
                name, account_type, opening_balance_minor, currency, is_default, is_archived, created_at, updated_at
            )
            VALUES ('Cash', 'cash', 0, 'INR', 1, 0, ?, ?);
            """,
            (now, now),
        )

    for key, value in (("appearance", "system"), ("currency", "INR")):
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO NOTHING;
            """,
            (key, value, now),
        )


def initialize_database(
    db_path: Path | str,
    *,
    migrations_dir: Path | None = None,
) -> list[int]:
    """Initialize database file, run pending migrations, and seed baseline records."""
    with db_session(db_path) as conn:
        applied = apply_migrations(conn, migrations_dir=migrations_dir)
        seed_defaults(conn)
        return applied
