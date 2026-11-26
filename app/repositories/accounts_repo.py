"""Repository for financial accounts."""

from __future__ import annotations

import sqlite3


def list_active_accounts_with_balances(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return active accounts ordered with default first and computed balances."""
    return conn.execute(
        """
        SELECT
            a.id,
            a.name,
            a.account_type,
            a.opening_balance_minor,
            a.currency,
            a.is_default,
            a.is_archived,
            a.created_at,
            a.updated_at,
            a.opening_balance_minor + COALESCE(
                (
                    SELECT SUM(p.signed_amount_minor)
                    FROM postings p
                    WHERE p.account_id = a.id
                ),
                0
            ) AS balance_minor
        FROM accounts a
        WHERE a.is_archived = 0
        ORDER BY a.is_default DESC, a.id ASC;
        """
    ).fetchall()


def get_account_by_id(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    """Fetch a single account row by primary key."""
    return conn.execute(
        """
        SELECT
            id,
            name,
            account_type,
            opening_balance_minor,
            currency,
            is_default,
            is_archived,
            created_at,
            updated_at
        FROM accounts
        WHERE id = ?;
        """,
        (account_id,),
    ).fetchone()


def get_total_balance_minor(conn: sqlite3.Connection) -> int:
    """Compute total balance across all non-archived accounts in minor units."""
    opening_sum = conn.execute(
        "SELECT COALESCE(SUM(opening_balance_minor), 0) FROM accounts WHERE is_archived = 0;"
    ).fetchone()[0]
    postings_sum = conn.execute(
        """
        SELECT COALESCE(SUM(p.signed_amount_minor), 0)
        FROM postings p
        JOIN accounts a ON a.id = p.account_id
        WHERE a.is_archived = 0;
        """
    ).fetchone()[0]
    return int(opening_sum) + int(postings_sum)
