# ADR-0007: Budgets, Rollover, Attachments & Migration Recovery

- **Status**: Accepted (Phase 2)
- **Date**: 2026-11-26

## Decision

1. **Budgets & Rollover**: Monthly `category_budgets` (active expense categories, rollover disabled by default) and `overall_budgets` distinguish unconfigured budgets (`NULL`) from explicit `₹0.00` caps. When consecutive months enable `rollover_enabled = 1`, positive unused budget carries forward deterministically (`carry_out = max(0, effective_limit - max(0, net_spend))`); missing intervening months or `rollover_enabled = 0` reset carry-in to `0`.
2. **Scoped Receipt Attachments**: Standard JSON endpoints keep `MAX_CONTENT_LENGTH = 64 KiB` enforcement; `POST /api/transactions/<id>/attachments` permits bounded `<= 5 MiB` `multipart/form-data` uploads validated strictly by PNG/JPEG/PDF magic bytes, SHA-256, and UUID storage outside the repo and `.app` bundle (`<data_dir>/attachments/`), served strictly with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`.
3. **Pre-Migration Backups**: Before upgrading any existing non-empty database (`0002+`), `initialize_database()` writes a verified online `sqlite3.Connection.backup()` snapshot (`0600`) under `<data_dir>/backups/` and verifies `PRAGMA foreign_key_check` + `PRAGMA integrity_check` before committing DDL.
