# ADR-012: Public browser ingress via dedicated Cloudflare Tunnel

**Status:** Accepted
**Decision date:** 2026-09-07
**Repository basis:** `main@f2d72f509d9aa434cb334dd42092b9c8a140da3c`, tree `8b8b9a39ec67e538b2d3c4b104cfa3a19fa34a59`
**Owning package:** UI-IMP-WP29

## Context

[ADR-008](ADR-008-nas-runtime-topology.md) selected tailnet-only Tailscale Serve for browser HTTPS and explicitly rejected Cloudflare, Funnel, public Internet exposure, and production LAN HTTP for that private ingress path. That private-management plane remains valid.

The operator has now selected a **public** production browser origin distinct from Tailscale management and distinct from the remote MCP Cloudflare Tunnel documented under `ops/nas/remote/`. Application authentication remains [ADR-011](ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md) WebAuthn/passkey with an opaque server session. Cloudflare is transport, not Principal authority. Cloudflare Access is not selected.

This ADR supersedes **only** ADR-008's prohibition on Cloudflare as the production **public browser** ingress. It does not reopen NAS hosting, PostgreSQL privacy, gateway privacy, filesystem authority, Apple/TCC split, or Tailscale as the private management plane.

## Decision

1. Production browser/PWA hostname is **`pa.bobby-fetting.me`**. Canonical origin is **`https://pa.bobby-fetting.me`**. WebAuthn RP ID is **`pa.bobby-fetting.me`**. Allowed origin is exactly **`https://pa.bobby-fetting.me`**. No wildcard RP ID, no sibling-domain RP ID, no temporary public hostname.

2. Public browser ingress is a **dedicated Cloudflare Tunnel**, separate from the remote MCP tunnel: separate tunnel identity, hostname, credentials, origin, and ingress policy. Frontend traffic is never merged into the MCP tunnel. `/mcp` is not served on the frontend hostname.

3. Path: Cloudflare HTTPS edge → frontend tunnel → NAS-local **public browser reverse proxy** → Next.js web/BFF → private gateway → NAS-local PostgreSQL. The tunnel originates outbound. No public NAS/LAN/WAN origin port. No router port-forward. Gateway and PostgreSQL remain unpublished.

4. Tailscale Serve remains the private management/maintenance browser and machine-ingress plane. Adding public Cloudflare ingress does not remove Tailscale.

5. The public proxy accepts Host `pa.bobby-fetting.me` only. Unknown Host fails closed. It refuses `/v1/*`, `/remote/*`, `/apple/*`, `/mcp`, and `/mcp/*`. Remaining browser/PWA/BFF routes may reverse-proxy to `web:3000`. Machine routes stay on the private Tailscale proxy only.

6. Cloudflare identity headers, Access JWT/email, Tailscale identity headers, `X-Forwarded-*`, and `Authorization` are not Principal authority. The public proxy strips them. Application auth remains passkey → opaque SID → server-derived Principal.

7. Cloudflare Access is **not** a mandatory login layer. Optional edge WAF/bot controls are not implied. HSTS is owned by the public reverse proxy (`max-age=31536000`, no `includeSubDomains`, no preload). Next.js retains CSP, X-Frame-Options, nosniff, Referrer-Policy, and Permissions-Policy.

8. Production web `MYPA_AUTH_MODE` is **`passkey`**. Synthetic is impossible in production. Browser `local_operator` is not a web mode. Internal gateway `MY_PA_AUTH_MODE=local_operator` may remain for BFF→gateway transport.

9. Production leaves `MYPA_SESSION_SERVICE_URL` unset; session-service is the same Python gateway process at `MYPA_GATEWAY_URL`. The WP28 CI override remains valid for dead-gateway tests.

10. Live DNS, live tunnel routing, and public cutover require a separate operator instruction `PRODUCTION_ACTIVATION_APPROVED`. Repository implementation of config, CI, and non-public smoke does not activate production.

## Consequences

- ADR-008 historical text is retained. Its Tailscale-only public-browser prohibition is superseded here for production public ingress only.
- A second cloudflared contract exists beside `ops/nas/remote/`. Credentials are owner-only and never committed.
- `frontend / delivery-config` validates this contract with synthetic secrets. It never deploys.
- WP30 owns real-device, platform WebAuthn, live public smoke, and `PASS_VERIFIED`.

## Supersession

Supersedes ADR-008 solely on: Cloudflare as production public **browser** ingress; production public hostname/origin/RP ID as named above.

Does **not** supersede: NAS as canonical runtime host; unpublished PostgreSQL; unpublished generic gateway; private Tailscale management ingress; MCP-as-separate-plane; ADR-011 authentication; ADR-009 remote MCP OAuth.

## Implementation status

Owned by UI-IMP-WP29. Live public activation is not claimed by accepting this ADR.
