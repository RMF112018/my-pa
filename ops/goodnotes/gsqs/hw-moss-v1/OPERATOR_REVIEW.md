# Gate B controlled handwriting corpus — operator review

coordination_request_id:
`REQ-MYPA-GOODNOTES-GATE-B-HANDWRITING-CORPUS-20260820-001`

This package is **repository-safe metadata only**. It does not contain
PDFs, page renders, or gold transcriptions.

Do not mark this corpus approved by merging the PR. Do not treat this
package as B0 authorization. Do not send private page content to
ChatLLM, Abacus, or any other external model.

`CONTROLLED_HANDWRITING_CORPUS = INSUFFICIENT_EVIDENCE`

`b0_suitable = false`

`FIXED_LABELED_CORPUS_APPROVED = false`

Machine copy: [`public_catalog.json`](public_catalog.json). Decision
template: [`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml).

## Why this is not B0-ready

The authorized Moss PDF population was inventoried in full. Eligible
handwriting is smaller than the 75–150 page / 125–250 NOTE_UNIT target,
comes from one writer and one project family, has no genuinely
UNREADABLE pages, and first-pass labels are `PENDING` (inspection
geometry, not operator-adjudicated). Expanding the source set or
accepting this statistical limitation is an operator decision.

## Identity

| Field | Value |
| --- | --- |
| Handwriting corpus version | `gsqs-hw-moss-v1` |
| Private/public manifest digest | `3bed9cc9bfe4a7cb3d28383232e940268ab3435429312c0977eb82a326158f9d` |
| Combined Gate B identity | `fe0438c552a6c4a7f7fd9d59e0f3cbfef30e63f8ba33da1ff85c22b4297cc1a7` |
| Synthetic layer (unchanged) | `gsqs-v2` / `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd` |
| Fixture class | `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` |
| Source layer | `CONTROLLED_HANDWRITING` |
| Evaluator | `goodnotes-gsqs-independent` `1.1` / `4ba262fcd32f3a8e2801db9029a85d1a6d4844ab8aff868f33cc70caf3940f0e` |
| Authorized source root | the operator-named Moss inbox directory (path not repeated in JSON) |
| Private gold | local store only; each case binds `raster_sha256` + `label_sha256` |

Changing private gold truth changes `label_sha256` and therefore the
case digest and manifest digest.

## Source inventory

| | Count |
| --- | ---: |
| PDFs recursively found | 10 |
| Unique file SHA-256 | 10 |
| Exact file duplicates | 0 |
| Total pages | 40 |
| Unreadable / corrupt PDFs | 0 |
| Exact page-raster duplicate group | 1 group of 4 identical notebook-cover spines |
| Candidate handwriting pages | 27 |
| Render/parse failures | 0 |

## Admitted corpus

| | Count |
| --- | ---: |
| Admitted handwriting pages | 27 |
| Scoreable pages (`APPROVED` + operator-adjudicated) | 0 |
| Excluded / non-handwriting pages | 13 |
| NOTE_UNITs (first-pass, pending) | 66 |
| Geometry quality | inspection-estimated |

Exclusion reasons: notebook-cover 7, typed-no-handwriting 3,
blank-template 2, blank 1.

Sampling method: the eligible handwriting population is the entire
non-duplicate, non-blank, ink-bearing set. No additional pages were
manufactured to hit the 75–150 target.

## Diversity (admitted pages)

| Axis | Distribution |
| --- | --- |
| Style | mixed-print-cursive 22, sparse 4, slanted 1 |
| Transcription status | CLEAR 21, UNCERTAIN 6, UNREADABLE 0 |
| Primary class | PROJECT 12, MEETING 8, RELATIONSHIP 4, GENERAL 3 |
| Scenario / layout | lined-notebook 17, typed-agenda-plus-ink 9, mixed-typed-plus-ink 1 |
| Tags | 27/27 pages carry candidate tags (118 tag slots) |
| Ranking | 25/27 pages carry ranked candidates (77 ranks); 2 pages are explicit no-association |

There is no separate print-only vs cursive-only coverage at target
size. Template families (typed OAC agenda; lined daily notes) recur.

## Partitions (group-level)

| Partition | Pages | NOTE_UNITs | Leakage groups |
| --- | ---: | ---: | ---: |
| A | 6 | 11 | 4 |
| B | 14 | 33 | 2 |
| C | 7 | 22 | 2 |

`A ∩ B = ∅`, `A ∩ C = ∅`, `B ∩ C = ∅` at leakage-group level.

Related pages from one document/session stay in one group. Exact
duplicate covers share a group and are excluded. Sequential OAC agenda
exports share `lg-oac-tbr-residences` (holdout C). The daily-note
notebook is entirely in B.

Corpus C remains a real holdout: do not expose its private gold or page
content to a future optimizer.

## Combined measurement policy

Do not pool `gsqs-v2` (93 scoreable synthetic pages) with this
handwriting layer into one GSQS number. Report:

- synthetic GSQS: evaluator / regression / adversarial / schema
- handwriting GSQS: transcription, transcription-status, realistic
  segmentation/classification

Transcription B0, if later authorized, uses the handwriting layer only.

## Privacy

| Check | Result |
| --- | --- |
| Raw PDFs committed to Git | no |
| Page renders committed to Git | no |
| Private transcripts committed to Git | no |
| External model disclosure | none |
| Live `goodnotes.propose` / ChatLLM scoring | not run |

## Readiness

`CONTROLLED_HANDWRITING_CORPUS = INSUFFICIENT_EVIDENCE`

Operator next action: decide whether to expand the authorized source
population, adjudicate these pending labels as a limited qualitative
set, or accept the statistical limitation. A later exact authorization
is required before any external-model B0 that would disclose private
page content.
