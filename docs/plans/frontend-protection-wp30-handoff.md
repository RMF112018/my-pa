# WP30 handoff from UI-IMP-WP29

WP29 records the production public-browser contract. It does not activate
production and does not mark the 250-criterion ledger `PASS_VERIFIED`.

## Public origin (repository contract; not live)

- Hostname: `pa.bobby-fetting.me`
- Canonical origin: `https://pa.bobby-fetting.me`
- WebAuthn RP ID: `pa.bobby-fetting.me`
- Allowed origin: exactly `https://pa.bobby-fetting.me`
- Expected HSTS (public reverse proxy): `Strict-Transport-Security: max-age=31536000` with no `includeSubDomains` and no preload
- Health: unauthenticated `GET /api/health` → `{ ok: true, status: "live" }` when production passkey config parses; otherwise 503 `misconfigured` with no env echo
- Reserved path refusals on the public origin: `/v1/*`, `/remote/*`, `/apple/*`, `/mcp`, `/mcp/*`
- `PRODUCTION_ACTIVATION_NOT_PERFORMED`. Cloudflare DNS/tunnel routing is not claimed.

## Devices and engines

- Real Safari (not Playwright WebKit)
- Real iOS Safari PWA install / update / offline
- Real Android Chrome PWA install / update
- Real platform WebAuthn authenticators (not Chromium virtual authenticator)

## Accessibility and reflow

- Screen-reader workflows (VoiceOver, TalkBack, NVDA as applicable)
- Manual keyboard review beyond the automated Cmd/K and named-dialog checks
- Real 200% / 400% browser zoom (current checks include viewport proxies only)

## Visual and performance

- Subjective visual quality against the product, not Darwin PNG equality
- Real Core Web Vitals on `https://pa.bobby-fetting.me`
- Canvas terminal reconciliation (`PFE-AC-226`)

## Runtime / delivery remainder

- Live public smoke on `pa.bobby-fetting.me` after operator `PRODUCTION_ACTIVATION_APPROVED`
- Connected-source truth still unknown (System must not invent it)
- `PASS_VERIFIED` of `PFE-AC-001..250`

## Historical audits WP27 did not invent

- Final post-workstream WP-02 acceptance reconciliation
- Dedicated WP-08 PWA/offline audit
- Dedicated WP-14 Knowledge/Library/GoodNotes audit
- `PFE-AC-123..139` published-vs-later-audit mapping (`UNRECONCILED_ACCEPTANCE_MAPPING_123_139`)

## Acceptance

Do not mark the 250-criterion ledger `PASS_VERIFIED` from WP29. Do not treat
`frontend / required` green as terminal frontend acceptance. Real Safari, iOS,
Android, platform WebAuthn, CWV, and `PASS_VERIFIED` remain WP30.
