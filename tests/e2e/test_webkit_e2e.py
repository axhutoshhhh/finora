"""End-to-end WebKit tests against live Waitress + Flask backend with isolated temp DB."""

from __future__ import annotations

import http.client
import os
import secrets
import socket
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from waitress import create_server

from app import create_app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop_waitress_server(server) -> None:
    """Close Waitress server cleanly inside its own asyncore thread."""

    def _shutdown() -> None:
        server.task_dispatcher.shutdown()
        for channel in list(server._map.values()):
            channel.close()
        server.close()

    server.trigger.pull_trigger(_shutdown)


@pytest.fixture()
def live_server(tmp_path: Path):
    data_dir = tmp_path / "e2e_data"
    port = _find_free_port()
    token = secrets.token_urlsafe(32)
    app = create_app(
        data_dir=data_dir,
        api_token=token,
        server_port=port,
        testing=False,
    )
    server = create_server(app, host="127.0.0.1", port=port, threads=8)
    thread = threading.Thread(target=server.run, name="finora-e2e-waitress", daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            conn.request("GET", "/health", headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse()
            if resp.status == 200:
                break
        except OSError:
            time.sleep(0.05)
        finally:
            if conn is not None:
                conn.close()
    else:
        _stop_waitress_server(server)
        raise RuntimeError("E2E Waitress server failed readiness probe.")

    yield {"base_url": base_url, "token": token, "data_dir": data_dir}

    _stop_waitress_server(server)
    thread.join(timeout=2.0)


def _open_webkit_page(
    playwright_ctx, base_url: str, token: str, *, width: int = 1200, height: int = 780
):
    browser = playwright_ctx.webkit.launch()
    context = browser.new_context(viewport={"width": width, "height": height})
    # Simulate the production CSP-safe run_js token handoff (Path 1/3 in api.js)
    # and confirm no token residue stays on window after consumption.
    context.add_init_script(f"window.__finoraPendingAuth = {token!r};")
    page = context.new_page()
    app_console_errors: list[str] = []
    page_errors: list[str] = []
    capture_state = {"capturing": False}

    def _on_console(msg) -> None:
        # Playwright's screenshot() temporarily injects an inline stylesheet to hide carets/scrollbars,
        # which triggers CSP style-src 'self' only during screenshot capture.
        if msg.type == "error" and not capture_state["capturing"]:
            app_console_errors.append(msg.text)

    page.on("console", _on_console)
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.goto(base_url, wait_until="networkidle")
    return browser, context, page, app_console_errors, page_errors, capture_state


def _take_shot(page, capture_state: dict[str, bool], path: Path) -> None:
    capture_state["capturing"] = True
    try:
        page.screenshot(path=str(path))
    finally:
        capture_state["capturing"] = False


@pytest.mark.e2e
def test_end_to_end_transaction_theme_and_responsive_layout(live_server, tmp_path: Path) -> None:
    base_url = live_server["base_url"]
    token = live_server["token"]
    shot_dir_env = os.environ.get("FINORA_E2E_SCREENSHOT_DIR")
    shot_dir = Path(shot_dir_env) if shot_dir_env else tmp_path / "shots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser, context, page, console_errors, page_errors, capture_state = _open_webkit_page(
            p, base_url, token, width=1200, height=780
        )
        try:
            # 1. Empty state on first launch
            expect(page.locator("#overview-balance")).to_have_text("₹0.00")
            expect(page.locator("#overview-empty")).to_be_visible()
            expect(page.locator("#overview-table-wrap")).to_be_hidden()
            _take_shot(page, capture_state, shot_dir / "01_overview_empty_light.png")

            # 2. Open transaction dialog, test Escape cancel
            page.locator("#new-tx-btn").click()
            dialog = page.locator("#tx-dialog")
            expect(dialog).to_be_visible()
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()

            # 3. Validation error preserves form data
            page.locator("#new-tx-btn").click()
            page.locator("#tx-amount").fill("-50")
            page.locator("#tx-description").fill("Unsaved Coffee")
            page.locator("#tx-submit-btn").click()
            expect(page.locator("#tx-amount-error")).to_be_visible()
            expect(page.locator("#tx-description")).to_have_value("Unsaved Coffee")
            _take_shot(page, capture_state, shot_dir / "02_dialog_validation_error.png")

            # 4. Fix amount and save income first
            page.locator('input[name="entry_type"][value="income"]').check(force=True)
            page.locator("#tx-amount").fill("85000.00")
            page.locator("#tx-description").fill("Monthly stipend and research fellowship")
            _take_shot(page, capture_state, shot_dir / "03_dialog_income_ready.png")
            page.locator("#tx-submit-btn").click()
            expect(dialog).not_to_be_visible()

            expect(page.locator("#overview-balance")).to_have_text("₹85,000.00")
            expect(page.locator("#overview-income")).to_have_text("₹85,000.00")
            expect(page.locator("#overview-empty")).to_be_hidden()

            # 5. Add expense + long description edge case + large monetary value check
            page.locator("#new-tx-btn").click()
            page.locator("#tx-amount").fill("1250.50")
            page.locator("#tx-description").fill(
                "Weekly groceries, fresh produce, and organic kitchen supplies for November"
            )
            page.locator("#tx-submit-btn").click()
            expect(dialog).not_to_be_visible()

            page.locator("#new-tx-btn").click()
            page.locator('input[name="entry_type"][value="income"]').check(force=True)
            page.locator("#tx-amount").fill("12345678.90")
            page.locator("#tx-description").fill(
                "Large institutional scholarship grant disbursement"
            )
            page.locator("#tx-submit-btn").click()
            expect(dialog).not_to_be_visible()

            expect(page.locator("#overview-balance")).to_have_text("₹1,24,29,428.40")
            expect(page.locator("#overview-expense")).to_have_text("₹1,250.50")
            expect(page.locator("#overview-surplus")).to_have_text("+₹1,24,29,428.40")
            expect(page.locator("#overview-empty")).to_be_hidden()
            expect(page.locator("#overview-table-wrap")).to_be_visible()
            _take_shot(page, capture_state, shot_dir / "04_overview_populated_light.png")

            # 6. Navigate to Transactions view
            page.locator('[data-nav-view="transactions"]').click()
            expect(page.locator("#view-transactions")).to_be_visible()
            expect(page.locator("#tx-empty")).to_be_hidden()
            expect(page.locator("#tx-history-body tr")).to_have_count(3)
            _take_shot(page, capture_state, shot_dir / "05_transactions_light.png")

            # 7. Navigate to Settings, switch to Dark appearance, and verify reload persistence
            page.locator('[data-nav-view="settings"]').click()
            expect(page.locator("#view-settings")).to_be_visible()
            page.locator('input[name="appearance"][value="dark"]').check(force=True)
            expect(page.locator('meta[name="color-scheme"]')).to_have_attribute("content", "dark")

            bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            assert bg != "rgb(247, 247, 244)", f"Dark mode background did not change: {bg}"
            _take_shot(page, capture_state, shot_dir / "06_settings_dark.png")

            # Reload page and verify dark appearance persisted in SQLite
            page.reload(wait_until="networkidle")
            expect(page.locator('meta[name="color-scheme"]')).to_have_attribute("content", "dark")
            expect(page.locator('input[name="appearance"][value="dark"]')).to_be_checked()

            # Check Overview in dark mode
            page.locator('[data-nav-view="overview"]').click()
            expect(page.locator("#overview-balance")).to_have_text("₹1,24,29,428.40")
            expect(page.locator('[data-nav-view="overview"]')).to_have_attribute(
                "aria-current", "page"
            )
            _take_shot(page, capture_state, shot_dir / "07_overview_populated_dark.png")

            # 8. Minimum supported viewport (900x600) zero horizontal overflow & unclipped table
            page.set_viewport_size({"width": 900, "height": 600})
            overflow = page.evaluate(
                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )
            assert overflow is False, "Horizontal overflow detected at 900x600 minimum viewport"
            table_overflow = page.evaluate(
                "document.querySelector('#overview-table-wrap').scrollWidth > document.querySelector('#overview-table-wrap').clientWidth"
            )
            assert table_overflow is False, "Recent activity table clipped horizontally at 900x600"
            _take_shot(page, capture_state, shot_dir / "08_overview_min_900x600_dark.png")

            page.locator('[data-nav-view="transactions"]').click()
            tx_table_overflow = page.evaluate(
                "document.querySelector('#tx-table-wrap').scrollWidth > document.querySelector('#tx-table-wrap').clientWidth"
            )
            assert tx_table_overflow is False, "Transactions table overflowed at 900x600"
            _take_shot(page, capture_state, shot_dir / "09_transactions_min_900x600_dark.png")

            # 9. Keyboard Tab navigation reaches focusable control cleanly & zero token residue on window
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement !== document.body")
            assert page.evaluate(
                "typeof window.__finoraPendingAuth === 'undefined' && typeof window.__finoraSetAuth === 'undefined'"
            )

            assert console_errors == [], f"Console errors observed: {console_errors}"
            assert page_errors == [], f"Uncaught page errors observed: {page_errors}"
        finally:
            context.close()
            browser.close()
