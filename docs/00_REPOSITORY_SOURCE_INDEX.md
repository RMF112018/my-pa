# Repository Source Index

**Repository:** `RMF112018/my-pa`  
**Architecture basis:** `REQ-PKL-MYPA-REPO-ARCHITECTURE-20260730-001`  
**Bootstrap goal:** `GOAL-MYPA-PKL-G00-REPOSITORY-BOOTSTRAP`  
**Status:** `SCAFFOLD_ONLY`

## Required entry sequence

1. [`../AGENTS.md`](../AGENTS.md)
2. [`../AI_OPERATING_MANUAL.md`](../AI_OPERATING_MANUAL.md)
3. this index
4. the nearest owning README or index

## Root controls

| File | Role |
|---|---|
| `README.md` | Product and current-state overview |
| `AGENTS.md` | Repository authority, boundaries, stops, and naming |
| `AI_OPERATING_MANUAL.md` | Model-assisted delivery workflow |
| `CLAUDE.md` | Thin agent-harness entry point |
| `SECURITY.md` | Security and sensitive-data boundary |
| `CONTRIBUTING.md` | Contribution prerequisites |

## Architecture and decisions

- [`architecture/00_ARCHITECTURE_INDEX.md`](architecture/00_ARCHITECTURE_INDEX.md)
- [`decisions/00_ADR_INDEX.md`](decisions/00_ADR_INDEX.md)

## Major repository areas

| Path | Responsibility |
|---|---|
| `apps/` | Gateway, worker, and CLI process boundaries |
| `src/my_pa/contracts/` | Versioned contracts |
| `src/my_pa/domain/` | Provider-independent domain model |
| `src/my_pa/application/` | Use cases and orchestration |
| `src/my_pa/infrastructure/` | Concrete adapters |
| `src/my_pa/bootstrap/` | Composition roots |
| `migrations/` | PostgreSQL schema evolution |
| `schemas/` | Machine-readable contracts |
| `tests/` | Verification suites |
| `fixtures/` | Synthetic test data |
| `.ai/` | Machine-oriented governance and goal routing |
| `ops/` | Inactive operational assets |
| `scripts/` | Developer/operator automation |
| `evidence/` | Durable verification summaries |

## Current authorization boundary

Only documentation scaffolding is present. No runtime implementation, database access, migration, source access, managed-document write, connector access, schedule, deployment, or production activation is implied.
