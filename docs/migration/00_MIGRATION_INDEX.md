# Migration Index

**Status:** `GOVERNANCE_AND_IDENTITY_ONLY`

This directory owns governed records for `GOAL-MYPA-POSTGRESQL-MIGRATION-001`. It is the
nearest owning index for `docs/migration/**`.

Directory presence does not authorize implementation. No runtime migration code, schema, DDL,
ETL, loader, control plane, dependency, or CI change belongs here. Database, SQLite, snapshot,
and PostgreSQL access require a separate explicit operator authorization.

Read [`AGENTS.md`](../../AGENTS.md) first; it is the principal normative policy and it already
fixes the architectural facts this goal operates under (`§4`: PostgreSQL is the canonical
metadata and knowledge store; the logical database identity is `my_pa`; a physical compatibility
alias authorizes no rename, migration, connection, or mutation). See also
[`ADR-002`](../decisions/ADR-002-database-identity-and-compatibility-alias.md).

## Governance records

- [`governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md`](governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md) — migration goal charter: objective, authority, scope, prohibitions, evidence and review rules.
- [`governance/goal-state.json`](governance/goal-state.json) — current goal lifecycle state, active phase, active work item, and successor activation state.
- [`governance/work-item-ledger.json`](governance/work-item-ledger.json) — work items, states, authorized paths, acceptance criteria, and the at-most-one-active rule.
- [`governance/authorization-ledger.json`](governance/authorization-ledger.json) — authorization identity, operator activation basis, validity window, mutation limits, and consumption rule.
- [`governance/exact-identity.json`](governance/exact-identity.json) — authenticated target, legacy, snapshot, target-identity, branch, worktree, plan, review, and gate bindings.
- [`governance/source-read-only-identity.json`](governance/source-read-only-identity.json) — legacy SQLite source identity, read-only authority, and explicit access/rename/mutation denial.
- [`governance/plan-and-review-bindings.json`](governance/plan-and-review-bindings.json) — planning gate, R2 plan package, independent plan review, and authorization-chain artifact bindings.
- [`governance/acceptance-criteria-register.json`](governance/acceptance-criteria-register.json) — `P00-AC-01` … `P00-AC-05` with required evidence, plus the criteria expressly excluded as `WP-P00-02` scope.
- [`governance/identity-attestation-contract.schema.json`](governance/identity-attestation-contract.schema.json) — documentation-level JSON Schema contract for identity attestations, plus content-safe evidence and audit rules. Schema only; no parser, runtime, model, loader, or dependency.

## Evidence

Work-item evidence lives under `evidence/migration/<work-item-id>/` and is bound to the exact
implementation head. See [`evidence/migration/WP-P00-01/00_EVIDENCE_INDEX.json`](../../evidence/migration/WP-P00-01/00_EVIDENCE_INDEX.json).

## Current state

| Item | Value |
|---|---|
| Goal | `GOAL-MYPA-POSTGRESQL-MIGRATION-001` |
| Phase | `PHASE-00` — `IN_PROGRESS` |
| Active work item | **none** |
| Last closed work item | `WP-P00-01` — bind migration identities and governance ledger |
| `WP-P00-01` state | **`CLOSED`** |
| Repository identity | **`RUNTIME_GIT_REQUIRED`** — branch `main`; committed exact-current SHA intentionally not stored |
| Successor `WP-P00-02` | `NOT_ACTIVATED` — operator-only, never automatic |
| Remaining Phase 00 criteria | `P00-AC-06` … `P00-AC-08` (belong to `WP-P00-02`) |

Every future authorization must authenticate local and remote `main` at dispatch time and
bind the resulting exact SHA and tree in the external authorization and evidence package.
No committed predecessor SHA is current authority.

Historical merge identities (not current authority):

| Role | Identity |
|---|---|
| `ORIGINAL_AUTHORIZATION_BASE` | `d4fed7ec12f0b25ad5520d806aeb7766e95228d5` |
| `MERGE_SHA` — WP-P00-01 implementation (PR #8) | `3e5aad7b2526b09b1e46c817bd00c401e569f5a4` |
| `MERGE_SHA` / `RECORD_BASE` — closeout correction (PR #9) | `178a7e243cbc6100c6937144ff10a7987206c04a` |

## Work-item history

`WP-P00-01` — closed. Acceptance criteria `P00-AC-01` … `P00-AC-05` satisfied.

| Stage | Identity |
|---|---|
| Implementation | `d60c25f51964fd2ae05211d0f3e9fef8d8f7f03f`, tree `9956fe7bed3b2d92e7243b1881f5b31c2d28da1d` |
| Independent review | `INDEPENDENT_WP_P00_01_IMPLEMENTATION_REVIEW_PASS` at the pre-merge head, 0 blocking findings |
| Integration | pull request #8 |
| Merge | squash, `3e5aad7b2526b09b1e46c817bd00c401e569f5a4`, tree unchanged at `9956fe7b…` |
| Post-merge validation | `PASS` — tree and all 20 file blobs byte-identical |
| Cleanup | complete — both branch refs deleted |
| Closeout correction | squash merge `178a7e243cbc6100c6937144ff10a7987206c04a`, tree `25131169…`; branch cleanup complete |
| Final closeout | **BLOCKED** by `MYPA-WP-P00-01-FINAL-CLOSEOUT-F-001` until the non-recursive baseline correction is independently reviewed |

Historical implementation evidence is preserved under
[`evidence/migration/WP-P00-01/`](../../evidence/migration/WP-P00-01/00_EVIDENCE_INDEX.json);
closeout evidence is under
[`evidence/migration/WP-P00-01/closeout/`](../../evidence/migration/WP-P00-01/closeout/00_CLOSEOUT_INDEX.json);
non-recursive baseline correction evidence is under
[`evidence/migration/WP-P00-01/closeout/nonrecursive-baseline/`](../../evidence/migration/WP-P00-01/closeout/nonrecursive-baseline/00_INDEX.json).
Durable coordination packages for every stage are published to the governed Drive evidence area.
