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
    assert applied_first == [1, 2]

    # Repeated initialization must be completely idempotent
    applied_second = initialize_database(db_path)
    assert applied_second == []

    with db_session(db_path) as conn:
        migrations = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version;"
        ).fetchall()
        assert [(m["version"], m["name"]) for m in migrations] == [
            (1, "initial_schema"),
            (2, "phase2_core_financials"),
        ]

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


@pytest.mark.unit
def test_phase1_to_phase2_migration_preserves_data_and_creates_backup(tmp_path: Path) -> None:
    from app.migrations.runner import default_migrations_dir

    db_path = tmp_path / "upgrade_test.sqlite3"
    phase1_only = tmp_path / "phase1_mig"
    phase1_only.mkdir()
    src_migs = default_migrations_dir()
    (phase1_only / "0001_initial_schema.sql").write_text(
        (src_migs / "0001_initial_schema.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # Seed genuine Phase 1 DB state
    assert initialize_database(db_path, migrations_dir=phase1_only) == [1]
    with db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO transactions (entry_type, tx_date, description, created_at, updated_at)
            VALUES ('income', '2026-11-10', 'Stipend', '2026-11-10T10:00:00Z', '2026-11-10T10:00:00Z');
            """
        )
        inc_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        conn.execute(
            """
            INSERT INTO postings (transaction_id, account_id, category_id, signed_amount_minor, created_at)
            VALUES (?, 1, 11, 500000, '2026-11-10T10:00:00Z');
            """,
            (inc_id,),
        )
        conn.execute(
            """
            INSERT INTO transactions (entry_type, tx_date, description, created_at, updated_at)
            VALUES ('expense', '2026-11-15', 'Groceries', '2026-11-15T10:00:00Z', '2026-11-15T10:00:00Z');
            """
        )
        exp_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        conn.execute(
            """
            INSERT INTO postings (transaction_id, account_id, category_id, signed_amount_minor, created_at)
            VALUES (?, 1, 1, -12550, '2026-11-15T10:00:00Z');
            """,
            (exp_id,),
        )

    # Upgrade to Phase 2 migrations
    assert initialize_database(db_path) == [2]

    backups_dir = db_path.parent / "backups"
    backups = list(backups_dir.glob("pre_migration_v1_to_v2_*.sqlite3"))
    assert len(backups) == 1
    assert (backups[0].stat().st_mode & 0o777) == 0o600

    with db_session(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
        total_postings = conn.execute(
            "SELECT COALESCE(SUM(signed_amount_minor), 0) FROM postings;"
        ).fetchone()[0]
        assert total_postings == 487450
        rows = conn.execute(
            "SELECT entry_type, tx_date, description, revision, deleted_at FROM transactions ORDER BY id;"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("income", "2026-11-10", "Stipend", 1, None),
            ("expense", "2026-11-15", "Groceries", 1, None),
        ]
        cash = conn.execute(
            "SELECT opening_balance_date, icon FROM accounts WHERE id = 1;"
        ).fetchone()
        assert len(cash["opening_balance_date"]) == 10
        assert cash["icon"] == "wallet"


@pytest.mark.unit
def test_failed_upgrade_preserves_phase1_db_and_creates_backup(tmp_path: Path) -> None:
    from app.migrations.runner import default_migrations_dir
    from app.utils.errors import DatabaseError

    db_path = tmp_path / "broken_upgrade.sqlite3"
    migs = tmp_path / "migs"
    migs.mkdir()
    src_migs = default_migrations_dir()
    (migs / "0001_initial_schema.sql").write_text(
        (src_migs / "0001_initial_schema.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert initialize_database(db_path, migrations_dir=migs) == [1]

    with db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO transactions (entry_type, tx_date, description, created_at, updated_at)
            VALUES ('expense', '2026-11-12', 'Preserved row', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z');
            """
        )

    (migs / "0002_broken.sql").write_text(
        "ALTER TABLE accounts ADD COLUMN extra TEXT DEFAULT ''; INVALID SQL STATEMENT;",
        encoding="utf-8",
    )
    with pytest.raises(DatabaseError):
        initialize_database(db_path, migrations_dir=migs)

    backups = list((tmp_path / "backups").glob("pre_migration_v1_to_v2_*.sqlite3"))
    assert len(backups) == 1

    with db_session(db_path) as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations;").fetchall()]
        assert versions == [1]
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(accounts);").fetchall()]
        assert "extra" not in cols
        txs = conn.execute("SELECT description FROM transactions;").fetchall()
        assert [r["description"] for r in txs] == ["Preserved row"]
