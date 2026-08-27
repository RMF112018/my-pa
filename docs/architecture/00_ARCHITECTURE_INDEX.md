# Architecture Index

## Accepted foundation

- Modular monolith in one repository
- Separate gateway and worker processes
- Operator CLI as a third entry surface
- Inward dependency direction: apps/bootstrap → infrastructure/application → domain/contracts
- PostgreSQL as the canonical metadata and knowledge store
- Source providers separated from managed-document stores
- Progressive, reference-driven indexing
- Obsidian as a rebuildable projection
- Neutral `my_pa` / `MY_PA_` naming

## Architecture documents

| Document | Status |
|---|---|
| [`system-context.md`](system-context.md) | Current repository architecture |
| [`module-boundaries.md`](module-boundaries.md) | Present — proposed for repository review |
| [`data-authority.md`](data-authority.md) | Present — proposed for repository review |
| [`../security/threat-model.md`](../security/threat-model.md) | Present — proposed for repository review |
| [`../decisions/ADR-003-product-owned-user-authored-source-records.md`](../decisions/ADR-003-product-owned-user-authored-source-records.md) | Accepted — the third authority class |
| [`../decisions/ADR-008-nas-runtime-topology.md`](../decisions/ADR-008-nas-runtime-topology.md) | Accepted — staged NAS target topology; not deployed |
| [`../decisions/ADR-009-oauth-refresh-token-families.md`](../decisions/ADR-009-oauth-refresh-token-families.md) | Accepted — rotating refresh tokens for remote MCP |

## Specification

The read-only Minimum Viable Candidate (MCV) contract is [`../specs/mcv-read-only-vertical-slice.md`](../specs/mcv-read-only-vertical-slice.md).

## Decision records

See [`../decisions/00_ADR_INDEX.md`](../decisions/00_ADR_INDEX.md) and the unresolved items in [`../../PHASE-00-OPEN-DECISION-LEDGER.md`](../../PHASE-00-OPEN-DECISION-LEDGER.md).

## Implementation boundary

This index records architecture direction and current composition. The `my_pa`
package defines one hundred and two capabilities and exposes them through the HTTP,
MCP, and operator-CLI adapters; a default composition serves fifty-six of
them, because the `documents.`, `entities.` and `relationship_memory.` families
each require an environment variable that has no default. The gateway and worker
composition roots use the same PostgreSQL-backed policy and application seams.
Alembic owns seventy-seven revisions at head `d8f3a1c6e942`; the chain admits `gsqs.start`/`gsqs.status` at `c4b0a1d9e827` immediately before Phase B continues at `c7a1f04b9e63`, then `gsqs.step` at `d8f3a1c6e942` after Phase B's `3d07af4dc513`. The current candidate
also includes the MossAIc web BFF/PWA, managed documents, GoodNotes, the bounded
model gate, Frontier MCP, and the Apple source host. These documents describe the
resulting implementation and the accepted, inactive NAS target. They do not
authorize live source/database access, deployment, production activation, or
risk acceptance.

Corrected 2026-08-23: the paragraph above claimed 30 capabilities and 34
revisions at head `b4e8d2c7a613`. That pair was self-consistent when it was
written — `b4e8d2c7a613` is still in this chain and is still its 34th revision —
and further revisions have landed on top of it since, with current head `d8f3a1c6e942`. The
current figures were already stated in [`system-context.md`](system-context.md)
beside it, which has been kept current through those work packages while this
index was not, and that is how a figure like this survives: the sibling is the
document that gets read, and the index is the document that gets cited. Neither
number is counted by hand: the capability figure is `len(Capability)` and the
revision figure is the file count of `migrations/versions/`. The capability one
is now bound as well as correct — the old wording, `thirty shared application
capabilities`, slipped past
`tests/architecture/test_spelled_counts_match_the_sets_they_name.py` because
that rule admits only a fixed list of adjectives between the number and the
noun, and `shared application` is not on it, so the sentence carrying the stale
figure was the one sentence in the file the sweep could not read. The wording
above puts the noun where the rule can see it: planting `seventy-two` there
reddens that guard.
