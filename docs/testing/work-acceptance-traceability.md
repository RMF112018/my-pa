# Work acceptance traceability

This matrix maps the Tasks & Commitments criteria dated 2026-08-22 to repository evidence. It is an evidence index, not a conformance declaration. `PASS` is reserved for a criterion whose complete required evidence ran in this worktree. `PARTIAL` names evidence that passed while another required gate was unavailable. `ADDED/UNRUN` means executable evidence exists but its required runtime was unavailable; `STATIC` is bounded source review; `DEFERRED` means the product deliberately does not expose the capability yet.

## Contract acceptance

| Criterion | Status | Exact evidence |
|---|---|---|
| TC-AC-001 | PARTIAL | `web/src/components/work/workbench.test.tsx`; `tests/contract/test_http_transport.py`; lifecycle enum remains closed in `domain/task/lifecycle.py`. Component runtime was unavailable. |
| TC-AC-002 | PARTIAL | `web/src/components/work/workbench.test.tsx`; `web/src/components/work/work.stories.tsx`; task list DTO exposes due/scheduled/deferred separately. Frontend evidence was unrun. |
| TC-AC-003 | PARTIAL | `tests/contract/test_http_transport.py` and Task application-service tests passed; browser create was unrun. |
| TC-AC-004 | PARTIAL | HTTP contract tests passed; database atomic rollback and component compare/reapply evidence were not rerun. |
| TC-AC-005 | PARTIAL | Task transition/evidence unit/HTTP evidence passed; detail Storybook/browser evidence was unrun. |
| TC-AC-006 | PARTIAL | `tests/unit/test_commitment_integration.py` passed; browser cross-object assertion was unrun. |
| TC-AC-007 | PARTIAL | link/unlink HTTP/application evidence passed; database and browser gates were unrun. |
| TC-AC-008 | PARTIAL | bulk HTTP evidence passed; component/browser preview-confirm evidence was unrun. |
| TC-AC-009 | PARTIAL | backend contract evidence passed; obligation component/story evidence was unrun. |
| TC-AC-010 | PARTIAL | Commitment service/integration/HTTP evidence passed; database/browser gates were unrun. |
| TC-AC-011 | PARTIAL | HTTP search/history evidence passed; frontend editable-state evidence was unrun. |
| TC-AC-012 | PARTIAL | HTTP current-state conflict evidence passed; component and concurrent-browser evidence was unrun. |
| TC-AC-013 | PARTIAL | HTTP state evidence passed; Work component and outage E2E evidence was unrun. |
| TC-AC-014 | PARTIAL | evidence-body separation is static and HTTP evidence passed; security suite was not rerun. |
| TC-AC-015 | PARTIAL | HTTP same-principal evidence passed; architecture and BFF JavaScript gates were unrun. |
| TC-AC-016 | ADDED/UNRUN | `web/e2e/work-acceptance.spec.ts` keyboard perspective workflow; lifecycle movement uses a native labelled select, not drag. |
| TC-AC-017 | PARTIAL | Component URL/detail focus evidence passed; `web/e2e/work-acceptance.spec.ts` browser context evidence remains unrun. |
| TC-AC-018 | DEFERRED | No AI/context suggestion persistence control is exposed in Work. |
| TC-AC-019 | ADDED/UNRUN | explicit 390/768/1440 and 200%-equivalent reflow cases in `web/e2e/work-acceptance.spec.ts`; existing shell visual snapshots do not substitute for these unrun cases. |
| TC-AC-020 | ADDED/UNRUN | `web/e2e/pwa.spec.ts` asserts the service-worker cache allowlist excludes principal-bound responses; it was not rerun this cycle. |
| TC-AC-021 | STATIC + ADDED/UNRUN | Work remains under successor `AppShell`; shell keyboard/theme/reflow suites exist, and Work-specific Playwright coverage was added. |
| TC-AC-022 | STATIC + ADDED/UNRUN | Work composes existing Button/Input/Sheet/SurfaceState/Card/Badge primitives; `web/src/components/work/work.stories.tsx` adds feature Storybook/a11y states. |
| TC-AC-023 | STATIC | changed dependency/config paths are empty; no second shell, UI kit, token, overlay, theme, density, or responsive framework was introduced. |

## UX acceptance

| Criterion | Status | Exact evidence |
|---|---|---|
| TC-UX-001 | PARTIAL | Component perspective/context evidence passed; keyboard browser evidence remains unrun. |
| TC-UX-002 | PARTIAL | HTTP expected-version/conflict evidence passed; board component/browser evidence was unrun. |
| TC-UX-003 | PASS | Priority is separately labelled and its component test passed; Storybook compiled the canonical Task states. |
| TC-UX-004 | PASS | Distinct Deadline, Planned work, and Available after component evidence passed and stories compiled. |
| TC-UX-005 | PARTIAL | Backend evidence-reference contract passed; detail UI evidence was unrun. |
| TC-UX-006 | PARTIAL | Cross-object integration evidence passed; browser assertion was unrun. |
| TC-UX-007 | PASS | Human obligation sentences passed component tests for both directions and their stories compiled. |
| TC-UX-008 | STATIC + ADDED/UNRUN | No drag path exists and native select is the only move control; keyboard browser evidence was unrun. |
| TC-UX-009 | PARTIAL | HTTP state distinctions passed; component/browser state matrix was unrun. |
| TC-UX-010 | PARTIAL | Drawer close, URL cleanup, and trigger-focus restoration passed in the component suite; real-stack browser evidence remains unrun. |
| TC-UX-011 | PARTIAL | Atomic versioned backend patch evidence passed; component evidence was unrun. |
| TC-UX-012 | PARTIAL | Bulk server receipt evidence passed; component/browser controls were unrun. |
| TC-UX-013 | PARTIAL | HTTP link roundtrip evidence passed; database/browser gates were unrun. |
| TC-UX-014 | DEFERRED | Work exposes no AI/context suggestion control. |
| TC-UX-015 | ADDED/UNRUN | Storybook a11y error gate and existing axe Work scan; keyboard Work Playwright added. Automated checks are explicitly not full WCAG conformance. |
| TC-UX-016 | STATIC + ADDED/UNRUN | Work route is a successor-shell child and uses its nav/command/Inspector/theme model; responsive keyboard suite added. |
| TC-UX-017 | STATIC | imports show reuse of existing shared controls and semantic styles; only domain-specific Work composition is local. |
| TC-UX-018 | STATIC + ADDED/UNRUN | no new dependency/config/framework; Work stories provide light/dark/compact/mobile regression inputs. |

## Validation receipt

- `python3 -m pytest -q tests/unit/test_command_input_types.py tests/unit/test_task_management_service.py tests/unit/test_commitment_management_service.py tests/unit/test_commitment_integration.py tests/contract/test_http_transport.py` — **296 passed**, two dependency deprecation warnings, 37.66 seconds.
- Ruff over the changed backend/test paths — **passed**.
- Vitest — **37 files / 422 tests passed** under the exact-lock runtime.
- Targeted ESLint — **passed**.
- Storybook build — **passed**.
- TypeScript typecheck (`npm run typecheck`) — **passed** after aliasing Storybook contract types.
- Playwright — **not run**; the real-stack/disposable-database browser harness was unavailable in this cycle.
- Disposable PostgreSQL database tier — **not run**; no available disposable server was assumed.
- Visual snapshots — **not generated** because deterministic Playwright execution was unavailable; no baseline was fabricated.
