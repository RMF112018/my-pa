# Migration Index

**Status:** `MIGRATION_COMPLETE_LEGACY_RETAINED`
**Goal:** `GOAL-MYPA-POSTGRESQL-MIGRATION-001`
**Repository:** `RMF112018/my-pa`

The legacy SQLite corpus has been migrated into PostgreSQL. `my_pa` is the
canonical store for this repository; the legacy source is retained indefinitely
as a read-only archive and is never mutated. Work from Phase 01 onward proceeded
under the campaign decision register recorded by the repository owner (decision
`OD-005`) and under `AGENTS.md`.

This directory owns migration governance, identity, and phase records. It is not
itself a database, DDL, ETL, loader, or deployment surface.

## Result

Read from the live database and `migration_control` on 2026-08-01.

| | |
| --- | --- |
| Target | PostgreSQL 17.10, database `my_pa`, container `my-pa-postgres`, `127.0.0.1:5433` |
| Alembic revision | `3a8e2cb16d59` (head) |
| Schemas | 9 — 8 domain plus `migration_control` |
| Base tables | 494 = 484 domain + 9 control plane + `public.alembic_version` |
| Rows migrated | 3,263,870 |
| Rows quarantined | 8 (`UNSUPPORTED_TEXT_NUL`) |
| Foreign keys | 277, 0 left `NOT VALID` |
| Migration runs | 2, both `COMPLETED` |
| Legacy source | 4,368,125,952 bytes, sha256 `9b8c8d8b…`, schema 128 — retained read-only, indefinitely |

Of the source's 3,323,450 rows, 3,263,878 were in scope and 59,572 (1.79%) were
deliberately excluded. The excluded rows exist only in the retained legacy file;
[`PHASE-12-RETENTION.md`](PHASE-12-RETENTION.md) enumerates them by category.

## Phase records

- [`PHASE-01-FOUNDATION.md`](PHASE-01-FOUNDATION.md) — connection contract,
  engine, Alembic ownership of all target DDL.
- [`PHASE-11-CUTOVER.md`](PHASE-11-CUTOVER.md) — what "canonical" means, how a
  component obtains a session, coexistence with the legacy application, and the
  target-side rollback runbook.
- [`PHASE-12-RETENTION.md`](PHASE-12-RETENTION.md) — legacy source identity,
  retention posture, what the archive uniquely holds, and the backup risk.
  Retention only: `OP-RETIRE-001` is **DO NOT PROCEED** and nothing is retired.

Phases 02 through 10 are recorded in `migration_control` — `migration_runs`,
`phase_status`, `table_progress`, `quarantine_records`, `identifier_map`,
`source_key_map` — rather than in prose here. Query them with
`apps/cli/migration.py status --run-id <id>`.

## Operations

- [`/ops/runbooks/postgres-operations.md`](/ops/runbooks/postgres-operations.md)
  — start, stop, health check, connect, back up, restore.
- [`/ops/postgres/README.md`](/ops/postgres/README.md) — the instance: image,
  tuning, locale, collation contract, reset procedure.

## Governing records

- `governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md`
- `governance/goal-state.json`
- `governance/work-item-ledger.json`
- `governance/authorization-ledger.json`
- `governance/acceptance-criteria-register.json`
- `governance/branch-and-worktree-strategy.md`
- `governance/logging-and-audit-standard.md`
- `governance/target-surface-naming-rule.md`
- `governance/validate_phase00_governance.py`

## Phase 00 result

| Item | State |
|---|---|
| `WP-P00-01` | `CLOSED` |
| `WP-P00-02` | `CLOSED` |
| Active work items | `0` |
| `P00-AC-01` through `P00-AC-08` | accepted |
| PR #11 reviewed head | `245ec31005041f6e1cacef19478c070b272e3dcd` |
| PR #11 squash merge | `4adb205e7c70841b95abb52623b159456eb2eafc` |
| Reviewed-content equivalence | `PASS` — 16/16 blobs identical |
| PR #12 closeout squash merge | `2672898530916c3657d6e5fef47b401c219a61da` |
| Direct Phase 00 validator execution | `PASS` — exit 0, full checkout |
| Branch cleanup | `COMPLETE` — all three residual remote refs deleted |

`P00-AC-08` is accepted by exact-head review, overlapping repository evidence,
and direct execution of `validate_phase00_governance.py` including its full
public-surface scan. No risk is accepted.

## Closeout evidence

- `../../evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json`
- `../../evidence/migration/WP-P00-02/closeout/00_CLOSEOUT_INDEX.json`
- `../../evidence/migration/WP-P00-02/closeout/01_POST_MERGE_VALIDATION.md`
- `../../evidence/migration/WP-P00-02/closeout/02_FINDINGS_AND_CLEANUP_STATUS.md`
- `../../evidence/migration/WP-P00-02/closeout/PHASE-00-FINAL-CLOSEOUT.md`
- `../../evidence/migration/phase-00-final/CLOSEOUT.md`
