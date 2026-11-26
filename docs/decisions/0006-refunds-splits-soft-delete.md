# ADR-0006: Linked Refund & Split Allocation Accounting Policy

- **Status**: Accepted (Phase 2)
- **Date**: 2026-11-26

## Decision

1. **Linked Refunds (`entry_type = 'refund'`)**: Must reference an active `expense` via `transactions.related_transaction_id`. Sum of active refunds (`deleted_at IS NULL`) cannot exceed the original expense total or any per-category allocation on a split expense (verified atomically inside `BEGIN IMMEDIATE`). Refunds reduce `net_expense = gross_expense - refunds_minor` in the refund's `tx_date` month without silently rewriting historical months or inflating ordinary income. Original expenses with active refunds cannot be soft-deleted or shrunk below active refunded amounts.
2. **Split Transactions (`is_split = 1`)**: Represented as one `transactions` header owning `N >= 2` same-account postings across distinct/selected expense or income categories whose `signed_amount_minor` values sum exactly to the parent transaction total.
3. **Soft Deletion & Optimistic Revisions**: `deleted_at` removes transactions and their postings from all active balances, summaries, and budgets while preserving attachment links and postings for undo/restore; `revision` guards against stale-form `PATCH` overwrites.
