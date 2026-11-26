# Changelog

All notable changes to Finora are documented in this file.

## [1.0.0] - 2026-11-27 (Phase 5 — Stable Release & Public Distribution)

### Added
- MIT `LICENSE`, `CONTRIBUTING.md`, static GitHub Pages showcase (`site/`), and university evaluation/viva documentation.
- `pytest-cov` branch & line coverage reporting (`78%` overall across `3,778` statements / `1,202` branches).
- Final `Finora-v1.0.0-macos-arm64.zip` release archive and `SHA256SUMS.txt`.

## [0.3.0] - 2026-11-27 (Phase 3 — Advanced Features, Analytics & Financial Intelligence)

### Added
- **Migration `0003_phase3_intelligence.sql`**: Added `savings_goals`, `goal_allocations`, `recurring_rules`, `recurring_occurrences`, `notification_events`, `notification_preferences`, `categorization_rules`, `import_batches`, and `import_batch_rows`.
- **Analytics & Reports**: Implemented `analytics_service.py`, `analytics_repo.py`, locally bundled `Chart.js 4.4.7` UMD (`app/static/vendor/chart.umd.min.js`), and `/api/analytics/*` endpoints.
- **Advisory Engine & Forecasting**: Implemented deterministic deduplicated advisory rules (`advisory_service.py`), pace-based monthly spending forecasts (`forecasting_service.py`), and `/api/insights` + `/api/notifications*`.
- **Savings Goals & Recurring**: Implemented ledger-backed goal allocations (`goal_service.py`), recurring rules/subscriptions with Jan 31 / Feb 29 anchor preservation and atomic idempotent posting (`recurring_service.py`).
- **Calendar & Auto-Categorization**: Implemented monthly financial calendar (`calendar_service.py`) and merchant/description rule engine (`categorization_service.py`).
- **Import, Export, Backup & Demo Workspace**: Implemented bounded CSV import preview/commit (`import_service.py`), formula-injection-safe CSV & offline PDF 1.4 export (`export_service.py`), SHA-256 ZIP backup & staged restore (`backup_service.py`), and isolated synthetic demo workspace (`workspace_service.py`).
- **Benchmarks**: Added `benchmarks/baseline_phase3.py` (0–10k datasets).

## [0.2.0] - 2026-11-27 (Phase 2 — Core Financial Functionality)

### Added
- **Database Migration `0002_phase2_core_financials.sql`**: Added account types/credit limits/archival, `transactions.parent_transaction_id` (linked refunds), `tags`, `transaction_tags`, `budgets`, `budget_settings`, `attachments`, Phase 2 indexes, automatic pre-migration `sqlite3.Connection.backup()` (`0700`/`0600`), and post-migration `PRAGMA foreign_key_check` / `integrity_check`.
- **Accounts & Transfers**: Full support for `cash`, `bank`, `savings`, `wallet`, and `credit_card` accounts with credit limit/utilization/overpayment surplus tracking, archival (`confirm_nonzero`) and restore, and asset-to-asset / asset-to-credit-card transfers (excluding credit card outbound cash advances).
- **Splits, Refunds, Editing & Bulk Actions**: Multi-category split transactions, partial/full/split linked refunds with cross-month net spending and delete/shrink locks, optimistic-concurrency `PATCH` (`expected_revision`), soft delete/restore/purge, parameterized `json_each(?)` search/filtering/sorting/pagination, and atomic bulk operations.
- **Categories, Tags & Attachments**: Custom categories (preserving 10 system expense slugs and kind immutability), normalized tags, and receipt attachments (`<= 5 MiB` PNG/JPEG/PDF magic-byte verification, SHA-256 checksum, `0600` UUID storage).
- **Monthly Budgets & Rollover**: Category monthly limits, overall monthly spending cap with allocation-exceeded warning, unconfigured vs `₹0.00` distinction, up-to-60-month consecutive rollover, and `copy-previous`.
- **Desktop UI & Benchmarks**: Expanded 5-screen desktop shell (`Overview`, `Transactions`, `Accounts`, `Budgets`, `Settings`), keyboard shortcuts (`Cmd+1..4`, `Cmd+,`, `Cmd+N`, `Cmd+F`, `Cmd+Z` undo), native `<dialog>` workflows, and repeatable 0–100k dataset benchmark (`benchmarks/baseline_phase2.py`).

### Fixed (Independent Phase 2 Audit)
- Enforced the 64 KiB JSON body limit on chunked/unknown `Content-Length` requests alongside `MAX_ATTACHMENT_HTTP_BYTES` for scoped attachment uploads.
- Preserved `opening_balance_minor` magnitude when updating only `opening_balance_direction` on a credit card account.
- Checked `idempotency_key` replay/conflict before active-account/category validation so retries succeed even after archival.
- Replaced float division with integer paise formatting when preserving refund allocations on edit, clamped negative-spend `usage_percent` at `0.0`, and fixed Settings `database_path` display.

## [0.1.0] - 2026-11-26 (Phase 1 — Foundation, Architecture & Design)

### Added
- Modular Python/Flask architecture (`app/routes`, `app/services`, `app/repositories`, `app/migrations`, `app/utils`) and native macOS `pywebview` launcher (`desktop/`).
- Ledger-ready SQLite schema (`0001_initial_schema.sql`) with `accounts`, `categories`, `transactions`, `postings`, `settings`, and `schema_migrations`.
- Exact `Decimal` monetary parser, minor-unit integer storage (`paise`), and Indian INR grouping (`₹1,25,000.00`).
- Idempotent seeding of 10 predefined expense categories, 7 separate income categories, default `Cash` account (`₹0.00`), and `system` appearance setting.
- Secured local API endpoints (`/health`, `/api/overview`, `/api/transactions`, `/api/categories`, `/api/accounts`, `/api/settings`, `/api/settings/appearance`) with ephemeral per-launch token authentication and `Host`/`Origin`/`Sec-Fetch-Site`/CSP enforcement.
- Original Finora SVG branding, macOS `Finora.icns` application icon, locally bundled Lucide SVGs, token-based light/dark/system CSS design system, and accessible `<dialog>` transaction creation flow.
- Native macOS menu integration (`File -> New Transaction` with `Cmd+N`), `NSWindow` appearance sync, single-instance `flock` guard, and early Apple Silicon (`arm64`) PyInstaller `.app` build configuration (`finora.spec`, `scripts/build_app.sh`).
- Automated test suites (`tests/unit`, `tests/integration`, `tests/e2e`), Ruff/Bandit/`pip-audit` checks, GitHub Actions CI workflow, and Phase 1 baseline performance benchmark (`benchmarks/baseline_phase1.py`).
