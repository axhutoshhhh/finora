"""Unit tests for desktop single-instance locking, readiness checks, and path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from desktop.launcher import deliver_launch_token
from desktop.lifecycle import (
    SingleInstanceGuard,
    StartupError,
    allocate_loopback_port,
    start_waitress_server,
    stop_waitress_server,
    wait_for_server_ready,
)
from desktop.paths import verify_bundled_assets


@pytest.mark.unit
def test_single_instance_lock_blocks_second_acquire_and_releases(tmp_path: Path) -> None:
    lock_file = tmp_path / ".finora.lock"
    first = SingleInstanceGuard(lock_file)
    second = SingleInstanceGuard(lock_file)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()


@pytest.mark.unit
def test_waitress_startup_readiness_and_clean_shutdown(tmp_path: Path) -> None:
    port = allocate_loopback_port()
    app = create_app(data_dir=tmp_path / "srv_data", server_port=port, testing=False)
    server, thread = start_waitress_server(app, port=port)
    try:
        wait_for_server_ready(port, timeout_seconds=3.0)
    finally:
        stop_waitress_server(server, thread)
    assert not thread.is_alive()


@pytest.mark.unit
def test_readiness_timeout_raises_startup_error() -> None:
    unused_port = allocate_loopback_port()
    with pytest.raises(StartupError):
        wait_for_server_ready(unused_port, timeout_seconds=0.2)


@pytest.mark.unit
def test_verify_bundled_assets_succeeds() -> None:
    root = verify_bundled_assets()
    assert (root / "app" / "templates" / "app.html").is_file()


@pytest.mark.unit
def test_deliver_launch_token_enforces_expected_origin() -> None:
    class _FakeWindow:
        def __init__(self, url: str) -> None:
            self._url = url
            self.scripts: list[str] = []

        def get_current_url(self) -> str:
            return self._url

        def run_js(self, script: str) -> None:
            self.scripts.append(script)

    evil = _FakeWindow("https://evil.example/")
    assert (
        deliver_launch_token(
            evil,  # type: ignore[arg-type]
            token="secret-token",
            expected_origin="http://127.0.0.1:50000/",
        )
        is False
    )
    assert evil.scripts == []

    local = _FakeWindow("http://127.0.0.1:50000/transactions")
    assert (
        deliver_launch_token(
            local,  # type: ignore[arg-type]
            token="secret-token",
            expected_origin="http://127.0.0.1:50000/",
        )
        is True
    )
    assert len(local.scripts) == 1
    assert "__finoraSetAuth" in local.scripts[0]
    assert "secret-token" in local.scripts[0]
