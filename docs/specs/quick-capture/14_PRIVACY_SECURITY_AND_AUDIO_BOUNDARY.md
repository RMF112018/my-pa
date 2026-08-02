# Privacy, Security, and Audio Boundary

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Default privacy posture

- Classification: `private_local`
- Cloud eligible: `false`
- Training eligible: `false`
- Lock-screen content display: `false`
- Third-party analytics payload: no source text or sensitive metadata
- External action authority: none

Location on a local device does not by itself determine classification. The user or policy may apply `restricted_local` or another approved class.

## Sensitive content classes

Quick Capture may contain:

- legal strategy;
- personnel matters;
- health information;
- financial amounts;
- credentials accidentally pasted;
- relationship observations;
- confidential project information;
- disputes or allegations;
- personally identifying information.

The pipeline must assume sensitivity, not infer safety from mode or source.

## Surface privacy

- No source text in notification previews by default.
- No participant/project/amount in lock-screen notifications.
- Avoid sensitive titles in URLs, browser history, app titles, and recent-window lists.
- Dedicated capture route uses opaque IDs only.
- Provide lock/logout and cache-clear behavior.
- Capture text is not sent to third-party telemetry.
- Error reporting uses stable IDs, stage, size, timing, and safe error class.
- Clipboard is not read automatically.
- Pasted content is untrusted data.

## Model routing

Before any model call, create a context manifest with:

- exact capture/version;
- selected fields/spans;
- purpose;
- classification;
- destination;
- model/provider/version;
- retention/training terms;
- redaction;
- authority class;
- policy decision/version;
- correlation/audit reference.

Default local-only does not imply every local model/process is approved. Model package, isolation, logs, and retention still require policy.

Cloud processing requires a separate operator decision naming provider/account, purpose, field allowlist, retention/training terms, security posture, audit receipt, and revocation.

## Prompt-injection controls

Captured/pasted text is never instruction authority.

- system prompts state that content is evidence data;
- no tool permissions in extraction calls;
- schema-constrained output;
- strip/ignore embedded tool instructions;
- separate retrieved evidence from control messages;
- validate URLs/identifiers;
- no automatic fetch of links;
- no external action from extracted commands;
- record prompt/schema/model version;
- adversarial injection tests.

## Relationship-surveillance boundary

- no relationship score;
- no hidden sentiment/loyalty/compatibility rating;
- no sensitive-trait inference;
- no public research by default;
- no continuous monitoring implied by a Conversation Log;
- private notes remain visibly user-authored and do not become source facts about another person;
- consequential relationship guidance remains proposed.

## Retention and deletion

Operator decision required. Recommended interim policy:

- retain immutable versions while active;
- archive rather than hard-delete;
- define draft expiration separately;
- define offline ciphertext removal after verified sync;
- preserve audit/receipt without copying content;
- hard delete only with legal/privacy basis, impact analysis, exact target, backup/recovery considerations, and explicit authority;
- downstream accepted records require separate disposition.

## Audio boundary

### Typed MVP

Included:

- typed text;
- pasted text;
- OS-level dictation into the text field.

OS dictation is treated as text input. my-pa does not store audio or claim transcription provenance beyond the resulting user-reviewed text.

### Near-term candidate

User-initiated audio memo:

- explicit record control;
- visible recording state;
- local encrypted audio;
- explicit stop/save;
- transcription with source time spans;
- retention and deletion policy;
- no background call interception.

Requires a new feature specification and legal/privacy review.

### Later/high-risk

- meeting recording;
- speaker diarization;
- live transcription;
- consent capture;
- background recording;
- call recording.

These require jurisdiction-sensitive consent analysis, platform entitlements, privacy design, audio retention, speaker identity controls, and explicit operator authority.

### Rejected from MVP

- automatic phone-call interception;
- automatic call recording;
- hidden/background recording;
- recording triggered solely by call state;
- model inference that recording consent exists.

## Threats and controls

| Threat | Control |
|---|---|
| Accidental sensitive disclosure | private-local default, explicit routing policy, no content telemetry |
| Incorrect person linking | unresolved candidate sets, review, reversible identity workflow |
| False commitments/decisions | span requirement, review-required promotion, extraction evaluation |
| Duplicate sync | IDs, idempotency, request hash, receipt replay |
| Stale offline credentials | local-only save policy, reauthentication before sync |
| Device theft | encryption, lock, minimal previews, revocation limits disclosed |
| Malicious pasted instructions | data/instruction separation, no tools, schema validation |
| Oversized capture | bounded input, draft preservation, clear error |
| Notification leakage | generic notifications, previews off |
| Improper deletion | archive default, impact preview, operator-gated hard delete |
| Model-training leakage | false by default, explicit eligibility records |
| Automation on unreviewed capture | proposal-only state, policy gate, separate action authority |
