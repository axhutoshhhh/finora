-- Phase 3: Advanced Features, Analytics & Financial Intelligence
-- Adds savings goals & allocations, recurring rules & occurrences,
-- advisory notification events & preferences, categorization rules,
-- and CSV import batch tracking.

CREATE TABLE IF NOT EXISTS savings_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 100),
    target_minor INTEGER NOT NULL CHECK (target_minor > 0),
    target_date TEXT CHECK (
        target_date IS NULL OR (
            length(target_date) = 10
            AND target_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        )
    ),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 240),
    priority INTEGER NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
    account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived')),
    completed_at TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES savings_goals(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    signed_amount_minor INTEGER NOT NULL CHECK (signed_amount_minor != 0),
    allocation_date TEXT NOT NULL CHECK (
        length(allocation_date) = 10
        AND allocation_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 240),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goal_allocations_goal_date
    ON goal_allocations(goal_id, allocation_date DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_goal_allocations_account
    ON goal_allocations(account_id);

CREATE TABLE IF NOT EXISTS recurring_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 100),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('expense', 'income', 'transfer')),
    is_subscription INTEGER NOT NULL DEFAULT 0 CHECK (is_subscription IN (0, 1)),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    to_account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    merchant TEXT NOT NULL DEFAULT '' CHECK (length(merchant) <= 120),
    payment_method TEXT NOT NULL DEFAULT 'other' CHECK (
        payment_method IN ('cash', 'upi', 'card', 'bank_transfer', 'other')
    ),
    frequency TEXT NOT NULL CHECK (
        frequency IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')
    ),
    start_date TEXT NOT NULL CHECK (
        length(start_date) = 10
        AND start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    next_occurrence_date TEXT NOT NULL CHECK (
        length(next_occurrence_date) = 10
        AND next_occurrence_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    end_date TEXT CHECK (
        end_date IS NULL OR (
            length(end_date) = 10
            AND end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        )
    ),
    anchor_day INTEGER NOT NULL CHECK (anchor_day BETWEEN 1 AND 31),
    reminder_days_before INTEGER NOT NULL DEFAULT 3 CHECK (reminder_days_before BETWEEN 0 AND 30),
    auto_post INTEGER NOT NULL DEFAULT 0 CHECK (auto_post IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 240),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'ended', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES recurring_rules(id) ON DELETE CASCADE,
    scheduled_date TEXT NOT NULL CHECK (
        length(scheduled_date) = 10
        AND scheduled_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    status TEXT NOT NULL DEFAULT 'upcoming' CHECK (
        status IN ('upcoming', 'due', 'overdue', 'posted', 'skipped', 'canceled')
    ),
    posted_transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 240),
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(rule_id, scheduled_date)
);

CREATE INDEX IF NOT EXISTS idx_recurring_occurrences_status_date
    ON recurring_occurrences(status, scheduled_date);

CREATE TABLE IF NOT EXISTS notification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    rule_version INTEGER NOT NULL DEFAULT 1,
    dedup_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK (
        category IN ('budget', 'spending', 'upcoming', 'savings', 'review')
    ),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'alert')),
    title TEXT NOT NULL CHECK (length(title) <= 160),
    message TEXT NOT NULL CHECK (length(message) <= 600),
    supporting_json TEXT NOT NULL DEFAULT '{}',
    period_key TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    nav_target TEXT NOT NULL DEFAULT 'insights',
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    is_dismissed INTEGER NOT NULL DEFAULT 0 CHECK (is_dismissed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notification_events_active
    ON notification_events(is_dismissed, is_read, created_at DESC);

CREATE TABLE IF NOT EXISTS notification_preferences (
    rule_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    threshold_value INTEGER,
    native_enabled INTEGER NOT NULL DEFAULT 0 CHECK (native_enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categorization_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 100),
    match_field TEXT NOT NULL DEFAULT 'merchant' CHECK (match_field IN ('merchant', 'description')),
    match_type TEXT NOT NULL CHECK (match_type IN ('exact', 'contains', 'starts_with')),
    pattern TEXT NOT NULL CHECK (length(trim(pattern)) > 0 AND length(pattern) <= 120),
    entry_type TEXT NOT NULL DEFAULT 'expense' CHECK (entry_type IN ('expense', 'income')),
    target_category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    priority INTEGER NOT NULL DEFAULT 100 CHECK (priority BETWEEN 1 AND 10000),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_categorization_rules_priority
    ON categorization_rules(is_enabled, entry_type, priority ASC, id ASC);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_uuid TEXT NOT NULL UNIQUE,
    source_filename TEXT NOT NULL CHECK (length(source_filename) <= 255),
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    total_rows INTEGER NOT NULL CHECK (total_rows >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    status TEXT NOT NULL DEFAULT 'committed' CHECK (status IN ('committed', 'reversed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batch_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL CHECK (row_number >= 1),
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('inserted', 'skipped_duplicate', 'rejected')),
    reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 240)
);
