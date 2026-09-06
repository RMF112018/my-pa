# Testing and review

Executable test/CI truth lives in `pyproject.toml`, `web/package.json`, the test tree and `.github/workflows/`.

## Test architecture

### FAST
The default Python development loop excludes expensive/external classes:

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"
```

FAST is intended for deterministic domain/application/contract work without database/network/model/E2E dependencies. Application tests use fakes where persistence is not the subject.

### Database/schema
Use isolated PostgreSQL databases for:

- Alembic empty-to-head / upgrade-path checks;
- SQLAlchemy repository behavior;
- constraints/locking/idempotency;
- Principal partitioning;
- migrations/backfills;
- recovery behavior.

Database setup is intentionally expensive and is not part of the FAST contract. `tests/conftest.py` plus schema/database helpers own fixture behavior; do not create an ad hoc shared database fixture in one feature test.

### Contract / policy / security
`tests/contract/`, `tests/policy/` and `tests/security/` protect:

- transport parity;
- capability/request/response contracts;
- authorization and Principal derivation;
- BFF decoder parity;
- remote MCP/HTTP boundaries;
- negative/refusal behavior;
- filesystem/data-disclosure boundaries.

### Frontend
From `web/`:

```sh
npm test
npm run lint
npm run typecheck
npm run build
```

`npm run test:contract` targets gateway decoder parity.

### Browser E2E / accessibility / responsive
`npm run e2e` runs the repository browser stack and uses a disposable PostgreSQL database plus loopback Python/Next servers. Frontend CI selects curated security, journey, accessibility and responsive suites.

Do not use a live Entra tenant or live personal data for automated E2E.

### Recovery / specialized evaluation
Recovery, connector, evaluation and other specialized markers run only when directly relevant. They are not silently promoted/demoted merely to change CI duration.

## CI

### `repository-checks`
Runs on PRs to `main`, pushes to `main`, and manual dispatch. Important behaviors include:

- exact checkout identity recording;
- relative Markdown link validation;
- required governance-path checks;
- YAML validation;
- Python Ruff/format/mypy/FAST;
- web-security checks;
- dependency-floor validation;
- database-tier work and other repository checks.

Read the workflow before changing tier assumptions; historical comments/counts in prose are not a substitute for its current commands.

### `frontend-quality`
Runs on PRs/pushes to `main`. A classifier decides whether frontend-relevant paths changed, then conditionally runs static, unit, production build, contract, security, E2E, accessibility/responsive and related jobs.

A documentation-only change may legitimately classify frontend work as not applicable; the repository-level docs/link gate still applies.

## Adding tests for a feature

1. prove pure invariants at the lowest deterministic layer;
2. add application tests with fakes for orchestration/policy;
3. add database tests only for persistence/schema properties;
4. add transport contract/security tests for public behavior;
5. add frontend unit/decoder tests for BFF/UI logic;
6. add E2E only for cross-process/browser behavior that lower tiers cannot prove;
7. add recovery/evaluation when the acceptance criterion requires it.

Avoid duplicating the same expensive scenario across jobs without a distinct contract.

## Markers

Markers are registered in `pyproject.toml`. Current classes include `slow`, `database`, `network`, `connector`, `evaluation`, `e2e`, `recovery` and database-fixture strategy markers. Use the current file rather than copying this list into test code.

## Review preparation

Before requesting review:

- authenticate exact head/tree;
- ensure the diff is bounded to the objective;
- run applicable tests/CI;
- disclose every failure, skip, unavailable dependency and limitation;
- state migration/config/security/runtime impact;
- ensure docs/examples/links are current;
- identify deferred/operator-only work.

An exact-head review is invalid after a later commit.

## Review quality

An independent review should challenge:

- acceptance-criteria coverage;
- architecture/dependency direction;
- authorization/data isolation;
- migration safety;
- contract compatibility;
- failure/idempotency/recovery behavior;
- test quality, not only pass count;
- docs/runtime command accuracy;
- hidden scope expansion.

Passing CI is evidence, not self-approval or production readiness.
