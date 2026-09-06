# WP30 handoff from UI-IMP-WP27

Automation cannot close these evidence classes. WP27 records them; it does not perform them.

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
- Real Core Web Vitals on the production origin
- Canvas terminal reconciliation (`PFE-AC-226`)

## Runtime / delivery (WP29 then WP30)

- Production headers / origin (`pa.bobby-fetting.me`)
- Cloudflare Tunnel and NAS runtime identity
- Deployment and rollback rehearsal
- Connected-source truth still unknown (System must not invent it)

## Historical audits WP27 did not invent

- Final post-workstream WP-02 acceptance reconciliation
- Dedicated WP-08 PWA/offline audit
- Dedicated WP-14 Knowledge/Library/GoodNotes audit
- `PFE-AC-123..139` published-vs-later-audit mapping (`UNRECONCILED_ACCEPTANCE_MAPPING_123_139`)

## Acceptance

Do not mark the 250-criterion ledger `PASS_VERIFIED` from WP27. Do not treat `frontend / required` green as terminal frontend acceptance.
