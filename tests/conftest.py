"""Shared test fixtures ensuring complete isolation from user financial data."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.migrations.runner import initialize_database


@pytest.fixture()
def isolated_db(tmp_path: Path) -> Path:
    """Create a fresh, migrated, seeded SQLite database inside pytest tmp_path."""
    data_dir = tmp_path / "finora_test_data"
    db_path = data_dir / "finance.sqlite3"
    initialize_database(db_path)
    return db_path
