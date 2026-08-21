# GoodNotes Durable Note Intelligence (dormant Abacus Task)

The proposed regular Agent Task **GoodNotes Durable Note Intelligence** is a
repository contract only. This runbook records the operating constraints, the
synthetic canary, and the activation steps that remain unauthorized.

The repository-side durable-note pipeline is now runnable in tests and through
a dormant composition helper: observe → settle → split/render → lineage →
content-ready → waiting-proposal → reconcile → NEW-only preview/receipt.
Lineage completion is not terminal success. Terminal `SUCCEEDED` is recorded
only after repository-side reconcile and preview. Later continuation of the
same `request_id` verifies ingestion identity and persisted page/source
evidence **before** any FAILED→RUNNING mutation. Standalone lineage replay
performs the same persisted page/version identity check before returning
existing positions and before FAILED→RUNNING. Completed-stage prefix
validation covers the full prerequisite chain even when LINEAGE itself is
absent. Completed LINEAGE is skipped only after that proof; missing rasters
in the post-LINEAGE / pre-CONTENT_READY crash window are restored
deterministically without rerunning lineage. Completed RECONCILE and PREVIEW
require proposal evidence; a legitimate zero-change reconciliation (proposal
present, zero change rows) is valid and yields a suppressed NEW-only receipt
(`summary_hash` of the empty body). Successful PREVIEW/run terminal state and
the original successful `ended_at` are monotonic. The
operator-reviewed delivery canary records PREPARED → local receipt replay →
ACKNOWLEDGED on the attempt ledger and does not send externally (`SENT` stays
0). A historical failed canary that left PREVIEW FAILED while a preview receipt
still exists is fail-closed and is not a resume target.

Production persistence is
`PostgresDurableNoteStore` on a caller-supplied connection; the composition
helper does not open a connection or auto-wire the gateway. Live Teams/email
delivery, live Abacus inference, and production activation remain unauthorized.

**Production is not activated.** No step below was executed against a live
Abacus account, a live Abacus Task, `abacus.ai`, or live personal data. Steps
marked **operator-only** remain reserved to the operator (`AGENTS.md` §5 and
§8.2).

Related:

- [`goodnotes-and-model-operations.md`](goodnotes-and-model-operations.md) —
  bounded local OCR/review composition; inert until configured.
- [`goodnotes-durable-note-rollout.md`](goodnotes-durable-note-rollout.md) —
  WP-15 dormant rollout gates. Production and pilot remain off.
- [`managed-knowledge-context.md`](managed-knowledge-context.md) — synthetic
  canary versus live Abacus for `context.prepare`.
- [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md) — separately enabled
  remote MCP; default remote writes off.
- [`../abacus/goodnotes-durable-note-intelligence.task.json`](../abacus/goodnotes-durable-note-intelligence.task.json)
  — frozen draft Task artifact marked `DRAFT_NOT_ACTIVATED`.
- [`../goodnotes/gsqs/README.md`](../goodnotes/gsqs/README.md) — Gate B
  GSQS corpus, independent evaluator, and B0 harness. Corpus is ready for
  operator review. `MEASURED_B0` is not established; self-improvement and
  automatic promotion stay off. The live Task is not run from that package.

## Proposed Task contract

The Task may call only the my-pa MCP tools `goodnotes.work`,
`goodnotes.content`, and `goodnotes.propose`. Those names are
Capability/Command-derived. `goodnotes.content` is a pathless, Principal-bound
read of the pinned visual PNG used for page identity. It does not return a
filesystem path or a raw PDF, and it does not route through `knowledge.search`
or `knowledge.read`. `goodnotes.work` remains metadata-only. `tools/list` for
`goodnotes.propose` publishes discriminated `segments[]` variants so a fresh
ChatLLM session can construct a valid proposal without repository inspection:
SOURCE_CONTEXT is the base/v1 region shape under both schema versions; NOTE_UNIT
under `note-unit.v1` uses that same vocabulary; NOTE_UNIT under `note-unit.v2`
may add candidate_tags, ranked_candidates, confidence, and
transcription_status. Runtime validation is unchanged. Remote MCP still stamps
`idempotency_key`; callers must not send it.

The Task:

- requests only bounded my-pa work (`goodnotes.work`);
- inspects handwriting through `goodnotes.content` when the Agent needs the
  pinned raster;
- analyzes immutable page-version content/context;
- returns schema-valid proposals (`goodnotes.propose`);
- has no direct database, source, or destination writes;
- fail-closes when MCP, auth, or content transfer fails (no proposal write);
- never produces a canonical NEW-only summary itself. Repository-side preview
  is owned by the durable-note orchestrator, not this Task.

Out of the allowlist, including as a substitute work plane: `knowledge.search`,
`knowledge.read`, `context.prepare`, `review.decide`, Task/document authoring,
GoodNotes reconcile, operator correction, and NEW-only delivery. Reconcile,
correction, and delivery are not MCP capabilities and must not be added for
this Task.

`MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` defaults to false. The
process-local gate is read by `bootstrap.goodnotes_durable_note`. Bounded
GoodNotes OCR/review composition does not read it. Setting the flag true does
not create a live Abacus Task. The orchestrator is not invoked from gateway
startup.

## Synthetic canaries versus live Abacus

The protocol harness is automated against `ApplicationService.invoke` and MCP
tool descriptions in
`tests/contract/test_goodnotes_durable_note_canary.py`. Pipeline stage
advancement, including lineage-not-terminal and crash/resume, is covered by
`tests/unit/test_goodnotes_orchestrator.py`. PostgreSQL stage/raster persistence
through `PostgresDurableNoteStore` is covered by
`tests/database/test_goodnotes_orchestrator.py`. Both use synthetic fixtures only
(`"synthetic note"`, admitted vector PDFs). Live Abacus OAuth, remote
`tools/list`, actual ChatLLM/Agent Task invocation, and scheduled Task→remote
MCP expiry/refresh proof are **not** in that suite and remain operator-gated.
This runbook does not claim Abacus inference is live.

No command block in this runbook was executed against production, a live
Abacus account, or live personal data.

## Activation sequence

None of these steps turns production on by existing in this document. Marked
steps require a separate operator decision. GN-09 TBR live bridge and WP-15
production activation are out of scope here; see
[`goodnotes-tbr-preservation.md`](goodnotes-tbr-preservation.md) and
[`goodnotes-durable-note-rollout.md`](goodnotes-durable-note-rollout.md).

1. Merge the reviewed pull request.
2. Local canary: FAST synthetic suite, including
   `tests/contract/test_goodnotes_durable_note_canary.py` and
   `tests/unit/test_goodnotes_orchestrator.py`.
3. Confirm the frozen artifact still reads `DRAFT_NOT_ACTIVATED` and names
   `goodnotes.work` / `goodnotes.content` / `goodnotes.propose`.
4. Live Abacus Task create, edit, enable, or disable — **operator-only**. Not
   authorized by this change.
5. OAuth canary (`tools/list` against a registered client) — **operator-only**.
6. Scheduled Task→remote MCP grant expiry and refresh proof — **operator-only**.
7. Production activation — **operator-only**.
8. Gate B B0 establishment against Corpus B — **operator-only**, and only
   after corpus approval. The successor prompt is
   [`../goodnotes/gsqs/SUCCESSOR-B0-PROMPT.md`](../goodnotes/gsqs/SUCCESSOR-B0-PROMPT.md).
   This runbook does not authorize that run.

## Rollback

1. Leave `MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` false (the
   default). Canonical GoodNotes OCR/review, work, content, and propose paths
   stay; this gate does not withdraw them.
2. Do not enable, edit, or delete a live Abacus Task from this runbook. Live
   Task mutation is **operator-only**.
3. Emergency withdrawal of the remote surface remains
   [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md).
