# Backend and domain architecture

## Package boundaries

```text
src/my_pa/
  domain/          invariants, values, aggregates, lifecycle rules
  contracts/       public transport-neutral schemas and ports
  application/     use cases, policy/disclosure, orchestration
  adapters/        driving adapters: HTTP, MCP, CLI
  infrastructure/  driven adapters: persistence, providers, jobs, migration
  bootstrap/       validated settings and composition
apps/              executable composition roots
```

The conceptual dependency direction is inward:

```text
apps/bootstrap
  -> adapters / application / infrastructure
  -> contracts / domain
```

`domain` must not depend on application or infrastructure. Infrastructure implements ports declared inward. Driving adapters translate protocols; they do not contain domain decisions.

Architecture tests under `tests/architecture/` enforce dependency direction and transport behavior.

## Domain

Put in `domain/` when behavior is:

- an invariant, state machine, value object or aggregate rule;
- independent of SQL, HTTP, MCP, filesystems and process lifecycle;
- meaningful regardless of which transport or repository implementation invokes it.

Avoid framework imports and persistence concerns.

## Contracts

`contracts/` contains:

- public request/response/envelope shapes;
- stable transport-neutral DTOs;
- application ports used by infrastructure;
- capability-facing data structures.

Do not expose SQLAlchemy rows or provider SDK objects through public contracts.

## Application

`application/` owns:

- capability command handling;
- authorization and disclosure;
- orchestration across ports;
- idempotency/conflict semantics at the use-case level;
- transaction coordination;
- mapping internal failures to public typed errors.

A feature with a public capability normally needs command/application wiring here before HTTP/MCP/CLI can serve it.

## Adapters

Driving adapters currently include HTTP, MCP and CLI. All share request normalization. Adapter work should be protocol mapping only:

- parse protocol-specific input;
- resolve transport identity/credential context;
- call canonical normalization/application entry points;
- render the canonical response.

A transport must not invent a special write, bypass policy or expose a capability the application did not compose.

## Infrastructure

Infrastructure owns implementations of ports:

- SQLAlchemy/PostgreSQL repositories and units of work;
- source-provider adapters;
- managed-document stores;
- worker/job persistence and leases;
- migration/legacy-load implementation;
- external/process-specific mechanisms.

Private ORM/database details stay behind ports.

## Composition

`src/my_pa/bootstrap/` validates configuration and composes dependencies. Repository-root `apps/` files are executable composition roots.

Do not add a service locator, plugin framework or speculative registry because a new feature exists. Extend the existing explicit composition unless evidence demonstrates it no longer fits.

## Adding a backend feature

1. define/confirm domain semantics;
2. add pure domain behavior and tests;
3. add/extend transport-neutral contracts and ports;
4. implement application use case/policy/disclosure;
5. implement persistence/provider adapter if needed;
6. wire composition;
7. expose through canonical capability/transport path;
8. add contract/security/database tests;
9. update current domain/reference docs.

See [`../development/feature-development-playbook.md`](../development/feature-development-playbook.md).
