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
- live evaluator behavior identity (this HEAD):
  `d2bd088a098f99d31637069fd339a67d665b80eb7aa97b403367cce1011a3fb7`
- historical identity at the evaluator-plane public/private bind
  (`e638c8a` / PR #149):
  `7dfe81005e931c073fc1e06264e20dedffc8dae530cb50822cac81baed10931f`
- historical identity at the GSQS B0 MCP evaluation merge (`1a48e99` /
  tree `2080e457…`):
  `c8a111c65f17ca292b48f12e4a4925d425675bdbcc4678fe3745db8ffe3c9583`
- historical identity at the 2026-08-21 operator decision
  (`5c52cc7` / tree `dda58686…`):
  `3673a9dbf99214dc6d724822682c2b5547c7a0343d56c7024956734f1516fc7d`
  Those earlier decisions are not reusable as `EXECUTE_MEASURED_B0` for
  this HEAD. Scoring formulas did not change. Page-level `primary_class`
  and `transcription_status` are independent public descriptors; GSQS
  scores per region. Handwriting admission still checks NOTE_UNIT
  `note_unit_count`, `candidate_tag_count`, and `ranked_candidate_count`
  and does not require a unique region class or status.

Exact git commit/tree are supplied by the later authorization. Dirty
worktrees fail closed. `latest` and branch names are not identities.
The candidate file is Class 1 only: RouteLLM, `route-llm`, the five
operator display names, omitted generation settings, and the prompt
path. It does not contain endpoint, Path A/B, or provider API ids.

## Authorization

Copy `ops/goodnotes/gsqs/b0/EXECUTE_MEASURED_B0.template.json`. Fill every
blank. The commissioned path binds the **MCP evaluation surface**:

- `mcp_evaluation_surface` — `stdio-isolated` (never the live remote MCP origin)
- `mcp_evaluation_binding_mode` — `ISOLATED_IN_PROCESS` or
  `OPERATOR_LOCAL_STDIO`
- `mcp_evaluation_evidence_id` — nonempty evidence id

The dormant HTTP execute path still recognizes:

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
prompt, evaluator, model identity, evaluation surface, or
repetition scope fails closed. There is no `--force` / `--skip-governance`
flag.

Runtime environment (never Git):

- `MY_PA_GSQS_B0_RASTER_ROOT` — `{case_id}.png` (or jpg/jpeg/webp/gif),
  required for `serve-eval-mcp` only
- `MY_PA_ROUTELLM_API_KEY` / `MY_PA_ROUTELLM_BASE_URL` — required only
  for the dormant HTTP `execute` path; **not** used by `score` or
  `serve-eval-mcp`

Do not ingest Partition-B rasters into live NAS knowledge. Do not use
`https://my-pa-mcp.bobby-fetting.me/mcp` as the B0 image source.
`goodnotes.propose` is not the scoring path.

## Preflight (no disclosure)

```text
python apps/cli/gsqs_b0.py preflight
```

Optional: `--authorization <artifact>` validates a proposed authorization
without making a model call. `--evidence-dir` writes public control files
only. Verdict is `GO` or `NO-GO`. `disclosure_would_occur` is always false.
Preflight never probes RouteLLM and never opens a disclosure journal.

## Connected-MCP workflow (ChatLLM initiation)

ChatLLM starts, drives inference, and observes a repetition through
production MCP tools `gsqs.start`, `gsqs.step`, and `gsqs.status`.
ChatLLM is the MCP client. RouteLLM routes models inside ChatLLM.
NAS never calls ChatLLM or RouteLLM and does not require an API key
or base URL for GSQS. Direct NAS RouteLLM HTTP is not the canonical
production path. ChatLLM does not choose campaign census, rasters,
or trusted interchange fields. Real handwriting remains fail-closed.

The server owns campaign identity, raster materialization, capture
persistence, and status. `gsqs.start` with
`authorization_id=synthetic-routellm-commissioning` returns PREPARED.
ChatLLM then calls `gsqs.step` to receive each case raster and to
submit semantic segments. `authorization_id=synthetic-b0-commissioning`
keeps the synthetic-fake server-local path. An MCP request timeout is
not a workflow failure for that fake path: production `gsqs.start`
returns after recording the run, and ChatLLM polls `gsqs.status`.

## Local prediction acquisition (stdio host)

Hosted ChatLLM cannot spawn `serve-eval-mcp` against the operator raster
root. An external RouteLLM MCP client is **not** assumed to exist. The
repository now owns a local execution host that:

- spawns `python apps/cli/gsqs_b0.py serve-eval-mcp` on the workstation
  that can read the checkout and raster root;
- enumerates the frozen census in exact order;
- writes `gsqs-analyzer-capture-v1` / `repetition-00N.json` for `score`.

Synthetic commissioning uses a generated 73-case fixture and the
`synthetic-fake` model client. Real RouteLLM HTTP remains uncommissioned
(`BLOCKED_ROUTELLM_CLIENT_ACTIVATION_AUTHORIZATION_REQUIRED`). Real
Partition-B acquisition requires a later `REAL_HANDWRITING_B0_EXECUTION`
authorization that this implementation does not admit.

```text
python apps/cli/gsqs_b0.py acquire-repetition \
  --authorization <gsqs-b0-acquisition-authorization-v1.json> \
  --repetition 1 \
  --campaign-fixture <synthetic-campaign.json> \
  --output ops/goodnotes/gsqs/b0/runs/<run_id>/rep-001 \
  --model-client synthetic-fake
```

The command runs **one** repetition, does not score, and does not start
the next repetition. Interruption invalidates the attempt; partial
evidence is preserved and is not resumable. See
[`B0_LOCAL_EXECUTION.md`](B0_LOCAL_EXECUTION.md).

## Commissioned path (RouteLLM-over-MCP evaluation, then admit-and-score)

The analyzer plane is **stdio-isolated**. `serve-eval-mcp` publishes
`goodnotes.work` and `goodnotes.content` (ImageContent PNG) only.
`goodnotes.propose` is withheld. A local host (above) must own the stdio
child; hosted ChatLLM is not that host. Captured `gsqs-analyzer-output-v1`
documents are admitted and scored locally:

```text
python apps/cli/gsqs_b0.py serve-eval-mcp \
  --authorization <filled-EXECUTE_MEASURED_B0.json> \
  --evidence-dir ops/goodnotes/gsqs/b0/runs/<run_id>

python apps/cli/gsqs_b0.py score \
  --authorization <filled-EXECUTE_MEASURED_B0.json> \
  --model-identity routellm-goodnotes-b0-v1@sha256:<digest> \
  --prompt-config ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt \
  --repetitions 3 \
  --evaluator-corpus <local-private-evaluator-plane.json> \
  --analyzer-output-dir <captured-repetitions> \
  --evidence-dir ops/goodnotes/gsqs/b0/runs/<run_id>
```

`score` does not read `MY_PA_ROUTELLM_*`, does not probe `GET /v1/models`,
and does not POST images. Handwriting `--evaluator-corpus` must be a local
`gsqs-evaluator-plane-v2` binding (`binding_kind`:
`controlled_handwriting`). Admission recomputes the public case digest
and the private `label_sha256` and derives scoring regions from that
label. It does not require `case_digest(CorpusCase)` to equal the public
census digest. Synthetic `gsqs-evaluator-plane-v1` remains valid only for
synthetic evaluator-plane tests. Extra A/C/unscoreable cases are rejected,
not filtered. Gold never enters the evaluation MCP, the capture documents,
or public evidence. `MEASURED_B0` remains `NOT_YET_ESTABLISHED` until a
later evidence-bound transition.

## Dormant HTTP execute (not commissioned)

The RouteLLM HTTP incumbent transport remains in-tree for the unbound
refuse path and for any later re-authorization of that transport. It is
**not** the commissioned B0 driver. Direct RouteLLM HTTP is unavailable
in this environment and is not to be invented.

```text
python apps/cli/gsqs_b0.py execute \
  --authorization <filled-EXECUTE_MEASURED_B0.json> \
  --model-identity routellm-goodnotes-b0-v1@sha256:<digest> \
  --prompt-config ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt \
  --repetitions 3 \
  --evidence-dir ops/goodnotes/gsqs/b0/runs/<run_id> \
  --evaluator-corpus <local-private-evaluator-plane.json>
```

`--evaluator-corpus` is an explicit local file. Controlled handwriting
uses `schema_version`: `gsqs-evaluator-plane-v2` with a
`controlled_handwriting` binding that carries the canonical private
label beside declared public-case and label SHA-256 values. Those values
are recomputed; they are not trusted. Synthetic workflows keep
`gsqs-evaluator-plane-v1` (`case_digest_payload`). The artifact is not
hashed into the Class-1 candidate. The public catalog has no gold. The
handwriting artifact must contain exactly the frozen scoreable
Partition-B cases. Validation checks ordered case IDs, raster/content
SHA, corpus version, scoreable-B eligibility, public case identity, and
private `label_sha256` before `GET /v1/models` and before any
`OUTBOUND_ATTEMPT_STARTED`. Extra A/C/unscoreable cases are rejected,
not filtered. Gold never enters the HTTP body, prompt, journal, or
public evidence.

After evaluator validation, execute probes `GET /v1/models` (image-free,
max three attempts). A successful response must contain a `data` list,
which may be empty. The probe is not used to infer provider mappings or
mutate `model_identity`. Image POST remains a single attempt. Public
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
