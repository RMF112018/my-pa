# Production frontend deployment — `pa.bobby-fetting.me`

Repository contract for deploying the public browser origin
`https://pa.bobby-fetting.me`. This runbook is neither deployment authorization
nor evidence of the current public activation state.

DNS, Cloudflare Tunnel routing, and public cutover require a separate operator
instruction `PRODUCTION_ACTIVATION_APPROVED` for this hostname. Do not infer
that approval, or its absence, from a running container or this document.

Hostname throughout: `pa.bobby-fetting.me`. Canonical origin:
`https://pa.bobby-fetting.me`. WebAuthn RP ID: `pa.bobby-fetting.me`.

**Dated observation, not an admission (2026-09-23 UTC).** A bounded read-only
`ssh bf-nas` observation with strict host-key checking reached
`TheLakeHouseNAS`. Docker reported a linux/x86_64 engine with ID
`dae23744-d1a7-4a18-85bb-8be28855fe4e`, project
`my-pa-nas-contract`, and eight running containers: the canonical six plus
`public-proxy` and `frontend-cloudflared`. The six canonical restart policies
were `no`, consistent with smoke Compose, but the selected/admitted lifecycle
mode was not authenticated. The clean root-owned mode-0700 checkout at
`/volume1/my-pa/runtime-f0f7869e-smoke-20260914T151915Z` had HEAD
`f0f7869e92e3acd3c3503658a121be8a4a28be0a` and tree
`45d0e89ab91c8610df2114835e875a7a55d5cbef`, matching running app source
labels. The observed proxy RepoDigest was
`caddy@sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a`;
it is not approval for a future candidate. `/volume1/my-pa/deployment` was
absent. Active image-manifest and admission paths, Compose authority, backup
and database revision, DNS/public reachability, and activation approval were
not established. Reauthenticate all of them at the next action boundary; do
not carry this snapshot forward as current state.

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
   exact-HEAD Git source bundle: fourteen inventoried members. Verify bundle
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
   A refusal stops before the other thirteen members transfer and leaves all
   runtime state selected as it was. A pass permits a fresh
   `origin/main` check, transfer of the remaining thirteen members, a *new*
   versioned root-owned mode-0700 NAS artifact directory with root-owned
   mode-0400 regular files, and SHA-256/size readback of all fourteen members.
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
   remain old. Load/admit all four runtime images against the live engine and
   issue the new deployable image manifest. Verify that the preserved old
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
   running compatible dependents. Do not alter existing `public-proxy` or
   `frontend-cloudflared` state as part of this smoke upgrade, but do not call
   the upgrade private-only for that reason.
8. **Post-start transport smoke and stop boundary.** Check the private web health
   response (`{ ok: true, status: "live" }` in production passkey mode), exact
   `node server.js` process, full source commit/tree, absent browser Entra/MSAL
   variables, and private proxy refusal of machine-internal `/v1/*`. This is
   transport/configuration evidence, not production WebAuthn sign-in. The
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
