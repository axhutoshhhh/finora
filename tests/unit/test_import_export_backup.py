"""Unit tests for CSV import/export, formula injection, PDF, and backup/restore (Scenarios I, J, K)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.services import (
    account_service,
    backup_service,
    category_service,
    export_service,
    import_service,
    transaction_service,
)
from app.utils.errors import ValidationError


@pytest.mark.unit
def test_scenario_i_and_j_csv_preview_commit_idempotency_and_possible_dup(
    isolated_db: Path,
) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    rows_csv = ["date,description,merchant,amount,entry_type"]
    for i in range(100):
        rows_csv.append(f"2026-11-{(i % 28) + 1:02d},Purchase {i},Shop {i},{100 + i}.00,expense")
    csv_bytes = "\n".join(rows_csv).encode("utf-8")

    # Preview must create 0 transactions
    prev = import_service.preview_csv_import(
        isolated_db, csv_bytes=csv_bytes, account_id=cash_id, mapping={}
    )
    assert prev["total_rows"] == 100
    assert prev["valid_count"] == 100
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 0

    # Commit + idempotent replay
    c1 = import_service.commit_csv_import(
        isolated_db,
        batch_uuid=prev["batch_uuid"],
        source_filename="test.csv",
        account_id=cash_id,
        rows=prev["rows"],
    )
    c2 = import_service.commit_csv_import(
        isolated_db,
        batch_uuid=prev["batch_uuid"],
        source_filename="test.csv",
        account_id=cash_id,
        rows=prev["rows"],
    )
    assert c1["inserted_count"] == 100
    assert c2["idempotent_replay"] is True
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 100

    # Scenario J: same amount & date with different description -> possible_duplicate (reviewable, not dropped)
    csv2 = b"date,description,merchant,amount,entry_type\n2026-11-01,Second coffee,Cafe,100.00,expense\n"
    prev2 = import_service.preview_csv_import(
        isolated_db, csv_bytes=csv2, account_id=cash_id, mapping={}
    )
    assert prev2["rows"][0]["status"] == "possible_duplicate"


@pytest.mark.unit
def test_csv_formula_injection_and_pdf_generation(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "125.00",
            "tx_date": "2026-11-10",
            "merchant": "=CMD('calc')",
            "description": "+SUM(1,2)",
        },
    )
    csv_out = export_service.export_transactions_csv(isolated_db)
    assert "'=CMD('calc')" in csv_out
    assert "'+SUM(1,2)" in csv_out

    pdf = export_service.export_pdf_report(isolated_db, preset="all_time")
    assert pdf.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf


@pytest.mark.unit
def test_scenario_k_backup_restore_and_malicious_archive_rejection(
    isolated_db: Path, tmp_path: Path
) -> None:
    data_dir = isolated_db.parent
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "500.00",
            "tx_date": "2026-11-10",
            "description": "Before backup",
        },
    )
    b_res = backup_service.create_workspace_backup(data_dir, isolated_db)
    b_zip = Path(b_res["backup_path"])
    assert b_zip.exists()

    # Mutate DB after backup, then restore
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat,
            "amount": "900.00",
            "tx_date": "2026-11-12",
            "description": "After backup",
        },
    )
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 2

    backup_service.restore_workspace_backup(data_dir, isolated_db, b_zip)
    assert transaction_service.list_transactions(isolated_db)["total_count"] == 1

    # Malicious path traversal archive must be rejected
    bad_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
    with pytest.raises(ValidationError):
        backup_service.restore_workspace_backup(data_dir, isolated_db, bad_zip)
