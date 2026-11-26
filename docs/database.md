# Finora — Database Architecture & Schema

## 1. Engine & Connection Policies
- Engine: SQLite (`sqlite3`, verified `3.53.4` on macOS).
- Applied on every connection (`app/database.py`):
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA busy_timeout = 5000;`
  - `PRAGMA journal_mode = WAL;` (verified dynamically against file-backed DB; skipped only on `:memory:` if ever used)
  - `PRAGMA synchronous = NORMAL;`
- Connections are created per request/operation or short-lived context and never shared unsafely across threads.

## 2. Phase 1 Tables (`0001_initial_schema.sql`)
- `schema_migrations`: `version INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `applied_at TEXT NOT NULL`.
- `accounts`: `id`, `name`, `account_type`, `opening_balance_minor INTEGER`, `currency TEXT`, `is_default`, `is_archived`, `created_at`, `updated_at`.
- `categories`: `id`, `slug TEXT UNIQUE`, `name`, `kind ('expense'|'income')`, `icon`, `color_token`, `sort_order`, `is_system`, `is_archived`, `created_at`.
- `transactions`: `id`, `entry_type ('expense'|'income'|'transfer'|'refund')`, `tx_date ('YYYY-MM-DD')`, `description`, `idempotency_key` (partial unique index where not null), `created_at`, `updated_at`.
- `postings`: `id`, `transaction_id` (FK `ON DELETE CASCADE`), `account_id` (FK `ON DELETE RESTRICT`), `category_id` (FK `ON DELETE RESTRICT`, nullable in schema for future transfers), `signed_amount_minor INTEGER CHECK (signed_amount_minor != 0)`, `created_at`.
- `settings`: `key TEXT PRIMARY KEY`, `value TEXT NOT NULL`, `updated_at TEXT NOT NULL`.

## 3. Indexes
- `idx_transactions_tx_date_id ON transactions(tx_date DESC, id DESC)` — powers Overview recent activity and chronological transaction history.
- `idx_postings_transaction_id ON postings(transaction_id)` — fast join from transaction header to postings.
- `idx_postings_account_id ON postings(account_id)` — fast account balance summation.
- `idx_postings_category_id ON postings(category_id)` — fast category totals for Phase 2/3 budgets & reports.
- `idx_categories_kind_order ON categories(kind, is_archived, sort_order)` — fast category dropdown loading.
- `ux_transactions_idempotency_key ON transactions(idempotency_key) WHERE idempotency_key IS NOT NULL` — prevents duplicate retry writes.

## 4. Planned Future Schema Additions (Phases 2–3)
- `transactions.related_transaction_id` (linked refunds).
- `budgets` (monthly category caps).
- `tags` & `transaction_tags` (many-to-many tagging).
- `savings_goals` & `goal_allocations`.
- `recurring_rules` & `scheduled_occurrences`.
- `categorization_rules`, `notifications`, `attachments`, `import_batches`.
