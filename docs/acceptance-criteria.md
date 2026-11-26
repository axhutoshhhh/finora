# Finora — Phase 1 Acceptance Criteria Tracker

Status values: `Pending`, `Passed`, `Failed`, `Blocked`, `N/A`. Updated strictly from observed evidence.

## Architecture
- [ ] Modular project architecture exists
- [ ] Flask application factory works
- [ ] Routes, services and database access are separated
- [ ] Persistent project instructions exist (`AGENTS.md`, `GEMINI.md`)
- [ ] Future phase requirements are documented
- [ ] Dependencies are reproducible (`requirements.lock`, `requirements-dev.lock`)
- [ ] No unnecessary frameworks have been introduced

## Desktop Application
- [ ] Native macOS window launches successfully
- [ ] Application starts without a manually launched Flask server
- [ ] Window resizing works
- [ ] Native window controls work
- [ ] Server readiness is handled correctly
- [ ] Startup failures have meaningful error handling
- [ ] Application shuts down cleanly
- [ ] Duplicate-instance behavior is handled
- [ ] Early ARM64 application bundle builds
- [ ] Packaged application launch has been tested

## Design
- [ ] Original Finora branding exists
- [ ] Application icon is prepared (`Finora.icns`)
- [ ] No generic square in-interface logo
- [ ] No purple gradients or prohibited AI-style design
- [ ] Reusable design system exists
- [ ] Desktop shell is visually consistent
- [ ] Overview screen is functional
- [ ] Transaction interface is functional
- [ ] Settings screen is functional
- [ ] Light appearance works
- [ ] Dark appearance works
- [ ] Appearance preference persists
- [ ] Minimum window size (`900x600`) remains usable
- [ ] Keyboard and focus states are implemented
- [ ] No deceptive or nonfunctional visible controls

## Financial Foundation
- [ ] SQLite database initializes successfully
- [ ] Versioned migrations work
- [ ] Exactly ten predefined expense categories are seeded
- [ ] Income categories are separate
- [ ] Default Cash account is initialized
- [ ] Repeated launches do not duplicate default records
- [ ] Monetary amounts use integer minor units
- [ ] Basic expense creation works
- [ ] Basic income creation works
- [ ] Invalid monetary values are rejected
- [ ] Overview values reflect stored transactions
- [ ] Transactions persist across restarts
- [ ] Test data is separated from real user data

## Security
- [ ] Local server binds only to loopback (`127.0.0.1`)
- [ ] Financial API routes reject unauthorized requests
- [ ] Appropriate origin and Host validation exists
- [ ] Parameterized SQL is used
- [ ] Untrusted content is safely rendered
- [ ] No external runtime assets are required
- [ ] Debug mode is disabled in packaged builds
- [ ] Local data storage is outside the repository
- [ ] No secrets or personal financial records are committed
- [ ] Security limitations are documented

## Testing & Quality
- [ ] Unit tests pass
- [ ] Database tests pass
- [ ] Backend integration tests pass
- [ ] Frontend tests pass or unavailable tests are explicitly identified
- [ ] Actual desktop behavior has been verified where possible
- [ ] Visual inspection has been performed
- [ ] Discovered release-blocking Phase 1 defects are resolved
- [ ] Linting passes (`ruff`)
- [ ] Dependency audit results are recorded (`pip-audit`)
- [ ] Preliminary performance methodology is documented

## Documentation & Git
- [ ] `README.md` accurately describes current functionality
- [ ] Architecture is documented
- [ ] Database schema is documented
- [ ] Financial rules are documented
- [ ] API contracts are documented
- [ ] Design system is documented
- [ ] Security model is documented
- [ ] Test plan exists
- [ ] Known issues are documented
- [ ] Git history contains meaningful development commits
- [ ] Repository remains unpublished
- [ ] Phase 2 handover notes exist
