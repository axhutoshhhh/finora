"""SQLite connection management, security permissions, and integrity PRAGMAs."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from app.utils.errors import DatabaseError

SQLITE_BUSY_TIMEOUT_MS = 5000


def ensure_secure_data_dir(data_dir: Path) -> None:
    """Create the runtime data directory with owner-only (0700) permissions."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(data_dir, 0o700)
    except OSError as exc:
        raise DatabaseError(
            "Unable to initialize the local Finora data directory. Check folder permissions."
        ) from exc


def _secure_db_file(db_path: Path) -> None:
    """Restrict database file permissions to owner read/write (0600)."""
    for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ):
        if candidate.exists():
            # Non-fatal if filesystem ignores POSIX mode bits, though local APFS supports it.
            with suppress(OSError):
                os.chmod(candidate, 0o600)


def _configure_connection(conn: sqlite3.Connection, *, is_memory: bool) -> None:
    """Apply mandatory integrity and concurrency PRAGMAs to a SQLite connection."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
    if not is_memory:
        row = conn.execute("PRAGMA journal_mode = WAL;").fetchone()
        if row is not None and str(row[0]).lower() == "wal":
            conn.execute("PRAGMA synchronous = NORMAL;")


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a configured SQLite connection for the given path."""
    is_memory = str(db_path) == ":memory:"
    path_arg = ":memory:" if is_memory else os.fspath(Path(db_path))
    if not is_memory:
        ensure_secure_data_dir(Path(db_path).parent)
    try:
        conn = sqlite3.connect(path_arg, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0)
        _configure_connection(conn, is_memory=is_memory)
        if not is_memory:
            _secure_db_file(Path(db_path))
        return conn
    except sqlite3.Error as exc:
        raise DatabaseError("Unable to open the local financial database.") from exc


@contextmanager
def db_session(
    db_path: Path | str,
    *,
    immediate: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a short-lived transactional SQLite connection and guarantee cleanup."""
    conn = connect(db_path)
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE;")
        with conn:
            yield conn
    except sqlite3.Error as exc:
        raise DatabaseError("A local database operation failed.") from exc
    finally:
        if str(db_path) != ":memory:":
            _secure_db_file(Path(db_path))
        conn.close()
