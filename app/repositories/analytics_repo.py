"""Parameterized SQLite aggregation queries for Phase 3 analytics & reporting."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _json_list(values: list[int] | None) -> str:
    return json.dumps(values or [])


def get_period_totals(
    conn: sqlite3.Connection,
    *,
    start_date: str | None,
    end_date: str | None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
) -> dict[str, int]:
    """Return exact integer minor-unit totals for income, gross_expense, and refund."""
    acct_json = _json_list(account_ids)
    cat_json = _json_list(category_ids)
    has_accts = 1 if account_ids else 0
    has_cats = 1 if category_ids else 0
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'income' THEN p.signed_amount_minor
                ELSE 0
            END), 0) AS income_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor
                ELSE 0
            END), 0) AS gross_expense_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'refund' THEN p.signed_amount_minor
                ELSE 0
            END), 0) AS refund_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('income', 'expense', 'refund')
          AND (? IS NULL OR t.tx_date >= ?)
          AND (? IS NULL OR t.tx_date <= ?)
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
          AND (? = 0 OR p.category_id IN (SELECT value FROM json_each(?)));
        """,
        (start_date, start_date, end_date, end_date, has_accts, acct_json, has_cats, cat_json),
    ).fetchone()
    return {
        "income_minor": int(row["income_minor"]),
        "gross_expense_minor": int(row["gross_expense_minor"]),
        "refund_minor": int(row["refund_minor"]),
    }


def get_monthly_series(
    conn: sqlite3.Connection,
    *,
    start_date: str | None,
    end_date: str | None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return monthly income, gross expense, refund, and net expense."""
    acct_json = _json_list(account_ids)
    cat_json = _json_list(category_ids)
    has_accts = 1 if account_ids else 0
    has_cats = 1 if category_ids else 0
    rows = conn.execute(
        """
        SELECT
            substr(t.tx_date, 1, 7) AS month,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'income' THEN p.signed_amount_minor ELSE 0
            END), 0) AS income_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor ELSE 0
            END), 0) AS gross_expense_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'refund' THEN p.signed_amount_minor ELSE 0
            END), 0) AS refund_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('income', 'expense', 'refund')
          AND (? IS NULL OR t.tx_date >= ?)
          AND (? IS NULL OR t.tx_date <= ?)
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
          AND (? = 0 OR p.category_id IN (SELECT value FROM json_each(?)))
        GROUP BY substr(t.tx_date, 1, 7)
        ORDER BY month ASC;
        """,
        (start_date, start_date, end_date, end_date, has_accts, acct_json, has_cats, cat_json),
    ).fetchall()
    return [dict(r) for r in rows]


def get_category_breakdown(
    conn: sqlite3.Connection,
    *,
    start_date: str | None,
    end_date: str | None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return per-category gross spending, refunds, and net spending."""
    acct_json = _json_list(account_ids)
    cat_json = _json_list(category_ids)
    has_accts = 1 if account_ids else 0
    has_cats = 1 if category_ids else 0
    rows = conn.execute(
        """
        SELECT
            c.id AS category_id,
            c.name AS category_name,
            c.slug AS category_slug,
            c.color_token AS color_token,
            c.is_archived AS is_archived,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor ELSE 0
            END), 0) AS gross_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'refund' THEN p.signed_amount_minor ELSE 0
            END), 0) AS refund_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        JOIN categories c ON c.id = p.category_id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('expense', 'refund')
          AND c.kind = 'expense'
          AND (? IS NULL OR t.tx_date >= ?)
          AND (? IS NULL OR t.tx_date <= ?)
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
          AND (? = 0 OR p.category_id IN (SELECT value FROM json_each(?)))
        GROUP BY c.id
        ORDER BY (gross_minor - refund_minor) DESC, c.name ASC;
        """,
        (start_date, start_date, end_date, end_date, has_accts, acct_json, has_cats, cat_json),
    ).fetchall()
    return [dict(r) for r in rows]


def get_top_merchants(
    conn: sqlite3.Connection,
    *,
    start_date: str | None,
    end_date: str | None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return top spending merchants (net of refunds) for non-empty merchants."""
    acct_json = _json_list(account_ids)
    cat_json = _json_list(category_ids)
    has_accts = 1 if account_ids else 0
    has_cats = 1 if category_ids else 0
    rows = conn.execute(
        """
        SELECT
            TRIM(t.merchant) AS merchant,
            COUNT(DISTINCT t.id) AS tx_count,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor
                WHEN t.entry_type = 'refund' THEN -p.signed_amount_minor
                ELSE 0
            END), 0) AS net_spend_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('expense', 'refund')
          AND length(trim(t.merchant)) > 0
          AND (? IS NULL OR t.tx_date >= ?)
          AND (? IS NULL OR t.tx_date <= ?)
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
          AND (? = 0 OR p.category_id IN (SELECT value FROM json_each(?)))
        GROUP BY LOWER(TRIM(t.merchant))
        HAVING net_spend_minor > 0
        ORDER BY net_spend_minor DESC, merchant ASC
        LIMIT ?;
        """,
        (
            start_date,
            start_date,
            end_date,
            end_date,
            has_accts,
            acct_json,
            has_cats,
            cat_json,
            limit,
        ),
    ).fetchall()
    return [dict(r) for r in rows]


def get_daily_activity(
    conn: sqlite3.Connection,
    *,
    start_date: str | None,
    end_date: str | None,
    account_ids: list[int] | None = None,
    category_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return daily net expense, income, and transaction count."""
    acct_json = _json_list(account_ids)
    cat_json = _json_list(category_ids)
    has_accts = 1 if account_ids else 0
    has_cats = 1 if category_ids else 0
    rows = conn.execute(
        """
        SELECT
            t.tx_date AS date,
            COUNT(DISTINCT t.id) AS tx_count,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'income' THEN p.signed_amount_minor ELSE 0
            END), 0) AS income_minor,
            COALESCE(SUM(CASE
                WHEN t.entry_type = 'expense' THEN -p.signed_amount_minor
                WHEN t.entry_type = 'refund' THEN -p.signed_amount_minor
                ELSE 0
            END), 0) AS net_expense_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.deleted_at IS NULL
          AND t.entry_type IN ('income', 'expense', 'refund')
          AND (? IS NULL OR t.tx_date >= ?)
          AND (? IS NULL OR t.tx_date <= ?)
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
          AND (? = 0 OR p.category_id IN (SELECT value FROM json_each(?)))
        GROUP BY t.tx_date
        ORDER BY t.tx_date ASC;
        """,
        (start_date, start_date, end_date, end_date, has_accts, acct_json, has_cats, cat_json),
    ).fetchall()
    return [dict(r) for r in rows]


def get_account_balance_deltas_by_month(
    conn: sqlite3.Connection,
    *,
    account_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return monthly posting deltas per account for historical balance reconstruction."""
    acct_json = _json_list(account_ids)
    has_accts = 1 if account_ids else 0
    rows = conn.execute(
        """
        SELECT
            p.account_id AS account_id,
            substr(t.tx_date, 1, 7) AS month,
            COALESCE(SUM(p.signed_amount_minor), 0) AS delta_minor
        FROM postings p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.deleted_at IS NULL
          AND (? = 0 OR p.account_id IN (SELECT value FROM json_each(?)))
        GROUP BY p.account_id, substr(t.tx_date, 1, 7)
        ORDER BY month ASC;
        """,
        (has_accts, acct_json),
    ).fetchall()
    return [dict(r) for r in rows]
