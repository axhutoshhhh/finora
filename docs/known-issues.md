# Finora — Known Issues & Environment Notes

1. **OS Version Difference**: Development hardware runs `macOS 27.0.1` (`BuildVersion 26A434`) on Apple M2 (`arm64`) rather than macOS Tahoe 26 referenced in the project brief. All macOS runtime verification reflects `macOS 27.0.1`.
2. **Python 3.15.2 Framework SSL CA Bundle**: The installed python.org `Python 3.15.2` framework lacks `etc/openssl/cert.pem` (`Install Certificates.command` not run), causing stdlib `urllib` HTTPS calls to fail certificate verification. Runtime Finora is 100% offline; `pip` uses its bundled `certifi`.
3. **Unencrypted SQLite at Rest**: Local financial data uses standard `sqlite3` protected by macOS POSIX permissions (`0700`/`0600`) and FileVault rather than application-level database encryption.
4. **Local Code Signing**: Phase 1 `.app` bundles will use ad-hoc signing (`codesign --sign -`); Apple Developer ID signing and notarization belong to Phase 5 when distribution certificates are supplied.
