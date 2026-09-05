# Development workflow

## Objective first

Every change starts with:

- one objective;
- acceptance criteria;
- in-scope behavior/paths;
- explicit out-of-scope items;
- security/data/deployment/destructive boundaries;
- exact repository/base identity.

Do not start implementation from a vague “improve X” prompt.

## Branching

A normal change:

1. authenticate current `origin/main`;
2. create a short-lived branch/worktree from that exact base;
3. keep the PR single-purpose;
4. reauthenticate if the base or adjacent contracts move materially.

Repository policy governs who may create/merge/clean up a branch. A development plan is not merge or deployment authority.

## Plan from contracts inward/outward

For each feature, inspect:

- accepted product intent if needed;
- domain model/invariants;
- existing application capability/use case;
- persistence and migration chain;
- HTTP/BFF and MCP mappings;
- auth/security/configuration;
- frontend state/PWA implications;
- tests/CI;
- runtime/operations;
- docs/ADR implications.

Use `feature-development-playbook.md`.

## Implementation order

Default order when multiple layers change:

1. pure domain rules and tests;
2. transport-neutral contracts/ports;
3. schema/migration and persistence adapter;
4. application use case/policy/disclosure;
5. composition;
6. HTTP/MCP/CLI exposure;
7. BFF/decoder/frontend;
8. operations/config updates;
9. documentation.

This is a dependency order, not a requirement to touch every layer.

## Minimal implementation

Follow `AGENTS.md` YAGNI rules:

- no speculative service/registry/plugin abstraction;
- no new process/database/cache/queue without a current need;
- no unrelated refactor;
- limited duplication is acceptable before a shared contract is stable;
- a new dependency needs a current reason and removal/maintenance story.

## Database changes

Use Alembic and an isolated database. Verify:

- single intentional head;
- empty-to-head;
- affected supported upgrade path;
- schema constraints;
- forward safety;
- no inferred destructive target.

Do not run destructive migration commands against an unverified/shared target.

## Contract changes

A public capability change is cross-transport by default. Confirm:

- command/request shape;
- response/error/disclosure semantics;
- authorization/purpose;
- idempotency/conflict behavior;
- MCP schema derivation;
- HTTP/CLI parity;
- BFF decoder/route impact.

## Frontend changes

Preserve the BFF boundary. Browser code should not gain direct Principal/gateway authority.

Update relevant:

- server route;
- decoder/types/fixtures;
- component/page;
- unit tests;
- contract tests;
- security/accessibility/responsive/E2E tests.

Use Drive product/UX intent as intent, not as executable implementation truth.

## Configuration

If adding a setting:

1. define it in the canonical settings model;
2. choose a fail-closed default or no default;
3. validate it;
4. classify whether it is secret/sensitive;
5. document it in `.env.example` or `web/.env.example`;
6. test unknown/invalid/boundary behavior;
7. document runtime/backward-compatibility impact.

## Documentation

Update current playbook docs when a change alters behavior, architecture, contract, configuration, testing, operations or developer workflow. Do not add chronology to durable docs.

## Before review

Run the narrow affected tests, then the required tier. Confirm:

- exact head/tree;
- diff matches objective;
- docs and examples match current code;
- failures/skips/limitations disclosed;
- migration/config/security impact stated;
- no unrelated mutation;
- operator-only actions identified.

Review must bind to the exact head; a later commit invalidates it.
