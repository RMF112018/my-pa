---
title: my-pa — Canonical Workflow Inventory
artifact_id: WORKFLOWS-MYPA-CANONICAL-002
artifact_type: Workflow inventory
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

# Canonical Workflow Inventory

## WF-01 Daily orientation
Today → inspect Pulse reasons/coverage → enter Situation → Frame → Trace or Review → Close with outcome, remaining obligation, receipt, and next attention point.

## WF-02 Quick Note
Invoke Capture → Quick Note → one field → optional context → Save → `Saved` or `Saved on this device` → dismiss → asynchronous processing → original text immediately retrievable. Typed text remains recoverable on failure.

## WF-03 Conversation Log
Launch mode → one field → Save → preserve CaptureVersion → seed skeletal Conversation → propose participants/channel/time/project/topics/commitments/decisions/tasks/questions/risks/issues/events → identity resolution/unresolved → Review → accepted Project/Relationship timeline updates.

## WF-04 Contextual capture
Launch from Project, Relationship, Meeting, Commitment, Decision, or Situation. Valid exact context is deterministic and removable. Failed context does not block Capture. Inferred context is proposal-only.

## WF-05 Offline capture
Encrypt/store local transaction → acknowledge only after commit → sync pending → retry on foreground/resume/online/manual → reauthenticate as required → server verifies principal/ID/idempotency/hash/context → prior receipt for identical replay or atomic source/receipt/job → preserve conflicts. No background-sync guarantee or broad offline mutation.

## WF-06 Processing
Validate version/hash → normalize with offset map → deterministic extraction → eligible model route/context manifest → exact spans/candidates/confidence/limitations/contradictions → persist attempts/proposals → index original → route Review → surface partial/failure.

## WF-07 Commitment Review
Compare exact source and proposed direction/parties/action/due date → resolve or retain identity → preview Today/Relationship/Project impact → Accept/Correct/Reject/Defer/Unresolved → transactional receipt. No external action.

## WF-08 Decision Review
Inspect decision, participants, alternatives, date, evidence, contradictions/unavailable sources → correct/accept/reject/defer → create source-linked Decision and timeline receipt.

## WF-09 Identity resolution
Show mention/candidates/evidence/aliases/affiliations/counterevidence → select existing/create new/keep unresolved/propose merge or split/reject → preserve history/reversibility. Merge requires Review.

## WF-10 Relationship briefing
Show accepted identity/affiliation, interactions, reciprocal commitments, projects, private observations, contradictions, coverage, and contextual Capture. Label inferred content. No score.

## WF-11 Private observation
Persist as user-authored Observation → private/local/cloud-false/training-false → link after identity resolution → never silently become external fact/sensitive trait → consequential promotion through Review.

## WF-12 Project continuity
Project workspace/Situation → review commitments/decisions/risks/issues/questions/sources/timeline → contextual Capture → Trace across sources/captures → Review → close/carry obligations.

## WF-13 GoodNotes
Scan approved read-only synthetic/later authorized root → pair artifacts → compare hashes/fingerprints → queue new/changed/retryable pages → preserve page/region → extract/render/OCR under policy → proposals → Review beside source → accept shared Assertion/KnowledgeRecord → never mutate source.

## WF-14 Reveal
Query/scope/facets → bounded results with coverage/freshness/authority/completeness/unavailable sources → source preview/object/Situation/Trace → preserve context if creating Situation or Capture.

## WF-15 Trace
Select object/time range → reconstruct source events, captures, interactions, proposals, reviews, accepted records, contradictions, outcomes → distinguish timestamp types → expose gaps → navigate exact source.

## WF-16 Recovery
Detect source/job/index/model/storage/offline/review failure → safe error and scope → bounded retry/reprocess → preserve attempt → verify idempotency/receipt → never mark complete because attempted.

## WF-17 Source change
New source version → compare affected spans/regions → preserve prior support → mark affected accepted records revalidation-required → reaffirm/correct/supersede/withdraw through Review.

## WF-18 Closure
Record outcome, disposition, completed/remaining commitments, evidence, authority, receipt, and next attention date. Closing Situation never deletes history.

## WF-19 Frontier client searches enrolled evidence
Authenticate actor/client → discover granted capability and bounds → submit purpose/scope/query → application policy decision → bounded knowledge search → disclosure envelope states coverage/freshness/authority/limitations → client cites safe references → audit read without logging ordinary content.

## WF-20 Frontier client fetches exact support
Select opaque source/knowledge reference and expected version → policy and enrollment check → provider containment and version validation → return bounded representation plus provenance → conflict/partial/unavailable fails visibly rather than implying completeness.

## WF-21 Partial or unavailable evidence
Client request encounters unsupported, quarantined, stale, partial, policy-ineligible, or unavailable evidence → application returns uniform external error/result with safe disclosure → model must qualify output → System records internal reason class and trace → no retry loop or substituted source is invented.

## WF-22 Propose managed-document creation
Client requests product-owned artifact with destination, purpose, classification, lineage, and idempotency key → separate write-grant and policy decision → create under authorized managed root → immutable v1 + audit + receipt → route to Library and Review when consequence requires it.

## WF-23 Expected-version managed update
Client reads current version → requests update with expected version, reason, lineage, classification, and idempotency → policy decision → mismatch returns conflict → success creates new immutable version and receipt → prior version remains recoverable.

## WF-24 Prohibited source mutation
Client requests overwrite, rename, move, delete, upload, permission change, metadata mutation, or managed write targeting a source root → capability absent or policy denial → no provider mutation method is called → proportionate audit event records actor/client/capability/reason class without sensitive payload.

## WF-25 Authorization refresh or loss
Access token expires/revokes → client uses supported refresh continuity or reauthorization → origin independently revalidates issuer/audience/resource/client/grant → capability list is recalculated → failed refresh disables invocation and appears under System without broadening scope.

## WF-26 Ungranted capability
Client invokes a known but ungranted capability or side-effect class → uniform `insufficient_scope`/`policy_denied` response → capability remains absent from discovery → System shows grant gap and operator action, not an in-tool privilege escalation path.

## WF-27 Client-created content enters Review
Managed artifact or proposed record contains consequential commitments, decisions, identity changes, sensitive conclusions, or external-action implications → persist as product-owned proposal/managed evidence → create Review Case → human disposition promotes, rejects, edits, or requests evidence → receipt binds outcome.

## WF-28 Trace an MCP-originated read or write
System > Connected Clients/Activity → select invocation → inspect actor, client profile, capability/schema, purpose, scope, policy version/decision, source or managed target, disclosure, audit event, idempotency/expected version, mutation receipt, and limitations → follow lineage into Library, Review, Situation, project, or relationship context.

## Apple Mail, Calendar & Contacts workflows

### WF-29 — Connect and discover Apple sources

1. User opens System → Sources → Apple Mail, Calendar & Contacts.
2. Product verifies the native bridge and permissions independently.
3. Native adapters discover reachable accounts and buckets.
4. UI groups results by Mail, Calendar, and Contacts and discloses unavailable or unsupported scope.
5. User resolves any ambiguous account label to one exact discovered identity.

### WF-30 — Configure and begin initial synchronization

1. User selects accounts and exact mailboxes, calendars, and contact collections.
2. User selects an initial sync start date.
3. Product freezes a scope preview and performs immediate per-bucket preflight.
4. User confirms **Begin Sync**.
5. Product records the immutable cutoff and starts bounded baseline jobs.
6. UI shows item outcomes, retriable failures, exclusions, and estimated/known coverage without leaking content into logs.

### WF-31 — Reconcile and activate watchers

1. Each bucket independently reaches source exhaustion or terminal exclusions.
2. Product reconciles cursor continuity, admitted/duplicate/failure outcomes, spool residue, and checkpoint monotonicity.
3. A durable checkpoint and activation receipt are committed.
4. Only then does the bucket enter `watching`.
5. Account health remains partial if sibling buckets failed.

### WF-32 — Modify synchronized scope

- Adding an account or bucket repeats discovery, preflight, baseline, reconciliation, and watcher activation.
- Removing scope stops future reads and preserves prior evidence.
- Moving the start date earlier creates an idempotent backfill.
- Pausing retains checkpoints; resuming verifies identity and runs overlap reconciliation.

### WF-33 — Recover permission or source drift

1. A watcher detects permission denial, account disappearance, bucket remapping, checkpoint distrust, or bridge incompatibility.
2. Affected buckets stop advancing and enter a precise degraded state.
3. UI provides remediation or explicit remapping.
4. Recovery revalidates scope, reconciles overlap, and issues a new activation receipt.
5. Historical evidence is preserved throughout.
