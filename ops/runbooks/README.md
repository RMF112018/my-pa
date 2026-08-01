# Runbooks

Operational procedures for running `my-pa` locally.

| Runbook | Covers |
| --- | --- |
| [`postgres-operations.md`](postgres-operations.md) | The canonical `my_pa` PostgreSQL database: start, stop, health check, connect, back up, restore. |

Related, outside this directory:

- [`../postgres/README.md`](../postgres/README.md) — the PostgreSQL instance
  itself: image, tuning, locale, collation contract, cluster-creation settings,
  reset procedure.
- [`../compose/postgres.yml`](../compose/postgres.yml) — the container
  definition.
- [`/docs/migration/PHASE-11-CUTOVER.md`](/docs/migration/PHASE-11-CUTOVER.md) —
  target-side rollback procedures.

A procedure here is written only after it has been executed, and each one states
which of its commands were not run and why. Destructive data operations,
deployment, and production activation remain operator-gated (`AGENTS.md` §5).

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
