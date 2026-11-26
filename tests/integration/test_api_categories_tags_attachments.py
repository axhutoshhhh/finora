"""Integration tests for categories, tags, and attachment upload/download security API."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def api_env(tmp_path: Path):
    data_dir = tmp_path / "cat_tag_att_data"
    token = "cat-tag-att-token"
    app = create_app(data_dir=data_dir, api_token=token, testing=True)
    headers = {
        "Host": "127.0.0.1",
        "Origin": "http://127.0.0.1",
        "Sec-Fetch-Site": "same-origin",
        "X-Finora-Token": token,
    }
    return app.test_client(), headers, data_dir


@pytest.mark.integration
def test_categories_tags_and_attachment_security_api(api_env) -> None:
    client, headers, _data_dir = api_env
    cash_id = client.get("/api/accounts", headers=headers).get_json()["accounts"][0]["id"]

    r_cat = client.post(
        "/api/categories",
        json={"name": "Books & Notes", "kind": "expense", "icon": "book-open"},
        headers=headers,
    )
    assert r_cat.status_code == 201
    cat_id = r_cat.get_json()["category"]["id"]

    r_tag = client.post("/api/tags", json={"name": "Reimbursable"}, headers=headers)
    assert r_tag.status_code == 201
    tag_id = r_tag.get_json()["tag"]["id"]

    r_tx = client.post(
        "/api/transactions",
        json={
            "entry_type": "expense",
            "account_id": cash_id,
            "category_id": cat_id,
            "amount": "850.00",
            "tx_date": "2026-11-15",
            "tag_ids": [tag_id],
        },
        headers=headers,
    )
    assert r_tx.status_code == 201
    tx_id = r_tx.get_json()["transaction"]["id"]

    # Reject non-PDF disguised file
    r_bad_file = client.post(
        f"/api/transactions/{tx_id}/attachments",
        data={"file": (io.BytesIO(b"#!/bin/sh\necho hi"), "fake.pdf")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert r_bad_file.status_code == 415

    # Reject >5 MiB upload
    r_big_file = client.post(
        f"/api/transactions/{tx_id}/attachments",
        data={"file": (io.BytesIO(b"%PDF-" + b"a" * (5 * 1024 * 1024 + 16)), "big.pdf")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert r_big_file.status_code == 413

    # Valid JPEG upload + authorized download + security headers
    r_ok = client.post(
        f"/api/transactions/{tx_id}/attachments",
        data={"file": (io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF"), "bill.jpg")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert r_ok.status_code == 201
    att_id = r_ok.get_json()["attachment"]["id"]

    # Unauthorized download blocked
    assert (
        client.get(f"/api/attachments/{att_id}", headers={"Host": "127.0.0.1"}).status_code == 401
    )

    r_dl = client.get(f"/api/attachments/{att_id}", headers=headers)
    assert r_dl.status_code == 200
    assert r_dl.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in r_dl.headers["Content-Security-Policy"]
    r_dl.close()

    assert client.delete(f"/api/attachments/{att_id}", headers=headers).status_code == 200
    assert client.get(f"/api/attachments/{att_id}", headers=headers).status_code == 404
