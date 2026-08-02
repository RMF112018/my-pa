---
title: my-pa — Canonical Product Synthesis Specification
artifact_id: SPEC-MYPA-CANONICAL-PRODUCT-002
artifact_type: Canonical product specification
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

# my-pa — Canonical Product Synthesis Specification

## 1. Purpose and authority

This is the current canonical whole-product definition for my-pa. It reconciles the synthesized vNext frontend/product package, Quick Capture, Relationship Intelligence, GoodNotes, Workspace governance, and authenticated repository truth.

It defines product intent, UX contracts, domain boundaries, source-authority rules, MVP scope, acceptance expectations, and recommended sequencing. It does not authorize implementation, repository mutation, source access, cloud disclosure, audio recording, external action, merge, deployment, production activation, or risk acceptance.

Feature-specific packages remain authoritative where more detailed and not explicitly changed here.

## 2. Product category and mental model

Category: **evidence-grounded executive continuity system**.

Primary grammar:

`Today → Pulse → Situation → Frame → Trace or Review → Close`

Persistent capabilities:

- `Reveal`: retrieve and reconstruct evidence.
- `Capture`: preserve user-authored evidence.

Secondary evidence lifecycle:

`Observe/Capture → Preserve → Interpret → Propose → Review/Promote → Surface → Trace → Close`

Capture remains pervasive rather than a new top-level stage or destination.

## 3. Product principles

- Evidence before fluency.
- Attention before volume.
- Continuity before isolated transactions.
- Preserve user-authored evidence before structuring.
- Proposal before promotion.
- Consequence outranks confidence.
- Shared records support multiple lenses.
- Unresolved identity/time/context is valid state.
- Original evidence remains reachable.
- Corrections add history.
- Offline behavior is bounded.
- External action requires separate authority.
- Privacy defaults to local/private/cloud-false/training-false.
- Essential workflows work without chat.
- System limits and unavailable evidence are visible.
- Architecture follows measured need.

## 4. Information architecture

### 4.1 Primary destinations

**Today**
- Pulse;
- commitments due/at risk;
- decisions awaiting authority;
- relationship follow-ups;
- project exceptions;
- active Situations;
- explicit user focus;
- capture/review failures requiring action.

**Situations**
- purposeful contexts around projects, people, meetings, decisions, issues, risks, questions, or missions;
- Frame, Trace, evidence, commitments, decisions, tasks, questions, risks, and contextual Capture.

**Review**
- extraction;
- identity;
- commitments and decisions;
- financial/date interpretations;
- contradictions;
- source-version impact;
- duplicate/merge;
- model/privacy eligibility;
- later external-action proposals.

**Library**
- Captures;
- Notes;
- Conversations;
- Relationships;
- Organizations;
- Projects;
- Commitments;
- Decisions;
- Tasks;
- Knowledge;
- Sources;
- Saved Views.

**System**
- sources/enrollment;
- coverage;
- jobs/queues/retries;
- search/index;
- models/policy;
- database/storage;
- offline sync/conflicts;
- review backlog;
- failures/quarantine;
- capabilities/build/schema.

### 4.2 Persistent capabilities

Reveal is global retrieval. Capture is global evidence creation. Neither becomes a sixth destination.

### 4.3 Contextual surfaces

Project workspace/timeline; Relationship workspace/timeline; Conversation/Meeting detail; Commitment/Decision detail; Capture detail; GoodNotes review; evidence rail; provenance panel; impact preview; receipt panel.

## 5. Canonical record classes

### Source records
Source, SourceArtifact, SourceVersion, Capture, CaptureVersion, GoodNotes Notebook/Page/PageVersion, SourceSpan, SourceRegion, SourceReceipt.

### Domain records
Person, Organization, Relationship, Project, Conversation, Interaction, Meeting, Event, Observation, Assertion, Commitment, Decision, Task, Risk, Issue, OpenQuestion, KnowledgeRecord.

### Context/projection records
Situation, Frame, Trace, TimelineEntry, Briefing, PulseItem, Notification, SavedView, SearchIndexEntry.

### Governance records
Proposal, ReviewCase, PromotionReceipt, AuditEvent, PolicyDecision, ProcessingJob, ProcessingAttempt, ConflictRecord, SupersessionLink, RevalidationRequirement.

## 6. Quick Capture contract

### 6.1 Modes
Quick Note and Conversation Log are modes over one Capture persistence model.

### 6.2 Minimum interaction
- one unrestricted multiline field;
- explicit Save;
- no required structured metadata;
- optional deterministic/removable context;
- durable acknowledgment;
- dismissal after acknowledgment;
- asynchronous processing.

### 6.3 Online save
Atomically creates:
- Capture;
- CaptureVersion;
- exact source hash;
- source receipt;
- classification/processing policy;
- validated context links;
- processing job/outbox;
- audit correlation.

### 6.4 Offline save
Atomically creates:
- encrypted local Capture/CaptureVersion IDs;
- content hash;
- idempotency key;
- client-created time/timezone;
- optional launch context;
- sync state/error class.

### 6.5 Editing
Autosave protects drafts only. Explicit Save commits evidence. Editing a committed capture creates a new immutable version. Accepted downstream records supported by changed spans enter `revalidation_required`. No last-write-wins source text.

### 6.6 Processing states
draft, saved, saved_offline, waiting, processing, ready, needs_review, partial, failed_retryable, failed_permanent, syncing, synced, blocked_auth, policy_denied, conflict, archived, superseded.

## 7. Relationship Intelligence contract

### 7.1 Scope
Person/organization identity; identity observations/candidates; relationship context; interactions; conversations; meetings; introductions; reciprocal commitments; relationship events; private observations; briefing; timeline; project involvement; stale/contradictory assertion handling.

### 7.2 Exclusions
No sales pipeline, account ownership, relationship score, hidden sentiment, protected-trait inference, continuous surveillance, default public enrichment, automatic messaging, separate engine/store, or graph database.

### 7.3 Identity resolution
Support exact resolved identity, candidate set, unresolved identity, explicit new identity, duplicate candidate, merge/split proposal, aliases, temporal affiliation, resolution history, and reversible correction. Confidence alone cannot trigger consequential merge.

### 7.4 Reciprocal commitments
Preserve direction:
- user owes another party;
- another party owes user;
- organization/project direction where supported;
- unknown obligor/counterparty until resolved.

Commitment remains distinct from Task, Follow-up, Decision, and Notification.

## 8. Integrated workflows

### 8.1 Phone call or in-person conversation
1. Launch Conversation Log.
2. Enter one field and Save.
3. Preserve exact CaptureVersion and receipt.
4. Create skeletal Conversation because mode is explicit.
5. Propose participants, channel, occurred time, project/Situation, topics, commitments, decisions, tasks, questions, risks, issues, financial/date facts, and relationship events.
6. Resolve identity, retain candidates, or keep unresolved.
7. Route consequential items to Review with exact spans and impact.
8. Accepted records update Conversation, reciprocal commitments, Project/Relationship timelines, and relevant Situations.
9. Only accepted/deterministic eligible records feed Pulse.
10. Original capture remains linked.

### 8.2 Meeting follow-up
Contextual launch may deterministically link an exact Meeting version. Extracted attendees/outcomes remain proposed unless authoritative.

### 8.3 Observation about a person
Persist as user-authored private Observation. It may link after identity resolution but cannot silently become an external fact, sensitive trait, or relationship score.

### 8.4 Promise by another person
Propose reciprocal Commitment with that person as obligor. Identity, action, due date, and source spans remain reviewable.

### 8.5 Promise by user
Propose Commitment with user as obligor. Acceptance does not send email, modify calendar, or create external tasks.

### 8.6 Project financial/schedule discussion
Amounts, dates, milestones, and interpretations are high-consequence proposals. They never modify financial, schedule, Procore, or project systems.

### 8.7 Unresolved identity
Capture remains valid. Create unresolved mention/candidate set. Identity failure never blocks source persistence.

## 9. GoodNotes integration

### 9.1 Authority
PDF page is primary processing representation. `.goodnotes` is retained archival source. Page/PageVersion/Region locate evidence. Transcription is derived. Knowledge extraction is proposed. User correction becomes accepted representation through Review.

### 9.2 Processing
- detect new/materially changed pages;
- skip unchanged fingerprints;
- preserve failed/retryable attempts;
- render/segment;
- extract existing text first;
- run local-first OCR/vision where practical;
- compare candidates where justified;
- record model/pipeline/prompt/context;
- route high-risk/low-confidence items;
- promote accepted records into shared domains;
- never mutate source notebooks.

### 9.3 MVP boundary
Validate one bounded synthetic flow:

`source → page version → region → transcription/proposal → Review → accepted Assertion/KnowledgeRecord → Reveal/Trace`

Live NAS ingestion, historical backfill, personalized training, challenger promotion, native `.goodnotes` parsing, and whiteboard semantics remain gated.

## 10. Source authority matrix

| Element | Authority |
|---|---|
| External source bytes | source-authoritative within exact version |
| Original CaptureVersion text | source-authoritative for what user committed |
| Capture/version identity | product canonical |
| Server receipt time | canonical observed |
| Client/device time | observed |
| Deterministic launch mode/context | observed/deterministic after validation |
| User edit | new source-authoritative version |
| AI summary | derived/inferred |
| Participant/project/channel/time candidate | proposed unless deterministic |
| Commitment/decision/financial/date interpretation | proposed; review required |
| Accepted Assertion/KnowledgeRecord | canonical in product lifecycle, source-linked |
| TimelineEntry/PulseItem/Briefing | derived projection |
| Search index | rebuildable cache |
| Receipt/AuditEvent | canonical transition evidence |

## 11. Proposal and review policy

### Automatically persisted
Exact source/version/hash; authenticated author; server receipt; device time labeled observed; explicit mode; validated launch context; classification; processing policy; original-text indexing; safe technical metadata.

### Useful noncanonical proposals
Topic; likely identity/project/Situation; related records; channel/time candidate; summary; generic task/follow-up; relationship/project event candidate.

### Review required
Commitment; Decision; financial fact; critical date/milestone; identity merge/split; consequential ambiguous link; contradiction resolution; sensitive relationship promotion; legal/personnel/medical interpretation; source edit invalidating accepted state; cloud/training eligibility; destructive deletion; external action.

### ReviewCase contents
Plain-language transition; exact source/version; spans/regions/counterevidence; target/version; candidate identities; confidence; model/rule/schema/prompt; coverage/unavailable evidence; sensitivity/policy; downstream impact; allowed dispositions; receipt behavior.

Dispositions: Accept; Correct and Accept; Reject; Defer; Mark Unresolved; Reprocess under eligible route; Escalate operator decision.

## 12. Frontend contract

Recommended subject to ADR: React, TypeScript, Vite, type-safe router, generated client, server-state cache, SSE/polling, minimal UI-only state, same-origin protected deployment.

Backend remains policy/lifecycle/identity/mutation authority. Commands bind idempotency, exact subject/version, transition, evidence, authority, and correlation. Events invalidate and clients refetch.

Responsive:
- Desktop: rail, canvas, evidence/impact rail, modal/app-window Capture.
- Tablet: one canvas plus sheets/drawers.
- Mobile: task-focused navigation, full-height Capture, stacked detail/evidence drawer.
- PWA: installable shell, supported shortcuts, offline Capture queue, foreground sync.

WCAG 2.2 AA with keyboard, screen reader, focus restoration, 400% reflow, text scaling, touch targets, reduced motion, high contrast, and non-color status.

## 13. Privacy, security, and model routing

- no source text in third-party analytics, logs, URLs, notifications, or crash breadcrumbs;
- source/pasted/OCR text is untrusted data;
- no tools in extraction calls;
- schema-constrained output;
- explicit context manifest;
- cloud eligibility false by default;
- training eligibility false by default;
- provider/model allowlist and purpose binding;
- local availability is not disclosure consent;
- account switch cannot bind offline capture to wrong principal;
- source and managed writes remain separate;
- hard delete remains operator-gated.

## 14. Reveal, Trace, Pulse, and System

**Reveal** returns scope, filters, coverage, freshness, authority, completeness/truncation, unavailable sources, references, and warnings.

**Trace** distinguishes occurred, recorded, receipt, processing, proposal, acceptance, and indexing times. It is reconstruction, not source.

**Pulse** may use accepted records and visibly labeled low-risk proposals according to policy. Every item explains why it surfaced and its evidence/uncertainty.

**System** exposes capability availability, source containment, scans/coverage, jobs/retries, extraction/quarantine, index freshness, model routes, database/storage, offline sync/conflicts, review backlog, failures, and build/schema/policy versions.

## 15. Integrated MVP

Included:
- five-destination shell;
- Today/Pulse;
- Situations/Frame/Trace;
- Reveal/full-text search/coverage;
- Review/receipts;
- Library/System;
- Quick Note/Conversation Log;
- durable online persistence;
- encrypted append-only offline Capture;
- original-text indexing;
- asynchronous extraction;
- people/organization/project/date/task/commitment/decision/question/risk/issue proposals;
- exact spans;
- identity candidate/unresolved;
- Relationship workspace/timeline/briefing;
- reciprocal commitments;
- Project workspace/timeline;
- private relationship observations;
- one bounded synthetic GoodNotes region proof;
- accessibility/privacy/audit/recovery/performance tests.

Near-term:
broader GoodNotes/OCR; dictionaries/aliases; selective notifications; share target; Apple Shortcut guidance; model evaluation; bounded attachments; richer briefings/timelines.

Later:
native wrappers/global hotkeys/App Intents/widgets/share extensions; user-initiated audio memo; meeting recording; public research; delegate/multi-user; predictive follow-up; semantic retrieval after benchmark; personalized handwriting; external-action execution under separate authority.

Rejected for MVP:
mandatory metadata; automatic recording/interception; relationship score; automatic identity merge; silent consequential promotion; default cloud; automatic external action; broad offline mutation; native-first delivery; premature microservices/graph/vector infrastructure.

## 16. Repository truth and sequencing

Authenticated basis: `RMF112018/my-pa@b48b1b177046637297467e661dfb1da023d49bed`.

Implemented foundation includes PostgreSQL migration, common contracts, policy/audit/identity primitives, source registry, bounded enrollment, jobs/leases/retries, and hardened read-only provider.

Incomplete: extraction/quarantine/coverage; full-text search; HTTP/MCP product transport; complete worker behavior; personal-data services; Relationship Intelligence; GoodNotes ingestion; frontend/PWA; offline queue.

Therefore:
- active read-only MCV remains prerequisite;
- product publication does not change active objective;
- frontend hold remains until expressly lifted;
- implementation requires current-head/tree/worktree authorization and independent review;
- live personal sources require exact separate authorization.

## 17. Acceptance invariants

No later plan may weaken:
- exact source identity;
- immutable versions;
- spans/regions;
- unresolved identity;
- proposal/promotion separation;
- reciprocal commitment direction;
- append-only offline scope;
- privacy/model routing;
- external-action separation;
- no source mutation;
- visible coverage/unavailability;
- receipts/audit;
- accessibility;
- recovery/idempotency.

## 18. Invalidation

Invalidated for implementation planning by a later canonical package, material operator decision, repository architecture/objective change, conflicting owning feature contract, incomplete publication verification, or missing/invalid roundtrip receipt. Invalidation preserves the package but requires revalidation.

## 17. Frontier-client capability surface

The Frontier NAS MCP Connector is a transport integration into the canonical capability plane. It is not a new product destination, workflow stage, business-logic layer, or storage authority.

### 17.1 Actors and authority

- **Owning principal:** the human user whose authenticated identity and policy grants control access.
- **Frontier client:** ChatGPT, Claude, Grok, or another verified compatible client. It presents requests and model output but holds no inherent product authority.
- **Model:** a reasoning component operating within the client. Model text, tool selection, retrieved content, and prompt instructions do not grant authority.
- **Application policy service:** the sole decision point for actor, client, purpose, capability, scope, classification, side effect, and lifecycle authorization.
- **Source provider:** read-only capability over an enrolled source boundary.
- **Managed-document service:** separate product-owned write capability with immutable versions and reversible lifecycle.

### 17.2 Capability-plane rule

HTTP, first-party UI, CLI, worker, and MCP adapters must call the same transport-neutral application use cases. The MCP adapter may translate protocol schemas, client identity, session state, and errors. It must not independently own search semantics, synthesis, authorization, source enrollment, persistence, mutation, review transitions, audit semantics, or AI authority.

### 17.3 Product-surface relationship

- **Reveal:** frontier clients may invoke bounded evidence search/read and receive the canonical disclosure envelope.
- **Capture:** remains a first-party global capability and product-owned user-authored source record. MCP exposure of Capture or conversation commands is deferred until separately specified and granted.
- **Library:** shows managed documents and client-created product artifacts with lifecycle, provenance, versions, and lineage.
- **Review:** receives model/client proposals and consequential records under the same promotion rules as first-party AI.
- **System:** owns connected-client profiles, grants, scopes, sessions, capability exposure, health, revocation, safe mode, denials, invocations, audit, and receipts.
- **Situations, projects, relationships, knowledge, and sources:** remain canonical domain objects. A client may retrieve or propose against them only through existing application policy and lifecycle contracts.

## 18. Authentication, authorization, and privacy contract

Remote profiles require OAuth authorization-code flow with PKCE S256; protected-resource metadata; authorization-server or OIDC discovery; exact issuer, audience, resource, redirect, and token validation; short-lived access tokens; rotating refresh tokens where supported; and `offline_access` only where persistent client connectivity requires it. Pre-registration and Client ID Metadata Documents are preferred where supported; Dynamic Client Registration is a compatibility path, not the default authority model.

Token material is hashed or externally managed, expires, rotates, revokes, and is attributed to an authenticated actor and client. Edge authorization is defense in depth; the origin independently validates authorization and application policy. External denials are uniform while internal reason classes remain audit-visible. Caller-supplied principal IDs, operator flags, model text, or tool arguments never create authority. Write capability requires a separate grant from read capability.

Local data is not implicitly cloud-eligible. Every disclosure is evaluated for classification and client eligibility; logs exclude ordinary query/content payloads and secrets. The product may deny, redact, limit, or require first-party review even when a protocol-level token is valid.

## 19. Source and managed-document contract

Source systems remain source-authoritative and read-only by default. Reads bind source, object, exact version/fingerprint, enrollment scope, purpose, provenance, freshness, coverage, and limitations. Absolute paths, native IDs, database keys, credentials, and protected topology are not public capability output.

Managed documents are product-owned, stored under a separately designated managed root/store, and represented by stable document identity plus immutable versions. Creation and mutation bind authenticated actor/client, grant and policy version, capability/schema version, purpose, classification, source lineage, idempotency key, expected current version, audit event, and receipt. Version mismatch returns conflict; it never becomes last-write-wins. Archive is reversible by default; ordinary clients receive no hard-delete authority.

A managed document is canonical evidence of what the product stored and who/what created it. It is not automatic proof that every assertion in its content is true. Source lineage and review state remain visible.

## 20. Semantic capability families

The product may expose a compact provider-neutral surface for capability discovery; bounded source listing/metadata/status/fetch; evidence-aware knowledge search/read; recent records; representation export; managed folder/file create, update, copy, relocate, archive, revision listing, and restore; and product-owned comments/review interactions. Tool names and domain objects remain provider-neutral. Google-specific collaboration, permission administration, public links, and rich office-document emulation are excluded absent explicit product models and authorization.

## 21. Connector scope layers

| Layer | Canonical status |
|---|---|
| Read-only knowledge substrate and disclosure contracts | Repository prerequisite; partly implemented, not yet composed end to end |
| Transport-neutral application services and local HTTP/MCP equivalence | Active repository sequence through WP-4; synthetic/local only |
| Local operational candidate | Active repository sequence through WP-5 |
| Synthetic connector conformance and capability registry | Connector planning scope after transport contracts stabilize |
| Remote bounded read profile | Post-MCV; requires OAuth, private ingress, client-specific conformance, and operator enablement |
| Managed-document persistence and lifecycle | Post-MCV feature scope; repository currently defers managed documents |
| Remote managed-write profile | Later than managed-document proof; separate write grant and canary required |
| Live NAS source enrollment | Operator-gated by exact root/source/scope |
| ChatGPT, Claude, and Grok production profiles | Each independently tested and enabled; protocol support alone is insufficient |
| Production ingress/hostname/identity provider/credentials | Operator-only activation |

## 22. Acceptance invariants

1. No MCP handler contains independent business or persistence logic.
2. Equivalent application requests have equivalent policy, disclosure, audit, and result semantics across first-party and MCP transports.
3. Source mutation is structurally absent from the source-provider boundary.
4. Managed writes cannot address a source root or bypass expected-version/idempotency controls.
5. Capability discovery returns only currently available and granted capabilities, schemas, bounds, and side-effect classes.
6. Client compatibility is `unverified` until a profile binds exact tested schema/version/hash and conformance evidence.
7. Retrieved content is treated as data, not instruction authority.
8. Consequential proposals remain review-gated regardless of client or model.
9. Edge authorization never substitutes for origin validation and application policy.
10. Every consequential mutation produces an attributable audit event and durable receipt.

