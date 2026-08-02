---
title: my-pa — Source Authority and Provenance Model
artifact_id: AUTH-MYPA-CANONICAL-002
artifact_type: Source authority and provenance
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

