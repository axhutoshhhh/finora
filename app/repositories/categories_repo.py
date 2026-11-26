"""Repository for expense and income categories."""

from __future__ import annotations

import sqlite3


def list_categories(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    include_archived: bool = False,
) -> list[sqlite3.Row]:
    """Return categories with active transaction counts ordered deterministically."""
    if kind is not None and include_archived:
        return conn.execute(
            """
            SELECT
                c.id, c.slug, c.name, c.kind, c.icon, c.color_token,
                c.sort_order, c.is_system, c.is_archived, c.created_at,
                COUNT(DISTINCT CASE WHEN t.deleted_at IS NULL THEN t.id END) AS transaction_count
            FROM categories c
            LEFT JOIN postings p ON p.category_id = c.id
            LEFT JOIN transactions t ON t.id = p.transaction_id
            WHERE c.kind = ?
            GROUP BY c.id
            ORDER BY c.is_archived ASC, c.sort_order ASC, c.id ASC;
            """,
            (kind,),
        ).fetchall()
    if kind is not None:
        return conn.execute(
            """
            SELECT
                c.id, c.slug, c.name, c.kind, c.icon, c.color_token,
                c.sort_order, c.is_system, c.is_archived, c.created_at,
                COUNT(DISTINCT CASE WHEN t.deleted_at IS NULL THEN t.id END) AS transaction_count
            FROM categories c
            LEFT JOIN postings p ON p.category_id = c.id
            LEFT JOIN transactions t ON t.id = p.transaction_id
            WHERE c.is_archived = 0 AND c.kind = ?
            GROUP BY c.id
            ORDER BY c.sort_order ASC, c.id ASC;
            """,
            (kind,),
        ).fetchall()
    if include_archived:
        return conn.execute(
            """
            SELECT
                c.id, c.slug, c.name, c.kind, c.icon, c.color_token,
                c.sort_order, c.is_system, c.is_archived, c.created_at,
                COUNT(DISTINCT CASE WHEN t.deleted_at IS NULL THEN t.id END) AS transaction_count
            FROM categories c
            LEFT JOIN postings p ON p.category_id = c.id
            LEFT JOIN transactions t ON t.id = p.transaction_id
            GROUP BY c.id
            ORDER BY c.kind ASC, c.is_archived ASC, c.sort_order ASC, c.id ASC;
            """
        ).fetchall()
    return conn.execute(
        """
        SELECT
            c.id, c.slug, c.name, c.kind, c.icon, c.color_token,
            c.sort_order, c.is_system, c.is_archived, c.created_at,
            COUNT(DISTINCT CASE WHEN t.deleted_at IS NULL THEN t.id END) AS transaction_count
        FROM categories c
        LEFT JOIN postings p ON p.category_id = c.id
        LEFT JOIN transactions t ON t.id = p.transaction_id
        WHERE c.is_archived = 0
        GROUP BY c.id
        ORDER BY c.kind ASC, c.sort_order ASC, c.id ASC;
        """
    ).fetchall()


def list_active_categories(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Return active categories ordered deterministically."""
    return list_categories(conn, kind=kind, include_archived=False)


def get_category_by_id(conn: sqlite3.Connection, category_id: int) -> sqlite3.Row | None:
    """Fetch a single category by primary key."""
    return conn.execute(
        """
        SELECT id, slug, name, kind, icon, color_token, sort_order, is_system, is_archived, created_at
        FROM categories
        WHERE id = ?;
        """,
        (category_id,),
    ).fetchone()


def get_active_category_by_name_ci(
    conn: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    exclude_category_id: int | None = None,
) -> sqlite3.Row | None:
    """Find an active category matching kind and trimmed case-insensitive name."""
    if exclude_category_id is not None:
        return conn.execute(
            """
            SELECT id, name FROM categories
            WHERE is_archived = 0 AND kind = ? AND lower(trim(name)) = lower(trim(?)) AND id != ?;
            """,
            (kind, name, exclude_category_id),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, name FROM categories
        WHERE is_archived = 0 AND kind = ? AND lower(trim(name)) = lower(trim(?));
        """,
        (kind, name),
    ).fetchone()


def get_next_sort_order(conn: sqlite3.Connection, kind: str) -> int:
    """Return next display sort_order for a category kind."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM categories WHERE kind = ?;",
        (kind,),
    ).fetchone()
    return int(row[0])


def count_active_categories_of_kind(conn: sqlite3.Connection, kind: str) -> int:
    """Count non-archived categories for one classification."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM categories WHERE kind = ? AND is_archived = 0;",
            (kind,),
        ).fetchone()[0]
    )


def create_category(
    conn: sqlite3.Connection,
    *,
    slug: str,
    name: str,
    kind: str,
    icon: str,
    color_token: str,
    sort_order: int,
    now: str,
) -> int:
    """Insert a custom expense or income category."""
    cursor = conn.execute(
        """
        INSERT INTO categories (
            slug, name, kind, icon, color_token, sort_order, is_system, is_archived, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?);
        """,
        (slug, name, kind, icon, color_token, sort_order, now),
    )
    return int(cursor.lastrowid)


def update_category(
    conn: sqlite3.Connection,
    *,
    category_id: int,
    name: str,
    icon: str,
    color_token: str,
    sort_order: int,
) -> None:
    """Update editable category display fields while keeping slug and kind stable."""
    conn.execute(
        """
        UPDATE categories
        SET name = ?, icon = ?, color_token = ?, sort_order = ?
        WHERE id = ?;
        """,
        (name, icon, color_token, sort_order, category_id),
    )


def set_category_archived(conn: sqlite3.Connection, *, category_id: int, archived: bool) -> None:
    """Archive or restore a category."""
    conn.execute(
        "UPDATE categories SET is_archived = ? WHERE id = ?;",
        (1 if archived else 0, category_id),
    )
