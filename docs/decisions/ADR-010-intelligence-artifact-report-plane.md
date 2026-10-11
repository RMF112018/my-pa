# ADR-010: Intelligence Artifact / Report plane

- **Status:** Accepted
- **Decision ID:** `MYPA-RPT-D-010`
- **Repository:** `RMF112018/my-pa`
- **Repository identity:** `main@edc074e37d023d3d006903d7e6accd7c87b61683`
- **Scope:** Product-owned synthesized intelligence artifacts, cycle identity, and pipeline lineage. No live Abacus, OneDrive, production, or merge authority.

## Context

Morning Intelligence produces durable intermediate artifacts, not only a final Brief: six Collectors, thirty Researchers, six Synthesizers, six Reporters, and one Morning Brief. ADR-003 already names product-owned *user-authored* records. These artifacts are product-owned *synthesized* Markdown with exact pipeline lineage. They are not Captures, not managed documents, and not extraction-plane knowledge.

## Decision

1. Own the plane as the smallest coherent Intelligence Artifact / Report capability inside the modular monolith and the canonical `ApplicationService`.
2. Persist in PostgreSQL: UTF-8 Markdown `TEXT`, typed columns for stable semantics, bounded schema-versioned JSONB only where structure is variable.
3. Separate mutable producer-run state from immutable committed artifact body/digest. Corrections append successor versions.
4. Keep pipeline dependency lineage and external source provenance as distinct relations.
5. Bind every attempt to a server-issued `cycle_run_id`. A business date is metadata, not identity.
6. Keep the cycle definition (focus areas, source lanes, stage graph, required membership) in a code-controlled catalog in v1.
7. Expose `reports.*` capabilities through the same application service MCP and a future BFF will call. Principal is authenticated context. Production grants stay off.

## Consequences

- Eight public capabilities and two purposes (`report_authoring`, `report_read`) join the audited vocabulary.
- Additive Alembic revision `e9b2c4d7a150` creates the six Intelligence tables.
- Live OneDrive cutover, dual-write, enterprise-content eligibility, and unattended Abacus refresh remain operator-gated.

## Supersession

Does not supersede ADR-003. Synthesized intelligence artifacts are a fourth authority class beside original sources, managed documents, and user-authored captures.

## Amendment (2026-10-09): Synthesizer lane membership and partial lineage

Decision 6 stands: the catalog stays in code. Its membership policy changes for the researcher-to-reporter path only.

- A Synthesizer names one or more Researcher heads of its own cycle and focus area, at most one per source lane. The source-lane vocabulary is unchanged. Which lanes a focus area runs is an operator decision; an absent lane is not an error.
- `research_swarm` and `synthesizer_inputs` list every lane with `required: false`. One shared eligibility predicate decides both these resolver sets and Synthesizer/Reporter commit acceptance, so the resolver's eligible members are exactly what a commit accepts.
- A Synthesizer or Reporter over any partial input must itself be committed as `partial`.
- `reports.record_run_state` refuses `succeeded` when the coordinate has no current artifact head.
- Dependency refusals carry `dependency_report_ids` plus a reason token from the closed `SafeDetail` set.
- `reporter_input` keeps its single member required, but a PARTIAL synthesizer is eligible, so its aggregate is DEGRADED rather than BLOCKED. `collectors` keeps the legacy blocking behaviour with every member required. (`morning_brief_inputs` originally kept it too; superseded by the amendment below.) No migration and no new persisted value.

## Amendment (2026-10-11): the Daily Briefing is never blocked

Decision 6 still stands. The Morning Brief and `morning_brief_inputs` move onto the shared eligibility predicate.

- A Morning Brief names zero or more Reporter heads of its own cycle, at most one per expected focus area, each eligible (`READY` or `PARTIAL`) under the shared predicate. A missing or partial Reporter never blocks the brief.
- A brief with any partial Reporter input or any uncovered expected focus area must be committed as `partial`; a `final` claim is refused with `artifact_state`. It is never downgraded silently.
- A superseded, non-head or lineage-stale Reporter, another cycle's Reporter, another Principal's id, a non-Reporter, a duplicate focus area and an admitted-but-not-expected focus area stay refused exactly as before.
- `morning_brief_inputs` lists every expected focus area with `required: false` and is never `BLOCKED`: `READY` when every area's Reporter is eligible and final, `DEGRADED` otherwise. Every `reports.resolve_set` result carries `missing_focus_areas` and `partial_focus_areas` (sorted focus-area ids; empty for every other set). One gap rule computes them for both the resolver and the brief commit.
- No migration and no new persisted value.

## Amendment (2026-10-11): the per-Principal report type registry

Decision 6 still stands for the stage graph: the five stages, the built-in kind of each stage, the focus areas and the source lanes stay in the code-controlled catalog. What a Principal may add is its own report *kinds*.

- **Registry.** `reports.types.create` registers a client kind (a lower_snake token of 1 to 64 characters that is not a built-in kind) at one of the five stages, with a description and an optional display name. `reports.types.list` returns the built-in kinds, authoritative in code, merged with the acting Principal's own client kinds, each with its `origin` (`builtin` or `client`). Every report capability that takes `artifact_kind` accepts any kind registered for the acting Principal at the right stage; an unregistered or misplaced kind is refused with the Principal's own registered kinds listed. Revision `a591b81f10a2` adds `knowledge.intelligence_report_types` (append-only, one row per Principal and kind) and relaxes the plane's kind CHECKs to a kind token while keeping every built-in kind bound to its own stage.
- **Kind-scoped heads.** Heads and lineage are keyed by (Principal, cycle, stage, artifact kind, focus area, source lane): `a591b81f10a2` recreates the `intelligence_artifact_current_head` unique index with `artifact_kind` after `stage`, and every head lookup, supersede and `succeeded` run-state check uses the committed kind. Each kind has its own lineage, so a client kind at a built-in stage never supersedes, displaces or is superseded by the built-in report at that stage.
- **Stage rules, built-in upstreams.** A client kind at a stage takes exactly the built-in kind's dependency rules for that stage: the same upstream stage and dependency count, and the same never-falsely-final rule. A client kind at `morning_brief` names zero to six built-in Reporter heads exactly as the Daily Briefing does; any partial or uncovered expected focus area forces `partial`, and a `final` claim is refused with `artifact_state`.
- **Built-in-only consumption; client kinds are standalone.** The Daily Briefing and every resolver set (`collectors`, `research_swarm`, `synthesizer_inputs`, `reporter_input`, `morning_brief_inputs`) consume only built-in kinds: eligibility, failed-run and stale-upstream checks look up the built-in kind of the upstream stage. A dependency cited by any commit, built-in or client kind, must be the built-in kind of its stage; a client-kind artifact cited as a dependency is refused with the bare `dependency_report_ids` refusal. Nothing consumes a client kind.
- **No retirement.** The registry is insert-only and there is no retirement capability. Committed artifacts keep their kind, and retiring a kind would orphan them or force a rewrite of immutable rows; a retirement can be added later as its own decision.
- **Cap.** A Principal holds at most 64 client kinds, which also bounds every refusal that lists them. A new kind beyond the cap is a `conflict` on `artifact_kind` with `max_items`. Registration takes a per-Principal transaction-scoped advisory lock before it looks up, counts and inserts, so concurrent registrations cannot exceed the cap.
- **Idempotent replay.** Registering an identical definition again succeeds with `replayed: true` and writes nothing, without an idempotency key, including at the cap. A different definition for a registered kind, or a built-in kind, is a `conflict` on `artifact_kind`; nothing is rewritten.
- **Principal isolation.** Registrations, listings and the kinds a refusal lists are the acting Principal's own. Another Principal's kind is indistinguishable from an unregistered one and never appears in a response.
- **Migration.** `a591b81f10a2` downgrade refuses with `restrict_violation`, deleting nothing, while any client registry row, any run or artifact of a non-built-in kind, or any audit row naming `reports.types.create` or `reports.types.list` exists. Otherwise it restores the original CHECKs and the original current-head index byte for byte (with only built-in kinds left, stage and kind are one to one, so the narrower key holds every head) and drops the table.
- **Open risk (recorded, not fixed here).** A commit validates (registered kind, dependencies, heads) and then writes, and the two are not one serialized step: state read during validation can change before the write lands. This validate-then-commit race is an open risk, not addressed by this amendment.
