# Migration preflight — b9025e7fb738 (down_revision 5c1e7a9b3d42)

- Touches: `knowledge.entities` (INSERT, zero-candidate rows only) and
  `knowledge.project_entity_links` (UPDATE). No DDL.
- Expected production effect (snapshot): 4 entities minted, 4 links bound, 0 flagged.
  Re-run the read-only count immediately before execution; it must still be
  `unresolved_missing = 4`, `unresolved_ambiguous = 0`.
- Idempotent: a second pass reports only no-op outcomes.
- Online only. `alembic upgrade --sql` raises by design.
- Rollback: `downgrade()` is a no-op. Recovery is a pre-run `pg_dump` of the two
  tables (or the existing attested PostgreSQL backup) and restore of those rows.
  Take that dump before executing.
- Production execution is operator-reserved (AGENTS.md section 8.2).
- Post-run read-back: each of the 4 links `bound`, entity `entity_type='project'`,
  `status='active'`; participation list by `prj_` and by `ent_` returns no conflict.
