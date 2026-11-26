# Finora — System Architecture

## 1. Layer Topology

```text
macOS Desktop Window (pywebview WKWebView + Cocoa Menus)
   │  in-memory launch token via DesktopBridge
   ▼
Frontend Shell (Semantic HTML5 + Token CSS + Modular Vanilla JS)
   │  fetch() + X-Finora-Token + strict JSON
   ▼
Secured Local Flask API (Waitress WSGI on 127.0.0.1:<ephemeral_port>)
   │  Host / Origin / Sec-Fetch-Site / Token / Size guards
   ▼
Service Layer (transaction_service, overview_service, settings_service)
   │  Authoritative financial logic + Decimal validation
   ▼
Repository Layer (Parameterized SQL)
   │
   ▼
SQLite (`finance.sqlite3`, WAL mode, FK enforcement)
```

## 2. Responsibility Boundaries
- **Desktop (`desktop/`)**: Path resolution, single-instance lock (`flock`), Waitress server lifecycle, readiness probing, `pywebview` window creation, `DesktopBridge`, native macOS menu bar (`Cmd+N`, `About`, `Quit`), `NSWindow.appearance` synchronization, and clean teardown.
- **Routes (`app/routes/`)**: Thin HTTP handlers (`pages.py`, `health.py`, `api.py`). Parse JSON, delegate to services, return uniform JSON payloads or error envelopes.
- **Services (`app/services/`)**: Business validation, monetary conversions via `app/utils/money.py`, calendar/month slicing via `app/utils/time.py`, idempotency checks, and atomic multi-step coordination.
- **Repositories (`app/repositories/`)**: Parameterized SQLite reads/writes only; no HTTP or HTML awareness.
- **Migrations (`app/migrations/`)**: Versioned `.sql` scripts applied inside transactions and tracked in `schema_migrations`, followed by idempotent seed routines.
- **Frontend (`app/templates/`, `app/static/`)**: Renders backend-supplied values safely via `textContent` / `createElement`. Never computes authoritative balances or totals.

## 3. Packaging Strategy
- PyInstaller `--onedir` `.app` bundle (`finora.spec`) targeting `arm64` on Apple Silicon macOS.
- Bundles `app/templates`, `app/static`, `app/migrations/sql`, and `assets/branding`.
- Never writes mutable user data inside `.app`; mutable runtime files go strictly to `~/Library/Application Support/Finora/`.
