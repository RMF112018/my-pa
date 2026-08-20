# GoodNotes Durable Note Ingestion rollout (WP-15, dormant)

Repository-side feature flags, dry-run reporting, and the operator-gated
activation sequence for GoodNotes Durable Note Ingestion. Every gate defaults
off. This runbook does not ingest, write canonical notes, deliver a summary,
call Abacus, mutate NAS, or change the existing TBR Task.

**Production is not activated. Pilot is not activated.** No step below was
executed against a live GoodNotes root, a production or shared database, a live
Abacus account, `abacus.ai`, SharePoint, OneDrive, Teams, email, or live
personal data. Each live transition remains **operator-only** (`AGENTS.md` §5
and §8.2).

Related:

- [`goodnotes-and-model-operations.md`](goodnotes-and-model-operations.md) —
  bounded local OCR/review composition; inert until configured. It does not
  read these flags.
- [`goodnotes-durable-note-intelligence.md`](goodnotes-durable-note-intelligence.md)
  — dormant Abacus Task contract. Semantic Agent work dispatch reuses
  `MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED`.
- [`goodnotes-tbr-preservation.md`](goodnotes-tbr-preservation.md) — GN-09
  contract stays `GN-09_EXTERNAL_TASK_GATE_PENDING`. There is no TBR runtime;
  the optional-bridge flag does not implement or authorize a live bridge.

## Separable gates

All six are `bool = False` on `Settings`. An unconfigured process therefore
holds every gate off. `bootstrap.goodnotes_rollout` is what reads them.
`bootstrap.goodnotes` and `bootstrap.goodnotes_tbr` do not.

| Gate | Setting / environment | Default |
| --- | --- | --- |
| Durable GoodNotes note ingestion | `goodnotes_durable_note_ingestion_enabled` / `MY_PA_GOODNOTES_DURABLE_NOTE_INGESTION_ENABLED` | off |
| Semantic Agent work dispatch | `goodnotes_durable_note_intelligence_enabled` / `MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` | off |
| Canonical semantic writes | `goodnotes_canonical_semantic_writes_enabled` / `MY_PA_GOODNOTES_CANONICAL_SEMANTIC_WRITES_ENABLED` | off |
| User-facing summary/delivery | `goodnotes_user_facing_summary_delivery_enabled` / `MY_PA_GOODNOTES_USER_FACING_SUMMARY_DELIVERY_ENABLED` | off |
| Optional TBR bridge | `goodnotes_tbr_bridge_enabled` / `MY_PA_GOODNOTES_TBR_BRIDGE_ENABLED` | off |
| Optional Self-Improving optimizer | `goodnotes_self_improving_optimizer_enabled` / `MY_PA_GOODNOTES_SELF_IMPROVING_OPTIMIZER_ENABLED` | off |
| Current rollout stage | `goodnotes_rollout_stage` / `MY_PA_GOODNOTES_ROLLOUT_STAGE` | `observe-only` |

Turning a flag true does not perform the named action. Setting the intelligence
flag still does not create a live Abacus Task. Setting the TBR flag still does
not mutate the existing TBR Task and does not implement a live bridge.
Setting the optimizer flag still does not run an optimizer.

## Ordered stage

`MY_PA_GOODNOTES_ROLLOUT_STAGE` selects exactly one current stage. The default
is `observe-only`. Unknown values fail closed at process start. The six boolean
gates remain capability prerequisites and must be the consistent prefix for the
selected stage; a later or out-of-order flag does not drop to a lower stage, it
unlocks nothing. The durable-note orchestrator consumes this resolved stage
before each effectful step. `compose_durable_note_orchestrator` is still not
invoked from gateway startup.

| Stage | Boolean prefix (ingestion / intelligence / writes / delivery / TBR) |
| --- | --- |
| `observe-only` | all off |
| `page-identity-dry-run` | all off |
| `semantic-proposals-without-canonical-note-writes` | intelligence on |
| `canonical-writes-with-delivery-disabled` | intelligence and writes on |
| `new-only-summary-preview` | same as canonical writes |
| `operator-reviewed-delivery-canary` | intelligence, writes, and delivery on |
| `bounded-scheduled-operation` | ingestion plus the canary prefix |
| `optional-tbr-bridge` | all sequence flags including TBR — **unauthorized**; resolving or enabling this stage fails closed and does not mutate TBR |

## Activation sequence

None of these steps turns production on by existing in this document. Each live
transition requires a separate operator decision. Do not skip ahead: later
flags without their earlier prerequisites fail closed and unlock no live step.

1. **Observe-only.** Default. All sequence gates off. Bounded OCR/review
   composition and the GN-09 TBR contract stay as they are. The orchestrator
   observes/admits only.
2. **Page-identity dry run.** Same flags as observe-only; the stage setting
   selects this step. Split/render and lineage as a dry run. No semantic
   proposals, canonical writes, or delivery.
3. **Semantic proposals without canonical note writes.** Intelligence flag on;
   canonical writes, delivery, ingestion, and TBR remain off.
4. **Canonical writes with delivery disabled.** Intelligence and canonical
   writes on; delivery, ingestion, and TBR remain off.
5. **NEW-only summary preview.** Same flags as step 4; the stage setting
   selects preview. Preview is not live delivery. No attempt auto-send.
6. **Operator-reviewed delivery canary.** Intelligence, canonical writes, and
   delivery on; ingestion and TBR remain off. May record dormant attempt-ledger
   windows (PREPARED, ACKNOWLEDGED, or FAILED). Continuation of an existing
   preview-success run verifies exact ingestion and page/source identity before
   mutation, reuses completed lineage when consistent, restores only missing
   post-LINEAGE rasters, and replays the existing operator-local receipt.
   Successful PREVIEW/run/`ended_at` are not rewritten. Still does not send to
   Teams, email, OneDrive, SharePoint, or Abacus (`SENT` remains 0). A live
   canary is **operator-only**. A historical run whose PREVIEW stage was marked
   FAILED while a preview receipt remains is not a resume target.
7. **Bounded scheduled operation.** Ingestion plus the step-6 flags. Same live
   send posture as the canary: still off. This repository does not add a
   scheduler. Scheduling against a live root is **operator-only**.
8. **Optional TBR bridge.** Representing or enabling this stage fails closed.
   Live TBR Task mutation and a live bridge remain **unauthorized** until a
   later exact authorization; GN-09 stays `GN-09_EXTERNAL_TASK_GATE_PENDING`.

The Self-Improving optimizer is optional and outside this sequence. It does not
advance a step. Gate B repository infrastructure (`ops/goodnotes/gsqs/`) can
score synthetic analyzer output without writing proposals; it does not
activate the optimizer, establish `MEASURED_B0`, or enable automatic
promotion.

## Dry-run helper

`my_pa.bootstrap.goodnotes_rollout.rollout_report` reads the current flags and
the selected stage and returns the one current step they would permit, or none
when the combination fails closed. It does not ingest, write notes, deliver, or
call Abacus. It is not a live canary.

```bash
.venv/bin/python -c \
  "from my_pa.bootstrap.goodnotes_rollout import rollout_report; \
   from my_pa.bootstrap.settings import load_settings; \
   print(rollout_report(load_settings()))"
```

That command was not executed against production. It still requires
`MY_PA_DATABASE_URL` because `load_settings` does; pointing it at an unknown or
canonical physical database is **operator-only** and is not authorized here.

With every gate at its default, the report names `observe-only` only.
`production_activated` and `pilot_activated` stay false.

## Synthetic canaries versus live systems

Automated coverage is FAST/unit only:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_goodnotes_rollout.py \
  tests/unit/test_goodnotes_orchestrator.py \
  tests/contract/test_goodnotes_durable_note_canary.py \
  tests/unit/test_goodnotes_tbr_preservation.py \
  tests/unit/test_goodnotes_evaluation.py \
  tests/unit/test_goodnotes_gsqs.py \
  tests/unit/test_goodnotes_gsqs_corpus.py \
  tests/unit/test_goodnotes_gsqs_harness.py
```

Those suites use synthetic fixtures such as `"synthetic note"`. They do not
call Abacus, write a live note, deliver a summary, or touch TBR destinations.

Live Abacus Task create/edit/enable, OAuth `tools/list`, scheduled Task→remote
MCP, live GoodNotes/NAS ingestion, canonical production writes, user-facing
delivery, and a live TBR bridge remain **operator-only** and were not run.

## Rollback

1. Leave every `MY_PA_GOODNOTES_*_ENABLED` flag unset or false (the default).
   Leave `MY_PA_GOODNOTES_ROLLOUT_STAGE` unset or `observe-only`.
2. Bounded GoodNotes OCR/review composition continues to ignore these flags.
3. Leave the existing TBR Task unchanged. Do not enable, edit, or delete it
   from this runbook.
4. Do not enable, edit, or delete a live Abacus Task from this runbook.
5. Emergency withdrawal of the remote surface remains
   [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md).
