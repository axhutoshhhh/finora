"""Synthetic test fixtures (never loaded into the user's real workspace)."""

from __future__ import annotations

SYNTHETIC_TRANSACTIONS: list[dict[str, object]] = [
    {
        "entry_type": "income",
        "category_slug": "salary",
        "amount": "85000.00",
        "tx_date": "2026-11-01",
        "description": "Monthly stipend & salary credit",
    },
    {
        "entry_type": "expense",
        "category_slug": "housing_rent",
        "amount": "24500.00",
        "tx_date": "2026-11-03",
        "description": "November apartment rent",
    },
    {
        "entry_type": "expense",
        "category_slug": "food_dining",
        "amount": "645.50",
        "tx_date": "2026-11-12",
        "description": "Groceries and fresh produce",
    },
    {
        "entry_type": "expense",
        "category_slug": "utilities_bills",
        "amount": "1499.00",
        "tx_date": "2026-11-18",
        "description": "Fiber broadband and electricity bill",
    },
    {
        "entry_type": "income",
        "category_slug": "freelance_income",
        "amount": "12500.75",
        "tx_date": "2026-11-22",
        "description": "UI accessibility audit consultation",
    },
    {
        "entry_type": "expense",
        "category_slug": "transportation",
        "amount": "320.25",
        "tx_date": "2026-11-25",
        "description": "Metro smart card recharge",
    },
]
