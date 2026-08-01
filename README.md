# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Current state

The repository contains the Python package `my_pa` under `src/`, the Alembic schema history for the canonical database, and a migrated PostgreSQL corpus in that database. It is a local development candidate: no product workflow runs end to end, and nothing here is deployable.

Implemented, and covered by the FAST tier unless noted:

- `contracts/v1` — the public request and response envelope, disclosure, error, and capability shapes.
- `domain/identity` — capability, purpose, principal, and operation binding, including all eight capability names and their operator-only flags.
- `domain/common`, `domain/policy`, `domain/audit` — identifiers, provenance, classification, time, policy decisions, and audit events.
- `bootstrap/settings` — strict `MY_PA_` configuration that fails closed on unknown or invalid values.
- `infrastructure/database/engine` — the connection contract for the canonical database. Covered by the database tier only.
- `application/capabilities` — derives the capability manifest and readiness report from the contract rather than restating them.
- `infrastructure/migration` — legacy extract and load, the migration control plane, and redaction.
- Six Alembic revisions covering target schemas and extensions, tables, indexes, foreign keys, the migration control plane, and views; head `6c4d3ea82f10`.
- `.github/workflows/repository-checks.yml` — document and configuration validation, the FAST tier, a declared-dependency-floor tier, and a database tier run against a disposable PostgreSQL service.

The migrated corpus holds 3,263,870 rows across 484 domain tables; 286 of those tables contain rows and 198 are empty. Those figures were recomputed from the live database on 2026-08-01. [`docs/migration/00_MIGRATION_INDEX.md`](docs/migration/00_MIGRATION_INDEX.md) owns the result record and the deliberate exclusions. The legacy SQLite source is retained read-only and is never mutated.

Not implemented. Nothing below `contracts` and `domain` executes a product workflow, and none of the following exists beyond a scaffold README:

- source registry, enrollment persistence, or any source provider, including a fixture provider;
- extraction, quarantine, coverage, and version-fingerprint binding;
- full-text search over enrolled content;
- the application job, lease, and retry plane; the migration control plane is migration-specific and is not that plane;
- HTTP transport and MCP adapter — `apps/gateway` is a README;
- the worker process — `apps/worker` is a README;
- an operator CLI beyond `apps/cli/migration.py`;
- managed documents, structured knowledge records, relationship services, GoodNotes ingestion, and Obsidian projection;
- any frontend. The repository contains no JavaScript toolchain and no `package.json`.

Accordingly, every capability reports `not_implemented`, PDF reports `decision_gated` pending `P00-OD-003`, and readiness reports `contracts_only`.

The current gap audit and implementation plan is [`docs/plans/mcv-completion-plan.md`](docs/plans/mcv-completion-plan.md).

## Approved architectural decisions

- Repository: `RMF112018/my-pa`
- Delivery model: modular monolith in one monorepo with separate gateway and worker processes plus an operator CLI
- Python namespace: `my_pa`
- Configuration prefix: `MY_PA_`
- Canonical logical database identity: `my_pa`
- Physical database: the canonical local `my_pa` PostgreSQL instance, bound to loopback port 5433, established by the accepted migration; the legacy source is retained read-only and no other physical database is a connection target
- External capability names: neutral; no legacy product aliases

## Repository map

Start with [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md).

## Boundaries

Original source systems remain authoritative and read-only by default. Managed output storage is a separate capability. PostgreSQL is the canonical metadata and knowledge store. Obsidian is a rebuildable projection, not the authority.

Schema changes reach the canonical database only through Alembic. Configuration fails closed: an unknown `MY_PA_` variable, an unparseable value, or a database URL that is not `postgresql+psycopg` naming a host and a database is rejected at startup. No source-system mutation, managed-document write, connector access, credential use, live-source read, service activation, deployment, or production action is authorized by the current repository state; each requires separate operator authorization.
