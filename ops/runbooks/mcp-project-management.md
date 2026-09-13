# Continuity Project MCP client contract

UNEXECUTED contract documentation for GAP-007. This file teaches autonomous
clients the published Project surface. It is not an executed operations
transcript and does not authorize deployment, production migration, live
personal-data access, or risk acceptance (`AGENTS.md` §5 and §8.2).

Related:

- [`project-entity-bridge-and-backfill.md`](project-entity-bridge-and-backfill.md)
  — Project↔Entity bridge, no name matching, backfill states, production apply
  blocked.
- [`mcp-project-runtime-validation.md`](mcp-project-runtime-validation.md) —
  post-deploy read-only catalog/describe checklist. Does not authorize deploy.
- [`mcp-and-cli-operations.md`](mcp-and-cli-operations.md) — stdio MCP and CLI
  envelope, handshake, and derived tool list.

Tool names are the canonical capability values. There is no ChatLLM- or
MossAIc-specific Project server branch. Compact `my_pa.describe` inherits the
schema `payload_schema_for` already publishes.

## Envelope versus nested payload

Every MCP call is two documents:

1. Envelope metadata at the top level: `request_id`, `purpose`, `principal_id`,
   `requested_at`, `contract_version`, `scope`. `capability` is the tool name
   and must not be repeated. On remote MCP those envelope fields are
   **server-owned** and a caller who sends them is refused.
2. Command fields under nested `payload`. Putting `project_id`,
   `expected_version`, `name`, `state`, or `idempotency_key` at the top level
   is `invalid_request`.

`principal_id` on the envelope is correlation input and confers no authority.

## Capabilities

| Capability | Kind | Nested payload |
| --- | --- | --- |
| `continuity.projects` | read | Optional `page_size`, `after`, `state`, `query` XOR `exact_name` |
| `continuity.projects.read` | read | Required `project_id` |
| `continuity.projects.create` | write | Required `name`; `idempotency_key` on the canonical contract (remote MCP stamps it); optional `description` |
| `continuity.projects.update` | write | Required `project_id`, `expected_version`, `idempotency_key`; at least one of `name`, `description`, `state` |
| `continuity.projects.close` | write | Required `project_id`, `expected_version`, `idempotency_key` |

There is no delete tool and no reopen tool.

## List filters and cursor

`continuity.projects` pages this Principal's Projects. Keyset cursor `after` is
the `project_id` of the last row on the previous page. `state` is the closed
enum `active` | `on_hold` | `closed`. `query` (substring) and `exact_name` are
mutually exclusive; sending both is `invalid_request`. A malformed cursor is
`invalid_request`.

## Version and `expected_version`

Every stored Project carries an integer `version` starting at 1. Update and
close require `expected_version` with no default: the version the caller last
read. A stale value is `conflict` and writes nothing. Do not send `version` as
an input field.

## System-owned fields

These appear in answers and must not appear in a request payload. The generated
schema sets `additionalProperties: false`, so naming one is `invalid_request`:

`principal_id`, `version`, `opened_at`, `closed_at`, `created_at`,
`updated_at`, `participants`, `canonical_participations`.

## Lifecycle

- Create opens `active`.
- Update may set `state` to `active` or `on_hold` only. Sending `closed` on
  update is `invalid_request`.
- Close is always `continuity.projects.close`, never update-with-closed.
- Already-closed is `conflict`, not a silent no-op.
- A closed Project cannot be reopened.
- There is no delete.

## Replay

Create, update, and close are idempotent on `(principal, idempotency_key)`.
The same key with the same payload digest returns the original result. The same
key with a different payload is `conflict`. Remote MCP stamps `idempotency_key`
so a model does not invent one; a caller-supplied copy of that field on the
remote surface is `invalid_request`.

## Participation via `project_id`

People and organizations join a Project through
`entities.participations.create` / `entities.participations.list`, not through
a Project-payload participants array.

- Create: exactly one of `project_id` or `project_entity_id` (XOR).
  `project_id` resolves through the Project↔Entity bridge. Unresolved linkage
  is `conflict`; nothing mints an Entity on that path; nothing matches on name.
- List: exactly one of `entity_id` or `project_id` (XOR). With `entity_id`,
  `perspective` is required (`project` | `participant`). With `project_id`,
  `perspective` may be omitted and is then `project`.

The JSON `participants` echo on Project read is non-authoritative. Canonical
active summaries appear as `canonical_participations` when the bridge row is
`bound`.

## Task association

- `tasks.list` optional `payload.project_id` scopes the page to that Project.
  Missing and foreign Projects are indistinguishable.
- `tasks.update` `payload.project_id` assigns an owned Continuity Project.
  `clear_project: true` detaches. Sending both is `invalid_request`. A missing
  or foreign `project_id` is `not_found`.

## Error vocabulary

Existing public codes only. Do not invent Project-specific codes.

| Situation | Code |
| --- | --- |
| Envelope vs payload mix-up, unknown field, illegal enum, XOR violation, closed-via-update | `invalid_request` |
| Missing or foreign `project_id` / `task_id` | `not_found` |
| Stale `expected_version`, already-closed, idempotency digest mismatch, unresolved bridge on participation | `conflict` |
| Capability or purpose not granted | `denied` or `unsupported` as the existing policy already answers |

Safe errors carry a stable code, a safe message, correlation, and retry
guidance. They do not carry paths, payloads, stack traces, or whether a denied
object exists in another partition.
