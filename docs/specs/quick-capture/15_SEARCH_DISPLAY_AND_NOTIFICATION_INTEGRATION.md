# Search, Display, and Notification Integration

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Search principle

The original capture must be searchable independently of successful extraction. Search may enrich retrieval but cannot make the source disappear behind generated objects.

## Reveal result model

Each result has an explicit type:

| Result type | Authority |
|---|---|
| Original Capture | source-authoritative user evidence |
| Conversation Event | accepted/skeletal/proposed event, labeled |
| Generated Summary | derived/inferred |
| Accepted Assertion | canonical product assertion |
| Task | canonical/proposed, labeled |
| Commitment | canonical/proposed, labeled |
| Decision | canonical/proposed, labeled |
| Relationship Event | canonical/proposed, labeled |
| Project Event | canonical/proposed, labeled |
| Review Proposal | noncanonical |

## Search capabilities

### Exact and lexical

- exact phrase;
- token/keyword;
- prefix and tolerant matching when justified;
- original-text-only scope;
- source authority filters;
- note/conversation view;
- archived/current;
- processing/review state.

PostgreSQL full-text search is the first implementation. `pg_trgm` may support tolerant matching when evaluation demonstrates value.

### Metadata filters

- captured date/time;
- occurred date/time;
- person;
- organization;
- project;
- Situation;
- channel;
- capture kind/subtype;
- classification;
- authority/trust state;
- review state;
- sync/processing state;
- device/origin, subject to privacy.

### Semantic retrieval

Deferred behind:

- benchmark;
- explicit capability state;
- privacy routing;
- source-span evidence;
- coverage disclosure;
- fallback to lexical search.

Semantic results never hide whether the match came from original text, summary, or another derived representation.

## Result card

Show:

- type label;
- short excerpt;
- original/derived/proposed/accepted label;
- recorded and occurred dates where relevant;
- linked people/project/Situation;
- source version;
- processing/coverage limitations;
- one-action evidence preview.

Do not put raw confidence as the primary label.

## Capture detail

Sections:

1. Original text
2. Version history
3. Context and links
4. Processing status
5. Extracted proposals
6. Accepted records
7. Evidence spans
8. Audit and receipts
9. Privacy/processing policy
10. Related records

## Conversation detail

Sections:

- conversation identity/state;
- original capture;
- accepted summary;
- channel/time/location;
- participants and unresolved mentions;
- topics;
- reciprocal commitments;
- decisions/tasks/follow-ups;
- risks/issues/questions;
- project/relationship links;
- evidence rail;
- review history.

## Timeline integration

### Relationship timeline

Include accepted:

- conversation event;
- follow-up;
- reciprocal commitment;
- user-authored private note when the user explicitly links it.

Proposed events remain in a labeled pending section, not the canonical timeline.

### Project timeline

Include accepted:

- conversation/meeting;
- field observation;
- decision;
- commitment;
- risk/issue;
- financial/schedule event.

Every item links back to exact source spans.

## Today and Pulse

### Today eligibility

- accepted task/commitment with due condition;
- explicit user reminder;
- review case due/time-sensitive;
- sync/processing failure needing action;
- upcoming relationship follow-up accepted by user.

### Pulse eligibility

Require:

- accepted consequence or explicit user assertion;
- meaningful urgency/impact;
- reason label;
- evidence and source access;
- deduplication against existing Pulse items;
- policy-safe display.

Do not promote merely because:

- a capture was saved;
- processing completed;
- a model assigned high confidence;
- many entities were extracted.

## Notifications

Default channels:

- in-app status/toast;
- optional generic system notification;
- Today item;
- Pulse item only under stricter criteria.

Allowed generic examples:

- “A capture needs review.”
- “One offline capture could not sync.”
- “Quick Capture processing failed.”

Disallowed lock-screen examples by default:

- note text;
- participant names;
- project name;
- financial amount;
- legal/personnel subject;
- relationship observation.

## Review and System integration

Review:

- consequential extraction;
- contradictions;
- unresolved high-impact identities;
- source edit revalidation;
- sensitive promotion.

System:

- ingestion rate;
- pending age;
- failed jobs;
- unresolved identity volume;
- review backlog;
- duplicate/idempotency conflicts;
- sync failure;
- index lag;
- model routing/privacy denials;
- storage growth.

System is operational truth, not a separate Quick Capture admin product.
