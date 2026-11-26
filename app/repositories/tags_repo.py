"""Repository for user-defined transaction tags and transaction-tag associations."""

from __future__ import annotations

import json
import sqlite3


def list_tags(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all tags with active transaction usage counts ordered alphabetically."""
    return conn.execute(
        """
        SELECT
            tg.id,
            tg.name,
            tg.created_at,
            tg.updated_at,
            COUNT(t.id) AS transaction_count
        FROM tags tg
        LEFT JOIN transaction_tags tt ON tt.tag_id = tg.id
        LEFT JOIN transactions t ON t.id = tt.transaction_id AND t.deleted_at IS NULL
        GROUP BY tg.id
        ORDER BY lower(tg.name) ASC, tg.id ASC;
        """
    ).fetchall()


def get_tag_by_id(conn: sqlite3.Connection, tag_id: int) -> sqlite3.Row | None:
    """Fetch a single tag by primary key."""
    return conn.execute(
        "SELECT id, name, created_at, updated_at FROM tags WHERE id = ?;",
        (tag_id,),
    ).fetchone()


def get_tag_by_name_ci(
    conn: sqlite3.Connection,
    name: str,
    *,
    exclude_tag_id: int | None = None,
) -> sqlite3.Row | None:
    """Find an existing tag using case-insensitive trimmed matching."""
    if exclude_tag_id is not None:
        return conn.execute(
            "SELECT id, name FROM tags WHERE lower(trim(name)) = lower(trim(?)) AND id != ?;",
            (name, exclude_tag_id),
        ).fetchone()
    return conn.execute(
        "SELECT id, name FROM tags WHERE lower(trim(name)) = lower(trim(?));",
        (name,),
    ).fetchone()


def create_tag(conn: sqlite3.Connection, *, name: str, now: str) -> int:
    """Insert a new tag and return its primary key."""
    cursor = conn.execute(
        "INSERT INTO tags (name, created_at, updated_at) VALUES (?, ?, ?);",
        (name, now, now),
    )
    return int(cursor.lastrowid)


def rename_tag(conn: sqlite3.Connection, *, tag_id: int, name: str, now: str) -> None:
    """Update a tag's display name."""
    conn.execute(
        "UPDATE tags SET name = ?, updated_at = ? WHERE id = ?;",
        (name, now, tag_id),
    )


def delete_tag(conn: sqlite3.Connection, *, tag_id: int) -> None:
    """Delete a tag cleanly without deleting any transactions."""
    conn.execute("DELETE FROM tags WHERE id = ?;", (tag_id,))


def set_transaction_tags(
    conn: sqlite3.Connection,
    *,
    transaction_id: int,
    tag_ids: list[int],
    now: str,
) -> None:
    """Replace all tag associations for a transaction."""
    conn.execute("DELETE FROM transaction_tags WHERE transaction_id = ?;", (transaction_id,))
    for tag_id in tag_ids:
        conn.execute(
            """
            INSERT INTO transaction_tags (transaction_id, tag_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(transaction_id, tag_id) DO NOTHING;
            """,
            (transaction_id, tag_id, now),
        )


def attach_tag_to_transaction(
    conn: sqlite3.Connection,
    *,
    transaction_id: int,
    tag_id: int,
    now: str,
) -> None:
    """Attach a tag to a transaction without creating duplicates."""
    conn.execute(
        """
        INSERT INTO transaction_tags (transaction_id, tag_id, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(transaction_id, tag_id) DO NOTHING;
        """,
        (transaction_id, tag_id, now),
    )


def get_tags_for_transactions(
    conn: sqlite3.Connection, transaction_ids: list[int]
) -> dict[int, list[dict[str, object]]]:
    """Batch-load tags keyed by transaction_id."""
    if not transaction_ids:
        return {}
    rows = conn.execute(
        """
        SELECT tt.transaction_id, tg.id, tg.name
        FROM transaction_tags tt
        JOIN tags tg ON tg.id = tt.tag_id
        WHERE tt.transaction_id IN (SELECT value FROM json_each(?))
        ORDER BY lower(tg.name) ASC, tg.id ASC;
        """,
        (json.dumps(transaction_ids),),
    ).fetchall()
    mapping: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        tx_id = int(row["transaction_id"])
        mapping.setdefault(tx_id, []).append({"id": int(row["id"]), "name": str(row["name"])})
    return mapping
