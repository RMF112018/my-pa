# Draft Role-Separated Exact-Head Review Request — WP-P00-02

Review the Phase 00 completion implementation as a role-separated reviewer context that did not perform the repository write.

## Identity to bind externally

```yaml
repository: RMF112018/my-pa
goal_id: GOAL-MYPA-POSTGRESQL-MIGRATION-001
phase_id: PHASE-00
work_item_id: WP-P00-02
authorization_id: AUTH-MYPA-MIGRATION-PHASE-00-COMPLETION-20260801-001
base_sha: 9039c587680866bfe4c1568db1992335778c5950
branch: bf/migration-phase-00-completion
head_sha: EXTERNAL_POST_COMMIT_EVIDENCE
tree_sha: EXTERNAL_POST_COMMIT_EVIDENCE
```

## Required adjudication

1. Authorization, entry gates, one-branch/one-commit limits, and changed-path containment.
2. Preservation of the blocked WP-P00-01 connector-only validation and bounded operator exception.
3. F-001 and F-003 dispositions.
4. Exact residual branch cleanup status and prohibition on other cleanup.
5. `P00-AC-06`, `P00-AC-07`, and `P00-AC-08`.
6. Goal-state, work-item, authorization, acceptance, charter, migration-index, and evidence consistency.
7. No runtime, database, dependency, CI, deployment, production, credential, source-data, or Phase 01 scope.
8. Deterministic validation and evidence integrity.
9. Exact-head binding; any later commit invalidates the review.

Return PASS, PASS_WITH_NONBLOCKING_FINDINGS, or FAIL. Do not accept risk, authorize merge, or activate Phase 01.
