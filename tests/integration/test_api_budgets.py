"""Integration tests for monthly budgeting and authorization APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "budgets_api_data"
    token = "budgets-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app.test_client(), headers


@pytest.mark.integration
def test_budgets_api_crud_copy_and_security(api_env) -> None:
    client, headers = api_env
    cats = client.get("/api/categories?kind=expense", headers=headers).get_json()["categories"]

    # Unauthorized requests blocked
    assert (
        client.put(
            "/api/budgets/category",
            json={"month": "2026-10", "category_id": cats[0]["id"], "limit": "5000"},
            headers={"Host": "127.0.0.1"},
        ).status_code
        == 401
    )

    r_cat = client.put(
        "/api/budgets/category",
        json={
            "month": "2026-10",
            "category_id": cats[0]["id"],
            "limit": "4000.00",
            "rollover_enabled": True,
        },
        headers=headers,
    )
    assert r_cat.status_code == 200
    assert r_cat.get_json()["overall"]["total_allocated_minor"] == 400_000

    r_ov = client.put(
        "/api/budgets/overall",
        json={"month": "2026-10", "limit": "15000.00"},
        headers=headers,
    )
    assert r_ov.status_code == 200
    assert r_ov.get_json()["overall"]["limit_minor"] == 1_500_000

    r_copy = client.post(
        "/api/budgets/copy",
        json={"target_month": "2026-11", "source_month": "2026-10"},
        headers=headers,
    )
    assert r_copy.status_code == 200
    nov = r_copy.get_json()
    assert nov["overall"]["limit_minor"] == 1_500_000
    assert nov["categories"][0]["carry_in_minor"] == 400_000

    assert (
        client.delete(
            f"/api/budgets/category/{cats[0]['id']}?month=2026-11", headers=headers
        ).status_code
        == 200
    )
    assert client.delete("/api/budgets/overall?month=2026-11", headers=headers).status_code == 200
