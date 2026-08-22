# Work acceptance traceability

This matrix maps the Tasks & Commitments criteria dated 2026-08-22 to repository evidence. It is an evidence index, not a conformance declaration. `PASS` is reserved for a criterion whose complete required evidence ran in this worktree. `PARTIAL` names evidence that passed while another required gate was unavailable. `ADDED/UNRUN` means executable evidence exists but its required runtime was unavailable; `STATIC` is bounded source review; `DEFERRED` means the product deliberately does not expose the capability yet.

## Contract acceptance

| Criterion | Status | Exact evidence |
|---|---|---|
| TC-AC-001 | PARTIAL | The full component suite, Storybook build, HTTP contract evidence, and exact-source Work browser/visual gates passed; the lifecycle enum remains closed in `domain/task/lifecycle.py`. The browser slice did not execute every lifecycle transition. |
| TC-AC-002 | PARTIAL | The component suite passed distinct due/scheduled/deferred labels and Storybook compiled their canonical states; the task DTO exposes the fields separately. Database/browser mutation evidence remains unrun. |
| TC-AC-003 | PASS | HTTP/application evidence passed, and the exact-source real-stack browser created a provenance-bound synthetic Task in a freshly migrated disposable database, read its canonical ID/version through the BFF, and reopened canonical detail. |
| TC-AC-004 | PARTIAL | HTTP conflict evidence and exact-source real-stack safe multi-field edit plus concurrent-client compare/reapply passed. The database atomic-rollback test was not rerun in this closeout. |
| TC-AC-005 | PASS | Task transition/evidence unit and HTTP evidence passed; the real-stack browser persisted an explicit closure note, received a server closure reference, linked the closure receipt in history, and revealed only after a second explicit user action through `/api/reveal`. |
| TC-AC-006 | PASS | `tests/unit/test_commitment_integration.py` passed, and the real-stack browser proved that completing the linked Task leaves the Commitment open. |
| TC-AC-007 | PASS | Link/unlink HTTP/application evidence passed; the real-stack browser linked, unlinked, and relinked the Task through the BFF against PostgreSQL, asserted the canonical relationship after each mutation, and changed no Commitment lifecycle state. |
| TC-AC-008 | PARTIAL | Bulk HTTP evidence and component preview/conflict/confirm/replay evidence passed; database/browser evidence remains unrun. |
| TC-AC-009 | PARTIAL | Backend contract evidence passed and both obligation directions compiled in Storybook; an asserted screen-reader-text browser case remains unrun. |
| TC-AC-010 | PASS | Commitment service/integration/HTTP evidence passed; the real-stack browser created, read and explicitly closed a versioned Commitment with durable origin and closure evidence against the disposable PostgreSQL tier. |
| TC-AC-011 | PARTIAL | HTTP search/history evidence, real-stack detail/read/close evidence, and explicit browser refusal of unsupported Waiting On search passed. A real-stack editable-field update case was not run. |
| TC-AC-012 | PASS | HTTP current-state conflict and frontend classification evidence passed; the real-stack browser forced a concurrent canonical update, showed current-versus-proposed fields, and required deliberate reapply before the proposed title persisted. |
| TC-AC-013 | PARTIAL | Gateway/HTTP state evidence (255 tests), the full frontend component suite, and exact-browser dead-gateway failure-state assertions across desktop/tablet/mobile passed. The browser suite did not inject every backend failure class. |
| TC-AC-014 | PASS | Gateway/HTTP and security evidence passed. In the real stack, opening `Why am I seeing this?` issued zero `/api/reveal` requests; only pressing `Reveal` issued the governed request, and the Work DTO never exposed a raw evidence body. |
| TC-AC-015 | PARTIAL | Gateway/HTTP, transport-parity (177 tests), security (85 tests), and JavaScript BFF/component evidence passed. The real-stack BFF rejected a caller-supplied `principalId`, and foreign opaque Task and Commitment identifiers returned nondisclosing 404s. A true two-identity browser case is not constructible in the pinned `local_operator` tier. |
| TC-AC-016 | PARTIAL | The exact-source browser keyboard perspective workflow passed across desktop/tablet/mobile; lifecycle movement uses a native labelled select, not drag, and a real-stack lifecycle transition passed on desktop. The new transition path used Playwright selection rather than a dedicated keyboard-only interaction. |
| TC-AC-017 | PASS | Component URL/detail focus evidence and the exact-source browser context, selection, drawer-close, URL preservation, and trigger-focus restoration workflow passed across desktop/tablet/mobile. |
| TC-AC-018 | DEFERRED | No AI/context suggestion persistence control is exposed in Work. |
| TC-AC-019 | PASS | Explicit 390/768/1440 and 200%-equivalent Work reflow cases passed across all configured projects; the reviewed deterministic 200% snapshots also passed without horizontal overflow. |
| TC-AC-020 | PASS | The service-worker registration/activation and principal-bound cache-exclusion assertions passed across desktop/tablet/mobile. |
| TC-AC-021 | PASS | Work remains under successor `AppShell`; full component, lint, typecheck, Storybook and Next build gates passed, followed by exact-browser keyboard, focus, theme, and responsive coverage across all projects. |
| TC-AC-022 | PASS | Work composes existing Button/Input/Sheet/SurfaceState/Card/Badge primitives; Storybook compiled, and exact-browser visual and automated accessibility regression gates passed across all projects. |
| TC-AC-023 | STATIC | Changed dependency/config paths are empty and no second shell, UI kit, token, overlay, theme, density, or responsive framework was introduced. The affected architecture count and secret-signature nodes passed after correction/artifact cleanup; the full architecture suite was not rerun afterward. |

## UX acceptance

| Criterion | Status | Exact evidence |
|---|---|---|
| TC-UX-001 | PASS | Component perspective/context evidence and the exact-browser keyboard List→Board→Calendar URL/filter-preservation workflow passed across desktop/tablet/mobile. |
| TC-UX-002 | PASS | HTTP expected-version/conflict, board component and frontend classification evidence passed; the real-stack browser forced a concurrent mutation and proved no silent overwrite before deliberate compare/reapply. |
| TC-UX-003 | PARTIAL | Priority is separately labelled and Storybook compiled the canonical Task states; no dedicated runtime assertion of priority-versus-focus semantics ran. |
| TC-UX-004 | PASS | Distinct Deadline, Planned work, and Available after component evidence passed and stories compiled. |
| TC-UX-005 | PASS | Backend evidence-reference contracts and detail stories passed; real-stack Task and Commitment terminal states exposed server-issued closure metadata, with Task closure linked to its history receipt and explicit governed reveal. |
| TC-UX-006 | PASS | Cross-object integration evidence passed, and the real-stack browser proved Task completion leaves the linked Commitment open without a fulfillment claim. |
| TC-UX-007 | PARTIAL | Human obligation sentences for both directions compiled in Storybook; no dedicated runtime assertion for both directions ran. |
| TC-UX-008 | PARTIAL | No drag path exists, a native labelled select is the only lifecycle move control, keyboard perspective navigation passed across all configured projects, and the real-stack lifecycle transition passed on desktop. The transition assertion did not drive the select exclusively by keyboard. |
| TC-UX-009 | PARTIAL | HTTP state distinctions passed; component/browser state matrix was unrun. |
| TC-UX-010 | PASS | Drawer close, URL cleanup, selection preservation, and trigger-focus restoration passed in both the component suite and exact-source real-stack browser runs across all projects. |
| TC-UX-011 | PASS | Atomic versioned backend evidence passed; the real-stack browser saved description and priority as one patch and read the canonical persisted result before continuing. |
| TC-UX-012 | PARTIAL | Bulk server receipt and component preview/conflict/confirm/replay evidence passed; browser controls remain unrun. |
| TC-UX-013 | PASS | HTTP roundtrip evidence passed; the real-stack browser proved link, unlink, and relink persistence through the BFF against the disposable PostgreSQL tier. |
| TC-UX-014 | DEFERRED | Work exposes no AI/context suggestion control. |
| TC-UX-015 | PARTIAL | Storybook compiled, and Work axe, landmark/heading, announcement, keyboard/focus, reduced-motion, and responsive browser checks passed across configured projects. Automated evidence is explicitly not a complete manual WCAG conformance assessment. |
| TC-UX-016 | PASS | Work is a successor-shell child; full component, lint, typecheck, Storybook and Next build gates passed, plus responsive keyboard/focus/theme browser coverage across desktop/tablet/mobile. |
| TC-UX-017 | STATIC | imports show reuse of existing shared controls and semantic styles; only domain-specific Work composition is local. |
| TC-UX-018 | PASS | No new dependency/config/framework was introduced; Work stories compiled, and reviewed light/dark/Inspector/command/200%-reflow snapshots plus automated accessibility checks passed across desktop/tablet/mobile. |

## Validation receipt

- Markdown and YAML governance guards — **passed**.
- Ruff lint and format checks — **passed**.
- Mypy — **passed**, with no issues in 366 source files.
- `python3 -m pytest -q tests/unit/test_command_input_types.py tests/unit/test_task_management_service.py tests/unit/test_commitment_management_service.py tests/unit/test_commitment_integration.py tests/contract/test_http_transport.py` — **296 passed**, two dependency deprecation warnings, 37.66 seconds.
- Architecture suite — initial full run **3,989 passed / 2 failed**. After correction and generated-artifact cleanup, both affected count/secret-signature nodes passed; the full architecture suite was not rerun.
- Official non-database FAST suite — initial full run **9,247 passed / 8 failed / 1,001 skipped**. Six source failures were corrected and the affected full files/nodes passed. Two optional Trio nodes remain unavailable in this environment; their asyncio counterparts passed. The complete FAST suite was not rerun after correction.
- Gateway and HTTP suite — **255 passed**.
- Transport-parity suite — **177 passed**.
- Affected security file — **85 passed**.
- Vitest — **37 files / 422 tests passed** under the exact-lock runtime.
- Full frontend ESLint (`npm run lint`) — **passed**.
- Storybook build — **passed**.
- TypeScript typecheck (`npm run typecheck`) — **passed** after aliasing Storybook contract types.
- Next production build (`npm run build`) — **passed**; 24 static pages were generated and all application/BFF routes compiled.
- Exact-source Playwright selection (`work-acceptance.spec.ts`, `accessibility.spec.ts`, `visual.spec.ts`, `journeys.spec.ts`, `failure-states.spec.ts`, `pwa.spec.ts`) — **157 passed / 2 expected project-specific target-size skips / 0 failed**, 2.3 minutes, across desktop/tablet/mobile.
- Exact-source real-stack Work mutation/security selection (`work-mutations.spec.ts`, desktop) — **3 passed / 0 failed**, 12.0 seconds: Task and Commitment create/read/close, safe edit, concurrent conflict/reapply, link/unlink/relink, terminal evidence and receipt linkage, explicit reveal, cross-object independence, caller-Principal refusal, nondisclosing foreign IDs, and explicit unsupported/unavailable state.
- Focused post-correction Work detail validation — **2 files / 6 tests passed**; focused ESLint and full TypeScript typecheck passed. The real-stack run exposed and corrected success-status ordering races in Task save and Commitment close so canonical reload completes before the UI invites the next action.
- Exact-source runtime attestation — the gateway Python resolved `my_pa` from this worktree and exposed the expected `TaskWorkView` vocabulary; the pre-existing unknown gateway on port 9099 was excluded, and the harness used the explicitly owned loopback port 9101.
- Mutation-harness runtime attestation — migration, governed synthetic relationship seeding and gateway startup were forced to this worktree with `PYTHONPATH=<worktree>/src`; the bounded final run used owned loopback port 9104. The synthetic counterparty was admitted through current, accepted, non-superseded Relationship Intelligence records rather than a raw canonical-person insert.
- Disposable PostgreSQL tier — the repository harness created only `my_pa_wp13_e2e` on loopback `127.0.0.1:5433`, migrated empty-to-head for each bounded run, and dropped it on teardown; final independent count was zero.
- Mutation disposable PostgreSQL tier — the final harness created only `my_pa_wpfe03_detail_acceptance_final`, migrated empty-to-head, and dropped it via the teardown trap; the independent post-run PostgreSQL catalog count was **zero**.
- Visual snapshots — the independent visual review passed the exact-source desktop/tablet/mobile 200%-reflow states. The dynamic freshness value remains truthful semantic `<time>` content at runtime and is hidden only for the screenshot assertion; tabular numerals preserve deterministic layout. Baselines were regenerated under the exact-source disposable stack and immediately passed **3/3** without update.
- Repository diff check (`git diff --check`) — **passed**.
