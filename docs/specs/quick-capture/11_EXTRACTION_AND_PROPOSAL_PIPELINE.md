# Extraction and Proposal Pipeline

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Nonblocking invariant

The save transaction must not wait for language models, entity resolution, semantic retrieval, or search indexing.

```text
Client save
  → durable capture/version + receipt + job/outbox
  → immediate acknowledgment
  → asynchronous worker pipeline
```

## Save transaction

In one PostgreSQL transaction:

1. authenticate principal and purpose;
2. validate bounded text and request schema;
3. resolve idempotency key;
4. create or return Capture;
5. create immutable CaptureVersion;
6. validate deterministic launch context;
7. write capture receipt and redacted audit event;
8. enqueue processing through the existing PostgreSQL job/outbox plane;
9. commit.

If audit/receipt persistence required by policy fails, the server fails closed. The client may then preserve the item in the offline queue and report sync pending rather than falsely reporting server save.

## Pipeline stages

### P-01 Validate

- confirm capture/version current and accessible;
- verify source hash;
- apply size/character limits;
- load processing-policy snapshot;
- deny prohibited destinations.

### P-02 Normalize

- retain original text untouched;
- create conservative processing text;
- normalize line endings and permitted Unicode form;
- generate offset mapping;
- identify pasted markup/quoted source boundaries.

### P-03 Language detection

- deterministic/local detector first;
- allow `unknown`;
- do not translate source text silently.

### P-04 Segmentation

- paragraphs;
- sentences;
- bullets;
- quoted/pasted regions;
- speaker-like clauses where present.

### P-05 Deterministic extraction

- dates and times;
- currency/amount patterns;
- project/document identifiers;
- known aliases;
- URLs;
- phone/email-like strings where policy permits;
- explicit task/commitment language cues.

Deterministic matches still require authority classification and spans.

### P-06 Named-entity extraction

Propose:

- people;
- organizations;
- projects;
- locations;
- documents;
- topics.

The extractor returns unresolved mentions separately from resolved identities.

### P-07 Identity and context resolution

Candidate ranking may use:

- exact aliases;
- known contact/entity identifiers;
- current Situation/Project/Relationship;
- recent calendar participants;
- project teams;
- organization membership;
- explicit document/project codes;
- chronology.

No false certainty: candidate sets and ambiguity remain visible. Identity merge is never automatic.

### P-08 Date/time normalization

- preserve raw phrase;
- resolve relative dates using client/server time context;
- record timezone and precision;
- identify ambiguity;
- distinguish recorded time from occurred time and due time.

### P-09 Work-object extraction

Propose:

- Task;
- Commitment;
- Decision;
- Follow-up;
- Open Question;
- Risk;
- Issue.

Each proposal includes actor/obligor, counterparty, action, due condition, status, direct spans, and missing required fields.

### P-10 Conversation enrichment

For Conversation Log:

- participants;
- channel;
- occurred time/duration/location;
- summary;
- topics;
- reciprocal commitments;
- decisions;
- relationship/project events.

Unknown values remain unknown.

### P-11 Relationship and project events

Generate noncanonical event candidates such as:

- interaction occurred;
- preference/concern expressed;
- stakeholder change;
- project risk raised;
- schedule milestone discussed;
- financial exposure mentioned.

Sensitive relationship conclusions require review and may be prohibited entirely.

### P-12 Contradiction detection

Compare proposed assertions with:

- accepted assertions;
- current project/relationship records;
- prior conversations;
- commitments/decisions;
- financial and schedule records where authorized.

The output is a contradiction candidate with both sides and source references, not an automatic resolution.

### P-13 Related-record retrieval

Use PostgreSQL lexical search first. Semantic retrieval is permitted only after benchmark enablement and policy.

Retrieval scope is explicit and recorded. Pasted/captured text cannot expand tool authority.

### P-14 Summary generation

A summary is optional, derived, source-linked, and clearly labeled. It must not omit uncertainty in a way that changes meaning. The original text remains primary.

### P-15 Proposal persistence

Persist typed proposals and spans transactionally. Invalid model output is rejected/quarantined, not stored as an accepted-looking record.

### P-16 Search indexing

Index:

- original capture text immediately;
- generated summary as derived text;
- accepted assertion/object text;
- explicitly labeled proposals only in review search.

### P-17 Review routing

Apply risk, confidence, ambiguity, consequence, sensitivity, contradiction, and policy rules.

### P-18 Today/Pulse eligibility

Only accepted or explicitly user-authored actionable consequences may be eligible. A model proposal alone cannot create a reminder or Pulse item.

## Idempotency

Recommended key:

```text
sha256(capture_version_id | stage | pipeline_version | stage_config_hash)
```

A completed stage with the same key returns the prior output. A changed pipeline/config creates a new attempt and may supersede proposals without deleting history.

## Retry

- Retry transient database, model-unavailable, and service-unavailable failures with bounded exponential backoff and jitter.
- Do not retry policy denial, invalid schema, oversized input, or deterministic integrity failures until input/config changes.
- Lease expiry is recoverable.
- Poison work enters terminal failure/quarantine after the configured budget.
- Retrying never duplicates accepted records.

## Processing state

Aggregate states:

- `pending`
- `processing`
- `complete`
- `partial`
- `needs_review`
- `failed_retryable`
- `failed_terminal`
- `policy_denied`
- `superseded`

Stage-level states remain available in System detail.

## Processing priority

1. interactive recent captures;
2. retries needed for user-visible completeness;
3. review-requested reprocessing;
4. ordinary enrichment;
5. historical reprocessing/model comparison.

## Operational metrics

- captures accepted per hour/day;
- save acknowledgment latency;
- pending age;
- stage latency and failure rate;
- retry/exhaustion rate;
- unresolved identity count;
- proposal volume by type/risk;
- review acceptance/correction/rejection;
- false commitment/decision evaluation rate;
- indexing lag;
- model route and privacy-denial count;
- sync duplicate/conflict rate;
- storage growth.
