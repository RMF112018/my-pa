# GoodNotes Durable Note Intelligence (dormant Abacus Task)

The proposed regular Agent Task **GoodNotes Durable Note Intelligence** is a
repository contract only. This runbook records the operating constraints, the
synthetic canary, and the activation steps that remain unauthorized.

**Production is not activated.** No step below was executed against a live
Abacus account, a live Abacus Task, `abacus.ai`, or live personal data. Steps
marked **operator-only** remain reserved to the operator (`AGENTS.md` §5 and
§8.2).

Related:

- [`goodnotes-and-model-operations.md`](goodnotes-and-model-operations.md) —
  bounded local OCR/review composition; inert until configured.
- [`managed-knowledge-context.md`](managed-knowledge-context.md) — synthetic
  canary versus live Abacus for `context.prepare`.
- [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md) — separately enabled
  remote MCP; default remote writes off.
- [`../abacus/goodnotes-durable-note-intelligence.task.json`](../abacus/goodnotes-durable-note-intelligence.task.json)
  — frozen draft Task artifact marked `DRAFT_NOT_ACTIVATED`.

## Proposed Task contract

The Task may call only the existing my-pa MCP tools `goodnotes.work` and
`goodnotes.propose` (GN-04). Those names are Capability/Command-derived; this
change does not add a public MCP tool and does not invent a second MCP surface.

The Task:

- requests only bounded my-pa work (`goodnotes.work`);
- analyzes immutable page-version content/context (digest and renderer
  provenance; no page bytes on this path);
- returns schema-valid proposals (`goodnotes.propose`);
- has no direct database, source, or destination writes;
- fail-closes when MCP, auth, or content transfer fails (no proposal write);
- never produces a canonical NEW-only summary itself. Delivery is GN-06, not
  this Task.

Out of the allowlist, including as a substitute work plane: `knowledge.search`,
`knowledge.read`, `context.prepare`, `review.decide`, Task/document authoring,
GoodNotes reconcile, operator correction, and NEW-only delivery. Reconcile,
correction, and delivery are not MCP capabilities and must not be added for
this Task.

`MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` defaults to false. The
process-local gate is read by `bootstrap.goodnotes_durable_note`. Bounded
GoodNotes OCR/review composition does not read it. Setting the flag true does
not create a live Abacus Task.

## Synthetic canaries versus live Abacus

The protocol harness is automated against `ApplicationService.invoke` and MCP
tool descriptions in
`tests/contract/test_goodnotes_durable_note_canary.py`. It uses synthetic
fixtures only (`"synthetic note"`). Live Abacus OAuth, remote `tools/list`,
actual ChatLLM/Agent Task invocation, and scheduled Task→remote MCP
expiry/refresh proof are **not** in that suite and remain operator-gated.

No command block in this runbook was executed against production, a live
Abacus account, or live personal data.

## Activation sequence

None of these steps turns production on by existing in this document. Marked
steps require a separate operator decision. GN-09 TBR live bridge and WP-15
production activation are out of scope here; see
[`goodnotes-tbr-preservation.md`](goodnotes-tbr-preservation.md).

1. Merge the reviewed pull request.
2. Local canary: FAST synthetic suite, including
   `tests/contract/test_goodnotes_durable_note_canary.py`.
3. Confirm the frozen artifact still reads `DRAFT_NOT_ACTIVATED` and names only
   `goodnotes.work` / `goodnotes.propose`.
4. Live Abacus Task create, edit, enable, or disable — **operator-only**. Not
   authorized by this change.
5. OAuth canary (`tools/list` against a registered client) — **operator-only**.
6. Scheduled Task→remote MCP grant expiry and refresh proof — **operator-only**.
7. Production activation — **operator-only**.

## Rollback

1. Leave `MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` false (the
   default). Canonical GoodNotes OCR/review, work, and propose paths stay;
   this gate does not withdraw them.
2. Do not enable, edit, or delete a live Abacus Task from this runbook. Live
   Task mutation is **operator-only**.
3. Emergency withdrawal of the remote surface remains
   [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md).
