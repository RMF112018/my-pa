# Deployment

This page is the developer-facing deployment router. It does not authorize deployment.

## Current topology

The repository defines a NAS/container deployment model around the existing modular monolith:

- PostgreSQL is the canonical application database.
- the Python gateway serves HTTP and, when separately invoked/configured, MCP;
- worker processes execute enrollment, capture, or re-enrichment work;
- the Next.js application is the browser/BFF tier;
- NAS Compose/runtime definitions live under `ops/nas/`, `ops/compose/`, and `ops/docker/`;
- ingress and remote MCP are explicit deployment surfaces rather than implicit application defaults.

The architectural boundary is documented in [Deployment and runtime architecture](../architecture/deployment-runtime.md).

## Before deployment work

1. Read `AGENTS.md`, especially the operator-only boundaries.
2. Read `.codex/skills/my-pa-nas-build-deploy/SKILL.md` for any NAS build/deploy request.
3. Reauthenticate the exact repository/branch/head being built.
4. Read the applicable `ops/runbooks/` procedure rather than copying a command from an old campaign record.
5. Establish exact target environment and data identity.
6. Confirm whether the requested action is merely packaging/build validation or is actual production activation.

Deployment, production activation, destructive production migration, credential mutation, live personal-data access, and material risk acceptance remain operator-gated.

## Repository entry points

- `ops/runbooks/nas-lifecycle.md` — NAS lifecycle.
- `ops/runbooks/nas-acceptance.md` — NAS acceptance/gates.
- `ops/runbooks/gateway-operations.md` — gateway process.
- `ops/runbooks/worker-operations.md` — worker process.
- `ops/runbooks/postgres-operations.md` — PostgreSQL operations.
- `ops/runbooks/remote-mcp-cloudflare.md` — remote MCP deployment boundary.
- `ops/nas/` — deployment scripts/contracts.
- `ops/compose/` — Compose definitions.
- `ops/docker/` — image definitions.

## Migration at deployment time

Schema changes are not inferred from an image or startup. Validate the intended target and migration head explicitly. Follow [Database migrations](../reference/database-migrations.md); never use a production/canonical database as a development migration target.

## Runtime verification

A deployment decision should distinguish:

- image/package built;
- process started;
- health probe passed;
- schema at intended revision;
- required capability composed and available;
- worker plane healthy when queued work requires it;
- web/BFF reachable through the intended ingress;
- authorization and refusal boundaries verified;
- rollback/recovery path still available.

A passing application test suite is not proof that a target runtime is activated correctly.

## Rollback

Use the specific runbook for the deployed surface. Do not improvise destructive database rollback. Database recovery is backup/restore- and migration-contract-dependent; see [Recovery](recovery.md).
