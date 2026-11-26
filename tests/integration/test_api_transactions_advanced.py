"""Integration tests for full transaction editing, soft-delete/restore, refunds, splits, search, and bulk API."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "tx_adv_data"
    token = "tx-adv-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app.test_client(), headers


@pytest.mark.integration
def test_transaction_edit_refund_split_delete_restore_and_search_api(api_env) -> None:
    client, headers = api_env
    cash_id = client.get("/api/accounts", headers=headers).get_json()["accounts"][0]["id"]
    cats = client.get("/api/categories?kind=expense", headers=headers).get_json()["categories"]

    # Create split transaction via API
    r_split = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "amount": "1000.00",
            "tx_date": "2026-11-10",
            "merchant": "BigBasket",
            "payment_method": "upi",
            "splits": [
                {"category_id": cats[0]["id"], "amount": "700.00"},
                {"category_id": cats[3]["id"], "amount": "300.00"},
            ],
        },
        headers=headers,
    )
    assert r_split.status_code == 201
    split_tx = r_split.get_json()["transaction"]
    assert split_tx["is_split"] is True

    # Edit split & merchant
    r_edit = client.patch(
        f"/api/transactions/{split_tx['id']}",
        json={
            "expected_revision": split_tx["revision"],
            "merchant": "BigBasket Now",
            "description": "Monthly groceries & essentials",
        },
        headers=headers,
    )
    assert r_edit.status_code == 200
    assert r_edit.get_json()["transaction"]["revision"] == 2

    # Partial refund on split allocation
    r_ref = client.post(
        f"/api/transactions/{split_tx['id']}/refunds",
        json={
            "amount": "200.00",
            "tx_date": "2026-11-15",
            "allocations": [{"category_id": cats[3]["id"], "amount": "200.00"}],
        },
        headers=headers,
    )
    assert r_ref.status_code == 201
    ref_tx = r_ref.get_json()["transaction"]

    # Search filter
    r_q = client.get("/api/transactions?q=BigBasket&payment_method=upi", headers=headers)
    assert r_q.status_code == 200
    assert r_q.get_json()["total_count"] == 1

    # Soft delete refund -> restore -> bulk delete
    assert client.delete(f"/api/transactions/{ref_tx['id']}", headers=headers).status_code == 200
    assert (
        client.post(f"/api/transactions/{ref_tx['id']}/restore", headers=headers).status_code == 200
    )

    r_bulk = client.post(
        "/api/transactions/bulk",
        json={"action": "delete", "transaction_ids": [ref_tx["id"], split_tx["id"]]},
        headers=headers,
    )
    assert r_bulk.status_code == 200
    assert r_bulk.get_json()["affected_count"] == 2

    r_trash = client.get("/api/transactions?deleted=deleted", headers=headers)
    assert r_trash.get_json()["total_count"] == 2
