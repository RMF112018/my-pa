---
title: my-pa — Open Operator Decisions
artifact_id: OPEN-DECISIONS-MYPA-CANONICAL-002
artifact_type: Open operator decisions
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z
version: 2.1
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-02
repository: RMF112018/my-pa
repository_head: 9096fa4fbe64ff1cdabc07e53a3e68c52efc8575
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.0
feature_package_id: MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086
feature_package_folder_id: 1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa
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

