# Finora — Known Issues & Environment Notes

1. **OS Version Difference**: Development and testing run on `macOS 27.0.1` (`BuildVersion 26A434`) on Apple M2 (`arm64`) rather than macOS Tahoe 26 referenced in the project brief. All macOS runtime verification reflects `macOS 27.0.1`.
2. **Python 3.15.2 Framework SSL CA Bundle**: The installed python.org `Python 3.15.2` framework lacks `etc/openssl/cert.pem` (`Install Certificates.command` not run), causing stdlib `urllib` HTTPS calls to fail certificate verification. Runtime Finora is 100% offline; `pip` and `pip-audit` use `certifi`.
3. **Unencrypted SQLite at Rest**: Local financial data uses standard `sqlite3` protected by macOS POSIX permissions (`0700`/`0600`) and FileVault rather than application-level database encryption.
4. **Local Code Signing**: Phase 1 `.app` bundles use local ad-hoc signing (`codesign --force --deep --sign -`); Apple Developer ID signing and notarization belong to Phase 5 when distribution certificates are supplied.
5. **Manual Native GUI Visual Inspection**: While automated WebKit E2E tests, live `pywebview` `WKWebView` integration checks, and standalone `Finora.app` bundle launches succeeded, interactive manual verification by the user of native macOS trackpad resizing, full-screen Spaces transitions, and visual window-bar menu interaction in Finder is recommended before Phase 2.
