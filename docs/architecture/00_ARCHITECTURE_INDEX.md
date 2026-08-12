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

## Specification

The read-only Minimum Viable Candidate (MCV) contract is [`../specs/mcv-read-only-vertical-slice.md`](../specs/mcv-read-only-vertical-slice.md).

## Decision records

See [`../decisions/00_ADR_INDEX.md`](../decisions/00_ADR_INDEX.md) and the unresolved items in [`../../PHASE-00-OPEN-DECISION-LEDGER.md`](../../PHASE-00-OPEN-DECISION-LEDGER.md).

## Implementation boundary

This index records architecture direction and current composition. The `my_pa`
package exposes twenty-six shared application capabilities through the HTTP,
MCP, and operator-CLI adapters; the gateway and worker composition roots use the
same PostgreSQL-backed policy and application seams. Alembic owns thirty-four
revisions at head `b4e8d2c7a613`. The current candidate also includes the
MossAIc web BFF/PWA, managed documents, GoodNotes, the bounded model gate,
Frontier MCP, and the Apple source host. These documents describe the resulting
implementation; they do not authorize live source/database access, deployment,
production activation, or risk acceptance.
