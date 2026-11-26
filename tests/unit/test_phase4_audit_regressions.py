"""Dedicated regression tests for all Phase 4 independent audit findings."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app import create_app
from app.services import (
    account_service,
    advisory_service,
    backup_service,
    budget_service,
    calendar_service,
    category_service,
    export_service,
    goal_service,
    import_service,
    recurring_service,
    transaction_service,
    workspace_service,
)
from app.utils.errors import ConflictError, ValidationError


@pytest.mark.integration
def test_stale_workspace_generation_header_rejected(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path / "ws_gen", api_token="ws-tok", testing=True)
    client = app.test_client()
    h = {"Host": "127.0.0.1", "Origin": "http://127.0.0.1", "X-Finora-Token": "ws-tok"}
    r_sw = client.post("/api/workspaces/switch", json={"workspace": "demo"}, headers=h)
    assert r_sw.status_code == 200
    assert r_sw.get_json()["workspace_gen"] == 2

    # Stale request carrying gen=1 must be rejected with 409
    r_stale = client.get("/api/accounts", headers={**h, "X-Finora-Workspace-Gen": "1"})
    assert r_stale.status_code == 409
    assert r_stale.get_json()["error"]["code"] == "workspace_changed"


@pytest.mark.unit
def test_backup_isolation_missing_manifest_and_wal_cleanup(
    isolated_db: Path, tmp_path: Path
) -> None:
    data_dir = isolated_db.parent
    _, demo_db = workspace_service.get_workspace_paths(data_dir, workspace="demo")
    workspace_service.seed_demo_workspace(demo_db)

    # Create primary attachment and demo attachment
    (data_dir / "attachments").mkdir(exist_ok=True)
    (data_dir / "attachments" / "primary.png").write_bytes(b"PRIMARY")
    (demo_db.parent / "attachments").mkdir(exist_ok=True)
    (demo_db.parent / "attachments" / "demo.png").write_bytes(b"DEMO")

    demo_zip = Path(backup_service.create_workspace_backup(data_dir, demo_db)["backup_path"])
    with zipfile.ZipFile(demo_zip, "r") as zf:
        names = set(zf.namelist())
        assert "attachments/demo.png" in names
        assert "attachments/primary.png" not in names

    # Missing finance.sqlite3 in manifest["files"] must be rejected
    bad_zip = tmp_path / "missing_db_manifest.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": 1, "files": {}}))
        zf.writestr("finance.sqlite3", b"")
    with pytest.raises(ValidationError):
        backup_service.restore_workspace_backup(data_dir, isolated_db, bad_zip)

    # Stale -wal/-shm sidecars are removed on valid restore
    wal = isolated_db.with_name(isolated_db.name + "-wal")
    wal.write_bytes(b"stale-wal")
    prim_zip = Path(backup_service.create_workspace_backup(data_dir, isolated_db)["backup_path"])
    backup_service.restore_workspace_backup(data_dir, isolated_db, prim_zip)
    assert not wal.exists()


@pytest.mark.unit
def test_recurring_transfer_creates_two_balanced_postings(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    bank_id = account_service.create_account(
        isolated_db, {"name": "Bank", "account_type": "bank", "opening_balance": "5000.00"}
    )["id"]
    recurring_service.create_rule(
        isolated_db,
        {
            "name": "Monthly Savings Transfer",
            "entry_type": "transfer",
            "amount": "1000.00",
            "account_id": bank_id,
            "to_account_id": cash_id,
            "frequency": "monthly",
            "start_date": "2026-11-10",
        },
    )
    occ = recurring_service.list_occurrences(isolated_db)[0]
    res = recurring_service.post_occurrence(isolated_db, occ["id"])
    assert res["created"] is True

    accts = {
        a["id"]: a["balance_minor"] for a in account_service.list_accounts(isolated_db)["accounts"]
    }
    assert accts[bank_id] == 400_000
    assert accts[cash_id] == 100_000


@pytest.mark.unit
def test_csv_commit_validation_and_whitespace_formula_sanitization(isolated_db: Path) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    exp_cat = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    with pytest.raises(ValidationError):
        import_service.commit_csv_import(
            isolated_db,
            batch_uuid="bad-batch-1",
            source_filename="x.csv",
            account_id=cash_id,
            rows=[
                {
                    "row_number": 1,
                    "status": "valid",
                    "entry_type": "transfer",
                    "amount_minor": 100,
                    "tx_date": "2026-11-10",
                    "category_id": exp_cat,
                }
            ],
        )
    assert export_service.sanitize_csv_cell(" =1+1") == "' =1+1"


@pytest.mark.unit
def test_calendar_odd_paise_transfer_and_completed_goal_and_advisory_guards(
    isolated_db: Path,
) -> None:
    cash_id = account_service.list_accounts(isolated_db)["accounts"][0]["id"]
    bank_id = account_service.create_account(
        isolated_db, {"name": "Bank", "account_type": "bank", "opening_balance": "5000.00"}
    )["id"]
    transaction_service.create_transfer(
        isolated_db,
        {
            "from_account_id": bank_id,
            "to_account_id": cash_id,
            "amount": "100.01",
            "tx_date": "2026-11-15",
        },
    )
    cal = calendar_service.get_month_calendar(isolated_db, month="2026-11")
    day15 = cal["days"][14]
    assert day15["posted"][0]["amount_minor"] == 10_001

    goal = goal_service.create_goal(isolated_db, {"name": "Laptop", "target_amount": "1000.00"})
    goal_service.update_goal_status(isolated_db, goal["id"], "completed")
    with pytest.raises(ConflictError):
        goal_service.add_contribution(isolated_db, goal["id"], {"amount": "100.00"})

    # Disabled budget_exceeded must not fall back to budget_approaching
    food_id = category_service.list_categories(isolated_db, kind="expense")[0]["id"]
    budget_service.set_category_budget(
        isolated_db, {"month": "2026-11", "category_id": food_id, "limit": "100.00"}
    )
    transaction_service.create_transaction(
        isolated_db,
        {
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": food_id,
            "amount": "200.00",
            "tx_date": "2026-11-10",
        },
    )
    advisory_service.update_notification_preferences(
        isolated_db, [{"rule_id": "budget_exceeded", "enabled": False}]
    )
    notes = advisory_service.evaluate_advisories(isolated_db, month="2026-11")
    assert not any(n["rule_id"] in ("budget_exceeded", "budget_approaching") for n in notes)
    with pytest.raises(ValueError):
        advisory_service.update_notification_preferences(
            isolated_db, [{"rule_id": "budget_approaching", "threshold_value": "bad"}]
        )
