# NAS runtime contract and operations

This directory records the accepted NAS runtime contract and its gated
operations. NAS-01 was an inert scaffold; current scripts can build candidates,
admit images, migrate, and start an already provisioned runtime when their live
identity checks and separate operator authorizations pass. Checked-in examples
and this README do not themselves authorize deployment or activation. For an
existing smoke-runtime upgrade from a workstation-built package, use
[`$my-pa-nas-build-deploy`](../../.codex/skills/my-pa-nas-build-deploy/SKILL.md)
and its workflow; first-time provisioning and pilot activation have different
gates in [`../runbooks/nas-lifecycle.md`](../runbooks/nas-lifecycle.md).

An existing smoke-runtime upgrade stages the exact-HEAD Git source bundle
first, before the other 13 members of the closed local package. After
NAS byte readback and bundle verification, clone it into a new exclusive clean
root-owned checkout. The fixed-purpose
[`preserved-runtime-env-preflight.py`](preserved-runtime-env-preflight.py) from
that checkout uses the verified host Python 3.8 path to check the preserved
old checkout, old image manifest and admissions, selected `smoke` mode, and
running identity. Before invoking an old wrapper, it must verify the canonical
old operator admission, source, manifest, Docker engine, admitted operator
image/platform/labels, old candidate/metadata/archive bytes and config, fixed
Git/Docker/Compose tools, socket, and dedicated mount paths. It then requires
full PASS from the authoritative pre-source gate baked into that exact old
image, run with no network, a read-only filesystem, dropped capabilities, and
fixed read-only input mounts. Host Python 3.8 is only the bootstrap verifier;
it does not replace that gate. The helper creates a labeled, transaction-bound
ephemeral gate container, waits for exit zero, removes only its verified CID,
and proves that exact CID and name are absent in a fresh daemon check. A CLI
timeout or a missing daemon is not cleanup evidence.

Only after gate PASS may the helper select the versioned old production/NAS/web
environment files in memory without changing canonical configuration, check
the admission/rendered/live hashes, and invoke the old lifecycle and
running-identity gates. The preserved checkout's
`ops/nas/compose.example.yml` must byte-match the canonical protected Compose
file. Full static ingress-manifest shape and live proxy publication are an
early screen; full ingress, public route/traffic, and Tailscale gates remain
separate. The helper reports no secret values. A refusal leaves the old runtime
selected and blocks transfer of the remaining 13 members. A pass permits
their transfer and byte readback but does not authorize
deployment, writer stopping, or protected-configuration mutation. The workflow
still repeats the full gates and live-`origin/main` checks before any
operator/image/admission mutation. The exact sequence and authority gates
are in the linked skill workflow.

If creation is ambiguous, the Docker daemon is unavailable, or cleanup cannot
be verified, stop transfer and preserve the old runtime. Report only a
sanitized non-secret gate-transaction identity for operator recovery; never
remove a foreign container. An uncatchable host `SIGKILL` may leave the gate
container behind, so its exact absence must be established before resuming.

Preflight threat model: trust begins with authenticated live `origin/main`, the
locally inventoried source bundle, exact clean root-owned new and preserved
checkouts, root-owned protected manifest/admissions, and the observed Docker
engine. Caller environment, paths, protected files, and Git/Compose/Docker
output are untrusted inputs; the helper constrains paths and file metadata,
checks byte and runtime identities, supplies a narrow process environment,
and refuses malformed or excessive output. Protected values stay in memory
and are not printed. Running as root and invoking the old Docker-socket-capable
gate/lifecycle retain inherent root/Docker authority; a `:ro` socket mount
does not constrain Docker API calls. These checks therefore depend on
trusted host binaries, daemon, and admitted artifacts. A PASS proves only the
bounded old-runtime identity check. It gives no assurance about public route,
traffic, full ingress, or Tailscale state and no authority to stop services or mutate
configuration, images, PostgreSQL, or firewall state.

Files:

- [`runtime-contract.toml`](runtime-contract.toml) is the machine-readable
  topology and authority contract used by architecture tests.
- [`compose.example.yml`](compose.example.yml) is the canonical six-service
  Compose definition. Its image, environment, path, platform, and service
  identities require exact admitted values; a checkout or example file alone
  is not a runnable deployment.
- [`compose.public-browser.example.yml`](compose.public-browser.example.yml) is an optional `--profile public-browser-edge` overlay for ADR-012 public browser Cloudflare ingress; it does not change the private six-service count.
- [`proxy-allowlist.example.caddy`](proxy-allowlist.example.caddy) defines the
  fail-closed private proxy route ordering used by the Compose contract.
- [`image-manifest.example.toml`](image-manifest.example.toml) separates the
  OCI platform-child digest, Docker image/config ID, and exported archive
  checksum. Its candidate status and placeholder evidence deliberately fail
  [`image_gate.py`](image_gate.py); only `--live` inspection of the target
  Docker engine and all four runtime archives can pass.
- Offline app/web/PostgreSQL/proxy archives are addressed at runtime by the exact
  loaded Docker image/config ID because `docker load` does not preserve a
  registry `RepoDigest`. PostgreSQL candidate creation separately verifies the
  exported child against the pinned `postgres:17.10` parent index. The OCI
  child digest, loaded config ID, and archive checksum remain distinct.
- Upstream PostgreSQL and proxy config identities are derived from the exported
  Docker archive config bytes, not from Docker Desktop's engine-specific `.Id`
  presentation. Candidate generation rechecks every archive against its build
  metadata and refuses any mismatch.
- [`operator.Dockerfile`](../docker/operator.Dockerfile) supplies a separate,
  short-lived Python 3.12 operator image. [`bootstrap-operator-runtime.sh`](bootstrap-operator-runtime.sh)
  verifies its archive before loading, binds it to the live NAS engine, and
  writes a root-owned mode-0400 admission. [`container-python.sh`](container-python.sh)
  then runs existing Python gates with no network, a read-only root, dropped
  capabilities, attached standard input, an explicit Compose-environment
  allowlist, the exact host Docker CLI and Compose plugin, and a short-lived
  Docker-socket mount. It is not a Compose service and grants no persistent
  container Docker authority. Emergency shutdown remains a host-shell path and
  does not depend on this image or its admission.
- [`start.sh`](start.sh) now prepares and starts the admitted six-service
  runtime only after exact live image, lifecycle, firewall, and running-identity
  gates pass. It uses Compose `--no-build --pull never` and cleans up a partial
  start; it is not a public-activation command.
- [`build-candidates.sh`](build-candidates.sh) refuses a dirty source tree and
  exports linux/amd64 app, web, and operator archives plus pinned PostgreSQL
  and exact digest-pinned proxy archives, metadata, and non-deployable candidate
  manifests. [`load-candidates.sh`](load-candidates.sh) first checks all four
  runtime archive and metadata hashes, then loads them into the live NAS Docker
  engine and issues an engine-bound deployable image manifest only if the live
  gate passes. The separate operator archive/admission path is described in
  [`../runbooks/nas-lifecycle.md`](../runbooks/nas-lifecycle.md).

The existing [`../compose/postgres.yml`](../compose/postgres.yml) remains a
single-Mac local-development service. It is not a NAS, pilot, or production
compose file.

NAS-03 introduced a PostgreSQL bind-mount contract plus explicit
[`validate-storage.sh`](validate-storage.sh), [`migrate.sh`](migrate.sh),
[`backup.sh`](backup.sh), and
[`restore-to-scratch.sh`](restore-to-scratch.sh) operations. They all require a
live-verified [`postgres-resources.example.toml`](postgres-resources.example.toml)
replacement bound to the exact Docker engine and canonical local filesystem.
The checked-in example refuses, and numeric PostgreSQL tuning remains absent
until CPU, memory, free storage, and filesystem type are measured on that NAS.
Migration is never an application startup side effect; canonical migration also
requires a recent backup receipt. Backups are custom-format, integrity-listed,
owner-only artifacts outside every current or preserved repository involved.
The destination itself must be an existing unlinked physical directory owned
by the effective operator with exact mode `0700`; backup partials are created
atomically with no-clobber and never replace a pre-existing regular file or
symlink.
Restore accepts only a new
`my_pa_scratch_*` database and retains a failed scratch target for diagnosis.
During a live-main smoke upgrade, current `backup.sh` has an explicit
preserved-runtime mode: the old checkout remains authoritative for its
manifest, Compose, runtime/bootstrap admissions, PostgreSQL resource, and live
container identity, while the exact clean current checkout is authenticated by
its deployable manifest plus the existing root-owned current operator admission,
whose complete authoritative schema binds the same source, engine, operator
image, externally staged candidate/archive/metadata paths and byte digests,
Python, Git, OpenSSL, and Compose identities. Canonical Docker runs the
standalone gate baked into that exact admitted operator image with no network
and a read-only filesystem. External inputs use distinct fixed
`/run/my-pa-input/` mount destinations and cannot shadow `/usr/local` tooling
or the baked gate. That gate validates the external artifacts and the
authoritative full image-manifest shape before any current-checkout path is
executed; truncated, extra-field, moved, or byte-mismatched artifacts refuse.
The mode refuses missing, dirty, linked, reused, or drifted source identities;
it does not copy firewall logic or permit a direct `pg_dump` escape hatch.
The gated two-phase bootstrap first issues a separate root-owned PostgreSQL
bootstrap admission from the selected canonical Compose service. This admission
requires no application, web, Entra, or edge credentials; fixed invalid values
satisfy Compose's whole-file interpolation only, and the admission proves none
reaches the PostgreSQL service or network. Prepare then creates the canonical
stopped Compose container and internal `my-pa-nas-contract_data-plane` network
before issuing the container-bound resource artifact; start separately
revalidates and starts only PostgreSQL. That state is temporary. The full
six-service runtime still requires its own exact runtime admission and real
operator-provisioned configuration. `postgresql_default`, the local-development
Compose file, ad-hoc PostgreSQL, and direct production `docker compose up
postgres` are not bootstrap paths.

[`synology-data-plane-firewall.sh`](synology-data-plane-firewall.sh) admits a
repository-owned `MY_PA_DATA_PLANE` chain as rule 1 inside DSM
`FORWARD_FIREWALL`, before every DSM acceptance rule. Built-in `FORWARD`
retains its single jump to `FORWARD_FIREWALL`. The MY-PA chain ACCEPTs only the exact Compose-owned internal
data-plane same-bridge/subnet 4-tuple (P1), then DROPs every other packet with
that bridge as in-interface (P2) or out-interface (P3), then RETURNs unrelated
forwarding to DSM. Built-in FORWARD and `FORWARD_FIREWALL` order are inspected
through `iptables-save -t filter` because direct built-in-chain inspection is
unreliable on this DSM.
`DEFAULT_FORWARD` is not an accepted equivalent, Docker isolation stays unwired,
and a leftover source-only data-plane RETURN in `FORWARD_FIREWALL` is refused.
Read-only `plan`/`check` are separate from explicitly confirmed, idempotent
`apply` and exact `remove`. `remove` resumes missing-jump and empty
unreferenced-chain cleanup; `apply` still populates an empty unreferenced
chain; proven legacy with the chain absent is already-removed. PostgreSQL database operations and ordinary runtime
start/restart/health refuse if the gate is missing. DSM firewall reload or NAS
reboot can clear runtime iptables state, so recovery must re-apply and re-check
before service lifecycle operations. Passing this gate does not admit the
ingress-plane or Cloudflare-egress gates, and does not authorize GoodNotes
validation.

[`synology-ingress-plane-firewall.sh`](synology-ingress-plane-firewall.sh)
applies the same exact-identity contract to the internal ingress bridge without
widening the host firewall. The data-plane rule must remain first; the ingress
rule must be the single exact second `FORWARD_FIREWALL` rule. Ordinary start
creates the stopped six-service topology before checking this gate, allowing a
new deployment to admit the real Compose-owned ingress bridge without starting
services. Start, restart, health, and diagnostics refuse when the gate is not
effective.

NAS-04/05 add the validated `container` gateway bind mode and the
[`runtime-services.example.toml`](runtime-services.example.toml) identity
contract. [`runtime_gate.py`](runtime_gate.py) binds each app container to its
exact Compose service, loaded image, dedicated non-root UID/GID, networks,
mounts, and absence of host publication or privilege. Its live permission pass
requires reads through allowed roots, refuses writes to config/source roots,
and performs a create/sync/rename/delete probe only in the gateway's managed
root. The checked-in example refuses until live NAS IDs and ACLs are provisioned.

NAS-06 keeps both the data and ingress planes internal, gives the application
services no external egress plane, hardens the exact Caddy route allowlist, and
requires a server-only canonical HTTPS origin. Synology Docker 24 does not
materialize a loopback host publication for a container attached only to an
internal bridge, so the hardened proxy alone also joins the non-internal
`host-edge` bridge. No application or database service joins that bridge, and
the proxy retains no database credential or application filesystem authority.
[`ingress_gate.py`](ingress_gate.py)
is read-only: it binds verified proxy, loopback publication, config hash, private
Tailscale Serve mapping, disabled Funnel, production browser passkey authentication
(historical credentialed `local_operator` browser mode is superseded), and the
absence of Entra configuration in the live gateway/web
environments. The proxy drops every capability before adding back only
`NET_BIND_SERVICE`: the pinned upstream Caddy binary carries that file capability
and Linux refuses to execute it under `no-new-privileges` when it is absent,
even though the runtime listener itself is the unprivileged port 8080.
The web service also clears the upstream Node image entrypoint explicitly, so
the inspected runtime process is exactly the declared `node server.js` command.
On Synology, invoke the gate through `container-python.sh` with
`MY_PA_NAS_TAILSCALE` bound to the exact absolute host CLI path and
`MY_PA_NAS_TAILSCALE_SOCKET` bound to the exact absolute live daemon-socket path. The wrapper
mounts both read-only at their conventional container paths only when both
values are present; supplying just one or a non-socket path refuses before the
operator container starts.

`container-python.sh` treats its host Docker client, Compose plugin, Git
binary, and operator admission as fixed trusted paths. It ignores caller
overrides for `MY_PA_NAS_DOCKER`, `MY_PA_NAS_COMPOSE_PLUGIN`, and
`MY_PA_NAS_OPERATOR_ADMISSION`; do not use those names to select alternate
tools or admissions for an operator invocation. Before either Docker or Git
runs, the wrapper verifies those paths and their ancestors are root-owned,
non-writable, non-symlinked, and identity-stable. The resolved repository root
must also be root-owned with exact mode `0700` before either tool runs because
the checkout is later bind-mounted into the Docker-socket operator container.
The operator admission must
be a root-owned, mode-0400 regular file with exactly one link. It passes only its documented
Compose/synthetic-acceptance environment-name allowlist to the Docker client;
unrelated inherited process environment is removed.
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

The canonical pilot runs `local_operator`; the flag may be omitted and, if
supplied, must match the fixed local operator. The dormant source overlay still
contains its separately gated multi-principal mode, but it is not selected by
the production stack. The Mac agent requires
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

The separately enabled remote MCP candidate is owned by [`remote/compose.yml`](remote/compose.yml).
It does not modify the existing private web ingress: its Cloudflare origin network
is internal, its tunnel is outbound-only, and the default publishes no NAS port.
On Synology, [`synology-cloudflare-egress-firewall.sh`](synology-cloudflare-egress-firewall.sh)
admits only the exact Compose egress bridge and DNS/Cloudflare Tunnel ports,
after the existing data- and ingress-plane rules.
See [`../runbooks/remote-mcp-cloudflare.md`](../runbooks/remote-mcp-cloudflare.md)
for exact configuration, deployment, rollback, client, and loopback-fallback procedures.

UI-IMP-WP29 adds a non-secret production environment schema, placeholder env,
deployment-manifest example, fail-closed `validate-production-env.py` /
`validate-delivery-config.py`, and dry-run `rollback.sh`. Public hostname is
`pa.bobby-fetting.me`. Canonical origin is exactly
`https://pa.bobby-fetting.me`. WebAuthn RP ID is exactly `pa.bobby-fetting.me`.
This repository documentation does not perform DNS or Cloudflare routing and
does not attest to their current live state.
See [`../runbooks/production-frontend-deployment.md`](../runbooks/production-frontend-deployment.md).

Production authentication (current; historical browser `local_operator` is
superseded):

- Browser production authentication is **passkey**.
- Browser setup (`/setup`) and operator recovery (`/recover/operator`) are
  WebAuthn plus one-time operator grants issued by
  [`../../apps/cli/auth.py`](../../apps/cli/auth.py).
- The private gateway **may** remain `local_operator` (capability plane). That
  is not a browser authentication mode and is not a recovery fallback.
- Browser passkey sessions and the gateway bind the same durable
  `LOCAL_OPERATOR_UUID` `24abf5d2-d0c2-5e1c-82f6-e72425e9ed37`. There is no
  caller-configurable Principal environment variable.
- Production web `MYPA_AUTH_MODE` is `passkey`. Forbidden browser values remain
  `synthetic`, `local_operator`, and `entra`. Entra/MSAL browser variables stay
  forbidden. BFF/Python session-service and WebAuthn secret pairs must match;
  [`validate-production-env.py`](validate-production-env.py) compares them
  without printing either value; given `--deployment-manifest` it also refuses
  `MYPA_SOURCE_COMMIT` / `MYPA_SOURCE_TREE` that are absent or disagree with
  the manifest `repository_commit` / `repository_tree` the image gate bound
  the image labels to.
- Private smoke is transport-only. Production WebAuthn is observed only at
  `https://pa.bobby-fetting.me` after `PRODUCTION_ACTIVATION_APPROVED`. The
  operator-gated procedure is
  [`../runbooks/auth-runtime-validation.md`](../runbooks/auth-runtime-validation.md)
  (**UNEXECUTED / OPERATOR-GATED**). Its inert template is
  [`auth-runtime-evidence.example.toml`](auth-runtime-evidence.example.toml);
  validate structure with
  [`validate-auth-runtime-evidence.py`](validate-auth-runtime-evidence.py)
  `--allow-template`. Neither file is runtime evidence.

Derive the single Alembic head from the `migrations/versions` chain at the
deployed commit; no stored revision in this README is deployment authority.

Implementation areas by package:

- NAS-02 images supply app/web Dockerfiles and the
  platform/digest/archive contract.
  Live NAS inspection, image load, and deployable-manifest issuance remain
  operator/device gates; checked-in examples are not deployable admissions;
- NAS-03 PostgreSQL storage, migration, backup, and scratch restore;
- NAS-04/05 services and filesystem permissions;
- NAS-06 private HTTPS ingress, production browser passkey (historical
  credentialed local-operator browser access is superseded), gateway
  `local_operator` transport, and proof that gateway/web have no Entra
  configuration or application egress;
- NAS-07 live Apple/TCC activation and real credential minting remain operator gates;
- NAS-10 acceptance.
