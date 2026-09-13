# Task UX Acceptance Ledger — `TASK-AC-001..050`

**Owning work package:** WP-TUX-08 (acceptance traceability).
**Repository basis:** `95e6dd5397c87b96e1962248d5d01334076c3c3e`, plus the WP-TUX-08 traceability
commit that introduced this file. Every `file:line` below was read back at that head.
**Rule:** unknown is not pass. Absence of contrary evidence is not evidence.

## Why this file exists

Before WP-TUX-08 the string `TASK-AC-0NN` appeared **18 times in 4 files** across the whole
repository, and only 7 of the 50 criteria (017, 018, 019, 042, 043, 045, 047) appeared anywhere at
all. The coverage overwhelmingly existed; it was simply not attributable. WP-TUX-08 did not author
new behavioural tests. It attached criterion identifiers to the tests that already prove the
behaviour, and it wrote this ledger so that each criterion resolves to an exact, greppable
`file:line`.

## Binding rule

A row may claim **PASS** only when it cites a `file:line` that exists at this head, or a CI run ID
executed on this head. No inference, no "it must be covered somewhere". Anything else is
**PENDING**. An operator-gated criterion can never be PASS in an agent session.

## Controlled vocabulary

| Status | Meaning |
|---|---|
| `PASS` | Exact evidence exists at this head and runs in a **blocking** CI lane (see *CI lane authority*). |
| `PENDING-RUN` | Exact evidence exists at this head, but it does not execute in a blocking lane, or it is not yet proven executed on this head by run ID. |
| `PENDING-RUNTIME` | Operator-gated. Requires a physical device, a deployed identity, or an authenticated external service. Cannot close in an agent session. |
| `GAP` | No evidence located at this head. Stated plainly rather than filled with a plausible citation. |

## CI lane authority

`.github/workflows/frontend-quality.yml:601` (`frontend / required`) gates on exactly these jobs:
`static`, `unit`, `production-build`, `contract`, `security`, `e2e-critical`, `accessibility`,
`responsive`, `delivery-config`. Those are the **blocking** lanes.

`pwa-offline` (`:312`), `browsers` (`:363`), `visual` (`:461`), `performance` (`:514`) and
`degraded-gateway` (`:538`) are each `continue-on-error: true` — **advisory**. An advisory green is
not acceptance (package finding TUX08-F007).

| Lane | Blocking? | Covers |
|---|---|---|
| `unit` (`:64`, `npm test` → vitest) | yes | every `web/src/**/*.test.ts(x)` row below |
| `e2e-critical` (`:157`, step `:206`, `--project=desktop`) | yes | `work-mutations.spec.ts`, `search-contract.spec.ts` |
| `accessibility` (`:209`, step `:256`, `--project=desktop`) | yes | `accessibility.spec.ts` |
| `responsive` (`:259`, step `:306`, desktop + tablet + mobile) | yes | `work-acceptance.spec.ts`, `today-tasks.spec.ts` |
| `pwa-offline` (`:308`, step `:357`) | **no — advisory** | `pwa.spec.ts`, `offline.spec.ts` |
| `browsers` (`:359`, steps `:410`, `:455`) | **no — advisory** | Firefox/WebKit re-runs only |
| `repository-checks.yml` `validate` (`:18`, FAST tier at `:109`) | yes | `tests/unit/**` |
| `repository-checks.yml` `database-current-head` (`:410`, selector at `:488`) | yes | `tests/database/**` |

## Ledger

| AC | Requirement | Owning WP | Evidence type | Evidence (`file:line`) | Status | Note |
|---|---|---|---|---|---|---|
| 001 | Create is a minimal form | WP-TUX-02 | unit (component) | `web/src/components/tasks/task-create-sheet.test.tsx:89` | PASS | Exactly Title, Description, Priority, Due. |
| 002 | Priority in human words, never `p1..p4` | WP-TUX-02 | unit | `web/src/lib/tasks/presentation.test.ts:84`, `:96`; `web/src/components/tasks/task-create-sheet.test.tsx:118`; `web/src/components/tasks/task-status-control.test.tsx:22` | PASS | `:96` also refuses to render an absent priority as Low. |
| 003 | No Origin note on an ordinary create | WP-TUX-02 | unit + source | `web/src/components/tasks/task-create-sheet.test.tsx:352`; `tests/unit/test_task_management_service.py:904` | PASS | Client sends none; service accepts a direct-principal create without evidence. |
| 004 | No Commitment/Role in the default create | WP-TUX-02 | unit | `web/src/components/tasks/task-create-sheet.test.tsx:89`, `:352` | PASS | |
| 005 | Work and Capture share one canonical create form | WP-TUX-02 | unit | `web/src/components/tasks/task-create-sheet.test.tsx:264`, `:338` | PASS | Both entries post `/api/tasks`, never `/api/capture`. |
| 006 | One intent yields exactly one Task | WP-TUX-03 | unit + DB | `web/src/lib/task/create-intent.test.ts:41`; `web/src/components/tasks/task-create-sheet.test.tsx:222`; `web/src/components/work/task-runtime-provider.test.tsx:245`; `tests/database/test_task_management_service.py:157` | PASS | Proven at intent, form, provider and database. Browser-layer proof is landing separately in `web/e2e/work-mutations.spec.ts` under a sibling WP-TUX-08 worker; it is **not** claimed by this row at this head. |
| 007 | An ambiguous retry reuses the idempotency key | WP-TUX-03 | unit | `web/src/lib/task/create-intent.test.ts:59`, `:80`; `web/src/lib/task/mutation-coordinator.test.ts:278` | PASS | Same caveat as 006 on the browser layer. |
| 008 | Two deliberate sessions yield two Tasks | WP-TUX-03 | unit | `web/src/lib/task/create-intent.test.ts:160` | PASS | Same caveat as 006 on the browser layer. |
| 009 | Due is date-only by default | WP-TUX-04 | unit | `web/src/components/tasks/task-due-control.test.tsx:40`, `:69`, `:98`; `web/src/components/tasks/use-task-operations.test.tsx:385` | PASS | The control offers civil days; the hook serializes a civil date. |
| 010 | A date-only Due becomes local `23:59:59` | WP-TUX-04 | unit | `web/src/lib/tasks/presentation.test.ts:336`, `:426`; `web/src/components/tasks/task-create-sheet.test.tsx:237` | PASS | `:426` reads the wall clock back independently of the helper under test. |
| 011 | An explicitly authored time is preserved | WP-TUX-04 | — | none | **GAP** | No evidence at this head, and none expected: `web/src/lib/tasks/presentation.ts:194` states the caller opts into an explicit time "only once that semantic exists upstream", and no surface authors one. `presentation.test.ts:197` proves only that display *omits* a time unless asked. See *Findings*, TUX08-L011. |
| 012 | DST and IANA zone boundaries hold | WP-TUX-04 | unit | `web/src/lib/tasks/presentation.test.ts:342` (spring forward), `:349` (fall back), `:356` (UTC-positive, incl. Sydney winter/summer), `:374` (UTC-negative), `:381` (leap day), `:388` (year boundary), `:426` (wall clock in every zone) | PASS | This is the entire TASK-AC-012 boundary matrix. Do not duplicate it elsewhere. |
| 013 | A Due earlier today still reads Today | WP-TUX-04 | unit | `web/src/lib/tasks/presentation.test.ts:161`, `:189` | PASS | `:189` pins the late-evening UTC case to the caller's civil day. |
| 014 | A Due on a prior day reads Overdue | WP-TUX-04 | unit | `web/src/lib/tasks/presentation.test.ts:173` | PASS | Whole civil days, singular and plural. |
| 015 | Status is operated inline from list and detail | WP-TUX-05 | unit + E2E | `web/src/components/work/task-list-row.test.tsx:180`, `:270`; `web/src/components/tasks/task-status-control.test.tsx:22`; `web/e2e/work-acceptance.spec.ts:251` | PASS | E2E in the blocking `responsive` lane. |
| 016 | Due is operated inline from list and detail | WP-TUX-05 | unit + E2E | `web/src/components/tasks/task-due-control.test.tsx:40`; `web/src/components/work/task-list-row.test.tsx:192`; `web/e2e/work-acceptance.spec.ts:262` | PASS | E2E in the blocking `responsive` lane. |
| 017 | Board Status by keyboard and by tap | WP-TUX-05/06 | E2E + unit | `web/e2e/work-acceptance.spec.ts:422`, `:505`; `web/src/components/tasks/task-status-control.test.tsx:126`, `:140` | PASS | `:505` is one of two titles the advisory `browsers` job selects by `--grep`; it is load-bearing and must not be renamed. |
| 018 | Calendar Due is changed directly | WP-TUX-05 | E2E | `web/e2e/work-mutations.spec.ts:299` | PASS | Blocking `e2e-critical` lane. File owned by a sibling worker; cited, not edited, by WP-TUX-08. |
| 019 | A Search hit is read canonically before it is mutated | WP-TUX-05 | E2E | `web/e2e/search-contract.spec.ts:360` | PASS | **Qualified.** `test.skip` on WebKit at `web/e2e/search-contract.spec.ts:363` (reason at `:365`: "Playwright WebKit is not Safari"). The criterion is proven on blocking Chromium desktop only; the Firefox/WebKit re-run at `frontend-quality.yml:410` is advisory. Real-Safari behaviour is not covered here and is not claimed. |
| 020 | Comments are append-only | WP-TUX-01 | unit + schema | `web/src/components/tasks/task-comments.test.tsx:233`; `tests/schema/test_wp_tux_01_task_origin_closure_comments_migration.py:288`; `tests/unit/test_task_management_service.py:921` | PASS | Enforced in the schema, not only in the UI. |
| 021 | Author and timestamp are visible | WP-TUX-01 | unit | `web/src/components/tasks/task-comments.test.tsx:96` | PASS | Human author label plus an ISO `dateTime`, with no identifier leaked. |
| 022 | A comment retry is idempotent | WP-TUX-01 | unit + DB | `tests/unit/test_task_management_service.py:975`; `tests/database/test_task_management_service.py:717`, `:792`, `:864` | PASS | DB rows prove it under a real concurrent insert race. |
| 023 | No comment edit or delete | WP-TUX-01 | unit + schema | `web/src/components/tasks/task-comments.test.tsx:233`; `tests/schema/test_wp_tux_01_task_origin_closure_comments_migration.py:288` | PASS | |
| 024 | Close is Confirm, and no third interaction | WP-TUX-02 | unit + E2E | `web/src/components/tasks/task-close-control.test.tsx:36`, `:61`; `web/src/components/pulse/today-task-card.test.tsx:262`; `web/e2e/work-acceptance.spec.ts:203`; `web/e2e/today-tasks.spec.ts:302` | PASS | Blocking `responsive` lane. |
| 025 | Close needs no note and summons no keyboard | WP-TUX-02 | unit + E2E | `web/src/components/tasks/task-close-control.test.tsx:72`; `web/e2e/work-acceptance.spec.ts:203` | PASS | The confirmation contains no text entry at all. |
| 026 | Close → completed, Cancel → cancelled | WP-TUX-01/02 | unit | `tests/unit/test_task_domain.py:67`; `web/src/components/tasks/task-close-control.test.tsx:126`; `web/src/components/tasks/use-task-operations.test.tsx:433`, `:491` | PASS | Exactly two terminal states, each with its own copy and its own pessimistic path. |
| 027 | `closed_at` is recorded and history is immutable | WP-TUX-01 | schema + unit | `tests/schema/test_wp_tux_01_task_origin_closure_comments_migration.py:208`, `:288`; `tests/unit/test_task_domain.py:344`, `:348` | PASS | Blocking `database-current-head` / FAST tiers. |
| 028 | No fabricated closure evidence | WP-TUX-01 | unit | `tests/unit/test_task_management_service.py:614`, `:637`, `:661`; `web/src/components/tasks/use-task-operations.test.tsx:462`; `web/src/components/work/task-list-row.test.tsx:919` | PASS | Absent evidence is allowed, blank evidence is refused, and the UI never shows a closure on a response that carried no Task. |
| 029 | A declared mutation state machine | WP-TUX-03 | unit | `web/src/lib/task/mutation-state.test.ts:37`, `:41`, `:53`; `web/src/lib/task/mutation-coordinator.test.ts:21` | PASS | Draft said "`mutation-state.test.ts` (4)"; the file holds **3** tests. Corrected. |
| 030 | A confirmed success survives the source unmounting | WP-TUX-03 | unit | `web/src/lib/task/create-intent.test.ts:168`, `:184`, `:202`; `web/src/components/ui/mutation-feedback.test.tsx:54`; `web/src/components/work/task-runtime-provider.test.tsx:337` | PASS | |
| 031 | A definitive failure preserves the authored input | WP-TUX-03 | unit | `web/src/lib/task/create-intent.test.ts:112`, `:134` | PASS | A new intent is minted only after a material change. |
| 032 | An ambiguous transport failure preserves the key | WP-TUX-03 | unit | `web/src/lib/task/create-intent.test.ts:59`; `web/src/lib/task/mutation-coordinator.test.ts:278`; `web/src/components/tasks/use-task-operations.test.tsx:360` | PASS | Same browser-layer caveat as 006. |
| 033 | A 409 preserves the draft and never blind-retries | WP-TUX-03 | unit | `web/src/components/work/work-detail.task-runtime.test.tsx:131`, `:163`, `:210`, `:363`; `web/src/lib/task/mutation-coordinator.test.ts:243`; `web/src/components/work/task-list-row.test.tsx:459`, `:500` | PASS | Detail and List parity proven. Board and Calendar reach the same coordinator through `useTaskRowOperations`; parity there is inferred from the shared seam, not separately measured. |
| 034 | Disappearance is announced and focus is restored | WP-TUX-05/07 | unit + E2E | `web/src/components/tasks/use-task-row-operations.test.tsx:289`; `web/src/components/pulse/today-pulse-surface.test.tsx:299`; `web/src/components/work/task-list-row.test.tsx:826`; `web/e2e/today-tasks.spec.ts:610` (announced), `:679` (focus) | PASS | Blocking `responsive` lane. |
| 035 | The change is perceptible to a screen reader | WP-TUX-05 | unit + E2E | `web/src/components/ui/mutation-feedback.test.tsx:114`, `:173`, `:134`; `web/e2e/accessibility.spec.ts:533` | PASS | Automated half only. The VoiceOver leg is TASK-AC-046 and is not claimed here. |
| 036 | An external MCP write is visible within ~5s | WP-TUX-05 | hook (synthetic) | `web/src/lib/task/use-foreground-revalidation.test.ts:223` | **PENDING-RUNTIME** | Operator-gated. The 5s cadence is proven against fake timers; the criterion is about a *real* external MCP write reaching a *real* foreground surface. Requires an authenticated external MCP client and a deployed identity. Cannot close in an agent session. |
| 037 | focus, visibility and online each revalidate | WP-TUX-05 | unit | `web/src/lib/task/use-foreground-revalidation.test.ts:332`, `:347`, `:370`; `web/src/components/work/use-task-freshness.test.ts:101`, `:136`, `:159` | PASS | |
| 038 | A local success reconciles the open reads | WP-TUX-05 | unit | `web/src/components/work/task-runtime-provider.test.tsx:449`, `:467`, `:565`; `web/src/lib/task/read-coordinator.test.ts:91` | PASS | One revalidation per logical mutation, and an older in-flight read is barred. |
| 039 | Hidden or offline stops the polling | WP-TUX-05 | unit | `web/src/lib/task/use-foreground-revalidation.test.ts:274`, `:303`, `:393` | PASS | The offline/SW leg of this behaviour additionally appears in the advisory `pwa-offline` lane, which is not relied on here. |
| 040 | A background refresh preserves a dirty editor | WP-TUX-05 | unit | `web/src/components/work/work-detail.task-runtime.test.tsx:188`; `web/src/lib/task/read-coordinator.test.ts:91` | PASS | |
| 041 | A Principal-bound API response is never SW-cached | WP-TUX-05 | E2E (specialized) | `web/e2e/pwa.spec.ts:101` | **PENDING-RUN** | Evidence exists and is exact, but `pwa.spec.ts` runs **only** in `frontend-quality.yml:308` `pwa-offline`, which is `continue-on-error: true` at `:312`. Per package finding **TUX08-F007 an advisory green is not PASS.** This row closes when a specialized execution of that lane on this head is recorded here by run ID. |
| 042 | No raw identifier in the primary UX | WP-TUX-05 | E2E + unit | `web/e2e/work-acceptance.spec.ts:178`, `:296`; `web/src/components/work/task-list-row.test.tsx:205`; `web/src/components/pulse/today-task-card.test.tsx:284`; `web/src/components/tasks/use-task-operations.test.tsx:596` | PASS | Diagnostics deliberately retain the identifier; `:178` asserts both halves. |
| 043 | No raw lifecycle or priority token in the primary UX | WP-TUX-05 | E2E + unit | `web/e2e/work-acceptance.spec.ts:178`, `:296`; `web/src/components/work/task-list-row.test.tsx:180`; `web/src/lib/tasks/presentation.test.ts:52` | PASS | |
| 044 | A Today card states what, why, and the action | WP-TUX-07 | unit + E2E | `web/src/components/pulse/today-task-card.test.tsx:180`; `web/e2e/today-tasks.spec.ts:302` | PASS | Reading order is asserted, not merely presence. |
| 045 | 320–430 CSS px with no horizontal scroll | WP-TUX-05/06/07 | E2E | `web/e2e/work-acceptance.spec.ts:162` (Task detail @ 320/375/390/430), `:637` (Board and Calendar @ 320/375/390/393/430, `NARROW_WIDTHS` at `:337`); `web/e2e/today-tasks.spec.ts:716` (Today @ 320/360/375/390/430) | PASS | Blocking `responsive` lane. This is narrow-viewport reflow, not browser zoom, and is not a WCAG 2.2 AA claim. |
| 046 | Two-click Close by keyboard **and** under VoiceOver | WP-TUX-02 | E2E (keyboard half) | keyboard: `web/src/components/tasks/task-close-control.test.tsx:85`, `:99`; `web/e2e/work-acceptance.spec.ts:203`. VoiceOver: none | **PENDING-RUNTIME** | Operator-gated. The keyboard half is proven; no automated harness in this repository drives VoiceOver. Requires a human on real macOS/iOS VoiceOver. Cannot close in an agent session. |
| 047 | Board and Calendar offer non-drag alternatives | WP-TUX-05 | E2E | `web/e2e/work-acceptance.spec.ts:536` (Board), `:604` (Calendar) | PASS | Blocking `responsive` lane. |
| 048 | Obsolete acceptance locks are replaced | WP-TUX-08 | this ledger | `docs/acceptance/task-ux-ac-ledger.md` (this file) | PASS | The criterion is satisfied by the existence of a re-enumerated, citation-bound ledger that supersedes the prior ad-hoc locks. |
| 049 | Backend coverage runs in blocking CI | WP-TUX-01 | unit + DB + CI | `tests/unit/test_task_management_service.py` (29 tests) via `.github/workflows/repository-checks.yml:18` `validate`, FAST tier at `:109`; `tests/database/test_task_management_service.py` (11 tests) via `:410` `database-current-head`, selector `-m "(database_clone or database_transactional) and not recovery and not e2e and not migration*"` at `:488` | PASS | Counts re-verified at this head: 29 and 11. |
| 050 | Acceptance on a physical iPhone | WP-TUX-06/07 | runtime | none | **PENDING-RUNTIME** | Operator-gated. Playwright's `mobile` project is an emulated viewport, not a device; WebKit under Playwright is explicitly not Safari (`web/e2e/search-contract.spec.ts:363`). Requires a human with hardware. Cannot close in an agent session. |

## Tally

| Status | Count | Criteria |
|---|---|---|
| `PASS` | 45 | all except those listed below |
| `PENDING-RUN` | 1 | 041 |
| `PENDING-RUNTIME` | 3 | 036, 046, 050 |
| `GAP` | 1 | 011 |

**Reachable in this session: 45 of 50.** AC-036, AC-046 and AC-050 cannot close without an
authenticated external MCP client, a human on VoiceOver, and physical hardware respectively.
AC-041 closes on a recorded specialized run. AC-011 needs a product decision before it needs a test.
That arithmetic is the whole justification for
`TASK_UX_REMEDIATION_IMPLEMENTATION_COMPLETE_RUNTIME_ACCEPTANCE_PENDING`.

## Execution record

WP-TUX-08 added no test and changed no assertion, so the suites below are recorded as *unchanged*
baselines held across the traceability commit, not as new acceptance evidence.

| Suite | Command | Result |
|---|---|---|
| Frontend types | `web/node_modules/.bin/tsc --noEmit` | exit 0 |
| Frontend lint | `web/node_modules/.bin/eslint .` | 0 errors, 123 warnings (baseline) |
| Frontend unit | `TZ=UTC web/node_modules/.bin/vitest run` | 208 files, 2190 tests, all passed (baseline, unchanged) |
| Annotated E2E | `npm run e2e -- e2e/pwa.spec.ts e2e/accessibility.spec.ts e2e/work-acceptance.spec.ts e2e/today-tasks.spec.ts --project=desktop` | 83 passed, 2.3m, exit 0 |

The E2E line above is a **local developer run**, not a CI run ID. It proves the docblock edits are
inert. It does **not** promote row 041: that row needs an executed `pwa-offline` lane recorded by
run ID, and a local green on an advisory spec is exactly the inference TUX08-F007 forbids.

## Findings

### TUX08-L011 — TASK-AC-011 has no upstream semantic to preserve

`web/src/lib/tasks/presentation.ts:194` records, in the source itself, that a caller opts into an
explicit time "only once that semantic exists upstream". Nothing upstream authors one: the create
sheet serializes a chosen Due to civil day end
(`web/src/components/tasks/task-create-sheet.test.tsx:237`), and `useTaskOperations.changeDue`
takes a civil date and does the same (`web/src/components/tasks/use-task-operations.test.tsx:385`).
`presentation.test.ts:197` proves only the display rule — a time is *omitted* unless the caller asks.

So TASK-AC-011 is not a missing test, it is a criterion whose precondition does not exist at this
head. It is recorded as **GAP**, not quietly attached to the civil-day-end tests, which prove the
opposite behaviour. Routed to the owning product/backend WP for a decision: either the explicit-time
semantic lands upstream and the criterion becomes testable, or the criterion is retired.

The draft ledger cited `use-task-operations.test.tsx:377` for this row. That line sits inside the
test at `:385` (post-annotation numbering), which asserts civil-day-end serialization — the opposite
of preserving an authored time. The citation was wrong and has been withdrawn rather than corrected.

### TUX08-L049-B — `_tasks_create` accepts a `project_id` it does not check for ownership

**Pre-existing. Outside WP-TUX-08 scope. Recorded here, not fixed here.**

`ApplicationService._tasks_update` (`src/my_pa/application/service.py:8347`) refuses a `project_id`
the calling Principal does not own:

```
src/my_pa/application/service.py:8390-8392
    if command.project_id is not None and (
        unit_of_work.projects.get_project(principal_id, command.project_id) is None
    ):
        raise NotFoundError(SafeDetail.PROJECT_ID)
```

`ApplicationService._tasks_create` (`:8284`) performs no equivalent check. It passes
`project_id=command.project_id` straight through at `:8326`. The only backstop is the table
definition at `src/my_pa/infrastructure/persistence/tables.py:6915`:

```
    Column("project_id", Text, ForeignKey(f"{SCHEMA}.projects.project_id")),
```

That is a **single-column** foreign key. It enforces that the project row exists; it does not
enforce that it belongs to the creating Principal, because `principal_id` is not part of the
reference. A Principal who learns another Principal's `project_id` can therefore create a Task
against it, where the same value on update would be refused.

This is a create/update asymmetry in a Principal-partitioning boundary, not a Task-UX defect, and
WP-TUX-08 is a traceability package with no production-source authority. It is routed to the owning
backend work package. It affects no row above: no TASK-AC criterion asserts create-side project
ownership.

## Maintenance

- A row's citation is a line number. Line numbers move. When a cited test file is edited, re-read
  the cited line and confirm it still says what the row claims, or re-point it. `rg "TASK-AC-0"`
  over the repository is the index this ledger is bound to.
- Two test titles in `web/e2e/work-acceptance.spec.ts` are selected by `--grep` at
  `.github/workflows/frontend-quality.yml:455` — "real touch targets" and "holds 44px across the
  width matrix". Renaming either silently empties that step. Prefer docblock identifiers over title
  changes everywhere, which is what WP-TUX-08 did.
- Never promote a row to PASS from an advisory lane's green. See TUX08-F007 and row 041.
