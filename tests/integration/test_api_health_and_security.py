"""Integration tests for /health, token auth, Host/Origin/Fetch-Metadata, and CSP."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def secured_client(tmp_path: Path):
    data_dir = tmp_path / "sec_data"
    app = create_app(
        data_dir=data_dir,
        api_token="ephemeral-secret-token-for-test",
        testing=True,
    )
    return app.test_client(), "ephemeral-secret-token-for-test"


@pytest.mark.integration
def test_health_endpoint_minimal_and_safe(secured_client) -> None:
    client, _token = secured_client
    resp = client.get("/health", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
    assert "Access-Control-Allow-Origin" not in resp.headers
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


@pytest.mark.integration
def test_html_shell_serves_strict_csp_and_no_token_leak(secured_client) -> None:
    client, token = secured_client
    resp = client.get("/", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert token not in html
    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.integration
def test_api_rejects_missing_or_wrong_token(secured_client) -> None:
    client, _token = secured_client
    for headers in (
        {"Host": "127.0.0.1"},
        {"Host": "127.0.0.1", "X-Finora-Token": "wrong-token"},
    ):
        resp = client.get("/api/overview", headers=headers)
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "unauthorized"


@pytest.mark.integration
def test_api_rejects_invalid_host_origin_and_cross_site(secured_client) -> None:
    client, token = secured_client

    # DNS rebinding / untrusted Host
    resp_host = client.get(
        "/api/overview",
        headers={"Host": "evil.example:5000", "X-Finora-Token": token},
    )
    assert resp_host.status_code == 403
    assert resp_host.get_json()["error"]["code"] == "invalid_host"

    # Cross-origin browser request
    resp_origin = client.post(
        "/api/transactions",
        json={},
        headers={
            "Host": "127.0.0.1",
            "Origin": "https://evil.example",
            "X-Finora-Token": token,
        },
    )
    assert resp_origin.status_code == 403
    assert resp_origin.get_json()["error"]["code"] == "invalid_origin"

    # Fetch Metadata cross-site
    resp_fetch = client.get(
        "/api/transactions",
        headers={
            "Host": "127.0.0.1",
            "Sec-Fetch-Site": "cross-site",
            "X-Finora-Token": token,
        },
    )
    assert resp_fetch.status_code == 403
    assert resp_fetch.get_json()["error"]["code"] == "cross_site_blocked"


@pytest.mark.integration
def test_api_rejects_non_json_and_oversized_payloads(secured_client) -> None:
    client, token = secured_client

    resp_ct = client.post(
        "/api/transactions",
        data="entry_type=expense",
        content_type="application/x-www-form-urlencoded",
        headers={"Host": "127.0.0.1", "X-Finora-Token": token},
    )
    assert resp_ct.status_code == 415

    huge_body = '{"description": "' + ("x" * 70_000) + '"}'
    resp_size = client.post(
        "/api/transactions",
        data=huge_body,
        content_type="application/json",
        headers={"Host": "127.0.0.1", "X-Finora-Token": token},
    )
    assert resp_size.status_code == 413

    # Chunked / unknown Content-Length body exceeding 64 KiB must also return 413
    import io

    resp_chunked = client.post(
        "/api/transactions",
        input_stream=io.BytesIO(huge_body.encode("utf-8")),
        content_type="application/json",
        headers={
            "Host": "127.0.0.1",
            "X-Finora-Token": token,
        },
        environ_base={"CONTENT_LENGTH": ""},
    )
    assert resp_chunked.status_code == 413
