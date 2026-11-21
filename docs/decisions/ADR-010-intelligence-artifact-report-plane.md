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
- **Kind-scoped heads.** Heads and lineage are keyed by (Principal, cycle, stage, artifact kind, focus area, source lane): `a591b81f10a2` recreates the `intelligence_artifact_current_head` unique index with `artifact_kind` after `stage`, and every head lookup, supersede and `succeeded` run-state check uses the committed kind. Each kind has its own lineage, so a client kind at a built-in stage never supersedes, displaces or is superseded by the built-in report at that stage. `reports.latest` without an `artifact_kind` considers the five built-in kinds only, in every selection (no stage, a stage only, a focus area only, or any combination; operator ruling N1): with a `stage` it returns the built-in kind of that stage, as it did before the registry, and without one the newest built-in head. A client kind is returned only when the call names it, while `reports.list` and `reports.search` without a kind may return client kinds.
- **Stage rules, built-in upstreams.** A client kind at a stage takes exactly the built-in kind's dependency rules for that stage: the same upstream stage and dependency count, and the same never-falsely-final rule. A client kind at `morning_brief` names zero to six built-in Reporter heads exactly as the Daily Briefing does; any partial or uncovered expected focus area forces `partial`, and a `final` claim is refused with `artifact_state`.
- **Built-in-only consumption; client kinds are standalone.** The Daily Briefing and every resolver set (`collectors`, `research_swarm`, `synthesizer_inputs`, `reporter_input`, `morning_brief_inputs`) consume only built-in kinds: eligibility, failed-run and stale-upstream checks look up the built-in kind of the upstream stage. A dependency cited by any commit, built-in or client kind, must be the built-in kind of its stage; a client-kind artifact cited as a dependency is refused with the bare `dependency_report_ids` refusal. Nothing consumes a client kind.
- **No retirement.** The registry is insert-only and there is no retirement capability. Committed artifacts keep their kind, and retiring a kind would orphan them or force a rewrite of immutable rows; a retirement can be added later as its own decision.
- **Cap.** A Principal holds at most 64 client kinds, which also bounds every refusal that lists them. A new kind beyond the cap is a `conflict` on `artifact_kind` with `max_items`. Registration takes a per-Principal transaction-scoped advisory lock before it looks up, counts and inserts, so concurrent registrations cannot exceed the cap.
- **Idempotent replay.** Registering an identical definition again succeeds with `replayed: true` and writes nothing, without an idempotency key, including at the cap. A different definition for a registered kind, or a built-in kind, is a `conflict` on `artifact_kind`; nothing is rewritten.
- **Principal isolation.** Registrations, listings and the kinds a refusal lists are the acting Principal's own. Another Principal's kind is indistinguishable from an unregistered one and never appears in a response.
- **Migration.** `a591b81f10a2` downgrade refuses with `restrict_violation`, deleting nothing, while any client registry row, any run or artifact of a non-built-in kind, or any audit row naming `reports.types.create` or `reports.types.list` exists. Otherwise it restores the original CHECKs and the original current-head index byte for byte (with only built-in kinds left, stage and kind are one to one, so the narrower key holds every head) and drops the table.
- **Open risk (recorded, not fixed here).** A commit validates (registered kind, dependencies, heads) and then writes, and the two are not one serialized step: state read during validation can change before the write lands. This validate-then-commit race is an open risk, not addressed by this amendment.

## Amendment (2026-11-20): the daily cycle scheduler, cycle closing, and one open cycle per date

Operator decision of 2026-11-20. Decision 5 stands: the `cycle_run_id` is still the identity and a business date is still metadata. What changes is that the backend, not ChatLLM, now opens and closes the daily Morning Intelligence cycle, and that `reports.begin_cycle` converges on an already open cycle for the same date. This section is the contract for that change.

- **Scheduler.** A worker plane, `apps/worker.py run --plane cycles`, runs once a day at 00:00 in `MY_PA_CYCLE_SCHEDULER_TIMEZONE` (default `America/New_York`, an IANA name resolved with `zoneinfo`). The run time is fixed at local midnight and is not configurable. The plane refuses to start (exit 2, before an engine is built) unless `MY_PA_CYCLE_SCHEDULER_ENABLED` is on (default off). One run, for business date *D* (the local calendar date when the run starts), closes stale cycles and then begins *D*'s cycle.
- **Due rule.** A run is due when the local date is later than the date of the last run that completed its begin step in this process. A process that starts runs at once for the current local date. That is the catch-up rule: a missed midnight is made up once, for the latest missed date only, and never backfilled day by day. Date arithmetic is on the local calendar, so the run neither repeats nor skips across a DST change.
- **Single flight.** A run holds a PostgreSQL session advisory lock for its whole duration. A second worker that cannot take the lock skips that attempt and tries again on its next poll. Every step is idempotent, so a repeated run for the same date writes nothing new.
- **Close step.** Every `open` or `running` `morning_intelligence` cycle of the operator Principal whose `business_date` is before *D* is closed. A cycle with at least one committed artifact (any kind, any `artifact_state`, superseded or not) becomes `complete`; a cycle with none becomes `cancelled`. Closing sets `finished_at`, increments `version`, and is a compare-and-set on the version read under an exclusive row lock, only from `open` or `running`. A cycle that is already `complete`, `failed` or `cancelled` is left unchanged, so closing is idempotent. Cycles dated *D* or later are never closed. Each cycle closes in its own transaction. A failure is logged and the cycle is retried on the next run.
- **Begin step.** The scheduler calls `reports.begin_cycle` through `ApplicationService.invoke`, the same authorize-and-audit path as every local caller: the operator Principal, purpose `report_authoring`, local transport, and no client grant set. It uses `cycle_id` `morning_intelligence`, `business_date` *D*, `automation_platform` `my_pa_scheduler`, and the deterministic idempotency key `auto-morning_intelligence-<YYYY-MM-DD>`. The begin step always runs, even when the close step failed. A failed begin is retried on the next poll.
- **Acting Principal and audit.** The scheduler acts as the fixed local operator Principal (ADR-013). Every remote OAuth client row is constrained to that Principal, so its cycles are ChatLLM's cycles. It holds no OAuth client and no grant, and no capability name is added. The begin call is audited in `knowledge.audit_events` like any other `reports.begin_cycle`. The close transition has no capability and writes no audit row. It is an internal lifecycle transition, like the worker planes' job state. Its durable record is the cycle row (`state`, `finished_at`, `version`) and the run's structured log line.
- **One open cycle per date (`reports.begin_cycle`).** The idempotency key is still resolved first, so a stored key replays its own cycle and a different fingerprint under the same key is still `conflict` on `idempotency_key`. The external-root uniqueness `conflict` on `cycle_run_id` also still applies. After those checks, and under a transaction-scoped advisory lock on (Principal, `cycle_id`, `business_date`), an existing `open` or `running` cycle for the same Principal, `cycle_id` and `business_date` is returned instead of creating a second one. If more than one exists (a pre-amendment leftover), the newest is returned. The response has the same schema with `created: false` and `replayed: true`. The new key's receipt is stored against that cycle, so the key keeps replaying it. The existing cycle's `automation_platform` and external root are not rebound. A new cycle is created only when no open or running cycle exists for that date, so a new attempt on a date needs the earlier attempt closed first. This is how the scheduler and a ChatLLM fallback converge on one cycle in either order. ChatLLM may keep calling `reports.begin_cycle` and needs no change.
- **Late writes to a closed cycle.** Before this amendment, `reports.commit` and `reports.record_run_state` checked only that the cycle existed and accepted writes to a cycle in any state. Now a new write to a `complete`, `failed` or `cancelled` cycle is refused `conflict` with the details `cycle_run_id` and `cycle_closed`, and nothing is written. A stored idempotency key still replays first. To serialize writes against a close, a write takes a share lock on its cycle row before checking the state, and a close takes the exclusive row lock before counting artifacts. A commit racing a close therefore either lands first and counts toward `complete`, or is refused.
- **`cycle_id` refusal.** An unknown `cycle_id` on `reports.begin_cycle` is now `invalid_request` with the detail `cycle_id`. It was `stage`, which named the wrong field.
- **No migration.** The `state`, `version` and `finished_at` columns and the state CHECK already admit every value written here. Two closed `SafeDetail` tokens are added: `cycle_id` and `cycle_closed`. No capability, purpose, grant or ChatLLM profile changes.
- **Not done here.** Nothing writes `running` or `failed`. A cycle is not closed on the same day it began. Days a stopped scheduler missed are not backfilled.
