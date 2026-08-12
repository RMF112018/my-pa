# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Current state

The repository contains the Python package `my_pa` under `src/`, the Alembic
schema history for the canonical database, and a migrated PostgreSQL corpus in
that database. It is a local development candidate: the bounded source and
capture workflows run end to end over synthetic fixtures, but nothing here is
deployable.

Implemented, and covered by the FAST tier unless noted:

- `contracts/v1` — the public request and response envelope, disclosure, error, and capability shapes.
- `domain/identity` — capability, purpose, principal, and operation binding, including all fifteen capability names and their operator-only flags. WP-6 added four `capture.*` names and two capture purposes, WP-7 added `capture.search`, and WP-8 added `review.list` and `review.decide` with `review_disposition`; none is operator-only because none grants external authority (`D-70`, `D-91`, `D-101`).
- `domain/common`, `domain/policy`, `domain/audit` — identifiers, provenance, classification, coverage state, time, policy decisions, and audit events.
- `domain/source` — the source registry, bounded enrollment with idempotency keys, and the read-only source-provider port.
- `domain/capture`, `domain/conversation` — the user-authored capture, immutable version, evidence-bound proposals and assertions, closed review policy, and explicit Conversation Log skeleton. Product-owned and append-only under [ADR-003](docs/decisions/ADR-003-product-owned-user-authored-source-records.md); none grants the source-provider port a write method or an external action.
- `domain/relationship` and the internal relationship application/read-model path — governed person and organisation identity, unresolved mentions, reversible reviewed resolution, source-backed profiles, timelines, and conversation participants over synthetic personal-source fixtures. WP-9 adds no public capability or live connector.
- `domain/extraction` — text and Markdown extraction outcomes, quarantine records, and coverage counts with stated limitations.
- `domain/search` — the lexical search query type.
- `bootstrap/settings` — strict `MY_PA_` configuration that fails closed on unknown or invalid values. `MY_PA_DATABASE_URL` is required and has no default.
- `infrastructure/database/engine` — the connection contract for the canonical database. Covered by the database tier only.
- `infrastructure/persistence` — source registry, enrollment, job lease and retry, extraction and quarantine, lexical search, the immutable capture/version/receipt plane, WP-7's evidence-bound proposal plane, and WP-8's review/promotion plane. Consequential proposals open review cases; accepting creates a canonical assertion plus policy receipt, rejection retains lineage, and a successor edit that changes a cited slice marks the assertion `revalidation_required`. Explicit Conversation Log creation and deterministic launch context are written in the capture save transaction; no external action client exists. **Capture search is a second full-text plane**, over `knowledge.capture_versions.content` with `simple` plus exact confirmation (`D-90`). Covered by the database tier.
- `infrastructure/providers/fixture.py` — a read-only fixture source provider that proves root containment, revalidates before read, and normalizes provider errors by errno.
- `application` — the fifteen capability use cases behind one entry point, one shared authorization and disclosure path, and the capability manifest and readiness report derived from that wiring rather than restated. It reaches persistence and providers only through the ports in `contracts/ports`.
- `adapters/http` and `apps/gateway.py run` — the HTTP transport and its composition root. All fifteen capabilities are reachable at `POST /v1/<capability>` on `127.0.0.1`, and the response body is the envelope the application produced. Starlette and uvicorn, not FastAPI; no credential is issued, read, or required, and there is no option to bind anywhere but loopback. [`ops/runbooks/gateway-operations.md`](ops/runbooks/gateway-operations.md) covers running it.
- `adapters/mcp` and `apps/gateway.py mcp` — the same fifteen capabilities over the Model Context Protocol, using the official `mcp` SDK on **stdio only**. The tool list is derived from the capability set and each tool's schema from the command it builds, so nothing about a capability is written down twice. No socket is opened and no credential is read; the SDK's network transports are never imported.
- `adapters/cli` and `apps/cli/invoke.py` — the operator CLI, which invokes one capability and writes the envelope to standard output. It is not a privileged bypass: it composes the same runtime the gateway composes, is handed the same principal, and has no option that could change one.
- `adapters/normalization.py` — the one place a request becomes a `(RequestMetadata, Command)` pair. All three transports call it and none of them can build either value, which is what makes `SPEC-AC-001` a structural property rather than three snapshots that agree today.
- `infrastructure/migration` — legacy extract and load, the migration control plane, and redaction.
- Twenty-one Alembic revisions covering target schemas and extensions, tables, indexes, foreign keys, the migration control plane, views, the `knowledge` schema, extraction, audit, enrollment, capture, proposal, review/promotion, relationship identity, the native-source control plane, the identity plane (user accounts and scope grants), per-Principal capture partitioning, and per-Principal review/promotion partitioning; head `d2e3f4a5b6c7`. Applied and rolled back in the database tier; only SQL generation is checked by FAST. **No revision derives a closed-set constraint from a domain enum** (`D-69`): historical vocabulary is frozen in each emitting revision and widened by an explicit `ALTER` in the revision that widens it, so an already-merged revision goes on emitting the DDL it emitted on the day it merged.
- `.github/workflows/repository-checks.yml` — document and configuration validation, the FAST tier, a declared-dependency-floor tier, and a database tier run against a disposable PostgreSQL service. The workflow itself carries no test coverage.

The migrated corpus holds 3,263,870 rows across 484 domain tables; 286 of those
tables contain rows and 198 are empty. Those figures were recomputed from the
live database on 2026-08-01. [`docs/migration/00_MIGRATION_INDEX.md`](docs/migration/00_MIGRATION_INDEX.md)
owns the result record and the deliberate exclusions. The legacy SQLite source is
retained read-only and is never mutated.

Two entries stood here until WP-4B3 and are recorded rather than deleted, because
both were true of every earlier commit and a reader of one of those commits
should be able to find out when each stopped being true.

- *"a source registered in production, and therefore anything for the gateway to read… nothing calls `register_source`."* `apps/cli/sources.py register` calls it, and `RegisteredSourceProviders` serves whichever roots the resulting `knowledge.sources` rows name. **`P00-OD-009` is untouched**: no root is configured anywhere in the tree, the command requires `--root` by exact path, and which roots are legitimate is still the operator's decision rather than a default.
- *"an executor for the work the worker claims… there is no extraction executor wired to it."* `src/my_pa/infrastructure/jobs/extraction.py` is that executor, and `apps/worker.py` wires it. A claimed job now reads each enumerated object through its provider and records an extraction, an `unsupported` row, or a quarantine, one transaction per object.

A fourth entry stood in the not-implemented list until WP-7 and is recorded the
same way:

- *"nothing consumes the capture outbox until WP-7"* was true of every commit
  before this one. `apps/worker.py run --plane capture` consumes it:
  `src/my_pa/infrastructure/jobs/capture_pipeline.py` runs nine stages over one
  stored capture version — validate against the processing policy recorded at
  save, normalise with a reversible offset mapping, detect language, segment
  (including quoted and pasted regions), match deterministically, normalise
  moments without resolving relative ones, confirm the text is searchable,
  derive work-object proposals, and persist them with the spans they cite. One
  transaction per stage, `hold_lease` first in each, so a worker whose lease was
  taken writes nothing. **It reads no source, opens no socket, and calls no
  model**; `P00-OD-006` is untouched. What WP-7 did **not** build is named
  rather than implied: no `CaptureDomainAssignment` table (`D-94` — its only
  deterministic input is a WP-8 context link), no accepted record and therefore
  no discharge of `QC-AC-011`'s accepted-derived-record half, which WP-8 owes
  (`D-89`), no alias table and therefore no person or organisation mentions
  (`D-93`), no relative-date resolution, because a stage that reads a clock
  cannot satisfy `QC-AC-035`'s replay clause, and no retry backoff, which
  `release_job` still lacks against `11:216` on the shared job plane (`D-99`).

A third entry stood beside them until WP-6 and is recorded the same way:

- *"user-authored capture … exists beyond a scaffold README"* was in the
  not-implemented list below. It is now four capabilities — `capture.create`,
  `capture.revise`, `capture.read`, `capture.list` — five `knowledge` tables, and
  a save that commits the capture, its version, its submission, its receipt, and
  its queued processing job together or not at all. What WP-6 did **not** build
  is named rather than implied: no remote transport, no registered capture
  client, no delivery attempt log (`D-74`), nothing consumed the capture outbox
  at that point — WP-7 does now, and the entry above says what it did and did
  not build — and captures carry no owner-scoped access control (`D-72`, and
  [`docs/operations/mcv-limitations.md`](docs/operations/mcv-limitations.md)
  limitation 2 is where that is disclosed).

Not implemented. None of the following exists beyond a scaffold README:

- managed documents, GoodNotes ingestion, and Obsidian projection;
- any frontend. The repository contains no JavaScript toolchain and no `package.json`.

Accordingly, `capabilities.get` reports every capability `available` and
readiness `ready`, while PDF still reports `decision_gated` pending
`P00-OD-003`. Both figures are derived from the application's own wiring rather
than from a constant, and `ready` is a statement about the application and not
about a deployment: a process serves it over HTTP on loopback, and the slice now
runs end to end over synthetic fixtures — an operator registers a source, an
enrollment enumerates it, the worker extracts it, and `knowledge.read` returns
one of its records with the identifier enumeration issued.
`tests/end_to_end/test_vertical_slice.py` is that path, walked.
`tests/architecture/test_readme_state_claims.py` holds this paragraph to
the values the build actually produces.

The current gap audit and implementation plan is [`docs/plans/mcv-completion-plan.md`](docs/plans/mcv-completion-plan.md).
On 2026-08-01 the operator reprioritized the objective to admit two features,
Relationship Intelligence and Quick Capture; sections 12 through 14 of that plan
carry the work packages, the decisions that admitted them, and the decisions
still open.

On 2026-08-02 the operator ratified a canonical whole-product definition by
direct instruction, mirrored at [`docs/specs/canonical-product-definition/`](docs/specs/canonical-product-definition/00_README.md).
It settles what the product means; it grants no implementation authority, does
not outrank repository policy, and did not change the plan — its own roadmap
puts finishing WP-4 and WP-5 first, which is what this plan already sequenced.
The 58 operator decisions it carries remain open: 30 `OP`, 9 `MCP-OP`, 9
`NAR-OP`, and 10 `NAPDCB-OP`. Section 15 records the reconciliation and the
instrument it rests on.

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
