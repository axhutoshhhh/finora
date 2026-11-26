-- Phase 1 Initial Ledger Schema
-- Ledger-ready transactions + postings core supporting Phase 1 income/expense
-- and clean Phase 2/3 expansion for transfers, splits, and linked refunds.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    account_type TEXT NOT NULL CHECK (
        account_type IN ('cash', 'bank', 'savings', 'credit_card', 'wallet', 'investment')
    ),
    opening_balance_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR' CHECK (length(currency) = 3),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_accounts_single_default
    ON accounts(is_default)
    WHERE is_default = 1;

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE CHECK (length(trim(slug)) > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    icon TEXT NOT NULL,
    color_token TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 1 CHECK (is_system IN (0, 1)),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_categories_kind_order
    ON categories(kind, is_archived, sort_order);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL CHECK (
        entry_type IN ('expense', 'income', 'transfer', 'refund')
    ),
    tx_date TEXT NOT NULL CHECK (
        length(tx_date) = 10
        AND tx_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 240),
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_transactions_tx_date_id
    ON transactions(tx_date DESC, id DESC);

CREATE UNIQUE INDEX ux_transactions_idempotency_key
    ON transactions(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    signed_amount_minor INTEGER NOT NULL CHECK (signed_amount_minor != 0),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_postings_transaction_id ON postings(transaction_id);
CREATE INDEX idx_postings_account_id ON postings(account_id);
CREATE INDEX idx_postings_category_id ON postings(category_id);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
