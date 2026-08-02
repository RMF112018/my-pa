# Review and Promotion Policy

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Objective

Preserve trust without making every capture an administrative task.

The system separates:

1. **source persistence**;
2. **noncanonical enrichment**;
3. **canonical promotion**;
4. **external action**.

Each has a different authority boundary.

## Automatically accepted

May be committed without review when deterministic and policy-valid:

- Capture and CaptureVersion source record;
- exact source text and hash;
- server receipt timestamp;
- authenticated author;
- client/device timestamp labeled observed;
- explicit launch mode;
- exact launch context after current-version validation;
- classification default and processing-policy selection;
- full-text indexing of original text;
- system processing/audit metadata;
- low-risk technical tags such as language or content length.

## Useful without canonical promotion

Persist as labeled proposals and use in bounded retrieval/review without blocking the user:

- topics;
- likely people/organizations/projects;
- likely Situation;
- related records;
- conversation channel;
- occurred-time candidate;
- generic task/follow-up candidates;
- summary;
- note subtype;
- relationship/project event candidate.

These may support filters and suggestions only when the UI visibly identifies them as inferred/proposed. They do not update canonical profiles, timelines, or obligations.

## Review required before canonical promotion

- commitment;
- decision;
- financial fact or amount interpreted as project truth;
- critical date or schedule milestone;
- identity merge/split;
- ambiguous person/project link with consequential effects;
- contradictory assertion resolution;
- sensitive relationship observation;
- legal/personnel/medical inference;
- external-action instruction;
- deletion affecting accepted records;
- source edit that invalidates accepted downstream state;
- change to cloud/model-training eligibility.

## Prohibited automatic transitions

AI/rules may not automatically:

- send messages;
- create calendar events;
- modify contacts;
- update Procore/financial/schedule systems;
- create externally visible tasks;
- accept risk;
- merge identities;
- resolve contradictions;
- delete source or accepted evidence;
- expose content to a cloud model;
- use capture content for training;
- start recording;
- create a relationship score;
- infer protected/sensitive traits.

## Risk classes

| Class | Example | Default |
|---|---|---|
| Low | language, topic, exact context link | auto or proposal |
| Moderate | likely project/person, generic task | proposal |
| High | commitment, decision, amount, due date | review |
| Critical | legal/personnel conclusion, external action, identity merge, destructive effect | explicit review and possibly separate operator authority |

## Confidence and consequence

Confidence alone does not determine promotion. A 0.99 high-consequence commitment remains review-required. A 0.75 topic may remain a harmless proposal.

Routing function considers:

```text
risk × consequence × ambiguity × sensitivity × reversibility × confidence
```

## Review-case contents

- proposed transition in plain language;
- exact Capture and CaptureVersion;
- highlighted direct/context/counterevidence spans;
- source text access;
- target object and expected version;
- candidate identities/alternatives;
- confidence and calibration;
- model/rule/schema/prompt provenance;
- contradiction and unavailable evidence;
- downstream impact;
- allowed dispositions;
- resulting receipt behavior.

## Dispositions

- Accept
- Correct and Accept
- Reject
- Defer
- Mark Unresolved
- Reprocess under an eligible route
- Escalate to operator-only decision

## Review burden controls

- no review case for every low-risk tag;
- aggregate low-risk suggestions in Capture detail;
- homogeneous bulk review only with server-side preview;
- deduplicate overlapping proposals;
- suppress repeated rejected patterns for the same context where safe;
- prioritize by due date, consequence, and uncertainty;
- allow “review later” without blocking capture;
- measure correction and false-positive rates;
- retire low-value extractors rather than normalize excessive review.

## Notifications

A review notification is permitted only when:

- a consequential proposal is time-sensitive;
- an explicit user instruction requests a reminder/review;
- processing failed and requires user action;
- a sync conflict risks loss or ambiguity.

Notifications show generic wording by default and no capture text, participant, amount, or project name on lock screens.

## External actions

Acceptance of a commitment or task is not authority to execute it. External actions require a separate action proposal, exact authorization, preview, and execution receipt.
