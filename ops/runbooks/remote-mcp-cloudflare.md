# Remote MCP on NAS through Cloudflare Tunnel

This procedure deploys the separately enabled Streamable HTTP MCP process and
an outbound-only named Cloudflare Tunnel. It does not deploy automatically and
does not authorize production activation. The default Compose stack publishes
no NAS port; PostgreSQL remains on an existing private Docker network.

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
write-capable client requires all three independent inputs: register it with
`--writes-enabled`, create only the required grants with `--write` and an exact
`--purpose`, and run `control --remote-enabled --writes-enabled`. The process
setting `MY_PA_REMOTE_WRITES_ENABLED` remains a fourth, default-off ceiling.

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
MCP startup. A missing exact same-bridge rule is a deployment refusal; never
replace it with a broad `INPUT_FIREWALL` exception or disable DSM firewall.
The five exact rules occupy positions 3–7 after the canonical data- and
ingress-plane rules. The first admits only same-bridge TCP 8766 on the exact
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
From outside the
NAS, `/healthz` may return only generic liveness, `/readyz` must return the
catch-all 404, and `/mcp` without a valid bearer token must fail closed. Configure
the MCP client for Streamable HTTP at `https://<stable-hostname>/mcp` and its
OAuth bearer flow; never put a bearer token in the URL. Validate `initialize`,
`tools/list`, then the read-only `capabilities.get` before broader reads.

The deterministic reference-client profile validated on 2026-08-13 is the
official Python `mcp==2.0.0` `streamable_http_client` plus `ClientSession`. It
exercised initialize, discovery, seventeen canonical read capabilities,
pagination-bearing list/search requests, malformed and forged identity input,
body/result/concurrency bounds, origin authentication refusals, remote write
enablement/disablement, idempotent replay, dependency outages, and reconnect to
a newly composed server. Proprietary ChatLLM/Abacus configuration remains an
operator acceptance step because no account or client build was available here;
record its exact version and OAuth profile before production routing.

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
