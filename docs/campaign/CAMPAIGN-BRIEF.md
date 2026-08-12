---
campaign_id: CAMPAIGN-MYPA-MOSS-FULL-IMPLEMENTATION-20260805
product_package_id: MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008
product_package_version: "4.0"
product_package_sha256: 60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
main_head: a2f5345629db6de568f46724214bab84158bc383
main_tree: 210a62fe78fe4707ab26bb773dca0d9b7840aca7
active_goal_id: GOAL-MYPA-MOSS-MCV-MVP-V4
active_work_item_id: WP-06-R5-RELATIONSHIP-CONTINUITY
active_authorization_id: PROMPT-MYPA-MOSS-FULL-IMPLEMENTATION-MANAGER-20260805-001
lifecycle_state: WP05_MERGED_WP06_ACTIVE
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
  - id: WP-03
    name: R2 Product-owned Capture — Principal-Partitioned Ownership
    merged_as: 646c2731a749173d2d162d882b39c6c6f6080157
    merge_method: "squash (PR 47, all three CI checks green)"
    post_merge_validation: >
      FAST tier 3018 passed (+15 new unit tests from 3003 baseline); web
      vitest 29 passed (+4 from 25 baseline). Branch
      feat/wp-03-r2-principal-capture deleted remotely and locally.
    artifacts:
      - docs/decisions/ADR-005-principal-partitioned-capture.md
      - migrations/versions/20260805_e7f3a9c2d514_partition_capture_by_principal.py
      - src/my_pa/domain/identity/binding.py (durable principal derivation)
      - tests/unit/test_principal_binding.py (6 tests)
      - tests/security/test_cross_principal_capture_isolation.py (4 tests)
      - tests/schema/test_capture_partition_migration.py (2 tests)
      - tests/capture/test_owner_is_the_partition.py (renamed, 2 tests)
      - web/src/lib/capture/idempotency.ts (per-principal admission store)
  - id: WP-05
    name: R4 Proposal / Review / Promotion — Principal-Partitioned
    merged_as: a2f5345629db6de568f46724214bab84158bc383
    merge_method: "squash (PR 48)"
    post_merge_validation: >
      FAST tier 3018 passed at merge baseline; ADR-006
      (PKL-MYPA-D-WP05-001) accepted. Branch
      feat/wp-05-r4-review-promotion deleted remotely and locally.
    artifacts:
      - docs/decisions/ADR-006-principal-partitioned-review-and-promotion.md
      - src/my_pa/domain/review/ (review cases, assertions, spans, receipts)
      - owner-derived principal_id on review records; principal-scoped
        reads and decisions; non-authoritative AI until human disposition
  - id: WP-06
    name: R5 Relationship / Project Continuity — Principal-Partitioned
    status: active
    branch: feat/wp-06-r5-relationship-continuity
    artifacts:
      - docs/decisions/ADR-007-principal-partitioned-relationship-and-project-continuity.md
      - migrations partitioning the relationship graph (add principal_id to
        17 relationship tables) and creating 7 R5 tables (situations, frames,
        traces, projects, project_situations, relationship_events, pulse_items)
      - src/my_pa/domain/situation/ and domain/relationship/event.py
      - src/my_pa/application/situation_service.py and situation repository
      - web/ situation board, projects, and principal-scoped relationship
        timeline surfaces (accepted-only continuity)
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
  - id: CD-07
    decision: >
      WP-06 relationship/project continuity is Principal-partitioned
      (ADR-007, PKL-MYPA-D-WP06-001): the relationship graph and the new
      Situation/Frame/Trace/Project/RelationshipEvent/PulseItem tables all
      carry a mandatory owner-derived principal_id with the opaque-identifier
      CHECK and a principal-first index; situation, project, and relationship
      timeline reads are principal-scoped, continuity surfaces expose only
      accepted evidence, and a foreign Principal's continuity is
      indistinguishable from a nonexistent one on every read path (MU-AC-05).
open_findings: []
blocked_actions:
  - production deployment or activation
  - live Entra app registration, credentials, or secret handling
  - live personal-data access
  - destructive Apple/native retirement
operator_only_decisions:
  - MCV completion date (AGENTS.md section 1, open ledger)
  - live tenant activation and app registration for R0A+
deferred_work_packages:
  - id: WP-04
    name: R3 Offline Capture
    reason: >
      WP-04 (offline capture queue) is deferred by operator decision. It is a
      leaf dependency not required by downstream work packages. WP-05 depends
      only on WP-03 (captures as input) and WP-01 (identity foundation), both
      complete.
next_work_package: WP-07-R6-MICROSOFT-365-READ-CONNECTOR
required_sources:
  - /docs/campaign/WORK-PACKAGE-MAP.md
  - product package documents 02, 07, 09, 12, 13, 17, 18, 19
invalidations:
  - Any commit to main after 646c2731a749173d2d162d882b39c6c6f6080157
    invalidates the head identity recorded here; re-authenticate before WP-05.
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
- **WP-03 (R2 Product-owned Capture) merged** as `646c273` (PR 47):
  durable local-operator principal (`domain/identity/binding.py`),
  ownership bound and verified at capture admission, per-Principal
  idempotency at revision `e7f3a9c2d514`, owner-scoped
  read/list/search/revise (foreign captures are nonexistent), and
  cross-Principal capture isolation negative tests (ADR-005,
  PKL-MYPA-D-WP03-001).
- **WP-05 (R4 Proposal / Review / Promotion) merged** as `a2f5345`
  (PR 48): owner-derived `principal_id` on review cases, assertions,
  spans, and receipts; principal-scoped reads and decisions; AI proposals
  remain non-authoritative until human disposition (ADR-006,
  PKL-MYPA-D-WP05-001).
- **WP-06 (R5 Relationship / Project Continuity) active** on
  `feat/wp-06-r5-relationship-continuity`: the relationship graph is
  partitioned by `principal_id` and seven new continuity tables
  (situations, frames, traces, projects, project_situations,
  relationship_events, pulse_items) are created, each carrying the
  mandatory opaque-identifier `principal_id` and a principal-first index;
  the Situation/Frame/Trace/Project domain, application service and
  repository, principal-scoped situation/project/timeline read surfaces,
  accepted-only continuity, and MU-AC-05 cross-Principal isolation
  negative tests (ADR-007, PKL-MYPA-D-WP06-001).

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
