# ADR-001: Modular Monolith with Separate Gateway and Worker Processes

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-002`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Architecture scaffold; no runtime implementation

## Context

The product needs one coherent domain and persistence model while supporting synchronous model-facing access and asynchronous ingestion, reconciliation, recovery, and projection work.

## Decision

Use one monorepo and one modular Python codebase with three composition surfaces:

1. `my-pa-gateway` for HTTP and MCP access;
2. `my-pa-worker` for durable background work;
3. `my-pa` for operator CLI functions.

Modules must enforce inward dependency direction. Independent services are deferred until measured scaling, isolation, ownership, or deployment requirements justify a split.

## Consequences

- Shared contracts and domain invariants remain in one repository.
- Gateway and worker can run as separate processes without premature microservice boundaries.
- PostgreSQL-backed jobs and outbox patterns are preferred before adding Redis/Celery.
- This ADR does not authorize executable code, deployment, or service activation.
