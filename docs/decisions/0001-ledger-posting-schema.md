# ADR-0001: Ledger-Ready `transactions` and `postings` Schema

- **Status**: Accepted (Phase 1)
- **Date**: 2026-11-26

## Context

Finora begins in Phase 1 with single-account `Cash` expenses and income. In Phases 2 and 3, it must support multiple accounts (including credit card liabilities), internal account transfers, credit card repayments, split transactions across multiple categories, and linked refunds. Storing a single `account_id`, `category_id`, and unsigned `amount` directly on one `transactions` row creates structural friction when adding transfers or splits later, forcing a destructive data migration.

## Decision

Model financial entries as a two-table core from Day 1:

1. `transactions` (journal header): `id`, `entry_type` (`expense`, `income`, `transfer`, `refund`), `tx_date` (`YYYY-MM-DD`), `description`, `idempotency_key`, `created_at`, `updated_at`.
2. `postings` (ledger lines): `id`, `transaction_id` (FK -> `transactions.id` `ON DELETE CASCADE`), `account_id` (FK -> `accounts.id` `ON DELETE RESTRICT`), `category_id` (FK -> `categories.id` `ON DELETE RESTRICT`, nullable in schema for future transfers), `signed_amount_minor` (`INTEGER NOT NULL CHECK (signed_amount_minor != 0)`), `created_at`.

Phase 1 enforces via service validation (and `API` input checks) that only `expense` (1 negative posting) and `income` (1 positive posting) with a matching non-archived `category_id` and `account_id` are accepted.

## Consequences

- **Positive**: Account balance is universally `opening_balance_minor + COALESCE(SUM(signed_amount_minor), 0)`. Splits, transfers, and credit card repayments require no core table rewrite—only enabling additional `entry_type` rules and optional metadata columns (e.g., `related_transaction_id` for refunds).
- **Positive**: Remains transparent and easy to query for SQL learners (`JOIN postings ON postings.transaction_id = transactions.id`).
- **Trade-off**: Phase 1 transaction queries perform one indexed join between `transactions` and `postings`, which is negligible in SQLite at personal finance scale.
