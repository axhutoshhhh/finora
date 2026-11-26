"""Repository for ledger transactions and postings."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

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

_LOGICAL_AMOUNT_EXPR = (
    "CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) "
    "ELSE ABS(SUM(p.signed_amount_minor)) END"
)

_SORT_SQL: dict[str, str] = {
    "newest": "t.tx_date DESC, t.id DESC",
    "oldest": "t.tx_date ASC, t.id ASC",
    "amount_desc": f"{_LOGICAL_AMOUNT_EXPR} DESC, t.tx_date DESC, t.id DESC",
    "amount_asc": f"{_LOGICAL_AMOUNT_EXPR} ASC, t.tx_date DESC, t.id DESC",
    "merchant_asc": "lower(COALESCE(NULLIF(t.merchant, ''), t.description)) ASC, t.tx_date DESC, t.id DESC",
}


@dataclass(frozen=True)
class TransactionFilter:
    """Validated query filter options for chronological transaction listing."""

    query: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    account_id: int | None = None
    category_id: int | None = None
    entry_type: str | None = None
    payment_method: str | None = None
    tag_id: int | None = None
    min_amount_minor: int | None = None
    max_amount_minor: int | None = None
    deleted_mode: str = "active"  # active | deleted | all
    sort: str = "newest"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    return create_multi_posting_transaction(
        conn,
        entry_type=entry_type,
        tx_date=tx_date,
        description=description,
        merchant=merchant,
        payment_method=payment_method,
        related_transaction_id=related_transaction_id,
        is_split=False,
        idempotency_key=idempotency_key,
        postings=[(account_id, category_id, signed_amount_minor)],
        now=now,
    )


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


def replace_transaction_header_and_postings(
    conn: sqlite3.Connection,
    *,
    transaction_id: int,
    entry_type: str,
    tx_date: str,
    description: str,
    merchant: str,
    payment_method: str,
    is_split: bool,
    postings: list[tuple[int, int | None, int]],
    now: str,
) -> None:
    """Atomically update a transaction header and replace its ledger postings."""
    conn.execute(
        """
        UPDATE transactions
        SET
            entry_type = ?,
            tx_date = ?,
            description = ?,
            merchant = ?,
            payment_method = ?,
            is_split = ?,
            revision = revision + 1,
            updated_at = ?
        WHERE id = ?;
        """,
        (
            entry_type,
            tx_date,
            description,
            merchant,
            payment_method,
            1 if is_split else 0,
            now,
            transaction_id,
        ),
    )
    conn.execute("DELETE FROM postings WHERE transaction_id = ?;", (transaction_id,))
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


def update_single_posting_category_bulk(
    conn: sqlite3.Connection,
    *,
    transaction_ids: list[int],
    category_id: int,
    now: str,
) -> None:
    """Update category_id on compatible single-posting transactions atomically."""
    ids_json = json.dumps(transaction_ids)
    conn.execute(
        """
        UPDATE postings
        SET category_id = ?
        WHERE transaction_id IN (SELECT value FROM json_each(?));
        """,
        (category_id, ids_json),
    )
    conn.execute(
        """
        UPDATE transactions
        SET revision = revision + 1, updated_at = ?
        WHERE id IN (SELECT value FROM json_each(?));
        """,
        (now, ids_json),
    )


def soft_delete_transaction(conn: sqlite3.Connection, *, transaction_id: int, now: str) -> None:
    """Soft-delete a transaction without dropping postings or attachments."""
    conn.execute(
        """
        UPDATE transactions
        SET deleted_at = ?, revision = revision + 1, updated_at = ?
        WHERE id = ?;
        """,
        (now, now, transaction_id),
    )


def restore_transaction(conn: sqlite3.Connection, *, transaction_id: int, now: str) -> None:
    """Restore a soft-deleted transaction back into the active ledger."""
    conn.execute(
        """
        UPDATE transactions
        SET deleted_at = NULL, revision = revision + 1, updated_at = ?
        WHERE id = ?;
        """,
        (now, transaction_id),
    )


def purge_transaction(conn: sqlite3.Connection, *, transaction_id: int) -> None:
    """Permanently delete a soft-deleted transaction (cascades postings/tags/attachment rows)."""
    conn.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))


def get_transaction_rows_by_id(conn: sqlite3.Connection, transaction_id: int) -> list[sqlite3.Row]:
    """Fetch all posting-joined rows for a single transaction ID."""
    return conn.execute(
        f"{_TRANSACTION_SELECT} WHERE t.id = ? ORDER BY p.signed_amount_minor ASC, p.id ASC;",
        (transaction_id,),
    ).fetchall()


def get_transaction_by_id(conn: sqlite3.Connection, transaction_id: int) -> sqlite3.Row | None:
    """Fetch the primary posting-joined row by ID."""
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


def list_active_refund_rows_for_parent(
    conn: sqlite3.Connection,
    parent_transaction_id: int,
    *,
    exclude_refund_id: int | None = None,
) -> list[sqlite3.Row]:
    """Fetch all active refund posting rows linked to an original expense."""
    if exclude_refund_id is not None:
        return conn.execute(
            f"""
            {_TRANSACTION_SELECT}
            WHERE t.entry_type = 'refund'
              AND t.related_transaction_id = ?
              AND t.deleted_at IS NULL
              AND t.id != ?
            ORDER BY t.tx_date DESC, t.id DESC, p.id ASC;
            """,
            (parent_transaction_id, exclude_refund_id),
        ).fetchall()
    return conn.execute(
        f"""
        {_TRANSACTION_SELECT}
        WHERE t.entry_type = 'refund'
          AND t.related_transaction_id = ?
          AND t.deleted_at IS NULL
        ORDER BY t.tx_date DESC, t.id DESC, p.id ASC;
        """,
        (parent_transaction_id,),
    ).fetchall()


def count_active_refunds_for_parent(conn: sqlite3.Connection, parent_transaction_id: int) -> int:
    """Count active refunds linked to an expense."""
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE entry_type = 'refund'
              AND related_transaction_id = ?
              AND deleted_at IS NULL;
            """,
            (parent_transaction_id,),
        ).fetchone()[0]
    )


_SEARCH_COUNT_SQL = """
SELECT COUNT(*) FROM (
    SELECT t.id
    FROM transactions t
    JOIN postings p ON p.transaction_id = t.id
    WHERE
        (
            (:deleted_mode = 'active' AND t.deleted_at IS NULL)
            OR (:deleted_mode = 'deleted' AND t.deleted_at IS NOT NULL)
            OR (:deleted_mode = 'all')
        )
        AND (:date_from IS NULL OR t.tx_date >= :date_from)
        AND (:date_to IS NULL OR t.tx_date <= :date_to)
        AND (:entry_type IS NULL OR t.entry_type = :entry_type)
        AND (:payment_method IS NULL OR t.payment_method = :payment_method)
        AND (
            :account_id IS NULL OR EXISTS (
                SELECT 1 FROM postings p_acc WHERE p_acc.transaction_id = t.id AND p_acc.account_id = :account_id
            )
        )
        AND (
            :category_id IS NULL OR EXISTS (
                SELECT 1 FROM postings p_cat WHERE p_cat.transaction_id = t.id AND p_cat.category_id = :category_id
            )
        )
        AND (
            :tag_id IS NULL OR EXISTS (
                SELECT 1 FROM transaction_tags tt_f WHERE tt_f.transaction_id = t.id AND tt_f.tag_id = :tag_id
            )
        )
        AND (
            :like_term IS NULL OR (
                t.merchant LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                OR t.description LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                OR EXISTS (
                    SELECT 1 FROM postings p_s
                    JOIN accounts a_s ON a_s.id = p_s.account_id
                    LEFT JOIN categories c_s ON c_s.id = p_s.category_id
                    WHERE p_s.transaction_id = t.id
                      AND (
                          a_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                          OR c_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM transaction_tags tt_s
                    JOIN tags tg_s ON tg_s.id = tt_s.tag_id
                    WHERE tt_s.transaction_id = t.id
                      AND tg_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                )
            )
        )
    GROUP BY t.id
    HAVING
        (
            :min_amount_minor IS NULL OR (
                CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
            ) >= :min_amount_minor
        )
        AND (
            :max_amount_minor IS NULL OR (
                CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
            ) <= :max_amount_minor
        )
);
"""

_SEARCH_IDS_SQL = """
SELECT t.id
FROM transactions t
JOIN postings p ON p.transaction_id = t.id
WHERE
    (
        (:deleted_mode = 'active' AND t.deleted_at IS NULL)
        OR (:deleted_mode = 'deleted' AND t.deleted_at IS NOT NULL)
        OR (:deleted_mode = 'all')
    )
    AND (:date_from IS NULL OR t.tx_date >= :date_from)
    AND (:date_to IS NULL OR t.tx_date <= :date_to)
    AND (:entry_type IS NULL OR t.entry_type = :entry_type)
    AND (:payment_method IS NULL OR t.payment_method = :payment_method)
    AND (
        :account_id IS NULL OR EXISTS (
            SELECT 1 FROM postings p_acc WHERE p_acc.transaction_id = t.id AND p_acc.account_id = :account_id
        )
    )
    AND (
        :category_id IS NULL OR EXISTS (
            SELECT 1 FROM postings p_cat WHERE p_cat.transaction_id = t.id AND p_cat.category_id = :category_id
        )
    )
    AND (
        :tag_id IS NULL OR EXISTS (
            SELECT 1 FROM transaction_tags tt_f WHERE tt_f.transaction_id = t.id AND tt_f.tag_id = :tag_id
        )
    )
    AND (
        :like_term IS NULL OR (
            t.merchant LIKE :like_term ESCAPE '\\' COLLATE NOCASE
            OR t.description LIKE :like_term ESCAPE '\\' COLLATE NOCASE
            OR EXISTS (
                SELECT 1 FROM postings p_s
                JOIN accounts a_s ON a_s.id = p_s.account_id
                LEFT JOIN categories c_s ON c_s.id = p_s.category_id
                WHERE p_s.transaction_id = t.id
                  AND (
                      a_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                      OR c_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
                  )
            )
            OR EXISTS (
                SELECT 1 FROM transaction_tags tt_s
                JOIN tags tg_s ON tg_s.id = tt_s.tag_id
                WHERE tt_s.transaction_id = t.id
                  AND tg_s.name LIKE :like_term ESCAPE '\\' COLLATE NOCASE
            )
        )
    )
GROUP BY t.id
HAVING
    (
        :min_amount_minor IS NULL OR (
            CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
        ) >= :min_amount_minor
    )
    AND (
        :max_amount_minor IS NULL OR (
            CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
        ) <= :max_amount_minor
    )
ORDER BY
    CASE WHEN :sort = 'oldest' THEN t.tx_date END ASC,
    CASE WHEN :sort = 'oldest' THEN t.id END ASC,
    CASE WHEN :sort = 'amount_desc' THEN (
        CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
    ) END DESC,
    CASE WHEN :sort = 'amount_asc' THEN (
        CASE WHEN t.entry_type = 'transfer' THEN MAX(ABS(p.signed_amount_minor)) ELSE ABS(SUM(p.signed_amount_minor)) END
    ) END ASC,
    CASE WHEN :sort = 'merchant_asc' THEN lower(COALESCE(NULLIF(t.merchant, ''), t.description)) END ASC,
    t.tx_date DESC,
    t.id DESC
LIMIT :limit OFFSET :offset;
"""

_SELECT_BY_JSON_IDS_SQL = """
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
WHERE t.id IN (SELECT value FROM json_each(?))
ORDER BY p.signed_amount_minor ASC, p.id ASC;
"""


def search_transactions(
    conn: sqlite3.Connection,
    *,
    flt: TransactionFilter,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    """Search, filter, sort, and paginate transactions returning (rows, total_count)."""
    like_term = f"%{_escape_like(flt.query)}%" if flt.query else None
    sort_key = flt.sort if flt.sort in _SORT_SQL else "newest"
    params: dict[str, object] = {
        "deleted_mode": flt.deleted_mode,
        "date_from": flt.date_from,
        "date_to": flt.date_to,
        "entry_type": flt.entry_type,
        "payment_method": flt.payment_method,
        "account_id": flt.account_id,
        "category_id": flt.category_id,
        "tag_id": flt.tag_id,
        "like_term": like_term,
        "min_amount_minor": flt.min_amount_minor,
        "max_amount_minor": flt.max_amount_minor,
        "sort": sort_key,
        "limit": limit,
        "offset": offset,
    }
    total_count = int(conn.execute(_SEARCH_COUNT_SQL, params).fetchone()[0])
    if total_count == 0:
        return [], 0

    id_rows = conn.execute(_SEARCH_IDS_SQL, params).fetchall()
    ids = [int(r["id"]) for r in id_rows]
    if not ids:
        return [], total_count

    order_map = {tx_id: idx for idx, tx_id in enumerate(ids)}
    joined_rows = conn.execute(_SELECT_BY_JSON_IDS_SQL, (json.dumps(ids),)).fetchall()
    joined_rows.sort(key=lambda r: order_map[int(r["id"])])
    return joined_rows, total_count


def list_transactions(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[sqlite3.Row]:
    """List distinct transaction headers cleanly with default newest-first ordering."""
    flt = TransactionFilter(deleted_mode="all" if include_deleted else "active", sort="newest")
    rows, _ = search_transactions(conn, flt=flt, limit=limit, offset=offset)
    return rows


def list_transactions_for_account(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    limit: int = 25,
) -> list[sqlite3.Row]:
    """Return active transactions touching a specific account (including transfers/splits)."""
    flt = TransactionFilter(account_id=account_id, deleted_mode="active", sort="newest")
    rows, _ = search_transactions(conn, flt=flt, limit=limit, offset=0)
    return rows


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
    """Compute (income_minor, gross_expense_minor, refunds_minor) for active entries in range."""
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
