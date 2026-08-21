# Successor prompt — operator corpus approval and MEASURED_B0

This prompt is for a **later, separately authorized** phase. It is not
authorization to run now.

Failed reviewed head (invalidated by this remediation):
`16ea8949f7c740733105342d4ee89e53fa617ac4`

Current handwriting identities after GSQS-B-138 remediation:

- corpus: `gsqs-hw-combined-v1`
- manifest digest: `238c22aa5b51fee3993a8e72e0b2ce9d696fb9f7b164a2853d1ddc3f59eabaed`
- combined Gate B identity: `bda6e66bbaf5ac068e5b2cf64a52f1e6c06975b5dd86294591de82fe8afdeb8b`
- evaluator: `goodnotes-gsqs-independent` `1.1`
- evaluator code identity: `3673a9dbf99214dc6d724822682c2b5547c7a0343d56c7024956734f1516fc7d`
- evaluator implementation digest: `ca23ecebd5252c3924da0e29e7320f1fd301111290340a0105daeb8f3470b5e4`
- synthetic layer: `gsqs-v2` / `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd`

`b0_suitable = false`. Admitted labels are `PENDING` /
`FIRST_PASS_LOCAL_INSPECTION`. B0 is **not** immediately executable.

Cite the exact repository head/tree of the PR that carries this file
when that later phase is authorized. A later commit invalidates this
handoff.

## Stop / do not

- Do not let ChatLLM / the production worker grade itself.
- Do not call production `goodnotes.propose` as the scoring path.
- Do not activate the Abacus optimizer.
- Do not set `AUTOMATIC_PROMOTION = ENABLED`.
- Do not ingest ordinary / uncontrolled production GoodNotes or
  unmanaged personal handwriting.
- Do not send the controlled handwriting pages or private gold to an
  external model unless a **separate explicit private-data disclosure
  authorization** names this exact digest.
- Do not deploy, mutate OAuth/grants, schedule the Task, enable Gate C,
  modify TBR, or activate pilot/production.
- Do not use `gsqs-v1` to establish `MEASURED_B0`. Its disposition is
  `REJECT_FOR_B0`.
- Do not treat Corpus C private gold or page content as optimizer or
  prompt-tuning input.

## Controlled handwriting vs uncontrolled production data

The later B0 handwriting layer, if authorized, is only the
digest-bound `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` corpus
`gsqs-hw-combined-v1` after:

1. operator adjudication that rebinds those labels to
   `OPERATOR_ADJUDICATED` + `APPROVED` for this exact manifest;
2. `FIXED_LABELED_CORPUS_APPROVED = true` for that digest;
3. `b0_suitable = true` with nonempty scoreable B and C;
4. a separate private-data / external-model disclosure authorization.

Ordinary production GoodNotes ingest remains prohibited.

## Prerequisites

1. Operator has reviewed corpus `gsqs-v2` at manifest digest
   `e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd`.
   Synthetic-regression approval is not by itself B0 readiness.
2. Operator has adjudicated `gsqs-hw-combined-v1` at the digest above
   (historical `gsqs-hw-moss-v1` remains evidence, not an independent
   B0 floor). `UNREADABLE_REAL_WORLD_COVERAGE = NOT_OBSERVED` is a
   documented limitation; `gsqs-v2` still covers fabricated-unreadable
   traps. The former 75–150 page quota is not a rejection floor.
3. Freeze Corpus B (scoreable partition B only) to the **approved**
   digest. Corpus C stays unused for prompt/config tuning.
4. Freeze evaluator `goodnotes-gsqs-independent` `1.1` at the
   implementation-bound code identity above (or a new identity if
   scoring changed).
5. Confirm `FIXED_LABELED_CORPUS_APPROVED = true` for that digest only,
   and that the operator has stated the corpus is suitable for B0 — not
   regression-only.

## Incumbent

- analyzer_name: `chatllm-goodnotes-semantic`
- analyzer_version: `sit-1.0`

## Execution (only after the gates above)

1. For each scoreable Corpus B case, give the analyzer only the visual
   evidence and the interchange contract (`gsqs-analyzer-output-v1`).
   Capture `note-unit.v2` segments. Do not persist production proposals.
   2. Repeat the full Corpus B pass at least **3** independent times (more if
   observed variance warrants it). Record run/repetition number.
3. Score each pass with harness `score_partition` after `parse_interchange`
   (or equivalent validated admission). `evaluate_gsqs` re-admits constructed
   analyzer output through the shared note-unit.v2 contract; it is not a
   bypass around that contract. Per-segment `extra` is preserved into that
   contract and fail-closes when unknown or forbidden. Do not score
   raw/unvalidated `AnalyzerOutput` objects. Analyzer identity is derived
   from the raw scored artifacts even when segment admission later fails.
   Incumbent identity requirements are not bypassable by malformed output.
   Incumbent outputs require explicit `model_identity` and
   `prompt_config_identity`, plus exact repository commit/tree. Frozen-case
   `content_sha256` must match. Malformed interchange is fail-closed. The
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
