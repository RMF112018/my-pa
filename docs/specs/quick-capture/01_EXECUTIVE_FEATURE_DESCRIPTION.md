# Executive Feature Description — Quick Capture

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Conclusion

my-pa should adopt **Quick Capture** as the fastest path for creating evidence that originates with the user: memory, observation, a phone call, a meeting, an informal conversation, a field condition, or an idea.

The feature should be a **pervasive action**, not a form and not a primary navigation area. The user launches a capture surface, enters text into one unrestricted field, saves, and leaves. Durable persistence occurs before extraction. All classification, entity resolution, contextual linking, task/commitment/decision detection, contradiction checks, and proposal generation occur asynchronously.

## Product problem

The current my-pa thesis is strong at assembling and governing evidence from external sources. It is incomplete unless it also captures evidence that exists only in the user’s head after an interaction. Conventional notes, CRM forms, and project-management records fail at the moment of capture because they demand filing, categorization, participant selection, dates, projects, and follow-up choices before the user can preserve the substance.

Quick Capture reverses that sequence:

```text
Preserve → Acknowledge → Interpret → Propose → Review → Reuse
```

The user supplies the evidence once. my-pa performs the administrative work later and keeps the original text independently addressable.

## Product position

Quick Capture is simultaneously:

- **a feature**: the visible one-field capture experience;
- **an ingestion source**: a product-owned source class for user-authored evidence; and
- **a platform capability**: a contract exposed through in-app launchers, installed PWA routes, commands, keyboard shortcuts, share targets where supported, and later OS-native integrations.

## Initial modes

### Quick Note

A general user-authored evidence record. It may contain an observation, reminder, idea, decision note, field note, meeting note, pasted text, or other unstructured material. These are inferred subtypes, not required pre-save choices.

### Conversation Log

A user-authored summary of a phone call, in-person conversation, video call, meeting, or informal exchange. The system evaluates participants, organizations, projects, Situations, channel, time, commitments, decisions, follow-ups, tasks, open questions, risks, issues, relationship events, project events, financial amounts, critical dates, milestones, referenced documents, contradictions, and unresolved identities.

A dedicated Conversation Log launch communicates the user’s intent. It may create a skeletal Conversation event with unknown fields after save. Inferred details remain proposed until the applicable authority policy permits promotion.

## Minimum interaction contract

Required input:

- one non-empty unrestricted text field; and
- an explicit save gesture, normally the Save button or `Cmd/Ctrl+Enter`.

Not required:

- title;
- participant;
- date;
- project;
- Situation;
- category;
- task/commitment/decision fields;
- sensitivity choice;
- tags;
- attachments;
- AI settings.

Optional context may be supplied by the launch route without user work—for example, a capture launched from a Project, Relationship, Situation, meeting, Commitment, or Decision. Such context is deterministic launch metadata, not model inference.

## Experience requirements

- Warm in-app launch to focused cursor: target p75 ≤100 ms and p95 ≤250 ms.
- Installed-PWA cold launch to focused cursor: target p75 ≤1.5 s and p95 ≤2.5 s on supported target devices.
- Keystroke response: ≤50 ms p95; never wait on network or model processing.
- Save acknowledgment after local durable commit: ≤200 ms p95.
- Online server acceptance: target ≤750 ms p95 on the intended local network.
- The capture surface closes immediately after durable persistence.
- Processing continues asynchronously and is inspectable but nonblocking.
- A non-empty unsaved draft is locally recoverable.
- Offline capture is append-only and confirms local persistence.

Targets are acceptance budgets to validate on supported hardware, not claims about current runtime behavior.

## Source and authority recommendation

The original saved text is:

- a **product-owned source record**;
- **source-authoritative user evidence** for what the user wrote;
- usually classified `private_local` by default;
- immutable by version;
- independently addressable;
- provenance-complete;
- never overwritten by a generated summary.

The text proves what the user recorded, not necessarily that every statement is objectively true. Derived facts remain assertions or proposals with explicit authority, confidence, evidence spans, and review state.

## Information architecture

Quick Capture remains a global action available from:

- the app shell;
- command palette / Reveal;
- keyboard shortcut;
- contextual object headers;
- mobile action affordance;
- installed-PWA launch routes.

Library should contain a combined **Captures** collection with default saved views for **Notes** and **Conversations**. This avoids three competing destinations while satisfying predictable retrieval. Accepted linked captures may appear in Project and Relationship timelines. Unresolved consequential extractions appear in Review. Processing failures appear in System.

## Platform recommendation

### Web/PWA MVP

- one responsive capture route;
- in-app overlay/sheet;
- installable PWA;
- mode-specific URLs;
- manifest shortcuts where the browser/OS exposes them;
- Windows Start/taskbar jump-list shortcuts;
- offline IndexedDB queue;
- foreground/resume sync, with Background Sync used only as an enhancement;
- Windows PWA share target where supported.

### Native-required later work

- Apple App Intents, Siri-native actions, Lock Screen widgets, Control Center controls, and robust Share extensions;
- macOS menu-bar utility and system-wide shortcut;
- Windows system-tray utility and system-wide shortcut;
- consistent always-on-top floating windows;
- platform-level encrypted credential/keychain integration.

A thin Tauri wrapper is the preferred desktop candidate only after PWA measurements prove a material need. Electron is not recommended unless its ecosystem capabilities are specifically required.

## MVP recommendation

Include:

- Quick Note and Conversation Log launch modes;
- one-field in-app/PWA surface;
- explicit save plus local draft autosave;
- immediate server or offline durable persistence;
- immutable capture versions;
- idempotent asynchronous processing;
- exact-text search;
- people/project/date/task/commitment/decision proposals;
- evidence spans;
- Review routing;
- Captures/Notes/Conversations Library views;
- Project and Relationship timeline integration for accepted links;
- audit, receipts, retries, and visible failure states;
- offline append-only capture queue.

Exclude from MVP:

- automatic call recording or interception;
- stored audio;
- native Apple/Windows wrappers;
- attachments other than later bounded shared text/URLs;
- cloud processing by default;
- automatic external actions;
- automatic canonical commitments, decisions, financial facts, critical dates, or identity merges.

## Formal product principle

Adopt:

> **When the user is the source, my-pa preserves the evidence first and structures it afterward.**

This closes a material gap in the product thesis. my-pa should not merely assemble evidence; it should make creation of new evidence faster than opening a conventional notes, CRM, or project-management record.
