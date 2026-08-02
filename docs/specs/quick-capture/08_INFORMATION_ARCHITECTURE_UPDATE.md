# Information Architecture Update

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Decision

Quick Capture remains a **pervasive global action**, not a primary navigation destination.

Primary navigation remains:

1. Today
2. Situations
3. Review
4. Library
5. System

Reveal remains the global search/command surface.

## Global action placement

- Navigation shell: `Capture` button.
- Reveal / command palette:
  - Capture note
  - Log conversation
  - Capture in current Situation
- Context headers: Capture action with deterministic context.
- Mobile: persistent action reachable with one tap.
- Keyboard: focused-app shortcut.
- Installed app routes: Quick Note and Conversation Log.

## Library

Add **Captures** as the canonical durable collection. Provide built-in saved views:

- All Captures
- Notes
- Conversations
- Recent
- Needs Review
- Processing
- Sync Pending
- Archived

The left navigation under Library may show Notes and Conversations as view shortcuts, but they resolve to filtered Captures routes rather than separate domain silos.

Suggested routes:

```text
/library/captures
/library/captures?view=notes
/library/captures?view=conversations
/captures/{capture_id}
/conversations/{conversation_id}
```

## Capture detail

Capture detail includes:

- original/current source text;
- version history;
- source authority label;
- recorded/device/server timestamps;
- deterministic and proposed contexts;
- processing status and attempts;
- extracted proposals and exact spans;
- accepted downstream records;
- review cases;
- audit/receipt links;
- classification and processing route;
- archive/edit actions.

## Conversation detail

Conversation detail is a specialized Event view:

- summary and original capture;
- participants and unresolved mentions;
- organization/project/Situation links;
- channel and occurred time, with trust labels;
- commitments in each direction;
- decisions, tasks, follow-ups, risks, issues, questions;
- relationship/project timeline placement;
- evidence/provenance rail;
- correction and review state.

## Contextual surfaces

### Today

Show only:

- explicit reminders created/accepted from captures;
- accepted commitments/tasks due soon;
- review items whose consequence and timing justify attention;
- sync/processing failures only when user action is required.

Do not show every new capture.

### Pulse

A capture may influence Pulse only when an accepted or explicitly user-authored consequence meets Pulse ranking criteria. Raw capture volume, model confidence, or processing completion is not sufficient.

### Situation Frame

Show latest relevant linked captures in a compact evidence stream. Proposed links are labeled and do not silently enter the Situation’s accepted state.

### Trace

Capture versions, accepted links, corrections, and derived events appear chronologically with distinct recorded, occurred, processing, and acceptance times.

### Project Workspace

Accepted project-linked conversations, observations, decisions, commitments, risks, milestones, and amounts appear in Timeline and relevant specialized collections. Original capture remains accessible.

### Relationship Workspace

Accepted interactions and reciprocal commitments appear in timeline and preparation surfaces. Private notes remain visibly distinct from sourced facts and model inferences.

### Review

Review queues include:

- consequential extraction;
- participant/entity resolution;
- context linking;
- contradiction;
- source edit revalidation;
- sensitive relationship assertion;
- processing policy denial where operator action is needed.

### System

System > Processing shows:

- pending/failed capture jobs;
- extraction/index lag;
- sync failures;
- model routing and privacy denial counts;
- unresolved identity volume;
- review burden;
- storage growth.

## Reveal result types and trust labels

Reveal must distinguish:

- `Original Capture`
- `Conversation Event`
- `Generated Summary`
- `Accepted Assertion`
- `Task`
- `Commitment`
- `Decision`
- `Relationship Event`
- `Project Event`
- `Review Proposal`

Each result shows source type, recorded/occurred time as applicable, linked context, authority/trust state, and evidence-preview action.
