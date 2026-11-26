"""Versioned SQLite migration runner and idempotent baseline seeding."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.database import db_session, ensure_secure_data_dir
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


def create_pre_migration_backup(
    conn: sqlite3.Connection,
    db_path: Path,
    *,
    current_version: int,
    target_version: int,
) -> Path:
    """Create and verify an online SQLite pre-migration backup outside the repo and .app."""
    backups_dir = db_path.parent / "backups"
    ensure_secure_data_dir(backups_dir)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / (
        f"pre_migration_v{current_version}_to_v{target_version}_{stamp}.sqlite3"
    )
    suffix = 1
    while backup_path.exists():
        backup_path = backups_dir / (
            f"pre_migration_v{current_version}_to_v{target_version}_{stamp}_{suffix}.sqlite3"
        )
        suffix += 1

    backup_conn = sqlite3.connect(os.fspath(backup_path))
    try:
        conn.backup(backup_conn)
        check_row = backup_conn.execute("PRAGMA quick_check;").fetchone()
        if check_row is None or str(check_row[0]).lower() != "ok":
            raise DatabaseError("Pre-migration backup verification failed; migration aborted.")
    except sqlite3.Error as exc:
        raise DatabaseError(
            "Unable to create a verified pre-migration database backup; existing data is untouched."
        ) from exc
    finally:
        backup_conn.close()

    os.chmod(backup_path, 0o600)
    return backup_path


def verify_database_integrity(conn: sqlite3.Connection) -> None:
    """Verify foreign-key consistency and structural SQLite integrity after migration."""
    fk_rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
    if fk_rows:
        raise DatabaseError(
            "Database foreign-key check failed after migration; transaction rolled back."
        )
    integrity_row = conn.execute("PRAGMA integrity_check;").fetchone()
    if integrity_row is None or str(integrity_row[0]).lower() != "ok":
        raise DatabaseError("Database integrity check failed after migration.")


def _get_applied_versions(conn: sqlite3.Connection) -> set[int]:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations';"
    ).fetchone()
    if row is None:
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
    return {int(r["version"]) for r in rows}


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: Path | None = None,
    *,
    db_path: Path | None = None,
    backup_on_upgrade: bool = False,
) -> list[int]:
    """Apply all pending SQL migrations atomically inside an explicit SQLite transaction."""
    sql_dir = migrations_dir or default_migrations_dir()
    migrations = _discover_migrations(sql_dir)
    if not migrations:
        return []

    existing_versions = _get_applied_versions(conn)
    pending = [(v, n, p) for v, n, p in migrations if v not in existing_versions]
    if not pending:
        return []

    if (
        backup_on_upgrade
        and existing_versions
        and db_path is not None
        and str(db_path) != ":memory:"
        and db_path.exists()
    ):
        create_pre_migration_backup(
            conn,
            db_path,
            current_version=max(existing_versions),
            target_version=max(v for v, _, _ in pending),
        )

    started_txn = False
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE;")
        started_txn = True

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        applied_versions = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations;").fetchall()
        }

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

        if newly_applied:
            verify_database_integrity(conn)
        if started_txn:
            conn.commit()
        return newly_applied
    except Exception:
        if started_txn and conn.in_transaction:
            conn.rollback()
        raise


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
        cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(accounts);").fetchall()}
        if "opening_balance_date" in cols:
            conn.execute(
                """
                INSERT INTO accounts (
                    name, account_type, opening_balance_minor, opening_balance_date,
                    description, icon, color_token, credit_limit_minor,
                    currency, is_default, is_archived, created_at, updated_at
                )
                VALUES ('Cash', 'cash', 0, ?, 'Primary cash wallet', 'wallet', 'cat-forest', NULL, 'INR', 1, 0, ?, ?);
                """,
                (now[:10], now, now),
            )
        else:
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
    """Initialize database file, create backup before upgrading existing DB, migrate, and seed."""
    resolved_path = Path(db_path) if str(db_path) != ":memory:" else None
    with db_session(db_path) as conn:
        try:
            applied = apply_migrations(
                conn,
                migrations_dir=migrations_dir,
                db_path=resolved_path,
                backup_on_upgrade=True,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Database schema migration failed and was rolled back safely. "
                "Your original records and any pre-migration backup in the backups directory remain intact."
            ) from exc
        seed_defaults(conn)
        return applied
