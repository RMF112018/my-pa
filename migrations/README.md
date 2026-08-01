# Migrations

Alembic owns every schema change to the canonical `my_pa` PostgreSQL database.

- `env.py` — the offline and online environments. The URL comes from
  `MY_PA_DATABASE_URL` through the process settings, never from `alembic.ini`,
  so no credential can reach the repository.
- `script.py.mako` — the template new revisions are generated from.
- `versions/` — the revisions themselves, in dependency order.

Usage, the connection contract, and the round-trip requirement are documented in
[`docs/migration/PHASE-01-FOUNDATION.md`](/docs/migration/PHASE-01-FOUNDATION.md).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
