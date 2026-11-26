"""Integration tests for Phase 3 analytics & reporting API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "analytics_api_data"
    token = "analytics-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app.test_client(), headers


@pytest.mark.integration
def test_analytics_api_endpoints_and_security(api_env) -> None:
    client, headers = api_env

    # Unauthorized request must be rejected
    unauth = client.get("/api/analytics/report", headers={"Host": "127.0.0.1"})
    assert unauth.status_code == 401

    # Seed one income and one expense
    acct_id = client.get("/api/accounts", headers=headers).get_json()["accounts"][0]["id"]
    inc_cat = client.get("/api/categories?kind=income", headers=headers).get_json()["categories"][
        0
    ]["id"]
    exp_cat = client.get("/api/categories?kind=expense", headers=headers).get_json()["categories"][
        0
    ]["id"]

    client.post(
        "/api/transactions",
        json={
            "entry_type": "income",
            "account_id": acct_id,
            "category_id": inc_cat,
            "amount": "20000.00",
            "tx_date": "2026-11-05",
            "description": "Salary",
        },
        headers=headers,
    )
    client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": acct_id,
            "category_id": exp_cat,
            "amount": "5000.00",
            "tx_date": "2026-11-10",
            "merchant": "Swiggy",
            "description": "Dinner",
        },
        headers=headers,
    )

    rep = client.get(
        "/api/analytics/report?preset=custom&start_date=2026-11-01&end_date=2026-11-30",
        headers=headers,
    )
    assert rep.status_code == 200
    data = rep.get_json()
    assert data["summary"]["income_minor"] == 2_000_000
    assert data["summary"]["net_expense_minor"] == 500_000
    assert data["summary"]["surplus_minor"] == 1_500_000
    assert data["merchants"][0]["merchant"] == "Swiggy"

    for sub in (
        "summary",
        "income-expense",
        "categories",
        "merchants",
        "balance-history",
        "budgets",
    ):
        r = client.get(f"/api/analytics/{sub}?preset=all_time", headers=headers)
        assert r.status_code == 200
