"""Unit tests for category management, transaction tags, and local attachment security."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import (
    account_service,
    attachment_service,
    category_service,
    tag_service,
    transaction_service,
)
from app.utils.errors import ConflictError, NotFoundError, ValidationError


@pytest.mark.unit
def test_category_customization_kind_lock_and_archive(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    food = [
        c
        for c in category_service.list_categories(isolated_db, kind="expense")
        if c["slug"] == "food_dining"
    ][0]

    # Renaming default expense category preserves stable slug
    renamed = category_service.update_category(isolated_db, food["id"], {"name": "Meals & Dining"})
    assert renamed["slug"] == "food_dining"
    assert renamed["name"] == "Meals & Dining"

    # Custom category + case-insensitive duplicate guard
    custom = category_service.create_category(
        isolated_db,
        {"name": "Pet Care", "kind": "expense", "icon": "heart-pulse", "color_token": "cat-sage"},
    )
    assert custom["is_system"] is False
    with pytest.raises(ConflictError):
        category_service.create_category(isolated_db, {"name": "  pet care  ", "kind": "expense"})

    # Cannot convert expense category to income category
    with pytest.raises(ValidationError):
        category_service.update_category(isolated_db, custom["id"], {"kind": "income"})

    # Record historical tx then archive custom category; tx remains readable, new tx rejected
    tx, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": custom["id"],
            "amount": "450.00",
            "tx_date": "2026-11-18",
        },
    )
    archived = category_service.archive_category(isolated_db, custom["id"])
    assert archived["is_archived"] is True
    assert (
        transaction_service.get_transaction_detail(isolated_db, tx["id"])["category_name"]
        == "Pet Care"
    )

    with pytest.raises(NotFoundError):
        transaction_service.create_transaction(
            isolated_db,
            {
                "entry_type": "expense",
                "account_id": cash_id,
                "category_id": custom["id"],
                "amount": "100.00",
                "tx_date": "2026-11-19",
            },
        )
    restored = category_service.restore_category(isolated_db, custom["id"])
    assert restored["is_archived"] is False


@pytest.mark.unit
def test_tags_lifecycle_filtering_and_bulk_tagging(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    cat_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]

    t_college, _ = tag_service.create_tag(isolated_db, {"name": "College"})
    t_hostel, _ = tag_service.create_tag(isolated_db, {"name": "Hostel"})
    with pytest.raises(ConflictError):
        tag_service.create_tag(isolated_db, {"name": "college"})

    tx1, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": cat_id,
            "amount": "200.00",
            "tx_date": "2026-11-12",
            "tag_ids": [t_college["id"], t_college["id"]],
        },
    )
    assert [t["name"] for t in tx1["tags"]] == ["College"]

    tx2, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": cat_id,
            "amount": "300.00",
            "tx_date": "2026-11-13",
        },
    )
    transaction_service.bulk_action(
        isolated_db,
        {"action": "add_tag", "transaction_ids": [tx1["id"], tx2["id"]], "tag_id": t_hostel["id"]},
    )

    filtered = transaction_service.list_transactions(isolated_db, tag_id=t_hostel["id"])
    assert filtered["total_count"] == 2
    searched = transaction_service.list_transactions(isolated_db, query="College")
    assert [r["id"] for r in searched["transactions"]] == [tx1["id"]]

    # Deleting a tag must NOT delete any transactions
    tag_service.delete_tag(isolated_db, t_college["id"])
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 2


@pytest.mark.unit
def test_attachment_magic_bytes_traversal_size_and_orphan_prevention(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    cat_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    tx, _ = transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": cat_id,
            "amount": "120.00",
            "tx_date": "2026-11-20",
        },
    )

    # Disguised SVG/HTML rejected by magic byte inspection
    with pytest.raises(ValidationError) as svg_err:
        attachment_service.save_attachment(
            isolated_db,
            transaction_id=tx["id"],
            original_filename="receipt.png",
            raw_bytes=b"<svg onload=alert(1)></svg>",
        )
    assert svg_err.value.status_code == 415

    # Valid PNG with traversal attempt in original filename
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    att = attachment_service.save_attachment(
        isolated_db,
        transaction_id=tx["id"],
        original_filename="../../evil/receipt.png",
        raw_bytes=png_bytes,
    )
    assert att["mime_type"] == "image/png"
    assert "/" not in att["original_filename"]
    meta, stored_path = attachment_service.get_attachment_for_download(isolated_db, att["id"])
    assert stored_path.parent == (isolated_db.parent / "attachments").resolve()
    assert (stored_path.stat().st_mode & 0o777) == 0o600
    assert stored_path.read_bytes() == png_bytes

    # Failed transaction DB insert must clean up staged file (no orphaned file left)
    before_files = set((isolated_db.parent / "attachments").iterdir())
    with pytest.raises(NotFoundError):
        attachment_service.save_attachment(
            isolated_db,
            transaction_id=99999,
            original_filename="valid.pdf",
            raw_bytes=b"%PDF-1.7\n%%EOF",
        )
    assert set((isolated_db.parent / "attachments").iterdir()) == before_files

    attachment_service.delete_attachment(isolated_db, att["id"])
    assert not stored_path.exists()
