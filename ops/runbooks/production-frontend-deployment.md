# Production frontend deployment — `pa.bobby-fetting.me`

Repository contract for deploying the public browser origin
`https://pa.bobby-fetting.me`. This runbook is neither deployment authorization
nor evidence of the current public activation state.

DNS, Cloudflare Tunnel routing, and public cutover require a separate operator
instruction `PRODUCTION_ACTIVATION_APPROVED` for this hostname. Do not infer
that approval, or its absence, from a running container or this document.

Hostname throughout: `pa.bobby-fetting.me`. Canonical origin:
`https://pa.bobby-fetting.me`. WebAuthn RP ID: `pa.bobby-fetting.me`.

**Dated observation, not a gate admission (2026-09-26 UTC).** A read-only
`ssh bf-nas` check reached `TheLakeHouseNAS`. `https://pa.bobby-fetting.me/`
is served by the 2026-09-24 package, not by a later `origin/main`. Reauthenticate
before the next action; do not treat this snapshot as a future image selection.

Public route, verified by container identity plus an unauthenticated
`GET /api/health`:

- `frontend-cloudflared` ingress is `hostname: pa.bobby-fetting.me` →
  `service: http://public-proxy:8080`, then `http_status:404`. The tunnel
  image is `cloudflare/cloudflared:2026.7.3`. That container has no `sh`, so
  read the mounted config on the host; `docker exec sh` fails.
- `public-proxy` reverse-proxies to `web:3000` and accepts only host
  `pa.bobby-fetting.me`.
- `web` is on `my-pa-nas-contract_browser-origin` and
  `my-pa-nas-contract_ingress-plane`. Its image is
  `sha256:6f19619c20e3f6a1f9d11efd510af1b7a71cffb817a6584149392ef481c1f20e`,
  revision `cf17f7f27cb6463817e470b06f306baa10f697c2`, tree
  `6a6f79cd38b5180ff46c77c1641fc4cea95d8287`, built `2026-09-24T12:46:39Z`.
  `MYPA_CANONICAL_ORIGIN` is `https://pa.bobby-fetting.me`.
- Gateway and both workers use app image
  `sha256:108456a288c20c847e2694dab379aa6420e953909bc4d7b62bae2454a413eb01`
  with the same revision. The gateway healthcheck was `healthy`.
- The public response was `{"ok":true,"status":"live"}` with `via: 1.1 Caddy`
  and `server: cloudflare`. That web check does **not** prove the gateway
  migration probe. `apps/cli/health.py` is the probe that refuses a database
  not at the repository head.

`origin/main` later moved to `141758b93d8fccf5b571536ee41099685f2f95cf`
(Constraint desktop end-to-end reporter and frontend CI only). That commit is
not in the running images.

**Executed upgrade, 2026-09-24 UTC, with named deviations.** The package was
built by `ops/nas/build-candidates.sh` from a clean detached checkout of
then-current `origin/main` (`cf17f7f2` / `6a6f79cd`). The NAS accepted the
Git bundle by `tar` over `ssh -o BatchMode=yes`. macOS `rsync` rejected
`--info`, and the NAS SSH server refused the `scp` subsystem. The checkout
is `/volume1/my-pa/runtime-cf17f7f2-prod-20260924` (root, mode `0700`).
Archives are root-owned mode `0400` under
`/volume1/my-pa/artifacts/cf17f7f2-20260924`.

`bootstrap-operator-runtime.sh` admitted the new operator image and the
canonical operator admission was switched to that source. `load-candidates.sh`
then failed. The failure is Synology path compatibility, not a bad image or
Compose file:

- `ops/nas/container-python.sh` walks trusted paths and refuses a symlink.
  The error returned was `trusted path contains a symbolic link`.
- On this NAS, `/var/run` → `../run` (so `/var/run/docker.sock` fails first).
  `/usr/local/bin/docker`, `/usr/local/bin/docker-compose`, and `/usr/bin/git`
  are also symlinks into DSM packages and fail the same class of check.
- `load-candidates.sh` hides that stderr and prints `NAS tooling requires
  Python 3.12 or newer with tomllib` for any wrapper failure. Host Python is
  3.8.15. Do not treat that sentence as the cause.

Because the loader could not run, these gates were **not** executed:
`load-candidates.sh`, deployable image-manifest admission,
`/etc/my-pa/image-manifest.toml` update (it still described `f0f7869e`),
runtime-admission and PostgreSQL-bootstrap regeneration, preserved-runtime
`backup.sh`, `migrate.sh`, `start.sh`, firewall `plan`/`check`, writer
quiescence, and scratch restore. Do not describe this cutover as a gated
admission.

What did run, under explicit operator instruction to deploy the package:

- `docker load` of `app.tar` and `web.tar` only. Inspected IDs matched the
  candidate manifest. PostgreSQL
  `sha256:1edc8e87e53194e0cc8006c4e9df9b626c6c72cb43ad3385f0f34af7922065b1`
  and Caddy
  `sha256:af555904a0961945f16bb323a501457b13a4f7e9bde969b145b97da80b38ecbe`
  already matched the candidate, so those archives were not loaded and those
  containers were not recreated. The private proxy stayed on its previous
  container.
- Versioned `production.cf17f7f2.env` and `web.cf17f7f2.env` replaced only
  app/web image IDs, `MYPA_SOURCE_COMMIT`, `MYPA_SOURCE_TREE`, and
  `MY_PA_WEB_ENV_FILE`. No secret was printed.
- `docker compose` used both `ops/nas/compose.example.yml` and
  `ops/nas/compose.public-browser.example.yml`, profiles
  `nas-01-contract-only` and `public-browser-edge`, and `--no-build --pull never`,
  for `gateway`, both workers, `web`, `public-proxy`, and
  `frontend-cloudflared`. PostgreSQL stayed the same container.
  `start.sh` alone would recreate `web` without `browser-origin`, which drops
  it off this public proxy. The overlay is what keeps
  `https://pa.bobby-fetting.me/` on the new web container. Recreating the
  edge containers did not change the tunnel image or the Caddy upstream.
- Gateway health then reported revision `e6a4c2f91b73` and head
  `6f6ead27d122`: the database was not at the migration head and could not
  serve the build. Public `/api/health` was already `live`. A custom-format
  `pg_dump` as role `postgres` failed because that role does not exist; the
  cluster role is `my_pa` (`POSTGRES_USER` / `POSTGRES_DB`). The dump is
  `/volume1/my-pa/backups/pre-cf17f7f2-20260924T125757Z.dump`
  (3,734,716 bytes, SHA-256
  `58de69b7b92b97ffeca61be14fc2e6cfedf1644f5af2974acf924a233f419639`).
  `alembic upgrade head` inside the new gateway container applied
  `6f6ead27d122`. Its downgrade is a no-op. The gateway healthcheck then
  became `healthy`.

Do not repeat the ungated load, Compose, or Alembic steps unless the operator
explicitly accepts those deviations again. The next gated attempt still stops
at `container-python.sh` until the symlink contract matches this NAS.

## PREPARE / GATED UPGRADE

This is an already-bootstrapped canonical **smoke-runtime upgrade** route, not
first-time provisioning or pilot activation. Follow
[`$my-pa-nas-build-deploy`](../../.codex/skills/my-pa-nas-build-deploy/SKILL.md)
and its [workflow](../../.codex/skills/my-pa-nas-build-deploy/references/workflow.md)
for the complete point-of-action gates. The following is a release checklist,
not an executable remote-command recipe. An existing public edge must be
inventoried. Leaving its containers unchanged does not prevent canonical web
restart or image replacement from changing live public traffic.

1. **Authenticate current identity.** Independently verify `ssh bf-nas` host
   and device identity, linux/amd64 Docker engine, canonical project and exact
   Compose, current source commit/tree, selected and admitted lifecycle mode,
   six-service state, PostgreSQL container/resources, old image/runtime/operator
   admissions, protected configuration paths, backup status, and dependent
   writers. A `no` restart policy alone does not prove smoke mode. If the mode
   is pilot or any identity is ambiguous, stop; do not reuse the dated note.
   Distinguish this frontend tunnel from the remote MCP tunnel in
   `ops/nas/remote/`. Authenticate current public-edge routing, reachability,
   traffic, and activation-approval state using separately authorized,
   privacy-safe evidence; do not invent a public probe. If the edge is active
   or its state remains unknown, stop before writer quiescence until the
   operator approves a production-impact, maintenance, and rollback plan
   covering service interruption and an externally visible new app version.
   That approval is not permission for a new public cutover.
2. **Build on this workstation.** From a fresh detached, clean checkout of the
   *current* authenticated `origin/main`, run `ops/nas/build-candidates.sh`
   with a separately accepted exact proxy platform-child digest. No proxy
   digest recorded in this runbook is a future selection. The non-deployable
   package comprises app, web, operator, PostgreSQL, and proxy `.tar` plus
   `.metadata.json` files, `postgres.index.json`,
   `image-manifest.candidate.toml`, `operator-runtime.candidate.toml`, and an
   exact-HEAD Git source bundle: 14 inventoried members. Verify bundle
   head, SHA-256, size, and member set; re-fetch `origin/main` before transfer.
3. **Transfer source first and preflight the preserved runtime.** Prove the
   exact `sudo -n` privilege for each planned operation, an exclusive owner-only
   landing directory, and a protected root-owned staging parent. Transfer and
   read back only the inventoried source bundle first. Verify its advertised
   head and clone it without checkout into a *new* exclusive root-owned
   mode-0700 source directory at the exact HEAD/tree; require a clean worktree.
   The fixed-purpose read-only `ops/nas/preserved-runtime-env-preflight.py`
   from that verified checkout uses the bounded `/usr/bin/python3` privilege,
   first authenticates the old admission/source/manifest/engine/admitted
   operator image and candidate/metadata/archive bytes plus fixed tool,
   socket, and mount identities, then requires full PASS from the
   authoritative pre-source gate baked into that old operator image. The gate
   runs with no network, a read-only filesystem, dropped capabilities, and
   dedicated read-only inputs; host Python 3.8 does not replace it. Only after
   PASS does the helper select old versioned environment files in memory and
   invoke old lifecycle/running-identity gates for the preserved `smoke`
   runtime. Full static ingress shape and live proxy publication are an early
   screen; full ingress, Tailscale, and public route/traffic gates remain.
   A refusal stops before the other 13 members transfer and leaves all
   runtime state selected as it was. A pass permits a fresh
   `origin/main` check, transfer of the remaining 13 members, a *new*
   versioned root-owned mode-0700 NAS artifact directory with root-owned
   mode-0400 regular files, and SHA-256/size readback of all 14 members.
   Repeat the old-runtime and live-main gates before later mutation. A pass
   does not authorize writer stopping or protected-configuration mutation.
   Never modify the old checkout or copy credentials, environment, database
   dumps, or session material. Do not invent a transfer command, staging
   destination, or broader privilege; the observed absence of
   `/volume1/my-pa/deployment` is not permission to create it.
4. **Old-runtime gates, quiescence, then candidate admission.** Recheck current
   `origin/main`, public routing/traffic state, and the specific
   production-impact authorization immediately before stopping writers; stop
   on drift or missing approval. Under the *old* canonical operator/runtime
   admissions, prove the old running stack, rollback inputs, firewall state,
   and PostgreSQL identity. Separately authorize stopping the five canonical application
   writers and each dependent project; leave the same admitted PostgreSQL
   running and prove zero non-operator writers. Stage the new operator admission
   from its transferred archive. Because `container-python.sh` fixes
   `/etc/my-pa/operator-runtime.toml`, an exclusive staged admission alone
   cannot run the new checkout's loader. A separately authorized, byte-preserved
   and rollback-safe atomic switch of *only* that canonical operator admission
   must pass before `load-candidates.sh`; the old image manifest, runtime and
   PostgreSQL bootstrap admissions, Compose selection, and protected values
   remain old. Before `load-candidates.sh`, run the new checkout's
   `container-python.sh` directly and keep its stderr. On this NAS it exits
   `trusted path contains a symbolic link` because `/var/run` is a symlink and
   the Docker and Git binaries are DSM package symlinks.
   `load-candidates.sh` rewrites every such failure as a Python 3.12 error.
   That is not image or Compose failure, and host Python 3.8 is not the
   defect. Stop there; do not `docker load` around it unless the operator
   explicitly accepts the deviations in the 2026-09-24 observation above.
   When the wrapper does accept the paths, load/admit all four runtime images
   and issue the new deployable image manifest. Verify that the preserved old
   checkout is reachable to the new operator wrapper for the later backup, or
   stop. See the workflow for the exact ordering and failure recovery.
5. **Prospective configuration.** Generate new runtime and PostgreSQL
   bootstrap admissions at exclusive noncanonical paths; do not select them
   while the old stack is running. Record exact loaded app/web/PostgreSQL image
   IDs, proxy child digest, and any separately approved frontend-cloudflared
   image in a new non-secret
   [`deployment-manifest.example.toml`](../nas/deployment-manifest.example.toml)
   replacement outside Git. That deployment manifest is distinct from the
   engine-bound NAS image manifest. Validate an *already authorized* protected
   production environment in place with `validate-production-env.py` using its
   `--deployment-manifest` argument and run `validate-delivery-config.py`;
   creating or changing protected values requires separate authority. The
   validator must bind `MYPA_SOURCE_COMMIT` / `MYPA_SOURCE_TREE` to the manifest.
   Production browser auth is `passkey`, canonical origin/RP ID are exactly the
   origin/hostname above, `MYPA_SESSION_SERVICE_URL` is absent or empty, and
   each BFF/Python session-service and WebAuthn secret pair must match with
   values at least 32 characters long without being printed. Browser synthetic,
   `local_operator`, and Entra/MSAL modes are refused; there is no
   caller-configurable Principal. Gateway `local_operator` is a separate
   transport mode. Derive the single Alembic head from the checked-in migration
   chain at the deployed commit; do not copy a revision from this runbook.
6. **Protect and migrate data.** With the prior runtime identity and zero-writer
   gate still valid, use the *current* checkout's preserved-runtime mode of
   `ops/nas/backup.sh` against an existing owner-only directory outside both
   repositories. Verify its `.sha256` receipt. Prove the prospective PostgreSQL
   Compose hash and admitted container/resource identity match before any
   canonical runtime/bootstrap/config switch. Only under separate protected
   configuration and migration authorization publish the staged admissions
   together and run `ops/nas/migrate.sh`; migration is never a start side effect.
   Take and verify a post-migration backup, then restore it to a new scratch
   database and check the derived head and health. Never downgrade canonical
   `my_pa` or treat an image rollback as database rollback.
7. **Canonical start and verification.** Run `ops/nas/preflight.sh`, repeat the
   PostgreSQL compatibility proof, and obtain a separate point-of-action
   authorization for possible interruption of that *same* PostgreSQL container
   before `ops/nas/start.sh`. Revalidate the production-impact plan and
   public route/traffic state: an unchanged public edge may serve the new
   canonical web version or expose the interruption. Stop on drift. The start
   script internally uses Compose `--no-build --pull never` for the canonical
   six services; it can stop all six on a failed partial start. Require the
   original PostgreSQL container ID and
   resource gate to survive, then six exact services, `ops/nas/health.sh`,
   repository-derived migration head, and restoration of only previously
   running compatible dependents. `start.sh` does not apply
   `compose.public-browser.example.yml`, so the recreated `web` service is
   not on `browser-origin`. While `https://pa.bobby-fetting.me/` is routed
   `public-proxy` → `web:3000` on that network, apply the public overlay to
   `web` in the same recreation or the public route no longer reaches the new
   container. Do not change tunnel credentials, DNS, or the Caddy upstream as
   part of that attachment, and do not call the upgrade private-only.
8. **Post-start transport smoke and stop boundary.** Check the private web health
   response (`{ ok: true, status: "live" }` in production passkey mode), exact
   `node server.js` process, full source commit/tree, absent browser Entra/MSAL
   variables, and private proxy refusal of machine-internal `/v1/*`. The same
   JSON from `https://pa.bobby-fetting.me/api/health` proves only that the
   public web process answered through Caddy and Cloudflare. It does not prove
   `apps/cli/health.py` or the gateway healthcheck. Require the gateway probe
   to report the repository-derived Alembic head before calling the upgrade
   ready. This is transport/configuration evidence, not production WebAuthn
   sign-in. The
   canonical-origin procedure in
   [`auth-runtime-validation.md`](auth-runtime-validation.md) requires valid TLS,
   the exact RP ID, and separate activation authority. Do not change DNS,
   Cloudflare Tunnel routing, Funnel, port-forwarding, or public NAS/LAN origin
   ports during PREPARE; do not infer their existing state from this checklist.

## ACTIVATE — OPERATOR APPROVAL REQUIRED

Required before any command in this section: an explicit operator instruction
`PRODUCTION_ACTIVATION_APPROVED` for hostname `pa.bobby-fetting.me`.

This section describes a separately authorized future action, not the status
of the observed public-edge containers. Reauthenticate their current service,
DNS, tunnel, and traffic state before any change; a running edge is not proof
that public cutover was approved or completed.

After the post-start health and transport checks pass and the operator has
separately approved the specific public-edge change:

1. Render the frontend tunnel config with
   `ops/nas/render-frontend-cloudflared-config.py` to the owner-only path named
   by `MY_PA_FRONTEND_CLOUDFLARED_CONFIG`. Refuse overwrite.
2. Start or change `public-proxy` and `frontend-cloudflared` from
   `ops/nas/compose.public-browser.example.yml` only when their verified
   current state and specific operator authorization permit that action. Do not
   host-publish `0.0.0.0`, postgres, or gateway.
3. Example DNS cutover command (not evidence that it has or has not run):

   ```sh
   cloudflared tunnel route dns $TUNNEL_ID pa.bobby-fetting.me
   ```

4. Confirm the public proxy Host is exactly `pa.bobby-fetting.me`, HSTS is
   `max-age=31536000` without `includeSubDomains` or preload, and `/v1/*`,
   `/remote/*`, `/apple/*`, `/mcp`, and `/mcp/*` return 404.
5. Do not treat Cloudflare Access, Cloudflare identity headers, or
   `X-Forwarded-*` as Principal authority.
6. Auth-state is read-only. `inconsistent` hard-stops. `uninitialized` means
   bootstrap is pending and is never ready. Only `ready` supports ordinary
   commissioned operation. Do not treat a private-origin transport check as
   WebAuthn commissioning.

On canonical-origin auth failure: stop `frontend-cloudflared` and
`public-proxy`; retain PostgreSQL and Tailscale private management; restore
prior digest-pinned images and configuration only under operator instruction.
Do not continue public-edge traffic. Physical-device WebAuthn, bootstrap, and
recovery follow [`auth-runtime-validation.md`](auth-runtime-validation.md)
only with separate operator authority; verify their present state.

## ROLLBACK

Rollback uses a previous non-secret deployment manifest. It does not talk to
production from the repository script. Rehearse with
`ops/nas/rollback.sh --dry-run` and the exact verified prior manifest path;
the path is not established by the dated observation above.

The dry-run prints the exact `app_image_id`, `web_image_id`,
`proxy_image_digest`, and `cloudflared_image` that would be used, refuses a
`latest` tag, and refuses `docker build`. Live image load/start remains an
operator action against those exact IDs. Its static
`PRODUCTION_ACTIVATION_NOT_PERFORMED` output is a dry-run script marker, not
evidence of live DNS, tunnel, traffic, or activation state.

**Emergency public-edge stop** must identify the exact current Compose
project, files, and two edge services before acting. Stop only
`frontend-cloudflared` and `public-proxy`; do not stop PostgreSQL or the
private Tailscale management path. This runbook does not supply a command
that assumes the current Compose authority or public-edge state.

After the public edge is down, Tailscale private management and PostgreSQL
remain. Restore the previous digest-pinned images from the prior manifest only
under operator instruction. Never roll forward with `:latest`. Canonical-origin
auth failure uses this same public-edge stop; it does not stop PostgreSQL or
the private management path.
