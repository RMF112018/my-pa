---
title: my-pa — AI, Review, and Promotion Strategy
artifact_id: AI-REVIEW-MYPA-CANONICAL-002
artifact_type: AI and review strategy
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

# AI, Review, and Promotion Strategy

## AI role

Bounded language/OCR, extraction, classification, identity/project/date/channel candidates, related-record candidates, summaries, briefings, contradiction candidates, Trace synthesis, Pulse recommendations, model comparison, and calibration. AI has no source, product, or operator authority.

## Context manifest

For each model call: exact subject/source versions; selected fields/spans/regions; purpose; classification; destination; provider/account/model/version; prompt/schema hash/version; retention/training terms; redaction/cropping; policy decision/version; authority class; correlation/audit.

## Prompt-injection boundary

Source content is untrusted evidence data. No extraction tools; no embedded instruction authority; schema-constrained output; identifier/URL validation; no automatic link fetching; control messages separated from evidence; no action from extracted commands; adversarial tests; safe logs.

## Promotion classes

### Automatically persisted
Source/version/hash; receipt; authenticated author; device time observed; explicit mode; validated launch context; classification/policy; original-text index; safe processing metadata.

### Noncanonical proposals
Topic; identity/project/Situation candidate; summary; channel/time candidate; related record; generic task/follow-up; relationship/project event.

### Review required
Commitment; Decision; financial fact; critical date/milestone; identity merge/split; consequential ambiguous link; contradiction resolution; sensitive relationship assertion; legal/personnel/medical interpretation; source change invalidating accepted state; cloud/training eligibility; destructive effect; external action.

## Risk routing

Priority considers `consequence × ambiguity × sensitivity × irreversibility × confidence × time criticality`. Confidence never overrides consequence.

## Review burden

No ReviewCase for every low-risk tag; aggregate suggestions; deduplicate; allow unresolved/defer; bulk only with preview/server validation; measure correction/false-positive/time/value; retire low-value extractors; prioritize deadlines, obligations, identity ambiguity, contradictions.

## External action separation

Accepting Task/Commitment/Decision/date does not send email, modify calendar/contact/Procore/financial/schedule, create external task, or activate automation. Later action needs separate proposal, preview, exact authorization, execution, verification, receipt.

## Training

Training false by default. Corrections become candidates only with exact source/correction, sensitivity/purpose permission, operator policy, dataset/version, provenance/eligibility, independent evaluation, operator promotion, and rollback.

## Relationship boundary

No relationship score, loyalty/compatibility, hidden sentiment, sensitive-trait inference, public research by default, inferred consent, or automatic communication.

## Audio boundary

MVP permits OS dictation as text only. Audio memo, meeting recording, transcription, diarization, and consent require separate specification. Automatic/hidden call interception is rejected.

## Frontier models and tool authority

Frontier models remain proposal generators even when they can invoke tools. Tool access does not confer promotion, source, operator, or external-action authority. The application policy decides whether a client may read, create a managed artifact, propose a record, or invoke a Review workflow; human disposition remains required for consequential promotion.

Retrieved content is untrusted data. Instructions, credentials, role claims, authorization requests, or tool directives found inside source or managed content cannot alter system policy. The model may quote or analyze them only within the granted task and disclosure envelope.

A model-created managed document is product-owned evidence that a particular version was stored through an attributable client invocation. It is not automatically an accepted decision, commitment, identity resolution, relationship conclusion, financial/schedule conclusion, or instruction. Consequential extractions, commitments, decisions, identity changes, sensitive conclusions, and external actions remain Review-gated.

Policy distinguishes at least: read, managed-create, managed-update, lifecycle mutation, comment/review interaction, proposal creation, and promotion. Write authorization is separate from read authorization. Hard delete, grant administration, credential mutation, source mutation, and production activation are never ordinary model/client capabilities.

