# Local B0 execution infrastructure

This document describes the repository-owned stdio host that closes
B0-EXEC-001/002/003, and the production-MCP workflow that later invokes it.
It does **not** authorize real handwriting, private gold, scoring, or
`MEASURED_B0`.

```text
CHATLLM_AS_B0_ANALYZER_PLANE = NO
CHATLLM_AS_CONNECTED_MCP_WORKFLOW_INITIATOR = YES
LOCAL_AGENT_DIRECT_ROUTELLM_WORKFLOW_INITIATION = NO
```

ChatLLM initiates a repetition only through the existing connected MY-PA
MCP (`gsqs.start` / `gsqs.step` / `gsqs.status` on
`https://my-pa-mcp.bobby-fetting.me/mcp`). ChatLLM is the MCP client
and drives inference; RouteLLM routes models inside ChatLLM. NAS never
calls ChatLLM or RouteLLM. That surface is orchestration plus
client-driven case lease, not a NAS HTTP RouteLLM client. The stdio
analyzer plane remains `python apps/cli/gsqs_b0.py serve-eval-mcp`
(`goodnotes.work`, `goodnotes.content`) for the synthetic-fake path.
HTTPS `goodnotes.eval.*` is not canonical B0.

Historical finding (2026-08-25): hosted ChatLLM MCP cannot read the
operator raster filesystem, and no local RouteLLM MCP client existed.
That finding stands for the **analyzer** plane. It does not mean ChatLLM
is absent from the workflow: ChatLLM remains the operator initiation
surface. This infrastructure replaces the disproven assumption that an
external RouteLLM MCP client already existed.

## Components

- **B0-EXEC-001** — `StdioEvalSession` spawns
  `python apps/cli/gsqs_b0.py serve-eval-mcp`, owns stdin/stdout/stderr,
  completes MCP initialize, and refuses `tools/list` unless it is exactly
  `goodnotes.work` and `goodnotes.content`.
- **Model-client boundary** — `B0ModelClient`. The synthetic fake is
  admitted for commissioning. Direct RouteLLM HTTP remains
  `BLOCKED_ROUTELLM_CLIENT_ACTIVATION_AUTHORIZATION_REQUIRED` (API key,
  origin, and uncommissioned `/v1/chat/completions` use).
- **B0-EXEC-002** — `acquire_repetition` walks the campaign census in
  stored order. The model does not choose the next case. One CLI
  invocation runs one explicit `--repetition`. Interrupted attempts are
  `INTERRUPTED` or `INVALID` and are not resumable.
- **Connected-MCP workflow** — production tools `gsqs.start`, `gsqs.step`,
  and `gsqs.status`. ChatLLM initiates and drives inference; RouteLLM
  routes inside ChatLLM. The server owns campaign identity, rasters,
  trusted interchange fields, and capture persistence. NAS RouteLLM HTTP
  is not the canonical production path. Real handwriting remains denied.

## Authorization

Synthetic runs require `SYNTHETIC_B0_ACQUISITION` bound to the synthetic
campaign, repetition, candidate, prompt, and `synthetic-fake` client.

Real Partition B (`gsqs-hw-combined-v1` / frozen combined identity)
requires `REAL_HANDWRITING_B0_EXECUTION`. That operation is recognized
and **not admitted** in this implementation
(`REAL_HANDWRITING_ACQUISITION_ADMITTED = False`). There is no `--force`.

## Scoring separation

`acquire-repetition` never calls `score`. Later gold authorization and
score authorization remain separate.

## Failure / resume

Crash or invalidation preserves `ACQUISITION_STATE.json` and
`accepted-cases.jsonl`. The same output directory cannot be reused.
Fresh repetition, same census order, fresh stdio process, fresh
model-client session.
