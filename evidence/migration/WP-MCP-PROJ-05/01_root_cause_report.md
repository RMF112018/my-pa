# WP-MCP-PROJ-05 — Root cause: legacy Continuity Projects never bound to a project Entity

Date: 2026-10-15. Base: `origin/main` 4e6b4f62. Migration: `b9025e7fb738`.

## Symptom
`entities.participations.create` / `.list` with a Continuity `project_id` (`prj_`)
returns `conflict` / safe detail `project_id` for certain established projects.
It is a read-path failure too, independent of any write.

## Confirmed mechanism
1. `9f2c8a1d4e70` (2026-09-13, WP-MCP-PROJ-01) created `knowledge.project_entity_links`
   and backfilled every pre-existing Project as `unresolved_missing`, null entity,
   by design ("nothing here mints an Entity and nothing joins on a name").
2. New Projects are minted and bound atomically by
   `continuity_authoring._mint_bound_project_entity`. That path is correct.
3. Nothing in the codebase ever moved a row out of `unresolved_missing` or
   `unresolved_ambiguous`. The reconciliation step was never written.
4. `ApplicationService._bound_project_entity_id` refuses any non-`bound` link with
   `ConflictError(PROJECT_ID)`. That refusal is correct behavior for the data state.

Category (brief section A4): 1 (missing canonical entity provisioning) with 2
(no reconciliation of the backfilled bridge). Not a resolver, ownership, lifecycle
or constraint defect.

## Why controls differ
The two working control projects were created after 2026-09-13 and so passed
through the mint-and-bind path at creation.

## Evidence (read-only production inspection, 2026-10-15, operator-authorized)
- One principal in the whole system.
- `project_entity_links`: 2 `bound`, 4 `unresolved_missing`, 0 `unresolved_ambiguous`.
- 0 `bound` rows pointing at a missing or non-project entity.
- No project-type entity exists under the principal whose canonical name matches
  any of the 4 unresolved projects (only the 2 bound controls and one unrelated
  archived test entity exist).
- Affected population is 4, not the 3 named: the fourth is a closed synthetic
  test project, `prj_cdac50904f7f806677251edaaba1e2f6`.

## Fix
New idempotent reconciliation, `project_entity_reconciliation.reconcile_project_entity_links`,
called by migration `b9025e7fb738`. Per `unresolved_missing` row, with a fresh
candidate query per row: zero same-name project entities -> mint and bind; one or
more -> flag `unresolved_ambiguous`, never auto-bind. Bound and ambiguous rows are
untouched. Offline (`--sql`) mode fails closed. `downgrade()` is a documented
no-op (no per-row log exists from which to reverse safely).
Forward path (`continuity_authoring.py`) and resolver (`service.py`) are unchanged.

## Limitations
- The migration executes against whatever rows exist at run time; counts in the
  register are the 2026-10-15 snapshot.
- Rollback is restore-from-backup only; see the preflight report.
- Participation write for the originally failing person is NOT performed here.
