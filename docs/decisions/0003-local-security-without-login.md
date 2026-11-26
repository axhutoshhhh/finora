# ADR-0003: Zero-Login Local Security Model

- **Status**: Accepted (Phase 1)
- **Date**: 2026-11-26

## Context

Finora is an offline-first single-user desktop app with no user accounts, login, or passwords. Because the frontend renders inside `WKWebView` talking to a local Flask/Waitress HTTP server on loopback, a naive localhost server would be exposed to local browsers, CSRF, DNS rebinding, or arbitrary local HTTP clients.

## Decision

- Bind Waitress strictly to `127.0.0.1` on an ephemeral free port (`port=0` / dynamic bind).
- Generate a per-launch 256-bit cryptographically random `API_TOKEN` (`secrets.token_urlsafe(32)`) in memory inside the desktop launcher.
- Deliver the token exclusively in memory via `pywebview` `DesktopBridge.get_launch_token()` (which checks that the active WebView URL belongs to `http://127.0.0.1:<port>/`), into an unexported JS closure (`api.js`). Never expose the token in URLs, HTML templates, `localStorage`, `sessionStorage`, logs, or Git.
- Enforce on every `/api/*` request: strict `Host` matching `127.0.0.1:<port>`, `Origin` (if present) matching `http://127.0.0.1:<port>`, `Sec-Fetch-Site` (`same-origin` or `none` if present), constant-time `X-Finora-Token` check, `Content-Type: application/json` on mutations, and `MAX_CONTENT_LENGTH = 64 KiB`.
- Apply strict CSP (`default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cross-Origin-Resource-Policy: same-origin`.
- Block non-loopback navigations inside `WKWebView`.

## Consequences

- **Positive**: Seamless zero-login startup while blocking unauthorized local browser tabs, remote websites (CSRF/DNS rebinding), and unauthenticated local API callers.
- **Limitation**: Another process running under the **same** logged-in macOS user account can still inspect process memory or read `~/Library/Application Support/Finora/finance.sqlite3` directly on disk unless FileVault/sandbox restrictions apply; Finora relies on macOS user account isolation and FileVault rather than claiming database encryption at rest.
