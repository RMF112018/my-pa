# Deployment and runtime architecture

MY-PA is still an unreleased candidate. Repository deployment assets describe supported technical topology; they do not constitute production activation.

## Process topology

The core Python runtime has:

- `apps/gateway.py` — HTTP/MCP composition root;
- `apps/worker.py` — enrollment, capture or re-enrichment worker plane;
- operator CLI programs under `apps/cli/`.

The web application runs separately under `web/` and calls the Python gateway through the BFF boundary.

PostgreSQL is a separate service. NAS deployment definitions live under `ops/nas/` and container definitions under `ops/docker/`.

## Network boundaries

The Python gateway defaults to loopback and admits an explicit container bind mode for container-local service communication. NAS Compose does not make every internal process a public service.

Publishing TLS/tunnel/reverse-proxy ingress is an operational action, not something a feature should infer from a runtime flag.

Remote MCP/capture surfaces are independently enabled and authenticated.

## Filesystem boundaries

- source roots are operator-registered and read-only by default;
- managed-document root is explicit and separate;
- NAS runtime paths/configuration are defined under `ops/nas/`;
- Apple personal-data access has platform/TCC boundaries outside ordinary Linux/container code.

## Database lifecycle

The runtime requires an explicit PostgreSQL URL. Schema migration is an explicit deployment/startup concern; do not assume an application process should opportunistically mutate schema.

Use `ops/runbooks/postgres-operations.md` and deployment runbooks for actual procedures.

## NAS build/deploy agent routing

For AI-agent requests to build or deploy the NAS package, `AGENTS.md §8.4` routes through:

`.codex/skills/my-pa-nas-build-deploy/SKILL.md`

The skill points to current runbooks/scripts and does not grant deployment, production, credential, firewall, service-interruption, destructive-restore or risk authority.

## Health and readiness

A running process is not the same as a ready system. Readiness combines:

- gateway/application capability composition;
- database availability/migration compatibility;
- worker plane backlog/heartbeat/dead-letter state;
- feature-specific resolver/readiness states;
- web reachability when the browser surface is in scope.

`/api/system` surfaces a bounded web view of current backend/worker states; individual domain readiness (for example report resolver readiness) must not be mislabeled as global health.

## Rollback/recovery

Rollback is subsystem-specific:

- application/container rollback;
- database restore/migration recovery;
- managed-document bytes + metadata consistency;
- worker lease/retry recovery;
- NAS lifecycle rollback.

Use [`../operations/recovery.md`](../operations/recovery.md) and detailed runbooks; do not invent a generic rollback that cannot restore all authority classes.
