"""Repository for monthly category budgets, overall limits, and spend aggregation."""

from __future__ import annotations

import sqlite3


def list_category_budgets_up_to_month(
    conn: sqlite3.Connection,
    *,
    min_month: str,
    max_month: str,
) -> list[sqlite3.Row]:
    """Return configured category budgets in [min_month, max_month] inclusive."""
    return conn.execute(
        """
        SELECT
            cb.id, cb.category_id, cb.month, cb.limit_minor, cb.rollover_enabled,
            cb.created_at, cb.updated_at
        FROM category_budgets cb
        WHERE cb.month >= ? AND cb.month <= ?
        ORDER BY cb.month ASC, cb.category_id ASC;
        """,
        (min_month, max_month),
    ).fetchall()


def get_overall_budget(conn: sqlite3.Connection, month: str) -> sqlite3.Row | None:
    """Fetch the independent overall monthly spending cap if configured."""
    return conn.execute(
        "SELECT month, limit_minor, created_at, updated_at FROM overall_budgets WHERE month = ?;",
        (month,),
    ).fetchone()


def upsert_category_budget(
    conn: sqlite3.Connection,
    *,
    category_id: int,
    month: str,
    limit_minor: int,
    rollover_enabled: bool,
    now: str,
) -> int:
    """Create or update a monthly category budget atomically."""
    conn.execute(
        """
        INSERT INTO category_budgets (
            category_id, month, limit_minor, rollover_enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(category_id, month) DO UPDATE SET
            limit_minor = excluded.limit_minor,
            rollover_enabled = excluded.rollover_enabled,
            updated_at = excluded.updated_at;
        """,
        (category_id, month, limit_minor, 1 if rollover_enabled else 0, now, now),
    )
    row = conn.execute(
        "SELECT id FROM category_budgets WHERE category_id = ? AND month = ?;",
        (category_id, month),
    ).fetchone()
    return int(row["id"])


def delete_category_budget(conn: sqlite3.Connection, *, category_id: int, month: str) -> int:
    """Remove a category budget for a specific month; returns deleted row count."""
    cursor = conn.execute(
        "DELETE FROM category_budgets WHERE category_id = ? AND month = ?;",
        (category_id, month),
    )
    return int(cursor.rowcount)


def upsert_overall_budget(
    conn: sqlite3.Connection,
    *,
    month: str,
    limit_minor: int,
    now: str,
) -> None:
    """Create or update an overall monthly spending limit."""
    conn.execute(
        """
        INSERT INTO overall_budgets (month, limit_minor, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(month) DO UPDATE SET
            limit_minor = excluded.limit_minor,
            updated_at = excluded.updated_at;
        """,
        (month, limit_minor, now, now),
    )


def delete_overall_budget(conn: sqlite3.Connection, *, month: str) -> int:
    """Delete an overall monthly spending limit; returns deleted row count."""
    cursor = conn.execute("DELETE FROM overall_budgets WHERE month = ?;", (month,))
    return int(cursor.rowcount)


def get_category_monthly_spend_map(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date_exclusive: str,
) -> dict[tuple[str, int], tuple[int, int]]:
    """Return {(month_yyyy_mm, category_id): (gross_expense_minor, refunds_minor)} for active entries."""
    rows = conn.execute(
        """
        SELECT
            substr(t.tx_date, 1, 7) AS month_key,
            p.category_id,
            COALESCE(SUM(CASE WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor ELSE 0 END), 0) AS gross_minor,
            COALESCE(SUM(CASE WHEN t.entry_type = 'refund' THEN p.signed_amount_minor ELSE 0 END), 0) AS refund_minor
        FROM transactions t
        JOIN postings p ON p.transaction_id = t.id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('expense', 'refund')
          AND p.category_id IS NOT NULL
          AND t.tx_date >= ?
          AND t.tx_date < ?
        GROUP BY substr(t.tx_date, 1, 7), p.category_id;
        """,
        (start_date, end_date_exclusive),
    ).fetchall()
    return {
        (str(r["month_key"]), int(r["category_id"])): (
            int(r["gross_minor"]),
            int(r["refund_minor"]),
        )
        for r in rows
    }


def list_configured_categories_with_archive(
    conn: sqlite3.Connection, month: str
) -> list[sqlite3.Row]:
    """Return category_budgets joined with category metadata for one month."""
    return conn.execute(
        """
        SELECT
            cb.id, cb.category_id, cb.limit_minor, cb.rollover_enabled,
            c.name AS category_name, c.slug AS category_slug,
            c.icon AS category_icon, c.color_token AS category_color_token,
            c.is_archived AS category_is_archived
        FROM category_budgets cb
        JOIN categories c ON c.id = cb.category_id
        WHERE cb.month = ? AND c.kind = 'expense'
        ORDER BY c.sort_order ASC, c.id ASC;
        """,
        (month,),
    ).fetchall()
