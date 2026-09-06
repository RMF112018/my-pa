# System overview

MY-PA is a local-first modular application with one canonical Python application model, a browser BFF, PostgreSQL persistence, bounded workers and several transport/integration edges.

## Major runtime components

### Python gateway
`apps/gateway.py` composes the application once and exposes:

- HTTP capability calls under `/v1/<capability>`;
- local MCP over stdio;
- separately enabled remote MCP over authenticated Streamable HTTP;
- supporting session/WebAuthn/OAuth routes where configured.

HTTP and MCP use the same settings, application service and policy/disclosure behavior.

### Worker
`apps/worker.py` executes bounded asynchronous work. Current planes include enrollment, capture and Relationship Intelligence re-enrichment. A process serves one selected plane. Worker code is idempotency/lease-aware and reports content-free counts/state.

### Web
`web/` is a Next.js App Router PWA and BFF. Browser requests terminate at server routes that resolve session identity and call the Python gateway. The web tier does not reimplement domain rules.

### PostgreSQL
PostgreSQL is the canonical metadata/knowledge store. Alembic owns schema evolution. Application state, provenance, product-owned records, relationship/work/report state, job state and audit metadata live in database-owned schemas/tables.

### Source providers and managed storage
Original sources are read-only by default. Managed-document bytes use an explicitly configured separate managed root. Product-owned user-authored records are a third authority class stored in PostgreSQL.

## Request flow

```text
browser / MCP / CLI / HTTP
        |
        v
transport normalization
        |
        v
application authorization + use case + disclosure
        |
        v
ports/contracts
        |
        +--> PostgreSQL repositories / jobs
        +--> read-only source provider
        +--> managed byte store when explicitly configured
```

`src/my_pa/adapters/normalization.py` is the shared request-normalization boundary for HTTP, MCP and CLI. Transport-specific code must not create alternative identity, authorization or domain semantics.

## Authority model

Three data-authority classes matter to feature design:

1. **Original sources** — authoritative external/source-system evidence; read-only by default.
2. **Managed documents** — product-managed byte/document lifecycle at a designated managed root.
3. **Product-owned records** — user-authored/canonical MY-PA records held in PostgreSQL under ADR-003.

Derived/model-generated content carries provenance and does not silently overwrite authoritative evidence.

## Core architecture decisions

See ADRs:

- ADR-001 modular monolith / separate gateway and worker processes.
- ADR-002 logical database identity.
- ADR-003 product-owned records as a third authority class.
- ADR-004 Next.js frontend architecture.
- ADR-005..ADR-007 Principal partitioning.
- ADR-008 NAS runtime topology.
- ADR-009 remote MCP refresh-token families.
- ADR-010 Intelligence Artifact/Report plane.
- ADR-011 passkey/WebAuthn browser authentication and opaque server sessions.

## Extension rule

A new feature should normally extend the existing layers rather than add a new process, database, queue, cache or service. New infrastructure requires a current measured need and a durable architectural justification.

Use [`../development/feature-development-playbook.md`](../development/feature-development-playbook.md) before planning a cross-layer feature.
