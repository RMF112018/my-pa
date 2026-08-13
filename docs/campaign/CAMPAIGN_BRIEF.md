# Campaign identity

- Campaign ID: `MYPA-REMOTE-MCP-CLOUDFLARE-20260813`
- Objective: Implement a secure remote MCP endpoint for `my-pa`, accessible through
  Cloudflare, preserving the existing application-service authorization boundary and
  producing a deployable NAS runtime candidate.
- Repository: `RMF112018/my-pa`
- Implementation branch: `bf/remote-cloudflare-mcp-20260813`

# Source implementation plan

- Title: `11_REMOTE_CLOUDFLARE_MCP_IMPLEMENTATION_PLAN_20260813`
- Drive document ID: `1yac6v7sOS2HjftO5j0-ppZI_B2khlmDDDSNGyau5R9o`
- Owning feature-package folder: `1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa`
- Planning baseline SHA: `90a0e840dc662875e39327c86ead9b71dfe644e9`
- Planning baseline tree: `de0ecf44ade7a3e49843273afff0727352e4e564`
- Current implementation baseline SHA: `90a0e840dc662875e39327c86ead9b71dfe644e9`
- Current implementation baseline tree: `de0ecf44ade7a3e49843273afff0727352e4e564`
- Material drift: none. Authenticated `origin/main` exactly matches the planning baseline.
  Open PR #81 is an unrelated GitHub Actions dependency update.

# Architectural invariants

1. MCP remains a transport adapter.
2. MCP product operations enter through `ApplicationService.invoke(...)`.
3. MCP does not directly query PostgreSQL.
4. MCP does not directly invoke repositories as an alternative application API.
5. A caller cannot provide authoritative `principal_id`.
6. Authenticated identity resolves Principal server-side.
7. External scopes do not replace internal application authorization.
8. Cloudflare is ingress/auth infrastructure, not application authorization.
9. Source systems remain read-only.
10. Managed-document writes remain isolated from source storage.
11. Existing stdio MCP remains supported.
12. Remote MCP is separately disableable.
13. Remote writes are separately disableable and default off.
14. PostgreSQL has no public port.
15. NAS services expose no unnecessary host ports.
16. Secrets never enter Git.
17. Runtime identity and configuration are explicit and reproducible.
18. Migrations remain Alembic-owned.
19. Tool schemas remain generated and validated from canonical capability contracts.
20. Degraded operation fails closed for authorization-sensitive operations.

# Tier map

| Tier | Purpose | Scope / expected components | Tests | Completion criteria | Dependencies | Status |
|---|---|---|---|---|---|---|
| 0 | Repository reconciliation and bootstrap | Git/GitHub truth, MCP/application/NAS/migration inspection, branch, this brief | status, identity, Alembic and architecture inventory | exact clean baseline and no architecture ambiguity | none | `PASS` |
| 1 | Remote MCP transport | Streamable HTTP `/mcp`, liveness/readiness, bounds, concurrency, timeout, stdio preservation | unit, contract, architecture, synthetic HTTP E2E | initialize/list/call work; safe failures; stdio green | 0 | `PASS` |
| 2 | Remote identity and Principal binding | remote clients/grants, server-side Principal binding, revocation/expiry/kill switches | migration, unit, security, cross-Principal | caller cannot select identity; grants fail closed | 1 | `PASS` |
| 3 | OAuth/protected resource | issuer/audience/client/resource validation, discovery metadata, challenge/redaction | deterministic auth/security tests | invalid/expired/revoked/insufficient credentials refused at origin | 2 | `PASS` |
| 4 | Remote tool hardening | canonical read/write classification and filtered deterministic discovery | contract, architecture, policy tests | only real canonical tools exposed; initial profile read-only | 2, 3 | `PASS` |
| 5 | NAS runtime | dedicated non-root MCP service, private networks, resource bounds, health, compose gates | compose render and synthetic container tests | no public DB/origin and independent disablement | 1–4 | `PASS` |
| 6 | Cloudflare contract | pinned tunnel service/config, route allowlist, origin protections, runbooks | config validation and loopback tests | deterministic outbound-only tunnel contract | 5 | `PASS` |
| 7 | E2E and security acceptance | reference client and positive/negative/degraded matrix | synthetic MCP/auth/security/restart tests | read-only path green; no leaks or source mutation | 1–6 | `PASS` |
| 8 | Remote write candidate | existing reversible/versioned writes with default-off policy | idempotency, conflict, audit, isolation, backup/restore | write semantics proven while default remains off | 2–7 | `PASS` |
| 9 | Deployable release candidate | full validation, docs, operator checklist, final evidence, release branch/PR | FAST, PR/FULL relevant suites, image/compose/migration/security | no known red tests; only external configuration remains | 0–8 | `IN_PROGRESS` |

# Work allocation

- Lead: architecture integration, campaign brief, conflict resolution, full validation,
  final Git/PR lifecycle.
- Transport/contracts worker: `src/my_pa/adapters/mcp/`, remote composition root and
  transport-specific tests.
- Auth/persistence worker: remote client/grant identity, Alembic migration and security tests.
- Runtime worker: `ops/nas/`, Cloudflare configuration, deployment/rollback documentation and
  runtime validation.
- Lead-owned shared surfaces: canonical application/capability contracts, cross-stream
  integration tests, final documentation and acceptance evidence.

# Running findings

- Existing MCP is official-SDK stdio and already routes normalized tool calls through
  `ApplicationService.invoke(...)` with a composition-supplied Principal.
- Repository policy and architecture tests intentionally freeze stdio-only behavior; this
  campaign deliberately extends those accepted contracts while preserving stdio compatibility.
- Existing user work was present in two other checkouts. Both are preserved untouched; this
  campaign uses an isolated clean worktree.
- Live NAS, Cloudflare account, hostname, OAuth registration and target-client credentials are
  unavailable locally. Their exact non-secret configuration contracts will be implemented and
  synthetic behavior tested; production activation remains operator configuration.
- A synthetic Linux/amd64 remote container ran as UID/GID 10001 with read-only root, all
  capabilities dropped, no-new-privileges, PID/CPU/memory limits, read-only config/source mounts,
  writable managed root, private PostgreSQL connectivity and loopback-only diagnostic publication.
  Health/readiness/401 behavior and container restart were exercised. The exact pinned
  Cloudflared image executed `ingress validate` successfully against the rendered route contract.
  A fail-closed live admission gate performs the corresponding post-start checks on the NAS,
  including exact image/command/network identity, origin-network internalness, privilege,
  capability/device, resource/restart/init, mount-containment, credential-mount and port checks.
- Git index mutations are rejected by the active execution policy even though this campaign
  authorizes normal Git work. The candidate therefore remains an uncommitted bounded change set.

# Current status

Tiers 0–8 are `PASS`. Tier 9 awaits Git commit/push/PR publication, the only
non-operator-configuration requirement the execution environment still blocks.
Live Cloudflare, OAuth and proprietary target-client activation remain explicit
operator actions.

# Final completion record

- Final branch: `bf/remote-cloudflare-mcp-20260813`.
- Final Git identity: current baseline HEAD remains
  `90a0e840dc662875e39327c86ead9b71dfe644e9` / tree
  `de0ecf44ade7a3e49843273afff0727352e4e564`; the validated candidate is present as the bounded
  working-tree change set because this execution environment denied Git index mutations. Exact
  post-commit HEAD/tree must be recorded after that policy gate is lifted.
- Alembic: empty PostgreSQL 17.10 upgraded through all 37 revisions to
  `e3b7a1d5c942 (head)`; `pg_dump`/restore into a second database preserved that head and the
  fail-closed `remote_enabled=false`, `writes_enabled=false` controls.
- A second PostgreSQL backup/restore rehearsal preserved an operator-created synthetic remote
  client and exact resource-bound grant as well as Alembic head `e3b7a1d5c942`. The remote E2E
  enters the canonical `documents.create` path through `ApplicationService.invoke(...)`; the
  existing database acceptance test for that same managed-document service restores real rows
  and immutable bytes into an emptied PostgreSQL plane and fresh managed root, then reads and
  digest-verifies every restored version. Together these prove affected durable write state,
  rather than only the new OAuth tables, survives backup/restore.
- Application validation: repository-wide Ruff check/format and strict mypy passed. The FAST
  suite passed with `5148 passed, 717 deselected`; the complete database-marked suite passed with
  `717 passed, 5147 deselected`. Focused remote transport, OAuth, migration, architecture and
  runtime suites passed with `36 passed`.
- Runtime validation: default and loopback Compose render gates passed; the static remote NAS
  validator passed; a pinned Linux/amd64 non-root application image build and default command
  passed. A constrained Linux/amd64 container connected to PostgreSQL, returned readiness 200 only
  after durable enablement, refused anonymous MCP with 401, proved root/config/source unwritable
  and the managed root writable, restarted and repeated 200/401. The pinned Cloudflared container
  validated the exact rendered ingress configuration. Live tunnel establishment requires the
  operator credential and hostname by design.
- Security acceptance: authenticated Principal comes only from the bearer credential and durable
  binding; caller `principal_id` is absent from schema and rejected if sent; scope grants intersect
  canonical capabilities and optional purpose/resource bounds; discovery, challenge, expiry,
  revocation, global/client/write kill switches, request/auth concurrency, deadlines, bounded
  bodies/results, real database readiness, DNS rebinding protection, redaction and source/managed
  write isolation are covered. A repository-wide, non-disclosing high-confidence secret-signature
  regression scans source, operations, migrations, docs, tests, workflows, configuration and web
  artifacts and passed as part of FAST. Ruff's Bandit security rules passed. This repository has
  no configured dependency-vulnerability or container-image scanner, so no such scan is claimed;
  the built image's dependency consistency check passed.
- Deployment artifacts: `ops/nas/remote/compose.yml`, optional loopback overlay, pinned
  cloudflared `2026.7.3` contract/template/renderer/validator, live container admission gate,
  environment examples, operator CLI, and deployment/verification/rollback runbook.
- Client validation: official Python `mcp==2.0.0` Streamable HTTP client validated initialize,
  discovery, seventeen canonical remote reads, pagination-bearing calls, malformed/oversized
  input, bounded results/concurrency, remote managed-document creation/idempotent replay, write
  disablement, dependency failures and reconnect. No proprietary ChatLLM/Abacus build was
  available, so that exact external profile remains operator acceptance.
- Operator configuration remaining: choose the stable hostname; create and validate the
  Cloudflare tunnel and credentials; register the OAuth protected resource/client; provide exact
  image digests, NAS paths and service UIDs/GIDs; migrate the target database; register the
  durable Principal/client/grants; validate NAS egress/firewall/DNS; run private readiness and the
  target client's initialize/list/read-only call matrix before routing production traffic.
- Known limitation: no live NAS, Cloudflare account, OAuth registration, credentials, or target
  MCP client was available in this workspace, so external activation was deliberately not
  claimed. Git staging/commit/push/PR operations were also denied by the active execution policy,
  despite the campaign's authorization, so the validated change set has not been published.
  Remote writes remain independently default-off and require the documented four-way enablement.
- Current disposition: `IMPLEMENTATION_COMPLETE_PUBLICATION_PENDING`; Git publication is
  mechanically pending because the active execution policy rejects index writes.
  The NAS operator must still run `live-gate.py` against the credentialed named tunnel before
  production routing; exact committed HEAD/tree and PR must be recorded once Git writes are
  permitted.
