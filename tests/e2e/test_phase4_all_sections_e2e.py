"""Playwright WebKit E2E verification across all 10 Finora sections (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from app.services import workspace_service


@pytest.mark.e2e
def test_all_ten_sections_interactive_webkit(live_server) -> None:
    base_url = live_server["base_url"]
    token = live_server["token"]
    db_path = Path(live_server["data_dir"]) / "finance.sqlite3"
    # Seed demo data into the test server's isolated DB so all 10 sections have rich data
    workspace_service.seed_demo_workspace(Path(db_path))

    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        context = browser.new_context(viewport={"width": 1200, "height": 780})
        context.add_init_script(f"window.__finoraPendingAuth = {token!r};")
        page = context.new_page()

        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        try:
            page.goto(base_url, wait_until="domcontentloaded")
            expect(page.locator("#overview-recent-body tr").first).to_be_visible()

            for nav in (
                "transactions",
                "accounts",
                "budgets",
                "reports",
                "goals",
                "recurring",
                "calendar",
                "insights",
                "settings",
                "overview",
            ):
                page.locator(f'[data-nav-view="{nav}"]').click()
                expect(page.locator(f"#view-{nav}")).to_be_visible()

            # Verify Reports populated
            page.locator('[data-nav-view="reports"]').click()
            expect(page.locator("#reports-summary-row .summary-chip").first).to_be_visible()

            # Verify 900x600 zero horizontal overflow across all 10 sections
            page.set_viewport_size({"width": 900, "height": 600})
            for nav in (
                "overview",
                "transactions",
                "accounts",
                "budgets",
                "reports",
                "goals",
                "recurring",
                "calendar",
                "insights",
                "settings",
            ):
                page.locator(f'[data-nav-view="{nav}"]').click()
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                )
                assert overflow is False, f"Horizontal overflow on {nav} at 900x600"

            assert console_errors == [], f"Console errors: {console_errors}"
            assert page_errors == [], f"Page errors: {page_errors}"
        finally:
            context.close()
            browser.close()
