# Feature development playbook

Use this playbook to turn a product request into a technically complete implementation plan before writing code.

## 1. Authenticate repository identity

Record:

- repository;
- default branch/current `origin/main`;
- base commit/tree;
- active branch/worktree;
- open PRs touching the same domain/contracts;
- applicable governance/authorization.

Stop if exact identity cannot be established.

## 2. Read governing sources

Minimum:

- `AGENTS.md`;
- `docs/00_REPOSITORY_SOURCE_INDEX.md`;
- nearest current technical references;
- accepted ADRs.

If product/UX intent is required, use the cleaned Drive product-definition index and the relevant domain package. Do not treat product intent as proof of current implementation.

## 3. Define the feature contract

Write:

- user/business outcome;
- in-scope behavior;
- non-goals;
- acceptance criteria;
- authority/data/security constraints;
- expected failure/conflict states.

Separate accepted intent from current implementation facts.

## 4. Inspect current domain/code paths

Find the closest existing aggregate/use case/capability. Identify:

- domain invariants/state transitions;
- canonical identifiers;
- Principal/authority ownership;
- provenance/evidence semantics;
- idempotency/version/conflict semantics;
- existing extension points actually in use.

Do not invent a parallel model when one already exists.

## 5. Persistence impact

Answer:

- Is new durable state required?
- Which schema/table owns it?
- Is Principal partitioning required?
- What uniqueness/foreign-key/check constraints enforce invariants?
- Is append-only/version history required?
- What transaction/locking/idempotency behavior is required?
- Does an Alembic revision need data migration/backfill?
- What is the supported compatibility/rollback posture?

If no persistence change is required, say so.

## 6. Backend/domain impact

Map changes to:

- `domain/`;
- `contracts/`;
- `application/`;
- `infrastructure/`;
- `bootstrap/` / `apps/`.

Preserve dependency direction. State the implementation order.

## 7. API/BFF impact

Determine:

- new/changed capability;
- request/response/error/disclosure contract;
- HTTP route exposure;
- BFF server route;
- TypeScript decoder/types;
- optimistic-concurrency/idempotency handling;
- browser identity behavior.

Avoid browser-side domain authority.

## 8. MCP impact

Ask:

- Should the capability be MCP-visible?
- Does canonical application wiring already make it derivable?
- What purpose/capability grant applies?
- Is it read/write/operator-only?
- What happens on local stdio vs remote authenticated MCP?
- Does remote-write policy require an additional gate?
- Are ChatLLM compact-profile or other client-compatibility tests affected?

Do not create a client-specific capability vocabulary.

## 9. Frontend impact

Identify:

- page/route/component;
- loading/empty/error/conflict states;
- design-system primitives;
- responsive/accessibility behavior;
- offline/PWA implications;
- accepted Drive UX source;
- BFF/contract dependencies.

Do not design around backend behavior that does not exist; call out backend dependencies explicitly.

## 10. Security/auth impact

Evaluate:

- Principal derivation/partition isolation;
- auth/session/token behavior;
- new ingress/network exposure;
- source/managed-store authority;
- sensitive fields/logging;
- credential/config changes;
- external data disclosure;
- destructive/operator-only actions.

Add targeted negative/security tests when a boundary moves.

## 11. Configuration impact

For every new setting state:

- exact owner (`Settings`, web env, Compose/runtime);
- default/no-default;
- validation;
- secret/sensitive classification;
- example-file change;
- startup/backward-compatibility effect.

## 12. Migration impact

If schema changes:

- derive from current Alembic head;
- preserve one head;
- name down-revision explicitly;
- define empty-to-head and predecessor-to-head tests;
- define data backfill/idempotency;
- define destructive/rollback constraints.

## 13. Test strategy

Map each acceptance criterion to tests:

- unit/domain;
- application/contract;
- schema/database;
- security/policy;
- frontend unit/contract;
- browser E2E/accessibility/responsive;
- recovery/idempotency;
- specialized evaluation when needed.

Identify expensive resources and which CI tier owns them.

## 14. Implementation order

Produce dependency-ordered work packages with non-overlapping responsibilities. Shared registries/migration chain/composition are integrated deliberately, not edited concurrently without ownership.

## 15. Validation gates

Define:

- narrow local tests;
- FAST;
- affected PR/database/frontend gates;
- docs link/config validation;
- exact-head CI;
- independent review where required.

Passing tests do not authorize production or risk acceptance.

## 16. Documentation update

State which durable docs change:

- README only for front-door behavior;
- architecture for cross-cutting structure;
- domain reference for feature semantics;
- reference for contract/config/migration;
- operations for run/recovery impact;
- ADR only for durable difficult-to-reverse decisions.

Historical campaign narration does not belong in current guides.

## 17. Review/evidence preparation

Prepare:

- exact base/head/tree;
- acceptance mapping;
- changed paths;
- tests/CI results;
- migrations/config/security impact;
- deviations;
- known limitations;
- unavailable evidence;
- operator-only next actions.

A later commit invalidates exact-head review.

## Plan output template

```text
Objective
Repository/base
Accepted product-intent source
Current implementation facts
Scope / non-goals
Acceptance criteria
Domain changes
Persistence/migration changes
Application/capability changes
API/BFF/MCP changes
Frontend/PWA changes
Security/auth/config changes
Implementation sequence
Tests and CI
Documentation/ADR changes
Operational impact
Risks/assumptions/unavailable evidence
Stop conditions
```
