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

This index records architecture direction only. Behavior now exists: the `my_pa` package, eleven Alembic revisions at head `1a4c9e77b2d5`, the migrated PostgreSQL corpus, a read-only fixture source provider, and PostgreSQL persistence for the source registry, enrollment, jobs, extraction, quarantine, coverage, lexical search, and — since WP-6 — the user-authored capture plane. Services now run too, which this sentence denied until WP-4B: `apps/gateway.py` serves the twelve capabilities over HTTP and MCP on loopback, `apps/gateway.py`'s CLI sibling invokes one, `apps/worker.py` claims and executes queued extraction work, and WP-4B3 composed the slice end to end from an operator registering a source to `knowledge.read`. These documents describe intended behavior and do not authorize implementation, database access, source access, deployment, or production activation.
