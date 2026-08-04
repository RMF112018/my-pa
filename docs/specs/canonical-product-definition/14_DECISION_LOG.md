---
title: my-pa — Canonical Reconciliation Decision Log
artifact_id: DECISIONS-MYPA-CANONICAL-002
artifact_type: Decision log
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-APPLE-MCC-MOSS-INTEGRATION-20260804T214700Z
version: 2.3
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-04
repository: RMF112018/my-pa
repository_head: 195fa54206996dddd6c6e0b6da0872781aa4f5f0
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.2
feature_package_id: MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087
feature_package_folder_id: 13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5
feature_package_manifest_id: 1gBPfHAtPClqFoT7skQJlpp9Sf2L72q_J
feature_package_publication_receipt_id: 1ATS9ONwZmA9Ar1_-sHaxCKcRUUwvoOqT
integration_control_folder_id: 1PLw2r7MmNXKi2pZxaIRiXTNVg-itiZ99
---

# Canonical Reconciliation Decision Log

| ID | Decision | Status |
|---|---|---|
| CR-D-001 | Category: evidence-grounded executive continuity system | Canonical recommendation |
| CR-D-002 | Retain Today→Pulse→Situation→Frame→Trace or Review→Close | Canonical |
| CR-D-003 | Reveal and Capture are global utilities, not destinations | Canonical |
| CR-D-004 | Keep five primary destinations | Canonical |
| CR-D-005 | Quick Note/Conversation Log are Capture modes | Canonical |
| CR-D-006 | Explicit Conversation Log may seed skeletal Conversation; Quick Note inference remains proposal | Canonical |
| CR-D-007 | RI is integrated domain; PRIE historical | Canonical |
| CR-D-008 | No relationship score/hidden sentiment/surveillance | Canonical |
| CR-D-009 | Capture text proves what user recorded, not all described facts | Canonical |
| CR-D-010 | Consequential promotion review-gated regardless confidence | Canonical |
| CR-D-011 | Offline MVP is encrypted append-only Capture | Recommended; security decisions open |
| CR-D-012 | PWA first; native later | Canonical recommendation |
| CR-D-013 | OS dictation only in MVP; audio separate | Canonical |
| CR-D-014 | GoodNotes is shared source provider, not silo | Canonical |
| CR-D-015 | MVP has one synthetic GoodNotes region proof, broader ingestion near-term | Recommendation |
| CR-D-016 | New versioned canonical package, not in-place revision | Publication decision |
| CR-D-017 | Prior vNext retained; superseded only as whole-product current definition | Publication decision |
| CR-D-018 | Active repository MCV remains prerequisite/objective | Authenticated implementation fact |
| CR-D-019 | Publication grants no implementation authority | Governance invariant |
| CR-D-020 | Rendered atlas valid for shell but incomplete for integrated flows | Evidence finding |
| CR-D-021 | Structured concepts close specification coverage, not rendered/usability completeness | Publication decision |
| CR-D-022 | External action remains separate after knowledge acceptance | Canonical |

Later operator decisions, canonical packages, ADRs, or owning feature revisions may invalidate entries. Record invalidation; never silently rewrite.

| MCP-CAN-001 | `my-pa` remains an evidence-grounded executive continuity system; MCP is a governed external capability surface. | ACCEPTED |
| MCP-CAN-002 | Preserve `Today -> Pulse -> Situation -> Frame -> Trace or Review -> Close`; Reveal and Capture remain persistent capabilities. | ACCEPTED |
| MCP-CAN-003 | One application capability plane serves first-party and frontier-client transports; no parallel MCP business logic. | ACCEPTED |
| MCP-CAN-004 | Source systems remain read-only; managed documents use a separate product-owned store and lifecycle. | ACCEPTED |
| MCP-CAN-005 | ADR-003 product-owned user-authored Capture records remain distinct from managed documents and source systems. | ACCEPTED |
| MCP-CAN-006 | Client/model requests have no inherent authority; centralized application policy governs actor, client, purpose, scope, classification, and side effect. | ACCEPTED |
| MCP-CAN-007 | Remote authorization uses OAuth authorization code + PKCE S256, standards discovery, exact token/resource validation, short lifetimes, revocation, edge plus origin validation, and separate write grants. | ACCEPTED PRODUCT DIRECTION; IMPLEMENTATION NOT AUTHORIZED |
| MCP-CAN-008 | Pursue Google Drive-like semantic capability parity, not Google-specific storage, permissions, sharing, or office-document imitation. | ACCEPTED |
| MCP-CAN-009 | MCP is not primary navigation; client controls, health, grants, denials, invocations, audit, and receipts belong under System. | ACCEPTED |
| MCP-CAN-010 | Managed artifacts appear in Library and enter Review according to content/lifecycle consequence. | ACCEPTED |
| MCP-CAN-011 | Client compatibility is unverified until exact profile conformance evidence exists for each intended client. | ACCEPTED |
| MCP-CAN-012 | The connector is post-MCV sequenced scope; documentation does not insert remote OAuth, live NAS, managed writes, or production ingress into the active repository objective. | ACCEPTED |
| MCP-CAN-013 | Lexical search remains initial; semantic/vector infrastructure stays benchmark-gated. | RETAINED |
| MCP-CAN-014 | No new numbered canonical artifact is required; the detailed feature package remains the owning subordinate feature definition. | ACCEPTED |

## Decisions added 2026-08-02 — Remote Quick Capture MCV integration

- `MYPA-RQC-D-001`: Remote Quick Capture is incorporated into the MCV as an extension of Quick Capture.
- `MYPA-RQC-D-002`: The initial remote transport is iOS Shortcut over authenticated HTTPS to `capture.create`.
- `MYPA-RQC-D-003`: The first-party PWA is the canonical cross-platform, offline-recovery, history, correction, and Review client.
- `MYPA-RQC-D-004`: Literal SMS, hosted messaging APIs, additional cellular service, and iMessage relay dependencies are excluded from the MCV baseline.
- `MYPA-RQC-D-005`: Capture success means durable source persistence and receipt before enrichment.
- `MYPA-RQC-D-006`: Message content is evidence data and grants no external-action, deletion, command, policy, or unrestricted-tool authority.
- `MYPA-RQC-D-007`: The governing feature package is `MYPA-REMOTE-QUICK-CAPTURE-FEATURE-PACKAGE-20260802-001`, folder `1lDSkTldgSkaRfJ3v9h-U10lCe-Lmwzsv`.
- `MYPA-RQC-D-008`: MCV product inclusion does not itself authorize repository mutation, credentials, ingress activation, deployment, production, or risk acceptance.
## Native Apple Reminders integration decisions

- `MYPA-NAR-D-001`: Native Apple Reminders Integration is included in the MCV as an opt-in Native Productivity Integration and External Execution Projection.
- `MYPA-NAR-D-002`: my-pa Task is authoritative; Apple Reminder is never the system of record.
- `MYPA-NAR-D-003`: The canonical implementation is a signed Swift macOS bridge using EventKit, authenticated loopback application services, and `SMAppService`.
- `MYPA-NAR-D-004`: The MCV uses one dedicated iCloud Reminders list and does not map lists to Projects or domains.
- `MYPA-NAR-D-005`: Synchronization is hybrid and field-level; no last-write-wins rule is allowed.
- `MYPA-NAR-D-006`: Apple completion may complete the mapped Task but does not automatically fulfill a Commitment or prove an external condition.
- `MYPA-NAR-D-007`: Existing reminders are not blanket-imported; unmanaged reminders remain untouched.
- `MYPA-NAR-D-008`: Native recurrence is deferred; my-pa projects one Task occurrence at a time.
- `MYPA-NAR-D-009`: External deletion never deletes the canonical Task and requires preservation/conflict handling.
- `MYPA-NAR-D-010`: AppleScript, Shortcut-based synchronization, direct Reminders database access, LaunchDaemon, MCP internal transport, and premature XPC are rejected for the MCV.
- `MYPA-NAR-D-011`: The governing feature package is `MYPA-NATIVE-APPLE-REMINDERS-INTEGRATION-FEATURE-PACKAGE-20260802-001`, folder `1qDE49KcJ8GSqFlljukYgGlq3eikeTnWq`.
- `MYPA-NAR-D-012`: Product inclusion does not authorize repository mutation, EventKit permission, credentials, code signing, deployment, production activation, or risk acceptance.

## Native Apple Personal Data Capture Bridge integration decisions

- `MYPA-NAPDCB-D-001`: The user-facing feature name is **Apple Mail, Calendar & Contacts**; “Apple MCC” and “Moss Capture” are legacy aliases only.
- `MYPA-NAPDCB-D-002`: The feature is included in the MCV as a conditional, first-class macOS source integration.
- `MYPA-NAPDCB-D-003`: Accounts and buckets are discovered and user-configurable; no personal account label is hard-coded as canonical scope.
- `MYPA-NAPDCB-D-004`: Typed account names are search/disambiguation aids and cannot activate unresolved scope.
- `MYPA-NAPDCB-D-005`: Pressing Begin Sync freezes one configuration revision, start instant, cutoff, calendar horizon, and exact bucket identity set.
- `MYPA-NAPDCB-D-006`: Mail baseline ends at the frozen cutoff; Calendar extends to cutoff plus 90 days; Contacts captures current selected collection membership without a historical cutoff.
- `MYPA-NAPDCB-D-007`: Baseline completion, reconciliation, durable checkpoint, and activation receipt are mandatory before each bucket watcher becomes authoritative.
- `MYPA-NAPDCB-D-008`: Apple data is source-authoritative and read-only; it is not Quick Capture, a managed-document write, or product-owned source content.
- `MYPA-NAPDCB-D-009`: The native host uses protected spool plus authenticated application admission and holds no direct PostgreSQL credentials.
- `MYPA-NAPDCB-D-010`: The legacy NAS/SCP/SQLite path, fixed plist configuration, hard-coded user paths, and precompiled unverified binaries are rejected as target architecture.
- `MYPA-NAPDCB-D-011`: Adding scope requires a new baseline; removing scope stops future reads but does not silently delete historical evidence; earlier start dates create idempotent backfills.
- `MYPA-NAPDCB-D-012`: Permission/source drift produces explicit degraded states and recovery; zero results cannot represent denied access.
- `MYPA-NAPDCB-D-013`: Mail implementation remains subject to a current feasibility gate; Calendar and Contacts may proceed independently if Mail is blocked.
- `MYPA-NAPDCB-D-014`: The governing feature package is `MYPA-NATIVE-APPLE-PERSONAL-DATA-CAPTURE-BRIDGE-FEATURE-PACKAGE-20260804-087`, folder `13jS8vmsWHvwQQqPksNlwW5r2whH8V8Z5`.
- `MYPA-NAPDCB-D-015`: Product inclusion and package publication grant no implementation, live-access, credential, source-mutation, deployment, activation, disclosure, destructive-retention, or risk-acceptance authority.
