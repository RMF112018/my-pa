# Successor prompt — operator corpus approval and MEASURED_B0

coordination_request_id of the remediation that produced `gsqs-v2`:
`REQ-MYPA-GOODNOTES-GATE-B-CORPUS-V2-REMEDIATION-20260820-001`

This prompt is for a **later, separately authorized** phase. It is not
authorization to run now.

## Stop / do not

- Do not let ChatLLM / the production worker grade itself.
- Do not call production `goodnotes.propose` as the scoring path.
- Do not activate the Abacus optimizer.
- Do not set `AUTOMATIC_PROMOTION = ENABLED`.
- Do not ingest ordinary production GoodNotes or personal/business
  handwriting.
- Do not deploy, mutate OAuth/grants, schedule the Task, enable Gate C,
  modify TBR, or activate pilot/production.
- Do not use `gsqs-v1` to establish `MEASURED_B0`. Its disposition is
  `REJECT_FOR_B0`.

## Prerequisites

1. Operator has reviewed corpus `gsqs-v2` at manifest digest
   `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd`.
   Synthetic-regression approval is not by itself B0 readiness.
2. Operator has reviewed handwriting corpus `gsqs-hw-moss-v1` at
   manifest digest
   `3bed9cc9bfe4a7cb3d28383232e940268ab3435429312c0977eb82a326158f9d`
   **and** has either expanded the source population to the B0 floor or
   explicitly accepted the documented statistical limitation. Current
   state is `INSUFFICIENT_EVIDENCE`. External scoring of that layer
   requires a separate private-data disclosure authorization. The
   synthetic-phrase path in
   [`HANDWRITING_ADMISSION.md`](HANDWRITING_ADMISSION.md) remains
   available if the operator prefers non-personal samples instead.
3. Freeze Corpus B (scoreable partition B only) to the **approved**
   digest. Corpus C stays unused for prompt/config tuning.
4. Freeze evaluator `goodnotes-gsqs-independent` version `1.1` with code
   identity
   `4ba262fcd32f3a8e2801db9029a85d1a6d4844ab8aff868f33cc70caf3940f0e`
   (or a new evaluator version if scoring changed).
5. Confirm `FIXED_LABELED_CORPUS_APPROVED = true` for that digest only,
   and that the operator has stated the corpus is suitable for B0 — not
   regression-only.

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
