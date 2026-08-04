---
title: my-pa — AI, Review, and Promotion Strategy
artifact_id: AI-REVIEW-MYPA-CANONICAL-002
artifact_type: AI and review strategy
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

## Apple-source processing and Review

Baseline and watcher admission are deterministic source-ingestion operations. They do not depend on successful model enrichment and SHALL complete or disclose limitations independently of downstream extraction.

After durable admission, deterministic and model-assisted processing may propose identity links, relationship facts, meeting context, commitments, tasks, decisions, and classifications. Every proposal SHALL retain source-version provenance and confidence/limitation context. Consequential records SHALL follow the existing Review and promotion policy; no mailbox, event, contact field, HTML content, attachment text, or prompt-like source content can instruct the application to bypass policy or invoke tools.

Routine duplicate observations, safe immutable version creation, and checkpoint advancement do not require human Review. Ambiguous identity resolution, conflicting canonical facts, sensitive derived claims, external actions, and material corrections do.

Private Apple source content is not automatically eligible for external model disclosure. Local processing is preferred; any external model path requires a separate eligibility policy, minimization, redaction, auditable client/model identity, and operator-authorized activation.
