"""Repeatable Phase 1 baseline performance benchmark for Finora.

Runs strictly against temporary isolated databases and records factual timing
measurements without touching any user data directory.
"""

from __future__ import annotations

import http.client
import json
import os
import platform
import secrets
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from waitress import create_server

from app import create_app
from app.migrations.runner import initialize_database
from app.services import transaction_service


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_benchmark_dataset(db_path: Path, count: int = 100) -> tuple[int, int, int]:
    accounts = transaction_service.list_accounts(db_path)
    cash_id = int(accounts[0]["id"])
    exp_cats = transaction_service.list_categories(db_path, kind="expense")
    inc_cats = transaction_service.list_categories(db_path, kind="income")
    exp_cat_id = int(exp_cats[0]["id"])
    inc_cat_id = int(inc_cats[0]["id"])

    for i in range(count):
        is_income = (i % 5) == 0
        transaction_service.create_transaction(
            db_path,
            {
                "entry_type": "income" if is_income else "expense",
                "account_id": cash_id,
                "category_id": inc_cat_id if is_income else exp_cat_id,
                "amount": f"{100 + i}.50",
                "tx_date": f"2026-11-{(i % 28) + 1:02d}",
                "description": f"Benchmark synthetic entry {i + 1}",
            },
        )
    return cash_id, exp_cat_id, inc_cat_id


def _measure_cold_desktop_startup() -> float:
    """Measure cold subprocess launch of main.py until DB + lock file appear and teardown."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "cold_start"
        env = {**os.environ, "FINORA_DATA_DIR": str(data_dir)}
        t0 = time.perf_counter()
        proc = subprocess.Popen(
            [".venv/bin/python", "main.py"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        db_path = data_dir / "finance.sqlite3"
        lock_path = data_dir / ".finora.lock"
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if db_path.exists() and lock_path.exists() and lock_path.read_text().strip():
                    break
                time.sleep(0.02)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        finally:
            proc.terminate()
            proc.wait(timeout=5.0)
    return elapsed_ms


def _api_request_ms(
    port: int,
    token: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> float:
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "X-Finora-Token": token,
    }
    payload_bytes = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload_bytes = json.dumps(body).encode("utf-8")

    t0 = time.perf_counter()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request(method, path, body=payload_bytes, headers=headers)
        resp = conn.getresponse()
        resp.read()
        assert resp.status in (200, 201), f"Unexpected HTTP status {resp.status} for {path}"
    finally:
        conn.close()
    return (time.perf_counter() - t0) * 1000.0


def run_benchmark() -> dict[str, object]:
    cold_startup_ms = _measure_cold_desktop_startup()

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "bench_data"
        db_path = data_dir / "finance.sqlite3"
        initialize_database(db_path)
        cash_id, exp_cat_id, _inc_cat_id = _seed_benchmark_dataset(db_path, count=100)

        port = _find_free_port()
        token = secrets.token_urlsafe(32)
        app = create_app(
            data_dir=data_dir,
            db_path=db_path,
            api_token=token,
            server_port=port,
            testing=False,
            initialize_db=False,
        )
        server = create_server(app, host="127.0.0.1", port=port, threads=8)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for health ready
        for _ in range(100):
            try:
                _api_request_ms(port, token, "GET", "/health")
                break
            except OSError:
                time.sleep(0.02)

        try:
            overview_latencies = [
                _api_request_ms(port, token, "GET", "/api/overview?month=2026-11")
                for _ in range(25)
            ]
            history_latencies = [
                _api_request_ms(port, token, "GET", "/api/transactions?limit=100")
                for _ in range(25)
            ]
            save_latencies = [
                _api_request_ms(
                    port,
                    token,
                    "POST",
                    "/api/transactions",
                    {
                        "entry_type": "expense",
                        "account_id": cash_id,
                        "category_id": exp_cat_id,
                        "amount": "149.50",
                        "tx_date": "2026-11-26",
                        "description": f"Benchmark write {idx}",
                    },
                )
                for idx in range(25)
            ]

            with sync_playwright() as p:
                browser = p.webkit.launch()
                context = browser.new_context(viewport={"width": 1200, "height": 780})
                context.add_init_script(f"window.__finoraPendingAuth = {token!r};")
                page = context.new_page()

                t_ui0 = time.perf_counter()
                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.locator("#overview-recent-body tr").first.wait_for(state="visible")
                first_usable_ui_ms = (time.perf_counter() - t_ui0) * 1000.0

                t_nav0 = time.perf_counter()
                page.locator('[data-nav-view="transactions"]').click()
                page.locator("#tx-history-body tr").first.wait_for(state="visible")
                nav_to_tx_ms = (time.perf_counter() - t_nav0) * 1000.0

                t_nav1 = time.perf_counter()
                page.locator('[data-nav-view="settings"]').click()
                page.locator("#view-settings").wait_for(state="visible")
                nav_to_settings_ms = (time.perf_counter() - t_nav1) * 1000.0

                context.close()
                browser.close()
        finally:

            def _stop() -> None:
                server.task_dispatcher.shutdown()
                for ch in list(server._map.values()):
                    ch.close()
                server.close()

            server.trigger.pull_trigger(_stop)
            thread.join(timeout=2.0)

    def _stats(samples: list[float]) -> dict[str, float]:
        ordered = sorted(samples)
        p95_idx = min(len(ordered) - 1, max(0, int(0.95 * len(ordered)) - 1))
        return {
            "median_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(ordered[p95_idx], 2),
            "max_ms": round(max(ordered), 2),
        }

    return {
        "environment": {
            "os": f"macOS {platform.mac_ver()[0]}",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "dataset_rows": 100,
        },
        "metrics_ms": {
            "cold_desktop_init_ms": round(cold_startup_ms, 1),
            "webkit_first_usable_overview_ms": round(first_usable_ui_ms, 1),
            "webkit_nav_to_transactions_ms": round(nav_to_tx_ms, 1),
            "webkit_nav_to_settings_ms": round(nav_to_settings_ms, 1),
            "api_overview": _stats(overview_latencies),
            "api_transactions_list_100": _stats(history_latencies),
            "api_transaction_create": _stats(save_latencies),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
