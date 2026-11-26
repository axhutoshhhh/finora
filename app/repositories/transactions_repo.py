"""Repository for ledger transactions and postings."""

from __future__ import annotations

import sqlite3

_TRANSACTION_SELECT = """
SELECT
    t.id,
    t.entry_type,
    t.tx_date,
    t.description,
    t.merchant,
    t.payment_method,
    t.related_transaction_id,
    t.is_split,
    t.revision,
    t.deleted_at,
    t.idempotency_key,
    t.created_at,
    t.updated_at,
    p.id AS posting_id,
    p.account_id,
    a.name AS account_name,
    a.account_type AS account_type,
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
    merchant: str = "",
    payment_method: str = "other",
    related_transaction_id: int | None = None,
    idempotency_key: str | None,
    account_id: int,
    category_id: int | None,
    signed_amount_minor: int,
    now: str,
) -> int:
    """Insert a transaction header and its single ledger posting atomically."""
    cursor = conn.execute(
        """
        INSERT INTO transactions (
            entry_type, tx_date, description, merchant, payment_method,
            related_transaction_id, is_split, revision, deleted_at,
            idempotency_key, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, 1, NULL, ?, ?, ?);
        """,
        (
            entry_type,
            tx_date,
            description,
            merchant,
            payment_method,
            related_transaction_id,
            idempotency_key,
            now,
            now,
        ),
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


def create_multi_posting_transaction(
    conn: sqlite3.Connection,
    *,
    entry_type: str,
    tx_date: str,
    description: str,
    merchant: str = "",
    payment_method: str = "other",
    related_transaction_id: int | None = None,
    is_split: bool = False,
    idempotency_key: str | None = None,
    postings: list[tuple[int, int | None, int]],
    now: str,
) -> int:
    """Insert a transaction header and N ledger postings inside the caller's transaction."""
    cursor = conn.execute(
        """
        INSERT INTO transactions (
            entry_type, tx_date, description, merchant, payment_method,
            related_transaction_id, is_split, revision, deleted_at,
            idempotency_key, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?);
        """,
        (
            entry_type,
            tx_date,
            description,
            merchant,
            payment_method,
            related_transaction_id,
            1 if is_split else 0,
            idempotency_key,
            now,
            now,
        ),
    )
    transaction_id = int(cursor.lastrowid)
    for account_id, category_id, signed_amount_minor in postings:
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


def get_transaction_rows_by_id(conn: sqlite3.Connection, transaction_id: int) -> list[sqlite3.Row]:
    """Fetch all posting-joined rows for a single transaction ID."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.id = ? ORDER BY p.signed_amount_minor ASC, p.id ASC;",
        (transaction_id,),
    ).fetchall()


def get_transaction_by_id(conn: sqlite3.Connection, transaction_id: int) -> sqlite3.Row | None:
    """Fetch the primary posting-joined row by ID (compatible with single-posting callers)."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.id = ? ORDER BY p.id ASC LIMIT 1;",
        (transaction_id,),
    ).fetchone()


def get_transaction_rows_by_idempotency_key(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> list[sqlite3.Row]:
    """Fetch all rows matching an idempotency key."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.idempotency_key = ? ORDER BY p.signed_amount_minor ASC, p.id ASC;",
        (idempotency_key,),
    ).fetchall()


def get_transaction_by_idempotency_key(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> sqlite3.Row | None:
    """Fetch primary row by client idempotency key."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.idempotency_key = ? ORDER BY p.id ASC LIMIT 1;",
        (idempotency_key,),
    ).fetchone()


def list_transactions(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[sqlite3.Row]:
    """List distinct active transaction headers + representative rows cleanly."""
    if include_deleted:
        id_rows = conn.execute(
            """
            SELECT t.id
            FROM transactions t
            ORDER BY t.tx_date DESC, t.id DESC
            LIMIT ? OFFSET ?;
            """,
            (limit, offset),
        ).fetchall()
    else:
        id_rows = conn.execute(
            """
            SELECT t.id
            FROM transactions t
            WHERE t.deleted_at IS NULL
            ORDER BY t.tx_date DESC, t.id DESC
            LIMIT ? OFFSET ?;
            """,
            (limit, offset),
        ).fetchall()
    ids = [int(r["id"]) for r in id_rows]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(  # noqa: S608 - placeholders are '?' literals only
        f"""
        {_TRANSACTION_SELECT}
        WHERE t.id IN ({placeholders})
        ORDER BY t.tx_date DESC, t.id DESC, p.signed_amount_minor ASC, p.id ASC;
        """,
        tuple(ids),
    ).fetchall()


def list_transactions_for_account(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    limit: int = 25,
) -> list[sqlite3.Row]:
    """Return active transactions touching a specific account (including transfers/splits)."""
    ids = [
        int(r["id"])
        for r in conn.execute(
            """
            SELECT DISTINCT t.id
            FROM transactions t
            JOIN postings p ON p.transaction_id = t.id
            WHERE p.account_id = ? AND t.deleted_at IS NULL
            ORDER BY t.tx_date DESC, t.id DESC
            LIMIT ?;
            """,
            (account_id, limit),
        ).fetchall()
    ]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(  # noqa: S608 - placeholders are '?' literals only
        f"""
        {_TRANSACTION_SELECT}
        WHERE t.id IN ({placeholders})
        ORDER BY t.tx_date DESC, t.id DESC, p.signed_amount_minor ASC, p.id ASC;
        """,
        tuple(ids),
    ).fetchall()


def count_transactions(
    conn: sqlite3.Connection,
    *,
    include_deleted: bool = False,
) -> int:
    """Return count of recorded active (or all) transactions."""
    if include_deleted:
        return int(conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0])
    return int(
        conn.execute("SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL;").fetchone()[0]
    )


def get_month_summary_detailed(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date_exclusive: str,
) -> tuple[int, int, int]:
    """Compute (income_minor, gross_expense_minor, refunds_minor) for active entries in half-open range."""
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
            ) AS gross_expense_minor,
            COALESCE(
                SUM(CASE WHEN t.entry_type = 'refund' THEN p.signed_amount_minor ELSE 0 END),
                0
            ) AS refunds_minor
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        WHERE t.deleted_at IS NULL AND t.tx_date >= ? AND t.tx_date < ?;
        """,
        (start_date, end_date_exclusive),
    ).fetchone()
    return int(row["income_minor"]), int(row["gross_expense_minor"]), int(row["refunds_minor"])


def get_month_summary(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date_exclusive: str,
) -> tuple[int, int]:
    """Compute (income_minor, net_expense_minor) for half-open range."""
    income_minor, gross_expense_minor, refunds_minor = get_month_summary_detailed(
        conn, start_date=start_date, end_date_exclusive=end_date_exclusive
    )
    return income_minor, gross_expense_minor - refunds_minor
