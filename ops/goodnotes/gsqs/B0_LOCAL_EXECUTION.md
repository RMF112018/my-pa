# Local B0 execution infrastructure

This document describes the repository-owned stdio host that closes
B0-EXEC-001/002/003. It does **not** authorize real handwriting, private
gold, scoring, or `MEASURED_B0`.

Historical finding (2026-08-25): hosted ChatLLM MCP cannot read the
operator raster filesystem, and no local RouteLLM MCP client existed.
That finding stands. This infrastructure replaces the disproven
assumption that an external RouteLLM MCP client already existed.

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
- **B0-EXEC-003** — `write_repetition_capture` emits
  `gsqs-analyzer-capture-v1` containing `gsqs-analyzer-output-v1`
  documents as `repetition-00N.json`, atomically, with identical-replay
  idempotency and conflicting-replay rejection.

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
