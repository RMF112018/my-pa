# WP-TUX-04 — Canonical Create Task

## Identity

- **Goal:** `wp-tux-04-canonical-create-task`
- **Work item:** WP-TUX-04 — Canonical Create Task
- **Coordination request:** `MYPA-WP-TUX-04-IMPLEMENTATION-20260912-001`
- **Repository:** `RMF112018/my-pa`
- **Authorized base commit:** `7f068e65ba64756ff5c1df77f0412311f9fe19df`
- **Authorized base tree:** `8688ac24544c1f8703593875381df7b0b77efc2c`
- **Branch:** `feat/wp-tux-04-canonical-create-task-20260912`
- **Worktree:** `/private/tmp/my-pa-wp-tux-04-20260912`
- **Head:** recorded in the implementation receipt at completion
- **PR:** recorded at completion

## Objective

Deliver one canonical, accessible, mobile-first ordinary Create Task interaction that exists
once as a shared Task component, opens from both Work → New task and Global Capture → Create
Task, and exposes exactly Title, Description, Priority and Due date.

## Scope

- Extract the Workbench-embedded `TaskCreate` into a shared `TaskCreateSheet` under the landed
  `web/src/components/tasks/` ownership.
- Reduce ordinary create to four fields; remove Commitment, Role and the create-time commitments
  read. Origin remains absent.
- Bind the WP-TUX-03 priority vocabulary; no raw `p1`–`p4` in ordinary Create UX.
- Replace the `datetime-local` Due with a date-only control serialized as `23:59:59` local in the
  applicable IANA zone, then UTC, via a tested end-of-day sibling of the landed civil-day helpers.
- Add a narrow session-scoped confirmed-create reconciliation seam so a shell-launched create can
  notify active Task queries.
- Wire Work and Global Capture to the same component.

## Acceptance criteria

The 35-item WP-TUX-04 completion gate in the governing package, and the Create portions of
`TASK-AC-001`–`008`, `009`, `010`, `011` (contribution), `012` (DST/timezone proof),
`029`–`032`, `038`, `043` (priority), `045` (responsive), `048` (obsolete expectation
replacement) and `050` (automated enablement).

## Constraints

- Consume WP-TUX-01, WP-TUX-02 and WP-TUX-03 contracts; build no competing copies.
- Preserve the WP-TUX-02 create-intent, synchronous submit mutex and ambiguous same-key retry.
- Preserve the trusted BFF boundary that injects `origin_kind="direct_principal"`.
- Task creation must never enter Capture's offline queue or be replayed on reconnect.
- Reuse the existing Radix `Sheet`; add no second overlay system.
- No backend, domain, schema or migration change is expected.

## Prohibited

Merge to `main`; deployment; production activation; database or migration execution; credential
or secret creation, mutation or disclosure; live personal-data access; source-system mutation;
destructive data action; destructive repository cleanup; material risk acceptance; weakening
governance, security, testing or acceptance criteria; implementing WP-TUX-05 through WP-TUX-08
beyond hooks strictly necessary here.

## Authorization boundary

Operator-authorized for implementation, branch/worktree, in-scope edits, synthetic tests,
commits, push, one focused PR, specialized workers and independent exact-head review.
Terminal state is **review-complete / PR-ready / not merged**.

## Plan

The accepted governing package
`MYPA_TASK_MANAGEMENT_UX_WP_TUX_04_CANONICAL_CREATE_TASK_REMEDIATION_PACKAGE_2026-09-12.md`
(Drive ID `13dTrFe3YpODzx2c8e3_qjAgjzHxnjCsRKwlomL2sZWY`), reconciled by
`MYPA_TASK_MANAGEMENT_UX_WP_TUX_04_POST_WP3_EXECUTION_RECONCILIATION_2026-09-12.md`
(Drive ID `1-AFmZpjOLOnYdiErNcLxJEgmvRcRniya`), which cleared the WP-TUX-03 dependency.

## Test and evidence results

Recorded in the implementation receipt and the published Drive coordination response at
completion.

## Review outcome

Independent exact-head review recorded at completion. Any commit after that review invalidates
it and a new review is obtained.

## Final state

`IN_PROGRESS` until the implementation receipt records a terminal disposition.
