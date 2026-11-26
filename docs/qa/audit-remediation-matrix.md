# Finora — Phase 4 Independent Audit Remediation Matrix

All 12 Critical and High findings from the independent read-only audit (`19f9568f-3f1d-4b24-ab2d-1545cb421672`) are tracked below with verified regression tests.

| ID | Severity | Defect | Affected File(s) | Corrective Implementation | Regression Test | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Critical | Cross-workspace stale-request race | `app/__init__.py`, `app/routes/api.py` | Added `FINORA_WORKSPACE_GEN` + `X-Finora-Workspace-Gen` (`409 Conflict`) guard | `test_stale_workspace_generation_header_rejected` | **Resolved** |
| 2 | Critical | Backup attachment leak, WAL sidecars & omitted manifest DB wipe | `app/services/backup_service.py` | Scoped attachments to `db_path.parent / "attachments"`, required `finance.sqlite3` in manifest, unlinked `-wal`/`-shm` | `test_backup_isolation_missing_manifest_and_wal_cleanup` | **Resolved** |
| 3 | Critical | Recurring `transfer` single-posting unbalanced entry | `app/services/recurring_service.py` | Validated `to_account_id` (active, distinct, non-CC source) & inserted 2 balanced postings atomically | `test_recurring_transfer_creates_two_balanced_postings` | **Resolved** |
| 4 | High | `O(N²)` correlated subquery on `account_id`/`category_id` | `app/migrations/sql/0004_phase4_indexes.sql` | Added covering index `idx_postings_tx_acct_cat_amt` | `benchmarks/benchmark_phase4.py` | **Resolved** |
| 5 | High | Full-table `SCAN t` on 100k `overview_load` & `amount_desc` | `app/migrations/sql/0004_phase4_indexes.sql` | Added `idx_transactions_active_date_id`, `idx_transactions_active_type_date` (`overview_load` -54.1% at 100k) | `benchmarks/benchmark_phase4.py` | **Resolved** |
| 6 | High | `reset_demo_workspace` / `seed_demo_workspace` concurrency race | `app/services/workspace_service.py` | Added `threading.RLock()` (`_WORKSPACE_LOCK`) around seed/reset | `test_scenario_l_workspace_isolation_and_demo_reset` | **Resolved** |
| 7 | High | `phase3.js` token closure mismatch (`401` in live desktop) | `app/static/js/phase3.js`, `app/static/js/api.js`, `app/templates/app.html` | Converted `phase3.js` to ES module importing `requestJson` from `api.js` | `test_all_ten_sections_interactive_webkit` | **Resolved** |
| 8 | High | `commit_csv_import` missing date/type/amount/category validation | `app/services/import_service.py` | Enforced `expense`/`income` only, `0 < amount <= MAX`, active matching category | `test_csv_commit_validation_and_whitespace_formula_sanitization` | **Resolved** |
| 9 | High | Recurring `sync_occurrences` start-date & lifecycle | `app/services/recurring_service.py` | Synced `create_rule` to `date.today()` | `test_recurring_transfer_creates_two_balanced_postings` | **Resolved** |
| 10 | High | Odd-paise transfer integer division in Calendar | `app/services/calendar_service.py` | Computed `raw_amt // 2` after summing | `test_calendar_odd_paise_transfer_and_completed_goal_and_advisory_guards` | **Resolved** |
| 11 | High | Advisory `budget_exceeded` fallback & unvalidated `threshold_value` | `app/services/advisory_service.py` | Changed `else:` to `elif pct < 100:` and validated `threshold_value` | `test_calendar_odd_paise_transfer_and_completed_goal_and_advisory_guards` | **Resolved** |
| 12 | High | Goal completed-state contribution bypass | `app/services/goal_service.py` | Blocked contributions/withdrawals on `completed` goals | `test_calendar_odd_paise_transfer_and_completed_goal_and_advisory_guards` | **Resolved** |
