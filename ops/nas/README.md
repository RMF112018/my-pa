# NAS runtime scaffold

This directory records the accepted NAS runtime contract. NAS-01 is
non-deploying: these files do not create a NAS root, build images, start
containers, enable Tailscale Serve, initialize or migrate a database, read live
personal data, or mint credentials.

Files:

- [`runtime-contract.toml`](runtime-contract.toml) is the machine-readable
  topology and authority contract used by architecture tests.
- [`compose.example.yml`](compose.example.yml) is a disabled example of the
  future container layout. Every image, secret, NAS path, platform, and service
  identity is required explicitly; it has no usable defaults. It also names a
  NAS-04 gateway bind setting that does not exist yet, deliberately preventing
  this topology contract from being mistaken for a runnable stack.
- [`proxy-allowlist.example.caddy`](proxy-allowlist.example.caddy) shows the
  fail-closed route ordering. It is mounted only by the disabled example.
- [`image-manifest.example.toml`](image-manifest.example.toml) separates the
  OCI platform-child digest, Docker image/config ID, and exported archive
  checksum. Its candidate status and placeholder evidence deliberately fail
  [`image_gate.py`](image_gate.py); only `--live` inspection of the target
  Docker engine and all three exported archives can pass.
- Offline app/web/PostgreSQL archives are addressed at runtime by the exact
  loaded Docker image/config ID because `docker load` does not preserve a
  registry `RepoDigest`. PostgreSQL candidate creation separately verifies the
  exported child against the pinned `postgres:17.10` parent index. The OCI
  child digest, loaded config ID, and archive checksum remain distinct.
- [`start.sh`](start.sh) is an intentional refusal until the exact live NAS
  reports `linux/amd64`, loaded digest resolution is proven, and NAS-04 adds the
  gateway container bind. A later activation may use only Compose `--no-build
  --pull never` after that gate passes.
- [`build-candidates.sh`](build-candidates.sh) refuses a dirty source tree and
  exports linux/amd64 app/web archives plus BuildKit identity metadata. Its
  output is still non-deployable. [`load-candidates.sh`](load-candidates.sh)
  remains an explicit operator/device refusal until the live NAS and the exact
  official PostgreSQL platform-child archive are available.

The existing [`../compose/postgres.yml`](../compose/postgres.yml) remains a
single-Mac local-development service. It is not a NAS, pilot, or production
compose file.

NAS-03 adds an unpublished PostgreSQL bind-mount contract plus explicit
[`validate-storage.sh`](validate-storage.sh), [`migrate.sh`](migrate.sh),
[`backup.sh`](backup.sh), and
[`restore-to-scratch.sh`](restore-to-scratch.sh) operations. They all require a
live-verified [`postgres-resources.example.toml`](postgres-resources.example.toml)
replacement bound to the exact Docker engine and canonical local filesystem.
The checked-in example refuses, and numeric PostgreSQL tuning remains absent
until CPU, memory, free storage, and filesystem type are measured on that NAS.
Migration is never an application startup side effect; canonical migration also
requires a recent backup receipt. Backups are custom-format, integrity-listed,
owner-only artifacts outside the repository. Restore accepts only a new
`my_pa_scratch_*` database and retains a failed scratch target for diagnosis.

NAS-04/05 add the validated `container` gateway bind mode and the
[`runtime-services.example.toml`](runtime-services.example.toml) identity
contract. [`runtime_gate.py`](runtime_gate.py) binds each app container to its
exact Compose service, loaded image, dedicated non-root UID/GID, networks,
mounts, and absence of host publication or privilege. Its live permission pass
requires reads through allowed roots, refuses writes to config/source roots,
and performs a create/sync/rename/delete probe only in the gateway's managed
root. The checked-in example refuses until live NAS IDs and ACLs are provisioned.

NAS-06 separates the internal `ingress-plane` from the gateway/web-only
`entra-egress` plane, hardens the exact Caddy route allowlist, and requires a
server-only canonical HTTPS origin. [`ingress_gate.py`](ingress_gate.py) is
read-only: it binds verified proxy, loopback publication, config hash, private
Tailscale Serve mapping, disabled Funnel, and installed Entra egress evidence.
The checked-in ingress manifest refuses. Enabling Serve or changing a firewall
remains an explicit operator action and has no script in this package.

NAS-07 adds an off-by-default Apple machine plane at exactly
`POST /apple/v1/grant.poll` and `POST /apple/v1/envelope.admit`. The NAS stages
short-lived, Principal-bound grants through [`../../apps/apple_grant.py`](../../apps/apple_grant.py);
the Mac runs the outbound-only [`../../apps/apple_agent.py`](../../apps/apple_agent.py),
durably journals grant metadata beside (but never inside) the protected content
spool, and acknowledges content only after verifying the NAS receipt against
the exact admitted bytes. [`../../apps/cli/apple_credentials.py`](../../apps/cli/apple_credentials.py)
is the operator-only, show-once credential mint path. None of these commands
enables ingress, invokes live TCC access by itself, or supplies the Mac with a
database or general NAS filesystem credential.

In pilot `entra` mode, both operator commands require the owning
`--principal-id`; their database operations remain partitioned by that value and
refuse a bridge, configuration, or bucket owned by any other Principal. In
scratch `local_operator` mode the flag may be omitted and, if supplied, must
match the fixed local operator. The Mac agent requires
`MYPA_APPLE_CONTROL_ORIGIN`, `MYPA_APPLE_PRINCIPAL_ID`, `MYPA_APPLE_BRIDGE_ID`,
`MYPA_APPLE_BRIDGE_CREDENTIAL`, `MYPA_APPLE_HOST_EXECUTABLE`,
`MYPA_APPLE_SPOOL_DIRECTORY`, `MYPA_APPLE_GRANT_JOURNAL`,
`MYPA_APPLE_CONTACTS_IDENTITY_EPOCH`, and `MYPA_APPLE_MAIL_GENERATION`.

NAS-08 adds opt-in placement, not activation. The
[`compose.sources.example.yml`](compose.sources.example.yml) overlay gives the
existing GoodNotes operator composition one one-shot service. Its root and
manifest resolve below `/srv/my-pa/goodnotes`, its OCR executable resolves
below the exclusive `/srv/my-pa/goodnotes-ocr` mount, and both mounts are
read-only. No long-lived worker, gateway, web, proxy, or Frontier process
receives either GoodNotes authority.
[`source_gate.py`](source_gate.py) checks those identities against
[`source-contract.toml`](source-contract.toml) and refuses writable or escaped
placement.

The same overlay records Frontier as an opt-in `apps/gateway.py mcp` process
with stdin open, TTY disabled, and no `ports` or `expose`. The example
[`frontier-mcp-child.example.json`](frontier-mcp-child.example.json) launches it
with `docker compose run --rm --no-deps -T`, so its lifetime belongs to the MCP
client and the wire remains standard input/output. There is no MCP proxy route,
OAuth flow, browser path, or network listener. The profile and existing MCP
kill switch remain explicit operator decisions; external MCP use is outside
this package.

The static check is safe without a NAS or source data:

```bash
python ops/nas/source_gate.py \
  ops/nas/source-contract.toml \
  ops/nas/compose.sources.example.yml \
  ops/nas/compose.example.yml \
  ops/nas/frontier-mcp-child.example.json \
  ops/nas/proxy-allowlist.example.caddy
```

NAS-09 supplies fail-closed `preflight`, `start`, `stop`, `restart`, `status`,
readiness, diagnostics, bounded logs, and emergency-shutdown wrappers. Smoke is the default and
retains `restart: "no"`. The restart-only
[`compose.pilot.example.yml`](compose.pilot.example.yml) is accepted only when
[`lifecycle_gate.py`](lifecycle_gate.py) verifies a clean exact repository head
against root-published, detached-signature-verified NAS-10 PASS and operator
activation artifacts bound to the exact NAS engine, compose/runtime contract,
image manifest, root-published runtime admission, resolved Compose digest,
commit, and tree. Every lifecycle action checks resolved and running image
identity; smoke binds the base-only render while pilot binds the ordered
base-plus-pilot-overlay render, so caller-controlled image or mode drift refuses. Emergency shutdown bypasses those availability
gates but accepts only the canonical root-owned six-service Compose target.
Checked-in evidence examples refuse. See
[`../runbooks/nas-lifecycle.md`](../runbooks/nas-lifecycle.md).

NAS-10 adds the closed synthetic [`acceptance-matrix.toml`](acceptance-matrix.toml),
an inert evidence runner, and an exact-head independently signed review gate.
Only complete synthetic evidence can produce an unsigned NAS-09-compatible PASS
candidate; it performs no activation. See
[`../runbooks/nas-acceptance.md`](../runbooks/nas-acceptance.md).

Later packages own executable behavior:

- NAS-02 images supply app/web Dockerfiles and the
  platform/digest/archive contract.
  Live NAS inspection, image load, and deployable-manifest issuance remain
  operator/device gates; no image here is currently deployable;
- NAS-03 PostgreSQL storage, migration, backup, and scratch restore;
- NAS-04/05 services and filesystem permissions;
- NAS-06 private HTTPS ingress, Entra pilot origin, and a verified Microsoft
  OIDC/JWKS egress allowlist for gateway and web;
- NAS-07 live Apple/TCC activation and real credential minting remain operator gates;
- NAS-10 acceptance.
