# Remote MCP on NAS through Cloudflare Tunnel

This procedure deploys the separately enabled Streamable HTTP MCP process and
an outbound-only named Cloudflare Tunnel. It does not deploy automatically and
does not authorize production activation. The default Compose stack publishes
no NAS port; PostgreSQL remains on an existing private Docker network.

## Supported clients and shared contract

`my-pa` exposes one canonical MCP server, not one implementation per model
vendor. The local stdio composition remains available to the existing ChatLLM
workflow, and the separately enabled remote process exposes the same tool names,
schemas, results, annotations, and application authorization through stateless
Streamable HTTP at `https://<stable-hostname>/mcp`.

| Capability | ChatLLM | ChatGPT |
|---|---|---|
| Intentionally supported client | Yes | Yes |
| MCP server and tool contract | Shared | Shared |
| Transport | Existing stdio or remote Streamable HTTP | Remote Streamable HTTP or an operator-configured Secure MCP Tunnel |
| Client registration | Existing DCR client | DCR connector instance |
| User authentication | Existing origin OAuth 2.1 flow when remote | Origin OAuth 2.1 authorization code + PKCE S256 |
| Refresh tokens | Existing per-client setting; off by default | Per-client setting; enable before code exchange when durable linking is required |
| Authorization | Existing Principal, scope, purpose, capability-grant, and write gates | The same gates; DCR registration alone grants no tool |

ChatGPT uses Dynamic Client Registration here. Current OpenAI guidance prefers
Client ID Metadata Documents (CIMD) when an authorization server supports them,
but explicitly continues to support DCR. The repository-owned origin does not
fetch remote client metadata or JWKS and the admitted NAS topology gives the MCP
process no such egress. Adding CIMD would therefore widen the network and
authorization-server design. DCR is the smallest supported choice: ChatGPT
registers one public PKCE client for the connector instance, and the operator
then approves only that durable client through explicit grants. Do not create or
hardcode an invented OpenAI client ID or secret.

The remote tool list includes accurate MCP safety annotations and an OAuth
`securitySchemes` declaration in tool `_meta`. These are client hints only.
Bearer validation, exact resource binding, durable client state, scope/grant
intersection, application policy, and the independent write switches remain
authoritative.

Normative interoperability references:

- [Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Authentication](https://developers.openai.com/plugins/build/auth)
- [Building MCP servers for plugins and API integrations](https://developers.openai.com/api/docs/mcp)

## Connect ChatGPT in developer mode

This repository does not activate a public endpoint, create a ChatGPT
connection, or configure a Secure MCP Tunnel. After separately authorized
deployment and private readiness checks:

1. Confirm `MY_PA_REMOTE_MCP_ENABLED=true`, an exact stable HTTPS
   `MY_PA_OAUTH_AUDIENCE=https://<stable-hostname>/mcp`, matching
   `MY_PA_OAUTH_AUTHORIZATION_SERVER=https://<stable-hostname>`,
   `MY_PA_REMOTE_MCP_PUBLIC_HOST=<stable-hostname>`, intended
   `MY_PA_OAUTH_SCOPES`, and a generated owner-held
   `MY_PA_OAUTH_OPERATOR_SECRET`. Never place the secret in Git, a URL, or logs.
2. Validate the public endpoint with MCP Inspector using Streamable HTTP and the
   complete `/mcp` URL. Verify protected-resource discovery, DCR, PKCE S256,
   initialization, tool discovery, one read call, invalid-token refusal, and
   grant enforcement.
3. In ChatGPT, open **Settings → Security and login** and enable **Developer
   mode**. Availability depends on account and workspace policy.
4. Open ChatGPT Plugins, select the plus button, provide a user-facing name and
   description, and enter `https://<stable-hostname>/mcp`. For an approved
   private-network alternative, select an already configured Secure MCP Tunnel;
   this repository does not create one.
5. ChatGPT performs DCR and opens the origin authorization page. Record the
   public client ID shown on that page. Before approving, use the operator CLI
   to grant only the required capabilities to that exact ID. Start with a
   bounded read grant such as `capabilities.get` using the commands below.
6. If durable linking is required, enable refresh for that exact client before
   approving. Merely requesting `refresh_token` during DCR does not override the
   repository's default-off refresh policy.
7. Enter the owner-held operator secret on the origin page and approve. ChatGPT
   completes the authorization-code + PKCE exchange. Review the discovered tool
   list, start a new chat with the connection enabled, call
   `capabilities.get`, and confirm mutation tools remain absent unless separately
   and intentionally granted and enabled.

The compact ChatLLM façade is a **publication profile on this same `/mcp`
resource**, default-off. It does not add a URL, OAuth audience, or
protected-resource document. `MY_PA_MCP_CHATLLM_GATEWAY_ENABLED` plus an exact
OAuth client-ID allowlist (`MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS`) selects
which already-registered clients see `my_pa.describe` / `my_pa.read` (and
conditional write/operator umbrellas) instead of the canonical catalog.
Enabling either variable in production, writing live client IDs, or cutting
ChatLLM over to the façade is a separate operator commissioning act. Rollback is
unsetting the flag; grants and OAuth clients are unchanged.

Example bounded approval, using only public identifiers and no secret values:

```bash
python apps/cli/remote_mcp.py grant \
  --oauth-client-id "$CHATGPT_OAUTH_CLIENT_ID" --scope my-pa.read \
  --capability capabilities.get --purpose status_observation \
  --resource "$MY_PA_OAUTH_AUDIENCE"
python apps/cli/remote_mcp.py set-client-refresh \
  --oauth-client-id "$CHATGPT_OAUTH_CLIENT_ID" --refresh-enabled
```

Omit the second command when interactive reauthorization is acceptable. To
withdraw the connection, revoke the exact client. Refresh-token rotation,
replay-family revocation, one-hour access tokens, and 30-day idle/90-day
absolute refresh-family limits remain those of ADR-009.

ChatGPT UI validation is an external operator step. A local or CI protocol test
must be reported separately and must not be described as a successful ChatGPT
workspace connection.

## Operator values and secrets

Choose the stable MCP hostname, Cloudflare account/tunnel UUID, exact NAS paths,
dedicated numeric UIDs/GIDs, and digest-pinned application and `cloudflared`
images. The origin OAuth server dynamically registers a public PKCE client and
binds it to the repository-defined `LOCAL_OPERATOR_UUID`; the caller never
supplies an authoritative Principal. Store the database password, OAuth operator secret,
and named-tunnel `credentials.json` only in owner-readable NAS files. Never put
them in the Compose interpolation file, Git, command history, or logs.

Copy `ops/nas/remote/compose.env.example` and `remote.env.example` outside the
checkout. Replace every example/REQUIRED value. The remote profile starts
read-only: `MY_PA_REMOTE_WRITES_ENABLED=false`. The global remote switch is
independent of the stdio process. Ensure the three host roots are canonical,
non-overlapping directories; source and config roots are mounted read-only and
only the managed root is writable.
Percent-encode any reserved characters in the database password embedded in
`MY_PA_DATABASE_URL`; the complete DSN belongs only in the owner-readable remote
environment file.

The checked-in Cloudflare example pins the official multi-platform
`cloudflare/cloudflared:2026.7.3` manifest at
`sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf`.
Re-verify that tag-to-digest binding against the official registry before every
deployment; an upgrade is a reviewed repository change, never a mutable tag.

The Synology cgroup-v1 kernel exposes neither the CFS quota controller nor the
PIDs controller. This stack therefore pins the MCP origin and connector to
different single-core CPU sets and retains hard memory limits. Do not replace
the CPU sets with Compose `cpus`: Docker rejects that setting on the production
NAS before container startup. The stack makes no false PID-controller claim:
Docker silently discards `pids_limit` there, and UID-scoped `nproc` is not a
container-isolated substitute.

Allow outbound traffic only as follows: `cloudflared` needs DNS and Cloudflare
Tunnel connectivity on TCP/UDP 7844 (TCP 443 fallback) to Cloudflare's published
Tunnel endpoints. The MCP process needs only the private PostgreSQL and origin
networks; it performs no identity-provider or JWKS egress. Neither service needs
an inbound firewall rule.

Cloudflare Access is optional defense in depth only. If enabled, its policy must
admit the chosen MCP client's OAuth flow without widening either route, and its
identity never substitutes for the origin bearer token, durable client binding,
or application authorization. A request that passes Access but fails origin
OAuth validation remains denied. Do not add an Access bypass rule for `/mcp`.

After migrating the database, complete dynamic client registration. It creates a
write-disabled durable client already constrained to `LOCAL_OPERATOR_UUID`.
Use the returned public client ID with the supported operator CLI, rather than
direct SQL, to establish explicit read grants:

```bash
python apps/cli/remote_mcp.py grant \
  --oauth-client-id "$OAUTH_CLIENT_ID" --scope my-pa.read \
  --capability capabilities.get --resource "$OAUTH_AUDIENCE"
python apps/cli/remote_mcp.py control --remote-enabled --no-writes-enabled
```

Emergency withdrawal is durable: run `control --no-remote-enabled
--no-writes-enabled`; revoke one client with `revoke --oauth-client-id ...`.
Revoke an individual grant with `revoke-grant --grant-uuid ...`. Ordinary
production grants may include a UTC `--expires-at` timestamp. The dedicated
ChatLLM full-data-management profile is the exception: required application-data
grants for that client use omitted `--expires-at` (`NULL`). Reconcile that
profile with `profile-diff` / `profile-plan` / `profile-apply` as documented in
[`managed-knowledge-context.md`](managed-knowledge-context.md). OAuth token
lifetimes stay finite.
For a purpose-bound grant, add `--purpose <canonical-purpose>`. Enabling a
write-capable client requires all independent inputs: the existing client must
be marked write-enabled with `set-client-writes --oauth-client-id ...
--writes-enabled` (do not re-register a live client just to flip that flag),
create only the required grants with `--write` and an exact `--purpose`, and
run `control --remote-enabled --writes-enabled`. The process setting
`MY_PA_REMOTE_WRITES_ENABLED` remains a further, default-off ceiling.

Refresh tokens are optional and off by default. Merging refresh-capable code
does not change existing clients. After an additive migration and image
deploy, enable refresh for one exact client only:

```bash
python apps/cli/remote_mcp.py set-client-refresh \
  --oauth-client-id "$OAUTH_CLIENT_ID" --refresh-enabled
```

Then complete one interactive authorization-code flow to seed a refresh family.
Ordinary access tokens remain one hour. Isolated tests may inject a shorter
access lifetime through the authorization-server constructor; production
settings do not. Production activation, live Abacus proof, and burn-in remain
operator-gated.

To roll refresh back without dropping tables: `set-client-refresh
--no-refresh-enabled` for the affected client, then revert the application
image if needed. Do not use Alembic downgrade as the first rollback; dropping
refresh tables destroys stored authorization.

Revoke a refresh family by presenting the refresh token to `/oauth/revoke` or
by revoking the client. Both are non-oracular. Never log tokens or digests.

## Prepare and validate

```bash
python ops/nas/remote/validate.py
python ops/nas/remote/render-cloudflared-config.py \
  --output /volume1/my-pa/cloudflared/config.yml \
  --tunnel-id "$TUNNEL_ID" --hostname "$MCP_HOSTNAME"
chmod 600 /volume1/my-pa/secrets/mcp-remote.env
chown "$CLOUDFLARED_UID:$CLOUDFLARED_GID" \
  /volume1/my-pa/secrets/cloudflared \
  /volume1/my-pa/cloudflared/config.yml \
  /volume1/my-pa/secrets/cloudflared/credentials.json
chmod 500 /volume1/my-pa/secrets/cloudflared
chmod 400 /volume1/my-pa/cloudflared/config.yml \
  /volume1/my-pa/secrets/cloudflared/credentials.json
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge config --quiet
```

`MY_PA_DATA_NETWORK` must be exactly
`my-pa-nas-contract_data-plane`. Never use `postgresql_default`, the local-only
`ops/compose/postgres.yml`, or an independently created PostgreSQL container.
The network must already be internal and owned by Compose project
`my-pa-nas-contract`; its admitted `postgres` service must be running healthy
on the exact image recorded by the verified PostgreSQL resource artifact.
On Synology, run `ops/nas/synology-data-plane-firewall.sh check` before private
MCP startup. That gate requires FORWARD `MY_PA_DATA_PLANE` then
`FORWARD_FIREWALL`, exact P1/P2/P3 enforcement, and no leftover source-only
data-plane RETURN. Passing it does not admit the ingress-plane or
Cloudflare-egress gates and does not authorize GoodNotes validation. Never
replace it with a broad `INPUT_FIREWALL` exception, `DEFAULT_FORWARD`, or a
disabled DSM firewall.
The five exact Cloudflare rules occupy positions 3–7 after the canonical data-
and ingress-plane `FORWARD_FIREWALL` rules those sibling gates still require. The first admits only same-bridge TCP 8766 on the exact
internal Compose-owned `mcp-origin` network, allowing `cloudflared` to reach the
origin without admitting host or external ingress. The remaining four admit
only DNS over TCP/UDP 53, Cloudflare Tunnel QUIC over UDP 7844, and the
documented TCP 7844/443 paths from the exact Compose-owned egress bridge. The
gate also requires Docker's exact masquerade rule. A broad source-network or
all-port allowance is not supported.

Inspect the rendered model: it must contain no `ports`, no database service,
no Docker socket, and only `/mcp`, `/healthz`, OAuth discovery, registration,
authorization, token, revocation, and protected-resource routes followed by the
404 catch-all. `/readyz` is intentionally not an edge route. Validate the tunnel
ownership/UUID with the operator's authenticated
Cloudflare tooling; do not paste its output into tickets or logs if it contains
account or credential data.

The origin-OAuth migration admits only the established empty remote-client
baseline. If any legacy `identity.remote_clients` row exists, migration refuses
before changing the schema. Resolve that identity through the repository-owned
operator workflow and obtain a fresh backup before retrying; do not relabel or
delete a row merely to satisfy the gate.

## Deploy, verify, and connect

```bash
set -a
. /volume1/my-pa/secrets/mcp-remote.env
set +a
# Online Alembic reads MY_PA_MIGRATION_DATABASE_URL and does not fall back
# to MY_PA_DATABASE_URL. Set the migration URL in this shell before upgrading.
python -m alembic upgrade head
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge pull
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge create cloudflared
sudo ops/nas/synology-cloudflare-egress-firewall.sh plan
sudo env MY_PA_CONFIRM_FIREWALL_MUTATION=my-pa-remote-mcp_cloudflare-egress \
  ops/nas/synology-cloudflare-egress-firewall.sh apply
sudo ops/nas/synology-cloudflare-egress-firewall.sh check
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge up -d --no-build
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge ps
set -a
. /volume1/my-pa/config/remote-compose.env
set +a
python ops/nas/remote/live-gate.py \
  --app-container my-pa-remote-mcp-my-pa-mcp-remote-1 \
  --edge-container my-pa-remote-mcp-cloudflared-1 \
  --app-image "$MY_PA_APP_IMAGE_ID" \
  --edge-image "$MY_PA_CLOUDFLARED_IMAGE" \
  --data-network "$MY_PA_DATA_NETWORK" \
  --postgres-resources /etc/my-pa/postgres-resources.toml
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml exec my-pa-mcp-remote \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8766/readyz').status)"
```

The private readiness probe must return 200 before client use. Prove discovery,
DCR, operator-secret approval, PKCE S256 exchange, one-time code use, bearer
validation, token revocation, and the server-side local-operator binding before
edge cutover. Never print the approval secret, authorization code, or token.

The origin consent page sets `Content-Security-Policy` `form-action` to `'self'`
plus the registered callback origin. Chromium and Brave apply `form-action` to
the 303 that follows Approve; omitting the callback origin makes the button
appear inert after a successful authorization-code write. Do not tighten
`form-action` back to `'self'` alone.

From outside the
NAS, `/healthz` may return only generic liveness, `/readyz` must return the
catch-all 404, and `/mcp` without a valid bearer token must fail closed. Configure
the MCP client for Streamable HTTP at `https://<stable-hostname>/mcp` and its
OAuth bearer flow; never put a bearer token in the URL. Validate `initialize`,
`tools/list`, then a domain-only `capabilities.get` before broader reads.

Remote MCP clients send domain/tool arguments only. The origin establishes
authenticated Principal, contract version, request identity, request time,
authorization Purpose, and an empty declared scope at the remote MCP boundary.
Do not coach a generic MCP client to invent `purpose`, `request_id`,
`requested_at`, `principal_id`, `contract_version`, `scope`, or
`idempotency_key`. Caller-supplied copies of those fields are refused. The
origin stamps a content-addressed idempotency key for remote writes so a model
retry does not invent a protocol. HTTP, stdio MCP, and the operator CLI keep
the caller-visible key on the canonical command.

When a capability permits more than one Purpose and the client holds more than
one of them (or a capability-wide grant), the origin stamps a canonical remote
Purpose: `capabilities.get` uses `status_observation`, and `sources.fetch` uses
`source_inspection`. A client granted only the other permitted Purpose still
receives that one. HTTP, stdio MCP, and the operator CLI keep the full
canonical envelope.

The deterministic reference-client profile validated on 2026-08-13 is the
official Python `mcp==2.0.0` `streamable_http_client` plus `ClientSession`. It
exercised initialize, discovery, seventeen canonical read capabilities,
pagination-bearing list/search requests, malformed and forged identity input,
body/result/concurrency bounds, origin authentication refusals, remote write
enablement/disablement, idempotent replay, dependency outages, and reconnect to
a newly composed server. Proprietary ChatLLM/Abacus configuration remains an
operator acceptance step because no account or client build was available here;
record its exact version and OAuth profile before production routing. A later
adapter correction made remote `tools/call` accept domain arguments without
internal envelope fields; reconnect ChatLLM after deploying that image so it
reloads `tools/list`. `context.prepare` grants, ChatLLM operating contract, the
task-management grant profile, and rollback of those grants are
[`managed-knowledge-context.md`](managed-knowledge-context.md); production is
not activated and live Abacus OAuth remains operator-gated.

Start only the origin for private diagnostics with `--profile remote-mcp up -d
my-pa-mcp-remote`; this does not start the tunnel. The origin-only profile may
be stopped with the same files and `down` only when the remote-edge network and
firewall were never admitted. An admitted remote-edge deployment must use the
ordered teardown below. Use bounded logs (`logs --tail 100`) and do not enable
request-body or authorization-header logging. The one sanctioned exception is
the redacted, operator-accepted `/mcp` interaction log
(`MY_PA_MCP_INTERACTION_LOG_ENABLED`, default `false`), which stores to
PostgreSQL rather than to container logs and never stores the authorization
header; enabling it, reading it and its 14-day purge are
[`mcp-interaction-log.md`](mcp-interaction-log.md).

## Rollback

Record the last known-good application and cloudflared digests before changing
the interpolation file. To roll back, disable the Cloudflare DNS/tunnel route or
stop `cloudflared` first, set the two prior digests, render and inspect Compose,
then run `up -d --no-build`. Do not roll back Alembic and do not restore database
or managed files merely to roll back these stateless containers. Re-run private
readiness and the unauthenticated-denial check before restoring the route. If
the new release wrote data, older code may be incompatible; keep the tunnel
stopped and escalate rather than altering durable state.

Never delete the Compose egress network while its firewall rules remain. For a
full remote-edge teardown, stop the connector, remove and verify the exact
rules while the admitted network identity still exists, and only then run
Compose down:

```bash
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge stop cloudflared
sudo env MY_PA_CONFIRM_FIREWALL_MUTATION=my-pa-remote-mcp_cloudflare-egress \
  ops/nas/synology-cloudflare-egress-firewall.sh remove
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge down
```

Exact stateless rollback sequence, after replacing the two image entries in the
owner-only Compose environment with the recorded prior digests:

```bash
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge stop cloudflared
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge config --quiet
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge up -d --no-build --pull never
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml exec my-pa-mcp-remote \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8766/readyz').status)"
```

## Loopback fallback

Only when the NAS container network cannot support the preferred arrangement,
add `-f ops/nas/remote/compose.loopback.yml`; this publishes only
`127.0.0.1:<explicit-port>`. Run a host-network `cloudflared` whose ingress
service is that loopback URL, preserve the same two-route allowlist and 404
catch-all, and verify from a second LAN host that the port is unreachable. A
non-loopback bind is a failed deployment, not a supported fallback.

### Explicit compact operator publication

`MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS` is a non-secret, comma-separated
exact OAuth client allowlist, empty by default. It must be a subset of
`MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS`; the compact gateway must also be
enabled. Match the authenticated token-derived client ID, never a request field.
This separate ceiling can publish `sources.enroll` and the four identity correction
names alongside ordinary capabilities. It creates no grants and changes neither
principal identity nor domain, client/global write, source, composition or
Knowledge gates. Existing clients and the ordinary `chatllm-data-v10` profile
retain their existing behavior when this new setting is absent.

For a full inventory, reconcile the ordinary profile first. The ordinary profile
excludes 28 names. Explicitly review individual purpose-bound grants for 21 of them:
the seven `constraint_sync.*`, four identity corrections, `sources.enroll`, three
GoodNotes pull protocol names, two Knowledge discovery writes, two compatibility
names and `gsqs.start/status`. Use the existing `grant` CLI for eligible individual
grants. The other 7 are the withheld lineage names `issues.close`, `issues.reopen`,
`records.associations.confirm`, `issues.memberships.confirm`,
`issues.project_links.confirm`, `records.backfill.plan` and `records.backfill.report`:
they are `CONTROL_PLANE_EXCLUDED` (attested to the local operator surface, or the
operator-only backfill dry run) and are **never** part of an inventory grant, an
individual grant or a profile (operator directive 2026-10-26; see
[Record lineage client exposure (P1)](#record-lineage-client-exposure-p1)).
The two Knowledge discovery writes require the existing exact Knowledge Manager
binding and `profile-apply`; raw `grant` refuses them. An ordinary profile diff
flags other control-plane grants as unexpected, so it is not the full inventory
acceptance check. Do not widen the ordinary profile or infer execution authority
from publication. Each grant keeps its canonical permitted purpose, exact scope
and resource and canonical write flag.

The deployed inventory contained 190 names; current main adds
`reports.types.create` (write) and `reports.types.list` (read). A full catalog check must enumerate each current capability and identify
missing composition or authorization gates explicitly. Paginated `my_pa.describe`
proves eligible contract exposure; successful metadata calls and isolated
synthetic family tests provide separate execution evidence. Catalogs, missing
argument errors and denied calls alone do not prove successful writes. No live
source enrollment, identity correction, ingestion or campaign execution is needed
for publication verification. GoodNotes correct/pull/complete and GSQS start use
`my_pa.write` and remain behind the remote write gates.

The explicit extra-grant manifest is below. Supply the actual public client ID,
accepted scope and exact `/mcp` resource to each reviewed CLI invocation. `write`
means include `--write` in `grant`. This table is planning evidence, not approval
to execute an operation or disclose data.

| Canonical capability | Purpose | Write | Installer |
| --- | --- | --- | --- |
| capabilities.get | status_observation | no | grant |
| continuity.tasks.create | continuity_authoring | yes | grant |
| constraint_sync.state | constraint_sync_read | no | grant |
| constraint_sync.delta | constraint_sync_read | no | grant |
| constraint_sync.conflicts | constraint_sync_read | no | grant |
| constraint_sync.preview | constraint_sync_authoring | yes | grant |
| constraint_sync.apply | constraint_sync_authoring | yes | grant |
| constraint_sync.acknowledge | constraint_sync_authoring | yes | grant |
| constraint_sync.resolve | constraint_sync_authoring | yes | grant |
| entities.merge.preview | entity_identity_correction | yes | grant |
| entities.merge | entity_identity_correction | yes | grant |
| entities.split.preview | entity_identity_correction | yes | grant |
| entities.split | entity_identity_correction | yes | grant |
| sources.enroll | bounded_enrollment | yes | grant |
| goodnotes.pull | goodnotes_pull | yes | grant |
| goodnotes.complete | goodnotes_pull | yes | grant |
| goodnotes.status | goodnotes_pull_observation | no | grant |
| knowledge.assertions.submit | knowledge_assertion_observation | yes | manager profile-apply |
| knowledge.discovery.checkpoint | knowledge_assertion_observation | yes | manager profile-apply |
| gsqs.start | gsqs_b0_execution | yes | grant |
| gsqs.status | gsqs_b0_observation | no | grant |

Knowledge Manager binding still requires the Knowledge/RI composition and its
checkpoint signing configuration. Identity correction, GoodNotes pull and other
optional planes retain their separate gates. Missing prerequisites are incomplete
activation, never a successful smaller substitute for the full inventory.

## Default-off database profiles (bounded implementation, not commissioned)

`MY_PA_MCP_DATABASE_PROFILES_ENABLED` defaults to false. Enabling it is a separate
operator commissioning action; neither this runbook nor a passing synthetic test
activates access. This implementation does not change live grants, clients,
credentials, HBA, networking, deployments or the migration chain.

The operator configures disjoint exact `MY_PA_MCP_DATABASE_RO_CLIENT_IDS` and
`MY_PA_MCP_DATABASE_RW_CLIENT_IDS`. Unknown clients are refused. Durable OAuth
registration, revocation/expiry, audience, scope, purpose, capability grants and
all existing write switches still apply. An RO mapping cannot promote. An RW
mapping without a surviving supported write capability/purpose grant or whose
write switches are closed uses the RO service. The MCP request cannot
supply a connection/role/DSN selector. There is no legacy/owner fallback when a
bound service is required or a role/target check fails.

Provide distinct `MY_PA_MCP_DATABASE_RO_PASSWORD_FILE` and
`MY_PA_MCP_DATABASE_RW_PASSWORD_FILE` plus
`MY_PA_MCP_DATABASE_EXPECTED_CLUSTER_ID`. The two passwords are read only when
the feature is deliberately enabled. Each file must be an absolute, non-symlink,
single-link regular file owned by the process UID with mode 0400, under a
canonical mode-0700 directory owned by that UID. Values never enter settings,
repr, tool schemas or error messages. Canonical NAS credentials remain root-held;
do not chmod/chown or mount them into a non-root service without a separately
approved delivery plan proving effective NAS ACL rights. POSIX loader checks do
not replace that NAS ACL proof.

Data connections use fixed `my_pa_mcp_ro` / `my_pa_mcp_rw` identities on the same
configured endpoint/database as the separately trusted control connection. Each
checkout checks the cluster through the control path and compares data server,
database and role identities, elevated attributes, memberships, persistent
ownership and schema/database CREATE powers. RO transactions also use READ ONLY.
Reviewed server TLS and channel-binding URL options are preserved. Query options
that can override role, endpoint, service or session authority (and unreviewed
client-certificate inputs) are refused rather than silently copied or discarded.
Two immutable application services bind all main/specialized UOW factories to
these data pools. Authentication and mandatory durable audit remain separate
trusted server paths; review their existing credential scope before commissioning.
The audit pool stays independent of work rollback and pool checkout. Automatic
business re-enrichment observations are not run by this profiled MCP path.

`MY_PA_MCP_DATABASE_WITNESS_ENABLED` also defaults to false and requires the
profiles to be enabled. When explicitly enabled, an authenticated
`capabilities.get` / `status_observation` response may include the same closed
receipt in `_meta` and a second text block (the first response envelope remains
unchanged). Text content is model-visible at the MCP protocol boundary; `_meta`
may be hidden by clients. Actual ChatGPT/Abacus receipt visibility is verified
only during separately authorized authenticated acceptance. The receipt covers
that request: selected data-role and database identity checks, the
actual work-transaction READ ONLY setting, and a matching audit commit on an
independent engine and pool. Control-path independence is configured structural
evidence, not observation of authentication/control SQL. No SQL, parameters,
credentials, client IDs, connection strings or file paths enter this receipt.
An incomplete or failed request emits no positive receipt. The default-off path
does not issue the extra transaction-setting query. See the witness contract in
[mcp-and-cli-operations.md](mcp-and-cli-operations.md) for its precise limits.
A passing synthetic test is not installed evidence: commissioning this witness
requires a separately reviewed image build, authorized deployment/configuration
and authenticated acceptance against that exact image. The receipt proves this
status request's work-transaction BEGIN and audit commit, not a business query,
all pool connections, crash recovery or future requests.

The closed capability matrix is in `contracts/mcp_database_profiles.py`:
26 reviewed read capabilities and, for effective RW only,
`canvas.workspace.put` (a Principal-scoped overlay with no feed flush). An RW
mapping alone grants no capability. Report writes, Record Event-producing
mutations, source writes, auth/control writes, preview/checkpoint side effects
and all unreviewed/new capabilities remain unavailable. Tool discovery, direct
calls and compact umbrella targets share the same ceiling. Generic transport
refusals retain their existing ProblemDetail behavior; application authorization
continues to record durable decisions and fails closed on audit failure.

In particular, the role grant manifest still denies report DML and feed writes.
Do not route these through the audit or owner connection, suppress feed failures,
change report guards or grant broad permissions to make them work. Business/feed
atomicity and guarded report commits remain unchanged. Extending this capability
matrix requires independent persistence review and, if needed, a separately
approved grant delta. No report-writing readiness is claimed.

The process has two additional bounded data pools when enabled: control and
audit each retain five connections, RO/RW data each have five, optional interaction
recording has five. With zero overflow this caps these pools at 20 connections
(or 25 with the optional recorder), excluding other existing processes. Keep
MCP's concurrency bound and independent audit progress; verify aggregate server
headroom before commissioning. Interaction recording remains independently off.

After a separately authorized implementation review and secret/config delivery,
commission only explicitly approved client IDs and capabilities against the
exact reviewed image and reauthenticated target. For withdrawal disable routing
and/or revoke only the commissioned client's grants and drain the process; never
fall back to an owner connection. This work does not authorize any such action.

## Record lineage client exposure (P1)

**Nothing in this section is executed by the repository change that adds it.** It is
the operator's P2 procedure for the
[P1 client-exposure contract](../../docs/architecture/record-lineage-client-exposure-contract.md)
(ADR-015 decision 16, operator directive 2026-10-26). Every switch below stays
default-off in code; every command below is a mutation or a production read that only the
operator (or the Manager, for the read-only recon) runs, in the order of
[P2 steps](#p2-steps-operator-in-order).

**How each client reaches lineage.** Both the ChatLLM gateway client and the ChatGPT
connector reach lineage on the **default remote MCP path** of this runbook: the same `/mcp`
resource, the same operator Principal, the server-stamped OAuth client id, and the same
grant, purpose and write gates. A remote client reaches a lineage capability exactly when
the process composes it (the switches below), the client holds its own durable grant on it,
and — for a write — every remote write gate is open. The compact façade
(`MY_PA_MCP_CHATLLM_GATEWAY_ENABLED` and its allowlist) changes only the tool shape, never
what is reachable. The ChatLLM data profile is `chatllm-data-v10`: it plans the 34
client-usable lineage-plane names as `DATA_CONDITIONAL` on the `LINEAGE` or
`PROGRAM_REPORTING` prerequisite, so `profile-plan` adds them exactly when the planner runs
with the serving process's switches on. The restricted MCP database profiles are **not**
the path: they are not commissioned, and lineage on them fails closed (see the opt-in value
below).

**Withheld from both clients, always:** `issues.close`, `issues.reopen`,
`records.associations.confirm`, `issues.memberships.confirm`,
`issues.project_links.confirm`, `records.backfill.plan` and `records.backfill.report`
(and the update of a closed Issue, which `issues.update`'s handler refuses to any
non-attested caller). All 7 are operator kind, so no remote publication lists them; the
ChatLLM profile classifies them `CONTROL_PLANE_EXCLUDED`, so an active grant on one is an
`unexpected_control_plane` finding and `profile-diff` is unhealthy. Never grant one.

### Production environment block (P2; names and values, no secrets)

Remote MCP process — the owner-only file named by `MY_PA_REMOTE_ENV_FILE`; set or change
exactly these lines:

```env
MY_PA_LINEAGE_ENABLED=true
MY_PA_PROGRAM_REPORTING_ENABLED=true
MY_PA_LINEAGE_BACKFILL_ENABLED=true
MY_PA_REMOTE_WRITES_ENABLED=true
```

Gateway process — the owner-only file named by `MY_PA_NAS_ENV_FILE` (the human channel's
CLI and `invoke` route run here). The enrollment and capture workers share that file; the
lines are inert for them:

```env
MY_PA_LINEAGE_ENABLED=true
MY_PA_PROGRAM_REPORTING_ENABLED=true
MY_PA_LINEAGE_BACKFILL_ENABLED=true
```

**Must remain as deployed, verified read-only before P2 proceeds:**
`MY_PA_MCP_DATABASE_PROFILES_ENABLED` absent or `false`;
`MY_PA_MCP_DATABASE_PROFILE_OPT_INS` absent; `MY_PA_MCP_DATABASE_WITNESS_ENABLED` absent
or `false`; `MY_PA_MCP_CHATLLM_GATEWAY_ENABLED`,
`MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS` and
`MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS` unchanged (and the deployed compose overlay
files reused exactly); `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` unchanged — if it is off,
`programs.*` stay unserved and unplanned, which is correct, not a fault.

Every one-off CLI container (`apps/cli/remote_mcp.py`, `apps/cli/invoke.py`) runs with the
environment of the process it acts for, so the planner sees the same planes. **The planner
desires lineage grants only when it runs with the serving process's switches**; run with
the wrong environment it reports no lineage gap rather than a wrong one.
`MY_PA_LINEAGE_BACKFILL_ENABLED` on the remote process publishes nothing (both backfill
names are operator kind); it is set there only so both files state the directive's switch
set identically.

### Switch matrix

| Switch | Code default | Enables | Depends on | P2 value |
| --- | --- | --- | --- | --- |
| `MY_PA_LINEAGE_ENABLED` | `false` | serves 32 of the 34 lineage names in the process (the 2 backfill names also need their sub-switch); the v10 planner desires the 27 `LINEAGE` names | nothing | `true` (gateway, remote MCP) |
| `MY_PA_PROGRAM_REPORTING_ENABLED` | `false` | serves the 7 S4 names; builds a 5-connection Program read pool per composing process | `MY_PA_LINEAGE_ENABLED`; the 2 `programs.*` reads also `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` and a Program read factory, `programs.overview` the Constraint plane | `true` (gateway, remote MCP) |
| `MY_PA_LINEAGE_BACKFILL_ENABLED` | `false` | serves the 2 operator-only dry-run names (no apply exists) | `MY_PA_LINEAGE_ENABLED` | `true` (gateway; inert on remote MCP) |
| `MY_PA_REMOTE_WRITES_ENABLED` | `false` | publishes and admits **every** remote write a client is granted, not only lineage | `MY_PA_REMOTE_MCP_ENABLED`; durable `control --writes-enabled`; per-client `set-client-writes`; a write grant | `true` (remote MCP) |
| durable global writes (`control --writes-enabled`) | off | same, durably | `MY_PA_REMOTE_WRITES_ENABLED` | on |
| per-client writes (`set-client-writes`) | off at registration | same, per client | the 2 above | on for the ChatLLM and ChatGPT clients only |
| `MY_PA_MCP_DATABASE_PROFILES_ENABLED` | `false` | restricted `ro`/`rw` roles; refuses every unmapped client | password files, cluster id | unchanged (off) |
| `MY_PA_MCP_DATABASE_PROFILE_OPT_INS` | empty | admits the 31 names to the restricted ceilings (fail closed today) | `MY_PA_MCP_DATABASE_PROFILES_ENABLED` | unset |
| `MY_PA_MCP_CHATLLM_GATEWAY_ENABLED` + allowlist | off / empty | compact façade publication shape | — | unchanged |

**Remote writes widen all remote writes.** Turning remote writes on opens **every active
write grant of each write-enabled client, including any individually granted control-plane
or operator-ceiling writes; up to 103 from the v10 profile alone** (102 without the
Knowledge plane): the 16 lineage writes and 87 others of the data profile (`tasks.*`,
`commitments.*`, `capture.*`, `meetings.*`, `constraints.*` / `constraint_categories.*`,
`continuity.*`, `documents.*`, `entities.*`, `relationship_memory.*`, `reports.*`,
`review.decide`, `canvas.workspace.put`, `context.feedback`, `goodnotes.correct` /
`propose`, `knowledge.assertions.create` and `project_controls.configure` writes). For a
client in `MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS` the compact operator ceiling also
publishes granted `entities.merge` / `split` (and previews) and `sources.enroll`;
individually granted `constraint_sync.*`, GoodNotes pull and `gsqs.start` writes open the
same way. No read-only CLI lists a client's grants, and `profile-diff` reports a
non-desired name `EXCLUDED` whether or not it is granted, so the read-only recon below is
how the operator learns the real set. Turning remote writes on is therefore a decision
about each write-enabled client's whole write grant set; the per-client flag is the control
that limits it to the 2 named clients.

### Read-only recon before any write gate opens

A read-only database enumeration, run in P2 by the operator or the Manager (never by a
repository worker), of every remote client: its `writes_enabled` flag, the durable global
`writes_enabled` and `remote_enabled` controls, and every active capability grant
(capability, purpose, `is_write`, scope, resource, expiry, grant UUID); plus, from the
deployed remote env file, `MY_PA_REMOTE_WRITES_ENABLED`,
`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`, and membership of each client id in
`MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS` and
`MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS`. Record the ChatLLM and ChatGPT client ids.

**Stop** (no write gate is opened) if any client other than those 2 holds a write grant
together with a write flag that is or would become effective; if any client holds an
active grant on one of the 7 withheld names (revoke it first by UUID, then re-run this
step); or if either named client holds write grants beyond those the operator has decided
to open (see the switch matrix).

### Durable state and grants (P2, operator; each a mutation)

Run these only after the recon passes:

```bash
python apps/cli/remote_mcp.py control --remote-enabled --writes-enabled
python apps/cli/remote_mcp.py set-client-writes --oauth-client-id "$CHATLLM_OAUTH_CLIENT_ID" --writes-enabled
python apps/cli/remote_mcp.py set-client-writes --oauth-client-id "$CHATGPT_OAUTH_CLIENT_ID" --writes-enabled
python apps/cli/remote_mcp.py profile-diff --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10
python apps/cli/remote_mcp.py profile-plan --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10
python apps/cli/remote_mcp.py profile-apply --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10 --apply
```

**Health.** P2 requires `profile-diff` to report `healthy: true` for each client before and
after apply. If `unexpected_control_plane` names a withheld lineage name, revoke that grant
with `revoke-grant --grant-uuid <uuid>` (the UUID comes from the read-only recon, because
`profile-diff` does not print it) and re-run `profile-diff`. `profile-apply` is not
health-gated, so this check is the operator's.

**The operator's choice per client, explicit:**

1. **The v10 profile.** If `profile-plan` adds exactly the 34 names of the grant table
   below (a client converged on `chatllm-data-v9`), apply it. If it adds more (a client
   not on the full-data profile, which the ChatGPT client may be), applying it
   deliberately grants the whole v10 profile, companions included.
2. **The 34 plus chosen companions.** Issue the 34 individually with `grant
   --oauth-client-id … --scope my-pa.read --capability <name> --purpose <purpose>
   [--write] --resource "$OAUTH_AUDIENCE"` from the grant table below (`--write` for the
   16 writes), **and** the companions for every family the client should link, from the
   companion table below. Without them only Issue-family lineage works: every other
   endpoint answers as absent and both composites are `denied`.

Never grant a withheld name: the 7 withheld names are never part of a profile, an
individual grant or any "full inventory" grant review.

The 34 client-usable lineage-plane grants (`write` means include `--write`):

| Canonical capability | Purpose | Write |
| --- | --- | --- |
| issues.create | issue_authoring | yes |
| issues.update | issue_authoring | yes |
| issues.read | issue_read | no |
| issues.list | issue_read | no |
| issues.history | issue_read | no |
| issues.timeline | issue_read | no |
| issues.closure_readiness | issue_read | no |
| issues.project_links.add | issue_authoring | yes |
| issues.project_links.end | issue_authoring | yes |
| issues.memberships.add | issue_authoring | yes |
| issues.memberships.end | issue_authoring | yes |
| issues.memberships.correct | issue_authoring | yes |
| issues.handoffs.record | issue_authoring | yes |
| issues.handoffs.correct | issue_authoring | yes |
| issues.handoffs.list | issue_read | no |
| issues.work.create_task | issue_work_authoring | yes |
| issues.work.create_commitment | issue_work_authoring | yes |
| records.associations.assert | record_lineage_authoring | yes |
| records.associations.correct | record_lineage_authoring | yes |
| records.associations.end | record_lineage_authoring | yes |
| records.associations.contest | record_lineage_authoring | yes |
| records.associations.reinstate | record_lineage_authoring | yes |
| records.associations.history | record_lineage_read | no |
| records.lineage | record_lineage_read | no |
| records.lineage.related | record_lineage_read | no |
| meetings.notes.versions | meeting_read | no |
| meetings.notes.read_version | meeting_note_history_read | no |
| programs.members.resolve | program_reporting_read | no |
| programs.overview | program_reporting_read | no |
| commitments.v2.read | commitment_read | no |
| commitments.v2.list | commitment_read | no |
| commitments.v2.search | commitment_read | no |
| commitments.v2.waiting_on | commitment_read | no |
| reports.manifest | report_read | no |

The companion grants a client given the 34 individually needs for each family it should
link (each companion's purpose is its one permitted purpose):

| Companion | Purpose | Write | Needed for |
| --- | --- | --- | --- |
| `meetings.read`, `meetings.list` | `meeting_read` | no | Meeting and note-version endpoints, anchors and seeds |
| `tasks.read`, `tasks.list` | `task_read` | no | Task endpoints and seeds |
| `commitments.read`, `commitments.list` | `commitment_read` | no | Commitment endpoints, seeds and handoff Commitments |
| `constraints.read`, `constraints.list` | `constraint_read` | no | Constraint endpoints (Constraint plane composed) |
| `capture.read`, `capture.list` | `capture_review` | no | Capture-version endpoints and anchors |
| `tasks.create` | `task_authoring` | yes | `issues.work.create_task` |
| `commitments.create` | `commitment_authoring` | yes | `issues.work.create_commitment` |

### The restricted-profile opt-in value (documentation only)

The canonical serialization of the full admissible opt-in set (sorted by name,
comma-separated, no spaces) is below. **Documentation only — do not set.** Pasted into the
remote environment while the database profiles are off, it stops the remote MCP at start;
with them on, every opted-in lineage call fails closed until a separately reviewed
privilege mechanism for existing objects exists, and every client not mapped `ro`/`rw` is
refused outright — so commissioning the profiles for ChatGPT would **remove** lineage (and
every other capability outside the restricted ceilings) from it. It is not part of the P2
environment block.

```text
MY_PA_MCP_DATABASE_PROFILE_OPT_INS=commitments.v2.list,commitments.v2.read,commitments.v2.search,commitments.v2.waiting_on,issues.closure_readiness,issues.create,issues.handoffs.correct,issues.handoffs.list,issues.handoffs.record,issues.history,issues.list,issues.memberships.add,issues.memberships.correct,issues.memberships.end,issues.project_links.add,issues.project_links.end,issues.read,issues.timeline,issues.update,issues.work.create_commitment,issues.work.create_task,meetings.notes.read_version,meetings.notes.versions,records.associations.assert,records.associations.contest,records.associations.correct,records.associations.end,records.associations.history,records.associations.reinstate,records.lineage,records.lineage.related
```

`programs.*` and `reports.manifest` are never admissible there (S4 D-46, S3.1 D-21).
`tests/contract/test_lineage_client_exposure_runbook.py` keeps this value, the environment
blocks, the grant table and the companion table equal to the code.

### P2 steps (operator, in order)

None of these is authorized by the repository change; each is the operator's:

1. Merge the P1 pull request (its CI green on the required gates).
2. Back up the production database ([`postgres-operations.md`](postgres-operations.md)).
3. Migrate to `023f8f7eb499`.
4. Build and load the images at the merge commit; recreate the gateway and the remote MCP
   with the deployed compose files and overlays reused exactly.
5. Before recreating, verify read-only that the remote env has the database profiles off
   and no opt-in; stop if not.
6. Set the environment lines above; recreate.
7. Run the read-only recon above; stop on any stop condition.
8. `control --remote-enabled --writes-enabled`; `set-client-writes` for the 2 clients only.
9. `profile-diff` / `profile-plan` v10 per client; then `profile-apply` or the 34 plus
   chosen companions. Require `healthy: true` before and after; if
   `unexpected_control_plane` names a withheld lineage name, revoke it (UUID from step 7)
   and re-diff.
10. Acceptance with synthetic, non-personal data, per client: `profile-diff` healthy, and
    the client's publication (façade `my_pa.describe` or canonical `tools/list`, per its
    allowlist membership) lists exactly the composed v10 lineage subset (34, or 32 with
    the entity plane off) and none of the 7; one cross-family association (for example a
    Task `originated_from` a Meeting note version) is committed and recorded
    `client_identified` with that client's id; a confirm from the CLI promotes it;
    `issues.close` from either client is absent and `unsupported`.
11. Optionally, the backfill dry run from the CLI (no apply exists).
12. Size the connection budget: the gateway reaches 15 backends with Program reporting on,
    and the remote MCP process adds its own 5-connection Program pool.

### Residual risks (stated plainly)

Every S3.1 residual becomes live once the 2 clients are provisioned and writes are on:

- **Unverifiable client and user claims.** The server knows the transport and the OAuth
  client id; it cannot know whether a human or a model composed a call, whether the user
  directed it, or whether evidence supports the relation. Every remote client is the
  operator Principal. `client_identified` means "an authenticated client wrote this";
  `user_directed_claim` means "that client said so". Both clients are model-driven.
- **Shared or stolen client credentials** make 2 agents 1 bucket and 1 label; revoking the
  client's grant or token is the control.
- **stdio and unstamped local callers** share 1 bucket with no client id, for any stdio
  process run with `MY_PA_LINEAGE_ENABLED`.
- **Review load.** Each client can commit up to 120 requests an hour (a composite writes up
  to 5 links) of unreviewed facts that hold Issue closes until the operator confirms or
  revises each through the CLI or `invoke`; no web review UI exists.
- **Cross-client interference.** ChatLLM and ChatGPT can end, correct or contest each
  other's never-accepted facts, and contest an accepted semantic link once; each such
  revision holds the close until reviewed.
- **Shared Principal budget.** The 2 clients (and any other granted client and the stdio
  bucket) share the Principal's 2000/day; one can deny lineage writes to the other for up
  to 24 hours. Revoking its grant or write flag is the control.
- **Refused writes serialize on the allocator lock.** A refused client write consumes no
  budget but, once past the commit mark, holds the Principal's allocator lock until it
  rolls back, so a client spamming refusable writes slows the operator's own lineage
  writes.
- **The human channel is whoever holds the gateway `invoke` credential or the CLI.** It is
  the only promoter of client facts, so that credential is accepted-lineage authority.
- **A byte-identical re-assert after an `end` replays the old answer**; **a local caller
  reusing an operator key gets `conflict`**; **buckets proliferate** with dynamic client
  registration, bounded only by grant issuance; **asserting `A blocks B` can reveal a
  `blocks` path** through a record the caller cannot see.
- **Reads reflect current visibility and evidence availability**; a `verified_at_commit`
  report reference proves agreement at commit only. **Database immutability is a DML
  guarantee** (CR-014 role separation is still an operator follow-up).

P1-specific:

- **Remote writes widen every write** (switch matrix above); the recon is the control.
- **Unreviewed Issue edits.** `issues.create` and `issues.update` are recorded writes, not
  reviewable facts: either client can create Issues and rename, re-describe, suspend or
  activate any open Issue with no review hold (close, reopen and closed-Issue updates stay
  attested).
- **Vendor data egress.** Both clients are external model vendors. Lineage reads return
  metadata, identifiers and offsets, but the exposed set also returns product content:
  `issues.*` titles and descriptions, `programs.overview` totals, `commitments.v2.*`
  Commitment content, `reports.manifest` sections, and `meetings.notes.read_version`
  returns historical note bodies — including text the operator later edited out of the
  current note. With the MCP interaction log on, request and response bodies are kept
  (redacted) for 14 days.
- **A 34-only client is Issue-only** without the companions.
- **Restricted profiles.** Commissioning `MY_PA_MCP_DATABASE_PROFILES_ENABLED` later
  removes lineage from every profile client until the privilege mechanism exists, and
  refuses every unmapped client.
- **Planner environment.** Run with the wrong environment the planner reports no lineage
  gap rather than a wrong one.
- **Pool budget.** Program reporting adds a 5-connection pool to every composing process,
  including the remote MCP container under its 768 MiB limit.
