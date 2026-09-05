# Recovery

Recovery is a controlled restoration to a known state, not an invitation to make destructive changes.

## Recovery hierarchy

Prefer, in order:

1. retry an idempotent bounded operation when its contract explicitly permits retry;
2. restart a process through its owned lifecycle procedure;
3. repair/reconcile product-owned state through an existing governed operation;
4. restore from a verified backup into a scratch environment and validate;
5. perform target recovery only with the exact authorization required for the target and blast radius.

## Database recovery

Never treat Alembic downgrade as a generic recovery tool. A downgrade may be destructive, incomplete, or intentionally unsupported.

For PostgreSQL:

- verify target database identity;
- verify backup identity/integrity;
- restore to scratch first when practical;
- validate schema/application behavior on the restored copy;
- preserve the pre-recovery state/evidence;
- obtain required authorization before destructive replacement of canonical data.

Deep procedure: `ops/runbooks/postgres-operations.md` and `ops/runbooks/end-to-end-operations.md`.

## Process/runtime recovery

Gateway and worker processes have different lifecycle semantics. Use their runbooks:

- `ops/runbooks/gateway-operations.md`;
- `ops/runbooks/worker-operations.md`;
- `ops/runbooks/nas-lifecycle.md` for NAS runtime.

A restart does not prove backlog recovery or application readiness; verify the affected capability/plane after restart.

## Managed-document recovery

Managed-document metadata and bytes are separate resources with explicit containment and backup requirements. Use `ops/runbooks/managed-document-operations.md`; do not rebuild missing authoritative content from model output.

## GoodNotes/GSQS and source data

Original source systems remain authoritative/read-only by default. Recovery must not mutate a source merely to make derived state convenient. Re-ingest/reconcile only through the bounded current workflow and preserve provenance.

## Evidence

Record exact before/after identity, recovery action, backup/source used, validation result, unresolved limitations, and any data that could not be recovered. Do not mark a recovery successful because a process starts if the affected contract was not revalidated.
