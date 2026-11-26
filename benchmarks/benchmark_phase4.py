"""Phase 4 repeatable before-and-after benchmark suite (backend + WebKit UI loading)."""

from __future__ import annotations

import http.client
import json
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from waitress import create_server

from app import create_app
from app.migrations.runner import initialize_database
from app.services import analytics_service, overview_service, transaction_service
from benchmarks.baseline_phase1 import _find_free_port
from benchmarks.baseline_phase2 import _bulk_seed_transactions, _summarize
from desktop.lifecycle import stop_waitress_server


def _time_bounded(fn: Any, *, iterations: int = 12, timeout_s: float = 5.0) -> dict[str, Any]:
    samples: list[float] = []
    timed_out = False
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        samples.append(elapsed * 1000.0)
        if elapsed > timeout_s:
            timed_out = True
            break
    out = _summarize(samples)
    out["iterations"] = len(samples)
    out["timed_out"] = timed_out
    return out


def run_phase4_benchmark() -> dict[str, Any]:
    results: dict[str, Any] = {"backend_10k": {}, "backend_100k": {}, "ui_10k": {}}

    # 10,000-row backend + WebKit UI loading
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "bench4_10k.sqlite3"
        initialize_database(db_path)
        _bulk_seed_transactions(db_path, 10_000)

        results["backend_10k"] = {
            "overview_load": _time_bounded(
                lambda: overview_service.get_overview(db_path, month="2026-11")
            ),
            "tx_amount_desc": _time_bounded(
                lambda: transaction_service.list_transactions(
                    db_path, sort="amount_desc", limit=100
                )
            ),
            "analytics_report": _time_bounded(
                lambda: analytics_service.get_full_analytics_report(db_path, preset="all_time")
            ),
        }

        port = _find_free_port()
        token = secrets.token_urlsafe(32)
        app = create_app(data_dir=Path(td), db_path=db_path, api_token=token, server_port=port)
        server = create_server(app, host="127.0.0.1", port=port, threads=8)
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        try:
            for _ in range(50):
                try:
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
                    c.request("GET", "/health", headers={"Host": f"127.0.0.1:{port}"})
                    if c.getresponse().status == 200:
                        c.close()
                        break
                except OSError:
                    time.sleep(0.02)

            with sync_playwright() as pw:
                browser = pw.webkit.launch()
                ctx = browser.new_context(viewport={"width": 1200, "height": 780})
                ctx.add_init_script(f"window.__finoraPendingAuth = {token!r};")
                page = ctx.new_page()

                ov_samples, tx_samples = [], []
                for _ in range(5):
                    t0 = time.perf_counter()
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
                    page.locator("#overview-recent-body tr").first.wait_for(state="visible")
                    ov_samples.append((time.perf_counter() - t0) * 1000.0)

                    t1 = time.perf_counter()
                    page.goto(
                        f"http://127.0.0.1:{port}/transactions", wait_until="domcontentloaded"
                    )
                    page.locator("#tx-history-body tr").first.wait_for(state="visible")
                    tx_samples.append((time.perf_counter() - t1) * 1000.0)

                results["ui_10k"] = {
                    "overview_ui_ms": _summarize(ov_samples),
                    "transactions_ui_ms": _summarize(tx_samples),
                }
                browser.close()
        finally:
            stop_waitress_server(server, th)

    # 100,000-row backend (with bounded 5s timeout)
    with tempfile.TemporaryDirectory() as td:
        db_100k = Path(td) / "bench4_100k.sqlite3"
        initialize_database(db_100k)
        _bulk_seed_transactions(db_100k, 100_000)
        results["backend_100k"] = {
            "overview_load": _time_bounded(
                lambda: overview_service.get_overview(db_100k, month="2026-11"), iterations=5
            ),
            "tx_amount_desc": _time_bounded(
                lambda: transaction_service.list_transactions(
                    db_100k, sort="amount_desc", limit=100
                ),
                iterations=5,
                timeout_s=3.0,
            ),
        }

    return results


if __name__ == "__main__":
    print(json.dumps(run_phase4_benchmark(), indent=2))
