---
title: my-pa — Source Authority and Provenance Model
artifact_id: AUTH-MYPA-CANONICAL-002
artifact_type: Source authority and provenance
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

# Source Authority and Provenance Model

## Authority classes

`source_authoritative`, `canonical`, `canonical_observed`, `observed`, `derived`, `inferred`, `proposed`, `accepted`, `contradicted`, `stale`, `superseded`, `unavailable`, `denied`.

## Capture authority

A saved Capture is product-owned source evidence for exact user-committed text and canonical for capture/version identity and server receipt. It is not proof every described fact occurred.

## External source authority

External systems remain authoritative for exact observed records. my-pa retains source/version/reference, extraction provenance, coverage, and limitations. It does not overwrite source or treat normalized copy as source.

## Provenance envelope

As applicable:

- source ID/version/hash;
- direct/context/counterevidence spans or regions;
- original-offset mapping;
- method;
- rule/model/provider/version;
- schema/prompt/pipeline version;
- context manifest/retrieval inputs;
- processing time;
- policy/version;
- classification/destination;
- calibrated confidence;
- limitations;
- unresolved identities;
- contradictions/unavailable evidence;
- reviewer/authority;
- receipt/audit;
- supersession/invalidation lineage.

## Text spans

UTF-8 source; Unicode code-point offsets under versioned scheme; exclusive end; line/column where useful; quote hash; server validation; normalized text maps to original.

## Page regions

Exact source/page-version; coordinate system/page dimensions; polygon/bounding box; crop hash; rendering/pipeline; transcription candidate; original page display.

## Time authority

Server receipt time is authoritative for receipt only. Device time is observed. Occurred time may be explicit, inferred, accepted, or unknown.

## Version/revalidation

Source edit creates new version; attempts/proposals remain bound to prior version; accepted records supported by changed spans enter revalidation; reaffirmation/correction/supersession preserves history; removed source does not automatically delete accepted knowledge; search index rebuilds from eligible versions.

## Receipts

**Source receipt:** IDs, idempotency/request hash, source hash, receipt time, classification/policy, context result, job/outbox, correlation; no sensitive body copy.

**Promotion receipt:** proposal/source, target prior/result versions, authority, disposition, impact, policy, audit.

**Action receipt:** separately required for later external actions. Promotion receipt is never action authority.

## Visible trust labels

Original source; User-authored; Device-reported; System-received; Inferred; Proposed; Accepted; Corrected; Contradicted; Stale; Unavailable; Denied; Superseded; Revalidation required. A percentage alone is insufficient.

## Frontier-client provenance

Every frontier read binds authenticated actor, client profile, optional model metadata, application capability/schema version, purpose, policy decision/version, enrolled scope, source/object/version/fingerprint, extraction/index version, representation, coverage, freshness, limitations, safe references, request/correlation IDs, and audit event.

Client-generated summaries and proposed records are derived output. Retrieved content is data, not instruction authority. A model cannot use text found in a source to change grants, select a new principal, authorize an operator flag, expand scope, or create a write entitlement.

Managed documents are product-owned authority for the exact stored version and lifecycle transition. They remain derived/proposed for factual assertions unless evidence and Review confer stronger trust. Lineage links point to exact source, knowledge, or managed versions and optional spans/regions. Copy, restore, relocation, comment, client, and model provenance remains visible.

Version conflict fails explicitly. A source read with a changed fingerprint returns conflict/stale/unavailable according to the provider contract. A managed update with the wrong expected version creates no new version. Archived managed documents remain addressable through history/receipts but are excluded from active default views; restore creates a new current version.

No connector capability mutates source bytes, names, locations, permissions, or metadata. The absence of source mutation is a capability boundary, not a configurable flag.

## Apple source authority

Apple Mail, Calendar, and Contacts are external source-authoritative systems. my-pa records what was observed, when, through which bridge/account/bucket, under which provider revision and configuration, with what digest, range, coverage basis, and limitations. It does not claim ownership of the source object and does not overwrite it.

Required provenance includes bridge ID, source account and bucket IDs, provider-native opaque identity at the adapter boundary, source revision, authoritative source timestamps, observation time, admission time, configuration revision, sync run, checkpoint, adapter/contract version, content digest, and applicable exclusion or truncation markers.

Source absence is an observation, not automatic deletion. Mailbox moves, calendar cancellation, contact group removal, permission loss, and account disappearance append evidence and affect freshness; they do not erase prior versions. Physical purge, if ever supported, is a separate retention decision and must preserve required audit/provenance records.

Derived identities, relationship facts, commitments, tasks, decisions, and other assertions cite source versions or exact spans where available. Conflicting or ambiguous derivations remain proposals or enter Review. An imported source object never gains authority merely because it was observed through a trusted local bridge.
