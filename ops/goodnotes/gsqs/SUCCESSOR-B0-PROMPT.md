# Successor prompt — operator corpus approval and MEASURED_B0

coordination_request_id of the infrastructure that built this package:
`REQ-MYPA-GOODNOTES-GATE-B-EVALUATION-20260820-001`

This prompt is for a **later, separately authorized** phase. It is not
authorization to run now.

## Stop / do not

- Do not let ChatLLM / the production worker grade itself.
- Do not call production `goodnotes.propose` as the scoring path.
- Do not activate the Abacus optimizer.
- Do not set `AUTOMATIC_PROMOTION = ENABLED`.
- Do not ingest personal GoodNotes.
- Do not deploy, mutate OAuth/grants, schedule the Task, enable Gate C,
  modify TBR, or activate pilot/production.

## Prerequisites

1. Operator has approved corpus `gsqs-v1` at manifest digest
   `971083804db9fc46295db1ea64dcf2288d4aa1feaddd1ac8a26345f3579bb6d3`
   (or a **new** corpus version if labels changed).
2. Freeze Corpus B (scoreable partition B only) to that digest.
3. Freeze evaluator `goodnotes-gsqs-independent` version `1.0` with code
   identity
   `ed24cf1172e88c88dd5ede15a47783f582a643c7f6eb7a4c22b9227d5bbc3011`
   (or a new evaluator version if scoring changed).
4. Confirm `FIXED_LABELED_CORPUS_APPROVED = true` for that digest only.

## Incumbent

- analyzer_name: `chatllm-goodnotes-semantic`
- analyzer_version: `sit-1.0`

## Execution

1. For each scoreable Corpus B case, give the analyzer only the visual
   evidence and the interchange contract (`gsqs-analyzer-output-v1`).
   Capture `note-unit.v2` segments. Do not persist production proposals.
2. Repeat the full Corpus B pass at least **3** independent times (more if
   observed variance warrants it). Record run/repetition number.
3. Score each pass with the repository function `evaluate_gsqs` / harness
   `score_partition`. The analyzer output is an interchange artifact. The
   evaluator is independent.
4. Publish component scores, GSQS, critical errors, and
   `measurement_valid` per repetition.
5. Compute mean, median, standard deviation (or equivalent spread), and
   critical-error frequency. Do **not** invent a promotion threshold. Future
   improvement must exceed this measured noise.
6. Only then set `MEASURED_B0 = ESTABLISHED` with the published
   distributions and exact corpus/evaluator identities.
7. Leave `SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED` unless a
   further authorization exists.
8. Leave `AUTOMATIC_PROMOTION = DISABLED`. Operator approval remains
   required for any later candidate promotion. Corpus C is unused until
   a candidate is promoted against B.

## Interchange

Each case produces a document:

- schema_version: `gsqs-analyzer-output-v1`
- corpus_version, case_id, content_sha256
- analyzer_name, analyzer_version
- proposal_schema_version: `note-unit.v2`
- segments[] matching the published NOTE_UNIT / SOURCE_CONTEXT contract

Do not fabricate ChatLLM output inside the repository harness. The
repository dry-run (`deterministic-gold-replay`) is only a harness
self-test.

## Database integrity

Gate B semantic scoring does not execute reconciliation. Keep
`DATABASE_INTEGRITY_METRIC` as the regression-suite floor. Do not invent
database effects to calculate GSQS.

## Success output

Exact HEAD/tree, corpus digest, evaluator identity, per-pass GSQS and
components, variance summary, critical-error list, confirmation that
automatic promotion remains disabled, and
`MEASURED_B0 = ESTABLISHED` only if the measurement is valid.
