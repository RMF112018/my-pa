# Terminology and Capture-Type Taxonomy

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Naming decision

- Capability/package: **Quick Capture**
- Global action label: **Capture**
- Initial modes: **Quick Note**, **Conversation Log**
- Durable collection: **Captures**
- Saved Library views: **Notes**, **Conversations**

The term “Call Log” is too narrow because the same workflow covers in-person, video, meeting, and informal interactions. “Conversation Log” is the correct initial mode label. “Universal Capture” is descriptive but overly infrastructural for the user-facing term.

## Taxonomy layers

### Layer 1 — launch mode

The only initial user-visible modes:

| Mode | Meaning | User must select? |
|---|---|---|
| `quick_note` | General user-authored evidence | Only when using a dedicated shortcut; general Capture may default here |
| `conversation_log` | Summary of an interaction with one or more people | Dedicated shortcut recommended; switchable in surface |

A general Capture launcher may infer a likely mode after save. Mode inference never blocks persistence.

### Layer 2 — inferred note subtype

Subtypes are derived labels, not required fields:

- `observation`
- `idea`
- `reminder`
- `decision_note`
- `field_note`
- `meeting_note`
- `status_note`
- `research_note`
- `pasted_text`
- `shared_content`
- `voice_dictated_text`
- `general_note`
- `unknown`

One capture may carry multiple subtype proposals. The source type remains Quick Note.

### Layer 3 — conversation channel

Channel values:

- `phone_call`
- `in_person`
- `video_call`
- `formal_meeting`
- `informal_exchange`
- `text_or_chat`
- `email_discussion_summary`
- `unknown`

Channel is canonical only when explicitly supplied, deterministically known from launch context, or accepted under policy. “Conversation” describes the event; channel describes how it occurred.

### Layer 4 — extracted content types

A capture may yield proposals for:

- person;
- organization;
- project;
- Situation;
- event time;
- location;
- topic;
- task;
- commitment;
- decision;
- follow-up;
- open question;
- risk;
- issue;
- relationship event;
- project event;
- financial amount;
- critical date;
- schedule milestone;
- referenced document;
- source link;
- contradiction;
- unresolved identity.

These are not capture types. They are evidence-backed proposals derived from a capture version.

## Mode behavior

### Separate launch shortcuts

Provide separate Quick Note and Conversation Log launch URLs/commands where the platform supports them. Dedicated launch sets a `mode_hint` and UI label; it does not require more fields.

### Switching modes

A compact mode control may appear in the header. It is optional and keyboard accessible. Switching changes processing expectations and placeholder copy, not the one-field contract.

### Inference behavior

- General Capture may default to Quick Note.
- Clear conversation language may produce a Conversation proposal.
- A low-confidence inference remains `unknown`.
- The system must not ask a blocking clarification before save.
- User correction of mode creates an auditable metadata correction and may requeue processing.

## Conversation as a first-class object

Recommendation:

- `Capture` is always the source record.
- A Conversation Log launched explicitly may create a skeletal `Conversation` event after save with unknown channel/participants/time fields.
- A conversation inferred from a Quick Note remains a proposal until accepted.
- The Conversation object is a specialized first-class `Event`, not an alternate source record.
- The Conversation retains a required link to the capture version that supports it.
