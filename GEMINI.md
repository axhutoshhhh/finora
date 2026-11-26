# Antigravity Project Instructions — Finora

Follow `AGENTS.md` at the repository root as the authoritative project policy.

## Antigravity-Specific Operational Rules
- Verify all changes with real execution (`pytest`, `ruff`, `bandit`, `pip-audit`, Playwright WebKit inspection, live `pywebview` launch, and PyInstaller `.app` build checks) before reporting success.
- When changing HTML, CSS, or client-side JS, consult `modern-web-guidance` first and preserve strict CSP (no inline `<script>` or `<style>` tags).
- Keep `docs/progress.md`, `docs/known-issues.md`, and `docs/acceptance-criteria.md` synchronized with verified facts only.
- Operate strictly within `/Users/ashutoshraj/finora`, Finora's isolated test temp directories, and the dedicated `~/Library/Application Support/Finora/` runtime directory. Never read unrelated personal files or modify global macOS security settings.
- Do not create a GitHub remote, push commits, or begin a subsequent roadmap phase without explicit user approval.
