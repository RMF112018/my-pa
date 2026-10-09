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
- `reporter_input` keeps its single member required, but a PARTIAL synthesizer is eligible, so its aggregate is DEGRADED rather than BLOCKED. `collectors` and `morning_brief_inputs` keep the legacy blocking behaviour with every member required. No migration and no new persisted value.
