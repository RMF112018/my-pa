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
  `MEASUREMENT-00N.json`, `B0_SUMMARY.json`, `EVIDENCE_INDEX.json`,
  and `disclosure_journal.jsonl` (started/reconciled request states only)
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
- Class-1 inference candidate: `ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json`
- `model_identity`: `routellm-goodnotes-b0-v1@sha256:<canonical-inference-config-digest>`
- evaluator: `goodnotes-gsqs-independent` `1.1`
- evaluator behavior identity:
  `3673a9dbf99214dc6d724822682c2b5547c7a0343d56c7024956734f1516fc7d`

Exact git commit/tree are supplied by the later authorization. Dirty
worktrees fail closed. `latest` and branch names are not identities.
The candidate file is Class 1 only: RouteLLM, `route-llm`, the five
operator display names, omitted generation settings, and the prompt
path. It does not contain endpoint, Path A/B, or provider API ids.

## Authorization

Copy `ops/goodnotes/gsqs/b0/EXECUTE_MEASURED_B0.template.json`. Fill every
blank, including:

- `route_llm_endpoint_origin` — exact `https://host[:port]`
- `route_llm_server_side_binding_mode` — `PLATFORM_ATTESTED` or
  `OPERATOR_DYNAMIC_SERVICE_AUTHORIZED`
- `route_llm_server_side_evidence_id` — nonempty evidence id
- `provider_model_mapping_evidence_id` — empty under Path B is valid;
  nonempty must match a local mapping file

The operation must be `EXECUTE_MEASURED_B0`. Prohibitions of Corpus C,
self-improvement, automatic promotion, and deployment must remain `true`.

Authorization is checked before any image would leave the trusted boundary.
Mismatch of commit, tree, corpus, combined identity, partition, analyzer,
prompt, evaluator, model identity, endpoint origin, Path A/B binding, or
repetition scope fails closed. There is no `--force` / `--skip-governance`
flag.

Runtime environment (never Git):

- `MY_PA_ROUTELLM_API_KEY`
- `MY_PA_ROUTELLM_BASE_URL` — origin must equal the authorized origin
- `MY_PA_GSQS_B0_RASTER_ROOT` — `{case_id}.png` (or jpg/jpeg/webp/gif)

## Preflight (no disclosure)

```text
python apps/cli/gsqs_b0.py preflight
```

Optional: `--authorization <artifact>` validates a proposed authorization
without making a model call. `--evidence-dir` writes public control files
only. Verdict is `GO` or `NO-GO`. `disclosure_would_occur` is always false.
Preflight never probes RouteLLM and never opens a disclosure journal.

## Execute (transport bound; disclosure still gated)

The RouteLLM incumbent transport is bound in this tree. That does **not**
authorize handwriting disclosure or establish `MEASURED_B0`. Execute still
requires independent exact-head review of the final head/tree **and** a
fresh `EXECUTE_MEASURED_B0` authorization bound to that reviewed
commit/tree, prompt SHA, candidate digest, endpoint origin, and Path A/B
evidence.

```text
python apps/cli/gsqs_b0.py execute \
  --authorization <filled-EXECUTE_MEASURED_B0.json> \
  --model-identity routellm-goodnotes-b0-v1@sha256:<digest> \
  --prompt-config ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt \
  --repetitions 3 \
  --evidence-dir ops/goodnotes/gsqs/b0/runs/<run_id> \
  --evaluator-corpus <local-private-evaluator-plane.json>
```

`--evaluator-corpus` is an explicit local file of evaluator-plane cases
using the existing `case_digest_payload` shape (`schema_version`:
`gsqs-evaluator-plane-v1`). It is not hashed into the Class-1 candidate.
The public catalog has no gold. Evaluator-plane exactness is checked
before `GET /v1/models` and before any `OUTBOUND_ATTEMPT_STARTED`. Gold
never enters the HTTP body, prompt, journal, or public evidence.

After evaluator validation, execute probes `GET /v1/models` (image-free,
max three attempts). Image POST remains a single attempt. Public
`RUN_CONTROL.json` is rebuilt from the disclosure journal on success,
failure, and unresolved restart.

Missing secrets, origin, Path A/B, or evidence dir keeps the unbound
refuse path. Image POST is single-attempt. A crash-safe journal at
`{evidence_dir}/disclosure_journal.jsonl` records `OUTBOUND_ATTEMPT_STARTED`
before transport receives image bytes. Restart with an unresolved STARTED
line fails closed. Public `EXTERNAL_MODEL_DISCLOSURE` is derived from that
journal. The model returns `{ "segments": [...] }` only; the application
assembles `gsqs-analyzer-output-v1`.

The public catalog does not contain evaluator gold. Execute fails closed
before image disclosure if evaluator-plane cases do not match the Partition
B census. Private gold stays off Git and off the analyzer plane.

Do not run execute as ordinary development. Binding this transport is not
authorization to disclose handwriting, inspect Corpus C, or set
`MEASURED_B0`.

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
