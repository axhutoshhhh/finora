# Security Policy — Finora

## Current Status

Finora is currently in **Phase 1 (Foundation, Architecture & Design)** and is not yet published as a public production release.

## Security Model Summary

Finora is an offline-first macOS desktop application without user login or cloud services:
- **Loopback Isolation**: The local Waitress server binds exclusively to `127.0.0.1` on an ephemeral free port (`0.0.0.0` is never used).
- **Per-Launch API Authorization**: Every `/api/*` request requires a fresh 256-bit ephemeral `X-Finora-Token` delivered strictly in memory via `WKWebView.run_js` (never stored in URLs, HTML, `localStorage`, logs, or Git).
- **CSRF & DNS Rebinding Protection**: Requests validate strict `Host`, `Origin`, `Sec-Fetch-Site`, and `Content-Type: application/json` headers, with zero permissive CORS headers and a 64 KiB body limit.
- **Frontend Hardening**: Strict `Content-Security-Policy` (`script-src 'self'`, `style-src 'self'`, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, safe `textContent` DOM rendering, and navigation filtering blocking external URLs.
- **Database Integrity**: Parameterized SQLite queries with `PRAGMA foreign_keys = ON` and owner-only file permissions (`0700` directory, `0600` database file).

## Known Limitations

- **Unencrypted SQLite at Rest**: Standard SQLite files in `~/Library/Application Support/Finora/finance.sqlite3` are not encrypted by the application. Confidentiality on disk relies on macOS user permissions and FileVault full-disk encryption.
- **Ad-Hoc Local Code Signing**: Phase 1 `.app` bundles are ad-hoc signed locally rather than Apple Developer ID signed or notarized.

## Reporting Security Issues

Until public repository publication in Phase 5, report issues privately to the repository maintainer via local project tracking (`docs/known-issues.md`) and never commit sensitive financial data or credentials.
