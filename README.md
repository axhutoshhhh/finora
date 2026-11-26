# Finora

Finora is an offline-first, single-user personal finance desktop application for macOS (Apple Silicon).

> **Current status**: **Phase 1 (`v0.1.0`) — Foundation, Architecture & Design**.  
> Finora is under active phased development and is not yet a feature-complete release. See [CHANGELOG.md](CHANGELOG.md), [docs/progress.md](docs/progress.md), and [docs/known-issues.md](docs/known-issues.md) for current scope and limitations.

## Implemented Phase 1 Functionality

- Launches directly into a native macOS desktop window (`pywebview` + `WKWebView`) without login, accounts, onboarding wizards, or an internet connection.
- Starts an embedded local Waitress WSGI server bound exclusively to `127.0.0.1` on an ephemeral port and tears it down cleanly on quit.
- Protects local financial API routes (`/api/*`) with an ephemeral per-launch token delivered in memory, alongside `Host`, `Origin`, `Sec-Fetch-Site`, and strict Content Security Policy enforcement.
- Initializes a versioned SQLite ledger schema (`transactions` + `postings` + `accounts` + `categories` + `settings` + `schema_migrations`) with foreign-key enforcement and WAL journaling.
- Idempotently seeds 10 predefined expense categories, 7 separate income categories, and a default `Cash` account (`INR`, `₹0.00`).
- Parses monetary inputs using Python `Decimal`, stores exact integer minor units (`paise`), and formats values in Indian numbering (`₹1,25,000.00`).
- Provides an end-to-end Phase 1 vertical slice: **Overview**, **Transactions** history, accessible **New Transaction** modal (`Cmd+N`) for income and expense entries, and **Settings** with persisted **System / Light / Dark** appearance.
- Includes an early Apple Silicon (`arm64`) PyInstaller `.app` bundle configuration.

## Technology Stack

- **Backend**: Python (`3.15.2` verified), Flask (`3.1.3`), Waitress (`3.0.2`), `sqlite3` (`3.53.4`), `Decimal`.
- **Frontend**: Semantic HTML5, Jinja2, token-based CSS (`light-dark()`), modular vanilla JS, locally bundled Lucide SVGs (`1.81.0`).
- **Desktop & Packaging**: `pywebview` (`6.2.1`), PyObjC (`13.1`), PyInstaller (`6.22.3`).
- **Tooling & QA**: `pytest`, `ruff`, `playwright` (WebKit), `bandit`, `pip-audit`.

## Local Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
playwright install webkit
```

Launch the desktop application in development:

```bash
.venv/bin/python main.py
```

To point Finora at a separate directory during development instead of your default user workspace:

```bash
FINORA_DATA_DIR=/tmp/finora-dev .venv/bin/python main.py
```

## Running Tests & Quality Checks

Automated tests always run against temporary isolated databases and never read or modify user data.

```bash
.venv/bin/pytest
.venv/bin/ruff check app desktop main.py tests scripts benchmarks
.venv/bin/ruff format --check app desktop main.py tests scripts benchmarks
.venv/bin/bandit -r app desktop main.py
.venv/bin/pip-audit -r requirements.lock
```

Run the Phase 1 baseline benchmark:

```bash
.venv/bin/python benchmarks/baseline_phase1.py
```

## Building the macOS Application

```bash
./scripts/build_app.sh
```

This builds `dist/Finora.app` for `arm64` via `finora.spec` and applies a local ad-hoc code signature (`codesign --force --deep --sign -`). Launch it with:

```bash
open dist/Finora.app
```

## Local Data Storage & Privacy

Mutable user data is stored outside the repository and outside `Finora.app` at:

```text
~/Library/Application Support/Finora/finance.sqlite3
```

Finora performs no telemetry, cloud sync, or external network requests. Standard SQLite database files are protected via owner-only POSIX permissions (`0700` directory, `0600` database file) and macOS FileVault when enabled; application-level SQLite encryption is not enabled.

## Known Limitations (Phase 1)

- Only `Overview`, `Transactions`, and `Settings` are implemented; multi-account management, transfers, editing/deleting transactions, budgets, analytics charts, and backups belong to Phases 2–3.
- `.app` builds are locally ad-hoc signed rather than Apple Developer ID signed or notarized.
- See [docs/known-issues.md](docs/known-issues.md) for environment and platform notes.

## Licensing

Third-party dependency and icon notices are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Final repository licensing (`MIT` or `Apache-2.0` recommended) will be confirmed prior to public publication in Phase 5.
