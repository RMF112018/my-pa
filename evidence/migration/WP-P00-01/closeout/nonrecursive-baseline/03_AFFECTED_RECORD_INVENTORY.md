# Affected Record Inventory

| Path | Defect before correction | Correction applied |
|---|---|---|
| `docs/migration/governance/goal-state.json` | `current_baseline` embedded `3e5aad7b…` as continuously current | Replaced with `repository_identity_resolution` (`RUNTIME_GIT`) + historical `record_base` |
| `docs/migration/00_MIGRATION_INDEX.md` | “Current merged baseline” + instruction to bind embedded SHA | Runtime-resolution statement; historical roles labelled |
| `docs/migration/governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md` | “Current merged baseline” / “current baseline” rows | Runtime Git authority; non-recursion rule; historical roles |
| `docs/migration/governance/authorization-ledger.json` | Top-level invalidation tied to live movement from `3e5aad7b…` | Runtime-resolution invalidation; new correction auth recorded as `ACTIVE_UNCONSUMED` |

## Explicitly unchanged (authorized exclusion)

| Path | Reason |
|---|---|
| `docs/migration/governance/work-item-ledger.json` | Not in authorized path set |
| `docs/migration/governance/exact-identity.json` | Historical WP-P00-01 identity record; must not be rewritten as current |
| `docs/00_REPOSITORY_SOURCE_INDEX.md` | Not in authorized path set |
