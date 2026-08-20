# Gate B GSQS evaluation infrastructure

Repository-side measurement system for Gate B of GoodNotes Durable Note
Intelligence. It holds a versioned labeled corpus, an independent GSQS
evaluator, critical-error gates, a side-effect-free B0 harness, and an
empty controlled-handwriting admission path.

This is not another MCP interoperability project. It does not run the live
ChatLLM Task, does not establish `MEASURED_B0`, does not activate the Abacus
optimizer, and does not enable automatic promotion.

Existing A-X synthetic acceptance coverage (`99d529e` / PR #131) remains the
durable-note canary corpus. Gate B adds a separate labeled semantic corpus;
it does not replace A-X.

## Operator entry

- [`v2/OPERATOR_REVIEW.md`](v2/OPERATOR_REVIEW.md) — current review target
  (`gsqs-v2` synthetic regression; handwriting still absent).
- [`v2/operator_review.json`](v2/operator_review.json) — machine-readable
  review payload, including per-partition distributions.
- [`v2/case_index.json`](v2/case_index.json) — per-case identity, partition,
  leakage group, content digest, and labels (no page bytes).
- [`v2/OPERATOR_DECISION.template.yaml`](v2/OPERATOR_DECISION.template.yaml)
  — approve / correct / reject / mark-ambiguous without editing database rows.
- [`HANDWRITING_ADMISSION.md`](HANDWRITING_ADMISSION.md) — operator sample
  requirements. No private image bytes are stored in Git.
- [`v1/OPERATOR_REVIEW.md`](v1/OPERATOR_REVIEW.md) — `gsqs-v1` is
  `REJECT_FOR_B0`; kept as a synthetic regression/canary.
- [`EVALUATOR.md`](EVALUATOR.md) — GSQS formulas, thresholds, and critical
  errors.
- [`SUCCESSOR-B0-PROMPT.md`](SUCCESSOR-B0-PROMPT.md) — next operator-authorized
  phase. ChatLLM must not grade itself.

## Corpus layers

1. **Deterministic synthetic regression** (`gsqs-v2`, and `gsqs-v1` as
   canary). Helvetica / Times-Italic PDFs. Valid for evaluator, schema,
   tags, ranking, critical errors, injection, and CI. Not handwriting.
2. **Controlled handwriting validation.** Admission records only until the
   operator supplies digest-bound synthetic non-personal samples.

## Partitioning (`gsqs-v2`)

Group-level A/B/C. Immutable `leakage_group_id` is the template family.
Scoreable groups are stratified by `scenario|class|status`; first group in
a stratum → B, second → C, rest → A. Non-scoreable groups → A. No group
may occupy two partitions. C is a true holdout and must not be used for
future optimizer prompts or config tuning.

`gsqs-v1` assignment remains case-level and is `REJECT_FOR_B0` because
replicas of one template can split.

## Current ceiling

`FIXED_LABELED_CORPUS = READY_FOR_OPERATOR_REVIEW`

`CORPUS_A_B_C = READY_TO_FREEZE_PENDING_OPERATOR_APPROVAL`

`INDEPENDENT_EVALUATOR = VALIDATED`

`CRITICAL_ERROR_GATES = VALIDATED`

`B0_HARNESS = READY`

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_OPERATOR_INPUT`

`GSQS_V1_B0_DISPOSITION = REJECT_FOR_B0`

`MEASURED_B0 = NOT_YET_ESTABLISHED`

`SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`

`AUTOMATIC_PROMOTION = DISABLED`

`FIXED_LABELED_CORPUS_APPROVED` remains false until explicit operator
approval of a digest. Changing a label or case after that approval requires
a new corpus version. Synthetic-regression approval still does not
establish `MEASURED_B0` while handwriting samples are absent.
