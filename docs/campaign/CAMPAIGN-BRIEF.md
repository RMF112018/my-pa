---
campaign_id: CAMPAIGN-MYPA-MOSS-FULL-IMPLEMENTATION-20260805
product_package_id: MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008
product_package_version: "4.0"
product_package_sha256: 60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
main_head: 6461e2ae914d9c70f487fa602d98987cd851e30d
main_tree: de4113fe3595f84373ca54ee5ec6b559ace5722d
active_goal_id: GOAL-MYPA-MOSS-MCV-MVP-V4
active_work_item_id: WP-03-R2-CAPTURE
active_authorization_id: PROMPT-MYPA-MOSS-FULL-IMPLEMENTATION-MANAGER-20260805-001
lifecycle_state: WP03_IMPLEMENTED_PR_OPEN_AWAITING_REVIEW
completed_work_packages:
  - id: WP-00
    name: Campaign Formation and Ratification
    artifacts:
      - docs/campaign/RATIFICATION-MYPA-MOSS-V4-20260805.md
      - docs/campaign/REPOSITORY-TRUTH-REPORT-20260805.md
      - docs/campaign/WORK-PACKAGE-MAP.md
      - docs/campaign/CAMPAIGN-BRIEF.md
  - id: WP-01
    name: R0A Identity Foundation
    merged_as: 21ff8dc228be84530fb598c2a81f037aafb2d9b0
    merge_method: "squash (PR 45, all three CI checks green)"
    post_merge_validation: >
      FAST tier 3003 passed; database tier 479 passed (one local-only
      Postgres teardown privilege, resolved by GRANT pg_signal_backend,
      not a repository defect). Branch feat/wp-01-r0a-identity-foundation
      deleted remotely and locally.
    artifacts:
      - migrations/versions/20260805_c4a7e2d81b53_create_identity_user_accounts.py
      - src/my_pa/domain/identity/
      - tests/security/test_principal_claims_validation.py
      - tests/security/test_cross_principal_isolation.py
  - id: WP-02
    name: R0/R1 Foundation — MossAIc Frontend Shell
    merged_as: 6461e2ae914d9c70f487fa602d98987cd851e30d
    merge_method: "squash (PR 46, gates green)"
    post_merge_validation: >
      FAST tier 3003 passed; web vitest 25 passed. Branch
      feat/wp-02-r1-frontend-shell deleted remotely and locally.
    artifacts:
      - docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md
      - web/ (Next.js App Router application, synthetic identity provider)
      - web/src/middleware.ts and route-level session guards
current_acceptance_baseline: MU-AC-01..MU-AC-05 (19_ACCEPTANCE_CRITERIA_CROSSWALK.md)
active_decisions:
  - id: CD-01
    decision: >
      WP-00 and WP-01 delivered on one feature branch and one PR
      (feat/wp-01-r0a-identity-foundation): campaign formation artifacts are
      documentation-only and R0A is their first governed consumer.
  - id: CD-02
    decision: >
      UserAccount/Principal registry lives in a new `identity` PostgreSQL
      schema owned by its own frozen-literal Alembic revision, keeping the
      identity plane separate from the `knowledge` application schema and the
      read-only legacy schemas.
  - id: CD-03
    decision: >
      R0A `principal_id` is a UUID minted at first sight of a validated
      `(tid, oid)` pair; `(tid, oid)` is identity, `upn`/`display_name` are
      mutable observations. The pre-v4 actor Principal (`prn_…`) remains a
      separate control-plane concept and is not conflated.
  - id: CD-04
    decision: >
      The Moss home tenant ID is injected as configuration into the identity
      service (constructor argument; synthetic value in tests). No live tenant
      value is committed.
  - id: CD-05
    decision: >
      WP-02 frontend is a Next.js App Router PWA under `web/` (ADR-004,
      PKL-MYPA-D-WP02-001) with a synthetic identity provider; identity
      derives only from validated Entra-shaped claims, sessions are
      HMAC-signed HttpOnly cookies, and caller-supplied identity fields
      are rejected at client wrapper, middleware, and every route.
  - id: CD-06
    decision: >
      WP-03 capture plane is Principal-partitioned (ADR-005,
      PKL-MYPA-D-WP03-001): the local operator is one durable principal
      across compositions, ownership is bound and verified at admission,
      idempotency is unique per (principal_id, idempotency_key) at
      revision e7f3a9c2d514, and a foreign Principal's capture is
      indistinguishable from a nonexistent one on every read path.
      Supersedes the D-72 working default and dissolves the D-67 premise.
open_findings: []
blocked_actions:
  - production deployment or activation
  - live Entra app registration, credentials, or secret handling
  - live personal-data access
  - destructive Apple/native retirement
operator_only_decisions:
  - MCV completion date (AGENTS.md section 1, open ledger)
  - live tenant activation and app registration for R0A+
next_work_package: WP-04-R3-OFFLINE-CAPTURE
required_sources:
  - /docs/campaign/WORK-PACKAGE-MAP.md
  - product package documents 02, 07, 09, 12, 13, 17, 18, 19
invalidations:
  - Any commit to main after 6461e2ae914d9c70f487fa602d98987cd851e30d
    invalidates the head identity recorded here; re-authenticate before WP-04.
artifact_references:
  ratification: docs/campaign/RATIFICATION-MYPA-MOSS-V4-20260805.md
  truth_report: docs/campaign/REPOSITORY-TRUTH-REPORT-20260805.md
  work_package_map: docs/campaign/WORK-PACKAGE-MAP.md
---

# Campaign Brief — my-pa Moss Full Implementation

## Mission

Build the complete accepted Moss-focused my-pa MCV/MVP as defined by the
ratified v4.0 product package, reconciled with current repository truth:
an evidence-grounded executive continuity system for authenticated Moss
employees, with strict per-Principal isolation, bounded AI, and delegated
Microsoft 365 connectivity — using synthetic identities and fixtures
throughout (no live credentials, no live personal data, no production
activation).

## Current state

- **WP-00 complete:** v4.0 package ratified; repository truth report,
  work-package map, and this brief published under `docs/campaign/`.
- **WP-01 (R0A Identity Foundation) merged** as `21ff8dc2`: `identity`
  schema migration, token-claim validation with home-tenant rejection,
  idempotent Principal resolution, caller-supplied identity rejection,
  fail-closed Principal-context data-access guard, and cross-Principal
  isolation negative tests.
- **WP-02 (MossAIc Frontend Shell) merged** as `6461e2ae` (PR 46):
  Next.js App Router PWA under `web/` with five destinations, synthetic
  Entra-shaped identity boundary, and canonical TypeScript contracts.
- **WP-03 (R2 Product-owned Capture) implemented on
  `feat/wp-03-r2-principal-capture`:** durable local-operator principal
  (`domain/identity/binding.py`), ownership bound and verified at capture
  admission, per-Principal idempotency at revision `e7f3a9c2d514`,
  owner-scoped read/list/search/revise (foreign captures are nonexistent),
  and cross-Principal capture isolation negative tests (ADR-005,
  PKL-MYPA-D-WP03-001). PR open for review.

## Operating rules in force

1. Repository governance (`AGENTS.md`) governs execution; the ratified package
   governs product intent; runtime evidence outranks both when facts conflict.
2. R0A blocks all user-scoped features (roadmap rule). MU-AC-01..05 are the
   gate.
3. Every durable user-scoped table introduced from WP-01 onward carries a
   mandatory `principal_id`; all reads/writes pass through fail-closed
   Principal predicates.
4. Migrations are frozen-literal and round-trip tested from empty.
5. No PR is merged without review; merges are squash merges after gates pass.

## State update protocol

Update the YAML frontmatter of this brief at every material transition
(work-package start, PR open, merge, blocker, invalidation). Superseded
decisions move to the decision log with their replacement identified — they
are not silently rewritten.
