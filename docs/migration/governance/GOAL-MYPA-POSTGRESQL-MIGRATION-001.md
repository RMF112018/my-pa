# GOAL-MYPA-POSTGRESQL-MIGRATION-001 — Migration Goal Charter

**Repository:** `RMF112018/my-pa`  
**Active phase:** `PHASE-00`  
**Current state:** `PHASE_00_COMPLETION_IMPLEMENTED_PENDING_EXACT_HEAD_REVIEW`  
**Reconciled at:** `2026-08-01T07:51:37Z`

## Objective

Establish the governed structure under which `my-pa` may later migrate to the canonical PostgreSQL metadata and knowledge store. Phase 00 binds identity, authority, workflow, privacy, naming, evidence, and review controls. It performs no database, schema, data movement, or runtime migration work.

## Current campaign

```yaml
authorization_id: AUTH-MYPA-MIGRATION-PHASE-00-COMPLETION-20260801-001
decision_id: OP-COMPLETE-MYPA-MIGRATION-PHASE-00
runtime_base_branch: main
runtime_base_sha: 9039c587680866bfe4c1568db1992335778c5950
implementation_branch: bf/migration-phase-00-completion
active_work_item: WP-P00-02
maximum_implementation_commits: 1
```

Exact post-commit identity is recorded externally. A committed predecessor SHA is historical input, not continuously current authority.

## Phase 00 work items

### WP-P00-01 — closed with preserved limitation

`WP-P00-01` satisfied `P00-AC-01` through `P00-AC-05`. PR #10 later corrected self-invalidating baseline semantics and is authenticated as merged from reviewed head `d54bdb6d23cebf38c11db7194aef59b03d573a16` to `main` at `9039c587680866bfe4c1568db1992335778c5950`.

The connector-only post-merge validation disposition remains:

`WP_P00_01_NRB_POST_MERGE_VALIDATION_BLOCKED_BY_UNAVAILABLE_GITHUB_EVIDENCE`

The operator has accepted `OPERATOR_EVIDENCE_EXCEPTION_ACCEPTED_FOR_PHASE_00_SEQUENCE`. This closes the administrative sequencing blocker but is not a technical PASS and grants no database, deployment, production, or data-integrity assurance.

- `MYPA-WP-P00-01-FINAL-CLOSEOUT-F-001`: closed under that bounded exception with the limitation preserved.
- `MYPA-WP-P00-01-NRB-IR-F-003`: corrected by runtime-Git identity resolution in the work-item ledger.
- Exact residual branch cleanup is authorized only for `bf/migration-wp-p00-01-nonrecursive-baseline` at `d54bdb6d23cebf38c11db7194aef59b03d573a16` and remains pending connector capability.

### WP-P00-02 — completion candidate

`WP-P00-02` is activated and implemented in the single completion candidate. It demonstrates:

- `P00-AC-06` through [`branch-and-worktree-strategy.md`](branch-and-worktree-strategy.md);
- `P00-AC-07` through [`logging-and-audit-standard.md`](logging-and-audit-standard.md);
- `P00-AC-08` through [`target-surface-naming-rule.md`](target-surface-naming-rule.md).

The implementing context records `DEMONSTRATED` only. Exact-head role-separated review is required before PR creation.

## Authority and precedence

1. authenticated runtime evidence;
2. authenticated repository and GitHub state;
3. repository governance, accepted specifications, ADRs, and acceptance criteria;
4. indexed Workspace publications;
5. conversations and reports as claims.

Only the operator may accept risk, authorize merge and destructive cleanup for the exact future identity, close Phase 00, deploy, activate production, or activate Phase 01.

## Branch, review, and cleanup controls

- One active work item, one short-lived branch, and one commit under this authorization.
- Runtime Git resolves the exact base; committed records do not claim continuously current SHA/tree.
- Review binds exact head and tree; a later commit invalidates review.
- Squash non-ancestry alone does not prove unique content.
- Cleanup requires exact operator authority, content-equivalence evidence or a clearly bounded exception, clean-worktree evidence where applicable, and a verified receipt.
- No connector capability means no cleanup claim.

## Logging and audit controls

Logs and audit records exclude message bodies, document contents, personal contact details, credentials, tokens, connection strings, raw JSON/source payloads, and sensitive query text. They may retain stable non-content identifiers, event types, bounded counters, redacted metadata, and decision/evidence references.

## Naming controls

Current public APIs, modules, environment variables, MCP capabilities, user-facing surfaces, and new repository paths use neutral `my-pa`, `my_pa`, and `MY_PA_` naming. Exact legacy names remain only in explicitly classified historical, read-only source, compatibility, migration-provenance, finding, or test-fixture contexts.

## Evidence and review

Evidence is content-safe and bound to exact identities. Failed and unavailable evidence is preserved. The implementing role may not self-PASS. A role-separated exact-head review adjudicates the candidate. PR and CI follow only after review PASS.

## Prohibitions

No SQLite, retained snapshot, PostgreSQL, or database access. No DDL, ETL, loaders, migration runtime code, dependencies, CI workflow changes, personal data processing, deployment, production activation, legacy retirement, risk acceptance, or Phase 01 activation.
