# AGENTS.md

## Repository authority

Use this precedence when facts conflict:

1. authenticated runtime evidence;
2. authenticated repository and GitHub state;
3. this repository's accepted governance, specifications, ADRs, and acceptance criteria;
4. indexed Workspace publications;
5. conversations and reports as claims until verified.

## Entry sequence

1. Read this file.
2. Read `AI_OPERATING_MANUAL.md`.
3. Read `docs/00_REPOSITORY_SOURCE_INDEX.md`.
4. Read the nearest owning README or index for the paths in scope.
5. Verify the exact repository, branch, base, head, tree, PR, and authorization before mutation.

## Naming and compatibility

- Distribution/repository identity: `my-pa`
- Python namespace: `my_pa`
- Configuration prefix: `MY_PA_`
- Runnable process names: `my-pa-gateway`, `my-pa-worker`, and `my-pa`
- Canonical logical database identity: `my_pa`
- A separately configured alias may reference the existing physical database. The alias does not authorize migration, rename, schema mutation, or legacy naming in public capabilities.
- New external APIs, MCP tools, paths, and product documentation must not use legacy employer branding.

## Architecture boundaries

- `domain` depends on no application or infrastructure module.
- `application` may depend on domain contracts and ports.
- `infrastructure` implements ports and may depend inward.
- `apps` and `bootstrap` are composition boundaries.
- Source providers and managed-document stores are separate capabilities.
- Original sources are authoritative and read-only by default.
- PostgreSQL is the planned canonical metadata and knowledge store.
- Obsidian is a deterministic, rebuildable projection.

## Delivery controls

- Use a dedicated branch or worktree bound to one approved goal and base SHA.
- Keep implementation within the authorized path set and acceptance criteria.
- Preserve failed tests, unresolved findings, and exact reviewed identity.
- Reviews bind the exact PR head or commit.
- Do not self-authorize merge, destructive migration, credential mutation, deployment, production activation, or risk acceptance.

## Mandatory stops

Stop when scope must materially change; repository identity drifts; acceptance criteria conflict; credentials, production access, destructive data operations, or undisclosed irreversible actions become necessary; or a security/privacy/data-loss risk is discovered.

## Current scaffold limitation

The present repository structure is documentation-only. Directory presence does not authorize feature implementation.
