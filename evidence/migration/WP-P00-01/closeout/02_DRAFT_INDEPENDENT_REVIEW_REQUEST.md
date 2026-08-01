# DRAFT — Independent Review Request: WP-P00-01 Closeout Correction

> **DRAFT. NOT DISPATCHED.** The implementing agent must not execute this or review its own work.
> Dispatch only to a fresh, independent reviewer with no authoring role in this correction.

```yaml
proposed_coordination_request_id: REQ-MYPA-MIGRATION-WP-P00-01-CLOSEOUT-CORRECTION-INDEPENDENT-REVIEW-20260801-032
parent_coordination_request_id: REQ-MYPA-MIGRATION-WP-P00-01-CLOSEOUT-CORRECTION-20260801-031
authorization_id: AUTH-MYPA-MIGRATION-WP-P00-01-CLOSEOUT-20260801-001
decision_id: OP-CLOSEOUT-WP-P00-01
repository: RMF112018/my-pa
base_branch: main
base_sha: 3e5aad7b2526b09b1e46c817bd00c401e569f5a4
base_tree: 9956fe7bed3b2d92e7243b1881f5b31c2d28da1d
implementation_branch: bf/migration-wp-p00-01-closeout-correction
implementation_head: SUPPLY_FROM_PUBLISHED_COMMIT_IDENTITY
implementation_tree: SUPPLY_FROM_PUBLISHED_COMMIT_IDENTITY
reviewer_role: INDEPENDENT
review_type: CLOSEOUT_CORRECTION_REVIEW
exact_head_binding_required: true
```

The operator must substitute the exact head and tree from the published `09_COMMIT-IDENTITY.json`
before dispatch. A review not bound to the exact head is invalid.

## Subject

Independently review the single commit `docs(migration): reconcile WP-P00-01 closeout state`, one
commit above `3e5aad7b2526b09b1e46c817bd00c401e569f5a4`.

## Reviewer authority

May read the repository at the exact head, the published evidence, and the authorization chain by
exact Drive ID. May **not** implement, amend, commit, push, open a pull request, merge, activate
`WP-P00-02`, access any database, or accept risk.

## Required verification

1. **Entry-gate integrity.** Confirm the authorization was `ACTIVE_UNCONSUMED` and unexpired at the
   recorded activation time, that it is correction-class, and that all seven controlling Drive
   artifacts authenticate.
2. **Exact identity.** Re-derive the base SHA and tree; confirm exactly one commit above base and
   the exact commit message.
3. **Path containment.** Confirm every changed path is within the authorized list, which is
   file-specific for `docs/` and a glob only for `evidence/migration/WP-P00-01/**`.
4. **Ledger reconciliation.** Confirm `WP-P00-01` is `CLOSED` and bound to merge SHA `3e5aad7b…`;
   that original implementation identities are preserved as history and **not** rewritten as
   though the closeout authorization were the original; and that zero work items are active.
5. **Goal state.** Confirm `active_work_item_id` is `null`, the stale binding to the consumed
   authorization is removed as current authority, and no successor is activated.
6. **Authorization ledger.** Confirm the original authorization is `CONSUMED`, the closeout
   authorization is recorded, and no successor authorization exists.
7. **Index and charter.** Confirm no current-state record still claims `WP-P00-01` is active or
   that `IMPLEMENTED_PENDING_INDEPENDENT_REVIEW` is its current state, and that historical facts
   are labelled historical rather than rewritten.
8. **Root source index.** Confirm it routes to `docs/migration/00_MIGRATION_INDEX.md` and that the
   now-resolved routing limitation was removed from the migration index.
9. **Cleanup convention.** Confirm the squash-merge cleanup rule is documented with all eight
   conditions and that it authorizes nothing by itself. Assess the decision to place it in the goal
   charter rather than a new governance file — a new file would have been outside the authorized
   path list.
10. **Scope discipline.** Confirm no runtime code, migration functionality, dependency, or CI
    workflow change, and no `WP-P00-02` implementation, activation, or authorization drafting.
11. **Validation.** Independently reproduce the FAST tier, JSON validation, the Markdown
    relative-link validator, and the stale-state search at the exact head.
12. **Evidence integrity.** Confirm historical implementation evidence was not overwritten, that
    closeout evidence is in its own subdirectory, and that no in-repository record claims to
    contain its own commit SHA.

## Required dispositions

```text
INDEPENDENT_WP_P00_01_CLOSEOUT_CORRECTION_REVIEW_PASS
INDEPENDENT_WP_P00_01_CLOSEOUT_CORRECTION_REVIEW_FAIL
INDEPENDENT_WP_P00_01_CLOSEOUT_CORRECTION_REVIEW_BLOCKED
```

A `PASS` authorizes nothing by itself. Push, pull request, merge, post-merge validation, branch
cleanup, final closure, and `WP-P00-02` activation each remain separately operator-gated.

## Note for the reviewer

This correction's own integration will squash-merge, which reproduces the `git branch -d`
non-ancestry refusal documented in the cleanup convention now recorded in the goal charter. The
convention exists so that outcome is anticipated rather than rediscovered.
