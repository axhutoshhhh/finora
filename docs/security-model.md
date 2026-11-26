# Finora — Security Model

## 1. Threat Model & Design Assumptions
Finora runs locally for a single macOS user without accounts or passwords. Its primary threats are:
1. **External web pages / CSRF / DNS rebinding** targeting the loopback HTTP server from another open browser tab.
2. **Unauthorized local HTTP clients** or scripts probing localhost ports.
3. **XSS / DOM injection** via crafted transaction descriptions or imported data (in later phases).
4. **Accidental leakage** of personal financial data into Git, `.app` bundle, logs, or error screens.

## 2. Implemented Phase 1 Defenses
- **Loopback Binding Only**: Waitress binds strictly to `127.0.0.1` on an ephemeral free port (`port=0`), never `0.0.0.0`.
- **Ephemeral Per-Launch API Token**: `desktop/launcher.py` generates a 256-bit `secrets.token_urlsafe(32)` token in memory per process launch. `pywebview`'s `DesktopBridge.get_launch_token()` verifies the active WebView origin (`http://127.0.0.1:<port>/`) and returns the token strictly into a private JS module closure—never stored in `localStorage`, URLs, HTML templates, logs, or disk.
- **API Authorization & Anti-CSRF / Anti-DNS-Rebinding**:
  - Every `/api/*` request validates `Host` (`127.0.0.1:<port>`), `Origin` (if present, exact `http://127.0.0.1:<port>`), `Sec-Fetch-Site` (if present, `same-origin` or `none`), and constant-time `X-Finora-Token` (`hmac.compare_digest`).
  - Mutating routes require `Content-Type: application/json` and adhere to `MAX_CONTENT_LENGTH = 65536` bytes.
  - Zero permissive CORS headers (`Access-Control-Allow-Origin` is never emitted).
- **Frontend Hardening**:
  - Strict CSP on HTML responses: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`.
  - Companion headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-origin`.
  - All user strings rendered strictly via DOM `textContent` / `createElement`.
  - External WebView navigation blocked (`pywebview` navigation guard).
  - Zero external CDN assets, zero analytics, zero telemetry.
- **Filesystem Hygiene**:
  - Runtime directory `~/Library/Application Support/Finora/` (`0700`), SQLite file (`0600`), backups/logs excluded from Git and `.app`.
  - Technical logs redact request bodies, tokens, and user transaction descriptions.
  - Flask `debug` mode is forcibly disabled in runtime/packaged builds; unhandled exceptions return generic JSON error IDs without stack traces.

## 3. Documented Security Limitations
- **Unencrypted SQLite at Rest**: Standard Python `sqlite3` databases are not encrypted by default. Finora does **not** claim database encryption at rest; local data confidentiality relies on macOS user account POSIX permissions (`0700`/`0600`) and full-disk FileVault encryption when enabled by the user.
- **Same-User Process Access**: Any process running as the same macOS UID with debugging or filesystem privileges can read local user files or inspect user-owned process memory.
- **Local Development Signing**: Phase 1 `.app` builds use ad-hoc signing (`codesign --sign -`), not Apple Developer ID signing or notarization.
