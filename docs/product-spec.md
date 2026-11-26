# Finora — Product Specification

## 1. Purpose & Vision
Finora is an offline-first, single-user personal finance desktop application built natively for macOS (Apple Silicon). It prioritizes financial precision, local privacy, understated native ergonomics, and long-term architectural maintainability over cloud subscriptions or marketing clutter.

## 2. Target User & Operating Constraints
- **User**: Single individual managing personal income, expenses, accounts, budgets, savings goals, and recurring obligations on macOS.
- **Zero Friction**: Opens directly into a usable Overview screen on first launch. No login, sign-up, email, password, Touch ID gate, onboarding wizard, internet connection, or cloud sync required.
- **Default Locale & Currency**: Indian Rupees (`INR`, `₹`), Indian numbering (`₹1,25,000.00`), local calendar dates (`YYYY-MM-DD`).

## 3. Five-Phase Roadmap & Screen Inventory

| Screen | Phase 1 Status | Planned Scope (Phases 2–5) |
| :--- | :--- | :--- |
| **Overview** | Implemented (balance, monthly income/expense/surplus, recent transactions, primary New Transaction action) | Functional dashboard summaries, budget progress, Phase 3 interactive charts & advisory highlights |
| **Transactions** | Implemented (basic history list + expense/income creation dialog) | Search, filter, edit, delete, split transactions, linked refunds, tags, attachments |
| **Settings** | Implemented (System/Light/Dark appearance, app version, local data path, privacy summary, About) | Currency/locale options, backup & restore, demo workspace switch, CSV import/export tools |
| **Accounts** | Documented only (hidden from Phase 1 nav) | Multiple bank/cash/savings/wallet/credit-card accounts, transfers, credit-card repayments |
| **Budgets** | Documented only (hidden from Phase 1 nav) | Monthly category budgets, custom categories, alert thresholds |
| **Reports** | Documented only (hidden from Phase 1 nav) | Interactive Chart.js analytics, cashflow & category breakdowns, report export |
| **Savings Goals** | Documented only (hidden from Phase 1 nav) | Goal targets, savings allocations (non-expense transfers), progress tracking |
| **Recurring Payments** | Documented only (hidden from Phase 1 nav) | Scheduled bills, subscriptions, pending vs posted handling |
| **Calendar** | Documented only (hidden from Phase 1 nav) | Monthly cashflow and upcoming bill calendar |
| **Insights** | Documented only (hidden from Phase 1 nav) | Rule-based offline advisory notifications & categorization rules |

## 4. Phase 1 Supported Operations
- Automatic first-launch workspace initialization (`~/Library/Application Support/Finora/`), database migration, seeding 10 expense categories + 7 income categories + default `Cash` account (`₹0.00`).
- Create an **expense** or **income** transaction with exact INR amount, category, account (`Cash`), date, and optional description.
- View real database-driven current balance, selected/current month income, expense, surplus/deficit, and transaction activity.
- Switch and persist **System**, **Light**, or **Dark** appearance across restarts.

## 5. Explicit Exclusions
- No cloud database, web SaaS hosting, user login/OAuth, telemetry, ads, or bank-aggregator APIs.
- No fake buttons, placeholder charts, or fictional demo transactions inside the user's production database.
