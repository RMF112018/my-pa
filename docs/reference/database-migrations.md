# Database and Alembic development

This is the developer playbook for PostgreSQL schema work. `ops/runbooks/postgres-operations.md` remains the deep operational procedure.

## Canonical model

- PostgreSQL is the canonical metadata/knowledge store.
- Logical application database identity is `my_pa`.
- SQLAlchemy persistence adapters live under `src/my_pa/infrastructure/persistence/`.
- Alembic history lives under `migrations/`.
- `MY_PA_DATABASE_URL` is required and has no default.
- Tests must use isolated/disposable databases, never live personal or production data.

## Before changing schema

1. Reauthenticate repository/base identity.
2. Inspect the owning domain and persistence port before the table shape.
3. Run:
   ```sh
   .venv/bin/alembic heads
   ```
   and establish the current single intentional head.
4. Inspect recent revisions and affected schema tests.
5. Define forward/backward compatibility and data-migration needs.
6. Decide how an old row is represented. Do not infer missing semantics merely to populate a new `NOT NULL` field.

## Create a migration

Use Alembic's current revision chain and a descriptive revision message. Keep one intentional head; parallel feature branches that add migrations must reconcile/re-parent or merge the chain deliberately before integration.

A migration should be:

- additive where practical;
- deterministic;
- reviewable independently from application code;
- explicit about constraints, indexes and seed/reference data;
- safe on the supported predecessor state;
- free of implicit destructive target selection.

## Data migrations

For backfills:

- derive only values supported by existing data/accepted rules;
- leave data absent when representation would require guessing;
- make rerun/idempotency behavior explicit where applicable;
- preserve provenance/identity;
- test representative legacy states and invariant failures.

## Validation

At minimum for an affected schema:

1. targeted migration/schema test;
2. empty schema → `head`;
3. relevant predecessor → `head`;
4. affected persistence/database tests;
5. repository PR gate.

Common commands:

```sh
.venv/bin/alembic heads
.venv/bin/alembic upgrade head
python -m pytest tests/schema/<affected_test>.py -q
python -m pytest tests/database/<affected_test>.py -q
```

The exact database-tier CI lanes are defined in `.github/workflows/repository-checks.yml`; do not restate historical test counts.

## Destructive changes

Dropping data, columns/tables, rewriting canonical content, or targeting an existing physical database is not routine migration work. Establish exact target and rollback/recovery evidence and obtain the required operator authorization.

## Rollback expectations

Do not assume every schema revision has a safe production downgrade. For a change that cannot be safely reversed in place, document forward-fix/restore strategy before implementation.

## Baseline / squash policy

The repository currently retains the full Alembic chain. This campaign does **not** authorize a baseline squash. A future squash requires a separate repo-truth migration assessment, compatibility decision, exact supported starting-state definition, and independent validation; documentation cleanup is not schema-history authority.
