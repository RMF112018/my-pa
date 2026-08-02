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
| [`system-context.md`](system-context.md) | Present — proposed for repository review |
| [`module-boundaries.md`](module-boundaries.md) | Present — proposed for repository review |
| [`data-authority.md`](data-authority.md) | Present — proposed for repository review |
| [`../security/threat-model.md`](../security/threat-model.md) | Present — proposed for repository review |
| [`../decisions/ADR-003-product-owned-user-authored-source-records.md`](../decisions/ADR-003-product-owned-user-authored-source-records.md) | Accepted — the third authority class |

## Specification

The read-only Minimum Viable Candidate (MCV) contract is [`../specs/mcv-read-only-vertical-slice.md`](../specs/mcv-read-only-vertical-slice.md).

## Decision records

See [`../decisions/00_ADR_INDEX.md`](../decisions/00_ADR_INDEX.md) and the unresolved items in [`../../PHASE-00-OPEN-DECISION-LEDGER.md`](../../PHASE-00-OPEN-DECISION-LEDGER.md).

## Implementation boundary

This index records architecture direction only. Behavior now exists: the `my_pa` package, eight Alembic revisions at head `8b3f5c17d904`, the migrated PostgreSQL corpus, a read-only fixture source provider, and PostgreSQL persistence for the source registry, enrollment, jobs, extraction, quarantine, coverage, and lexical search. No service runs — there is no gateway, worker, or transport, and nothing composes a capability end to end. These documents describe intended behavior and do not authorize implementation, database access, source access, deployment, or production activation.
