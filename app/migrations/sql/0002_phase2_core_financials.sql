-- Phase 2 Core Financial Schema Evolution
-- Preserves all Phase 1 tables, accounts, categories, transactions, and postings.

ALTER TABLE accounts ADD COLUMN opening_balance_date TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 240);
ALTER TABLE accounts ADD COLUMN icon TEXT NOT NULL DEFAULT 'wallet';
ALTER TABLE accounts ADD COLUMN color_token TEXT NOT NULL DEFAULT 'cat-forest';
ALTER TABLE accounts ADD COLUMN credit_limit_minor INTEGER CHECK (credit_limit_minor IS NULL OR credit_limit_minor >= 0);

UPDATE accounts
SET opening_balance_date = substr(created_at, 1, 10)
WHERE opening_balance_date = '' AND length(created_at) >= 10;

UPDATE accounts
SET opening_balance_date = '1970-01-01'
WHERE length(opening_balance_date) != 10;

ALTER TABLE transactions ADD COLUMN merchant TEXT NOT NULL DEFAULT '' CHECK (length(merchant) <= 120);
ALTER TABLE transactions ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'other' CHECK (
    payment_method IN ('cash', 'upi', 'debit_card', 'credit_card', 'bank_transfer', 'other')
);
ALTER TABLE transactions ADD COLUMN related_transaction_id INTEGER REFERENCES transactions(id) ON DELETE RESTRICT;
ALTER TABLE transactions ADD COLUMN is_split INTEGER NOT NULL DEFAULT 0 CHECK (is_split IN (0, 1));
ALTER TABLE transactions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1);
ALTER TABLE transactions ADD COLUMN deleted_at TEXT;

CREATE INDEX idx_transactions_active_date_id
    ON transactions(deleted_at, tx_date DESC, id DESC);

CREATE INDEX idx_transactions_related_id
    ON transactions(related_transaction_id)
    WHERE related_transaction_id IS NOT NULL;

CREATE INDEX idx_transactions_deleted_at
    ON transactions(deleted_at)
    WHERE deleted_at IS NOT NULL;

CREATE UNIQUE INDEX ux_categories_active_name_kind
    ON categories(kind, lower(trim(name)))
    WHERE is_archived = 0;

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 40),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_tags_name_ci
    ON tags(lower(trim(name)));

CREATE TABLE transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (transaction_id, tag_id)
);

CREATE INDEX idx_transaction_tags_tag_id
    ON transaction_tags(tag_id);

CREATE TABLE attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL CHECK (length(original_filename) BETWEEN 1 AND 255),
    stored_filename TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/png', 'image/jpeg', 'application/pdf')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_attachments_transaction_id
    ON attachments(transaction_id);

CREATE TABLE category_budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    month TEXT NOT NULL CHECK (
        length(month) = 7
        AND month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
    ),
    limit_minor INTEGER NOT NULL CHECK (limit_minor >= 0),
    rollover_enabled INTEGER NOT NULL DEFAULT 0 CHECK (rollover_enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category_id, month)
);

CREATE INDEX idx_category_budgets_month
    ON category_budgets(month, category_id);

CREATE TABLE overall_budgets (
    month TEXT PRIMARY KEY CHECK (
        length(month) = 7
        AND month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
    ),
    limit_minor INTEGER NOT NULL CHECK (limit_minor >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
