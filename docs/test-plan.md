# Finora — Phase 1 Test Plan

## 1. Test Isolation Guarantee
All automated tests execute against ephemeral `tmp_path` SQLite databases (`FINORA_DATA_DIR` / `DB_PATH` overridden per test). Automated tests **never** touch `~/Library/Application Support/Finora/`.

## 2. Test Pyramid
1. **Unit & Database Tests (`tests/unit/`)**:
   - `test_money.py`: `Decimal` parsing, rejection of `NaN`/`Infinity`/scientific notation/excess decimals/`<=0`/over-limit, exact paise conversion, Indian INR formatting.
   - `test_time.py`: `YYYY-MM-DD` local calendar date validation, month bounds calculation, UTC timestamp generation.
   - `test_database.py`: Schema creation, `schema_migrations` tracking, repeated migration idempotency, 10 expense + 7 income categories seeded without mixing, default `Cash` account seeded once, `PRAGMA foreign_keys = ON`, invalid constraints rejected, atomic rollback on error.
2. **Backend Integration & Security Tests (`tests/integration/`)**:
   - `test_api_health_and_security.py`: `/health` minimal payload, missing/wrong `X-Finora-Token` (`401`), invalid `Host` (`403`), cross-origin `Origin` (`403`), `Sec-Fetch-Site: cross-site` (`403`), missing CORS headers, strict CSP headers, payload size limit (`413`), unsupported content-type (`415`).
   - `test_api_transactions.py`: Empty overview (`₹0.00`), expense & income creation, category/entry-type mismatch rejection, nonexistent/archived IDs rejected, idempotency protection, overview math updates, persistence across fresh app factory instance, settings appearance persistence.
3. **End-to-End WebKit Tests (`tests/e2e/`)**:
   - Runs Playwright WebKit against a live Waitress test server on `127.0.0.1:<free_port>` using isolated temp DB and test-injected `window.pywebview.api.get_launch_token`.
   - Verifies empty state, opening `<dialog>`, recording expense & income, validation error preservation, canceling dialog, Overview balance/summary updates, Transactions view, Light/Dark appearance switch + reload persistence, `1200x780` & `900x600` zero horizontal overflow, and keyboard navigation (`Tab`, `Esc`).
4. **Live Desktop & Packaged `.app` Verification**:
   - Direct execution of `python main.py` (`pywebview`) and `dist/Finora.app` (`PyInstaller`) on macOS `27.0.1` (`arm64`) verifying launch, resizing, native menus (`Cmd+N`, `Quit`), persistence, duplicate-instance guard, and clean process teardown.
