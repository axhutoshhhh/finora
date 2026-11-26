# ADR-0002: Exact Monetary Arithmetic via `Decimal` and Integer Minor Units

- **Status**: Accepted (Phase 1)
- **Date**: 2026-11-26

## Context

IEEE-754 binary floating-point numbers (`float`) cannot represent base-10 currency fractions such as `0.10` or `0.20` exactly, causing cumulative rounding drift across balances, splits, and monthly budgets.

## Decision

- Parse all user-entered monetary strings using Python `decimal.Decimal` in `app/utils/money.py` (never via `float`).
- Reject `NaN`, `Infinity`, scientific notation (`1e5`), negative/zero transaction amounts, >2 fractional decimal places (for INR), and amounts exceeding `99,99,99,999.99` INR (`99_999_999_999` paise).
- Convert validated amounts to exact `int` minor units (`paise`, `1 INR = 100 paise`) before entering repositories or SQLite `INTEGER` columns.
- Format INR server-side using Indian digit grouping (`en-IN` convention, e.g., `₹1,25,000.00`).

## Consequences

- **Positive**: Exact base-10 arithmetic with zero floating-point drift and deterministic JSON/UI display.
- **Positive**: Single authoritative calculation and formatting path in Python services/utils.
- **Trade-off**: Multi-currency expansion later requires tracking `minor_unit_exponent` per currency alongside `currency` code.
