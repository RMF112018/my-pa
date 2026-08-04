---
title: my-pa — Acceptance Criteria Crosswalk
artifact_id: ACCEPTANCE-MYPA-CANONICAL-002
artifact_type: Acceptance crosswalk
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

# Acceptance Criteria Crosswalk

| # | Criterion | Result |
|---:|---|---|
| 1 | Quick Capture package fully reviewed | PASS |
| 2 | Relationship Intelligence package fully reviewed | PASS |
| 3 | Synthesized frontend package fully reviewed | PASS |
| 4 | Repository identity/constraints authenticated | PASS WITH LIMITATION: head yes; tree/worktree/runtime unavailable |
| 5 | Thesis incorporates user-authored evidence and RI | PASS |
| 6 | Quick Capture integrated throughout | PASS |
| 7 | RI integrated, not separate CRM/engine | PASS |
| 8 | Description/spec agree | PASS |
| 9 | IA agrees with workflows/frontend | PASS |
| 10 | Object terminology coherent | PASS |
| 11 | Source authority/AI promotion explicit | PASS |
| 12 | MVP includes recommended Quick Capture | PASS |
| 13 | Offline bounded without broad mutation | PASS |
| 14 | Roadmap reflects repository truth | PASS |
| 15 | Visual coverage reviewed and gaps resolved/disclosed | PASS: structural; rendered update remains |
| 16 | Open operator decisions isolated | PASS |
| 17 | Existing Drive identities preserved appropriately | PASS: new version; sources retained |
| 18 | Source/revision manifests complete | PASS WITH LIMITATIONS |
| 19 | MY-PA index updated | `REGISTERED_AND_VERIFIED` |
| 20 | Publication/coordination receipts verified | `COMPLETE` |
| 21 | No implementation authority implied | PASS |
| 22 | Final visible response identifies IDs/status | bound to response/chat |

## Limitations

Repository tree SHA, local worktree/runtime/database, and final PR/check status were unavailable from the authenticated connector. Current rendered atlas was not regenerated. Independent usability/privacy/security review was not performed. Feature package publication is product intent, not implementation acceptance.

## Frontier connector cross-package mapping

| ID | Canonical requirement | Feature-package mapping | Repository/acceptance evidence required | Current result |
|---|---|---|---|---|
| MCP-AC-01 | Governed external surface, unchanged product category/loop | Feature description §§3, 8 | Product docs and UI IA show no primary MCP destination | PASS — documentation |
| MCP-AC-02 | Thin adapter, one capability plane | Spec invariants; architecture §§1–6 | Application/transport equivalence tests; handler non-vacuity | NOT IMPLEMENTED |
| MCP-AC-03 | Source read-only, no mutation | Feature/spec invariants; security §9 | Source port has no mutation; negative exploit tests | PARTIAL — fixture read boundary exists; remote connector absent |
| MCP-AC-04 | Separate managed store/lifecycle | Feature workflows; data model §§3–13 | Separate root/store, immutable versions, expected-version, idempotency, archive/restore, backup/recovery | NOT IMPLEMENTED |
| MCP-AC-05 | Central authorization, least privilege, separate write grant | Security §§2–7 | Actor/client/grant/policy records; denial tests; revocation; kill switches | NOT IMPLEMENTED |
| MCP-AC-06 | OAuth/PKCE/resource binding/edge+origin | Security §§3–7; deployment §§3–6 | Standards conformance and negative auth tests | NOT IMPLEMENTED |
| MCP-AC-07 | Evidence disclosure and provenance | Tool contracts §§2–6; source model | HTTP/MCP parity for scope, coverage, freshness, authority, limitations | PARTIAL — contracts/foundations exist; end-to-end absent |
| MCP-AC-08 | Model remains proposal generator | Security §8; canonical AI strategy | Injection, promotion, review, and no-implicit-authority tests | PRODUCT CONTRACT; IMPLEMENTATION PENDING |
| MCP-AC-09 | Client-specific compatibility evidence | Deployment §§12–16; acceptance §7 | Exact profile/version/schema hash, auth/stream/error/refresh/limits tests per client | UNVERIFIED FOR CHATGPT/CLAUDE/GROK |
| MCP-AC-10 | Operational readiness and recovery | Deployment §§7–10; acceptance gates | Health/readiness, safe mode, rollback, backup/restore, incident/runbook evidence | NOT IMPLEMENTED |
| MCP-AC-11 | MVP/post-MVP/operator gates separated | Feature spec §2/12; canonical MVP/roadmap | Repository plan retains current MCV boundary; operator activation records | PASS — documentation |
| MCP-AC-12 | Audit and receipts attributable to actor/client | Security §12; data model | Append-oriented audit and durable mutation receipts with redaction | PARTIAL DOMAIN FOUNDATION; MANAGED RECEIPTS ABSENT |

Documentation acceptance is not implementation acceptance. Later repository or client changes invalidate the affected rows until exact-identity evidence is refreshed.

## Native Apple Personal Data Capture Bridge crosswalk

| Canonical group | Feature criteria | Canonical requirement | Current state |
|---|---|---|---|
| Setup and discovery | NAPDCB-AC-001–008 | Bridge/permission checks, account discovery, stable identity, exact bucket selection, ambiguity handling | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Date and scope | NAPDCB-AC-009–014 | User-local start date, immutable cutoff, Mail range, Calendar +90-day overlap horizon, all current selected Contacts | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Baseline integrity | NAPDCB-AC-015–022 | Bounded paging/spool, immutable versions, idempotent replay, mailbox/occurrence/membership identity, terminal outcome disclosure | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Reconciliation and watchers | NAPDCB-AC-023–030 | Coverage reconciliation, durable per-bucket checkpoint, activation receipt, overlap cycle, rolling Calendar horizon | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Reconfiguration | NAPDCB-AC-031–036 | Add/remove/pause/resume/backfill/remap semantics without silent deletion | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Architecture | NAPDCB-AC-037–040 | Signed native host, protected spool, application-mediated admission, no helper DB credentials or NAS relay | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Privacy and security | NAPDCB-AC-041–044 | Least privilege, content/log redaction, read-only source boundary, prompt-injection/no-implicit-authority protection | PRODUCT CONTRACT; NOT IMPLEMENTED |
| Recovery and packaging | NAPDCB-AC-045–048 | Crash recovery, permission/source drift, signed/notarized packaging, exact-head validation and activation gates | PRODUCT CONTRACT; NOT IMPLEMENTED |

Repository status at this product revision: WP-8 and WP-9 are merged on `main@195fa54206996dddd6c6e0b6da0872781aa4f5f0`. This does not prove or partially implement the Apple source feature. Feature acceptance remains unsatisfied until a future exact-identity implementation package produces direct test, CI, packaging, and live-canary evidence.
