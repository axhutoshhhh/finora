# Finora — Engineering & Agent Rules

Finora is an offline-first, single-user personal finance desktop application for macOS (Apple Silicon). Keep these rules authoritative across all five development phases.

## 1. Approved Technology Stack
- **Backend**: Python (`>=3.13`, verified on `3.15.2`), Flask (app factory + Blueprints), `sqlite3`, `Decimal` for monetary input, `INTEGER` minor units (paise, `1 INR = 100`) in SQLite, Waitress local WSGI server.
- **Frontend**: Semantic HTML5, Jinja2, token-based CSS (`light-dark()`, system font stack, `tabular-nums`), modular vanilla JS, locally bundled Lucide SVGs (`ISC`), Chart.js in Phase 3+.
- **Desktop & Packaging**: `pywebview` (`WKWebView`), PyObjC only for native macOS menus / `NSAppearance` / navigation guards, PyInstaller (`--onedir` `.app` for `arm64`).
- **Prohibited**: React, Electron, Firebase, Docker, Tailwind CSS, cloud DBs, Node.js runtime in the packaged app, login/registration/telemetry/external runtime CDNs.

## 2. Architecture Boundaries
- Request flow: `macOS desktop window -> frontend -> secured local Flask API -> services -> repositories -> SQLite`.
- Keep routes thin (HTTP/validation/serialization only), services authoritative for business logic & financial calculations, and repositories responsible strictly for parameterized SQL.
- Never let frontend JS compute authoritative financial totals or touch SQLite directly.
- Never dump the application into a single file or introduce speculative abstractions.

## 3. Financial Correctness Invariants
- Never store monetary amounts as `float` / binary floating point. Parse input with `Decimal`, validate bounds and precision (`<= 2` decimal places for INR), store integer minor units.
- Use local calendar dates (`YYYY-MM-DD`) for `tx_date` and timezone-aware UTC ISO-8601 timestamps for technical metadata.
- Preserve double-entry/ledger invariants: income increases assets; expenses decrease assets or increase liabilities; transfers are not income/expenses; credit card payments are transfers; opening balances are not income; refunds net spending per documented rules; splits must sum exactly to parent amount; archived items preserve history.

## 4. UI & Anti-AI-Slop Restrictions
- Inspire from disciplined macOS tools (Things 3, Apple Numbers, Apple Wallet, Linear) without copying proprietary marks or layouts.
- **Prohibited**: purple/rainbow gradients, gradient blobs, glowing buttons, excessive shadows, card grids around every section, pill bloat, emoji nav icons, fake traffic lights, decorative illustrations, fake metrics, or nonfunctional buttons for unbuilt phases.
- Expose only implemented screens in navigation. Support `system`, `light`, and `dark` appearances without FOUC or color-only state indicators. Keep `900 x 600` usable without horizontal overflow.

## 5. Security & Privacy Rules
- Bind WSGI strictly to `127.0.0.1` on an ephemeral port. Disable Flask `debug` in packaged builds.
- Protect `/api/*` with an ephemeral per-launch secret (`X-Finora-Token`) transferred strictly in memory via origin-checked `WKWebView.run_js` into a private JS closure (never in URLs, HTML, `localStorage`, logs, or Git).
- Enforce `Host`, `Origin`, `Sec-Fetch-Site`, `Content-Type: application/json`, request size limits, strict CSP (`script-src 'self'`, zero inline scripts/styles), and safe DOM (`textContent` / `createElement`).
- Store mutable data strictly outside the repo and `.app` bundle (`~/Library/Application Support/Finora/` with `0700`/`0600` permissions; override via `FINORA_DATA_DIR` in dev/test).
- Do not falsely claim SQLite is encrypted at rest; document reliance on POSIX permissions and macOS FileVault.

## 6. Code Quality, Testing & Git Discipline
- Use Ruff (`ruff check`, `ruff format`), Bandit, `pip-audit`, and pytest (`unit`, `integration`, `e2e`).
- Automated tests must run only against temporary isolated databases and never touch user data.
- Never fabricate test results, build outputs, or screenshots. Never commit personal financial records, secrets, `.venv/`, `build/`, or `dist/`.
- Respect phase gates: do not jump into future-phase modules or publish to a remote repository without explicit user approval.

## 7. Authoritative Documentation
See `docs/` for specifications: `product-spec.md`, `architecture.md`, `database.md`, `financial-rules.md`, `design-system.md`, `security-model.md`, `api.md`, `test-plan.md`, `acceptance-criteria.md`, `progress.md`, `known-issues.md`, and `docs/decisions/`.
