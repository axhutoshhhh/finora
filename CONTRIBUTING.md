# Contributing to Finora

Thank you for your interest in Finora.

## Development Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
playwright install webkit
```

## Quality & Testing
- Run tests: `.venv/bin/pytest -q`
- Lint & format: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- Security scan: `.venv/bin/bandit -r app desktop main.py`

## Privacy & Financial Correctness Rules
- Never commit personal financial databases (`.sqlite3`), receipts, bank statements, or credentials.
- All monetary calculations must use `Decimal` input parsing and exact integer minor units (`paise`).
- Report security vulnerabilities privately per [SECURITY.md](SECURITY.md).
