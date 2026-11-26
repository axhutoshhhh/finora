"""Database migration, seeding, constraint, and transaction integrity tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database import connect, db_session
from app.migrations.runner import (
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    apply_migrations,
    initialize_database,
)


@pytest.mark.unit
def test_initial_schema_seeding_and_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "unicode folder ₹" / "finance.sqlite3"
    applied_first = initialize_database(db_path)
    assert applied_first == [1]

    # Repeated initialization must be completely idempotent
    applied_second = initialize_database(db_path)
    assert applied_second == []

    with db_session(db_path) as conn:
        migrations = conn.execute("SELECT version, name FROM schema_migrations;").fetchall()
        assert [(m["version"], m["name"]) for m in migrations] == [(1, "initial_schema")]

        expense_cats = conn.execute(
            "SELECT slug, name FROM categories WHERE kind = 'expense' ORDER BY sort_order;"
        ).fetchall()
        assert len(expense_cats) == 10
        assert [c["slug"] for c in expense_cats] == [c[0] for c in DEFAULT_EXPENSE_CATEGORIES]

        income_cats = conn.execute(
            "SELECT slug, name FROM categories WHERE kind = 'income' ORDER BY sort_order;"
        ).fetchall()
        assert len(income_cats) == len(DEFAULT_INCOME_CATEGORIES)
        assert {c["slug"] for c in expense_cats}.isdisjoint({c["slug"] for c in income_cats})

        accounts = conn.execute(
            "SELECT name, account_type, opening_balance_minor, currency, is_default FROM accounts;"
        ).fetchall()
        assert len(accounts) == 1
        assert dict(accounts[0]) == {
            "name": "Cash",
            "account_type": "cash",
            "opening_balance_minor": 0,
            "currency": "INR",
            "is_default": 1,
        }

        appearance = conn.execute("SELECT value FROM settings WHERE key = 'appearance';").fetchone()
        assert appearance is not None and appearance["value"] == "system"


@pytest.mark.unit
def test_foreign_keys_and_constraints_enforced(isolated_db: Path) -> None:
    conn = connect(isolated_db)
    try:
        fk_state = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk_state == 1

        # Foreign key violation on nonexistent account_id
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute(
                """
                INSERT INTO transactions (entry_type, tx_date, description, created_at, updated_at)
                VALUES ('expense', '2026-11-26', 'Bad FK', '2026-11-26T00:00:00Z', '2026-11-26T00:00:00Z');
                """
            )
            tx_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
            conn.execute(
                """
                INSERT INTO postings (transaction_id, account_id, category_id, signed_amount_minor, created_at)
                VALUES (?, 9999, 1, -100, '2026-11-26T00:00:00Z');
                """,
                (tx_id,),
            )

        # Rollback must have discarded the parent transactions row too
        count = conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0]
        assert count == 0

        # Zero amount posting rejected
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute(
                """
                INSERT INTO transactions (entry_type, tx_date, description, created_at, updated_at)
                VALUES ('expense', '2026-11-26', 'Zero', '2026-11-26T00:00:00Z', '2026-11-26T00:00:00Z');
                """
            )
            tx_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
            conn.execute(
                """
                INSERT INTO postings (transaction_id, account_id, category_id, signed_amount_minor, created_at)
                VALUES (?, 1, 1, 0, '2026-11-26T00:00:00Z');
                """,
                (tx_id,),
            )
    finally:
        conn.close()


@pytest.mark.unit
def test_ddl_migration_rolls_back_atomically_on_failure(tmp_path: Path) -> None:
    mig_dir = tmp_path / "broken_migrations"
    mig_dir.mkdir()
    (mig_dir / "0001_broken.sql").write_text(
        """
        CREATE TABLE partial_table (id INTEGER PRIMARY KEY);
        INSERT INTO nonexistent_table VALUES (1);
        """,
        encoding="utf-8",
    )
    db_path = tmp_path / "atomic_test.sqlite3"
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(conn, migrations_dir=mig_dir)
        # Verify partial_table was rolled back atomically rather than left committed
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='partial_table';"
        ).fetchone()
        assert row is None
    finally:
        conn.close()
