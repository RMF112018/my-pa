# Migrations

Alembic owns every schema change to the canonical `my_pa` PostgreSQL database.

- `env.py` — the offline and online environments. The URL comes from
  `MY_PA_DATABASE_URL` through the process settings, never from `alembic.ini`,
  so no credential can reach the repository.
- `script.py.mako` — the template new revisions are generated from.
- `versions/` — the revisions themselves, in dependency order.
- `data/disposition_registry.json` — every legacy object with the target schema
  and treatment it resolves to. Rebuilt by
  `scripts/migration/build_disposition_registry.py`.
- `data/identifier_map.json` — every identifier the 63-byte budget or the
  neutral-naming rule forced the generator to rename. Seeded into
  `migration_control.identifier_map` by the control-plane revision, and rebuilt
  alongside the DDL by `scripts/migration/generate_target_schema.py`.
- `sql/` — the generated target DDL the revisions execute, in three steps:
  tables, then indexes, then foreign keys. Rebuilt by
  `scripts/migration/generate_target_schema.py`; do not hand-edit. The
  obligations the load takes on at the tables step — resetting the 46 identity
  sequences, and quarantining rather than inventing a NULL primary key — are
  stated in that revision's docstring. The foreign keys arrive `NOT VALID` and
  are validated by a separate reportable step (OD-017).

The control plane is created between the tables and the indexes, because that is
where the load runs. So the sequence is:

```text
alembic upgrade 4b9f0d27ac31      # schemas, 424 tables, migration_control
apps/cli/migration.py load ...    # rows land with no index and no FK in the way
alembic upgrade head              # indexes, then foreign keys
```

Usage, the connection contract, and the round-trip requirement are documented in
[`docs/migration/PHASE-01-FOUNDATION.md`](/docs/migration/PHASE-01-FOUNDATION.md).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.

Routine current-schema tests clone a worker-level template that has already been upgraded to head. Empty-to-head, revision-edge, and loader tests keep their own Alembic-driven fixtures. Historical migration compatibility is not part of the ordinary database job; adding a scheduled or release job for `migration_historical` is a bounded follow-up. Do not squash or rewrite this chain as a test-provisioning shortcut.
