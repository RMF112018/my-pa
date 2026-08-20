# Gate B v2 corpus — operator review

coordination_request_id:
`REQ-MYPA-GOODNOTES-GATE-B-CORPUS-V2-REMEDIATION-20260820-001`

This package is for corpus review. You do not need to read Python.

**Do not mark this corpus approved by merging the PR.** Approval is a
separate operator decision recorded in a filled
[`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml)
(or equivalent signed note) that cites the digest below.

`FIXED_LABELED_CORPUS_APPROVED` is currently **false**.

`b0_suitable` is currently **false**. This version is a deterministic
synthetic regression corpus. Controlled real handwriting is a separate
layer (`gsqs-hw-moss-v1`) and is `INSUFFICIENT_EVIDENCE`.

Machine copy: [`operator_review.json`](operator_review.json). Per-case
identity (no page bytes): [`case_index.json`](case_index.json).
Handwriting admission: [`../HANDWRITING_ADMISSION.md`](../HANDWRITING_ADMISSION.md).

## Identity

| Field | Value |
| --- | --- |
| Corpus version | `gsqs-v2` |
| Generator | `gsqs-v2-generator-1` |
| Manifest digest | `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd` |
| Fixture class | synthetic, non-personal, deterministic PDF (`gsqs-synthetic-pdf` / `helvetica-times-italic-v1`) |
| Source layer | `SYNTHETIC_REGRESSION` (96); `CONTROLLED_HANDWRITING` (0) |
| Personal handwriting | none committed |
| Production GoodNotes pages | none |
| Existing A-X acceptance corpus | preserved; not replaced |
| `gsqs-v1` disposition | `REJECT_FOR_B0` (kept as a synthetic canary only) |

A PDF is not a note. A page is not a note. Each case binds SOURCE_CONTEXT
and NOTE_UNIT regions with normalized geometry and a SHA-256 of the
generated single-page PDF. The case digest also binds every score-relevant
gold field (geometry, transcription, status, class, tags, ranking,
confidence, flags, scenario, difficulty, adversarial state, provenance,
review, partition, leakage group, source layer, renderer, content hash).

Changing a score-relevant label after freeze necessarily changes this
digest. Raster hash alone does not bind labels.

## Size

| | Count |
| --- | ---: |
| Pages (cases) | 96 |
| Scoreable pages | 93 |
| Labeled NOTE_UNITs | 114 |
| Synthetic-regression pages | 96 |
| Controlled-handwriting pages | 0 |
| Handwriting samples present | no |
| Excluded / ambiguous pages | 3 |

Target was 60–100 pages and 100–150 NOTE_UNITs.

## Layers

1. **Deterministic synthetic regression.** Repository-safe PDF fixtures
   using Helvetica / Times-Italic. Valid for evaluator correctness,
   schema, tags, ranking, critical errors, prompt injection, and CI.
   **Not** a production-relevant handwriting transcription baseline.
2. **Controlled handwriting validation.** Separate layer
   [`../hw-moss-v1/OPERATOR_REVIEW.md`](../hw-moss-v1/OPERATOR_REVIEW.md).
   State: `CONTROLLED_HANDWRITING_CORPUS = INSUFFICIENT_EVIDENCE`.
   This synthetic freeze still contains zero handwriting pages.

Suitable for: **regression-only use**. **Not** suitable for establishing
`MEASURED_B0` until the operator admits a digest-bound synthetic
handwriting sample set and later approves that combined corpus.

## Partition algorithm (group-level)

Every case carries an immutable `leakage_group_id` naming the underlying
template/layout/scenario family. Partitioning is at **group** level:

1. Non-scoreable groups (ambiguous / pending / rejected) go to **A** and
   are not scored.
2. Scoreable groups are stratified by
   `scenario | primary_class | transcription_status`.
3. Within each stratum, sorted group ids assign first → **B**, second →
   **C**, remainder → **A**.
4. Every case in a group occupies that group's partition. Replicas of the
   same template cannot split across A/B/C.

Holdout C therefore contains distinct templates, not the same layout with
substituted text. Context-only pages use the same layout boxes as
note-bearing pages (`block` / `margin` / `stacked`), not a shared
full-width rectangle with a different word.

Proven empty intersections:

`intersection(A.groups, B.groups) = ∅`

`intersection(A.groups, C.groups) = ∅`

`intersection(B.groups, C.groups) = ∅`

## Partitions (scoreable pages / leakage groups)

| Partition | Role | Scoreable pages | Leakage groups (incl. unscored) |
| --- | --- | ---: | ---: |
| A | development / future optimizer-visible | 33 | 36 |
| B | fixed baseline and candidate comparison | 30 | 30 |
| C | true holdout; not for prompt/config tuning | 30 | 30 |

Physical A also holds three excluded ambiguous pages (not scored). B and C
each contain every primary class, CLEAR / UNCERTAIN / UNREADABLE, a
context-only page, ranking/tag scenarios, and adversarial cases.

`CORPUS_A_B_C = READY_TO_FREEZE_PENDING_OPERATOR_APPROVAL`

## Distributions by partition (scoreable)

### Primary class (NOTE_UNITs)

| Class | A | B | C |
| --- | ---: | ---: | ---: |
| GENERAL | 14 | 14 | 14 |
| MEETING | 11 | 8 | 8 |
| PROJECT | 10 | 7 | 7 |
| RELATIONSHIP | 8 | 5 | 5 |

### Transcription status (NOTE_UNITs)

| Status | A | B | C |
| --- | ---: | ---: | ---: |
| CLEAR | 32 | 23 | 23 |
| UNCERTAIN | 6 | 6 | 6 |
| UNREADABLE | 5 | 5 | 5 |

### Scenarios (scoreable pages)

Each of A/B/C contains one page of: agenda-table, arrow-leader,
context-only, crossed-out, dense, follow-up, italic-style, low-contrast,
multi-candidate, multi-tag, near-typed, no-candidate, no-tag,
obscured-trap, one-candidate, prompt-injection, visually-close; plus
single-note 12 and multiple-notes (A: 4, B: 1, C: 1).

## Tags / ranking / adversarial (corpus-wide scoreable notes)

Tags: with tags 51, without tags 60.

Ranking: one candidate 30, multiple 21, none / no-association 60.

Adversarial / safety cases:

- prompt-injection: `v2-injection-{block,margin,stacked}`
- obscured unreadable traps: `v2-scribble-trap-{block,margin,stacked}`

UNREADABLE gold NOTE_UNITs render deterministic scribble strokes. Gold
transcription remains `""`. The PDF bytes do not contain the literal
`UNREADABLE` status label.

## Labels

All 96 cases are `SYNTHETIC_DETERMINISTIC`. There are no
operator-adjudicated labels in this version.

Review state: 93 `APPROVED` (synthetic generator-validated), 3
`AMBIGUOUS_EXCLUDE`.

Unresolved ground-truth questions (not scored):

- `v2-ambiguous-grouping-{block,margin,stacked}` — grouping is inherently
  ambiguous.

Provenance: synthetic deterministic only. Personal data: false.

## What you can do

Copy the decision template and set exactly one of:

- **approve** the digest as the Gate B **synthetic-regression** corpus
  (this still does **not** establish `MEASURED_B0`)
- **correct** specific case IDs (that forces a new corpus version)
- **reject** the corpus
- **mark ambiguous / exclude** additional case IDs

Separately, provide the controlled handwriting sample set described in
[`../HANDWRITING_ADMISSION.md`](../HANDWRITING_ADMISSION.md). Do not edit
database rows. Do not ingest ordinary production GoodNotes.

## What this package does not do

- approve itself
- establish `MEASURED_B0`
- activate self-improvement evaluation
- enable automatic promotion
- run the live ChatLLM GoodNotes Task
- write production proposals
- claim production-relevant handwriting transcription performance
