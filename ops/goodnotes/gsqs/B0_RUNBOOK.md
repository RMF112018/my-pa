# MEASURED_B0 runbook

This is the operator-facing procedure for the governed live-B0 runner.
It is **not** authorization to disclose handwriting pages or to establish
`MEASURED_B0`.

`b0_suitable = true` and `FIXED_LABELED_CORPUS_APPROVED = true` mean the
frozen handwriting corpus is eligible to be measured. They do not permit
an external model call. Live disclosure requires a later exact-head review
and a fresh `EXECUTE_MEASURED_B0` authorization bound to the reviewed
commit, tree, corpus digest, combined identity, analyzer, model, prompt,
and evaluator identities.

## What MEASURED_B0 means

`MEASURED_B0` is an empirical baseline: at least three complete authorized
Partition-B repetitions of one frozen candidate, scored by the independent
GSQS evaluator, with published variance. It is a measurement, not a
promotion decision. This repository still records:

- `MEASURED_B0 = NOT_YET_ESTABLISHED`
- `SELF_IMPROVEMENT_EVALUATION = NOT_YET_ACTIVATED`
- `AUTOMATIC_PROMOTION = DISABLED`
- Corpus C unused
- no deployment

Establishing `MEASURED_B0` later is a separate governed transition. It must
not activate self-improvement, automatic promotion, Corpus C, or deployment.

## Two-plane architecture

Analyzer plane (authorized visual inference only):

- current Partition-B raster
- public case id / corpus version / raster SHA-256
- frozen prompt/config and interchange schema

The analyzer must not receive gold transcriptions, gold segments,
evaluator diagnostics, expected scores, Corpus A or C gold, or a
filesystem handle to private gold. The adapter takes
`AnalyzerCaseInput`, not a gold-bearing `CorpusCase`.

Evaluator plane (private):

- frozen private gold
- admitted analyzer interchange via `parse_interchange()`
- `score_partition()` / `evaluate_gsqs()`
- `MeasurementRecord`

Gold never returns to the analyzer plane.

Evidence plane:

- public: `RUN_CONTROL.json`, census digest, `ANALYZER_CONFIG.json`,
  `MEASUREMENT-00N.json`, `B0_SUMMARY.json`, `EVIDENCE_INDEX.json`
- private diagnostics stay out of Git

## Frozen identities (approved handwriting corpus)

- corpus: `gsqs-hw-combined-v1`
- partition: **B only**, exactly 73 scoreable cases
- repetitions: at least 3, same candidate configuration
- post-rebind manifest:
  `636d671348cfba5b12b9e5032d5b3daee74f884aea101198ba69ed608ee40f22`
- post-rebind combined identity:
  `c3eb81e3fedb9590e6c33a38154722c0d9b697c7059d995c513c355a3143e070`
- incumbent: `chatllm-goodnotes-semantic` / `sit-1.0`
- prompt artifact: `ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt`
- evaluator: `goodnotes-gsqs-independent` `1.1`
- evaluator behavior identity:
  `3673a9dbf99214dc6d724822682c2b5547c7a0343d56c7024956734f1516fc7d`

Exact model identity and exact git commit/tree are supplied by the later
authorization. Dirty worktrees fail closed. `latest` and branch names are
not identities.

## Authorization

Copy `ops/goodnotes/gsqs/b0/EXECUTE_MEASURED_B0.template.json`. Fill every
blank. The operation must be `EXECUTE_MEASURED_B0`. Prohibitions of Corpus C,
self-improvement, automatic promotion, and deployment must remain `true`.

Authorization is checked before any image would leave the trusted boundary.
Mismatch of commit, tree, corpus, combined identity, partition, analyzer,
prompt, evaluator, or repetition scope fails closed. There is no
`--force` / `--skip-governance` flag.

## Preflight (no disclosure)

```text
python apps/cli/gsqs_b0.py preflight
```

Optional: `--authorization <artifact>` validates a proposed authorization
without making a model call. `--evidence-dir` writes public control files
only. Verdict is `GO` or `NO-GO`. `disclosure_would_occur` is always false.

## Execute (still blocked in this tree)

After independent exact-head review **and** a fresh authorization bound to
that reviewed commit/tree:

```text
python apps/cli/gsqs_b0.py execute \
  --authorization <filled-EXECUTE_MEASURED_B0.json> \
  --model-identity <exact-frozen-model> \
  --prompt-config ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt \
  --repetitions 3
```

Do not run this until those gates exist. The incumbent HTTP transport is
intentionally unbound in this tree; execute refuses disclosure even when
preflight is `GO`. Binding a live transport is a later change and requires
another exact-head review plus rebound authorization.

## Evidence

Public artifacts belong under `ops/goodnotes/gsqs/b0/runs/<run_id>/` (gitignored).
Private gold, raw page bytes, and evaluator diagnostics must not be committed.

## Invalidation

Abort or invalidate rather than continue when any case is missing, duplicated,
replaced, or identity-drifted; when analyzer output fails interchange
admission; when a repetition uses a different candidate configuration; or when
the worktree is dirty.

## Explicitly not authorized

- self-improvement
- automatic promotion
- Corpus C evaluation or prompt use
- deployment
- sending private gold to any external model
