"""Repository for local transaction receipt/invoice attachments."""

from __future__ import annotations

import json
import sqlite3


def list_attachments_for_transaction(
    conn: sqlite3.Connection, transaction_id: int
) -> list[sqlite3.Row]:
    """List attachment metadata rows belonging to one transaction."""
    return conn.execute(
        """
        SELECT id, transaction_id, original_filename, stored_filename, mime_type, size_bytes, sha256, created_at
        FROM attachments
        WHERE transaction_id = ?
        ORDER BY id ASC;
        """,
        (transaction_id,),
    ).fetchall()


def get_attachments_for_transactions(
    conn: sqlite3.Connection, transaction_ids: list[int]
) -> dict[int, list[dict[str, object]]]:
    """Batch-load lightweight attachment metadata keyed by transaction_id."""
    if not transaction_ids:
        return {}
    rows = conn.execute(
        """
        SELECT id, transaction_id, original_filename, mime_type, size_bytes, created_at
        FROM attachments
        WHERE transaction_id IN (SELECT value FROM json_each(?))
        ORDER BY id ASC;
        """,
        (json.dumps(transaction_ids),),
    ).fetchall()
    mapping: dict[int, list[dict[str, object]]] = {}
    for r in rows:
        tx_id = int(r["transaction_id"])
        mapping.setdefault(tx_id, []).append(
            {
                "id": int(r["id"]),
                "original_filename": str(r["original_filename"]),
                "mime_type": str(r["mime_type"]),
                "size_bytes": int(r["size_bytes"]),
                "created_at": str(r["created_at"]),
            }
        )
    return mapping


def get_attachment_by_id(conn: sqlite3.Connection, attachment_id: int) -> sqlite3.Row | None:
    """Fetch a single attachment record by ID."""
    return conn.execute(
        """
        SELECT id, transaction_id, original_filename, stored_filename, mime_type, size_bytes, sha256, created_at
        FROM attachments
        WHERE id = ?;
        """,
        (attachment_id,),
    ).fetchone()


def create_attachment(
    conn: sqlite3.Connection,
    *,
    transaction_id: int,
    original_filename: str,
    stored_filename: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    now: str,
) -> int:
    """Insert validated attachment metadata row."""
    cursor = conn.execute(
        """
        INSERT INTO attachments (
            transaction_id, original_filename, stored_filename, mime_type, size_bytes, sha256, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (
            transaction_id,
            original_filename,
            stored_filename,
            mime_type,
            size_bytes,
            sha256,
            now,
        ),
    )
    return int(cursor.lastrowid)


def delete_attachment(conn: sqlite3.Connection, attachment_id: int) -> None:
    """Remove attachment metadata record."""
    conn.execute("DELETE FROM attachments WHERE id = ?;", (attachment_id,))
