# Architecture Index

## Accepted foundation

- Modular monolith in one repository
- Separate gateway and worker processes
- Operator CLI as a third entry surface
- Inward dependency direction: apps/bootstrap → infrastructure/application → domain/contracts
- PostgreSQL as planned canonical metadata and knowledge store
- Source providers separated from managed-document stores
- Progressive, reference-driven indexing
- Obsidian as a rebuildable projection
- Neutral `my_pa` / `MY_PA_` naming

## Planned architecture documents

| Document | Status |
|---|---|
| `system-context.md` | Planned |
| `module-boundaries.md` | Planned |
| `data-authority.md` | Planned |
| `threat-model.md` | Planned |

## Decision records

See [`../decisions/00_ADR_INDEX.md`](../decisions/00_ADR_INDEX.md).

## Implementation boundary

This index records architecture direction only. The scaffold contains no executable services or persistence behavior.
