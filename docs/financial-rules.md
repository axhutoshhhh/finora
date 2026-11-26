# Finora — Financial Rules & Invariants

All financial definitions and arithmetic reside authoritatively in the Python backend (`app/utils/money.py`, `app/services/`).

## 1. Monetary Representation
- **Unit**: Integer minor units (`paise` for `INR`, where `₹1.00 = 100`).
- **Input Parsing**: Uses `decimal.Decimal` directly on trimmed string input (`1250`, `1250.5`, `1250.50`, optional Indian grouping commas stripped carefully after syntax validation).
- **Rejected Inputs**: Empty strings, non-numeric characters, `NaN`, `Infinity`, `-Infinity`, scientific notation (`1e4`), >2 decimal digits (`10.999`), zero or negative transaction amounts (`<= 0`), and amounts exceeding `99,99,99,999.99` INR (`99_999_999_999` paise).
- **Formatting**: Indian `en-IN` grouping (`₹1,25,000.00`, `-₹500.00`).

## 2. Dates & Timestamps
- **Transaction Date (`tx_date`)**: Local calendar date formatted strictly as `YYYY-MM-DD` (validated via `datetime.date.fromisoformat`).
- **Technical Metadata (`created_at`, `updated_at`)**: UTC timezone-aware ISO-8601 timestamps (`YYYY-MM-DDTHH:MM:SSZ`).

## 3. Accounting Invariants (All Five Phases)
1. **Asset & Liability Impact**: Income increases an owned asset balance (`+signed_amount_minor`); expenses decrease an asset balance (`-signed_amount_minor`) or increase a credit-card liability in Phase 2.
2. **Account Balance Formula**: `opening_balance_minor + SUM(postings.signed_amount_minor)`.
3. **Transfers**: Internal transfers between owned accounts (`entry_type = 'transfer'`, Phase 2) sum to `0` net worth change and are **never** counted as income, expense, or budget consumption.
4. **Credit Card Repayments**: Settling a credit card balance from a bank/cash account is a `transfer`, not an additional expense.
5. **Opening Balances**: Initial account balances (`opening_balance_minor`) establish starting net worth and are **not** counted as current-month income.
6. **Refunds**: Linked refunds (`entry_type = 'refund'`, Phase 2) reduce net spending for the referenced expense/category rather than inflating income.
7. **Savings Allocations**: Earmarking money toward a savings goal (Phase 3) does not create a fake expense.
8. **Pending vs. Posted**: Future/pending recurring reminders (Phase 3) do not alter posted account balances until posted.
9. **Split Transactions**: Sum of split posting amounts must equal the parent transaction amount exactly (enforced in minor units).
10. **Historical Integrity**: Archiving an account or category (`is_archived = 1`) preserves existing historical transactions and totals; archived entities cannot be selected for new transactions.

## 4. Phase 1 Category Taxonomy
- **Expense Categories (exactly 10 predefined, stable slugs)**:
  1. `food_dining` — Food & Dining
  2. `housing_rent` — Housing & Rent
  3. `transportation` — Transportation
  4. `shopping` — Shopping
  5. `education` — Education
  6. `healthcare` — Healthcare
  7. `entertainment` — Entertainment
  8. `subscriptions` — Subscriptions
  9. `utilities_bills` — Utilities & Bills
  10. `miscellaneous` — Miscellaneous
- **Income Categories (separate, 7 predefined)**:
  1. `salary` — Salary
  2. `allowance` — Allowance
  3. `freelance_income` — Freelance Income
  4. `scholarship` — Scholarship
  5. `business_income` — Business Income
  6. `gifts` — Gifts
  7. `other_income` — Other Income
- Income categories cannot be paired with `expense` transactions, and expense categories cannot be paired with `income` transactions.
