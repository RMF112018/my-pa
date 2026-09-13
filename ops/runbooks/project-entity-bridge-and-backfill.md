# Project↔Entity bridge and backfill

UNEXECUTED contract documentation for GAP-007. This file describes the durable
Continuity Project↔Entity bridge admitted by WP-MCP-PROJ-01. It does not
authorize production apply of the migration, live backfill against canonical
`my_pa`, deployment, or risk acceptance (`AGENTS.md` §5 and §8.2).

**Production apply of this migration is operator-only and is NOT authorized by
this campaign.**

Related:

- [`mcp-project-management.md`](mcp-project-management.md) — MCP client
  contract.
- [`mcp-project-runtime-validation.md`](mcp-project-runtime-validation.md) —
  post-deploy read-only checklist. Does not authorize deploy.
- Alembic revision `9f2c8a1d4e70` (`migrations/versions/20260913_9f2c8a1d4e70_project_version_and_entity_bridge.py`)
  adds `knowledge.projects.version` and `knowledge.project_entity_links`.

## Bridge table

`knowledge.project_entity_links` is keyed by the Continuity Project itself
`(principal_id, project_id)`. There is no new identifier kind.

| Column | Bound row | Unresolved row |
| --- | --- | --- |
| `project_entity_id` | one Entity in the same Principal | null |
| `linkage_state` | `bound` | `unresolved_missing` or `unresolved_ambiguous` |

The pairing is checked: a bound row names its entity, and only then. A bound
entity is unique per Principal. The link never stores a display name.

## No name matching

Nothing on this path joins Continuity Projects to Entities by name. Backfill
does not probe `entities.canonical_name` / `display_name` to guess a binding.
Forward create mints a **new** project-type Entity in the same transaction as
`continuity.projects.create` and writes a `bound` row. If that canonical name
is already held by an active project-type Entity, create fails closed rather
than attaching to the existing row.

## Unresolved states

Existing Project rows at migration receive version `1` and one
`unresolved_missing` bridge row with a null entity id.

| State | Meaning | Entity id |
| --- | --- | --- |
| `bound` | minted or later-resolved identity | present |
| `unresolved_missing` | no candidate | null |
| `unresolved_ambiguous` | more than one candidate | null |

Unresolved linkage is durable. Participation via `project_id` refuses with
`conflict` naming `project_id` and does not mint an Entity. Project read still
answers; `canonical_participations` is empty until the row is `bound`.

Resolving an unresolved row is a later, separately authorized act. This
campaign does not ship a resolver, a name-match backfill, or an operator apply
of the migration against production.

## Forward mint on create

`continuity.projects.create` inserts the Project at version 1, mints a
project-type Entity from the chosen name, and writes a `bound` link in one
transaction. Participation and Task association that take `project_id` then
resolve through that bound row.

## Production apply is blocked here

Applying `9f2c8a1d4e70` (and later Project revisions) to a non-disposable
database, including canonical `my_pa`, remains operator-gated. This campaign
authorizes repository schema, synthetic tests, and this contract text only.
Do not infer apply, cutover, or live backfill from the presence of the
revision file.
