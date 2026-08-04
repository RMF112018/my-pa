---
title: my-pa — Open Operator Decisions
artifact_id: OPEN-DECISIONS-MYPA-CANONICAL-002
artifact_type: Open operator decisions
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

# Open Operator Decisions

| ID | Decision | Recommended default | Before |
|---|---|---|---|
| OP-01 | Public descriptor | Evidence-grounded executive continuity system | marketing |
| OP-02 | Final labels | Quick Capture capability; Capture action; Quick Note; Conversation Log; Relationships | UI freeze |
| OP-03 | Navigation | Keep five destinations | frontend freeze |
| OP-04 | Conversation behavior | Explicit Log creates skeletal record; Quick Note inference proposed | schema |
| OP-05 | Priority vs active MCV | Complete MCV then explicit transition | implementation |
| OP-06 | Frontend hold | Remains until expressly lifted | frontend work |
| OP-07 | GoodNotes MVP breadth | One synthetic region proof | MVP plan |
| OP-08 | Offline inclusion | Encrypted append-only queue | release scope |
| OP-09 | Browser key management | Define key storage/recovery/device/restricted policy | offline |
| OP-10 | Signed-out capture | Previously authenticated device may save encrypted; reauth to sync | offline |
| OP-11 | Private-note default | private_local/cloud false/training false/no preview | privacy |
| OP-12 | Cloud models | none by default; explicit provider/purpose/fields/terms/audit/revocation | cloud |
| OP-13 | Save without AI control | secondary control; policy default | Capture UI |
| OP-14 | Retention/deletion | archive default; define drafts/offline/active/audit/hard delete | release |
| OP-15 | Editing | immutable versions; material change revalidation | API |
| OP-16 | Auto-link | deterministic launch context only initially | extraction |
| OP-17 | Review thresholds | consequential classes always review | policy |
| OP-18 | Public research | disabled by default | RI enrichment |
| OP-19 | Notifications | in-app; generic system notifications only | release |
| OP-20 | Attachments | defer; text/URL share first | storage |
| OP-21 | Voice/audio | dictation only; audio separate; interception excluded | audio |
| OP-22 | Native wrappers | PWA first, measure need | platform |
| OP-23 | External actions | none in MVP; separate proposal/authority/receipt | action |
| OP-24 | Delegate/multi-user | separate product/security model | collaboration |
| OP-25 | Initial live sources | exact sources/roots/auth/canary separately authorized | live access |
| OP-26 | Private-note sharing | single-user private initially | multi-user |
| OP-27 | Independent gates | usability, privacy/security, offline/key, exact-head review | release |
| OP-28 | Semantic search | defer until benchmark | expansion |
| OP-29 | Training eligibility | false by default | learning |
| OP-30 | Hard delete/privacy erasure | exact target/impact/backup/audit/authority | destruction |

Operator-only: change objective; lift frontend hold; authorize implementation/live source/cloud/audio/public research/external actions; set retention; accept risk; merge/deploy/activate production. This package performs none.

## Frontier connector operator decisions

| ID | Decision | Recommended default | Before |
|---|---|---|---|
| MCP-OP-001 | Reprioritize connector implementation relative to the active repository objective | Finish current WP-4/WP-5 MCV sequence first | Any connector implementation work package |
| MCP-OP-002 | First production frontier client | Select only after synthetic profiles; prefer one minimum-authority read client | Remote canary planning |
| MCP-OP-003 | Production ingress: universal Cloudflare endpoint, OpenAI-specific private tunnel, or both | One universal private endpoint first; add client-specific path only for measured incompatibility | Ingress activation |
| MCP-OP-004 | Production identity/authorization provider | Select a standards-current provider that satisfies metadata, PKCE, resource binding, refresh rotation, revocation, audit, and operational recovery | OAuth implementation/activation |
| MCP-OP-005 | Initial write-enabled client profiles | None until managed-document service, backup/restore, conflict/idempotency, and write-canary evidence pass | Any remote write grant |
| MCP-OP-006 | Live NAS/personal-source enrollment | No live root by default; authorize exact provider/root/account/scope/classification separately | Live source access |
| MCP-OP-007 | Production hostname, OAuth registrations, credentials, and Cloudflare changes | Keep current synthetic/local settings; decide only with readiness package | Production configuration |
| MCP-OP-008 | Managed-document physical store, backup policy, RPO/RTO, retention, archive, and hard-delete policy | Separate managed root; reversible archive; no ordinary hard delete; define tested recovery before writes | Managed-document implementation/readiness |
| MCP-OP-009 | Production activation and residual-risk acceptance | No activation until independent review, client conformance, recovery, runbooks, and explicit operator decision | Production |

Routine tool names, schema details, pagination limits, implementation library choices, and test structure are not returned as operator decisions when repository evidence can resolve them during planning.
## Native Apple Reminders operator decisions

The operator has admitted the feature to the canonical MCV. The following activation and implementation-bound decisions remain open:

| ID | Decision | Default/recommendation | Blocks |
|---|---|---|---|
| NAR-OP-001 | Exact reminders-only credential and grant issuance | Capture-independent, revocable, destination- and field-bounded grant | Bridge activation |
| NAR-OP-002 | Exact dedicated iCloud list name/account | `my-pa` in the operator's primary iCloud Reminders account | Live list binding |
| NAR-OP-003 | Automatic undated reminder policy | Only explicit reminder intent or concrete personal/household action | Undated auto-projection |
| NAR-OP-004 | External title/due/priority edit policy | Auto-apply only uncontested low-risk changes; otherwise Review | Two-way edit activation |
| NAR-OP-005 | Task cancellation withdrawal behavior | Review before deleting an active Apple reminder | Automatic withdrawal |
| NAR-OP-006 | Minimum supported macOS and hardware | macOS 13+ subject to target-Mac EventKit proof | Packaging target |
| NAR-OP-007 | Code-signing/notarization identity and distribution | Signed/notarized local installation; no unsigned production bridge | Installation |
| NAR-OP-008 | EventKit permission grant and live reminder access | Grant only after synthetic feasibility and privacy proof | Live access |
| NAR-OP-009 | Production activation and residual-risk acceptance | No activation before independent exact-head review and recovery canary | Production |

Routine Swift types, EventKit wrapper structure, polling/debounce values, SQL schema details, and tests are implementation decisions unless evidence elevates them to operator risk.

## Native Apple Personal Data Capture Bridge operator decisions

| ID | Decision | Recommended default | Blocks |
|---|---|---|---|
| NAPDCB-OP-001 | Exact live Apple accounts and account labels | Select explicitly after discovery; no hard-coded defaults | Live scope |
| NAPDCB-OP-002 | Exact Mail mailboxes, Calendars, and Contact collections | Least-privilege explicit bucket selection; dynamic future inclusion off | Baseline and watchers |
| NAPDCB-OP-003 | Default/maximum initial sync start date and backfill policy | User-selected date with bounded operator-approved maximum history | Historical import |
| NAPDCB-OP-004 | Mail access mechanism if a sandbox-compatible option is infeasible | Permit only a bounded read-only Apple Events/Scripting Bridge design after current proof | Mail implementation |
| NAPDCB-OP-005 | Attachment/body limits and excluded content classes | Metadata and bounded text first; attachments opt-in and size/type bounded | Payload admission |
| NAPDCB-OP-006 | Retention, source removal, and physical purge policy | Stop future reads while retaining provenance; purge separately authorized | Destructive retention |
| NAPDCB-OP-007 | Code-signing/notarization identity and supported macOS range | Signed/notarized logged-in-user app; final floor set by target-Mac proof | Packaging |
| NAPDCB-OP-008 | TCC permissions and dedicated live-test accounts | Grant only after synthetic and dedicated non-personal account validation | Live canary |
| NAPDCB-OP-009 | External model eligibility for Apple source content | Disabled by default; separate minimized/redacted authorization | Model disclosure |
| NAPDCB-OP-010 | Production activation and residual-risk acceptance | Independent exact-head review, recovery canary, and explicit activation decision | Production |

Routine type names, SQL details, polling/debounce values, page sizes, retry intervals, and UI copy remain implementation decisions unless evidence elevates them to operator risk.
