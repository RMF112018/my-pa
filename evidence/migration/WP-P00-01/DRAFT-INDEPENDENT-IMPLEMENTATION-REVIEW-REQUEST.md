# DRAFT — Independent Implementation Review Request: WP-P00-01

**State:** `DRAFTED_NOT_DISPATCHED`
**Dispatch authority:** `OPERATOR_ONLY`

This is a draft. The implementing agent must not execute it, and must not review or approve its
own work. Dispatch it only to a fresh, independent reviewer with no authoring role in
`WP-P00-01`.

```yaml
proposed_coordination_request_id: REQ-MYPA-MIGRATION-WP-P00-01-INDEPENDENT-IMPLEMENTATION-REVIEW-20260731-025
parent_coordination_request_id: REQ-MYPA-MIGRATION-WP-P00-01-IMPLEMENTATION-20260731-024
authorization_id: AUTH-MYPA-MIGRATION-WP-P00-01-20260731-001
goal_id: GOAL-MYPA-POSTGRESQL-MIGRATION-001
phase_id: PHASE-00
work_item_id: WP-P00-01
repository: RMF112018/my-pa
base_branch: main
base_sha: d4fed7ec12f0b25ad5520d806aeb7766e95228d5
base_tree: faf44a32ba54b13fb6ce75c25e4bf4cd4e2fa1c4
implementation_branch: bf/migration-wp-p00-01-governance-identity
implementation_head: SUPPLY_FROM_PUBLISHED_COMMIT_IDENTITY
implementation_tree: SUPPLY_FROM_PUBLISHED_COMMIT_IDENTITY
reviewer_role: INDEPENDENT
review_type: IMPLEMENTATION_REVIEW
exact_head_binding_required: true
```

The operator must substitute the exact implementation head and tree from the published
`COMMIT-IDENTITY.json` before dispatch. A review not bound to the exact head is invalid.

## Subject

Independently review the single commit `docs(migration): bind WP-P00-01 governance and
identities` on `bf/migration-wp-p00-01-governance-identity`, one commit above
`d4fed7ec12f0b25ad5520d806aeb7766e95228d5`.

## Reviewer authority

The reviewer may read the repository at the exact implementation head, read the published
evidence package, and read the authorization package by exact Drive ID.

The reviewer may **not** implement, amend, commit, push, open a pull request, merge, deploy,
activate `WP-P00-02`, connect to any database, open the snapshot, or accept risk.

## Required verification

1. **Entry-gate integrity.** Confirm the authorization was `ACTIVE_UNCONSUMED` and unexpired at
   the recorded first-write time, that it was operator-activated rather than self-authorized,
   and that the controlling receipt reported `COMPLETE_AND_VERIFIED`, publication `VERIFIED`,
   binding `MATCH`, index `REGISTERED_ACTIVE_UNCONSUMED`, and prompt binding
   `MATCH_AFTER_PROMPT_REVISION`.
2. **Exact identity.** Re-derive the target base SHA and tree, and independently re-authenticate
   the legacy head, tree, and schema version `135` through read-only repository metadata.
   Confirm the snapshot identity is recorded and that the snapshot was not opened.
3. **Mutation limits.** Confirm exactly one commit above the authorized base, the exact commit
   message, no amend, no second commit, no push, no pull request, and no merge.
4. **Changed-path containment.** Confirm every changed path falls within `docs/migration/**` or
   `evidence/migration/**`, and that no file outside those prefixes was created, modified,
   renamed, or deleted.
5. **Acceptance criteria.** Independently determine whether `P00-AC-01` through `P00-AC-05` are
   satisfied by evidence bound to the exact head. Confirm `P00-AC-06`, `P00-AC-07`, and
   `P00-AC-08` were neither implemented nor evidenced.
6. **Scope discipline.** Confirm no runtime code, database model, parser, loader, migration
   control plane, dependency, or CI change was introduced, and that
   `identity-attestation-contract.schema.json` remains a documentation contract only.
7. **Source authority.** Confirm the legacy SQLite source is documented read-only and that
   access, rename, and mutation remain denied. Confirm no database, SQLite, snapshot, or
   PostgreSQL access occurred.
8. **Target identity.** Confirm the logical target identity is `my_pa`, that no physical alias
   value was recorded, and that this agrees with `AGENTS.md` §4 and `ADR-002`.
9. **Evidence integrity.** Confirm validation output is preserved verbatim, that no failed
   evidence was deleted or overwritten, and that no credentials, connection strings, personal
   data, message bodies, document contents, or raw source or snapshot payloads appear anywhere
   in the package.
10. **Governance consistency.** Confirm the charter, goal state, work-item ledger, authorization
    ledger, acceptance register, and evidence index agree, and that `WP-P00-02` remains
    `NOT_ACTIVATED` with operator-only activation.
11. **Self-review boundary.** Confirm the implementation recorded `DEMONSTRATED` rather than any
    acceptance disposition, and that the independent review request was drafted, not executed.
12. **Disclosed limitations.** Assess the four limitations disclosed in
    `01_IMPLEMENTATION_CHECKPOINT.md` and the coordination response — in particular that
    `docs/00_REPOSITORY_SOURCE_INDEX.md` does not route to the new migration index because that
    path is outside the authorized scope. Determine whether that is correctly deferred or a
    defect.

## Required dispositions

One of:

```text
INDEPENDENT_WP_P00_01_IMPLEMENTATION_REVIEW_PASS
INDEPENDENT_WP_P00_01_IMPLEMENTATION_REVIEW_FAIL
INDEPENDENT_WP_P00_01_IMPLEMENTATION_REVIEW_BLOCKED
```

A `PASS` disposition authorizes nothing by itself. Push, pull request, merge, deployment,
cleanup, retirement, risk acceptance, and `WP-P00-02` activation each remain operator-gated and
require their own separate explicit authorization.

## Required response contract

The reviewer must return: reviewer independence attestation; exact head and tree reviewed;
entry-gate verification; identity re-authentication results; commit count and containment
results; per-criterion determinations for `P00-AC-01` through `P00-AC-05`; findings with
severity; evidence-integrity assessment; access attestations; disposition; and the operator-only
next action.

## Invalidation

Any commit made after the reviewed head invalidates this review. Any identity, scope, acceptance,
or mutation-limit drift invalidates both the authorization and the review bound to it.
