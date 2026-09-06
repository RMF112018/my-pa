# Observability

MY-PA deliberately favors bounded, content-free operational signals over broad payload logging.

## Principles

- Logs must not contain credentials, message/document bodies, contact details, sensitive query text, personal source content, or unredacted evidence.
- Prefer stable identifiers, state names, counts, timestamps, and redacted metadata.
- A missing observation is `unknown`, not `healthy`.
- Readiness, business-domain readiness, and process health are different signals.
- Failed and refused operations are evidence and must not be normalized into success.

## Gateway

The Python gateway intentionally disables Uvicorn access logging and does not treat request paths/payloads as an observability channel. Startup output identifies the served surface and material composition/refusal state.

Useful runtime evidence comes from:

- process exit/status;
- health/readiness endpoints or capability responses where implemented;
- `capabilities.get` for the composed capability manifest;
- content-free application audit events;
- database/worker health records.

See `ops/runbooks/gateway-operations.md`.

## Workers

Worker health is plane-specific. The current worker entry point supports:

- `enrollment`;
- `capture`;
- `reenrichment`.

The web System surface reports worker-plane state, backlog, dead-letter counts, and heartbeat information when available. An absent worker with no backlog may be `idle_or_not_required`; it is not silently represented as a running process.

See `ops/runbooks/worker-operations.md`.

## Database

Use PostgreSQL/container health plus application-level readiness. A live PostgreSQL socket does not establish that:

- the schema is at the intended Alembic revision;
- the application can authorize/serve a requested capability;
- a worker is processing queued work;
- a deployed web/BFF path is functional.

See `ops/runbooks/postgres-operations.md`.

## Audit and provenance

Security-relevant denials and consequential operations should retain proportionate audit/provenance records without retaining sensitive payloads. Model-derived data must remain distinguishable from authoritative/source-backed evidence.

## During incident diagnosis

Capture:

1. exact repository/deployment identity;
2. process and plane;
3. timestamp and stable operation/request IDs;
4. error/refusal code and safe details;
5. relevant feature/configuration names without secret values;
6. worker/database health facts;
7. reproduction using synthetic data where possible.

Do not copy secrets or personal records into issue, PR, or Drive evidence.
