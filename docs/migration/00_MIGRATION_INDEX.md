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
| Phase | `PHASE-00` |
| Active work item | `WP-P00-01` — bind migration identities and governance ledger |
| Authorization | `AUTH-MYPA-MIGRATION-WP-P00-01-20260731-001` |
| Bound acceptance criteria | `P00-AC-01` … `P00-AC-05` |
| Successor `WP-P00-02` | `NOT_ACTIVATED` — operator-only, never automatic |
| Terminal state | `IMPLEMENTED_PENDING_INDEPENDENT_REVIEW` |

## Registration limitation

[`docs/00_REPOSITORY_SOURCE_INDEX.md`](../00_REPOSITORY_SOURCE_INDEX.md) does not yet route to
this index, because that file is outside the authorized paths for `WP-P00-01`
(`docs/migration/**` and `evidence/migration/**`). Adding the route requires a separate
authorization. This is disclosed for independent review rather than resolved by widening scope.
