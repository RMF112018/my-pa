# Migration Index

**Status:** `GOVERNANCE_AND_IDENTITY_ONLY`  
**Goal:** `GOAL-MYPA-POSTGRESQL-MIGRATION-001`  
**Phase:** `PHASE-00 — COMPLETION CANDIDATE PENDING EXACT-HEAD REVIEW`

This directory owns migration governance and identity records only. It authorizes no database access, DDL, ETL, loader, runtime migration implementation, dependency change, CI change, deployment, production activation, or Phase 01 activation.

## Governing records

- [`governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md`](governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md)
- [`governance/goal-state.json`](governance/goal-state.json)
- [`governance/work-item-ledger.json`](governance/work-item-ledger.json)
- [`governance/authorization-ledger.json`](governance/authorization-ledger.json)
- [`governance/acceptance-criteria-register.json`](governance/acceptance-criteria-register.json)
- [`governance/branch-and-worktree-strategy.md`](governance/branch-and-worktree-strategy.md) — `P00-AC-06`
- [`governance/logging-and-audit-standard.md`](governance/logging-and-audit-standard.md) — `P00-AC-07`
- [`governance/target-surface-naming-rule.md`](governance/target-surface-naming-rule.md) — `P00-AC-08`
- [`governance/validate_phase00_governance.py`](governance/validate_phase00_governance.py) — deterministic standard-library validation

Historical identity/source records remain in this folder and remain authoritative for their bounded historical purposes.

## Current state

| Item | State |
|---|---|
| Runtime base | `main` @ `9039c587680866bfe4c1568db1992335778c5950` |
| Active work item | `WP-P00-02` |
| WP-P00-02 | `IMPLEMENTED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW` |
| P00-AC-06 | `DEMONSTRATED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW` |
| P00-AC-07 | `DEMONSTRATED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW` |
| P00-AC-08 | `DEMONSTRATED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW` |
| Phase 00 | `IN_PROGRESS_PENDING_REVIEW_AND_INTEGRATION` |
| Phase 01 | `NOT_ACTIVATED` |

## WP-P00-01 residual reconciliation

PR #10 is authenticated as merged at `9039c587680866bfe4c1568db1992335778c5950` from reviewed head `d54bdb6d23cebf38c11db7194aef59b03d573a16`. The earlier connector-only post-merge validation remains `BLOCKED_BY_UNAVAILABLE_GITHUB_EVIDENCE`; the operator exception permits Phase 00 sequencing but is not technical PASS.

- `MYPA-WP-P00-01-FINAL-CLOSEOUT-F-001`: `CLOSED_BY_OPERATOR_EVIDENCE_EXCEPTION_WITH_LIMITATION`.
- `MYPA-WP-P00-01-NRB-IR-F-003`: corrected in this candidate by removing stale required-base semantics from `work-item-ledger.json`.
- Residual branch `bf/migration-wp-p00-01-nonrecursive-baseline` still exists at `d54bdb6d23cebf38c11db7194aef59b03d573a16`; exact cleanup is authorized but pending an available branch-delete capability.

## Evidence

- [`../../evidence/migration/WP-P00-01/`](../../evidence/migration/WP-P00-01/00_EVIDENCE_INDEX.json)
- [`../../evidence/migration/WP-P00-01/closeout/`](../../evidence/migration/WP-P00-01/closeout/00_CLOSEOUT_INDEX.json)
- [`../../evidence/migration/WP-P00-02/`](../../evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json)

Exact post-commit head/tree, review, PR, CI, merge, cleanup, and final closeout identities are published externally so committed records do not attempt to predict their own containing commit.
