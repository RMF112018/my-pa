# Logical Data Model

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Modeling decision

Use the smallest model that preserves:

- original user-authored evidence;
- immutable versioning;
- exact provenance;
- asynchronous processing;
- extraction proposals;
- review and promotion;
- contextual links;
- conversation event semantics;
- offline idempotency;
- audit and receipts.

Do not create a separate table for every conceivable note subtype. `Capture` and `CaptureVersion` are the source model. A `Conversation` is a product event derived from or explicitly initiated by a Conversation Log.

## MVP aggregate

```text
Capture
 ├─ CaptureVersion [1..n]
 ├─ CaptureContextLink [0..n]
 ├─ ProcessingJob / Attempt [0..n]
 ├─ ExtractionProposal [0..n]
 │   └─ EvidenceSpan [1..n]
 ├─ ReviewCase [0..n]
 ├─ Conversation [0..1 current accepted/skeletal]
 ├─ AuditEvent [0..n]
 └─ Receipt [1..n]
```

## 1. Capture

Purpose: stable identity and lifecycle for one user-authored source record.

Recommended fields:

| Field | Type | Requirement |
|---|---|---|
| `capture_id` | opaque UUID-backed ID | Stable, nonsemantic |
| `capture_kind` | enum | `quick_note`, `conversation_log` |
| `origin` | enum | `in_app`, `pwa`, `shortcut`, `share_target`, `api`, `mcp`, later native |
| `owner_principal_id` | opaque ID | Required |
| `classification` | enum | Default `private_local` |
| `processing_policy` | enum | e.g. `local_only`, `eligible_route`, `no_ai` |
| `current_version_id` | FK | Required |
| `lifecycle_state` | enum | `active`, `archived`, `deletion_pending`, `deleted_tombstone` |
| `sync_state` | enum | server truth for client sync status |
| `created_at` | timestamptz | Server receipt time |
| `updated_at` | timestamptz | Product record mutation time |
| `archived_at` | timestamptz nullable | Explicit archive |
| `created_by_device_id` | opaque nullable | Policy-bounded |
| `mode_source` | enum | explicit route, switched by user, inferred, default |
| `correlation_id` | opaque | Audit/receipt correlation |

Constraints:

- current version belongs to same capture;
- a deleted/tombstoned capture cannot accept new processing;
- kind changes are auditable and may requeue processing;
- classification changes cannot silently widen processing eligibility.

## 2. CaptureVersion

Purpose: immutable user-authored source content.

| Field | Type | Requirement |
|---|---|---|
| `capture_version_id` | opaque ID | Stable |
| `capture_id` | FK | Required |
| `version_number` | integer | Monotonic per capture |
| `original_text` | text | Exact committed text |
| `text_sha256` | fixed hash | Exact UTF-8 bytes after defined transport decoding |
| `content_length_bytes` | integer | Bounded |
| `language_hint` | nullable | Caller hint, not authority |
| `client_created_at` | timestamptz nullable | Device-reported |
| `server_received_at` | timestamptz | Canonical receipt time |
| `client_timezone` | nullable | IANA identifier if supplied |
| `client_utc_offset_minutes` | nullable integer | Observed client metadata |
| `prior_version_id` | nullable FK | Supersession chain |
| `edit_reason` | nullable enum/text | Optional |
| `source_state` | enum | `current`, `superseded`, `withdrawn` |
| `created_by_principal_id` | ID | Required |
| `idempotency_key` | bounded string | Unique within principal/operation scope |

Rules:

- source text is immutable after insertion;
- edits create new versions;
- empty/whitespace-only versions are rejected;
- server preserves exact text; normalization is separate;
- prior versions remain retrievable under policy.

## 3. CaptureContextLink

Purpose: connect a capture to a Situation, Project, Relationship, Organization, meeting, Decision, Commitment, source, or other object.

Fields:

- `capture_context_link_id`;
- `capture_id`;
- `target_type`;
- `target_id`;
- `link_role` such as `launch_context`, `mentioned`, `about`, `resulted_in`, `supports`, `contradicts`;
- `authority_state`: `deterministic`, `user_confirmed`, `proposed`, `rejected`, `superseded`;
- `evidence_span_id` nullable;
- `confidence` nullable;
- `resolver_version` nullable;
- `created_at`, `accepted_at`, `superseded_at`;
- `review_case_id` nullable.

Unique active link per capture/target/role/authority where appropriate.

## 4. Processing jobs and attempts

Reuse the repository’s generic PostgreSQL-backed job/lease plane rather than creating Quick-Capture-specific queue infrastructure.

Job payload references:

- capture ID;
- capture version ID;
- pipeline version;
- stage;
- processing-policy snapshot;
- idempotency key;
- priority;
- retry budget.

Attempt records contain no raw text in logs. They reference input hashes and securely stored outputs.

## 5. ExtractionProposal

Purpose: typed, noncanonical candidate derived from a capture version.

Fields:

- `proposal_id`;
- `capture_version_id`;
- `proposal_type`;
- `payload_json` validated by proposal-type schema;
- `normalized_value`;
- `authority_state`: `proposed`, `accepted`, `corrected_accepted`, `rejected`, `deferred`, `superseded`, `invalidated`;
- `risk_class`: `low`, `moderate`, `high`, `critical`;
- `confidence_calibrated`;
- `method`: deterministic rule, resolver, local model, cloud model, hybrid;
- `method_version`, `schema_version`, `prompt_hash` nullable;
- `context_manifest_id` nullable;
- `created_at`;
- `review_case_id` nullable;
- `accepted_record_type/id` nullable;
- `invalidated_by_version_id` nullable.

Do not place arbitrary unvalidated model output directly into this table. Each proposal type has a bounded schema.

## 6. EvidenceSpan

Purpose: exact trace from a proposal/accepted record to source text.

Fields:

- `evidence_span_id`;
- `capture_version_id`;
- `start_offset`;
- `end_offset`;
- `offset_basis = unicode_code_point_v1`;
- `line_start`, `column_start`, `line_end`, `column_end`;
- `quoted_text`;
- `quoted_text_sha256`;
- `span_role`: `direct`, `context`, `counterevidence`;
- `processing_text_version_id` nullable;
- `mapping_version` nullable.

Validation re-derives the quoted text from the immutable source version. A mismatch quarantines the proposal.

## 7. ProcessingTextVersion

Optional but recommended when normalization materially changes offsets.

Fields:

- source capture version;
- normalized text;
- normalization version;
- normalized hash;
- reversible/traceable offset mapping to original;
- transformations applied.

For the MVP, normalization should be conservative: Unicode normalization policy, line-ending normalization for processing only, and no semantic rewriting.

## 8. Conversation

Purpose: first-class specialized Event representing an interaction.

Fields:

- `conversation_id`;
- `source_capture_id`;
- `source_capture_version_id`;
- `event_state`: `skeletal`, `proposed`, `accepted`, `superseded`, `archived`;
- `channel`: controlled enum plus `unknown`;
- `occurred_at_start/end` nullable;
- `occurred_at_precision` and `authority_state`;
- `recorded_at`;
- `duration_seconds` nullable;
- `location_text` nullable/proposed;
- `accepted_summary` nullable;
- `summary_authority_state`;
- `sensitivity`;
- `created_at`, `updated_at`;
- `superseded_by_id` nullable.

For an explicit Conversation Log, creation of a skeletal event is allowed with unknown channel/time/participants because the user explicitly selected the event class. Inferred conversations from Quick Notes remain proposals.

## 9. ConversationParticipant

Fields:

- `conversation_participant_id`;
- `conversation_id`;
- `entity_id` nullable;
- `unresolved_mention_text` nullable;
- `role`: participant, organizer, referenced person;
- `direction`: user, other, unknown;
- `authority_state`;
- `evidence_span_id`;
- `resolver_candidate_set_id` nullable;
- timestamps and review reference.

Identity merges/splits are not performed through this record. They use the governed identity workflow.

## 10. ConversationLink

Connects Conversation to:

- Situation;
- Project;
- Organization;
- Relationship;
- calendar meeting;
- document/source;
- downstream Commitment, Decision, Task, Risk, Issue, Question.

Use a generic typed link only if the repository already has a validated common link model. Otherwise use explicit bounded relations needed by the current work package.

## 11. ReviewCase, AuditEvent, Receipt

Reuse common product objects.

Quick Capture review cases must bind:

- exact capture/version;
- exact proposal and spans;
- expected current versions of affected records;
- risk and authority class;
- downstream impact;
- allowed dispositions;
- model/rule provenance.

Receipts must record the accepted transition without copying sensitive source text.

## 12. OfflineSyncRecord and IdempotencyRecord

Prefer not to create standalone server tables when existing request/idempotency and receipt records can satisfy the contract.

Client-side offline record contains:

- local capture/version IDs;
- encrypted payload;
- idempotency key;
- content hash;
- client timestamp/timezone;
- retry count;
- last error class;
- state;
- server receipt after sync.

Server uniqueness:

```text
UNIQUE(owner_principal_id, idempotency_key)
UNIQUE(capture_id, version_number)
```

The stored response/receipt must be replayable for identical requests. Reuse with a different request hash returns `idempotency_conflict`.

## MVP versus later model

### MVP required

- Capture
- CaptureVersion
- CaptureContextLink
- generic job/attempt integration
- ExtractionProposal
- EvidenceSpan
- Conversation
- ConversationParticipant
- common ReviewCase/AuditEvent/Receipt
- idempotency and client sync metadata

### Deferred until demonstrated

- CaptureAttachment
- dedicated CaptureProcessingAttempt if generic attempts are insufficient
- generalized polymorphic graph link store
- training-example tables
- audio/transcript/diarization objects
- multi-user sharing/access-control lists
- separate vector index
- capture templates
