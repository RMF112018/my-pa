# Checkpoint — project-entity bridge reconciliation (2026-10-15)

- Repo: my-pa. Branch `feat/project-entity-bridge-reconciliation`, base 4e6b4f62.
- Commits: 2fd0f6f9 (feature), 2109d498 (historical-edit guard allow-list),
  6a67da38 (offline fail-closed), plus this evidence commit.
- Migration: `b9025e7fb738`, single head. No schema change.
- Verified locally (PG 15, isolated instance): targeted reconciliation, schema and
  participation tests pass (23). Full `tests/schema -m database` sweep: see
  04b below / PR description for the base-vs-branch comparison.
- NOT done: PR, merge, production migration, production read-back, and the pending
  participation write for the person named in the original failed request.
- Next action: operator decision on running the migration in production after a
  fresh read-only count and a table dump (see 03).
- Pending participation: the original payload overclaimed. Employer announcement
  supports `role_basis_code=source_verified`, `stakeholder_side_code=design`,
  affiliation-level title as `role_text` at most; `stakeholder_class_code=core`
  and a project-specific "lead" role are not evidenced — use `unresolved`/`adjacent`
  unless a stronger source is found. The employment affiliation already exists;
  do not recreate it.
