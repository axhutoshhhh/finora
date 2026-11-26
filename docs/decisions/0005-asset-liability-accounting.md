# ADR-0005: Asset & Liability Accounting Sign Convention

- **Status**: Accepted (Phase 2)
- **Date**: 2026-11-26

## Decision

All accounts (`cash`, `bank`, `savings`, `wallet`, `credit_card`) retain Phase 1's signed economic balance convention:

- `balance_minor = opening_balance_minor + COALESCE(SUM(active postings.signed_amount_minor), 0)`
- Expenses post negative (`-amount_minor`); ordinary income and refunds post positive (`+amount_minor`).
- Transfers post paired zero-sum legs (`-amount_minor` source, `+amount_minor` destination, `category_id = NULL`).
- For `credit_card` accounts, opening debt is stored as a negative `opening_balance_minor` (e.g., `₹1,500` debt = `-150000`), purchases make `balance_minor` more negative, and asset-to-card repayments move `balance_minor` toward zero (`outstanding_liability_minor = max(0, -balance_minor)`, overpayment `credit_balance_surplus_minor = max(0, balance_minor)`).
- Net financial position equals `total_assets_minor - total_liabilities_minor` (mathematically equal to the sum of all active and archived `balance_minor` values).
- Outbound transfers from `credit_card` (cash advances) are blocked in Phase 2 until dedicated fee/APR definitions are introduced.
