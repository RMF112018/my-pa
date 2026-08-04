---
title: my-pa — Canonical Object and Domain Model
artifact_id: MODEL-MYPA-CANONICAL-002
artifact_type: Logical domain model
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

# Canonical Object and Domain Model

## Rules

Stable opaque IDs; immutable source versions; source support remains separate from domain state; projections are rebuildable; proposal/review/acceptance/correction/contradiction/supersession are explicit; time is multi-dimensional; unknown is represented.

## Definitions

- **Source:** evidence origin with type, ownership, access, classification, coverage, and mutation policy.
- **Capture:** product-owned Source envelope created through explicit authoring.
- **CaptureVersion:** immutable committed Capture text/hash. Drafts are not versions until Save.
- **Quick Note:** Capture mode for unrestricted memory/observation/idea/follow-up; not separate entity.
- **Conversation Log:** Capture mode indicating call/in-person/informal meeting/conversation; may seed skeletal Conversation.
- **Conversation:** specialized Interaction/Event aggregate with sources, participants/candidates, channel, occurred time, context, outcomes, and unknown fields.
- **Interaction:** meaningful exchange/contact; Conversation and Meeting are specialized forms.
- **Meeting:** scheduled/formally bounded Interaction/Event, distinct from notes/transcript/follow-up/decisions.
- **Person:** durable human identity with observations, aliases, affiliations, contact methods, source support, resolution history.
- **Organization:** durable company/team/agency identity with temporal affiliations and project relationships.
- **Relationship:** time/context-aware association and continuity domain; not a score.
- **Project:** durable work context with participants, sources, Situations, decisions, commitments, risks, issues, questions, timelines.
- **Situation:** purposeful operational context referencing one or more objects; does not own them.
- **Frame:** current/saved view of what matters, evidence, alternatives, obligations, uncertainty, and next authority point.
- **Trace:** derived source-linked temporal reconstruction; not source evidence.
- **Event:** dated occurrence/accepted record of occurrence with multiple time types.
- **Observation:** statement from source/user/system/reviewer; not automatically fact. Private notes are user Observations.
- **Assertion:** structured claim with subject/type/value, support, authority state, validity, contradiction, supersession.
- **Proposal:** candidate record/link/classification/transition before promotion.
- **Commitment:** obligation with direction, obligor, beneficiary/counterparty, action, due time, status, evidence.
- **Decision:** selected course with decision maker/participants, alternatives, basis, time, revisions, outcome, evidence.
- **Task:** action to perform; may implement a Commitment but does not replace it.
- **Risk:** potential adverse condition with evidence, owner, mitigation, status.
- **Issue:** current adverse condition requiring resolution.
- **OpenQuestion:** unresolved information requirement.
- **ReviewCase:** source + proposal + impact + authority + dispositions + receipt behavior.
- **Receipt:** immutable evidence of source acceptance or transition under exact identity/policy/authority/time.
- **AuditEvent:** append-oriented action, attempt, correction, denial, failure, or decision.
- **TimelineEntry:** derived projection of accepted or clearly labeled proposed state.
- **Briefing:** derived context package with coverage and authority.
- **Notification:** derived attention mechanism; not evidence.
- **PulseItem:** derived attention recommendation with reason, consequence, evidence, uncertainty, next step.
- **KnowledgeRecord:** accepted structured record linked to Assertions and exact source.

## Supporting records

SourceArtifact, SourceVersion, SourceSpan, SourceRegion, ProcessingJob, ProcessingAttempt, IdentityObservation, IdentityCandidateSet, Affiliation, RelationshipEvent, ContextLink, ConflictRecord, ContradictionSet, SupersessionLink, RevalidationRequirement, PolicyDecision, ContextManifest, SavedView.

## Capture/Conversation/Interaction

```text
Capture (source)
  └── CaptureVersion (exact text)
        ├── may seed/propose Conversation
        ├── supports Observations/Assertions/Proposals
        └── remains source-authoritative for user text

Interaction
  ├── Conversation
  ├── Meeting
  ├── Introduction
  └── other meaningful contact
```

Explicit Conversation Log can seed a skeletal Conversation. A Quick Note inferred to be conversational remains a proposal.

## Time model

client_created_at, server_received_at, recorded_at, occurred_at, source_observed_at, source_modified_at, processed_at, proposed_at, reviewed_at, accepted_at, effective_at, due_at, completed_at, indexed_at, superseded_at.

## State patterns

- Source: active, archived, superseded, unavailable, denied, quarantined.
- Proposal: proposed, needs_review, accepted, corrected_accepted, rejected, deferred, unresolved, superseded, invalidated.
- Assertion: proposed, accepted, contradicted, stale, superseded, withdrawn, revalidation_required.
- Identity: resolved, candidate, unresolved, merge_proposed, split_proposed, superseded.
- Commitment: proposed, accepted, active, at_risk, fulfilled, broken, withdrawn, superseded, unknown.
- Processing: waiting, running, partial, retryable_failure, permanent_failure, policy_denied, complete.

## Invariants

1. No domain record cites only normalized/model text when exact original exists.
2. No source edit overwrites prior version.
3. No identity merge occurs solely on confidence.
4. No accepted commitment/decision loses source support.
5. No timeline entry presents proposal as accepted.
6. No private Observation becomes public assertion automatically.
7. No processing failure hides Capture.
8. No external action follows internal acceptance automatically.
9. No text-only deduplication collapses distinct captures.
10. No deletion occurs without impact analysis and authority.

## Frontier access and managed-document records

Use transport-neutral domain names where possible. MCP-specific identifiers belong only where protocol/client attribution is materially required.

| Record | Purpose and invariant |
|---|---|
| `FrontierClientProfile` | Exact client/vendor/profile identity; supported transport/auth characteristics; tested capability/schema hashes; compatibility status; no authority by itself. |
| `AuthorizationGrant` | Actor + client + purpose + scopes + classifications + roots + side-effect classes + policy version + validity/revocation. Read and write grants are distinct. |
| `ClientSession` | Authenticated client session/token references, expiry, refresh/revocation state, resource/audience binding, last activity; no raw token storage. |
| `CapabilityDefinition` | Provider-neutral semantic ID/version, schemas/hashes, application use case, authorization and side-effect class, bounds, disclosure requirement, availability. |
| `CapabilityExposureProfile` | Client-specific tested subset and compatibility constraints. It filters exposure; it does not fork semantics. |
| `ManagedRoot` | Separate product-owned storage authority with protected configuration, classification/quota/retention/backup policy, and enablement state. Never a source root. |
| `ManagedFolder` | Product-owned hierarchy under one managed root; versioned lifecycle and collision rules. |
| `ManagedDocument` | Stable product identity, current immutable version pointer, classification, lifecycle, lineage, retention flags. |
| `ManagedDocumentVersion` | Immutable bytes/content reference, hash, size/type, actor/client/model/purpose, prior version, lineage, policy/audit binding. |
| `ManagedMutationReceipt` | Immutable safe transition evidence binding request, actor/client, capability/schema, target, prior/new state/version, policy, audit, time, limitations. |
| `Invocation` | Transport-neutral application invocation with optional MCP transport metadata; request/correlation, actor/client, purpose, capability, side effect, policy decision, result, disclosure, audit. |
| `DisclosureEnvelope` | Scope, coverage, freshness/version, authority, provenance, truncation, unavailable evidence, limitations, classification eligibility, safe references. |
| `IdempotencyRecord` | Principal/client/capability/version/normalized request/target/grant-policy/key binding and terminal result. Reuse with different input conflicts. |
| `ExpectedVersionCondition` | Explicit concurrency precondition for managed mutation and lifecycle transition. |
| `TokenReference` / `RevocationRecord` | Hashed or external token handle, issuer/resource/client bindings, expiry/rotation/revocation; never raw secret material. |

`AuditEvent` is extended with authenticated actor, client profile, session/token reference, capability/schema version, side-effect class, purpose, scope, policy version/decision, source or managed target, result, disclosure/receipt references, and safe internal denial class.

A `ManagedDocumentVersion` is canonical for stored artifact identity and content. Assertions within it retain derived/proposed/confirmed authority based on evidence and Review; document canonicality does not auto-promote claims.

## Remote Quick Capture object-model amendment

The MCV Capture model includes transport-neutral admission objects in addition to the existing immutable Capture and CaptureVersion chain:

- `CaptureSubmission`: request, correlation, idempotency, principal, registered client/device or relay, transport, capture method, trust state, transport message identifier, client timestamps, server receipt time, payload hash, admission result, CaptureVersion, and receipt.
- `RegisteredCaptureClient`: principal binding, device/client type, revocable credential reference, permitted capability, rate and size limits, creation, last-seen, and revocation state.
- `CaptureDeliveryAttempt`: bounded delivery attempts and safe error classification.
- `CaptureClassification` and `CaptureDomainAssignment`: versioned multi-label interpretation without relocating or overwriting the Capture.
- `CaptureEntityMention`: exact surface text, evidence span, entity type, unresolved/candidate/resolved state, and later resolution lineage.
- `CaptureCorrection`: source-text successor version, derived-value correction, identity correction, or routing correction, each with immutable lineage.

No transport-specific note store, SMS memory, PRIE memory database, second knowledge store, or model-specific memory is permitted.
## Native execution projection records

The canonical model adds provider-neutral execution projection records and one Apple-specific binding:

- `NativeIntegrationProfile`: principal, provider, bridge client/device, permission state, enabled/safe-mode state, policy, credential reference, health, last seen, and revocation.
- `ExternalActionGrant`: bounded principal/client/capability/destination/field/risk authorization, validity, revocation, and policy version.
- `ExecutionProjection`: stable projection identity linking one exact Task version or occurrence to one provider destination, managed field mask, lifecycle, policy, receipt, and supersession.
- `ExecutionProjectionCommand`: create/update/complete/reopen/withdraw command, expected versions, requested fields, idempotency, lease/attempts, safe errors, and result.
- `ExecutionProjectionObservation`: provider item identity, controlled-field snapshot and fingerprint, observed/received times, origin classification, and optional causal command.
- `ExecutionProjectionConflict`: conflicting fields, my-pa baseline/current values, provider baseline/current values, consequences, ReviewCase, disposition, and receipt.
- `NativeSyncCheckpoint`, `NativePermissionObservation`, `NativeBridgeRegistration`, and `ActionReceipt`: durable synchronization, permission, bridge, and execution evidence.
- `AppleReminderBinding`: reminder calendar identifier and fingerprint, calendar source/type/title, local item identifier, external identifier, opaque URL marker, creation/modification/completion observations, synchronized fingerprint, and identifier-recovery state.

Invariants:

1. A projection never replaces its Task.
2. Task acceptance never implies external-action authorization.
3. External deletion never deletes the Task.
4. Apple completion may complete a Task but never silently fulfills a Commitment.
5. No mapping depends on one Apple identifier alone.
6. No last-write-wins conflict resolution is permitted.
7. Provider observations are append-oriented evidence; reconciliation changes canonical state only through application policy.
8. Recurring Tasks project one occurrence at a time in the MCV.

## Apple source synchronization records

The feature adds the following canonical concepts without creating provider-specific domain leakage:

| Concept | Purpose |
|---|---|
| `NativeBridge` | One enrolled native macOS integration host and contract version |
| `SourceAccount` | Stable my-pa identity bound to one provider-native Apple account identity |
| `SourceBucket` | Smallest independently selectable/watchable mailbox, calendar, or contact collection |
| `SyncProfile` | Versioned user-selected scope, limits, and default date policy |
| `SyncRun` | Immutable baseline/backfill execution with frozen cutoff and range |
| `SourceCheckpoint` | Per-bucket durable monotonic resume point and overlap policy |
| `SourceObject` | Stable provider-neutral identity for a message, event/occurrence, contact, or membership |
| `SourceVersion` | Immutable observed source revision with provenance and digest |
| `WatcherRegistration` | Activation receipt binding a bucket, checkpoint, strategy, and freshness objective |

Provider-native opaque identifiers are stored at the infrastructure boundary and mapped to stable my-pa IDs. Display labels are mutable metadata, not identity.

Mail message identity and mailbox-membership edges are separate. Calendar series and occurrence identity are separate. Contact identity and group/container membership edges are separate. Source observations remain immutable; later changes append versions or membership observations.

`SyncRun` states include configured/preflight/running/partial/failed/reconciling/completed. Bucket lifecycle states include `discovered`, `selected`, `verification_failed`, `ready_for_initial_sync`, `initial_sync_running`, `initial_sync_partial`, `initial_sync_failed`, `reconciling`, `watcher_pending`, `watching`, `paused`, `permission_denied`, `account_unavailable`, `bucket_unavailable`, and `reconfiguration_required`.
