# Runbooks

Operational procedures for running `my-pa` locally.

| Runbook | Covers |
| --- | --- |
| [`end-to-end-operations.md`](end-to-end-operations.md) | **Start here.** The ordered sequence: probe the database, migrate, register, enroll, run the worker, search and read, and stop both processes — and the limitation that sequence walked into. |
| [`postgres-operations.md`](postgres-operations.md) | The canonical `my_pa` PostgreSQL database: start, stop, health check, connect, back up, restore. |
| [`worker-operations.md`](worker-operations.md) | The worker process: running it bounded or until signalled, stopping it cleanly, and how a crashed worker's job is recovered. |
| [`gateway-operations.md`](gateway-operations.md) | The HTTP gateway process: running it on loopback, calling the capabilities a composed build serves, the status each error code takes, its two connection pools, and stopping it. |
| [`managed-document-operations.md`](managed-document-operations.md) | The managed-document write plane: configuring its root, checking that its rows and its bytes agree, the metadata/bytes failure window and what it can leave behind, and backing the plane up and restoring it. |
| [`mcp-and-cli-operations.md`](mcp-and-cli-operations.md) | The other two transports: the MCP server on stdio and the operator CLI. What is identical to HTTP and why, the handshake and derived tool list, the CLI's options and exit status, and what a bad command line does. |
| [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md) | Separately enabled remote MCP on the NAS: private-origin Compose, outbound-only Cloudflare Tunnel, client checks, rollback, and loopback fallback. |
| [`nas-lifecycle.md`](nas-lifecycle.md) | Fail-closed NAS lifecycle commands, smoke restart policy, and the exact NAS-10 plus operator gates for the restart-only pilot overlay. |
| [`nas-acceptance.md`](nas-acceptance.md) | Inert NAS-10 synthetic matrix, independently signed exact-head review, and unsigned PASS-candidate gate. |
| [`context-semantic-retrieval.md`](context-semantic-retrieval.md) | Semantic retrieval gate: currently `SEMANTIC_GATE_FAIL`, lexical `context.prepare` is the active path, and how to re-run the SPECIALIZED evaluation. |
| [`managed-knowledge-context.md`](managed-knowledge-context.md) | ChatLLM operating contract, recommended grants, activation sequence, and rollback for `context.prepare`. Production is not activated. |
| [`goodnotes-durable-note-intelligence.md`](goodnotes-durable-note-intelligence.md) | Dormant Abacus Task contract for GoodNotes Durable Note Intelligence. Synthetic canary only; live Task create/edit/enable remains unauthorized. |
| [`goodnotes-durable-note-rollout.md`](goodnotes-durable-note-rollout.md) | WP-15 dormant rollout gates and operator-gated activation sequence. Production and pilot remain off; dry-run helper does not ingest, write, deliver, or call Abacus. |
| [`goodnotes-tbr-preservation.md`](goodnotes-tbr-preservation.md) | GN-09 TBR Staff Meeting regression freeze and dormant optional-bridge design. Existing TBR Task must not change; live bridge remains unauthorized. |
| [`relationship-intelligence.md`](relationship-intelligence.md) | The entity plane: what its forty-five `entities.` names answer, including Principal-scoped identity history and governed merge/split preview/apply; how the plane, write, identity-correction, remote-write, exact `remote.operator`, durable capability/purpose, and policy gates compose around its sixteen reads and twenty-nine writes; and the unexecuted, operator-gated WP-08 commissioning and WP-09 canary procedures. Live activation remains deferred. |
| [`goodnotes-and-model-operations.md`](goodnotes-and-model-operations.md) | GoodNotes ingestion and model-route operations. |
| [`../goodnotes/gsqs/README.md`](../goodnotes/gsqs/README.md) | Gate B GSQS labeled corpus, independent evaluator, and governed live-B0 runner. Preflight is non-disclosing; `MEASURED_B0` is not established. |
| [`context-personal-knowledge-pilot.md`](context-personal-knowledge-pilot.md) | Operator-authorized personal-knowledge pilot checklist. Does not access live personal data; queries and evidence must not be committed. |

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
