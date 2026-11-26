# ADR-0004: Desktop Shell, Lifecycle & Early ARM64 Packaging

- **Status**: Accepted (Phase 1)
- **Date**: 2026-11-26

## Context

Finora must open as a native macOS desktop window without requiring the user to install Python or start Flask manually, and must shut down cleanly on Apple Silicon (`arm64`).

## Decision

- Use `pywebview 6.2.1` backed by Apple's system `WKWebView` via `PyObjC 13.1`, eliminating bundled Chromium runtimes (such as Electron).
- Use `waitress 3.0.2` (`waitress.create_server`) on a background thread with bounded `/health` readiness probing and explicit `server.close()` during shutdown.
- Guard against accidental duplicate launches using an `fcntl.flock` lock file in the Finora data directory.
- Authoritative user preferences (`appearance`: `system` | `light` | `dark`) reside in SQLite `settings`, rendered server-side into `<meta name="color-scheme">` and synced with Cocoa `NSWindow.appearance` via PyObjC.
- Package early via PyInstaller (`finora.spec`) in directory-based `.app` bundle mode (`--onedir` `BUNDLE`, `--target-architecture arm64`) with ad-hoc local signing (`codesign --force --deep --sign -`).

## Consequences

- **Positive**: Small footprint, native macOS typography/scrolling/traffic lights, and clean `.app` startup on Apple Silicon.
- **Trade-off**: Directory-based `.app` bundles start faster and debug more reliably than `--onefile`; Developer ID signing and notarization remain out of scope until Phase 5 if distribution certificates are available.
