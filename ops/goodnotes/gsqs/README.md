# Gate B GSQS evaluation infrastructure

Repository-side measurement system for Gate B of GoodNotes Durable Note
Intelligence. It holds a synthetic labeled corpus, an independent GSQS
evaluator, critical-error gates, and a side-effect-free B0 harness.

This is not another MCP interoperability project. It does not run the live
ChatLLM Task, does not establish `MEASURED_B0`, does not activate the Abacus
optimizer, and does not enable automatic promotion.

Existing A-X synthetic acceptance coverage (`99d529e` / PR #131) remains the
durable-note canary corpus. Gate B adds a separate labeled semantic corpus;
it does not replace A-X.

## Operator entry

- [`v1/OPERATOR_REVIEW.md`](v1/OPERATOR_REVIEW.md) — inspect size,
  partitions, distributions, exclusions, and approval state without reading
  Python.
- [`v1/operator_review.json`](v1/operator_review.json) — machine-readable
  review payload.
- [`v1/case_index.json`](v1/case_index.json) — per-case identity, partition,
  content digest, and labels (no page bytes).
- [`v1/OPERATOR_DECISION.template.yaml`](v1/OPERATOR_DECISION.template.yaml)
  — approve / correct / reject / mark-ambiguous without editing database rows.
- [`EVALUATOR.md`](EVALUATOR.md) — GSQS formulas, thresholds, and critical
  errors.
- [`SUCCESSOR-B0-PROMPT.md`](SUCCESSOR-B0-PROMPT.md) — next operator-authorized
  phase. ChatLLM must not grade itself.

## Current ceiling

`FIXED_LABELED_CORPUS = READY_FOR_OPERATOR_REVIEW`

`CORPUS_A_B_C = READY_TO_FREEZE_PENDING_OPERATOR_APPROVAL`

`INDEPENDENT_EVALUATOR = VALIDATED`

`CRITICAL_ERROR_GATES = VALIDATED`

`B0_HARNESS = READY`

`MEASURED_B0 = NOT_YET_ESTABLISHED`

`SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`

`AUTOMATIC_PROMOTION = DISABLED`

`FIXED_LABELED_CORPUS_APPROVED` remains false until explicit operator
approval. Changing a label or case after that approval requires a new corpus
version.
