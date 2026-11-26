"""Repository for financial accounts and position aggregations."""

from __future__ import annotations

import sqlite3

_ACCOUNT_WITH_BALANCE_SELECT = """
SELECT
    a.id,
    a.name,
    a.account_type,
    a.opening_balance_minor,
    a.opening_balance_date,
    a.description,
    a.icon,
    a.color_token,
    a.credit_limit_minor,
    a.currency,
    a.is_default,
    a.is_archived,
    a.created_at,
    a.updated_at,
    a.opening_balance_minor + COALESCE(
        (
            SELECT SUM(p.signed_amount_minor)
            FROM postings p
            JOIN transactions t ON t.id = p.transaction_id
            WHERE p.account_id = a.id AND t.deleted_at IS NULL
        ),
        0
    ) AS balance_minor,
    (
        SELECT COUNT(DISTINCT t.id)
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE p.account_id = a.id AND t.deleted_at IS NULL
    ) AS active_transaction_count,
    (
        SELECT COUNT(*)
        FROM postings p
        WHERE p.account_id = a.id
    ) AS total_posting_count
FROM accounts a
"""


def list_accounts_with_balances(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    """Return accounts ordered with default first and active accounts before archived."""
    where_clause = "" if include_archived else "WHERE a.is_archived = 0"
    return conn.execute(
        f"""
        {_ACCOUNT_WITH_BALANCE_SELECT}
        {where_clause}
        ORDER BY a.is_archived ASC, a.is_default DESC, a.id ASC;
        """
    ).fetchall()


def list_active_accounts_with_balances(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return active accounts with authoritative computed balances."""
    return list_accounts_with_balances(conn, include_archived=False)


def get_account_by_id(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    """Fetch a single account row with authoritative balance by primary key."""
    return conn.execute(
        f"{_ACCOUNT_WITH_BALANCE_SELECT} WHERE a.id = ?;",
        (account_id,),
    ).fetchone()


def get_active_account_by_name_ci(
    conn: sqlite3.Connection,
    name: str,
    *,
    exclude_account_id: int | None = None,
) -> sqlite3.Row | None:
    """Check if an active account already exists with the same trimmed case-insensitive name."""
    if exclude_account_id is not None:
        return conn.execute(
            """
            SELECT id, name FROM accounts
            WHERE is_archived = 0 AND lower(trim(name)) = lower(trim(?)) AND id != ?;
            """,
            (name, exclude_account_id),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, name FROM accounts
        WHERE is_archived = 0 AND lower(trim(name)) = lower(trim(?));
        """,
        (name,),
    ).fetchone()


def create_account(
    conn: sqlite3.Connection,
    *,
    name: str,
    account_type: str,
    opening_balance_minor: int,
    opening_balance_date: str,
    description: str,
    icon: str,
    color_token: str,
    credit_limit_minor: int | None,
    currency: str,
    now: str,
) -> int:
    """Insert a new financial account and return its row ID."""
    cursor = conn.execute(
        """
        INSERT INTO accounts (
            name, account_type, opening_balance_minor, opening_balance_date,
            description, icon, color_token, credit_limit_minor,
            currency, is_default, is_archived, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?);
        """,
        (
            name,
            account_type,
            opening_balance_minor,
            opening_balance_date,
            description,
            icon,
            color_token,
            credit_limit_minor,
            currency,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def update_account(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    name: str,
    account_type: str,
    opening_balance_minor: int,
    opening_balance_date: str,
    description: str,
    icon: str,
    color_token: str,
    credit_limit_minor: int | None,
    now: str,
) -> None:
    """Update editable account attributes atomically."""
    conn.execute(
        """
        UPDATE accounts
        SET
            name = ?,
            account_type = ?,
            opening_balance_minor = ?,
            opening_balance_date = ?,
            description = ?,
            icon = ?,
            color_token = ?,
            credit_limit_minor = ?,
            updated_at = ?
        WHERE id = ?;
        """,
        (
            name,
            account_type,
            opening_balance_minor,
            opening_balance_date,
            description,
            icon,
            color_token,
            credit_limit_minor,
            now,
            account_id,
        ),
    )


def set_account_archived(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    archived: bool,
    now: str,
) -> None:
    """Mark an account as archived or restored, shifting default if needed."""
    conn.execute(
        "UPDATE accounts SET is_archived = ?, updated_at = ? WHERE id = ?;",
        (1 if archived else 0, now, account_id),
    )


def reassign_default_account(conn: sqlite3.Connection, new_default_id: int, now: str) -> None:
    """Move is_default = 1 cleanly to another active account."""
    conn.execute("UPDATE accounts SET is_default = 0, updated_at = ? WHERE is_default = 1;", (now,))
    conn.execute(
        "UPDATE accounts SET is_default = 1, updated_at = ? WHERE id = ?;", (now, new_default_id)
    )


def count_active_accounts(conn: sqlite3.Connection) -> int:
    """Return number of non-archived accounts."""
    return int(conn.execute("SELECT COUNT(*) FROM accounts WHERE is_archived = 0;").fetchone()[0])


def get_account_activity_totals(
    conn: sqlite3.Connection, account_id: int
) -> tuple[int, int, int, int]:
    """Return (income_minor, gross_expense_minor, refunds_minor, net_transfers_minor) for account."""
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN t.entry_type = 'income' THEN p.signed_amount_minor ELSE 0 END), 0) AS income_minor,
            COALESCE(SUM(CASE WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor ELSE 0 END), 0) AS expense_minor,
            COALESCE(SUM(CASE WHEN t.entry_type = 'refund' THEN p.signed_amount_minor ELSE 0 END), 0) AS refund_minor,
            COALESCE(SUM(CASE WHEN t.entry_type = 'transfer' THEN p.signed_amount_minor ELSE 0 END), 0) AS net_transfer_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE p.account_id = ? AND t.deleted_at IS NULL;
        """,
        (account_id,),
    ).fetchone()
    return (
        int(row["income_minor"]),
        int(row["expense_minor"]),
        int(row["refund_minor"]),
        int(row["net_transfer_minor"]),
    )


def get_total_balance_minor(conn: sqlite3.Connection) -> int:
    """Compute net financial position across all accounts (compatible with Phase 1 Cash asset sum)."""
    rows = list_accounts_with_balances(conn, include_archived=True)
    return sum(int(r["balance_minor"]) for r in rows)
