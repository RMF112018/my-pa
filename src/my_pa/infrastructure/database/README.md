# Database

PostgreSQL access for the canonical `my_pa` database: `engine.py` holds the engine factory, the transactional `session_scope`, and `healthcheck`.

Nothing here reads process settings. The caller passes a URL, which keeps configuration in `bootstrap` and makes a disposable test database an ordinary argument rather than a special case.

Schema changes belong to Alembic in `migrations/`, not to this package. The connection contract is documented in [`docs/migration/PHASE-01-FOUNDATION.md`](/docs/migration/PHASE-01-FOUNDATION.md).

The `models/`, `repositories/`, and `search/` subdirectories remain scaffold: none has an implementation yet.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
