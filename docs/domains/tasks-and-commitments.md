# Tasks and Commitments

Tasks and Commitments are product-owned work records served through the canonical Python application and web Work surface.

## Canonical semantics

The domain distinguishes Tasks from Commitments:

- a Task is an actionable work item with lifecycle/state, ownership, evidence and history;
- a Commitment represents an obligation with direction/counterparty/work context and explicit closure.

Both are Principal-scoped product-owned records. They are not source-system mutations.

Domain primitives live in `src/my_pa/domain/situation/`; application services live in `src/my_pa/application/tasks.py` and `src/my_pa/application/commitments.py`; persistence is under `src/my_pa/infrastructure/persistence/`.

## Public capability shape

Current capability families include read/list/search/create/update/history and explicit lifecycle/closure operations. The definitive capability names and command schemas are executable code, not this document.

Use:

- `src/my_pa/domain/identity/operation.py`
- `src/my_pa/application/commands.py`
- `src/my_pa/application/service.py`
- `web/README.md` for current BFF mapping

## Concurrency and history

Writes use server-side validation, idempotency where defined and optimistic version/conflict semantics. Mutation history is append-oriented and exposed through explicit history reads.

Do not implement a frontend-only edit model that bypasses expected version or canonical transition rules.

## Evidence

Task/Commitment origin and closure behavior is evidence-aware. New states/closures must preserve the domain's required evidence/provenance semantics rather than adding a UI-only “done” flag.

## Web

The Work surface uses BFF routes under `/api/tasks` and `/api/commitments`. Browser identity comes from the server session. Routes decode canonical gateway responses and preserve conflicts/refusals.

Accepted frontend/UX intent is Drive-owned. If a feature changes Work UX, start from the current Drive product-definition router and reconcile to current backend contracts.

## Adding a field or lifecycle operation

Check all of:

1. domain aggregate/value;
2. application command/use case;
3. persistence schema/repository and Alembic;
4. public capability contract;
5. authorization/Principal isolation;
6. BFF decoder/route;
7. UI/editor/filter/history behavior;
8. migration/backfill;
9. unit/database/contract/security/E2E tests;
10. this domain reference.

Do not infer a new Task/Commitment relationship from a frontend display requirement; define and persist it explicitly when product semantics require one.
