# WP28 handoff from UI-IMP-WP27

WP27 did **not** implement release-gate architecture. Controlling WP28 gate membership is [`frontend-release-gates.md`](frontend-release-gates.md).

## Required today (do not weaken)

`frontend / classify`, `static`, `unit`, `production-build`, `contract`, `security`, `e2e-critical`, `accessibility`, `responsive`, and the aggregate `frontend / required`.

`web/e2e/failure-states.spec.ts` remains **out** of `e2e-critical`. WP28 runs it as advisory `frontend / degraded-gateway` after `MYPA_SESSION_SERVICE_URL` points at the live gateway and `web/e2e/stack.sh` allowlists `http://localhost:3101` for session-service origin checks.

## Advisory (WP28)

`pwa-offline`, `browsers`, `visual`, `performance`, `degraded-gateway` — all `continue-on-error: true`. None are in `frontend / required`.

## Still not this package

- GitHub ruleset / required-check mutation
- Nightly/release matrices
- Final CWV or bundle budgets
- WP29 delivery-config / deployment
- Linux visual baselines (Darwin snapshots only until a later commit)
