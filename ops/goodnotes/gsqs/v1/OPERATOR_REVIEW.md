# Gate B v1 corpus — operator review

coordination_request_id: `REQ-MYPA-GOODNOTES-GATE-B-EVALUATION-20260820-001`

This package is for corpus approval. You do not need to read Python.

**Do not mark this corpus approved by merging the PR.** Approval is a
separate operator decision recorded in a filled
[`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml)
(or equivalent signed note) that cites the digest below.

`FIXED_LABELED_CORPUS_APPROVED` is currently **false**.

Machine copy: [`operator_review.json`](operator_review.json). Per-case
identity (no page bytes): [`case_index.json`](case_index.json).

## Identity

| Field | Value |
| --- | --- |
| Corpus version | `gsqs-v1` |
| Generator | `gsqs-v1-generator-1` |
| Manifest digest | `971083804db9fc46295db1ea64dcf2288d4aa1feaddd1ac8a26345f3579bb6d3` |
| Fixture class | synthetic, non-personal, deterministic PDF (`gsqs-synthetic-pdf` / `helvetica-times-italic-v1`) |
| Personal handwriting | none |
| Production GoodNotes pages | none |
| Existing A-X acceptance corpus | preserved; not replaced |

A PDF is not a note. A page is not a note. Each case binds SOURCE_CONTEXT
and NOTE_UNIT regions with normalized geometry and a SHA-256 of the
generated single-page PDF.

Changing a label or case after approval requires a **new** corpus version.
This digest is not `FROZEN` until you approve it.

## Size

| | Count |
| --- | ---: |
| Pages (cases) | 97 |
| Scoreable pages | 93 |
| Labeled NOTE_UNITs | 115 |
| Excluded / ambiguous pages | 4 |

Target was 60–100 pages and 100–150 NOTE_UNITs.

## Partitions (scoreable pages)

Stratified, not naive random. Within each stratum
`(family, primary_class, transcription_status)`, the first replica goes to
**B**, the second to **C**, the rest to **A**. Near-duplicate pages with
the same region/scenario signature cannot occupy two partitions.

| Partition | Role | Scoreable pages |
| --- | --- | ---: |
| A | improvement / development (future optimizer-visible) | 45 |
| B | fixed evaluation (future MEASURED_B0 / promotion) | 24 |
| C | holdout (hidden; final confirmation only) | 24 |

Physical partition A also holds the four excluded ambiguous pages (not
scored). B and C each contain every primary class, every transcription
status, and a context-only page.

`CORPUS_A_B_C = READY_TO_FREEZE_PENDING_OPERATOR_APPROVAL`

## Scenario coverage (scoreable pages)

| Scenario | Pages |
| --- | ---: |
| single-note | 36 |
| multiple-notes | 6 |
| context-only (no note) | 3 |
| follow-up | 3 |
| no-tag | 3 |
| multi-tag | 3 |
| one-candidate | 3 |
| multi-candidate | 3 |
| no-candidate | 3 |
| visually-close | 3 |
| dense | 3 |
| near-typed | 3 |
| arrow-leader | 3 |
| crossed-out | 3 |
| agenda-table | 3 |
| handwriting-style | 3 |
| low-contrast | 3 |
| prompt-injection | 3 |
| unreadable-trap | 3 |

## NOTE_UNIT class / status / tags / ranking

Primary class (notes): GENERAL 42, MEETING 27, PROJECT 24, RELATIONSHIP 18.

Transcription status (notes): CLEAR 78, UNCERTAIN 18, UNREADABLE 15.

Tags (notes): with tags 51, without tags 60.

Ranking (notes): one candidate 30, multiple 21, none / no-association 60.

## Labels

All 97 cases are `SYNTHETIC_DETERMINISTIC`. There are no
operator-adjudicated labels in this version.

Review state: 93 `APPROVED` (synthetic generator-validated), 4
`AMBIGUOUS_EXCLUDE`.

Unresolved ground-truth questions (not scored, not invented as operator
intent):

- `v1-ambiguous-grouping-r1` … `r4` — grouping is inherently ambiguous.

Adversarial / safety cases (still synthetic):

- prompt-injection replicas: `v1-injection-r1` … `r3`
- unreadable-fabrication traps: `v1-unreadable-trap-r1` … `r3`

## What you can do

Copy the decision template and set exactly one of:

- **approve** the digest as the Gate B v1 corpus
- **correct** specific case IDs (that forces a new corpus version)
- **reject** the corpus
- **mark ambiguous / exclude** additional case IDs

Do not edit database rows. Do not ingest personal GoodNotes to fill gaps.
If representative handwriting is later required, that is a separate
operator-controlled admission process, not this version.

## What this package does not do

- establish `MEASURED_B0`
- activate self-improvement evaluation
- enable automatic promotion
- run the live ChatLLM GoodNotes Task
- write production proposals
