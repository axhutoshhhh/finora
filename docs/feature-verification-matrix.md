# Finora — Feature Verification Matrix (`v1.0.0`)

| Feature | Entry Point | Backend / Service | Frontend | Automated Test | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Overview Dashboard | `/` (`Overview`) | `overview_service.py` | `render.js`, `main.js` | `test_all_ten_sections_interactive_webkit` | **Verified functional** |
| Transactions (CRUD, Splits, Refunds, Bulk) | `/transactions` | `transaction_service.py` | `dialog.js`, `render.js` | `test_transactions_advanced.py`, `test_phase2_workflows_e2e.py` | **Verified functional** |
| Accounts & Transfers (5 types, Credit Card) | `/accounts` | `account_service.py` | `render.js`, `dialog.js` | `test_accounts_and_transfers.py` | **Verified functional** |
| Budgets & Rollover (10 categories + overall) | `/budgets` | `budget_service.py` | `render.js` | `test_budgets_and_rollover.py` | **Verified functional** |
| Interactive Reports & Chart.js | `/reports` | `analytics_service.py` | `phase3.js`, `chart.umd.min.js` | `test_api_analytics.py`, `test_all_ten_sections_interactive_webkit` | **Verified functional** |
| Savings Goals & Allocations | `/goals` | `goal_service.py` | `phase3.js` | `test_goals_and_recurring.py` | **Verified functional** |
| Recurring Rules & Subscriptions | `/recurring` | `recurring_service.py` | `phase3.js` | `test_goals_and_recurring.py`, `test_phase4_audit_regressions.py` | **Verified functional** |
| Financial Calendar | `/calendar` | `calendar_service.py` | `phase3.js` | `test_calendar_and_categorization.py` | **Verified functional** |
| Advisory Insights & Forecasts | `/insights` | `advisory_service.py`, `forecasting_service.py` | `phase3.js` | `test_advisory_and_forecasting.py` | **Verified functional** |
| Categorization Rules | `/api/categorization-rules*` | `categorization_service.py` | Settings / API | `test_calendar_and_categorization.py` | **Verified functional** |
| CSV Import/Export & PDF Reports | `/api/import/*`, `/api/export/*` | `import_service.py`, `export_service.py` | API / Reports | `test_import_export_backup.py` | **Verified functional** |
| SHA-256 Backup & Staged Restore | `/api/backups*` | `backup_service.py` | Settings / API | `test_import_export_backup.py`, `test_phase4_audit_regressions.py` | **Verified functional** |
| Isolated Demo Workspace | `/api/workspaces*` | `workspace_service.py` | `app.html` | `test_workspace_isolation.py`, `test_phase4_audit_regressions.py` | **Verified functional** |
