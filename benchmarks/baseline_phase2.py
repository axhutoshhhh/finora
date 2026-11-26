"""Repeatable Phase 2 performance benchmark across empty, 100, 1k, 10k, and 100k datasets.

Strictly isolated to temporary directories; never reads or modifies personal data.
"""

from __future__ import annotations

import http.client
import json
import platform
import secrets
import sqlite3
import statistics
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
from app.database import db_session
from app.migrations.runner import initialize_database
from app.services import (
    account_service,
    budget_service,
    overview_service,
    transaction_service,
)
from benchmarks.baseline_phase1 import _find_free_port
from desktop.lifecycle import stop_waitress_server


def _bulk_seed_transactions(db_path: Path, count: int) -> tuple[int, int, int, int]:
    """Seed deterministic expenses, income, and transfers quickly inside one transaction."""
    cash = account_service.list_accounts(db_path)["accounts"][0]
    bank = account_service.create_account(
        db_path, {"name": "Bench Bank", "account_type": "bank", "opening_balance": "100000"}
    )
    exp_cat = transaction_service.list_categories(db_path, kind="expense")[0]["id"]
    inc_cat = transaction_service.list_categories(db_path, kind="income")[0]["id"]
    budget_service.set_category_budget(
        db_path, {"month": "2026-11", "category_id": exp_cat, "limit": "50000"}
    )

    if count == 0:
        return cash["id"], bank["id"], exp_cat, inc_cat

    now = "2026-11-26T10:00:00Z"
    with db_session(db_path, immediate=True) as conn:
        for i in range(count):
            is_inc = (i % 6) == 0
            etype = "income" if is_inc else "expense"
            amt = (150 + (i % 500)) * 100
            signed = amt if is_inc else -amt
            acct_id = bank["id"] if (i % 2 == 0) else cash["id"]
            cat_id = inc_cat if is_inc else exp_cat
            tx_date = f"2026-{(i % 11) + 1:02d}-{(i % 28) + 1:02d}"
            cur = conn.execute(
                """
                INSERT INTO transactions (
                    entry_type, tx_date, description, merchant, payment_method,
                    is_split, revision, deleted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'upi', 0, 1, NULL, ?, ?);
                """,
                (etype, tx_date, f"Synthetic note {i + 1}", f"Merchant {i % 50}", now, now),
            )
            conn.execute(
                """
                INSERT INTO postings (transaction_id, account_id, category_id, signed_amount_minor, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (int(cur.lastrowid), acct_id, cat_id, signed, now),
            )
    return cash["id"], bank["id"], exp_cat, inc_cat


def _summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95_idx = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    return {
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[p95_idx], 2),
        "max_ms": round(ordered[-1], 2),
    }


def _time_calls(fn, iterations: int = 12) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return _summarize(samples)


def run_benchmark() -> dict[str, Any]:
    results: dict[str, Any] = {
        "environment": {
            "os": f"macOS {platform.mac_ver()[0]}",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "datasets": {},
    }

    for size in (0, 100, 1_000, 10_000, 100_000):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "bench.sqlite3"
            initialize_database(db_path)
            cash_id, bank_id, exp_cat, _ = _bulk_seed_transactions(db_path, size)

            # Seed one known editable/refundable expense in Nov 2026
            ref_parent, _ = transaction_service.create_transaction(
                db_path,
                {
                    "entry_type": "expense",
                    "account_id": cash_id,
                    "category_id": exp_cat,
                    "amount": "2000.00",
                    "tx_date": "2026-11-20",
                    "merchant": "Anchor Target",
                },
            )

            iters = 7 if size >= 100_000 else 15
            ds_metrics: dict[str, Any] = {
                "accounts_list": _time_calls(
                    lambda p=db_path: account_service.list_accounts(p), iterations=iters
                ),
                "overview_load": _time_calls(
                    lambda p=db_path: overview_service.get_overview(p, month="2026-11"),
                    iterations=iters,
                ),
                "tx_search_query": _time_calls(
                    lambda p=db_path: transaction_service.list_transactions(
                        p, query="Anchor Target", limit=100
                    ),
                    iterations=iters,
                ),
                "tx_filtered_sorted": _time_calls(
                    lambda p=db_path, a=bank_id: transaction_service.list_transactions(
                        p,
                        month="2026-11",
                        account_id=a,
                        entry_type="expense",
                        sort="amount_desc",
                        limit=100,
                    ),
                    iterations=iters,
                ),
                "budget_load": _time_calls(
                    lambda p=db_path: budget_service.get_month_budgets(p, month="2026-11"),
                    iterations=iters,
                ),
            }

            if size <= 10_000:
                ds_metrics["transfer_create"] = _time_calls(
                    lambda p=db_path, c=cash_id, b=bank_id: transaction_service.create_transfer(
                        p,
                        {
                            "from_account_id": b,
                            "to_account_id": c,
                            "amount": "10.00",
                            "tx_date": "2026-11-25",
                        },
                    ),
                    iterations=8,
                )
                ds_metrics["refund_create"] = _time_calls(
                    lambda p=db_path, pid=ref_parent["id"]: transaction_service.create_refund(
                        p, pid, {"amount": "1.00", "tx_date": "2026-11-26"}
                    ),
                    iterations=8,
                )
                ds_metrics["tx_edit"] = _time_calls(
                    lambda p=db_path, pid=ref_parent["id"]: transaction_service.update_transaction(
                        p, pid, {"description": f"Edited {time.perf_counter_ns()}"}
                    ),
                    iterations=8,
                )

            if size == 10_000:
                # WebKit table render timing at 10,000 rows (paginated 100 rows DOM load)
                port = _find_free_port()
                token = secrets.token_urlsafe(32)
                app = create_app(
                    data_dir=Path(td), db_path=db_path, api_token=token, server_port=port
                )
                server = create_server(app, host="127.0.0.1", port=port, threads=8)
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                try:
                    for _ in range(50):
                        try:
                            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
                            conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{port}"})
                            if conn.getresponse().status == 200:
                                conn.close()
                                break
                        except OSError:
                            time.sleep(0.02)
                    with sync_playwright() as pw:
                        browser = pw.webkit.launch()
                        ctx = browser.new_context(viewport={"width": 1200, "height": 780})
                        ctx.add_init_script(f"window.__finoraPendingAuth = {token!r};")
                        page = ctx.new_page()
                        t0 = time.perf_counter()
                        page.goto(f"http://127.0.0.1:{port}/transactions", wait_until="networkidle")
                        page.locator("#tx-history-body tr").first.wait_for(state="visible")
                        ds_metrics["webkit_tx_table_render_10k_ms"] = round(
                            (time.perf_counter() - t0) * 1000.0, 1
                        )
                        browser.close()
                finally:
                    stop_waitress_server(server, thread)

            results["datasets"][str(size)] = ds_metrics

    return results


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
