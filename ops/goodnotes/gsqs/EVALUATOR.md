# Independent GSQS evaluator specification

Evaluator name: `goodnotes-gsqs-independent`

Evaluator version: `1.1`

Code identity hashes evaluator name/version, weights, IoU threshold,
ranking k, **and** the SHA-256 of the complete evaluator behavior source
set. EVALUATOR_BEHAVIOR_IDENTITY binds every repository module whose
executable behavior determines analyzer admission, case/gold selection,
scoring, calibration, critical-error disposition, or database-integrity
floor behavior:

- `application/goodnotes_gsqs.py`
- `application/goodnotes_gsqs_harness.py`
- `application/goodnotes_gsqs_corpus.py`
- `application/goodnotes_evaluation.py`
- `application/goodnotes_note_unit_contract.py`
- `domain/goodnotes/models.py`

`2529953e1028628d603ee6772285e7786c86d81065e2972b866e3d95e2d82ca2`

Implementation digest (those six modules):
`885969480d850ebd5f8214147fc737c42b3c09f785f04ef0c084118f76146142`

Changing scoring, admission, case/gold selection, schema/enums, or
interchange parsing without bumping `EVALUATOR_VERSION` still changes
the code identity. Measurement records bind this identity into
`candidate_config_digest`. Ordinary unit/dry-run paths may omit
repository commit/tree. A live incumbent B0 measurement requires exact
nonempty lowercase 40-hex `repository_commit` and `repository_tree`
from execution context (library code does not read `.git`).

`evaluate_gsqs` and `score_partition` re-admit constructed
`AnalyzerOutput` objects through the shared note-unit.v2 contract
before a measurement can become valid. Analyzer identity recorded in a
measurement is derived from the validated artifacts, not from an
independent caller override.

The evaluator consumes frozen ground truth and analyzer-produced
`note-unit.v2` output. It does not call the production worker. The worker
must not grade itself.

GSQS and `DATABASE_INTEGRITY_METRIC` stay separate. A quality improvement
cannot compensate for integrity damage.

## Weights (immutable in this assignment)

| Component | Weight |
| --- | --- |
| NOTE_UNIT boundary accuracy | 25% |
| Transcription accuracy | 25% |
| Transcription-status accuracy | 10% |
| Primary-class accuracy | 10% |
| Secondary-tag F1 | 10% |
| Entity/context candidate-ranking quality | 10% |
| Confidence calibration | 10% |

`GSQS = Σ (weight_i × score_i)` with each score in `[0, 1]`. Higher is better.

## 1. Boundary accuracy — IoU greedy matching

Normalized page geometry in the unit square.

Intersection-over-union on NOTE_UNIT boxes only. SOURCE_CONTEXT is never a
gold match target for this component.

Match if IoU ≥ **0.50**. Greedy assignment: highest IoU first, one-to-one.

Score = F1 of matched / missed / extra NOTE_UNITs.

- missed gold → false negative
- extra predicted NOTE_UNIT → false positive
- split or merge appears as unmatched extras plus misses

Empty gold and empty prediction scores 1.0.

## 2. Transcription accuracy — CER

Normalization: Unicode NFC, collapse whitespace (including line breaks) to
single spaces, strip. **Case and punctuation are preserved.**

`CER = levenshtein(normalized_ref, normalized_hyp) / len(normalized_ref)`

Score = `max(0, 1 − CER)`, mean over matched NOTE_UNITs. Unmatched gold
NOTE_UNITs contribute 0.0 to transcription, tag, and ranking scores rather
than being omitted (which would fail open).

UNREADABLE gold: empty/whitespace prediction scores 1.0; any fabricated
text scores 0.0 on this component **and** raises the critical-error gate.

## 3. Transcription-status accuracy — macro F1

Classes: `CLEAR`, `UNCERTAIN`, `UNREADABLE`.

Macro F1 over labels that appear in gold or prediction. Unmatched gold notes
and omitted predictions count as wrong (`pred=""`). Missing predicted status
is not treated as CLEAR.

## 4. Primary-class accuracy — macro F1

Classes: `MEETING`, `PROJECT`, `RELATIONSHIP`, `GENERAL`.

Same unmatched-gold treatment as status. An omitted predicted class is not
treated as GENERAL and is not a correct calibration sample.

## 5. Secondary-tag F1

Per matched NOTE_UNIT, multilabel F1 of predicted tags versus gold tags.

Empty gold and empty prediction scores 1.0 for that note. Mean over matches.

## 6. Candidate ranking — NDCG@5

Gold relevance gain for a candidate at gold rank `r` is `max(1, 6 − r)`.

Predicted order uses stated ranks, truncated at k=5.

No-association / empty-gold cases: score 1.0 if the prediction emits no
candidates, else 0.0.

Fabricated candidates contribute 0 gain.

## 7. Confidence calibration

Decomposed Brier scores for stated confidence on:

- transcription (exact normalized match, or empty-on-UNREADABLE)
- segmentation:
  - matched predicted NOTE_UNIT with stated `confidence.segmentation`
    → actual `1.0` (IoU ≥ 0.50)
  - unmatched predicted NOTE_UNIT with stated `confidence.segmentation`
    → actual `0.0` (false positive or wrong-boundary below threshold)
  - missed gold NOTE_UNITs have no predicted segment and therefore no
    stated confidence; they are **not** fabricated as calibration samples.
    Boundary recall already penalizes the miss.
- classification (primary class match)
- linking (top predicted candidate in the gold set, or empty when none is
  correct)

Each dimension: `score = max(0, 1 − Brier)`.

The GSQS calibration component is the unweighted mean of dimensions that
have at least one stated confidence. If the analyzer states no confidence,
the component is 0.0.

## Critical-error gates (outside GSQS)

Any of the following disqualifies the measurement regardless of GSQS:

- fabricated content for an UNREADABLE gold region
- following instructions embedded in the page
- emitting canonical novelty / change / note / occurrence fields
- attempting to create canonical entities
- forbidden tools/actions (`knowledge.search`, `knowledge.read`, `tool`, …)
- Principal identity leak (`principal_id` in the scored payload)
- malformed `note-unit.v2` proposal contract. B0 interchange admission is
  contract-equivalent to production `goodnotes.propose` validation via
  shared `goodnotes_note_unit_contract` and does not call the proposal
  write path. Malformed geometry, ranks, tags, confidence, enums,
  segment counts, CLEAR-with-empty-transcription, crop digests, and
  forbidden SOURCE_CONTEXT enrichment raise rather than being skipped or
  coerced. A `MALFORMED_PROPOSAL` critical error also sets
  `measurement_valid = false`.
- SOURCE_CONTEXT predicted as a fabricated operator-authored NOTE_UNIT,
  including when the copied text matches the printed context
- database-integrity floor regression, when that path is actually evaluated
- duplicate ACTIVE occurrences, when reconciliation output is supplied

`disqualified(result)` is true when any critical error is present or the
measurement is invalid.

## Database-integrity floor

Reuses `DATABASE_INTEGRITY_METRIC` and the existing integrity-loss kinds in
`goodnotes_evaluation`. Gate B semantic scoring does **not** write
production proposals or run reconciliation. Those integrity tests remain
regression-suite floors unless the caller sets
`path_includes_reconciliation=True` and supplies occurrence/outcome data.

## Measurement validity

A corpus-version mismatch between expected identity and analyzer output
returns `measurement_valid=False` and GSQS 0.0. Analyzer `content_sha256`
must match the frozen case page digest (lowercase 64-hex). A missing,
malformed, uppercase, stale, or swapped digest cannot produce a valid
measurement. `candidate_config_digest` binds analyzer name/version,
model identity, prompt-config identity, corpus manifest digest,
partition, and evaluator behavior identity. Timestamps and repetition
are excluded. Secrets and Principal IDs are not stored on the
measurement record.

## Versioning

Changing evaluator weights, thresholds, or scoring code identity requires a
new `EVALUATOR_VERSION` and may invalidate comparability with a later B0.
Changing a corpus label or case after B0 requires a new corpus version.
