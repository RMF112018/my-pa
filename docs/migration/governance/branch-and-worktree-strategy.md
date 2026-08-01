# Phase 00 Branch and Worktree Strategy

**Criterion:** `P00-AC-06`  
**Goal:** `GOAL-MYPA-POSTGRESQL-MIGRATION-001`

## Required entry gates

Before any implementation write:

1. Authenticate repository `RMF112018/my-pa`, target branch `main`, exact base SHA, and exact base tree from runtime Git or authenticated GitHub evidence.
2. Verify local `main`, remote `main`, and the authorization base agree. Any drift stops the work.
3. Verify the intended worktree is clean, not carrying unrelated changes, and attached to the intended branch.
4. Verify one active work item, one authorized branch, the exact changed-path allowlist, acceptance criteria, mutation limits, and prohibitions.
5. Publish the activation evidence outside the commit. A committed predecessor SHA is historical input, not continuously current authority.

## One-work-item / one-branch discipline

- One active work item maps to one short-lived branch and, when local execution is used, one dedicated worktree.
- Branch names must be neutral, purpose-specific, and contain no former-employer branding.
- A work item may not borrow another work item's branch, commit allowance, path scope, or review.
- The authorized branch begins at the exact authenticated base. Rebasing, merging another branch, or changing the base invalidates the entry gate unless expressly reauthorized.

## Review binding

- Implementation review binds the exact head SHA and tree.
- Any later commit invalidates the review; the changed head must be reviewed again.
- The implementing role records evidence as `DEMONSTRATED` only and may not self-PASS.
- Push and PR creation occur only after the authorization's review gate is satisfied.

## Squash-merge validation

A squash merge creates a new commit and therefore breaks ancestry with the reviewed feature head. Non-ancestry alone is not evidence of unique content.

Before cleanup, authenticate:

1. the PR is merged by the authorized method;
2. the resulting `main` identity;
3. reviewed-head versus merged-tree or content equivalence;
4. no branch-only paths;
5. all contributed blobs or equivalent content exist on `main`;
6. the exact feature branch has no later commit;
7. the local worktree is clean and not attached to the branch.

Unavailable evidence remains unavailable. An operator evidence exception may permit sequencing, but it must not be described as a technical PASS.

## Destructive cleanup authority

- Branch or worktree deletion requires a separate exact operator decision naming repository, branch, SHA, and permitted local/remote operations.
- Delete no other branch, tag, worktree, file, or untracked content.
- Prefer local branch deletion before remote ref deletion when local execution is available.
- Record the reviewed head before deletion because the commit may later become unreferenced.
- If the available connector cannot delete a ref, record `PENDING_CONNECTOR_CAPABILITY`; do not claim cleanup.

## Current campaign binding

```yaml
runtime_base_sha: 9039c587680866bfe4c1568db1992335778c5950
implementation_branch: bf/migration-phase-00-completion
maximum_active_work_items: 1
maximum_implementation_branches: 1
maximum_implementation_worktrees: 1
maximum_implementation_commits: 1
maximum_pull_requests: 1
```
