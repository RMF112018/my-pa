# MVP, Deferred Capabilities, and Roadmap

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## MVP definition

A high-quality MVP includes:

### Capture surfaces

- in-app global Capture;
- Quick Note route;
- Conversation Log route;
- command palette/Reveal commands;
- focused-app keyboard shortcut;
- responsive mobile/tablet surface;
- installable PWA;
- mode-specific URLs;
- Windows manifest shortcuts where supported.

### Durability

- one unrestricted text field;
- explicit save;
- local draft autosave;
- immediate server persistence;
- capture receipt;
- offline encrypted append-only queue;
- idempotent synchronization;
- immutable source versions;
- archive, not hard delete.

### Processing

- original-text indexing;
- language/segmentation;
- people/project/date extraction;
- task/commitment/decision proposals;
- exact evidence spans;
- basic conversation participant/channel/time proposals;
- deterministic launch-context linking;
- asynchronous jobs/retries;
- partial/failure state;
- review routing.

### Display

- Captures collection;
- Notes and Conversations saved views;
- Capture detail;
- Conversation detail;
- Reveal result types;
- accepted Project/Relationship timeline links;
- Review cases;
- System processing status.

### Trust/privacy

- private-local default;
- cloud false by default;
- no automatic external action;
- audit and receipts;
- prompt-injection controls;
- WCAG 2.2 AA;
- synthetic fixtures only.

## Near-term enhancements

- Windows PWA share target for text/URL;
- Apple Shortcut setup/deep links;
- better deterministic date/project/entity dictionaries;
- user-configurable mode/keyboard shortcuts;
- batch correction of homogeneous low-risk links;
- selective notification/reminder proposals;
- bounded attachments after separate storage design;
- model comparison/evaluation dashboard;
- improved context suggestions;
- offline storage health and export/recovery guidance.

## Later platform capabilities

- Tauri desktop wrapper for global hotkey, menu bar/system tray, floating window, secure key storage;
- native Apple target for App Intents, Siri, Spotlight, WidgetKit controls, Lock Screen/Control Center, Share extension;
- user-initiated audio memo;
- meeting recording/transcription under a separate legal/privacy feature;
- on-device speech transcription;
- advanced semantic retrieval after benchmark;
- team/multi-user capture only under a separate product/security model.

## Speculative/rejected

Rejected for the initial capability:

- mandatory metadata form;
- automatic call interception;
- hidden/background recording;
- native apps before PWA measurement;
- relationship score;
- automatic identity merge;
- automatic commitments/decisions as canonical;
- automatic external actions;
- arbitrary link fetching;
- cloud processing by default;
- generalized microservice/plugin architecture;
- dedicated vector/graph database;
- capture-specific Redis/Celery.

## Repository prerequisites

At the authenticated basis:

| Dependency | Current state | Quick Capture need |
|---|---|---|
| PostgreSQL and Alembic | Present | Extend only under authorized schema work |
| Common contracts/policy/audit primitives | Present | Reuse/extend |
| Source registry/enrollment/jobs | Present | Reuse job plane; capture is a new product-owned source |
| Extraction/quarantine/coverage/search | Not complete | Required |
| Gateway/application transports | Not complete | Required |
| Review/knowledge lifecycle | Product-defined, not complete end-to-end | Required |
| Frontend shell/PWA | Absent and operator-held | Required |
| Offline queue | Absent | Required |
| Relationship/project services | Deferred/not operational | Needed for full integration; MVP may retain proposals until available |

## Sequencing recommendation

This sequence is **conditional on explicit operator reprioritization** and current-head revalidation.

### QC-00 — Decision and scope gate

- accept or revise this product package;
- decide open operator items;
- resolve priority against MCV;
- lift or retain frontend hold;
- define exact implementation goal/authorization.

### QC-01 — Domain and contract foundation

- Capture/Version authority model;
- IDs/states/errors;
- proposal/span schemas;
- API contract;
- architecture tests;
- no frontend.

### QC-02 — Durable create/read/version

- Alembic schema;
- repository/application transaction;
- idempotency;
- receipt/audit;
- original-text read/search stub;
- synthetic tests.

### QC-03 — Processing and exact search

- worker stages;
- normalization/span mapping;
- deterministic extraction;
- FTS;
- proposals;
- retry/partial/failure.

### QC-04 — Review and conversation event

- review cases;
- acceptance receipts;
- Conversation/participants;
- context links;
- source edit revalidation;
- no external action.

### QC-05 — Web/PWA capture

- responsive one-field UI;
- global action/routes;
- generated client;
- installability;
- focused shortcut;
- accessibility/performance tests.

### QC-06 — Offline

- encrypted IndexedDB queue;
- sync contract;
- stale-auth/conflict behavior;
- recovery tests.

### QC-07 — Integration

- Library/Reveal;
- Project/Relationship timeline adapters where available;
- Today/Pulse gates;
- System metrics;
- end-to-end synthetic validation.

### QC-08 — Platform evaluation

- Windows shortcuts/share;
- Apple deep-link Shortcuts guidance;
- measure global-hotkey/native demand;
- ADR only if wrapper/native work is justified.

## Stop conditions

Stop implementation planning or execution when:

- repository basis or active objective drifts;
- frontend hold remains in force;
- live personal data becomes necessary;
- cloud/model disclosure is assumed;
- a new native platform or broker is required without operator decision;
- privacy/retention/offline key management cannot be bounded;
- current review/authority substrate cannot preserve consequential proposals.
