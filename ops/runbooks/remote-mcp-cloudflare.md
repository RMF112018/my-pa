# Remote MCP on NAS through Cloudflare Tunnel

This procedure deploys the separately enabled Streamable HTTP MCP process and
an outbound-only named Cloudflare Tunnel. It does not deploy automatically and
does not authorize production activation. The default Compose stack publishes
no NAS port; PostgreSQL remains on an existing private Docker network.

## Operator values and secrets

Choose the stable MCP hostname, Cloudflare account/tunnel UUID, exact NAS paths,
dedicated numeric UIDs/GIDs, and digest-pinned application and `cloudflared`
images. Register the OAuth client and the existing durable `my-pa`
client-to-Principal/capability binding before startup; the caller never supplies
an authoritative Principal. Store the database password, OAuth material (if any),
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

Allow outbound traffic only as follows: `cloudflared` needs DNS and Cloudflare
Tunnel connectivity on TCP/UDP 7844 (TCP 443 fallback) to Cloudflare's published
Tunnel endpoints; the MCP process needs DNS plus HTTPS only to the exact issuer
and JWKS hosts in its environment. Neither service needs inbound firewall rules.
Reconcile these names against current Cloudflare and identity-provider primary
documentation when activating; IPs are intentionally not frozen in Git.

Cloudflare Access is optional defense in depth only. If enabled, its policy must
admit the chosen MCP client's OAuth flow without widening either route, and its
identity never substitutes for the origin bearer token, durable client binding,
or application authorization. A request that passes Access but fails origin
OAuth validation remains denied. Do not add an Access bypass rule for `/mcp`.

After migrating the database, use the supported operator CLI rather than direct
SQL to establish the initial read-only binding:

```bash
python apps/cli/remote_mcp.py register \
  --principal-uuid "$PRINCIPAL_UUID" --oauth-client-id "$OAUTH_CLIENT_ID"
python apps/cli/remote_mcp.py grant \
  --remote-client-uuid "$REMOTE_CLIENT_UUID" --scope my-pa.read \
  --capability capabilities.get --resource "$OAUTH_AUDIENCE"
python apps/cli/remote_mcp.py control --remote-enabled --no-writes-enabled
```

Emergency withdrawal is durable: run `control --no-remote-enabled
--no-writes-enabled`; revoke one client with `revoke --remote-client-uuid ...`.
Revoke an individual grant with `revoke-grant --grant-uuid ...`. Production
client registrations and grants should include a UTC `--expires-at` timestamp.
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

Inspect the rendered model: it must contain no `ports`, no database service,
no Docker socket, and only `/mcp`, `/healthz`, and OAuth protected-resource
metadata, followed by the 404 catch-all. `/readyz` is intentionally not an
edge route. Validate the tunnel ownership/UUID with the operator's authenticated
Cloudflare tooling; do not paste its output into tickets or logs if it contains
account or credential data.

## Deploy, verify, and connect

```bash
set -a
. /volume1/my-pa/secrets/mcp-remote.env
set +a
python -m alembic upgrade head
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml --profile remote-edge pull
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
  --data-network "$MY_PA_DATA_NETWORK"
docker compose --env-file /volume1/my-pa/config/remote-compose.env \
  -f ops/nas/remote/compose.yml exec my-pa-mcp-remote \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8766/readyz').status)"
```

The private readiness probe must return 200 before client use. From outside the
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
my-pa-mcp-remote`; this does not start the tunnel. Stop either profile with the
same files and `down`. Use bounded logs (`logs --tail 100`) and do not enable
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
