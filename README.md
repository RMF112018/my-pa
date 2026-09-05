# my-pa

`my-pa` is the clean implementation repository for a local-first personal knowledge layer that mediates access to authoritative NAS files, managed documents, personal-data connectors, knowledge records, relationship intelligence, and model-facing context.

## Operating lineage

The current remediation candidate is developed on
`bf/ri-remediation-20260829` from `main` base
`8d5e1d01b209eae1169c4f60c79c6c2c2dc89eb4`, which is `main`'s head and the merge
commit of PR #163. The exact candidate head belongs in the pull request and
remediation closeout rather than in this file, where every commit would
immediately stale it.

Corrected 2026-08-29. This section named `bf/pilot-blocker-remediation` from
authenticated `main` base `9b35476b70fe4fbc03bb8f9835d93c1b71089bbe` as the
**current** candidate, and had gone stale: that branch's last commit is
`11936dd` (2026-08-12), it merged as PR #73 on 2026-08-12, and it now sits 100
commits behind `main` (`git rev-list --left-right --count
origin/main...origin/bf/pilot-blocker-remediation` → `100 49`). It is retained
here, alongside the earlier `recovery/pre-20260805-utc-rollback-c9fb513`
lineage, as preserved campaign history; each is preserved and each is
no longer current-state authority. Its authority record remains
[`docs/campaign/PILOT-BLOCKER-REMEDIATION-20260812.md`](docs/campaign/PILOT-BLOCKER-REMEDIATION-20260812.md),
which keeps its name and content.

## Current state

The repository contains the Python package `my_pa` under `src/`, the Alembic
schema history for the canonical database, and a migrated PostgreSQL corpus in
that database. It is a local development candidate: the bounded source and
capture workflows run end to end over synthetic fixtures, but nothing here is
deployable.

Implemented, and covered by the FAST tier unless noted:

- `contracts/v1` — the public request and response envelope, disclosure, error, and capability shapes.
- `domain/identity` — capability, purpose, principal, and operation binding, including all one hundred and thirty capability names and their operator-only flags. WP-6 added four `capture.*` names and two capture purposes, WP-7 added `capture.search`, WP-8 added `review.list` and `review.decide` with `review_disposition`, WP-29 introduced the original read/write `relationship_memory.*` family with the `relationship_memory_read` and `relationship_memory_authoring` purposes, and Relationship Intelligence Phase B later added `relationship_memory.propose` with `relationship_memory_proposal`; none is operator-only because none grants external authority (`D-70`, `D-91`, `D-101`).
- `domain/common`, `domain/policy`, `domain/audit` — identifiers, provenance, classification, coverage state, time, policy decisions, and audit events.
- `domain/source` — the source registry, bounded enrollment with idempotency keys, and the read-only source-provider port.
- `domain/capture`, `domain/conversation` — the user-authored capture, immutable version, evidence-bound proposals and assertions, closed review policy, and explicit Conversation Log skeleton. Product-owned and append-only under [ADR-003](docs/decisions/ADR-003-product-owned-user-authored-source-records.md); none grants the source-provider port a write method or an external action.
- `domain/relationship` and the Relationship Intelligence application plane — governed person and organisation identity, unresolved mentions, reversible reviewed resolution, source-backed profiles, timelines, and conversation participants over synthetic personal-source fixtures. WP-9 itself added no public capability or live connector. The completed entity plane now has fifty-five `entities.*` capabilities: seventeen reads and thirty-eight writes. Phase A supplies canonical entity authoring and observation workflows; Phase B adds governed proposal staging and persisted operator-only merge preview/apply; final completion adds Principal-scoped identity history and operator-only split preview/apply. Entity and Relationship Memory candidates integrate with canonical `review.list`/`review.decide`. The plane remains off unless `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` is set, its writes remain separately off unless `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` is set, and remote merge or split additionally requires the server-resolved exact `remote.operator` durable capability set plus the ordinary capability, purpose, feature, and policy gates. [`ops/runbooks/relationship-intelligence.md`](ops/runbooks/relationship-intelligence.md) is the current operator document for this plane.
- The shared review surface contains two, `review.list`, `review.decide`, and neither grants identity-correction execution authority.
- `domain/extraction` — text and Markdown extraction outcomes, quarantine records, and coverage counts with stated limitations.
- `domain/search` — the lexical search query type.
- `bootstrap/settings` — strict `MY_PA_` configuration that fails closed on unknown or invalid values. `MY_PA_DATABASE_URL` is required and has no default.
- `infrastructure/database/engine` — the connection contract for the canonical database. Covered by the database tier only.
- `infrastructure/persistence` — source registry, enrollment, job lease and retry, extraction and quarantine, lexical search, the immutable capture/version/receipt plane, WP-7's evidence-bound proposal plane, and WP-8's review/promotion plane. Consequential proposals open review cases; accepting creates a canonical assertion plus policy receipt, rejection retains lineage, and a successor edit that changes a cited slice marks the assertion `revalidation_required`. Explicit Conversation Log creation and deterministic launch context are written in the capture save transaction; no external action client exists. **Capture search is a second full-text plane**, over `knowledge.capture_versions.content` with `simple` plus exact confirmation (`D-90`). Covered by the database tier.
- `infrastructure/providers/fixture.py` — a read-only fixture source provider that proves root containment, revalidates before read, and normalizes provider errors by errno.
- `application` — the one hundred and thirty capability use cases behind one entry point, one shared authorization and disclosure path, and the capability manifest and readiness report derived from that wiring rather than restated. It reaches persistence and providers only through the ports in `contracts/ports`. The set includes the task-management and commitment plane (`tasks.*`, `commitments.*`), the context-prepare plane (`context.prepare`, `context.feedback`), the GoodNotes semantic plane (`goodnotes.work`, `goodnotes.content`, `goodnotes.propose`), the connected synthetic GSQS B0 workflow (`gsqs.start`, `gsqs.status`), and the Intelligence Artifact report plane (`reports.begin_cycle`, `reports.commit`, `reports.record_run_state`, `reports.read`, `reports.latest`, `reports.list`, `reports.search`, `reports.resolve_set`), which is served by a default process rather than gated: unlike `documents.` and `entities.`, it needs nothing of the composition root that a default process withholds. The Relationship Memory plane (`relationship_memory.create`, `relationship_memory.get`, `relationship_memory.list`, `relationship_memory.search`, `relationship_memory.history`, `relationship_memory.revise`, `relationship_memory.archive`, `relationship_memory.restore`, `relationship_memory.propose`) is gated the other way and by two switches rather than one: it needs `MY_PA_RELATIONSHIP_MEMORY_ENABLED` *and* the entity plane, because a memory binds an Entity as its subject and ownership is proven by reading `knowledge.entities`.
- `adapters/http` and `apps/gateway.py run` — the HTTP transport and its composition root. All one hundred and thirty capabilities are routable at `POST /v1/<capability>` on `127.0.0.1`, and the response body is the envelope the application produced — but routable is not served: on a default process the six `documents.` names, the fifty-five `entities.` names and the nine `relationship_memory.` names answer `501 unsupported`, because `/v1/{capability}` is a path parameter and dispatch reaches the handler, which refuses. Corrected 2026-08-19 from "reachable", which read as available. Starlette and uvicorn, not FastAPI. In `local_operator` mode the process serves one configured Principal without a request credential; in `entra` mode it requires and validates a bearer token. There is no option to bind anywhere but loopback. [`ops/runbooks/gateway-operations.md`](ops/runbooks/gateway-operations.md) covers running it.
- `adapters/mcp` and `apps/gateway.py mcp` — the same one hundred and thirty capabilities over the Model Context Protocol, using the official `mcp` SDK. Local MCP uses stdio; the separately enabled persistent remote surface uses authenticated Streamable HTTP and remains off by default. A default-off compact ChatLLM publication profile may replace that per-capability `tools/list` for exact configured OAuth client IDs on the same `/mcp` resource (`MY_PA_MCP_CHATLLM_GATEWAY_ENABLED`, empty `MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS`); it does not add a second URL, audience, or grant vocabulary. Unselected clients keep the canonical catalog. The tool list is derived from `ApplicationService.available_capabilities` and each tool's schema from the command it builds, so nothing about a capability is written down twice. A default process publishes sixty tools and withholds the six `documents.` names, the fifty-five `entities.` names and the nine `relationship_memory.` names until their variables are set. The plane switch publishes its seventeen reads; the write switch admits ordinary entity writes; the identity-correction switch separately admits operator-only merge and split preview/apply. [`ops/runbooks/mcp-and-cli-operations.md`](ops/runbooks/mcp-and-cli-operations.md) states the transport contract. Local stdio opens no socket; the remote surface binds only when explicitly enabled and authenticates before server-resolved grants are used.
- `adapters/cli` and `apps/cli/invoke.py` — the operator CLI, which invokes one capability and writes the envelope to standard output. It is not a privileged bypass: it composes the same runtime the gateway composes, is handed the same principal, and has no option that could change one.
- `adapters/normalization.py` — the one place a request becomes a `(RequestMetadata, Command)` pair. All three transports call it and none of them can build either value, which is what makes `SPEC-AC-001` a structural property rather than three snapshots that agree today.
- `infrastructure/migration` — legacy extract and load, the migration control plane, and redaction.
- Ninety-three Alembic revisions cover the complete local-candidate schema; the chain has head `d4e8b1c7a902`, additive on `a4d8e31b2c90`, and adds the Principal-partitioned canvas workspace overlay; `a4d8e31b2c90` is additive on `6a2f9d1c4b80` and adds the immutable GoodNotes semantic promotion receipt; `6a2f9d1c4b80` is additive on `c3f8a1d07e94`, and adds five Principal-partitioned, content-free GoodNotes pull and semantic-review ledger tables; `c3f8a1d07e94` admits `entities.graph` on `b8e4d1a6c073` while admitting `goodnotes.pull`, `goodnotes.complete`, and `goodnotes.status` to the frozen audit vocabulary; `b8e4d1a6c073` is additive on `16f05c46b8c3` and backfilling one `display`-typed `entity_names` row per **active** `entities` row, taking `display_value` from `entities.display_name` and `normalized_value` from `entities.canonical_name` -- **never a `legal` name**, the conflation `ENTITY-SCHEMA-001` exists to refuse -- while writing no `entity_project_participations` row (no legacy row is directly representable, since `project_display_name` is `NOT NULL` and the legacy plane carries no project-facing name; `RULING-M10`), no `entity_addresses` and no `entity_communication_methods` row (no type may be inferred from string position), and leaving `entity_aliases`, `entity_assignments` and `entity_external_identifiers` untouched (RI-ENT-WP-12; written against `c99cd8ed8d1c` and re-parented onto `16f05c46b8c3` once RI-ENT-WP-10/11 merged, `RULING-M11`, so the chain holds one head; the count was taken from the merged tree on 2026-09-03 -- eighty-nine, one more than the eighty-eight `origin/main` held at `16f05c46b8c3` -- rather than by adding one to the eighty-seven this branch had measured against `c99cd8ed8d1c`, `RULING-M2`); `16f05c46b8c3` is additive on `2c00c9ac64bc` and widening three closed CHECK sets -- `audit_events.capability_is_known` from 115 to 135 values, `entity_mutation_events.a_mutated_record_family_is_known` from six to eleven, and `entity_proposals.an_accepted_proposal_record_family_is_known` from six to eleven for metadata parity with the shared `_one_of(..., MutationRecordFamily, ...)` declaration -- so the capability names RI-ENT-WP-10 and RI-ENT-WP-11 published, twenty in all, and their five new record families can be recorded at all; `purpose_is_known` is deliberately not widened, because neither work package adds a `Purpose` (corrected 2026-09-01 by UI-IMP-WP02 from eighty-six at `c99cd8ed8d1c` to eighty-seven at `2c00c9ac64bc`; corrected 2026-09-02 by RI-ENT-WP-10/11 from that same eighty-six to its own eighty-seven at `16f05c46b8c3`; neither figure is true of a tree carrying both revisions, so the base merge counted the merged chain and wrote eighty-eight rather than picking a side, and re-parented `16f05c46b8c3` -- written against `c99cd8ed8d1c`, as `2c00c9ac64bc` was -- onto `2c00c9ac64bc` so the pair is one linear chain with one head rather than two); `2c00c9ac64bc` is additive on `c99cd8ed8d1c` and adds WebAuthn credential, challenge, recovery-code, and opaque session tables (UI-IMP-WP02); `c99cd8ed8d1c` is additive on `1cda4d536268` and renames the seeded `entity_relationship_types` row `design_coordinates_with` to `design_coordination_with` -- every other column unchanged -- so `EntityRelationshipType` could admit it as `DESIGN_COORDINATION_WITH` without tripping `tests/architecture/test_relationship_scoring_surface_is_denied.py`'s "location tracking" pattern, closing the enum to 35-of-35 parity with the taxonomy table (the WP-08 blocker-clearing rename); `1cda4d536268` is additive on `9a3f6c1e8d24` and adding the `entity_assertions` and `entity_assertion_evidence` tables, binding fact-level `assertion_status` and evidence to the six Entity-bound record families RI-ENT-WP-02 through RI-ENT-WP-06 added (RI-ENT-WP-07, closes `ENTITY-PROVENANCE-001`); `9a3f6c1e8d24` is additive on `8dc3619891bb` and widening the `entity_identity_effects`/`entity_identity_preview_ambiguities`/`entity_identity_ambiguity_settlements` `record_family` CHECKs to admit six new families -- `name`, `organization_profile`, `address`, `communication_method`, `project_participation`, `person_organization_affiliation` (RI-ENT-WP-06b); `8dc3619891bb` is additive on `17149a48fa30` and adding the `entity_relationship_types` table while re-pointing `entity_relationships.relationship_type` at it by foreign key in place of the frozen CHECK `9def3c2e63bb` installed (RI-ENT-WP-06a, closes `ENTITY-REL-001`); `17149a48fa30` is additive on `f5b06925857e` and adds the `entity_person_organization_affiliations` table (RI-ENT-WP-05); `f5b06925857e` is additive on `441b071bf37b` and adds the `entity_project_participations`, `entity_role_types`, and `entity_discipline_types` tables (RI-ENT-WP-04); `441b071bf37b` is additive on `7e114f822af2` and adds the `entity_addresses` and `entity_communication_methods` tables (RI-ENT-WP-03); `7e114f822af2` is additive on `b727e870d45e` and adds the `entity_names` and `entity_organization_profiles` tables (RI-ENT-WP-02); `c4b0a1d9e827` admits the GSQS B0 capabilities immediately before Phase B continues at `c7a1f04b9e63`. The chain includes the DDL-free native-baseline/managed-document merge, the merge of task-management `7504585e3ca5` with context-prepare `c6f1a8d3e204`, the additive `tasks.description` column with `pulse_items.priority` → `attention_rank` rename, additive OAuth refresh-token families, additive GoodNotes notebook lineage, logical pages, and run ledger, additive GoodNotes NOTE_UNIT occurrence, revision, link, and run-change persistence, additive GoodNotes semantic work/proposal capabilities with an insert-only proposal receipt table, additive GoodNotes entity associations with NEW-only delivery receipts, and additive GoodNotes exact visual render digests, additive `goodnotes.content` vocabulary, additive durable-note stage ledger and Principal-bound page rasters, additive GoodNotes server-grounded NOTE_UNIT crop identity with immutable revision provenance, additive GoodNotes Meeting/Agenda association kinds with NOTE_UNIT-scoped `note-unit.v2` semantics, and an additive dormant GoodNotes delivery-attempt ledger, and the relationship-intelligence entity tables `entities`, `entity_external_identifiers`, `entity_assignments`, and `entity_relationships`, the additive `entity_aliases` table (`b7f4d1a92c36`), and the admission of the `entities.*` capability family (`entities.search`, `entities.get`, `entities.resolve`, `entities.context`, `entities.relationships`) and the `entity_read` purpose to the `audit_events` closed sets (`c1a7e4b93d58`), and the entity observation, proposal, and merge-lineage tables `entity_observations`, `entity_proposals`, and `entity_merge_records` (`d2b8f5c04e71`), which add no capability and no purpose, and the admission of `entities.unresolved_mentions` to the same closed set (`e4d7b2f9a316`), which adds no table, and the additive nullable `entity_observations.mention_display_name` that the unresolved-mention queue reads in place of the matched form (`f3a8c1d7e592`), which adds no capability, and the Intelligence Artifact plane's cycle-run, producer-run, immutable-artifact, commit-receipt, pipeline-dependency and external-provenance tables with the eight `reports.*` capabilities and the `report_authoring`/`report_read` purposes (`e9b2c4d7a150`), and the Work Task/Commitment contract, history digests, and bounded bulk ledger, with `commitments.history`, `commitments.search` and `commitments.update` admitted to the `audit_events` capability set (`a4d9e7c2b615`), and the Relationship Memory plane's `relationship_memories`, `relationship_memory_versions`, `relationship_memory_submissions`, `relationship_memory_context_links`, `relationship_memory_evidence_links`, `relationship_memory_proposals`, `relationship_memory_proposal_evidence` and `relationship_memory_review_decisions` tables, with two `BEFORE UPDATE OR DELETE` triggers making the version and decision ledgers append-only, and the admission of the original read/write `relationship_memory.*` family plus the `relationship_memory_read`/`relationship_memory_authoring` purposes to the `audit_events` closed sets in the same revision (`f1c6b904a2d7`), which travel together because this is the first revision in the chain that knows the word. Phase B later admits `relationship_memory.propose` and `relationship_memory_proposal` in `b64e29a0f7c1`. The corrective revision `b727e870d45e` is additive on `8e1c4a7b2d90` and adds the merge-preview ambiguity and ambiguity-settlement tables, the `partial` re-enrichment state with the `limitations` column that explains it, the `reenrichment` worker-heartbeat plane, and a `BEFORE UPDATE OR DELETE` trigger making `knowledge.entity_proposal_review_decisions` append-only. Applied and rolled back in the database tier; SQL generation is checked by FAST. **No revision derives a closed-set constraint from a domain enum** (`D-69`): historical vocabulary is frozen in each emitting revision and widened by an explicit `ALTER` in the revision that widens it.
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

Accordingly, in a fully composed process — one given
`MY_PA_MANAGED_DOCUMENT_ROOT`, `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`,
`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED`,
`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED` and
`MY_PA_RELATIONSHIP_MEMORY_ENABLED` —
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
true only of a process given all required composition gates. None is set by default
(`managed_document_root` defaults to `""`, and `relationship_intelligence_enabled`
and `relationship_memory_enabled` to `False`, in `bootstrap/settings.py`), so a
default process publishes a manifest
in which 60 of the 130 capabilities are `available` and 70 — the six `documents.`
names, the fifty-five `entities.` names, and the nine `relationship_memory.` names — are
`not_implemented`, and readiness is `degraded` with the limitation
`70 of 130 capabilities are unwired.` Derived by building the manifest both ways
from the dispatch table, exactly as `_capabilities_get` does:
`build_capability_manifest(implemented=frozenset(_HANDLERS) - _ENTITY_CAPABILITIES
- _MANAGED_CAPABILITIES - _RELATIONSHIP_MEMORY_CAPABILITIES, limits=...)`.
`test_readme_state_claims.py` holds the fully composed and default-composition
figures in these paragraphs to the dispatch table and its three explicitly
withheld families.

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

Start with [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md). The operating lineage is the "Operating lineage" section above. The current Relationship Intelligence campaign state — work-package disposition, capability/acceptance traceability, and validation record — is [`docs/testing/relationship-intelligence-final-completion.md`](docs/testing/relationship-intelligence-final-completion.md), and the plan it executes is [`docs/plans/relationship-intelligence-implementation-plan.md`](docs/plans/relationship-intelligence-implementation-plan.md).

Corrected 2026-08-29: this line routed "the active campaign state" to [`docs/campaign/CAMPAIGN-BRIEF.md`](docs/campaign/CAMPAIGN-BRIEF.md), which [`docs/00_REPOSITORY_SOURCE_INDEX.md`](docs/00_REPOSITORY_SOURCE_INDEX.md) declares "historical/superseded … not authority for present campaign state, work selection, or repository lineage". Two documents cannot both be right about that file; the index was, and the brief is retained as history rather than routed to as current.

## Boundaries

Original source systems remain authoritative and read-only by default. Managed output storage is a separate capability. PostgreSQL is the canonical metadata and knowledge store. Obsidian is a rebuildable projection, not the authority.

Schema changes reach the canonical database only through Alembic. Configuration fails closed: an unknown `MY_PA_` variable, an unparseable value, or a database URL that is not `postgresql+psycopg` naming a host and a database is rejected at startup. Implemented authentication and managed-document mechanisms do not authorize live credentials or storage. No source-system mutation, live connector or personal-data access, credential creation/disclosure/rotation, service activation, deployment, or production action is authorized by the current repository state; each requires separate operator authorization.
