---
title: my-pa — Risks and Rejected Patterns
artifact_id: RISKS-MYPA-CANONICAL-002
artifact_type: Risk register
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

# Risks and Rejected Patterns

| ID | Risk | Severity | Mitigation |
|---|---|---:|---|
| R-001 | dashboard/card-wall drift | High | five destinations, Situation/Frame |
| R-002 | Capture becomes form | High | one-field contract |
| R-003 | capture loss/offline false success | Critical | transactions/receipts/recovery |
| R-004 | AI manufactures commitments/decisions | Critical | spans/review |
| R-005 | wrong identity contaminates timelines | High | unresolved/candidates/reversible review |
| R-006 | user observation treated as fact | High | authorship-vs-truth distinction |
| R-007 | relationship surveillance/scoring | High | explicit prohibition |
| R-008 | sensitive cloud disclosure | Critical | cloud false/fail closed |
| R-009 | prompt injection | High | untrusted data/no tools/schema |
| R-010 | browser key compromise | High | key review/limits |
| R-011 | background sync assumed | High | foreground/resume required |
| R-012 | PWA marketed as native | High | platform matrix |
| R-013 | notification leak | High | generic previews |
| R-014 | source edit rewrites accepted state | Critical | versions/revalidation |
| R-015 | review overload | High | consequence routing/burden metrics |
| R-016 | deletion impact hidden | Critical | archive/impact/operator gate |
| R-017 | OCR treated as source truth | High | page/region authority |
| R-018 | live source assumed | Critical | exact authorization |
| R-019 | product MVP confused with MCV | Critical | sequencing disclosure |
| R-020 | frontend starts under hold | Critical | operator lift |
| R-021 | premature native/infrastructure sprawl | High | PWA/modular monolith first |
| R-022 | action follows knowledge acceptance | Critical | separate action receipt |
| R-023 | audio consent/legal exposure | Critical | dictation only/separate feature |
| R-024 | text-only dedupe collapses evidence | Medium | identity/idempotency |
| R-025 | visual completeness overstated | Medium | structural vs rendered disclosure |

## Rejected patterns

Chat-first; generic dashboard; destination per object; mandatory metadata; separate capture store; separate PRIE engine/store; CRM pipeline/ownership; hidden relationship score/sentiment; silent identity merge/contradiction resolution/promotion; source writes by default; broad offline mutation; automatic link fetching; cloud/training default; call interception/hidden recording; native first; premature microservices/graph/vector/Capture-specific queue; external execution from unreviewed evidence; deletion that erases provenance or failed evidence.

| MCP-R01 | MCP adapter becomes a parallel application/business-logic plane | Critical | Thin transport mapping; application use cases own policy, search, lifecycle, persistence, audit; non-vacuity review. |
| MCP-R02 | Broad default read-plus-write grants | Critical | Separate capability/side-effect grants; least privilege; write disabled by default; independent kill switches. |
| MCP-R03 | Model text, retrieved content, or caller fields treated as authority | Critical | Authenticated identity and centralized policy only; prompt-injection boundary; no caller principal/operator flags. |
| MCP-R04 | Source mutation or managed write targeting source storage | Critical | Source provider structurally read-only; separate managed root/store/credentials; negative tests. |
| MCP-R05 | Token/secret leakage | Critical | Hashed/external token references, redacted logs/errors/receipts, short lifetimes, rotation/revocation, secret scanning. |
| MCP-R06 | OAuth redirect, issuer, audience, resource, or PKCE weakness | Critical | Exact validation, PKCE S256, protected-resource metadata/discovery, registered redirects, negative conformance tests. |
| MCP-R07 | Excessive tool count or overlapping aliases | High | Compact capability registry, provider-neutral semantic IDs, measured client profiles; reject predecessor 185-tool catalog. |
| MCP-R08 | Provider/model-specific canonical tool names | Medium | Provider-neutral naming; client profile only at exposure/compatibility layer. |
| MCP-R09 | Unbounded NAS traversal, topology, or native-ID leakage | Critical | Enrolled roots, opaque IDs, bounded listing/pagination/bytes/depth/time, no paths/SQL/native keys. |
| MCP-R10 | Client compatibility assumed from protocol support | High | Exact client/version/profile conformance, schema hash, negative tests, status `unverified` until evidence. |
| MCP-R11 | Edge authentication treated as sufficient | Critical | Independent origin token/resource validation plus application policy for every invocation. |
| MCP-R12 | Model-accessible hard delete | Critical | Reversible archive by default; hard deletion operator-only and separately governed. |
| MCP-R13 | Hidden partial, stale, unsupported, quarantined, or unavailable evidence | High | Mandatory disclosure envelope and qualified model output; no false-complete state. |
| MCP-R14 | Public links, sharing, or permission administration added without authority model | High | Explicitly deferred; require real multi-user object/authorization model and separate review. |
| MCP-R15 | Local data treated as automatically cloud-eligible | Critical | Classification/client eligibility policy and explicit source enrollment; local is not cloud-approved by default. |
| MCP-R16 | Frontier client becomes the only usable product interface | High | First-party responsive app/PWA, Capture, Review, System, revocation, recovery, audit, and receipts remain required. |
| MCP-R17 | Managed documents mistaken for source-authoritative claims | High | Separate authority class, exact source lineage, Review/trust state, visible client/model provenance. |
| MCP-R18 | Documentation interpreted as implementation or activation authority | High | Repository truth precedence, explicit scope matrix, operator gates, no code/deployment changes in this revision. |

## Additional rejected patterns

- Porting the predecessor broker, aliases, authorization overlap, or tool catalog wholesale.
- Client-side policy decisions or optional parameters that reveal hidden admin capabilities.
- Last-write-wins managed updates, mutable history, or idempotency keys unbound from normalized requests.
- Direct filesystem, database, Cloudflare, OAuth-client, credential, shell, or host administration through product tools.
- Declaring ChatGPT, Claude, Grok, mobile clients, or production ingress supported without direct current evidence.

## Apple Mail, Calendar & Contacts risks

| ID | Risk | Severity | Control |
|---|---|---|---|
| NAPDCB-R01 | Display labels mistaken for stable account identity | High | Bind opaque provider identity to stable my-pa ID; labels remain metadata |
| NAPDCB-R02 | Watcher starts before baseline and creates gaps | Critical | Baseline/reconciliation/checkpoint/activation-receipt hard gate per bucket |
| NAPDCB-R03 | Permission denial appears as empty source | High | Typed permission states; stop checkpoint advancement; visible remediation |
| NAPDCB-R04 | Calendar recurrence/timezone errors | High | Preserve series/occurrence, timezone, all-day, cancellation, and overlap semantics |
| NAPDCB-R05 | Mail automation is brittle or over-privileged | High | Current feasibility spike, bounded read-only adapter, TCC/sandbox evidence, fail closed |
| NAPDCB-R06 | Contact duplication or lost group membership | Medium | Stable contact identity plus separate membership edges and reconciliation |
| NAPDCB-R07 | Native helper bypasses application policy | Critical | No DB credentials; authenticated application admission only; contract tests |
| NAPDCB-R08 | Spool leaks personal data | Critical | Protected directory, encryption where available, bounded retention, redacted logs, recovery tests |
| NAPDCB-R09 | Source content prompt-injects models/tools | Critical | Content treated as data; no implicit authority; proposal/Review gates; external models disabled by default |
| NAPDCB-R10 | Removal destroys historical evidence | High | Removal stops reads; purge is separate explicit retention action |
| NAPDCB-R11 | Dynamic “all future buckets” broadens scope silently | High | Separate explicit option; default exact frozen selection |
| NAPDCB-R12 | Legacy code/binaries are copied without provenance | High | Adapt behavior only; rebuild source, sign/notarize, synthetic tests; no opaque binary adoption |
| NAPDCB-R13 | Product documentation is mistaken for live-access authority | Critical | `NOT_GRANTED` throughout; exact operator gates for TCC, accounts, activation, and risk |

## Additional rejected patterns

- Hard-coded `BF-Personal`, `Moss`, `iCloud`, user home paths, or plist arguments as canonical configuration.
- Direct PostgreSQL access or credentials in the native helper.
- NAS SCP, NAS SQLite, dual-write, or migration-loader reuse as the normal ingestion path.
- Starting watchers merely because a process is installed or alive.
- Last-write-wins checkpoints, checkpoint advancement before admission, or silent retry exhaustion.
- Treating account disappearance, zero results, permission denial, and unsupported scope as equivalent.
- Blanket import of all accounts, all historical mail, all attachments, or all future buckets without explicit scope.
- Apple source mutation, unmanaged reminder adoption, Messages/Notes/Photos expansion, or cloud-hosted Mac operation in the MCV.
