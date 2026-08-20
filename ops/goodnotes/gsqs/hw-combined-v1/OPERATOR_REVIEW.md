# Gate B controlled handwriting corpus — operator review

coordination_request_id:
`REQ-MYPA-PR138-REMEDIATION-20260820-001`

This package is **repository-safe metadata only**. It does not contain
PDFs, page renders, or gold transcriptions.

Do not mark this corpus approved by merging the PR. Do not treat this
package as B0 authorization. Do not send private page content to
ChatLLM, Abacus, or any other external model.

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_REVIEW`

`b0_suitable = false`

`FIXED_LABELED_CORPUS_APPROVED = false`

`scoreable_page_count = 0`

Admitted pages are first-pass / agent-produced labels
(`review_state = PENDING`, `label_provenance = FIRST_PASS_LOCAL_INSPECTION`).
They are **not** operator-adjudicated. Copying
[`OPERATOR_DECISION.template.yaml`](OPERATOR_DECISION.template.yaml) is
the operator ratification path; this remediation does not execute it.

Machine copy: [`public_catalog.json`](public_catalog.json).

## Identity

| Field | Value |
| --- | --- |
| Handwriting corpus version | `gsqs-hw-combined-v1` |
| Private/public manifest digest | `238c22aa5b51fee3993a8e72e0b2ce9d696fb9f7b164a2853d1ddc3f59eabaed` |
| Combined Gate B identity | `bda6e66bbaf5ac068e5b2cf64a52f1e6c06975b5dd86294591de82fe8afdeb8b` |
| Synthetic layer (unchanged) | `gsqs-v2` / `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd` |
| Historical Moss tranche | `gsqs-hw-moss-v1` / `3bed9cc9bfe4a7cb3d28383232e940268ab3435429312c0977eb82a326158f9d` |
| Fixture class | `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` |
| Source layer | `CONTROLLED_HANDWRITING` |
| Label provenance | `FIRST_PASS_LOCAL_INSPECTION` |
| Evaluator | `goodnotes-gsqs-independent` `1.1` / `0ed12cb707bc259b2f982bc202523e60f7c899ab38a6c9ed4d58d98fdfbddf65` |
| Evaluator implementation digest | `2b55f7de7e5aea4df9dff8f5287aff228f127287b3c10bcfe202775ff1111c04` |
| Authorized source roots | the operator-named Moss, Kast, and Altman inbox directories (paths not repeated in JSON) |
| Private gold | local store only; each case binds `raster_sha256` + `label_sha256` |

Changing private gold truth or provenance/review_state changes
`label_sha256` / case digest and therefore the manifest digest.

## Source inventory

| | Count |
| --- | ---: |
| PDFs recursively found | 86 |
| Unique file SHA-256 | 86 |
| Exact file duplicates | 0 |
| Total pages | 2234 |
| Unreadable / corrupt PDFs | 0 |
| Admitted handwriting pages | 239 |
| Scoreable pages | 0 |
| Excluded pages | 1995 |
| NOTE_UNITs (first-pass, pending) | 482 |
| `UNREADABLE_REAL_WORLD_COVERAGE` | `NOT_OBSERVED` |

Cohort pages: Moss 40, Kast 104, Altman 2090.

## Partitions (group-level, admitted)

| Partition | Admitted pages | Leakage groups |
| --- | ---: | ---: |
| A | 101 | 28 |
| B | 73 | 1 |
| C | 65 | 1 |

`A ∩ B = ∅`, `A ∩ C = ∅`, `B ∩ C = ∅` at leakage-group level. Freeze-time
validation also refuses identical admitted `raster_sha256` values in
different groups or partitions. Excluded exact duplicates may share a
raster with the admitted member.

Corpus C remains a real holdout: do not expose its private gold or page
content to a future optimizer.

## Combined measurement policy

Do not pool `gsqs-v2` with this handwriting layer into one GSQS number.
Transcription B0, if later authorized **after operator adjudication and
a separate private-data disclosure authorization**, uses the handwriting
layer only.

## Privacy

| Check | Result |
| --- | --- |
| Raw PDFs committed to Git | no |
| Page renders committed to Git | no |
| Private transcripts committed to Git | no |
| External model disclosure | none |
| Live `goodnotes.propose` / ChatLLM scoring | not run |

## Readiness

The census is complete and prepared. Operator next action: adjudicate
the bound private-gold digest (approve / correct / reject). Until that
ratification rebinds `OPERATOR_ADJUDICATED` + `APPROVED`, the layer is
not B0-scoreable.

Ceiling until a later authorized phase:

- `MEASURED_B0 = NOT_YET_ESTABLISHED`
- `SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`
- `AUTOMATIC_PROMOTION = DISABLED`
- `EXTERNAL_MODEL_DISCLOSURE = NONE`
