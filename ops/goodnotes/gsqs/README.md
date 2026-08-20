# Gate B GSQS evaluation infrastructure

Repository-side measurement system for Gate B of GoodNotes Durable Note
Intelligence. It holds a versioned labeled corpus, an independent GSQS
evaluator, critical-error gates, a side-effect-free B0 harness, and a
repository-safe digest-bound handwriting catalog (`gsqs-hw-combined-v1`,
with historical `gsqs-hw-moss-v1` preserved).

This is not another MCP interoperability project. It does not run the live
ChatLLM Task, does not establish `MEASURED_B0`, does not activate the Abacus
optimizer, and does not enable automatic promotion.

Existing A-X synthetic acceptance coverage (`99d529e` / PR #131) remains the
durable-note canary corpus. Gate B adds a separate labeled semantic corpus;
it does not replace A-X.

## Operator entry

- [`v2/OPERATOR_REVIEW.md`](v2/OPERATOR_REVIEW.md) — synthetic regression
  review target (`gsqs-v2`; still not handwriting-B0).
- [`hw-combined-v1/OPERATOR_REVIEW.md`](hw-combined-v1/OPERATOR_REVIEW.md) —
  complete Moss + Kast + Altman handwriting census. State:
  `READY_FOR_REVIEW`. No private bytes in Git.
- [`hw-moss-v1/OPERATOR_REVIEW.md`](hw-moss-v1/OPERATOR_REVIEW.md) —
  historical Moss-only tranche. State: `INSUFFICIENT_EVIDENCE`.
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
2. **Controlled handwriting validation.** Digest-bound private gold from
   the operator-authorized Moss, Kast, and Altman roots. Repository-safe
   catalog: [`hw-combined-v1/`](hw-combined-v1/). State:
   `CONTROLLED_HANDWRITING_CORPUS = READY_FOR_REVIEW`.
   Historical Moss-only package: [`hw-moss-v1/`](hw-moss-v1/).
   No private image bytes or transcriptions are in Git.

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

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_REVIEW`

`GSQS_V1_B0_DISPOSITION = REJECT_FOR_B0`

`MEASURED_B0 = NOT_YET_ESTABLISHED`

`SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`

`AUTOMATIC_PROMOTION = DISABLED`

`FIXED_LABELED_CORPUS_APPROVED` remains false until explicit operator
approval of a digest. Changing a label or case after that approval requires
a new corpus version. Synthetic-regression approval still does not
establish `MEASURED_B0`. The handwriting layer is the complete eligible
census from the three authorized roots; B0, if later authorized, measures
that corpus only. The former 75–150 page quota is a limitation, not a
rejection floor.
