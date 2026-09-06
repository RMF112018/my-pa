# Getting started

This is the shortest deterministic path for a developer or coding agent entering MY-PA.

## 1. Read before changing anything

1. `README.md`
2. `AGENTS.md`
3. `AI_OPERATING_MANUAL.md` for AI-assisted work
4. `docs/00_REPOSITORY_SOURCE_INDEX.md`
5. the nearest current architecture/domain/reference documents for the change
6. accepted ADRs that govern the affected boundary

Use the cleaned Drive product-definition index only when accepted product/UX intent is needed.

## 2. Authenticate repository state

Before planning:

```sh
git fetch origin
git status --short --branch
git rev-parse origin/main
git rev-parse 'origin/main^{tree}'
git worktree list --porcelain
```

Also inspect open PRs that touch the same paths/contracts. Record the exact base in the plan/PR.

Do not put the exact base SHA into durable current guides; it belongs in work/review evidence.

## 3. Python environment

Python 3.12+ is required.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The package/dependency authority is `pyproject.toml`.

## 4. PostgreSQL

Repository-local PostgreSQL:

```sh
docker compose -f ops/compose/postgres.yml up -d
docker compose -f ops/compose/postgres.yml ps
```

Set an explicit database URL:

```sh
export MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/<database>
```

`MY_PA_DATABASE_URL` is required. For migration/database development, use a disposable database, not a shared/canonical target.

Then:

```sh
.venv/bin/alembic heads
.venv/bin/alembic upgrade head
```

Read `docs/reference/database-migrations.md` before schema changes.

## 5. Python gateway / MCP / workers

HTTP gateway:

```sh
.venv/bin/python apps/gateway.py run
```

Local MCP over stdio:

```sh
.venv/bin/python apps/gateway.py mcp
```

Worker:

```sh
.venv/bin/python apps/worker.py run --plane enrollment
```

Use `--plane capture` or `--plane reenrichment` for those planes. Read `ops/runbooks/README.md` before operational work.

## 6. Web

```sh
cd web
npm ci
npm run dev
```

The BFF requires explicit web/gateway/session configuration. Read `web/.env.example` and `web/README.md`; do not commit real secrets or tenant/source values.

## 7. Fast validation

Python:

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"
```

Web:

```sh
cd web
npm test
npm run lint
npm run typecheck
npm run build
```

A feature may require database, security, contract, E2E, recovery or specialized tests in addition to these commands.

## 8. First implementation plan

Use `feature-development-playbook.md`. A correct plan identifies every affected layer before coding and explicitly says which layers are unaffected.

## 9. Common mistakes

- treating a scaffold directory as implementation authority;
- reading an old plan as current code truth;
- pointing Alembic at an inferred database;
- adding domain decisions to a BFF/MCP adapter;
- caller-supplied Principal identity;
- copying historical capability/migration/test counts;
- assuming a feature flag grants remote/deployment authority;
- using live personal data for development tests;
- changing an unrelated layer “while here”.
