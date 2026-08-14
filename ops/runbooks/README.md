# Runbooks

Operational procedures for running `my-pa` locally.

| Runbook | Covers |
| --- | --- |
| [`end-to-end-operations.md`](end-to-end-operations.md) | **Start here.** The ordered sequence: probe the database, migrate, register, enroll, run the worker, search and read, and stop both processes — and the limitation that sequence walked into. |
| [`postgres-operations.md`](postgres-operations.md) | The canonical `my_pa` PostgreSQL database: start, stop, health check, connect, back up, restore. |
| [`worker-operations.md`](worker-operations.md) | The worker process: running it bounded or until signalled, stopping it cleanly, and how a crashed worker's job is recovered. |
| [`gateway-operations.md`](gateway-operations.md) | The HTTP gateway process: running it on loopback, calling the public capabilities, the status each error code takes, its two connection pools, and stopping it. |
| [`mcp-and-cli-operations.md`](mcp-and-cli-operations.md) | The other two transports: the MCP server on stdio and the operator CLI. What is identical to HTTP and why, the handshake and derived tool list, the CLI's options and exit status, and what a bad command line does. |

Related, outside this directory:

- [`/docs/operations/mcv-limitations.md`](/docs/operations/mcv-limitations.md) —
  what the read-only slice does **not** do, each limitation citing the test or
  measurement that bounds it. A runbook says how to run the thing; that document
  says what running it does not establish.
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
