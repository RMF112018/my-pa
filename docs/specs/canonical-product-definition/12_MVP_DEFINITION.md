---
title: my-pa — Integrated MVP Definition
artifact_id: MVP-MYPA-CANONICAL-002
artifact_type: MVP definition
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-NATIVE-REMINDERS-INTEGRATION-20260802T150100Z
version: 2.2
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-02
repository: RMF112018/my-pa
repository_head: f18e7e3ded45f82456fbfa722443b23a004de0b3
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.1
feature_package_id: MYPA-NATIVE-APPLE-REMINDERS-INTEGRATION-FEATURE-PACKAGE-20260802-001
feature_package_folder_id: 1qDE49KcJ8GSqFlljukYgGlq3eikeTnWq
---

# Integrated MVP Definition

## Objective

Prove one executive can move from attention to context, create/retrieve evidence, review consequential proposals, preserve project/relationship continuity, and close loops through a trustworthy non-chat interface. This is not the active repository MCV and is not implementation authority.

## Required capabilities

### Foundation
PostgreSQL authority; identities/contracts/policy/audit; source registry/read-only provider; jobs/leases/retries; extraction/quarantine/coverage; FTS; gateway/worker/CLI; receipts/capability disclosure.

### Shell
Today, Situations, Review, Library, System, Reveal, Capture, responsive PWA, accessibility.

### Continuity
Transparent Pulse; Project and Relationship Situations; Frame; basic Trace; saved views; evidence rail.

### Quick Capture
Quick Note/Conversation Log; one field; Save; draft protection; online receipt; immutable versions; original search; status/retry/archive; desktop/mobile/PWA/keyboard; encrypted append-only offline queue; idempotent sync/conflict.

### Processing/Review
Deterministic extraction and eligible model route; people/organization/project/date/task/commitment/decision/question/risk/issue; participants/channel/time; spans; unresolved identity; ReviewCase; accept/correct/reject/defer/unresolved; impact; receipt; no external action.

### Relationship Intelligence
Person/Organization; identity observations/candidates; Relationship workspace; interactions/conversations; reciprocal commitments; briefing; project links; private observations; contradictions/stale assertions; no score/public research default.

### Project continuity
Project workspace/timeline; commitments/decisions/tasks/risks/issues/questions; contextual Capture; source-backed Trace.

### GoodNotes proof
Synthetic read-only source; notebook/page/version; one source region; transcription/proposal; Review; accepted Assertion/KnowledgeRecord; Reveal/Trace; no live NAS/broad backfill.

### System
Sources/coverage; jobs/retries; search; model/policy; storage/database; offline; review backlog; failure/recovery; build/schema/capability.

## Exit scenarios

1. Today explains each Pulse item.
2. Project Situation/Frame shows source-backed obligations and issues.
3. Relationship Situation shows interactions/reciprocal obligations and supports Capture.
4. Quick Note online is durably saved and retrievable.
5. Conversation Log offline reloads, syncs once, and yields reviewable commitment.
6. Participant identity resolves or remains deliberately unresolved.
7. Decision is reviewed with exact spans/impact.
8. Project event traces source→proposal→review→acceptance→timeline.
9. Synthetic GoodNotes region becomes accepted knowledge.
10. Retryable processing failure is visible/recovered.
11. Degraded/unavailable coverage is disclosed.
12. All workflows work without chat.

## Nonfunctional exit

Source immutability; idempotency; transactional state; no source mutation; no content leakage; fail-closed policy/model routing; offline account isolation; WCAG 2.2 AA; performance; backup/recovery/failure tests; exact receipts/audit; synthetic fixtures; independent exact-head review before reliance.

## Near-term

Broader GoodNotes/OCR; dictionaries/aliases; selective notifications; text/URL sharing; Apple Shortcut guidance; bounded attachments; model evaluation; richer enrichment/briefing/timelines.

## Later

Native/wrapper surfaces; global hotkeys; App Intents/widgets/share; audio memo/on-device transcription; consent-based meeting recording; public research; delegate/multi-user; predictive follow-up; benchmarked semantic retrieval; personalized handwriting; external actions.

## Exclusions

Production activation; live personal sources in acceptance; default cloud; automatic recording/interception; relationship score; silent identity merge/promotion; source-system writes; broad offline mutation; enterprise claims.

## Connector scope decision

The complete remote connector is **not** part of the repository's active MCV by documentation alone. Canonical scope is divided as follows:

| Scope | Included decision |
|---|---|
| Active repository MCV | Complete read-only knowledge slice; transport-neutral application services; local loopback HTTP/MCP semantic equivalence; synthetic evidence; operations/local candidate. |
| Connector proof | Compact provider-neutral capability registry; thin MCP mapping; synthetic conformance; denial/limit/conflict/disclosure parity. May begin only when application contracts are stable and repository scope authorizes it. |
| Connector MVP — bounded remote read | Standards-current OAuth/PKCE/discovery; private ingress; edge plus origin validation; one verified client profile; bounded enrolled-source search/read; audit, revocation, safe mode, and read kill switch. Post-MCV and operator-enabled. |
| Managed-document MVP | Separate managed root/store; immutable versions; create/update/copy/relocate/archive/revisions/restore; comments; expected version; idempotency; backup/restore; write receipts. Post-MCV and separately planned. |
| Connector MVP — managed write | One explicitly write-enabled verified client profile over the proven managed-document service; separate write grant and kill switch; synthetic then canary rollout. |
| Multi-client compatibility | ChatGPT, Claude, and Grok are independently profiled and tested; no support claim based on protocol compatibility alone. |
| Production activation | Hostname, identity provider, OAuth registrations, credentials, live roots, ingress, retention, residual risk, and activation remain operator-only. |

Current repository truth at `main@9096fa4fbe64ff1cdabc07e53a3e68c52efc8575` shows source registry/enrollment, a read-only fixture provider, extraction/quarantine/coverage, and lexical search persistence exist, while application services, gateway/MCP composition, managed documents, live NAS access, remote OAuth, and production ingress do not. Product documentation creates no implementation authority.

## Connector MVP exclusions

No source mutation; no broad read-plus-write default; no raw SQL, shell, arbitrary path, host, mount, or credential administration; no Google Docs/Sheets/Slides or sharing/permissions imitation; no hard delete by ordinary clients; no unbounded NAS traversal; no live personal data during synthetic proof; no claim that a frontier client replaces the first-party product.

## Remote Quick Capture is included in the MCV

The MCV includes the complete minimal remote text-capture slice:

1. `capture.create` application service and versioned request/receipt contract.
2. Product-owned append-only Capture and CaptureVersion persistence in PostgreSQL.
3. Transactional audit, idempotency, receipt, and processing outbox/job creation.
4. Authenticated HTTPS endpoint with a capture-only device/client grant.
5. iOS Shortcut with one unrestricted text field, dictation, and explicit durable acknowledgment.
6. PWA capture surface and offline-recovery path.
7. Asynchronous classification, clause extraction, entity mentions, multi-domain proposals, policy evaluation, Review routing, and exact-original search.
8. Relationship Intelligence, project, task, commitment, decision, conversation, general-note, personal, and household routing where the corresponding domain contract is available; otherwise the proposal remains retained and unresolved.

The MCV excludes rich attachments beyond inert shared text/URL references, native iOS/Android applications, literal SMS, iMessage relays, hosted messaging providers, autonomous external actions, cloud model disclosure absent separate approval, and production activation.
## Native Apple Reminders addition to the MCV

The MCV includes an opt-in Native Apple Reminders execution projection after the Task, Review, transport, and local operational substrate is complete. It includes:

1. one dedicated writable iCloud Reminders list;
2. a signed Swift macOS bridge using EventKit and `SMAppService`;
3. reminders-specific client authentication and standing external-action policy;
4. accepted-Task eligibility and Review routing;
5. title, sanitized notes, opaque URL, due/start, priority, and completion mapping;
6. durable command, observation, conflict, audit, and receipt records;
7. idempotent create/update/complete/reopen behavior with readback;
8. iPhone/iPad/Apple Watch completion reconciliation;
9. identifier recovery and periodic reconciliation;
10. fail-closed permission, list-loss, bridge-offline, backend-offline, and iCloud-delay behavior.

The MCV excludes blanket import, intentional shared-list use, native recurrence-series synchronization, tags, attachments, subtasks, full-fidelity Reminders mirroring, direct Reminders database access, AppleScript mutation, automatic external deletion, automatic Commitment fulfillment, and any Calendar/Contacts/Notes/Mail/Messages mutation.
