# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Current state

The repository contains the Python package `my_pa` under `src/`, the Alembic
schema history for the canonical database, and a migrated PostgreSQL corpus in
that database. It is a local development candidate: no product workflow runs end
to end, and nothing here is deployable.

Implemented, and covered by the FAST tier unless noted:

- `contracts/v1` — the public request and response envelope, disclosure, error, and capability shapes.
- `domain/identity` — capability, purpose, principal, and operation binding, including all eight capability names and their operator-only flags.
- `domain/common`, `domain/policy`, `domain/audit` — identifiers, provenance, classification, coverage state, time, policy decisions, and audit events.
- `domain/source` — the source registry, bounded enrollment with idempotency keys, and the read-only source-provider port.
- `domain/extraction` — text and Markdown extraction outcomes, quarantine records, and coverage counts with stated limitations.
- `domain/search` — the lexical search query type.
- `bootstrap/settings` — strict `MY_PA_` configuration that fails closed on unknown or invalid values. `MY_PA_DATABASE_URL` is required and has no default.
- `infrastructure/database/engine` — the connection contract for the canonical database. Covered by the database tier only.
- `infrastructure/persistence` — source registry, enrollment, job lease and retry, extraction and quarantine, and lexical search over `knowledge.extractions`. Covered by the database tier.
- `infrastructure/providers/fixture.py` — a read-only fixture source provider that proves root containment, revalidates before read, and normalizes provider errors by errno.
- `application/capabilities` — derives the capability manifest and readiness report from the contract rather than restating them.
- `infrastructure/migration` — legacy extract and load, the migration control plane, and redaction.
- Eight Alembic revisions covering target schemas and extensions, tables, indexes, foreign keys, the migration control plane, views, the `knowledge` schema, and the extraction tables; head `8b3f5c17d904`. Applied and rolled back in the database tier; only SQL generation is checked by FAST.
- `.github/workflows/repository-checks.yml` — document and configuration validation, the FAST tier, a declared-dependency-floor tier, and a database tier run against a disposable PostgreSQL service. The workflow itself carries no test coverage.

The migrated corpus holds 3,263,870 rows across 484 domain tables; 286 of those
tables contain rows and 198 are empty. Those figures were recomputed from the
live database on 2026-08-01. [`docs/migration/00_MIGRATION_INDEX.md`](docs/migration/00_MIGRATION_INDEX.md)
owns the result record and the deliberate exclusions. The legacy SQLite source is
retained read-only and is never mutated.

Not implemented. None of the following exists beyond a scaffold README:

- application services binding the eight capabilities to the persistence and provider behavior that exists;
- HTTP transport and MCP adapter — `apps/gateway` is a README;
- the worker process — `apps/worker` is a README;
- an operator CLI beyond `apps/cli/migration.py`;
- user-authored capture, relationship identity and profiles, managed documents, GoodNotes ingestion, and Obsidian projection;
- any frontend. The repository contains no JavaScript toolchain and no `package.json`.

Accordingly, every capability still reports `not_implemented`, PDF reports
`decision_gated` pending `P00-OD-003`, and readiness reports `contracts_only` —
the pieces exist but nothing composes them into a running capability yet.

The current gap audit and implementation plan is [`docs/plans/mcv-completion-plan.md`](docs/plans/mcv-completion-plan.md).
On 2026-08-01 the operator reprioritized the objective to admit two features,
Relationship Intelligence and Quick Capture; sections 12 through 14 of that plan
carry the work packages, the decisions that admitted them, and the decisions
still open.

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
