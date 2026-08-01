# Revisions

One file per Alembic revision, generated with `.venv/bin/alembic revision -m "..."`.

Every revision must be reversible and must survive the empty-to-head-to-empty round trip that `AGENTS.md` section 6 requires; `tests/schema/` enforces it. Downgrades drop with `RESTRICT` so a downgrade cannot silently delete objects a later revision left behind.

See [`docs/migration/PHASE-01-FOUNDATION.md`](/docs/migration/PHASE-01-FOUNDATION.md).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
