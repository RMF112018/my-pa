# Data and storage architecture

## Canonical stores

PostgreSQL is MY-PA's canonical metadata and knowledge store. It contains product-owned records, provenance, workflow/review state, relationship/work/report data, worker/job state and other application metadata.

Filesystem/NAS sources and managed-document storage are separate authority classes and must not be conflated with PostgreSQL ownership.

## Authority classes

### Original source systems
External/filesystem/provider sources remain authoritative for their source evidence and are read-only by default. Provider adapters expose bounded read/metadata operations; adding a write to a source provider requires explicit product scope and authority.

### Managed documents
Managed documents are MY-PA-controlled bytes and lifecycle records at an explicitly configured managed root. The managed root has no default and is checked against source roots so source and managed storage cannot silently overlap.

### Product-owned records
ADR-003 defines user-authored MY-PA records as a third class. They are canonical application records stored in PostgreSQL and are neither source-system writes nor managed-document writes.

## PostgreSQL model

SQLAlchemy infrastructure lives under `src/my_pa/infrastructure/persistence/` and database engine/configuration under `src/my_pa/infrastructure/database/`.

Public/domain code should not depend on ORM row shapes. Repositories and units of work implement transport-neutral ports.

## Schema evolution

Alembic owns schema evolution under `migrations/`. `alembic.ini` intentionally does not choose the target database; `MY_PA_DATABASE_URL` is required.

Use [`../reference/database-migrations.md`](../reference/database-migrations.md) for the development workflow.

## Search

The baseline search architecture uses PostgreSQL lexical/full-text mechanisms, including `pg_trgm` where appropriate. A vector/semantic store is not a default MCV infrastructure prerequisite; adding one requires a demonstrated need/benchmark gate and an accepted architecture change.

## Provenance and versioning

Durable records that derive from source/model input must preserve enough provenance to distinguish:

- authoritative source facts;
- product-owned user assertions;
- generated/derived proposals;
- accepted/rejected review outcomes;
- immutable/versioned historical state where the domain requires it.

Do not silently overwrite source evidence with generated content.

## Principal partitioning

Capture, review, Relationship Intelligence, continuity and other personal planes derive and persist Principal ownership server-side. New persistence must carry the owning Principal wherever the domain requires partition isolation, and reads/writes must prove that isolation in database/security tests.

## Database tests

Application tests should prefer fakes when persistence is not the subject. Persistence behavior, constraints, migrations, locking/idempotency and partition isolation belong in schema/database tests against isolated databases.

See [`../development/testing-and-review.md`](../development/testing-and-review.md).
