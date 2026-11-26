-- Phase 4: Performance Optimization Indexes
-- Covering and composite indexes for 100k-row overview, amount sorting, and analytics.

CREATE INDEX IF NOT EXISTS idx_transactions_active_date_id
    ON transactions(deleted_at, tx_date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_active_type_date
    ON transactions(deleted_at, entry_type, tx_date);

CREATE INDEX IF NOT EXISTS idx_postings_tx_acct_cat_amt
    ON postings(transaction_id, account_id, category_id, signed_amount_minor);
