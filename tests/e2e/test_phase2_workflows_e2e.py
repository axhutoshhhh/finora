"""Comprehensive Playwright WebKit E2E test covering all 18 Phase 2 UI screens & workflows."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.e2e.test_webkit_e2e import _open_webkit_page, _take_shot


@pytest.mark.e2e
def test_phase2_complete_ui_workflows_and_screenshots(live_server, tmp_path: Path) -> None:
    base_url = live_server["base_url"]
    token = live_server["token"]
    shot_env = os.environ.get("FINORA_E2E_SCREENSHOT_DIR")
    shot_dir = Path(shot_env) if shot_env else tmp_path / "phase2_shots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser, context, page, console_errors, page_errors, capture_state = _open_webkit_page(
            p, base_url, token, width=1200, height=780
        )
        try:
            # 1. Empty overview
            expect(page.locator("#overview-balance")).to_have_text("₹0.00")
            _take_shot(page, capture_state, shot_dir / "p2_01_overview_empty_light.png")

            # 2. Navigate to Accounts -> create Bank + Credit Card
            page.locator('[data-nav-view="accounts"]').click()
            expect(page.locator("#view-accounts")).to_be_visible()

            page.locator("#accounts-new-btn").click()
            page.locator("#account-name").fill("HDFC Salary Bank")
            page.locator("#account-type").select_option("bank")
            page.locator("#account-opening-balance").fill("45000.00")
            page.locator("#account-submit-btn").click()
            expect(page.locator("#account-dialog")).not_to_be_visible()

            page.locator("#accounts-new-btn").click()
            page.locator("#account-name").fill("Millennia Credit Card")
            page.locator("#account-type").select_option("credit_card")
            page.locator("#account-opening-balance").fill("0.00")
            page.locator("#account-credit-limit").fill("75000.00")
            page.locator("#account-submit-btn").click()
            expect(page.locator("#account-dialog")).not_to_be_visible()

            expect(page.locator("#accounts-assets-list")).to_contain_text("HDFC Salary Bank")
            expect(page.locator("#accounts-cards-list")).to_contain_text("Millennia Credit Card")
            _take_shot(page, capture_state, shot_dir / "p2_10_accounts_overview.png")

            # Click HDFC Salary Bank detail
            page.locator("#accounts-assets-list button", has_text="HDFC Salary Bank").click()
            expect(page.locator("#account-detail-panel")).to_contain_text("HDFC Salary Bank")
            _take_shot(page, capture_state, shot_dir / "p2_11_account_detail.png")

            # Click Credit Card detail
            page.locator("#accounts-cards-list button", has_text="Millennia Credit Card").click()
            expect(page.locator("#account-detail-panel")).to_contain_text("Credit Limit")
            _take_shot(page, capture_state, shot_dir / "p2_12_credit_card_account.png")

            # 3. Settings -> Create a Tag & Custom Category
            page.locator('[data-nav-view="settings"]').click()
            page.locator("#tab-settings-tags").click()
            page.locator("#settings-tag-name-input").fill("Hostel")
            page.locator("#settings-tag-create-form button[type='submit']").click()
            expect(page.locator("#settings-tags-body")).to_contain_text("#Hostel")

            page.locator("#tab-settings-categories").click()
            expect(page.locator("#settings-categories-body")).to_contain_text("Food & Dining")
            _take_shot(page, capture_state, shot_dir / "p2_15_category_management.png")

            # 4. New Expense dialog
            page.locator("#new-tx-btn").click()
            page.locator("#tx-amount").fill("2600.00")
            page.locator("#tx-account").select_option(label="HDFC Salary Bank")
            page.locator("#tx-merchant").fill("Campus Canteen")
            page.locator("#tx-description").fill("Monthly meal pass")
            _take_shot(page, capture_state, shot_dir / "p2_04_new_expense_dialog.png")
            page.locator("#tx-submit-btn").click()
            expect(page.locator("#tx-dialog")).not_to_be_visible()

            # 5. New Income dialog
            page.locator("#new-tx-btn").click()
            page.locator('input[name="entry_type"][value="income"]').check(force=True)
            page.locator("#tx-amount").fill("30000.00")
            page.locator("#tx-account").select_option(label="HDFC Salary Bank")
            page.locator("#tx-merchant").fill("Research Lab")
            page.locator("#tx-description").fill("Monthly stipend")
            _take_shot(page, capture_state, shot_dir / "p2_05_new_income_dialog.png")
            page.locator("#tx-submit-btn").click()
            expect(page.locator("#tx-dialog")).not_to_be_visible()

            # 6. Credit card purchase (Split transaction across 2 categories!)
            page.locator("#new-tx-btn").click()
            page.locator("#tx-amount").fill("1000.00")
            page.locator("#tx-account").select_option(label="Millennia Credit Card")
            page.locator("#tx-payment-method").select_option("credit_card")
            page.locator("#tx-merchant").fill("Reliance Smart")
            page.locator("#tx-description").fill("Groceries and study desk lamp")
            page.locator("#tx-split-toggle-btn").click()
            split_inputs = page.locator("#tx-split-rows .split-row-item input")
            split_inputs.nth(0).fill("650.00")
            split_inputs.nth(1).fill("350.00")
            page.locator("#tx-split-rows .split-row-item select").nth(1).select_option(
                label="Shopping"
            )
            page.locator('#tx-tags-picker input[type="checkbox"]').first.check()
            _take_shot(page, capture_state, shot_dir / "p2_09_split_dialog.png")
            page.locator("#tx-submit-btn").click()
            expect(page.locator("#tx-dialog")).not_to_be_visible()

            # 7. Transfer dialog (repay ₹400 to Credit Card)
            page.locator('[data-nav-view="overview"]').click()
            page.locator("#overview-transfer-btn").click()
            expect(page.locator("#tx-transfer-accounts-row")).to_be_visible()
            page.locator("#tx-amount").fill("400.00")
            page.locator("#tx-from-account").select_option(label="HDFC Salary Bank")
            page.locator("#tx-to-account").select_option(label="Millennia Credit Card")
            page.locator("#tx-description").fill("Card bill repayment")
            _take_shot(page, capture_state, shot_dir / "p2_07_transfer_dialog.png")
            page.locator("#tx-submit-btn").click()
            expect(page.locator("#tx-dialog")).not_to_be_visible()

            # 8. Transactions -> Refund dialog on Campus Canteen expense (₹200 partial refund)
            page.locator('[data-nav-view="transactions"]').click()
            expect(page.locator("#tx-history-body tr")).to_have_count(4)
            _take_shot(page, capture_state, shot_dir / "p2_03_transactions.png")

            canteen_row = page.locator("#tx-history-body tr", has_text="Campus Canteen")
            canteen_row.locator('button[aria-label="Record refund"]').click()
            expect(page.locator("#refund-dialog")).to_be_visible()
            page.locator("#refund-amount").fill("200.00")
            page.locator("#refund-description").fill("Canteen coupon credit")
            _take_shot(page, capture_state, shot_dir / "p2_08_refund_dialog.png")
            page.locator("#refund-submit-btn").click()
            expect(page.locator("#refund-dialog")).not_to_be_visible()

            # Edit transaction dialog (click Edit on Research Lab income)
            lab_row = page.locator("#tx-history-body tr", has_text="Research Lab")
            lab_row.locator('button[aria-label="Edit transaction"]').click()
            expect(page.locator("#tx-dialog")).to_be_visible()
            _take_shot(page, capture_state, shot_dir / "p2_06_edit_transaction_dialog.png")
            page.locator("#tx-cancel-btn").click()

            # 9. Budgets screen -> set Food & Dining ₹3,000 + overall ₹20,000
            page.locator('[data-nav-view="budgets"]').click()
            expect(page.locator("#view-budgets")).to_be_visible()

            food_row = page.locator("#budgets-table-body tr", has_text="Food & Dining")
            food_row.locator("button", has_text="Set Limit").click()
            expect(page.locator("#budget-dialog")).to_be_visible()
            page.locator("#budget-limit-input").fill("3000.00")
            page.locator("#budget-rollover-checkbox").check()
            _take_shot(page, capture_state, shot_dir / "p2_14_budget_editing.png")
            page.locator("#budget-submit-btn").click()
            expect(page.locator("#budget-dialog")).not_to_be_visible()

            # Note: Net Food & Dining spend = ₹2,600 - ₹200 refund + ₹650 split = ₹3,050 (> ₹3,000 limit!)
            expect(
                page.locator("#budgets-table-body tr", has_text="Food & Dining")
            ).to_contain_text("Over budget")
            page.locator("#budgets-edit-overall-btn").click()
            page.locator("#budget-limit-input").fill("20000.00")
            page.locator("#budget-submit-btn").click()
            expect(page.locator("#budget-dialog")).not_to_be_visible()
            _take_shot(page, capture_state, shot_dir / "p2_13_budgets_overview.png")

            # 10. Populated Overview check (Net worth = ₹45k Bank + ₹30k Inc - ₹2.6k Exp + ₹200 Ref - ₹1k CC = ₹71,600)
            page.locator('[data-nav-view="overview"]').click()
            expect(page.locator("#overview-balance")).to_have_text("₹71,600.00")
            _take_shot(page, capture_state, shot_dir / "p2_02_overview_populated.png")

            # 11. Search & filtering on Transactions
            page.locator('[data-nav-view="transactions"]').click()
            page.locator("#tx-filters-toggle-btn").click()
            page.locator("#tx-search-input").fill("Reliance")
            expect(page.locator("#tx-history-body tr")).to_have_count(1)
            _take_shot(page, capture_state, shot_dir / "p2_16_transactions_search_filter.png")
            page.locator("#tx-filters-reset-btn").click()
            expect(page.locator("#tx-history-body tr")).to_have_count(5)

            # 12. Soft delete & Undo banner
            xfer_row = page.locator("#tx-history-body tr", has_text="Card bill repayment")
            xfer_row.locator('button[aria-label="Delete transaction"]').click()
            expect(page.locator("#global-success-banner")).to_be_visible()
            expect(page.locator("#global-undo-btn")).to_be_visible()
            _take_shot(page, capture_state, shot_dir / "p2_18_delete_undo_feedback.png")
            page.locator("#global-undo-btn").click()
            expect(page.locator("#tx-history-body tr")).to_have_count(5)

            # 13. Dark mode settings + 900x600 zero-overflow check on Accounts & Budgets
            page.locator('[data-nav-view="settings"]').click()
            page.locator("#tab-settings-general").click()
            page.locator('input[name="appearance"][value="dark"]').check(force=True)
            expect(page.locator('meta[name="color-scheme"]')).to_have_attribute("content", "dark")
            _take_shot(page, capture_state, shot_dir / "p2_17_settings_dark.png")

            page.set_viewport_size({"width": 900, "height": 600})
            for nav in ("overview", "transactions", "accounts", "budgets", "settings"):
                page.locator(f'[data-nav-view="{nav}"]').click()
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                )
                assert overflow is False, f"Horizontal overflow on {nav} at 900x600"

            assert console_errors == [], f"Console errors: {console_errors}"
            assert page_errors == [], f"Uncaught page errors: {page_errors}"
        finally:
            context.close()
            browser.close()
