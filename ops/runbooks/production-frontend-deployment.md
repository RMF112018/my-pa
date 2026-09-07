# Production frontend deployment — `pa.bobby-fetting.me`

Repository contract for deploying the public browser origin
`https://pa.bobby-fetting.me`. This runbook does not activate production.

**PRODUCTION_ACTIVATION_NOT_PERFORMED.** DNS, Cloudflare Tunnel routing, and
public cutover require a separate operator instruction `PRODUCTION_ACTIVATION_APPROVED`.
Commands under **ACTIVATE** are placeholders and have not been run.

Hostname throughout: `pa.bobby-fetting.me`. Canonical origin:
`https://pa.bobby-fetting.me`. WebAuthn RP ID: `pa.bobby-fetting.me`.

## PREPARE / SAFE

Execute in this order on the NAS from a clean checkout of the exact reviewed
commit. Stop before DNS. Do not run Cloudflare routing. Do not publish
PostgreSQL or the gateway.

1. **Identity.** Confirm repository commit and tree, NAS Docker engine
   `linux/amd64`, and that this is the dedicated frontend tunnel — not the
   remote MCP tunnel under `ops/nas/remote/`.
2. **Build.** Export linux/amd64 app/web archives with
   `ops/nas/build-candidates.sh`. Do not `docker build` during start. Do not
   use a `latest` tag.
3. **Digest.** Record exact loaded image/config IDs (`MY_PA_APP_IMAGE_ID`,
   `MY_PA_WEB_IMAGE_ID`, `MY_PA_POSTGRES_IMAGE_ID`), `MY_PA_PROXY_IMAGE_DIGEST`,
   and the digest-pinned `MY_PA_FRONTEND_CLOUDFLARED_IMAGE`. Write a
   non-secret `ops/nas/deployment-manifest.example.toml` replacement outside
   Git (`repository_commit`, `repository_tree`, image IDs, `alembic_head`,
   compose/public-proxy/tunnel hashes, `environment_schema_version`).
4. **Backup.** Take a custom-format PostgreSQL backup with
   `ops/nas/backup.sh` to an owner-only directory outside the repository.
   Keep the `.sha256` receipt on the manifest as `backup_receipt`.
5. **Env validate.** Copy `ops/nas/production-environment.example.env` outside
   Git, replace every placeholder, and fail-closed validate:

   ```sh
   python ops/nas/validate-production-env.py \
     --env /volume1/my-pa/secrets/production.env \
     --schema ops/nas/production-environment.schema.toml \
     --compose ops/nas/compose.example.yml
   python ops/nas/validate-delivery-config.py
   ```

   Production web `MYPA_AUTH_MODE` is `passkey`.
   `MYPA_CANONICAL_ORIGIN` is exactly `https://pa.bobby-fetting.me`.
   `MYPA_SESSION_SERVICE_URL` is absent or empty. Session secrets are ≥32
   characters. Synthetic auth, `local_operator` as `MYPA_AUTH_MODE`, and
   Entra/MSAL browser variables are refused.
6. **Migrate.** Run `ops/nas/migrate.sh` only after a current backup receipt.
   Migration is never an application startup side effect.
7. **Start private services.** Start PostgreSQL, gateway, workers, and the
   private Tailscale proxy with `ops/nas/start.sh` using `--no-build --pull never`.
   Do not start `frontend-cloudflared` or `public-proxy` yet if public routing
   is not approved.
8. **Health.** `ops/nas/health.sh` for process/database readiness, then
   unauthenticated `GET /api/health` on the private web origin. Expect
   `{ ok: true, status: "live" }` when `NODE_ENV=production` and
   `MYPA_AUTH_MODE=passkey`.
9. **Web.** Confirm the private web container is `node server.js`,
   `MYPA_SOURCE_COMMIT` / `MYPA_SOURCE_TREE` are full hex, and browser Entra/MSAL
   variables are absent.
10. **Private proxy.** Confirm the Tailscale allowlist proxy still refuses
    `/v1/*` as machine-internal and does not become the public origin.
11. **Non-public smoke.** Exercise sign-in, `/api/health`, and reserved-path
    refusals on the private origin only. Do not send traffic to
    `pa.bobby-fetting.me`.
12. **STOP before DNS.** Do not create or change a Cloudflare DNS record. Do
    not run `cloudflared tunnel route dns`. Do not enable Funnel, port-forward,
    or a public NAS/LAN origin port. Leave this runbook here unless the operator
    has issued `PRODUCTION_ACTIVATION_APPROVED`.

## ACTIVATE — OPERATOR APPROVAL REQUIRED

Required before any command in this section: an explicit operator instruction
`PRODUCTION_ACTIVATION_APPROVED` for hostname `pa.bobby-fetting.me`.

**These commands are placeholders. They have not been run.
PRODUCTION_ACTIVATION_NOT_PERFORMED.**

After private smoke is green and the operator has approved:

1. Render the frontend tunnel config with
   `ops/nas/render-frontend-cloudflared-config.py` to the owner-only path named
   by `MY_PA_FRONTEND_CLOUDFLARED_CONFIG`. Refuse overwrite.
2. Start `public-proxy` and `frontend-cloudflared` from
   `ops/nas/compose.public-browser.example.yml` without host-publishing
   `0.0.0.0` and without publishing postgres/gateway.
3. Placeholder DNS (not executed):

   ```sh
   cloudflared tunnel route dns $TUNNEL_ID pa.bobby-fetting.me
   ```

4. Confirm the public proxy Host is exactly `pa.bobby-fetting.me`, HSTS is
   `max-age=31536000` without `includeSubDomains` or preload, and `/v1/*`,
   `/remote/*`, `/apple/*`, `/mcp`, and `/mcp/*` return 404.
5. Do not treat Cloudflare Access, Cloudflare identity headers, or
   `X-Forwarded-*` as Principal authority.

## ROLLBACK

Rollback uses a previous non-secret deployment manifest. It does not talk to
production from the repository script. Rehearse first:

```sh
ops/nas/rollback.sh --dry-run /volume1/my-pa/deployment/previous-manifest.toml
```

The dry-run prints the exact `app_image_id`, `web_image_id`,
`proxy_image_digest`, and `cloudflared_image` that would be used, refuses a
`latest` tag, and refuses `docker build`. Live image load/start remains an
operator action against those exact IDs.

**Emergency public-edge stop** (does not stop PostgreSQL):

```sh
# Placeholder service names from ops/nas/compose.public-browser.example.yml.
# Do not stop postgres. PRODUCTION_ACTIVATION_NOT_PERFORMED — not executed here.
docker compose \
  --file ops/nas/compose.example.yml \
  --file ops/nas/compose.public-browser.example.yml \
  --profile public-browser-edge \
  stop frontend-cloudflared public-proxy
```

After the public edge is down, Tailscale private management and PostgreSQL
remain. Restore the previous digest-pinned images from the prior manifest only
under operator instruction. Never roll forward with `:latest`.
