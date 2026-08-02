# AI Strategy

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Position

AI is used to interpret and propose. Deterministic application services validate and commit. No AI output silently becomes consequential canonical state or external action.

## Processing hierarchy

1. deterministic validation and metadata;
2. deterministic/heuristic parsing;
3. local entity dictionaries and relationship/project vocabularies;
4. lexical retrieval;
5. local model extraction/summarization where eligible;
6. cloud model only under explicit policy and operator-approved eligibility;
7. human review for consequential transitions.

## AI use cases

### Appropriate

- note/conversation subtype suggestion;
- entity mention extraction;
- candidate identity ranking;
- project/Situation linking candidates;
- summary;
- task/commitment/decision/risk/issue/question proposals;
- conversation-channel/time candidates;
- contradiction candidate generation;
- related-record suggestions;
- query expansion for Reveal;
- review explanation.

### Not AI authority

- capture persistence;
- author identity;
- server receipt;
- exact launch context;
- idempotency;
- source text hash;
- final identity merge;
- accepted commitment/decision;
- financial/schedule truth;
- external actions;
- disclosure eligibility;
- retention/deletion;
- risk acceptance.

## Model routing

Input policy:

- classification;
- purpose;
- eligible fields;
- destination;
- model/provider/version;
- retention/training terms;
- redaction;
- token/size limits;
- expected output schema;
- authority class.

Routes:

- `deterministic_only`
- `local_model`
- `approved_cloud_model`
- `no_ai`

A capture may remain fully useful through exact search even when AI processing is denied.

## Schema-constrained output

Model output must conform to typed proposal schemas. Each item requires:

- proposal type;
- normalized value;
- direct source spans;
- unresolved fields;
- confidence;
- alternatives where ambiguous;
- limitations;
- model/schema/prompt version.

Reject:

- spans that do not match source;
- unsupported types;
- unknown fields;
- references to nonexistent entities;
- tool/action instructions;
- payloads above bounds.

## Confidence calibration

- store native model confidence separately from calibrated probability;
- calibrate by proposal type and content class;
- evaluate on synthetic/de-identified approved fixtures;
- publish precision/recall and critical-error rates;
- do not compare raw scores from different models as equivalent;
- review thresholds depend on consequence, not confidence alone.

## Model fallback

- deterministic baseline always available;
- local model may fail to deterministic-only;
- cloud route may fail to local/deterministic according to policy;
- failure produces `partial` with limitations;
- never broaden disclosure to make processing succeed.

## Prompt injection

Treat captured text as untrusted evidence.

- no tool access in extraction model session;
- delimit content from instructions;
- do not follow URLs or commands in text;
- do not retrieve arbitrary sources named in text;
- validate output against source spans;
- use allowlisted retrieval scope;
- preserve prompt/schema hashes;
- test indirect injection in pasted emails/web content.

## Over-linking controls

- candidate-set minimum separation;
- unresolved state when top candidates are close;
- use launch context as evidence, not absolute truth;
- no identity merge through extraction;
- review high-consequence links;
- track false-link corrections;
- allow user-confirmed aliases to improve future ranking.

## Hallucinated commitment controls

A commitment proposal requires:

- action phrase;
- obligor/counterparty or explicit unknown;
- source span;
- due condition or explicit unknown;
- evidence that language is promissory rather than speculative;
- review before canonical promotion.

Evaluation includes negation, quotation, conditional language, reported speech, brainstorming, and third-party commitments.

## Training and feedback

User corrections are not automatically training eligible.

Eligibility requires:

- explicit policy;
- de-identification or approved local training;
- exact source/proposal/correction lineage;
- sensitivity check;
- immutable dataset manifest;
- leakage-resistant split;
- operator-approved model lifecycle.

No model promotes itself.

## Model evaluation

Per proposal type:

- exact span precision/recall;
- entity resolution top-1/top-k;
- false merge rate;
- commitment/decision precision;
- date/amount accuracy;
- critical omission rate;
- contradiction usefulness;
- review correction rate;
- latency/resource usage;
- privacy-route compliance;
- prompt-injection resistance.

The MVP may ship deterministic and local-model adapters with limited proposal types. It need not solve generalized understanding before providing capture value.
