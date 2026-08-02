# Testing, Evaluation, and Acceptance Criteria

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Test-data rule

Ordinary tests use synthetic fixtures only. No live personal notes, phone summaries, contacts, email, calendar, NAS, Procore, financial, or schedule data.

## Test strategy

### Domain tests

- capture/version immutability;
- lifecycle transitions;
- authority states;
- conversation skeletal/accepted states;
- context-link rules;
- span validation;
- source edit invalidation;
- archive/deletion boundaries.

### Contract tests

- strict schemas and unknown-field rejection;
- common envelope;
- idempotent replay;
- version conflict;
- partial/unavailable states;
- authorization/purpose;
- error redaction;
- generated client compatibility.

### Database tests

- empty-to-head migration;
- constraints and indexes;
- concurrent idempotency;
- job leasing/recovery;
- transaction atomicity;
- source/receipt/job all-or-nothing;
- accepted proposal/receipt all-or-nothing;
- supersession and lineage.

### Offline/sync tests

- airplane-mode save;
- reload/crash recovery;
- exact-once server result;
- replay after response loss;
- idempotency conflict;
- stale authentication;
- account switch isolation;
- storage quota/error;
- encrypted payload/no plaintext;
- foreground and supported background sync;
- multiple-device version conflict.

### Extraction evaluations

Synthetic corpus covers:

- observations;
- reminders;
- tasks;
- commitments by user/other/third party;
- negated commitments;
- conditional promises;
- quoted speech;
- decisions versus options;
- dates/relative dates/timezones;
- financial amounts;
- schedule milestones;
- ambiguous people/projects;
- same-name identities;
- unknown channel;
- multiple conversations in one note;
- pasted malicious instructions;
- legal/personnel sensitivity.

Metrics:

- proposal precision/recall;
- exact span precision/recall;
- critical false-positive rate;
- commitment/decision precision;
- person/project resolution top-1/top-k and false merge;
- date/amount exactness;
- review correction/rejection;
- latency/resource use.

### Privacy routing tests

- private/restricted never reaches cloud without policy;
- no source text in logs/analytics/events/URLs;
- no training eligibility by default;
- notifications generic;
- context manifest exact;
- denied route remains saved/searchable where policy permits.

### Prompt-injection tests

- “ignore instructions” in note;
- fake JSON/tool call;
- malicious URL;
- pasted email requesting exfiltration;
- instruction embedded in quoted meeting notes;
- model output with unsupported action.

Expected: no tool/action/disclosure; bounded proposal only or safe failure.

### PWA/browser/device matrix

Minimum:

- current supported Chrome/Edge desktop;
- current Safari macOS;
- current Safari iPhone/iPad Home Screen web app;
- Windows installed Edge PWA;
- offline/reload/resume;
- reduced motion/high contrast/large text;
- virtual/physical keyboard;
- paste/dictation.

Exact supported versions are selected at implementation time from then-current platform support.

### Accessibility

- automated WCAG checks;
- keyboard-only complete flow;
- screen-reader launch/type/save/status;
- focus restoration;
- 400% zoom/reflow;
- text scaling;
- touch targets;
- contrast;
- error retention/recovery;
- shortcut discoverability;
- offline status announcements.

### Performance

Measure:

- launch-to-cursor;
- keypress latency;
- local draft/save;
- server save;
- offline sync;
- processing queue delay;
- extraction completion;
- indexing;
- list/search;
- retry recovery;
- memory/storage growth.

### Usability

Tasks:

- capture a note in <10 seconds;
- log a call with no metadata;
- recover a draft;
- capture offline;
- locate original text later;
- distinguish source from summary;
- review a commitment;
- correct a participant;
- understand sync/processing failure.

## Acceptance criteria

### Product and UX

- `QC-AC-001`: A user can save Quick Note or Conversation Log with one non-empty free-text field and no structured metadata.
- `QC-AC-002`: Save acknowledgment does not wait for AI/extraction/indexing.
- `QC-AC-003`: Dedicated launch modes and general Capture use the same source contract.
- `QC-AC-004`: Non-empty drafts survive ordinary close/reload/crash scenarios under supported storage.
- `QC-AC-005`: Contextual capture does not fail if context linking is unavailable.

### Authority/provenance

- `QC-AC-010`: Original text is immutable by version and independently retrievable.
- `QC-AC-011`: Every proposal/accepted derived record points to exact validated source spans.
- `QC-AC-012`: Device, server, occurred, processed, and accepted timestamps remain distinct.
- `QC-AC-013`: Editing creates a new version and does not silently overwrite prior accepted state.
- `QC-AC-014`: AI summaries never replace original text.

### Review/action

- `QC-AC-020`: Commitments, decisions, critical dates, financial facts, identity merges, contradictions, and sensitive relationship conclusions require applicable review.
- `QC-AC-021`: External actions remain separately authorized.
- `QC-AC-022`: Rejected/corrected proposals retain lineage.
- `QC-AC-023`: Low-risk enrichment does not generate mandatory review burden by default.

### Offline/reliability

- `QC-AC-030`: Offline save confirms only after local transaction commit.
- `QC-AC-031`: Sync is idempotent under retry and response loss.
- `QC-AC-032`: Same idempotency key with changed content fails closed.
- `QC-AC-033`: Account/principal change cannot attach pending content to the wrong account.
- `QC-AC-034`: Processing failure never loses the source capture.
- `QC-AC-035`: Crash/lease recovery does not duplicate proposals or accepted objects.

### Privacy/security

- `QC-AC-040`: Default classification is private-local and cloud/training false.
- `QC-AC-041`: No capture text appears in logs, telemetry, event payloads, URL parameters, or lock-screen notifications by default.
- `QC-AC-042`: Captured/pasted instructions cannot invoke tools or broaden retrieval/disclosure.
- `QC-AC-043`: Local queue content is application-encrypted; limitations are documented.
- `QC-AC-044`: No audio/call recording exists in MVP.

### Search/display

- `QC-AC-050`: Exact original text is searchable independently of enrichment success.
- `QC-AC-051`: Reveal distinguishes original, derived, proposed, and accepted result types.
- `QC-AC-052`: Project/Relationship timeline entries link to original evidence.
- `QC-AC-053`: Raw captures do not enter Pulse solely because they were saved or processed.

### Device/accessibility/performance

- `QC-AC-060`: Responsive web/PWA supports the approved device/browser matrix.
- `QC-AC-061`: Web surfaces meet WCAG 2.2 AA for applicable criteria.
- `QC-AC-062`: Warm launch, input, save, and exit meet the budgets in file 06 on target hardware.
- `QC-AC-063`: Manifest/platform shortcuts are treated as progressive enhancement, not universal behavior.
- `QC-AC-064`: Native-only capabilities are not falsely claimed by PWA.

### Architecture/operations

- `QC-AC-070`: Implementation remains within modular monolith/gateway/worker/PostgreSQL unless a separately accepted ADR changes it.
- `QC-AC-071`: Existing PostgreSQL job plane is reused; no Redis/Celery/microservice is introduced without evidence.
- `QC-AC-072`: System exposes pending, failure, latency, sync, review, index, privacy-route, and storage metrics.
- `QC-AC-073`: Migrations and tests use isolated synthetic databases; no live personal data.
- `QC-AC-074`: Repository integration requires exact-current-head authorization and independent review.

### Publication

- `QC-AC-080`: Package contains all required product, UX, data, architecture, API, testing, risk, decision, visual, source, coordination, and receipt artifacts.
- `QC-AC-081`: Package folder identity and parent are verified.
- `QC-AC-082`: Primary artifacts, request/response, receipts, and owning-index registration are verified.
- `QC-AC-083`: Publication is not represented as implementation authority.
