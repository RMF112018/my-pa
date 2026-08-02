# Comprehensive Implementation Specification — my-pa Quick Capture

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## 1. Specification status and scope

This document is the integrated product and implementation specification for the proposed my-pa Quick Capture capability. It defines behavior, UX, authority, data, processing, contracts, platform sequencing, privacy, operations, testing, and acceptance criteria.

It is not implementation authority. It does not modify repository objectives, approve schema changes, grant source/model access, or authorize deployment.

## 2. Executive requirement

The user must be able to:

1. launch Quick Note or Conversation Log;
2. enter text in one unrestricted field;
3. save;
4. leave immediately after durable persistence;
5. allow backend processing to continue asynchronously.

No structured metadata is required before save.

## 3. Product purpose

Quick Capture solves the **human-origin evidence gap**. my-pa can ingest external evidence only after it exists. Many decisive facts first exist as memory after a phone call, meeting, observation, or informal exchange. Conventional forms delay or prevent preservation.

Quick Capture is:

- a pervasive feature;
- a product-owned ingestion source;
- a reusable platform capability.

It should be visible as a global action and as a Library collection, but not as a primary navigation destination.

## 4. Product principle

> **When the user is the source, my-pa preserves the evidence first and structures it afterward.**

This should become a formal product principle because it complements evidence-before-fluency and review-before-authority.

## 5. User-facing terminology

- Capability: Quick Capture
- Action: Capture
- Mode 1: Quick Note
- Mode 2: Conversation Log
- Collection: Captures
- Views: Notes, Conversations

The mode is a processing and UX hint, not a form schema.

## 6. Capture taxonomy

### 6.1 Modes

`quick_note` and `conversation_log`.

A general launcher defaults to Quick Note or infers mode after save. Dedicated shortcuts set an explicit hint. The user may switch modes in one compact control.

### 6.2 Inferred note subtypes

Observation, idea, reminder, decision note, field note, meeting note, status note, pasted text, shared content, dictated text, general/unknown.

### 6.3 Conversation channels

Phone, in person, video, formal meeting, informal exchange, text/chat, summarized email discussion, unknown.

Channel inference remains proposed unless explicitly supplied or deterministically known.

## 7. Minimum interaction contract

Required:

- non-empty text;
- explicit Save.

Optional:

- mode;
- deterministic context;
- sensitivity;
- dictation;
- processing preference;
- attachment later.

Save is explicit. Autosave protects drafts only.

After server or offline durable commit:

- show a concise acknowledgment;
- close the overlay/sheet by default;
- restore focus;
- continue processing.

## 8. Launch surfaces

### In-app

- global Capture button;
- Reveal/command palette;
- focused-app keyboard shortcut;
- contextual object actions;
- mobile/tablet navigation action.

### PWA/OS

- installed PWA;
- dedicated `/capture/note` and `/capture/conversation` routes;
- manifest shortcuts as progressive enhancement;
- Windows jump-list shortcuts/share target where supported;
- Apple Shortcut/deep-link setup guidance;
- native App Intents/widgets/controls/share extension deferred.

## 9. Performance budgets

- in-app warm launch to cursor: p75 ≤100 ms, p95 ≤250 ms;
- PWA cold launch to cursor: p75 ≤1.5 s, p95 ≤2.5 s;
- keypress-to-paint p95 ≤50 ms;
- local draft persistence p95 ≤100 ms after debounce;
- local/save acknowledgment p95 ≤200 ms;
- server durable acknowledgment p95 ≤750 ms on target local network;
- close after acknowledgment ≤100 ms;
- exact-text search eligibility p95 ≤10 s;
- ordinary extraction ≤30 s p95 for bounded input, excluding policy-blocked routes.

These are testable targets, not current-runtime claims.

## 10. Quick Note workflow

1. Launch.
2. Focus one field.
3. Type/paste/dictate through OS text input.
4. Draft autosaves locally.
5. Explicit Save.
6. Durable transaction creates source/version/receipt/job.
7. UI exits.
8. Worker extracts and proposes.
9. Original is indexed regardless of enrichment.
10. User can retrieve, edit by new version, link, review, or archive.

## 11. Conversation Log workflow

The user normally enters only a natural-language summary.

The pipeline evaluates:

- participants and organizations;
- Project/Situation;
- channel;
- occurred time, duration, location;
- summary/topics;
- commitments by each party;
- decisions;
- follow-ups/tasks;
- questions/risks/issues;
- relationship/project events;
- financial amounts;
- critical dates/milestones;
- documents/links;
- contradictions;
- unresolved identities.

An explicit Conversation Log may create a skeletal Conversation Event with unknown fields. Consequential extracted fields require review.

## 12. Conversation object decision

Conversation is a first-class specialized Event, not an alternate source.

- Capture remains source evidence.
- Conversation references exact source version.
- Explicit mode permits skeletal event creation.
- Inferred conversation from Quick Note remains proposed.
- Participant/entity ambiguity is represented, not guessed.
- Channel and occurred time expose authority/precision.

## 13. Source and authority

The original capture is source-authoritative for what the user recorded. It is not automatic proof that every described fact is true.

Authority classes:

- original source text: source-authoritative;
- server receipt: canonical observation;
- client time/device: observed;
- launch context: deterministic if validated;
- model/rule result: inferred/proposed;
- accepted assertion/event/work object: canonical within its lifecycle;
- summary/index: derived;
- user correction of source: new authoritative version;
- correction of extraction: canonical correction to derived state.

## 14. Versioning

- immutable source versions;
- current-version pointer;
- prior versions retained;
- text hash and source identity;
- edit creates reprocessing;
- accepted downstream records remain bound to old version and enter revalidation when support changes;
- extraction-only correction does not modify source.

## 15. Provenance and spans

Every proposal/accepted derived item points to exact source text.

Span fields:

- capture version;
- Unicode-code-point start/end, end exclusive;
- line/column;
- quoted text and hash;
- role: direct/context/counterevidence;
- processing-text mapping/version.

Normalized text is separate and traceable to original. A span mismatch quarantines the output.

## 16. Minimum logical data model

Required:

- Capture;
- CaptureVersion;
- CaptureContextLink;
- generic ProcessingJob/Attempt;
- ExtractionProposal;
- EvidenceSpan;
- Conversation;
- ConversationParticipant;
- common ReviewCase;
- common AuditEvent;
- Receipt;
- server idempotency record/result;
- client offline queue record.

Deferred:

- attachments;
- audio/transcript/diarization;
- training datasets;
- generalized graph links;
- multi-user sharing;
- dedicated vector store.

## 17. Save transaction

One PostgreSQL transaction:

1. authenticate/authorize;
2. validate bounded request;
3. resolve idempotency;
4. create capture/version;
5. validate launch context;
6. create receipt/audit;
7. enqueue job/outbox;
8. commit.

The response does not wait for AI. Identical idempotent replay returns the prior receipt; changed payload under the same key fails with conflict.

## 18. Processing pipeline

1. validate persisted source/version/policy;
2. conservative normalization with mapping;
3. language detection;
4. segmentation;
5. deterministic date/amount/identifier/URL extraction;
6. named entities;
7. identity/project/Situation resolution;
8. date/time normalization;
9. task/commitment/decision/risk/issue/question extraction;
10. conversation enrichment;
11. relationship/project event candidates;
12. contradiction detection;
13. related-record retrieval;
14. optional summary;
15. typed proposal/span persistence;
16. original/derived indexing;
17. review routing;
18. Today/Pulse eligibility.

Stages are idempotent, versioned, bounded, observable, and retryable where safe.

## 19. AI strategy

AI patterns:

- detect;
- resolve/rank;
- summarize;
- propose.

AI may not:

- persist source;
- grant authority;
- merge identity;
- accept commitments/decisions;
- decide cloud eligibility;
- execute actions;
- delete evidence.

Deterministic processing comes first. Local-model route is preferred for eligible private data. Cloud route is default-denied and requires explicit operator/policy approval. Captured text is untrusted data and has no tool authority.

## 20. Review policy

### Automatic

Source record/version, server receipt, authenticated author, explicit mode, validated launch context, original-text index, low-risk technical metadata.

### Nonblocking proposals

Topics, entities, projects, related records, note subtype, channel/time, generic task/follow-up, summary.

### Review-required

Commitments, decisions, critical dates, financial facts, identity merges, consequential ambiguous links, contradictions, sensitive relationship conclusions, deletion impacts, external actions.

### Prohibited automatic actions

Messages, calendar/contact/project-system changes, source mutation, risk acceptance, identity merge, recording, cloud disclosure, training, destructive deletion.

## 21. Offline-first model

Include in MVP.

- encrypted IndexedDB append-only queue;
- local IDs and idempotency;
- local confirmation only after commit;
- foreground/resume/online sync is correctness path;
- Background Sync is optional enhancement;
- server receipt confirms sync;
- changed idempotency payload conflicts;
- account switch/stale auth fail closed;
- local payload removed only after verified receipt;
- browser encryption limitations documented.

## 22. Privacy and sensitivity

Defaults:

- `private_local`;
- cloud false;
- training false;
- no lock-screen source content;
- no third-party analytics content;
- no automatic link following;
- no external action.

Model calls use explicit context manifests. Notifications are generic. Retention/hard deletion remain operator decisions.

## 23. Audio boundary

MVP:

- typed/pasted text;
- OS dictation into the field.

Not MVP:

- stored audio memo;
- call/meeting recording;
- speaker diarization;
- automatic interception;
- background recording.

Any recorded-audio work requires a separate product/legal/privacy specification and authorization.

## 24. Search and retrieval

Exact original-text search is mandatory.

Reveal distinguishes original source, Conversation, summary, accepted assertion, Task, Commitment, Decision, relationship/project event, and Review proposal.

Filters include kind, date, person, project, Situation, channel, authority, review, processing, and archive state. Semantic retrieval is deferred behind benchmark/policy.

## 25. Application placement

- global Capture;
- Library/Captures with Notes and Conversations views;
- capture/conversation detail;
- accepted links in Project/Relationship timelines;
- proposals in Review;
- operational failures in System;
- actionable accepted consequences in Today;
- Pulse only under strict accepted-consequence criteria.

## 26. Notifications

Default: in-app only.

System notifications only for:

- user-requested reminder;
- time-sensitive consequential review;
- sync conflict/failure requiring action;
- terminal processing failure needing action.

No routine “processing complete” spam. No content preview by default.

## 27. Accessibility

WCAG 2.2 AA target:

- labeled one-field experience;
- screen-reader announcements;
- complete keyboard flow;
- focus restoration;
- 44×44 touch targets where practical;
- reflow/large text;
- high contrast;
- reduced motion;
- safe-area support;
- status not color-only;
- errors preserve text;
- shortcut discoverability.

## 28. Reliability and operations

Operational visibility:

- accepted rate and save latency;
- pending/oldest age;
- stage latency/failure;
- retries/exhaustion;
- unresolved identities;
- review volume and dispositions;
- duplicate/idempotency conflicts;
- sync failures;
- index lag;
- model route/privacy denials;
- storage growth.

Capture source remains available even when processing fails.

## 29. Architecture

Reuse current modular monolith:

- PWA client;
- gateway/application;
- PostgreSQL;
- worker;
- model/policy adapters;
- common audit/receipt/review.

No new microservice, Redis, Celery, graph DB, dedicated vector DB, or native app is required for MVP.

SSE may notify/invalidate; polling fallback remains. Events contain safe identifiers/status only.

## 30. API surface

Proposed:

- create capture;
- create source version;
- fetch capture;
- list/search;
- processing status;
- retry;
- link/unlink context;
- review disposition;
- offline batch sync;
- create/resolve Conversation;
- retrieve evidence span.

All commands use idempotency, expected versions, strict schemas, policy, classification, provenance, and typed errors.

See file 18 for examples.

## 31. Platform matrix

### PWA MVP

- responsive app;
- installable Home Screen/desktop app;
- routes;
- focused keyboard shortcut;
- offline queue;
- Windows shortcuts/share target;
- generic push/badging only where supported and approved.

### Native-required

- system-wide hotkeys/menu bar/tray/floating window;
- Apple App Intents/Siri/Spotlight;
- WidgetKit Lock Screen/Control Center/Action button;
- Apple Share extension;
- stronger OS key storage;
- robust background lifecycle.

PWA features are progressive enhancements. Do not promise universal manifest shortcut/share/background behavior.

## 32. MVP scope

Include:

- two modes;
- one field;
- in-app/PWA;
- installability;
- immediate/offline persistence;
- versions;
- async processing;
- original search;
- core proposals/spans;
- Review;
- Library/detail/timeline integration;
- audit/receipts/retry/failure;
- accessibility/operations.

Exclude:

- recording;
- native wrappers;
- attachments;
- cloud default;
- external actions;
- automatic consequential canonical promotion.

## 33. Roadmap and dependencies

Current repository is not ready for this feature end to end.

Conditional sequence:

1. operator scope/priority/frontend decision;
2. capture domain/contracts;
3. persistence/create/read/version;
4. processing/search/proposals;
5. review/conversation;
6. PWA UI;
7. offline sync;
8. integration and operations;
9. measured platform wrapper/native evaluation.

Do not implement under the current objective without exact operator reprioritization.

## 34. Testing

Required:

- domain;
- contract;
- migration/database;
- concurrent idempotency;
- offline sync;
- extraction evaluation;
- identity/project resolution;
- commitment/decision adversarial cases;
- privacy/model routing;
- prompt injection;
- browser/PWA/device;
- accessibility;
- performance;
- crash/recovery;
- usability.

No live personal data.

## 35. Failure modes

Fail closed or explicitly partial for:

- local/server storage failure;
- authentication/policy denial;
- duplicate/idempotency conflict;
- stale context;
- unavailable model;
- invalid spans;
- identity ambiguity;
- source edit conflict;
- notification privacy;
- device loss;
- storage eviction;
- prompt injection;
- unsupported/oversized input;
- deletion impact.

## 36. Acceptance summary

The future implementation is acceptable only if:

- one-field save works without metadata;
- durable acknowledgment is non-AI-blocking;
- source text/version/provenance/spans are exact;
- offline replay is idempotent;
- consequential inferences require review;
- original text is searchable;
- private/cloud/training defaults are enforced;
- PWA/native boundaries are truthful;
- performance/accessibility budgets pass;
- System exposes failures/lag;
- repository exact-head implementation and independent review occur under separate authority.

## 37. Open operator decisions

Reserved to operator:

- final name/principle;
- priority and active objective;
- frontend hold;
- platforms;
- offline MVP;
- native wrapper;
- cloud/model policy;
- private default;
- retention/deletion;
- notifications;
- audio;
- attachments;
- editing;
- auto-link/review thresholds;
- external actions;
- Conversation skeletal behavior;
- device-local encryption posture.

## 38. Invalidations

Revisit this specification if any of these materially change:

- product navigation/mental model;
- authority/provenance vocabulary;
- repository architecture;
- common contract family;
- job/review/audit/receipt implementation;
- active objective/front-end authorization;
- platform capabilities;
- privacy/model policy;
- multi-user requirements;
- audio/recording scope.

## 39. Prohibitions

This specification does not authorize:

- repository change;
- branch/PR/merge;
- live personal data;
- source mutation;
- external-model disclosure;
- model training;
- recording;
- external actions;
- risk acceptance;
- deployment/production.
