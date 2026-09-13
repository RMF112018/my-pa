# Project MCP runtime validation

This is the repository procedure for a **read-only** catalog/describe check of
the Continuity Project MCP surface after a separately authorized deploy.

**Disposition: `NOT_PERFORMED_OPERATOR_GATED`.** It has not been executed.
This file does not authorize deployment, production activation, live
migration, credential mutation, or risk acceptance (`AGENTS.md` §5 and §8.2).
A green CI run cannot close physical/runtime acceptance criteria.

Related:

- [`mcp-project-management.md`](mcp-project-management.md) — client contract.
- [`project-entity-bridge-and-backfill.md`](project-entity-bridge-and-backfill.md)
  — bridge table; production apply blocked.
- [`mcp-and-cli-operations.md`](mcp-and-cli-operations.md) — stdio MCP
  handshake and derived tool list.
- [`auth-runtime-validation.md`](auth-runtime-validation.md) — sibling
  operator-gated runtime pattern.

## What this checklist is allowed to do

After an operator has independently authorized a target and a deploy, record
read-only catalog evidence:

- `tools/list` (or compact `my_pa.describe`) names the Project capabilities
  this build actually publishes.
- Each Project tool's `inputSchema` is the nested-payload envelope
  `normalize` already reads.
- Update and close require `expected_version` under `payload`.
- No vendor-specific Project tool name is published.

Stop before any write, any migration apply, any grant change, and any call
that needs live personal data.

## Read-only catalog checklist

Bind the check to the independently reviewed commit/tree and Alembic head
before recording results. A later implementation commit invalidates the
record.

1. Confirm the process under test is the authorized build. Do not start a new
   deploy from this procedure.
2. `tools/list` includes `continuity.projects` and
   `continuity.projects.read`. When remote writes are enabled on that
   authorized target, it also includes `continuity.projects.create`,
   `.update`, and `.close`. Local stdio publishes the five names together.
3. Compact clients call `my_pa.describe` with
   `capability: "continuity.projects.update"` (and `.close`). The returned
   `input_schema` equals the remote view of the canonical tool schema: nested
   `payload`, `expected_version` required, no façade special case.
4. `input_schema.properties` does not accept command fields at the top level.
   `payload.additionalProperties` is false. System-owned names
   (`principal_id`, `version`, `opened_at`, `closed_at`, `created_at`,
   `updated_at`, `participants`) are absent from the payload properties.
5. Tool names are the canonical capability values only. No `chatllm.*`,
   `mossaic.*`, or other vendor-prefixed Project tool is listed.
6. Do not call create/update/close against production data from this
   checklist. Replay, lifecycle, and error vocabulary are proven in
   synthetic contract tests, not by this runtime pass.

## Evidence hygiene

Record non-secret identities (commit SHA, tree, Alembic head, tool names,
schema property lists). Never record tokens, connection strings, personal
Project names, or unredacted payloads.

## What a pass here does not mean

A completed checklist is not deploy authorization, not production apply of
`9f2c8a1d4e70` or later Project revisions, and not risk acceptance. Those
remain separate operator decisions.
