# Gate B controlled handwriting corpus — operator review

coordination_request_id:
`REQ-MYPA-GOODNOTES-GATE-B-HANDWRITING-EXPANSION-20260820-002`

This package is **repository-safe metadata only**. It does not contain
PDFs, page renders, or gold transcriptions.

Do not mark this corpus approved by merging the PR. Do not treat this
package as B0 authorization. Do not send private page content to
ChatLLM, Abacus, or any other external model.

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_REVIEW`

`b0_suitable = true`

`FIXED_LABELED_CORPUS_APPROVED = false`

Machine copy: [`public_catalog.json`](public_catalog.json). Decision
template: [`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml).

## Why this is ready for operator review

The three operator-authorized GoodNotes roots were inventoried in full.
Every inventoried page has a public case. Admitted pages are
`APPROVED` with `OPERATOR_ADJUDICATED` provenance. Scoreable partitions
B and C are nonempty. Leakage groups do not cross partitions. Missing
real-world UNREADABLE is a documented limitation, not a rejection.
The former 75–150 page / 125–250 NOTE_UNIT floors are limitations
text only.

This review does **not** approve the corpus, run B0, or authorize
external-model disclosure.

## Identity

| Field | Value |
| --- | --- |
| Handwriting corpus version | `gsqs-hw-combined-v1` |
| Private/public manifest digest | `af12b8507da9bfae18a2dc5f024de410f144a44f02314289d300b1ad7cb1c547` |
| Combined Gate B identity | `d53718b834cd58efa8ad29753efeab237c150e7d7f60f8bda73cf343a9977d98` |
| Synthetic layer (unchanged) | `gsqs-v2` / `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd` |
| Historical Moss tranche | `gsqs-hw-moss-v1` / `3bed9cc9bfe4a7cb3d28383232e940268ab3435429312c0977eb82a326158f9d` |
| Fixture class | `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` |
| Source layer | `CONTROLLED_HANDWRITING` |
| Label provenance | `OPERATOR_ADJUDICATED` |
| Evaluator | `goodnotes-gsqs-independent` `1.1` / `4ba262fcd32f3a8e2801db9029a85d1a6d4844ab8aff868f33cc70caf3940f0e` |
| Authorized source roots | the operator-named Moss, Kast, and Altman inbox directories (paths not repeated in JSON) |
| Private gold | local store only; each case binds `raster_sha256` + `label_sha256` |

Changing private gold truth changes `label_sha256` and therefore the
case digest and manifest digest.

## Source inventory

| | Count |
| --- | ---: |
| PDFs recursively found | 86 |
| Unique file SHA-256 | 86 |
| Exact file duplicates | 0 |
| Total pages | 2234 |
| Unreadable / corrupt PDFs | 0 |
| Exact page-raster duplicate handling | one 86-page duplicate export excluded as `exact-page-duplicate`; admit the other member only |
| Candidate handwriting pages (admitted) | 239 |
| Render/parse failures | 0 |

Cohort pages: Moss 40, Kast 104, Altman 2090.

Sampling method: complete authorized census. No pages were manufactured
to hit a quota.

## Admitted corpus

| | Count |
| --- | ---: |
| Admitted handwriting pages | 239 |
| Scoreable pages (`APPROVED` + operator-adjudicated) | 239 |
| Excluded / non-handwriting pages | 1995 |
| NOTE_UNITs | 482 |
| Geometry quality | inspection-estimated |
| `UNREADABLE_REAL_WORLD_COVERAGE` | `NOT_OBSERVED` |
| PENDING admitted pages | 0 |

Exclusion reasons (page counts): typed-or-drawing-source 1652,
typed-only 196, exact-page-duplicate 86, typed-no-handwriting 30,
notebook-cover 14, signature-only 7, blank-template 5, blank 2,
typed-signature-only 2, sketch-no-text 1.

Contractor signature-only pages are excluded; they are not UNREADABLE
notes.

## Diversity (admitted pages)

| Axis | Distribution |
| --- | --- |
| Style | mixed-print-cursive 121, mixed-print-ink 91, sparse 26, slanted 1 |
| Transcription status | CLEAR 231, UNCERTAIN 8, UNREADABLE 0 |
| Primary class | PROJECT 153, MEETING 69, GENERAL 13, RELATIONSHIP 4 |
| Scenario / layout | daily-planner 102, oac-agenda 33, typed-agenda-plus-ink 24, typed-report 22, lined-notebook 20, typed-log 19, other layouts 19 |
| Tags | 239/239 pages carry candidate tags (1076 tag slots) |
| Ranking | 25/239 pages carry ranked candidates (77 ranks); 214 pages are explicit no-association |

Writer concentration remains high. Do not claim universal handwriting
accuracy. B0, if later authorized, measures this authorized corpus only.

## Partitions (group-level)

| Partition | Scoreable pages | NOTE_UNITs | Leakage groups (admitted) |
| --- | ---: | ---: | ---: |
| A | 101 | 208 | 28 |
| B | 73 | 129 | 1 |
| C | 65 | 145 | 1 |

`A ∩ B = ∅`, `A ∩ C = ∅`, `B ∩ C = ∅` at leakage-group level.

Related pages from one document/session stay in one group. Moss and
smaller Altman handwriting notebooks are in A. The large Altman
notebook family is in B. Kast is the C holdout.

Corpus C remains a real holdout: do not expose its private gold or page
content to a future optimizer.

## Combined measurement policy

Do not pool `gsqs-v2` (93 scoreable synthetic pages) with this
handwriting layer into one GSQS number. Report:

- synthetic GSQS: evaluator / regression / adversarial / schema
- handwriting GSQS: transcription, transcription-status, realistic
  segmentation/classification

Transcription B0, if later authorized, uses the handwriting layer only.
Synthetic `gsqs-v2` continues to test fabricated-unreadable traps.

## Privacy

| Check | Result |
| --- | --- |
| Raw PDFs committed to Git | no |
| Page renders committed to Git | no |
| Private transcripts committed to Git | no |
| External model disclosure | none |
| Live `goodnotes.propose` / ChatLLM scoring | not run |

## Readiness

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_REVIEW`

Operator next action: copy
[`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml),
cite the exact manifest digest, and record one of approve / correct /
reject. A later exact authorization is required before any
external-model B0 that would disclose private page content.

Ceiling until that later phase:

- `MEASURED_B0 = NOT_YET_ESTABLISHED`
- `SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`
- `AUTOMATIC_PROMOTION = DISABLED`
- `EXTERNAL_MODEL_DISCLOSURE = NONE`
