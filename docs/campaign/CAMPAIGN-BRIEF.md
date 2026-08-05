---
campaign_id: CAMPAIGN-MYPA-MOSS-FULL-IMPLEMENTATION-20260805
product_package_id: MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008
product_package_version: "4.0"
product_package_sha256: 60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
main_head: 88e8d8193095afa8d903db08324a588a5786908b
main_tree: 418c466b020db1819b575f3206dbbdaf71db7f0a
active_goal_id: GOAL-MYPA-MOSS-MCV-MVP-V4
active_work_item_id: WP-01-R0A-IDENTITY-FOUNDATION
active_authorization_id: PROMPT-MYPA-MOSS-FULL-IMPLEMENTATION-MANAGER-20260805-001
lifecycle_state: WP01_IMPLEMENTED_PR_OPEN_AWAITING_REVIEW
completed_work_packages:
  - id: WP-00
    name: Campaign Formation and Ratification
    artifacts:
      - docs/campaign/RATIFICATION-MYPA-MOSS-V4-20260805.md
      - docs/campaign/REPOSITORY-TRUTH-REPORT-20260805.md
      - docs/campaign/WORK-PACKAGE-MAP.md
      - docs/campaign/CAMPAIGN-BRIEF.md
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
open_findings: []
blocked_actions:
  - production deployment or activation
  - live Entra app registration, credentials, or secret handling
  - live personal-data access
  - destructive Apple/native retirement
operator_only_decisions:
  - MCV completion date (AGENTS.md section 1, open ledger)
  - live tenant activation and app registration for R0A+
next_work_package: WP-02-R0-R1-FOUNDATION-FRONTEND-SHELL
required_sources:
  - /docs/campaign/WORK-PACKAGE-MAP.md
  - product package documents 02, 07, 09, 12, 13, 17, 18, 19
invalidations:
  - Any commit to main after 88e8d8193095afa8d903db08324a588a5786908b
    invalidates the head identity recorded here; re-authenticate before WP-02.
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
- **WP-01 (R0A Identity Foundation) implemented on
  `feat/wp-01-r0a-identity-foundation`:** `identity` schema migration
  (`user_accounts`, `principal_scope_grants`), token-claim validation with
  home-tenant rejection, idempotent Principal resolution, caller-supplied
  identity rejection, fail-closed Principal-context data-access guard, and
  cross-Principal isolation negative tests. PR open for review.

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
