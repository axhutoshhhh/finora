"""Integration tests for financial accounts, credit cards, and transfer API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "acct_api_data"
    token = "acct-test-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app.test_client(), headers


@pytest.mark.integration
def test_accounts_and_transfers_api_workflow(api_env) -> None:
    client, headers = api_env

    # Create Bank + Credit Card
    r_bank = client.post(
        "/api/accounts",
        json={
            "name": "ICICI Salary",
            "account_type": "bank",
            "opening_balance": "25000.00",
            "opening_balance_date": "2026-11-01",
            "description": "Primary salary account",
        },
        headers=headers,
    )
    assert r_bank.status_code == 201
    bank = r_bank.get_json()["account"]

    r_cc = client.post(
        "/api/accounts",
        json={
            "name": "Amazon Pay Card",
            "account_type": "credit_card",
            "opening_balance": "1200.00",
            "credit_limit": "75000.00",
        },
        headers=headers,
    )
    assert r_cc.status_code == 201
    cc = r_cc.get_json()["account"]
    assert cc["outstanding_liability_minor"] == 120_000
    assert cc["available_credit_minor"] == 7_380_000

    # Transfer Bank -> CC Repayment
    r_xfer = client.post(
        "/api/transfers",
        json={
            "from_account_id": bank["id"],
            "to_account_id": cc["id"],
            "amount": "1200.00",
            "tx_date": "2026-11-18",
            "description": "Full bill settle",
        },
        headers=headers,
    )
    assert r_xfer.status_code == 201
    assert r_xfer.get_json()["transaction"]["transfer_subtype"] == "credit_card_repayment"

    # Detail check
    detail = client.get(f"/api/accounts/{cc['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.get_json()["account"]["outstanding_liability_minor"] == 0

    # Unauthorized account endpoints blocked
    r_unauth = client.post("/api/accounts", json={"name": "Hack", "account_type": "cash"})
    assert r_unauth.status_code in (401, 403)
    r_xfer_unauth = client.post(
        "/api/transfers",
        json={
            "from_account_id": bank["id"],
            "to_account_id": cc["id"],
            "amount": "10",
            "tx_date": "2026-11-18",
        },
    )
    assert r_xfer_unauth.status_code in (401, 403)
