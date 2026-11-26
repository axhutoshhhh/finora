"""Repository for ledger transactions and postings."""

from __future__ import annotations

import sqlite3

_TRANSACTION_SELECT = """
SELECT
    t.id,
    t.entry_type,
    t.tx_date,
    t.description,
    t.idempotency_key,
    t.created_at,
    t.updated_at,
    p.account_id,
    a.name AS account_name,
    a.currency AS currency,
    p.category_id,
    c.name AS category_name,
    c.slug AS category_slug,
    c.icon AS category_icon,
    c.color_token AS category_color_token,
    p.signed_amount_minor
FROM transactions t
JOIN postings p ON p.transaction_id = t.id
JOIN accounts a ON a.id = p.account_id
LEFT JOIN categories c ON c.id = p.category_id
"""


def create_single_posting_transaction(
    conn: sqlite3.Connection,
    *,
    entry_type: str,
    tx_date: str,
    description: str,
    idempotency_key: str | None,
    account_id: int,
    category_id: int,
    signed_amount_minor: int,
    now: str,
) -> int:
    """Insert a transaction header and its single ledger posting atomically."""
    cursor = conn.execute(
        """
        INSERT INTO transactions (
            entry_type, tx_date, description, idempotency_key, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (entry_type, tx_date, description, idempotency_key, now, now),
    )
    transaction_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO postings (
            transaction_id, account_id, category_id, signed_amount_minor, created_at
        )
        VALUES (?, ?, ?, ?, ?);
        """,
        (transaction_id, account_id, category_id, signed_amount_minor, now),
    )
    return transaction_id


def get_transaction_by_id(conn: sqlite3.Connection, transaction_id: int) -> sqlite3.Row | None:
    """Fetch a single joined transaction row by ID."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.id = ?;",
        (transaction_id,),
    ).fetchone()


def get_transaction_by_idempotency_key(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> sqlite3.Row | None:
    """Fetch a transaction by its client idempotency key."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.idempotency_key = ?;",
        (idempotency_key,),
    ).fetchone()


def list_transactions(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """List transactions ordered newest transaction date and ID first."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} ORDER BY t.tx_date DESC, t.id DESC LIMIT ? OFFSET ?;",
        (limit, offset),
    ).fetchall()


def count_transactions(conn: sqlite3.Connection) -> int:
    """Return total count of recorded transactions."""
    return int(conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0])


def get_month_summary(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date_exclusive: str,
) -> tuple[int, int]:
    """Compute (income_minor, expense_minor) for the half-open date range."""
    row = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(CASE WHEN t.entry_type = 'income' THEN p.signed_amount_minor ELSE 0 END),
                0
            ) AS income_minor,
            COALESCE(
                SUM(CASE WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor ELSE 0 END),
                0
            ) AS expense_minor
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        WHERE t.tx_date >= ? AND t.tx_date < ?;
        """,
        (start_date, end_date_exclusive),
    ).fetchone()
    return int(row["income_minor"]), int(row["expense_minor"])
