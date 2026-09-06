# MY-PA

MY-PA is a local-first personal knowledge and work-management application. It mediates access to authoritative source material, product-owned records, relationship intelligence, work/commitment state, intelligence artifacts, GoodNotes-derived knowledge, and model-facing context while keeping identity, authorization, provenance, and disclosure decisions in one application boundary.

The repository is the authority for **current executable technical truth**. Accepted product and UX intent lives in the cleaned MY-PA Google Drive library; start from the [current product-definition index](https://docs.google.com/document/d/1PAT3Vc6Y2POeqy5d9yHnnZLD5OWppsEw6Mwpv9UesNs/edit).

## Current supported scope

The codebase is an unreleased Minimum Viable Candidate (MCV), not a generally deployed service. Current implementation includes:

- a Python modular monolith with HTTP, MCP, CLI, worker, persistence, policy, and audit boundaries;
- PostgreSQL-backed knowledge, work, capture, relationship, review, and report planes;
- a Next.js App Router PWA/BFF under `web/`;
- local MCP over stdio and a separately enabled authenticated remote MCP surface;
- Tasks and Commitments, Relationship Intelligence, Quick Capture, GoodNotes/GSQS, Intelligence Artifacts/Reports, managed-document capabilities, and supporting continuity/context surfaces;
- a pure-domain first increment of Project Controls Constraint Management. Persistence, public capabilities, synchronization, MCP, and frontend behavior for Constraints must not be inferred from those domain primitives.

Availability is composition- and feature-gate-dependent. Use `capabilities.get` and the current application wiring rather than a copied capability count to determine what a running process serves.

## Architecture at a glance

```text
Browser / PWA
    |
    | server-side BFF routes, opaque session identity
    v
Python gateway  <---->  MCP clients / operator CLI
    |
    v
application use cases + authorization + disclosure
    |
    +--> domain + transport-neutral contracts
    |
    +--> infrastructure adapters
           +--> PostgreSQL
           +--> read-only source providers
           +--> managed-document byte store when configured
           +--> bounded worker/job planes
```

The main Python dependency direction is documented in [Backend and domain architecture](docs/architecture/backend-domain.md). The web application is a BFF over Python capabilities, not a second domain implementation.

## Repository structure

| Path | Purpose |
|---|---|
| `src/my_pa/domain/` | Domain values, aggregates, invariants, lifecycle rules |
| `src/my_pa/contracts/` | Transport-neutral public shapes and application ports |
| `src/my_pa/application/` | Use cases, orchestration, authorization/disclosure |
| `src/my_pa/adapters/` | Driving adapters: HTTP, MCP, CLI normalization/mapping |
| `src/my_pa/infrastructure/` | Persistence, providers, jobs, migration and other driven adapters |
| `src/my_pa/bootstrap/` | Validated configuration and dependency composition |
| `apps/` | Python process/CLI composition roots |
| `web/` | Next.js PWA and BFF |
| `migrations/` | Alembic schema history |
| `ops/` | Runtime definitions, NAS assets, and detailed runbooks |
| `tests/` | Unit, contract, architecture, schema/database, security, E2E and recovery tests |
| `docs/` | Current developer playbook plus retained historical/supporting records |

## Prerequisites

- Python 3.12+
- PostgreSQL 17-compatible local test/runtime environment
- Node.js 20 for the web application and frontend CI parity
- npm with the committed `web/package-lock.json`
- Docker/Compose when using repository PostgreSQL or NAS runtime definitions

See [Getting started](docs/development/getting-started.md) for the deterministic local path.

## Installation / bootstrap

Python:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Web:

```sh
cd web
npm ci
```

Do not copy secrets from documentation. `.env.example` and `web/.env.example` are variable-name/configuration references only.

## Configuration / environment model

Python settings use the `MY_PA_` prefix and fail closed on unknown names or invalid values. `MY_PA_DATABASE_URL` is required and has no default. The canonical parser is `src/my_pa/bootstrap/settings.py`.

Important boundaries:

- `MY_PA_AUTH_MODE`: Python HTTP identity mode (`local_operator` or `entra`);
- `MY_PA_DATABASE_URL`: required `postgresql+psycopg` target;
- feature/write/remote switches are explicit and default toward refusal;
- managed-document storage has no inferred root;
- real tenant IDs, credentials, source roots, and personal paths do not belong in tracked examples.

Web configuration is separately defined by `web/.env.example`. See [Configuration reference](docs/reference/configuration.md).

## Local execution

Start PostgreSQL with the repository Compose definition when appropriate:

```sh
docker compose -f ops/compose/postgres.yml up -d
```

After explicitly targeting the intended database:

```sh
export MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/<disposable-or-explicit-database>
.venv/bin/alembic upgrade head
```

Run the HTTP gateway:

```sh
.venv/bin/python apps/gateway.py run
```

Run local MCP over stdio:

```sh
.venv/bin/python apps/gateway.py mcp
```

Run a worker plane:

```sh
.venv/bin/python apps/worker.py run --plane enrollment
.venv/bin/python apps/worker.py run --plane capture
.venv/bin/python apps/worker.py run --plane reenrichment
```

Use the detailed procedures under `ops/runbooks/` for operational work rather than extrapolating from these examples.

## Database and Alembic

PostgreSQL is the canonical metadata/knowledge store. Alembic is the schema-change mechanism. Never assume a target database from a shell or old runbook; confirm `MY_PA_DATABASE_URL` before migration work.

For development:

```sh
.venv/bin/alembic heads
.venv/bin/alembic current -v
.venv/bin/alembic upgrade head
```

Schema work must preserve a single intentional migration head, use isolated databases for migration tests, and avoid destructive behavior unless separately authorized. See [Database and migration playbook](docs/reference/database-migrations.md).

## Testing and quality gates

Fast Python development loop:

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"
```

Frontend:

```sh
cd web
npm test
npm run lint
npm run typecheck
npm run build
```

`repository-checks.yml` and `frontend-quality.yml` are the executable CI definitions. Do not copy a historical test count into a current plan. See [Testing and review](docs/development/testing-and-review.md).

## Major integrations

- PostgreSQL for canonical application state.
- Filesystem/NAS source providers, read-only by default.
- Managed-document storage only at an explicitly configured managed root.
- Apple-source bridge/runtime components with separate TCC and platform boundaries.
- GoodNotes local-source and GSQS processing surfaces.
- MCP for model/agent access.
- Next.js web BFF for the browser application.

Product-intent references are routed from the Drive product-definition index; implementation truth is in this repository.

## MCP architecture

All transports converge on the same application capability model. MCP tools are derived from available application capabilities and command schemas rather than maintained as a second capability registry.

- `apps/gateway.py mcp`: local stdio; opens no socket.
- `apps/gateway.py mcp-remote`: separately enabled authenticated remote MCP.
- remote grants, purposes, feature gates, policy and write switches remain independent gates.
- client identity never creates authority by itself.

See [MCP and agent integration](docs/architecture/mcp-and-agent-integration.md) and [MCP capability reference](docs/reference/mcp-capabilities.md).

## Frontend / web application

`web/` is a Next.js App Router PWA. Browser identity is resolved server-side; the browser does not supply a Principal or gateway bearer. The production browser-auth target is passkey/WebAuthn with opaque server-side sessions; synthetic identity remains development-only and is refused in production.

The BFF maps browser routes to Python capabilities and preserves typed refusals/disclosure states. Quick Capture has a bounded encrypted offline queue with foreground replay; offline behavior is not a general background-sync guarantee.

See [Frontend/BFF/PWA architecture](docs/architecture/frontend-bff-pwa.md) and `web/README.md`.

## Deployment / runtime model

Repository deployment assets are under `ops/`, including PostgreSQL Compose, container definitions, NAS lifecycle material and runbooks. A normal runtime separates web, gateway/worker processes and persistence while preserving explicit network and filesystem boundaries.

For any AI-agent request to build or deploy the NAS package, repository policy routes first through `.codex/skills/my-pa-nas-build-deploy/SKILL.md`. That skill does not authorize deployment.

See [Deployment/runtime architecture](docs/architecture/deployment-runtime.md) and [Deployment operations](docs/operations/deployment.md).

## Observability / troubleshooting

Observability is deliberately content-minimizing:

- process startup/state information rather than sensitive request payload logging;
- worker heartbeats and backlog/dead-letter state;
- typed application errors/disclosures;
- `/api/system` for web-visible runtime/readiness information;
- Docker/Compose/process status in runbooks.

Start with [Troubleshooting](docs/operations/troubleshooting.md) and [Observability](docs/operations/observability.md).

## Security / privacy

The repository defaults to local-first, least privilege, synthetic test data, explicit data eligibility, source-system read-only behavior and fail-closed configuration. Never commit credentials, personal data, source contents, connection strings, private paths or unredacted evidence.

Read `SECURITY.md` and [Authentication and security architecture](docs/architecture/authentication-security.md) before security-sensitive work.

## Authoritative documentation navigation

1. `README.md` — orientation and high-level commands.
2. `AGENTS.md` — principal repository policy.
3. [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md) — current technical router.
4. The nearest current architecture/development/domain/operations/reference document.
5. Accepted ADRs when a durable architectural decision controls the change.
6. Drive product-definition index when product/UX intent is required.

Historical campaigns, plans, audits and mirrored product packages are retained evidence/supporting material, not normal technical navigation.

## AI-agent entry points

AI coding agents must start with `AGENTS.md`, then `AI_OPERATING_MANUAL.md`, then the repository source index and the nearest owning current reference. Tool-specific routers do not create independent policy.

A new feature should be planned using [`docs/development/feature-development-playbook.md`](docs/development/feature-development-playbook.md).

## Current limitations

- MY-PA is unreleased; repository presence is not production activation.
- live personal-data access, credential mutation, source-system mutation and deployment are separately controlled operations;
- some capabilities are feature/composition-gated and therefore not served by a default process;
- Constraint Management is only at its pure-domain foundation in current `main`;
- managed-document capabilities exist in Python but the current web package does not expose a managed-document screen;
- lexical PostgreSQL retrieval is the baseline; semantic/vector infrastructure is not a default prerequisite;
- detailed runtime evidence in old runbooks may describe the head at which it was measured, not current repository state.

## Contribution / development workflow

Use one bounded objective, branch from authenticated current `main`, implement the smallest correct change, run the applicable test tier, update current docs when behavior/contracts/architecture/operations/workflow change, and request review against the exact head.

See `CONTRIBUTING.md` and [Development workflow](docs/development/development-workflow.md).
