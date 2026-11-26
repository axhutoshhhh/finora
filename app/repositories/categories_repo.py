"""Repository for financial categories."""

from __future__ import annotations

import sqlite3


def list_active_categories(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
) -> list[sqlite3.Row]:
    """Return active categories ordered deterministically."""
    if kind is not None:
        return conn.execute(
            """
            SELECT id, slug, name, kind, icon, color_token, sort_order, is_system
            FROM categories
            WHERE is_archived = 0 AND kind = ?
            ORDER BY sort_order ASC, id ASC;
            """,
            (kind,),
        ).fetchall()
    return conn.execute(
        """
        SELECT id, slug, name, kind, icon, color_token, sort_order, is_system
        FROM categories
        WHERE is_archived = 0
        ORDER BY kind ASC, sort_order ASC, id ASC;
        """
    ).fetchall()


def get_category_by_id(conn: sqlite3.Connection, category_id: int) -> sqlite3.Row | None:
    """Fetch a single category by primary key."""
    return conn.execute(
        """
        SELECT id, slug, name, kind, icon, color_token, sort_order, is_system, is_archived
        FROM categories
        WHERE id = ?;
        """,
        (category_id,),
    ).fetchone()
