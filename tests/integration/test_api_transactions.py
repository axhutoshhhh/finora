"""Backend integration tests for overview, transactions, categories, accounts, and settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "integration_data"
    token = "integration-test-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app, app.test_client(), headers, data_dir, token


@pytest.mark.integration
def test_first_launch_empty_overview_and_seeded_lookups(api_env) -> None:
    _app, client, headers, _data_dir, _token = api_env

    overview = client.get("/api/overview", headers=headers)
    assert overview.status_code == 200
    ov = overview.get_json()
    assert ov["total_balance_minor"] == 0
    assert ov["total_balance_formatted"] == "₹0.00"
    assert ov["has_transactions"] is False
    assert ov["recent_transactions"] == []

    accounts = client.get("/api/accounts", headers=headers)
    assert accounts.status_code == 200
    acct_list = accounts.get_json()["accounts"]
    assert len(acct_list) == 1
    assert acct_list[0]["name"] == "Cash"

    exp_cats = client.get("/api/categories?kind=expense", headers=headers).get_json()["categories"]
    inc_cats = client.get("/api/categories?kind=income", headers=headers).get_json()["categories"]
    assert len(exp_cats) == 10
    assert len(inc_cats) == 7


@pytest.mark.integration
def test_create_transactions_persist_across_app_restart(api_env) -> None:
    _app, client, headers, data_dir, token = api_env

    cash_id = client.get("/api/accounts", headers=headers).get_json()["accounts"][0]["id"]
    exp_cat_id = client.get("/api/categories?kind=expense", headers=headers).get_json()[
        "categories"
    ][0]["id"]
    inc_cat_id = client.get("/api/categories?kind=income", headers=headers).get_json()[
        "categories"
    ][0]["id"]

    # Create income
    r1 = client.post(
        "/api/transactions",
        json={
            "entry_type": "income",
            "account_id": cash_id,
            "category_id": inc_cat_id,
            "amount": "5000.00",
            "tx_date": "2026-11-10",
            "description": "Monthly allowance",
            "idempotency_key": "tx-inc-1",
        },
        headers=headers,
    )
    assert r1.status_code == 201
    assert r1.get_json()["transaction"]["signed_amount_minor"] == 500_000

    # Create expense
    r2 = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat_id,
            "amount": "450.25",
            "tx_date": "2026-11-12",
            "description": "Lunch",
            "idempotency_key": "tx-exp-1",
        },
        headers=headers,
    )
    assert r2.status_code == 201
    assert r2.get_json()["transaction"]["signed_amount_minor"] == -45_025

    # Duplicate submission with same idempotency_key returns 200 without duplicating
    r2_dup = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat_id,
            "amount": "450.25",
            "tx_date": "2026-11-12",
            "description": "Lunch",
            "idempotency_key": "tx-exp-1",
        },
        headers=headers,
    )
    assert r2_dup.status_code == 200
    assert r2_dup.get_json()["created"] is False

    # Invalid amount rejected with 400
    r_bad = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": exp_cat_id,
            "amount": "-100",
            "tx_date": "2026-11-12",
        },
        headers=headers,
    )
    assert r_bad.status_code == 400

    # Category / entry_type mismatch rejected with 422
    r_mismatch = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": inc_cat_id,
            "amount": "100",
            "tx_date": "2026-11-12",
        },
        headers=headers,
    )
    assert r_mismatch.status_code == 422

    # Simulate fresh application restart with new create_app() instance
    restarted_app = create_app(data_dir=data_dir, api_token=token, testing=True)
    restarted_client = restarted_app.test_client()

    ov = restarted_client.get("/api/overview?month=2026-11", headers=headers).get_json()
    assert ov["total_balance_minor"] == 454_975
    assert ov["total_balance_formatted"] == "₹4,549.75"
    assert ov["month"]["income_minor"] == 500_000
    assert ov["month"]["expense_minor"] == 45_025
    assert ov["month"]["surplus_minor"] == 454_975
    assert ov["transaction_count"] == 2

    tx_list = restarted_client.get("/api/transactions", headers=headers).get_json()
    assert tx_list["total_count"] == 2
    assert len(tx_list["transactions"]) == 2


@pytest.mark.integration
def test_settings_appearance_api_and_callback(tmp_path: Path) -> None:
    seen: list[str] = []
    data_dir = tmp_path / "settings_data"
    token = "settings-token"
    app = create_app(
        data_dir=data_dir,
        api_token=token,
        testing=True,
        appearance_callback=seen.append,
    )
    client = app.test_client()
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "X-Finora-Token": token,
    }

    r_get = client.get("/api/settings", headers=headers)
    assert r_get.status_code == 200
    assert r_get.get_json()["appearance"] == "system"

    r_put = client.put(
        "/api/settings/appearance",
        json={"appearance": "dark"},
        headers=headers,
    )
    assert r_put.status_code == 200
    assert r_put.get_json()["appearance"] == "dark"
    assert seen == ["dark"]

    # Confirm meta tag updates on page shell reload
    html = client.get("/", headers={"Host": "127.0.0.1"}).get_data(as_text=True)
    assert '<meta name="color-scheme" content="dark">' in html

    r_bad = client.put(
        "/api/settings/appearance",
        json={"appearance": "invalid"},
        headers=headers,
    )
    assert r_bad.status_code == 400
