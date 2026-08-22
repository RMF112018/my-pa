# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Operating lineage

The current pilot-remediation candidate is developed on
`bf/pilot-blocker-remediation` from authenticated `main` base
`9b35476b70fe4fbc03bb8f9835d93c1b71089bbe`. The earlier
`recovery/pre-20260805-utc-rollback-c9fb513` lineage remains preserved as
campaign history; it is no longer current-state authority. The exact candidate
head belongs in the pull request and remediation closeout rather than in this
file, where every commit would immediately stale it.

## Current state

The repository contains the Python package `my_pa` under `src/`, the Alembic
schema history for the canonical database, and a migrated PostgreSQL corpus in
that database. It is a local development candidate: the bounded source and
capture workflows run end to end over synthetic fixtures, but nothing here is
deployable.

Implemented, and covered by the FAST tier unless noted:

- `contracts/v1` — the public request and response envelope, disclosure, error, and capability shapes.
- `domain/identity` — capability, purpose, principal, and operation binding, including all seventy capability names and their operator-only flags. WP-6 added four `capture.*` names and two capture purposes, WP-7 added `capture.search`, WP-8 added `review.list` and `review.decide` with `review_disposition`, and WP-29 added the eight `relationship_memory.` names with the `relationship_memory_read` and `relationship_memory_authoring` purposes; none is operator-only because none grants external authority (`D-70`, `D-91`, `D-101`).
- `domain/common`, `domain/policy`, `domain/audit` — identifiers, provenance, classification, coverage state, time, policy decisions, and audit events.
- `domain/source` — the source registry, bounded enrollment with idempotency keys, and the read-only source-provider port.
- `domain/capture`, `domain/conversation` — the user-authored capture, immutable version, evidence-bound proposals and assertions, closed review policy, and explicit Conversation Log skeleton. Product-owned and append-only under [ADR-003](docs/decisions/ADR-003-product-owned-user-authored-source-records.md); none grants the source-provider port a write method or an external action.
- `domain/relationship` and the internal relationship application/read-model path — governed person and organisation identity, unresolved mentions, reversible reviewed resolution, source-backed profiles, timelines, and conversation participants over synthetic personal-source fixtures. WP-9 added no public capability or live connector; the later Relationship Intelligence entity plane added six, `entities.search`, `entities.get`, `entities.resolve`, `entities.context`, `entities.relationships` and `entities.unresolved_mentions`, all read-only under the single `entity_read` purpose and all withheld unless `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` is set. Corrected 2026-08-19: this bullet said only "WP-9 adds no public capability", which was true of WP-9 and read as true of the plane. Corrected again 2026-08-20: it then said the plane added *five* and listed five, while three other sentences in this same file say six — `entities.unresolved_mentions` was admitted after this bullet was written and not carried into it. The spelled-count guard did not see it because the number was followed by a comma rather than the noun it counts; that shape is now read. [`ops/runbooks/relationship-intelligence.md`](ops/runbooks/relationship-intelligence.md) is the operator document for it, and records that its governance service is composed by nothing and so cannot yet be worked.
- `domain/extraction` — text and Markdown extraction outcomes, quarantine records, and coverage counts with stated limitations.
- `domain/search` — the lexical search query type.
- `bootstrap/settings` — strict `MY_PA_` configuration that fails closed on unknown or invalid values. `MY_PA_DATABASE_URL` is required and has no default.
- `infrastructure/database/engine` — the connection contract for the canonical database. Covered by the database tier only.
- `infrastructure/persistence` — source registry, enrollment, job lease and retry, extraction and quarantine, lexical search, the immutable capture/version/receipt plane, WP-7's evidence-bound proposal plane, and WP-8's review/promotion plane. Consequential proposals open review cases; accepting creates a canonical assertion plus policy receipt, rejection retains lineage, and a successor edit that changes a cited slice marks the assertion `revalidation_required`. Explicit Conversation Log creation and deterministic launch context are written in the capture save transaction; no external action client exists. **Capture search is a second full-text plane**, over `knowledge.capture_versions.content` with `simple` plus exact confirmation (`D-90`). Covered by the database tier.
- `infrastructure/providers/fixture.py` — a read-only fixture source provider that proves root containment, revalidates before read, and normalizes provider errors by errno.
- `application` — the seventy capability use cases behind one entry point, one shared authorization and disclosure path, and the capability manifest and readiness report derived from that wiring rather than restated. It reaches persistence and providers only through the ports in `contracts/ports`. The set includes the task-management and commitment plane (`tasks.*`, `commitments.*`), the context-prepare plane (`context.prepare`, `context.feedback`), the GoodNotes semantic plane (`goodnotes.work`, `goodnotes.content`, `goodnotes.propose`), and the Intelligence Artifact report plane (`reports.begin_cycle`, `reports.commit`, `reports.record_run_state`, `reports.read`, `reports.latest`, `reports.list`, `reports.search`, `reports.resolve_set`), which is served by a default process rather than gated: unlike `documents.` and `entities.`, it needs nothing of the composition root that a default process withholds. The Relationship Memory plane (`relationship_memory.create`, `relationship_memory.get`, `relationship_memory.list`, `relationship_memory.search`, `relationship_memory.history`, `relationship_memory.revise`, `relationship_memory.archive`, `relationship_memory.restore`) is gated the other way and by two switches rather than one: it needs `MY_PA_RELATIONSHIP_MEMORY_ENABLED` *and* the entity plane, because a memory binds an Entity as its subject and ownership is proven by reading `knowledge.entities`.
- `adapters/http` and `apps/gateway.py run` — the HTTP transport and its composition root. All seventy capabilities are routable at `POST /v1/<capability>` on `127.0.0.1`, and the response body is the envelope the application produced — but routable is not served: on a default process the six `documents.` names, the six `entities.` names and the eight `relationship_memory.` names answer `501 unsupported`, because `/v1/{capability}` is a path parameter and dispatch reaches the handler, which refuses. Corrected 2026-08-19 from "reachable", which read as available. Starlette and uvicorn, not FastAPI. In `local_operator` mode the process serves one configured Principal without a request credential; in `entra` mode it requires and validates a bearer token. There is no option to bind anywhere but loopback. [`ops/runbooks/gateway-operations.md`](ops/runbooks/gateway-operations.md) covers running it.
- `adapters/mcp` and `apps/gateway.py mcp` — the same seventy capabilities over the Model Context Protocol, using the official `mcp` SDK on **stdio only**. The tool list is derived from `ApplicationService.available_capabilities` and each tool's schema from the command it builds, so nothing about a capability is written down twice. Corrected 2026-08-19: this said the list is derived from "the capability set", which reads as the whole set; `server.py` reads `available_capabilities`, so a default process publishes fifty tools and withholds the six `documents.` names, the six `entities.` names and the eight `relationship_memory.` names until their variables are set — the published figure is unchanged because every name WP-29 added arrived on the withheld side of that split. [`ops/runbooks/mcp-and-cli-operations.md`](ops/runbooks/mcp-and-cli-operations.md) states the same split. No socket is opened and no credential is read; the SDK's network transports are never imported.
- `adapters/cli` and `apps/cli/invoke.py` — the operator CLI, which invokes one capability and writes the envelope to standard output. It is not a privileged bypass: it composes the same runtime the gateway composes, is handed the same principal, and has no option that could change one.
- `adapters/normalization.py` — the one place a request becomes a `(RequestMetadata, Command)` pair. All three transports call it and none of them can build either value, which is what makes `SPEC-AC-001` a structural property rather than three snapshots that agree today.
- `infrastructure/migration` — legacy extract and load, the migration control plane, and redaction.
- Sixty-six Alembic revisions covering the complete local-candidate schema; head `f1c6b904a2d7`. The chain includes the DDL-free native-baseline/managed-document merge, the merge of task-management `7504585e3ca5` with context-prepare `c6f1a8d3e204`, the additive `tasks.description` column with `pulse_items.priority` → `attention_rank` rename, additive OAuth refresh-token families, additive GoodNotes notebook lineage, logical pages, and run ledger, additive GoodNotes NOTE_UNIT occurrence, revision, link, and run-change persistence, additive GoodNotes semantic work/proposal capabilities with an insert-only proposal receipt table, additive GoodNotes entity associations with NEW-only delivery receipts, and additive GoodNotes exact visual render digests, additive `goodnotes.content` vocabulary, additive durable-note stage ledger and Principal-bound page rasters, additive GoodNotes server-grounded NOTE_UNIT crop identity with immutable revision provenance, additive GoodNotes Meeting/Agenda association kinds with NOTE_UNIT-scoped `note-unit.v2` semantics, and an additive dormant GoodNotes delivery-attempt ledger, and the relationship-intelligence entity tables `entities`, `entity_external_identifiers`, `entity_assignments`, and `entity_relationships`, the additive `entity_aliases` table (`b7f4d1a92c36`), and the admission of the `entities.*` capability family (`entities.search`, `entities.get`, `entities.resolve`, `entities.context`, `entities.relationships`) and the `entity_read` purpose to the `audit_events` closed sets (`c1a7e4b93d58`), and the entity observation, proposal, and merge-lineage tables `entity_observations`, `entity_proposals`, and `entity_merge_records` (`d2b8f5c04e71`), which add no capability and no purpose, and the admission of `entities.unresolved_mentions` to the same closed set (`e4d7b2f9a316`), which adds no table, and the additive nullable `entity_observations.mention_display_name` that the unresolved-mention queue reads in place of the matched form (`f3a8c1d7e592`), which adds no capability, and the Intelligence Artifact plane's cycle-run, producer-run, immutable-artifact, commit-receipt, pipeline-dependency and external-provenance tables with the eight `reports.*` capabilities and the `report_authoring`/`report_read` purposes (`e9b2c4d7a150`), and the Relationship Memory plane's `relationship_memories`, `relationship_memory_versions`, `relationship_memory_submissions`, `relationship_memory_context_links`, `relationship_memory_evidence_links`, `relationship_memory_proposals`, `relationship_memory_proposal_evidence` and `relationship_memory_review_decisions` tables, with two `BEFORE UPDATE OR DELETE` triggers making the version and decision ledgers append-only, and the admission of the eight `relationship_memory.` names and the `relationship_memory_read`/`relationship_memory_authoring` purposes to the `audit_events` closed sets in the same revision (`f1c6b904a2d7`), which travel together because this is the first revision in the chain that knows the word. Applied and rolled back in the database tier; SQL generation is checked by FAST. **No revision derives a closed-set constraint from a domain enum** (`D-69`): historical vocabulary is frozen in each emitting revision and widened by an explicit `ALTER` in the revision that widens it.
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

Not implemented. The following remains outside this candidate:

- live activation of personal connectors, production Entra registration, and
  the Obsidian projection.

A frontend exists under [`web/`](web/README.md): a Next.js App Router PWA
(MossAIc) whose normal application routes call the Python capability gateway.
It supports the synthetic development provider and a server-side Entra
authorization-code + PKCE callback/session path; no caller supplies a Principal
and the gateway bearer stays in the server-side session registry. The flow is
verified with synthetic MSAL results only — no live tenant credential or live
personal data was used — and the candidate is not deployed. Personal-data ingestion is Apple-first: Apple Mail, Calendar, Contacts, and Tasks/To-Do through
the first-party native Apple architecture
([`native/apple-source-host/README.md`](native/apple-source-host/README.md)) are
the active ingestion direction. Microsoft Graph is retained in the product
definition but **off by default and not an active personal-data ingestion path**;
Entra authentication is a separate concern from Graph connector activation, and a
disabled Graph connector must not be reported as a degraded active source.

Accordingly, in a fully composed process — one given both
`MY_PA_MANAGED_DOCUMENT_ROOT` and `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` —
`capabilities.get` reports every capability `available` and
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

**A default process is not that process, and this paragraph did not say so.**
Corrected 2026-08-19: it read "Accordingly, `capabilities.get` reports every
capability `available` and readiness `ready`" with no composition named, which is
true only of a process given both variables above. Neither is set by default
(`managed_document_root` defaults to `""` and `relationship_intelligence_enabled`
to `False` in `bootstrap/settings.py`), so a default process publishes a manifest
in which 42 of the 54 capabilities are `available` and 12 — the six `documents.`
and six `entities.` names — are `not_implemented`, and readiness is `degraded`
with the limitation `12 of 54 capabilities are unwired.` Derived by building the
manifest both ways from the dispatch table, exactly as `_capabilities_get` does:
`build_capability_manifest(implemented=frozenset(_HANDLERS) - _ENTITY_CAPABILITIES
- _MANAGED_CAPABILITIES, limits=...)`. `test_readme_state_claims.py` holds the
paragraph above honest against the fully-composed manifest only; the
default-composition figures in this paragraph are stated, not yet bound.

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

Start with [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md). The active campaign state — operating lineage, active work package, branch topology, and reconciliation posture — is [`docs/campaign/CAMPAIGN-BRIEF.md`](docs/campaign/CAMPAIGN-BRIEF.md).

## Boundaries

Original source systems remain authoritative and read-only by default. Managed output storage is a separate capability. PostgreSQL is the canonical metadata and knowledge store. Obsidian is a rebuildable projection, not the authority.

Schema changes reach the canonical database only through Alembic. Configuration fails closed: an unknown `MY_PA_` variable, an unparseable value, or a database URL that is not `postgresql+psycopg` naming a host and a database is rejected at startup. Implemented authentication and managed-document mechanisms do not authorize live credentials or storage. No source-system mutation, live connector or personal-data access, credential creation/disclosure/rotation, service activation, deployment, or production action is authorized by the current repository state; each requires separate operator authorization.
