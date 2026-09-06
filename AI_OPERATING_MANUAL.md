# AI Operating Manual

`AGENTS.md` is the principal repository policy. This manual explains how an AI development agent applies that policy to ordinary technical work; it does not create independent authority.

## Deterministic entry path

For repository work:

1. read `AGENTS.md`;
2. read `CONTRIBUTING.md` and `SECURITY.md` when their scopes apply;
3. authenticate repository, branch/base, head/tree, worktree and relevant PR state;
4. read `docs/00_REPOSITORY_SOURCE_INDEX.md`;
5. read the nearest current architecture/development/domain/operations/reference documents;
6. read accepted ADRs that govern the affected boundary;
7. consult the cleaned Drive product-definition index only when product/UX intent is required.

Do not reconstruct current technical truth from old Drive implementation packages, campaign reports, prior chats, or stale repository plans when code/tests/current docs can answer it.

## Truth and scope

Apply the precedence in `AGENTS.md`. In practice:

- runtime evidence governs deployed behavior;
- authenticated repository/GitHub state governs code and lifecycle identity;
- executable code, schemas, tests and accepted ADRs govern current technical contracts;
- current repository playbook documents explain those contracts and how to extend them;
- Drive product packages supply accepted intent, not executable behavior;
- historical reports and model summaries are claims/evidence, not current technical authority.

Every task needs one objective, acceptance criteria, explicit in-scope behavior/paths, out-of-scope items and stop conditions before implementation.

## Repository-truth preflight

Record at least:

```text
repository
default branch
current origin/main SHA
current tree SHA
working branch/worktree
open PRs that touch the same paths/contracts
applicable authorization
acceptance criteria
prohibited actions
```

If the base moves materially before implementation or review, reauthenticate and determine whether the plan remains valid.

## Planning a feature

Use `docs/development/feature-development-playbook.md`. The minimum technical sweep is:

1. product intent and domain semantics;
2. existing domain/code paths and dependency direction;
3. persistence/schema/migration impact;
4. application capability and contract impact;
5. HTTP/BFF impact;
6. MCP impact;
7. frontend/PWA impact;
8. identity/auth/security/privacy impact;
9. configuration/runtime impact;
10. test and CI impact;
11. operations/deployment impact;
12. documentation/ADR impact.

A missing layer is a finding to resolve, not permission to invent a second architecture.

## Coding boundaries

The stable Python shape is:

```text
apps/bootstrap -> adapters/application/infrastructure -> contracts/domain
```

- `domain` contains invariants and stays independent of application/infrastructure frameworks.
- `contracts` owns transport-neutral public shapes and ports.
- `application` owns use cases, authorization/disclosure and orchestration.
- driving adapters translate HTTP/MCP/CLI requests; they do not create new business behavior.
- `infrastructure` implements persistence/provider/job/migration ports.
- composition belongs in `bootstrap` and `apps`.

The web app is a BFF over Python capabilities, not a parallel domain layer.

## Persistence and migrations

Before database work read `docs/reference/database-migrations.md`.

Rules that deserve explicit attention:

- `MY_PA_DATABASE_URL` is required; never infer the target.
- use Alembic for schema evolution;
- preserve one intentional head;
- test empty-to-head and affected supported-upgrade paths on isolated databases;
- put domain invariants in the domain/application model and enforce durable database invariants with schema constraints where appropriate;
- treat destructive DDL/data operations as separately gated;
- do not use the canonical/shared database as a disposable test target.

## Public capabilities and MCP

Before adding or changing a capability read:

- `docs/reference/api-bff-contracts.md`;
- `docs/architecture/mcp-and-agent-integration.md`;
- `docs/reference/mcp-capabilities.md`.

Do not maintain a second hand-written MCP tool registry. MCP publication is derived from available application capabilities and command schemas. New behavior must enter through the canonical capability/command/application wiring and pass transport-parity tests.

Local stdio, remote MCP and HTTP differ in transport/authentication, not domain authority.

## Frontend work

Read `docs/architecture/frontend-bff-pwa.md` and `web/README.md`.

Preserve:

- server-derived Principal identity;
- opaque session handling;
- BFF ownership of gateway calls;
- typed refusal/disclosure semantics;
- contract decoder boundary under `web/src/lib/api/decode/`;
- current design-system/component patterns;
- responsive and accessibility expectations;
- bounded offline Quick Capture semantics.

Accepted visual/UX intent is looked up through the cleaned Drive product-definition index. Do not copy an old UI implementation plan into current technical docs.

## Testing

Read `docs/development/testing-and-review.md`.

Use the narrowest affected tests first, then the applicable repository tier. The canonical CI definitions are `.github/workflows/repository-checks.yml` and `.github/workflows/frontend-quality.yml`.

Never replace an applicable failing test with prose, retries, or a historical passing count.

## NAS build/deploy requests

`AGENTS.md §8.4` requires `.codex/skills/my-pa-nas-build-deploy/SKILL.md` before planning or action for a NAS package build/deploy request. That routing rule does not grant deployment, credential, firewall, service-interruption, destructive-restore or risk-acceptance authority.

## Documentation changes

Use `docs/development/documentation-standards.md`.

Update durable docs when behavior, contracts, architecture, security, operations, configuration or developer workflow materially changes. Keep exact-head evidence in PR/review/evidence records, not in durable current guides.

Add an ADR only for a durable cross-cutting decision that is difficult or costly to reverse.

## Review preparation

Before requesting review:

- authenticate the exact branch/head/tree;
- summarize changed paths and acceptance mapping;
- run the required validation;
- disclose failures, skips, unavailable dependencies and limitations;
- confirm no out-of-scope mutation occurred;
- update current documentation and ADRs when required;
- identify any operator-only next action.

A later commit invalidates an exact-head review.

## Historical material

`docs/campaign/`, old plans, migration campaign records, completed reviews/evidence and product-package mirrors may be useful evidence. They are not the normal current development path. Search them only when current truth does not answer a historical question or when a task explicitly requires lineage/evidence.

## Tool-specific adapters

- `CLAUDE.md` is a thin Claude router.
- `.ai/project-sources/00_AEOS_MASTER_INDEX.md` routes governance.
- `.codex/skills/` contains bounded tool/workflow skills.

None overrides `AGENTS.md` or creates application/product authority.
