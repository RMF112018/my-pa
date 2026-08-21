# Gate B controlled handwriting corpus — operator review

coordination_request_id:
`REQ-MYPA-GOODNOTES-HW-OPERATOR-REBIND-20260821-001`

This package is **repository-safe metadata only**. It does not contain
PDFs, page renders, or gold transcriptions.

Do not treat this ratification as B0 authorization. Do not send private
page content to ChatLLM, Abacus, or any other external model.

`CONTROLLED_HANDWRITING_CORPUS = APPROVED`

`b0_suitable = true`

`FIXED_LABELED_CORPUS_APPROVED = true`

`scoreable_page_count = 239`

Admitted pages are operator-adjudicated
(`review_state = APPROVED`, `label_provenance = OPERATOR_ADJUDICATED`).
The operator decision is bound to the **pre-rebind** digest. Changing
review/provenance metadata changed per-case `label_sha256` and the public
manifest; the post-rebind digest is the current catalog identity.

Concrete decision:
[`OPERATOR_DECISION-20260821.yaml`](OPERATOR_DECISION-20260821.yaml).
Drive artifact `OPERATOR-DECISION-GSQS-HW-COMBINED-V1-20260821-001`
(`1uaQ2lShnR6BY77CaOOD3grjmIotib3dJNMzjZaL5tIM`).

Machine copy: [`public_catalog.json`](public_catalog.json).

## Identity

| Field | Value |
| --- | --- |
| Handwriting corpus version | `gsqs-hw-combined-v1` |
| Approved PRE-rebind manifest digest | `238c22aa5b51fee3993a8e72e0b2ce9d696fb9f7b164a2853d1ddc3f59eabaed` |
| Approved PRE-rebind combined identity | `bda6e66bbaf5ac068e5b2cf64a52f1e6c06975b5dd86294591de82fe8afdeb8b` |
| POST-rebind manifest digest | `636d671348cfba5b12b9e5032d5b3daee74f884aea101198ba69ed608ee40f22` |
| POST-rebind combined identity | `c3eb81e3fedb9590e6c33a38154722c0d9b697c7059d995c513c355a3143e070` |
| Synthetic layer (unchanged) | `gsqs-v2` / `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd` |
| Historical Moss tranche | `gsqs-hw-moss-v1` / `3bed9cc9bfe4a7cb3d28383232e940268ab3435429312c0977eb82a326158f9d` |
| Fixture class | `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` |
| Source layer | `CONTROLLED_HANDWRITING` |
| Label provenance (admitted) | `OPERATOR_ADJUDICATED` |
| Evaluator | `goodnotes-gsqs-independent` `1.1` / `3673a9dbf99214dc6d724822682c2b5547c7a0343d56c7024956734f1516fc7d` |
| Evaluator implementation digest | `ca23ecebd5252c3924da0e29e7320f1fd301111290340a0105daeb8f3470b5e4` (unchanged; handwriting catalog code is outside the evaluator behavior identity source set) |
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
| Scoreable pages | 239 |
| Excluded pages | 1995 |
| NOTE_UNITs | 482 |
| `UNREADABLE_REAL_WORLD_COVERAGE` | `NOT_OBSERVED` |

Cohort pages: Moss 40, Kast 104, Altman 2090.

## Partitions (group-level, admitted / scoreable)

| Partition | Admitted pages | Scoreable pages |
| --- | ---: | ---: |
| A | 101 | 101 |
| B | 73 | 73 |
| C | 65 | 65 |

`A ∩ B = ∅`, `A ∩ C = ∅`, `B ∩ C = ∅` at leakage-group level. Freeze-time
validation also refuses identical admitted `raster_sha256` values in
different groups or partitions. Excluded exact duplicates may share a
raster with the admitted member.

Corpus C remains a real holdout: do not expose its private gold or page
content to a future optimizer.

## Combined measurement policy

Do not pool `gsqs-v2` with this handwriting layer into one GSQS number.
Transcription B0, if later authorized **after a separate private-data
disclosure authorization**, uses the handwriting layer only.

## Privacy

| Check | Result |
| --- | --- |
| Raw PDFs committed to Git | no |
| Page renders committed to Git | no |
| Private transcripts committed to Git | no |
| External model disclosure | none |
| Live `goodnotes.propose` / ChatLLM scoring | not run |

## Readiness

The operator ratified the pre-rebind private-gold label set. This rebind
converted admitted first-pass labels to `OPERATOR_ADJUDICATED` +
`APPROVED`. Excluded pages remain non-scoreable. B0 was not run.

Ceiling until a later authorized phase:

- `MEASURED_B0 = NOT_YET_ESTABLISHED`
- `SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`
- `AUTOMATIC_PROMOTION = DISABLED`
- `EXTERNAL_MODEL_DISCLOSURE = NONE`
