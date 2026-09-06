# Frontend release gates (UI-IMP-WP28)

WP28 owns CI gate architecture, the Playwright browser matrix, visual policy, and performance *measurement*. It does not deploy, mutate GitHub rulesets, invent Core Web Vitals budgets, or declare terminal frontend acceptance.

Base: `origin/main` `8995cc4cad4f75f36433e30e937a54544e84e082` (WP27 #215).

## Required today (`frontend / required`)

Unchanged from WP27:

`classify`, `static`, `unit`, `production-build`, `contract`, `security`, `e2e-critical`, `accessibility`, `responsive`.

Do not remove child jobs. Do not add `continue-on-error` to them.

## Advisory — INTRODUCED / ADVISORY (`continue-on-error: true`)

| Job | Why advisory | Promotion condition |
|---|---|---|
| `frontend / pwa-offline` | WP26 introduction; Chromium only; not real-device PWA | Green required-PR streak and no flake. Still not Safari/iOS/Android. |
| `frontend / browsers` | Firefox/WebKit critical subset; WebAuthn stays Chromium-CDP; Playwright WebKit is not Safari | Partial promotion possible after flake evidence. Never treat WebKit as Safari. |
| `frontend / visual` | Darwin PNG baselines only; Linux CI will mismatch until linux snapshots are committed. No auto-update. | Commit linux desktop baselines; freeze auto-approval policy. |
| `frontend / performance` | Observational `.next/static` JS census. **No accepted numeric budget.** | Accept a budget from measured evidence; do not invent one here. |
| `frontend / degraded-gateway` | Dead-gateway `failure-states.spec.ts` after `MYPA_SESSION_SERVICE_URL` split. Sign-in topology newly enabled. | Promote into `e2e-critical` only after a green advisory streak. |

`frontend / required` does **not** depend on any row in that table.

## Browser matrix

| Engine | CI now | Claim |
|---|---|---|
| Chromium (Playwright) | Required via `e2e-critical`, a11y, responsive | CI_PARTIAL for Chromium desktop |
| Firefox (Playwright) | Advisory `frontend / browsers` | Origin/CSRF + Search subset |
| WebKit (Playwright) | Advisory `frontend / browsers` | Same subset. **Not Safari.** |
| Real Safari / iOS / Android | None | WP30 |

## Visual policy

- Do not `--update-snapshots` in CI.
- Do not auto-approve baseline changes.
- Darwin snapshots remain the reviewed desktop/tablet/mobile set on this tree.
- Linux baselines are a follow-on commit, not a silent pass.

## Performance policy

- Typed route failures and `production-build` remain the CI-provable reliability floor.
- Bundle census is observational JSON (`npm run report:bundle`).
- Real CWV on `pa.bobby-fetting.me` is WP30.

## Dependency security

`web-security` already runs on repository-checks. WP28 does not add a separate npm-audit release gate or Dependabot policy change.

## GitHub rulesets

WP28 does **not** mutate GitHub required checks or rulesets. Binding `frontend / required` (or any new job) as a repository required status check remains an operator action under `AGENTS.md` section 8.2.

## Out of scope

- WP29: Cloudflare, DNS, NAS, deployment, rollback, delivery-config
- WP30: real devices, platform WebAuthn, screen readers, production smoke, `PASS_VERIFIED` of PFE-AC-001..250
- Promoting `pwa-offline` / `browsers` / visual / performance / degraded-gateway into `frontend / required` on this PR
- Nightly/release matrices
