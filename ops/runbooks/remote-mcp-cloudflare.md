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
Revoke an individual grant with `revoke-grant --grant-uuid ...`. Production
grants should include a UTC `--expires-at` timestamp.
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
request-body or authorization-header logging.

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
