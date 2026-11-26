# Changelog

All notable changes to Finora are documented in this file.

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
