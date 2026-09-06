# WP28 handoff from UI-IMP-WP27

WP27 does **not** implement release-gate architecture. This file is the promotion and measurement handoff only.

## Required today (do not weaken)

`frontend / classify`, `static`, `unit`, `production-build`, `contract`, `security`, `e2e-critical`, `accessibility`, `responsive`, and the aggregate `frontend / required`.

WP27 added `canvas.spec.ts` and `system.spec.ts` to **e2e-critical**. That is missing-protection wiring, not a new job.

`web/e2e/failure-states.spec.ts` (dead-gateway second Next server) is **not** in `e2e-critical`. Sign-in shares `MYPA_GATEWAY_URL` with session-service, so the dead server cannot complete synthetic sign-in in CI (90s `waitForURL /today`). WP28 may promote that suite only after session-service is independently reachable.

## Advisory — keep ADVISORY until WP28 decides

| Job | WP27 status | Promotion candidate? |
|---|---|---|
| `frontend / pwa-offline` | `continue-on-error: true` (WP26 INTRODUCED/ADVISORY) | Yes, after a green required-PR streak and no flake. Still not Safari/iOS/Android. |
| `frontend / browsers` | `continue-on-error: true` | Partial. Origin/CSRF + Search on Firefox/WebKit only. WebAuthn stays Chromium-CDP. Playwright WebKit is not Safari. |

## Do not create under WP27 (WP28 owns)

- `frontend / visual` required job
- `frontend / performance` required job
- `frontend / delivery-config`
- GitHub ruleset / required-check mutation
- nightly/release matrices
- final CWV or bundle budgets

## Visual

`web/e2e/visual.spec.ts` exists with Darwin snapshots only and is **not** in CI. WP28 must decide Linux baselines and auto-approval policy. Do not auto-approve baseline changes.

## Performance

No accepted numeric budgets. WP27 protects typed failures and production-build existence only. Representative Canvas scale fixtures are not a budget.

## Classifier

`tests/unit/test_frontend_ci_classify.py` pins the published `grep -Eq` pattern. WP28 may extend it, but must keep unrelated backend (including Canonical Constraint / `constraints.py`) off the heavy frontend path.

## Skips / retries (inventory)

- Playwright `retries: 0`. No pytest reruns.
- No `test.only` / `describe.only` / `test.fixme` / pytest `xfail`.
- Conditional skips that remain:
  - `web/e2e/webauthn.spec.ts` — Chromium-only virtual authenticator (not Firefox/WebKit; Playwright WebKit is not Safari).
  - `web/e2e/goodnotes.spec.ts` — mobile overflow measured on mobile/390 elsewhere.
  - `web/e2e/journeys.spec.ts` — tablet inspector orientation.
  - `web/e2e/system.spec.ts` — desktop-only (still runs in `e2e-critical` desktop).
  - `web/e2e/review-decisions.spec.ts` contextual Review handoff — skips when the empty e2e catalog has no pending/Evidence control (explicit reason; not a silent pass).
  - `web/e2e/search-contract.spec.ts` — two `page.route` intercept tests skip Playwright WebKit (not Safari); Chromium and Firefox still run them.
- Accessibility touch targets now run on the desktop CI project via an explicit 412×839 touch viewport.
- `continue-on-error` remains only on `pwa-offline` and `browsers`.

## Recommended WP28 first slice

1. Measure e2e-critical duration after WP27’s three added specs.
2. Keep advisory jobs advisory until flake rate is known.
3. Add visual/performance jobs as **advisory** first if introduced at all.
4. Bind required GitHub checks only after operator authorization (not this package).
