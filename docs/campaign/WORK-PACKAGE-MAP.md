# Work Package Map — my-pa Moss MCV/MVP Implementation Campaign

> **Historical record — superseded.** This is the superseded Moss v4.0 campaign's work-package sequencing (WP-00 through WP-09), including the "WP-06 active / WP-07 Microsoft 365 Graph connector next" claim. It is superseded by `MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001`, whose WP-01 → WP-02 → WP-03 critical path (milestone MS-0) is the current sequence — see [`docs/campaign/CAMPAIGN-BRIEF.md`](CAMPAIGN-BRIEF.md). Microsoft Graph connectors described below remain off by default and are not the active personal-data ingestion path. Original text preserved below unchanged.

```yaml
map_id: WORK-PACKAGE-MAP-MYPA-MOSS-20260805
product_package: MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008 (v4.0)
sequencing_authority: 13_ROADMAP_AND_DEPENDENCY_SEQUENCE.md reconciled with repository truth
rule: >
  R0A (WP-01) blocks every user-scoped feature. No Capture, Review, RI,
  connector, or frontend user surface begins until WP-01 passes its
  acceptance criteria.
```

Global stop conditions applying to **every** work package:

- Any inability to prove zero cross-Principal leakage is a blocking defect — stop.
- Any step requiring live credentials, live personal data, production
  deployment, or destructive Apple/native retirement — stop and record an
  operator decision request.
- Migration that cannot round-trip from empty and back — stop.

---

## WP-00 — Campaign Formation and Ratification *(this work)*

- **Objective:** ratify v4.0 product package; publish repository truth report,
  work-package map, and campaign brief; establish the campaign branch and
  governance record.
- **Depends on:** repository access; extracted v4.0 package.
- **Acceptance criteria:** ratification record with package ID/version/SHA256;
  truth report with current head/tree, retain/rebuild/retire inventory, and
  gap analysis; this map; campaign brief with YAML state.
- **Stop conditions:** repository inaccessible; package hash mismatch.

## WP-01 — R0A Identity Foundation *(bundled with WP-00 in the first PR)*

- **Objective:** `UserAccount`/Principal registry (`principal_id` stable opaque
  UUID derived from Entra `(tid, oid)`); `principal_scope_grants`; synthetic
  token-claim validation (home-tenant check, required claims); rejection of
  caller-supplied principal identity; fail-closed Principal-context data-access
  guard; cross-Principal isolation negative tests. No live credentials.
- **Depends on:** WP-00.
- **Acceptance criteria:** MU-AC-01 … MU-AC-05 (see
  `19_ACCEPTANCE_CRITERIA_CROSSWALK.md`):
  - MU-AC-01 each Principal reads/writes only their own `principal_id` partition;
  - MU-AC-02 Principal derived solely from validated token claims; caller-supplied identity rejected;
  - MU-AC-03 non-Moss tenant `tid` rejected before domain access;
  - MU-AC-04 automated isolation test proves no cross-principal read before any live data;
  - MU-AC-05 cross-principal sharing/delegation remains absent (deferred).
  Plus: migration round-trips from empty; `resolve_or_create` is idempotent
  under retry and concurrency; strict mypy/ruff clean.
- **Stop conditions:** isolation unprovable; any path accepts caller-supplied
  `principal_id` as authority.

## WP-02 — R0/R1 Foundation + Frontend Shell

- **Objective:** MossAIc frontend ADR; Next.js App Router + TypeScript +
  Tailwind scaffold; MSAL wiring with **synthetic/mock tokens** (no tenant
  activation); sign-in/sign-out/revocation contracts; five-destination shell
  (Today, Situations, Review, Library, System) + Capture/Reveal affordances;
  canonical object/state/error/span contracts surfaced to the frontend;
  System disclosure view; all views Principal-scoped.
- **Depends on:** WP-01.
- **Acceptance criteria:** shell renders all five destinations responsively;
  auth boundary rejects unauthenticated and foreign-tenant synthetic tokens;
  frontend never originates principal identity; contract types shared or
  generated; accessibility checks on the shell; E2E smoke of sign-in →
  destination navigation → sign-out with synthetic identity.
- **Stop conditions:** any frontend path that would require live Entra
  registration to proceed; Principal identity minted client-side.

## WP-03 — R2 Product-owned Capture

- **Objective:** Capture/Version schema partitioned by `principal_id`;
  idempotent capture APIs; receipts and audit; original-text index; capture
  jobs; global/contextual capture launch in the shell; status/failure surfaces.
- **Depends on:** WP-01 (partition + guard), WP-02 (shell).
- **Acceptance criteria:** capture bound to the authenticated Principal at
  admission; duplicate submission with same idempotency key returns the
  original receipt; cross-Principal capture read/list/search negative tests
  pass; no capture text in audit events or receipts (QC-AC-041 discipline).
- **Stop conditions:** capture record persistable without a Principal;
  idempotency race demonstrable.

## WP-04 — R3 Offline Capture

- **Objective:** Principal-bound PWA offline queue: IndexedDB append-only
  queue, stable IDs/request hashes, encryption/key policy review, stale-auth
  and account-switch isolation, foreground sync, conflict preservation,
  recovery and storage-pressure behavior.
- **Depends on:** WP-03.
- **Acceptance criteria:** capture bound to the authenticated Principal **at
  capture time, never rebound**; account-switch test proves queued items never
  replay under a different Principal; stale-session items quarantined, not
  silently dropped or re-owned; sync idempotent under retry.
- **Stop conditions:** any queued item replayable under another Principal.

## WP-05 — R4 Proposal / Review / Promotion

- **Objective:** adapt the existing proposal/review/promotion substrate to
  Principal partitioning; deterministic + model extraction proposals with
  spans; Review cases and impact; transactional promotion; receipts;
  revalidation; correction/rejection/defer/supersession paths; no external
  action from Review.
- **Depends on:** WP-03 (captures as proposal input), WP-01.
- **Acceptance criteria:** promotion is transactional with receipt; AI output
  remains non-authoritative until review acceptance; cross-Principal review
  negative tests; supersession invalidates stale review state.
- **Stop conditions:** any silent promotion path; review acting across
  Principals.

## WP-06 — R5 Relationship / Project Continuity

- **Objective:** Person/Organization identity, Relationship, Conversation /
  Interaction / Meeting records, reciprocal commitments, private observations,
  Project/Relationship workspaces and timelines, briefing surfaces;
  Situations/Frame/Trace; Today/Pulse gates — all partitioned per Principal.
- **Depends on:** WP-05 (accepted records), WP-02 (destinations).
- **Acceptance criteria:** relationship records and timelines are
  Principal-scoped end to end; Today/Pulse read only accepted records;
  cross-Principal relationship negative tests pass.
- **Stop conditions:** shared identity records legible across Principals.

## WP-07 — R6 Microsoft 365 Read Connector

- **Objective:** delegated Graph **read** connectors (Outlook Mail, Calendar,
  Contacts, OneDrive) against synthetic/dedicated fixtures: discovery and
  bucket selection; frozen baseline; delta queries with per-bucket
  `@odata.deltaLink` checkpoints; change-notification webhooks and renewal;
  `410 Gone` re-baseline; throttling and bounded paging; per-Principal
  encrypted token cache keyed `(tid, oid)`; provenance into Review/search.
- **Depends on:** WP-01 (scope grants, token-cache keying), WP-05 (Review
  intake), WP-06 (relationship linkage).
- **Acceptance criteria:** connector conformance tests for baseline, delta
  replay, `410 Gone`, throttling, webhook renewal, duplicate notification,
  drift recovery; per-Principal token-cache isolation without real secrets;
  read-only: no Graph write path exists; scope loss moves buckets to
  `scope_insufficient` without deleting evidence.
- **Stop conditions:** any live-tenant or live-credential requirement; any
  app-only (non-delegated) permission.

## WP-08 — R7 Bounded AI

- **Objective:** context manifests; selected-evidence synthesis; briefing;
  contradiction candidates; Pulse; evaluation/calibration; cost/latency/
  provenance disclosure; prompt-injection containment.
- **Depends on:** WP-05 (Review boundary), WP-06/WP-07 (evidence surfaces).
- **Acceptance criteria:** AI may derive and propose but cannot promote
  consequential facts/decisions/commitments/tasks or take external actions;
  every synthesis carries provenance and coverage disclosure; injection
  containment tests pass.
- **Stop conditions:** any autonomous promotion or external action path.

## WP-09 — R8 Microsoft To-Do Write Projection

- **Objective:** bounded delegated `Tasks.ReadWrite` projection for **accepted**
  canonical Tasks: `ExternalTaskBinding`; idempotent create/update/complete/
  reopen with `@odata.etag` readback; completion reconciliation; separate
  write grant; kill switch; audit and receipts; synthetic fixtures then canary.
- **Depends on:** WP-05 (accepted Tasks), WP-07 (Graph plumbing, token cache).
- **Acceptance criteria:** only accepted Tasks project; separate write grant
  required and revocable; kill switch halts all writes; idempotency and etag
  conflict tests; no binding depends on a single provider identifier alone.
- **Stop conditions:** write attempted without the separate grant; kill switch
  inoperative.

---

## Dependency graph

```text
WP-00 ──► WP-01 ──► WP-02 ──► WP-03 ──► WP-04
                     │           │
                     │           └────► WP-05 ──► WP-06 ──► WP-07 ──► WP-08
                     │                                        │
                     └────────────────────────────────────────┴────► WP-09
```

Campaign completion additionally requires the integrated end-to-end evidence
listed in the manager prompt section 16 (two-Principal isolation across all
capabilities, synthetic sign-in boundary, capture online/offline
reconciliation, Review receipts, Reveal provenance, connector recovery
behavior, System health views, responsive frontend E2E, migrations/audit/
privacy controls, and an independent final-head audit). Live tenant
activation, credentials, and production deployment remain operator-only.
