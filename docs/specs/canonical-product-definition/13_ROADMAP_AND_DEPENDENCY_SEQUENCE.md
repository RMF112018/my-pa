---
title: my-pa — Roadmap and Dependency Sequence
artifact_id: ROADMAP-MYPA-CANONICAL-002
artifact_type: Product roadmap
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

# Roadmap and Dependency Sequence

## Rule

Repository truth governs executable sequencing. This roadmap is not authorization.

## R0 Complete active read-only MCV
Extraction/quarantine/coverage/version binding; PostgreSQL FTS/justified trigram; HTTP/MCP/CLI parity; gateway/worker; operations/recovery/synthetic E2E; capability/limitation disclosure. No personal sources, RI, live GoodNotes, or frontend without reprioritization.

## R1 Product contracts/frontend proof
Canonical object/state/error/span/region/Situation/Frame/Trace/Review/Receipt contracts; frontend ADR; synthetic design-system proof; five-destination shell; System disclosure.

## R2 Product-owned Capture source
Capture/Version schema; idempotent APIs; receipt/audit; original index; jobs; modes; global/contextual launch; responsive PWA; status/failure.

## R3 Offline Capture
Encryption/key review; IndexedDB append-only queue; stable IDs/request hashes; stale-auth/account isolation; foreground sync; conflict preservation; recovery/storage-pressure tests.

## R4 Proposal/Review/promotion
Deterministic/model extraction; spans; identities/unresolved; commitments/decisions/dates/financial/tasks/questions/risks/issues; Review/impact; transactional promotion; receipts; revalidation; no external action.

## R5 Relationship/Project continuity
Person/Organization identity; Relationship; Conversation/Interaction/Meeting; reciprocal commitments; private observations; Project/Relationship workspaces/timelines; briefing; Situations/Frame/Trace; Today/Pulse gates.

## R6 GoodNotes bounded integration
Synthetic adapter; notebook/page/version; render/region provenance; baseline OCR; Review/Assertion/search/timeline. Later exact live-root authorization, new/changed detection, broader OCR, comparison, backfill, learning.

## R7 Bounded AI maturity
Context manifests; selected-evidence synthesis; briefing; contradiction candidates; Pulse; evaluation/calibration; cost/latency/provenance; no autonomous action.

## R8 Platform extensions
Measured PWA use before Windows/macOS wrappers, global hotkeys/tray/menu, App Intents/widgets/share, stronger key stores, user-initiated audio memo.

## R9 Later governance models
Public research; delegate/multi-user; external actions; meeting recording; predictive follow-up; enterprise permissions.

## Dependencies

| Capability | Depends on |
|---|---|
| Today/Pulse | search, accepted records, coverage, policy |
| Reveal | registry, extraction, search, disclosure |
| Capture online | gateway, PostgreSQL, receipts, jobs |
| Capture offline | PWA, encryption/key policy, sync/idempotency |
| Review | proposals, spans, identities, transactions, receipts |
| Relationship workspace | identity, interactions, commitments, timelines |
| Project Trace | source links, events, accepted records, time |
| GoodNotes | provider, jobs, page provenance, Review |
| AI | model gateway, context manifest, policy, audit |
| Native | stable web contracts, measured demand |

## Stop conditions

Unvalidated repository drift; unavailable worktree/authorization; silent objective change; frontend hold not lifted; live personal data required; cloud assumed; unbounded key model; source mutation; unreviewable consequential promotion; receipt/audit cannot bind identity; operator-only decision treated as accepted.

## R10 Frontier NAS MCP Connector sequence

This sequence is dependency-driven and grants no implementation authority.

1. **Finish accepted read-only knowledge slice.** Complete repository WP-4 application services/transports and WP-5 operations/local candidate with synthetic data and exact-head review.
2. **Stabilize transport-neutral application contracts.** Prove HTTP/MCP/CLI equivalence, policy, disclosure, error, audit, and bounds without remote ingress.
3. **Establish canonical capability registry.** Provider-neutral semantic IDs/versions/schema hashes, side-effect classes, availability, client exposure profiles, and conformance tests.
4. **Implement managed-document persistence and lifecycle.** Separate managed root/store, immutable versions, idempotency, expected versions, archive/restore, backup/recovery, lineage, comments, and receipts. This remains outside current MCV until separately authorized.
5. **Implement application authorization and client-grant records.** Actor/client/purpose/scope/classification/side-effect grants, revocation, token references, policy versions, audit attribution, and kill switches.
6. **Add the thin remote MCP adapter.** No business logic; bounded Streamable HTTP mapping to existing use cases.
7. **Add standards-current OAuth.** Authorization code + PKCE S256, metadata/discovery, exact issuer/audience/resource/redirect validation, short tokens, supported refresh rotation, and edge/origin validation.
8. **Prove local synthetic conformance.** Positive, denial, unavailable, partial, limit, conflict, idempotency, redaction, injection, recovery, and non-vacuity evidence.
9. **Prove private ingress.** Outbound-only tunnel/private path, health/readiness, revocation, safe mode, rollback, and no unintended public surface.
10. **Test each intended frontier client independently.** Bind exact client/profile version, auth behavior, schema snapshots/hashes, tool limits, streaming/error behavior, refresh continuity, and negative cases.
11. **Enable bounded read profile.** One client, one actor, minimum scopes, exact synthetic or operator-authorized source roots, read kill switch, monitored canary.
12. **Enable bounded managed-write profile.** Only after managed-document backup/restore and conflict/idempotency evidence; separate grant, canary root, reversible operations, write kill switch.
13. **Operational readiness and operator activation.** Validate runbooks, backup/recovery, observability, retention, incident response, residual risks, identity provider, hostname, registrations, credentials, live roots, and explicit activation decision.

Parallelization may occur only where it does not weaken dependency evidence. A later repository commit, schema contract, client release, OAuth standard/profile change, or ingress topology change invalidates affected review and compatibility evidence.

## Remote Quick Capture sequence amendment

Remote Quick Capture is moved into the MCV delivery sequence rather than treated as a post-MCV enhancement. The bounded order is:

1. Finalize the shared Capture authority, `capture.create` contract, policy matrix, migrations, receipt, audit, and outbox semantics.
2. Implement the durable application service and asynchronous worker path using synthetic data.
3. Expose the capture-only authenticated HTTP endpoint on the existing gateway boundary.
4. Deliver and test the iOS Shortcut against a non-production endpoint and synthetic captures.
5. Deliver the PWA capture/history/retry surface and prove offline reconciliation.
6. Add multi-domain routing, unresolved identity, proportional Review, and exact Trace to original content.
7. Run adversarial, recovery, privacy, and idempotency acceptance tests and obtain independent exact-head review.
8. Seek separate operator activation decisions for credentials, ingress, deployment, and production.

Rich attachments, native App Intents, browser extension, Android share target, desktop helpers, voice/audio, SMS/iMessage relay experiments, and other self-hosted messaging protocols remain later stages.
## Native Apple Reminders implementation sequence

Native Reminders is sequenced after the accepted Task and Review lifecycle and after the local gateway/worker candidate. It must not be used to invent Task semantics ahead of those dependencies. Recommended package sequence:

1. **NAR-00 — canonical policy amendment:** external-action separation, reminders-specific grant, Task completion semantics.
2. **NAR-01 — target-Mac EventKit feasibility proof:** permission/revocation, dedicated list, create/update/readback, phone completion, store-change observation, identifier recovery, login registration, sleep/offline behavior.
3. **NAR-02 — provider-neutral domain and contracts:** integration profile, projection, command, observation, conflict, receipts.
4. **NAR-03 — backend application services:** bridge health, command lease/result, observation submit, projection read, conflict disposition.
5. **NAR-04 — signed native bridge:** EventKit adapter, Keychain credential, `SMAppService`, permission/list onboarding, health and safe mode.
6. **NAR-05 — one-way creation and updates:** supported fields, idempotency, readback, receipts.
7. **NAR-06 — completion roundtrip:** Apple completion to Task and my-pa completion to reminder, with Commitment boundary.
8. **NAR-07 — conflicts and recovery:** concurrent edits, deletion, list loss, identifier recovery, offline spool, loop suppression.
9. **NAR-08 — security and operational proof:** revocation, background disablement, privacy, recovery, runbook, independent exact-head review.

In the repository work-package sequence this is a later MCV package, recommended as `WP-11`, after the PWA capture/Review path. Product inclusion grants no implementation, signing, permission, credential, deployment, or production authority.

## WP-12 — Native Apple Personal Data Capture Bridge

This package assigns the next unallocated provisional product work package, **WP-12**, after the existing WP-10 and WP-11 sequence. The repository has merged WP-8 and WP-9, but this documentation revision does not authorize starting WP-10, WP-11, or WP-12 out of sequence.

Recommended WP-12 sequence:

1. **WP-12A — feasibility and exact repository plan:** authenticate current repository truth; prove current macOS Mail, EventKit, Contacts, TCC, sandbox, signing, and service-lifecycle options; submit one bounded plan.
2. **WP-12B — contracts and persistence:** provider-neutral account/bucket/sync/checkpoint contracts, migrations, idempotency, provenance, audit, receipts, and synthetic fixtures.
3. **WP-12C — application admission:** authenticated bridge registration, discovery, preflight, baseline, status, reconfiguration, and watcher-use cases; no helper database credentials.
4. **WP-12D — native host and adapters:** signed Swift host, Mail/Calendar/Contacts read-only adapters, bounded protected spool, safe retry, packaging skeleton.
5. **WP-12E — baseline and reconciliation:** frozen run windows, pagination, backfill, coverage disclosure, per-bucket checkpoints, crash recovery.
6. **WP-12F — watchers and rolling horizon:** overlap reads, checkpoint advancement, Calendar future-window maintenance, source/permission drift handling.
7. **WP-12G — frontend:** System source configuration, discovery, date/scope review, progress, remediation, pause/resume/backfill.
8. **WP-12H — security and validation:** privacy tests, prompt-injection containment, synthetic/dedicated-account canaries, signing/notarization, recovery, independent exact-head review.
9. **WP-12I — live activation decision:** exact accounts/buckets, permissions, retention, residual risk, and production activation remain operator-only.

A failed feasibility result may narrow or block the Mail adapter without invalidating Calendar and Contacts. No implementation plan may substitute the legacy NAS/SCP/SQLite architecture or fixed account labels for the canonical target.
