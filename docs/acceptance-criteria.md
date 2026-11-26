# Finora — Phase 1 Acceptance Criteria Tracker

Status values: `Passed`, `Failed`, `Blocked`, `N/A`. Updated strictly from observed Phase 1 verification evidence.

## Architecture
- [x] Modular project architecture exists (`Passed` — `app/`, `desktop/`, `tests/`, `docs/`, `scripts/`, `benchmarks/`)
- [x] Flask application factory works (`Passed` — `app/__init__.py:create_app`)
- [x] Routes, services and database access are separated (`Passed` — thin `app/routes/`, authoritative `app/services/`, parameterized `app/repositories/`)
- [x] Persistent project instructions exist (`Passed` — `AGENTS.md`, `GEMINI.md`)
- [x] Future phase requirements are documented (`Passed` — `docs/product-spec.md`, `docs/database.md`, `docs/financial-rules.md`)
- [x] Dependencies are reproducible (`Passed` — `requirements.lock`, `requirements-dev.lock`)
- [x] No unnecessary frameworks have been introduced (`Passed` — Python/Flask/Waitress/SQLite/vanilla JS/CSS/pywebview only)

## Desktop Application
- [x] Native macOS window launches successfully (`Passed` — verified via `main.py` and `dist/Finora.app`)
- [x] Application starts without a manually launched Flask server (`Passed` — embedded Waitress started/stopped by `desktop/launcher.py`)
- [x] Window resizing works (`Passed` — `min_size=(900, 600)`, `resizable=True`, verified `win.resize(900, 600)` in live `pywebview` + `900×600` WebKit layout)
- [x] Native window controls work (`Passed` — Cocoa `NSTitledWindowMask | NSClosableWindowMask | NSMiniaturizableWindowMask | NSResizableWindowMask`, tested close/quit lifecycle)
- [x] Server readiness is handled correctly (`Passed` — bounded `/health` polling via `wait_for_server_ready` and timeout error test)
- [x] Startup failures have meaningful error handling (`Passed` — `StartupError`/`DatabaseError`/`AssetMissingError` mapped to native `NSAlert`)
- [x] Application shuts down cleanly (`Passed` — `stop_waitress_server` trigger shutdown + `SIGTERM` and AppleEvent quit leave 0 orphan processes)
- [x] Duplicate-instance behavior is handled (`Passed` — `SingleInstanceGuard` `flock` verified in unit test and packaged `Finora.app` double-launch test)
- [x] Early ARM64 application bundle builds (`Passed` — `dist/Finora.app`, `Mach-O 64-bit executable arm64`, `34M`)
- [x] Packaged application launch has been tested (`Passed` — tested direct binary + `open -n -a dist/Finora.app` + AppleEvent quit)

## Design
- [x] Original Finora branding exists (`Passed` — `assets/branding/finora-{mark,wordmark}-{light,dark}.svg`)
- [x] Application icon is prepared (`Passed` — `assets/branding/Finora.icns` generated from supersampled iconset)
- [x] No generic square in-interface logo (`Passed` — open SVG mark in sidebar and Settings)
- [x] No purple gradients or prohibited AI-style design (`Passed` — verified via CSS inspection and rendered screenshots)
- [x] Reusable design system exists (`Passed` — `tokens.css`, `base.css`, `layout.css`, `components.css`, `icons.css`)
- [x] Desktop shell is visually consistent (`Passed` — inspected across light/dark and `1200×780`/`900×600`)
- [x] Overview screen is functional (`Passed` — real DB balance, monthly income/expense/surplus, recent activity, empty state)
- [x] Transaction interface is functional (`Passed` — `<dialog>` expense/income creation + Transactions history table)
- [x] Settings screen is functional (`Passed` — System/Light/Dark appearance, defaults, storage paths, About)
- [x] Light appearance works (`Passed` — verified visually in WebKit)
- [x] Dark appearance works (`Passed` — verified visually in WebKit and live `WKWebView`)
- [x] Appearance preference persists (`Passed` — verified across page reloads and fresh app restart)
- [x] Minimum window size (`900x600`) remains usable (`Passed` — verified zero overflow on Overview & Transactions at `900×600`)
- [x] Keyboard and focus states are implemented (`Passed` — `:focus-visible`, skip link, `Esc`, `Cmd+N`, `Tab` verified)
- [x] No deceptive or nonfunctional visible controls (`Passed` — only implemented Overview, Transactions, Settings exposed)

## Financial Foundation
- [x] SQLite database initializes successfully (`Passed` — WAL mode, `0600` permissions, Unicode/space paths verified)
- [x] Versioned migrations work (`Passed` — `schema_migrations` tracking and atomic DDL rollback verified)
- [x] Exactly ten predefined expense categories are seeded (`Passed` — verified in DB and API)
- [x] Income categories are separate (`Passed` — 7 income categories separated by `kind='income'` and validated on write)
- [x] Default Cash account is initialized (`Passed` — `Cash`, `INR`, `opening_balance_minor=0`)
- [x] Repeated launches do not duplicate default records (`Passed` — repeated `initialize_database()` idempotency test)
- [x] Monetary amounts use integer minor units (`Passed` — `INTEGER` paise in SQLite, `Decimal` input parsing, `float` rejected)
- [x] Basic expense creation works (`Passed` — verified in unit, integration, WebKit E2E, and live `WKWebView`)
- [x] Basic income creation works (`Passed` — verified in unit, integration, and WebKit E2E)
- [x] Invalid monetary values are rejected (`Passed` — `NaN`, `Infinity`, `1e5`, `10,50`, `<=0`, `>2` decimals, floats rejected)
- [x] Overview values reflect stored transactions (`Passed` — verified across synthetic multi-entry fixtures and UI)
- [x] Transactions persist across restarts (`Passed` — verified across fresh `create_app()` and desktop relaunch)
- [x] Test data is separated from real user data (`Passed` — tests run exclusively inside `tmp_path`)

## Security
- [x] Local server binds only to loopback (`127.0.0.1`) (`Passed` — verified via `lsof` on live desktop process and Waitress config)
- [x] Financial API routes reject unauthorized requests (`Passed` — `401` on missing/wrong `X-Finora-Token`)
- [x] Appropriate origin and Host validation exists (`Passed` — `403` on invalid `Host`, `Origin`, `Sec-Fetch-Site`)
- [x] Parameterized SQL is used (`Passed` — all queries parameterized, verified by review and Bandit)
- [x] Untrusted content is safely rendered (`Passed` — `textContent`/`createElement` only, zero `innerHTML`)
- [x] No external runtime assets are required (`Passed` — Lucide SVGs and CSS/JS bundled locally; zero external calls)
- [x] Debug mode is disabled in packaged builds (`Passed` — `DEBUG=False`, `webview.start(..., debug=False)`, `OPEN_DEVTOOLS_IN_DEBUG=False`)
- [x] Local data storage is outside the repository (`Passed` — `~/Library/Application Support/Finora/`, verified 0 `.sqlite3` inside `Finora.app`)
- [x] No secrets or personal financial records are committed (`Passed` — verified via `git ls-files`)
- [x] Security limitations are documented (`Passed` — `SECURITY.md` and `docs/security-model.md`)

## Testing & Quality
- [x] Unit tests pass (`Passed` — `tests/unit/`, including DB, monetary, time, service, and desktop lifecycle tests)
- [x] Database tests pass (`Passed` — `tests/unit/test_database.py`)
- [x] Backend integration tests pass (`Passed` — `tests/integration/`)
- [x] Frontend tests pass (`Passed` — `tests/e2e/test_webkit_e2e.py` on Playwright WebKit)
- [x] Actual desktop behavior has been verified where possible (`Passed` — live `pywebview` `WKWebView` + `dist/Finora.app` launch/quit verified; manual human trackpad/Spaces interaction left for user evaluation)
- [x] Visual inspection has been performed (`Passed` — screenshots inspected across light/dark, empty/populated, validation errors, and `900×600`)
- [x] Discovered release-blocking Phase 1 defects are resolved (`Passed` — fixed CSP `eval()`, `[hidden]` flex override, Waitress teardown, `900×600` table fit, atomic DDL, `"10,50"` regex)
- [x] Linting passes (`Passed` — `ruff check` and `ruff format --check` pass with 0 errors)
- [x] Dependency audit results are recorded (`Passed` — `pip-audit -r requirements.lock` and `-r requirements-dev.lock` reported 0 vulnerabilities; `bandit` reported 0 issues)
- [x] Preliminary performance methodology is documented (`Passed` — `benchmarks/baseline_phase1.py` + `README.md`)

## Documentation & Git
- [x] `README.md` accurately describes current functionality (`Passed`)
- [x] Architecture is documented (`Passed` — `docs/architecture.md`, `docs/decisions/`)
- [x] Database schema is documented (`Passed` — `docs/database.md`)
- [x] Financial rules are documented (`Passed` — `docs/financial-rules.md`)
- [x] API contracts are documented (`Passed` — `docs/api.md`)
- [x] Design system is documented (`Passed` — `docs/design-system.md`)
- [x] Security model is documented (`Passed` — `docs/security-model.md`)
- [x] Test plan exists (`Passed` — `docs/test-plan.md`)
- [x] Known issues are documented (`Passed` — `docs/known-issues.md`)
- [x] Git history contains meaningful development commits (`Passed` — incremental Milestone commits + local `v0.1.0` tag)
- [x] Repository remains unpublished (`Passed` — `git remote -v` is empty)
- [x] Phase 2 handover notes exist (`Passed` — recorded in Phase 1 completion handover & docs)

---

# Finora — Phase 2 Acceptance Criteria Tracker (`v0.2.0`)

## Database Migration & Integrity
- [x] `0002_phase2_core_financials.sql` migrates existing Phase 1 databases without data loss (`Passed` — `tests/unit/test_database.py` & `dist/Finora.app` synthetic Phase 1 DB migration test)
- [x] Pre-migration `sqlite3.Connection.backup()` runs automatically with `0700`/`0600` permissions and `PRAGMA quick_check` (`Passed`)
- [x] Post-migration `PRAGMA foreign_key_check` and `PRAGMA integrity_check` pass (`Passed`)

## Accounts & Transfers
- [x] All 5 account types (`cash`, `bank`, `savings`, `wallet`, `credit_card`) supported with accurate asset/liability/net-worth math (`Passed`)
- [x] Credit card credit limit, available credit, and overpayment surplus tracked accurately (`Passed`)
- [x] Account type locked after postings exist (`ConflictError`), non-zero archival requires `confirm_nonzero=True`, and historical totals remain intact (`Passed`)
- [x] Transfers (`asset -> asset`, `asset -> credit_card`) are excluded from income/expense totals and reject outbound `credit_card` cash advances (`Passed`)

## Transactions, Splits, Refunds, Search & Bulk
- [x] Split transactions enforce exact sum-to-parent invariant and reject duplicate categories (`Passed`)
- [x] Partial, full, and split refunds enforce remaining-refundable cap, date >= parent, cross-month net spending, and parent delete/shrink locks (`Passed`)
- [x] Optimistic-concurrency `PATCH` (`expected_revision`), soft delete, undo restore, and purge work atomically (`Passed`)
- [x] Search, filters, sorting, pagination (`json_each(?)`), and atomic bulk actions work across all filter dimensions (`Passed`)

## Categories, Tags & Attachments
- [x] Custom categories preserve 10 system expense slugs and immutable kind (`Passed`)
- [x] Normalized tags and receipt attachments (`<= 5 MiB` PNG/JPEG/PDF magic-byte verification, SHA-256, `0600`) work end-to-end (`Passed`)

## Monthly Budgets & Rollover
- [x] Category & overall monthly budgets distinguish unconfigured vs `₹0.00` limits, warn on allocation > overall, and compute deterministic up-to-60-month rollover (`Passed`)
- [x] `copy-previous` and randomized 45-step financial invariant tests pass (`Passed`)

## Desktop UI, Security & Release Verification
- [x] All 5 screens (`Overview`, `Transactions`, `Accounts`, `Budgets`, `Settings`), shortcuts (`Cmd+1..4`, `Cmd+,`, `Cmd+N`, `Cmd+F`, `Cmd+Z`), and `900×600` zero-overflow WebKit layout verified (`Passed`)
- [x] Independent audit (`15a7eb0b-5496-4567-a4d8-860e24d7da68`) findings all fixed and regression-tested (`Passed`)
- [x] `ruff`, `bandit`, `pip-audit`, `pytest`, `benchmarks/baseline_phase2.py`, and `dist/Finora.app` (`v0.2.0`) verification pass (`Passed`)
