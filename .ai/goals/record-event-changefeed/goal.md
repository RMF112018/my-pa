# Goal: Record Event / Change Feed (Gate 2, WP-RE-01..07)

## Identity

- Goal ID: `record-event-changefeed`
- Coordination request: `MYPA-RECORD-EVENT-CHANGEFEED-GATE2-IMPLEMENTATION-20260929-001` (parent `MYPA-RECORD-EVENT-CHANGEFEED-GATE1-PLANNING-20260929-001`, PLAN_APPROVED)
- Authorization: GATE2-IMPLEMENTATION-AUTHORIZATION-ISSUED (Drive `1hSti-ja53NbVEYgVMMAuU1qQyC0P420s`, SHA-256 `1b8671340f93e45ffe9042a4523b7cec8a2ffbfb0410cbf3c322b659fde66964`)
- Operator rulings: Drive `1eGaV_16WVOcPgVdSJvyc5sBMqZFYB0Jw` (SHA-256 `40ff9f0c…9e10cf`)
- Repository: `RMF112018/my-pa`
- Branch: `bf/record-event-changefeed-20260929`
- Worktree: `/Users/bobbyfetting/my-pa-wt/record-event-changefeed`
- Base: `origin/main` `d6c706bb4e43cc15eefcda35f40d66eb58abe9ed`, tree `31d6dcebaf4fa076ec33d387a4e527d983518373`
- Head / PR: recorded per checkpoint below
- Gate-2 evidence Drive folder: `15gJT1I5uoEL3sMJb9uJWGHBzOnRVE5dt`

## Objective and scope

Implement the approved Gate-1 plan WP-RE-01..07 serially on one branch and one draft PR. Terminal state: **PR-READY, NOT MERGED** (`GATE2_PR_READY_NOT_MERGED`).

- Acceptance criteria: RE-AC-001..085 (Part 2 matrix), none weakened, renumbered or deselected.
- Scope: only the paths in the PATH-SYMBOL-OWNERSHIP matrix, plus this file, plus strictly mechanical consequences (recorded per checkpoint).
- Binding rulings: OD-1 (i) event_id cursor; OD-2 (i) + (d-i); OD-3 (i); OD-4 **B** (migration generated in WP-RE-01, re-pointed at R2/R3); OD-5 INCLUDE; OD-6 `review.decide`; OD-7 (i) `series_version`; OD-8 (i); OD-9 admitted to MCV (no `docs/plans/mcv-completion-plan.md` edit for OD-9); OD-10 (i); OD-11 (i) DATA_REQUIRED; OD-12 (i).

## Prohibitions

No merge (no §8.1 delegated merge, no `wi-complete`, no auto-merge); no deploy/NAS/production; no live DB write or migration; no live grant/profile/OAuth/secret/config change; no second PR; no weakening/deselection/xfail of any RE-AC or applicable test; no RE-AC PASS without exact-head evidence; no risk acceptance; no edits to PR #287 or any other branch; never touch `~/my-pa`. Stop conditions: package §19 items 1-9 and N1-N23.

## Execution topology (AGENTS.md §8.3)

Manager → one Orchestrator → specialized workers; at most one worker active at a time; model set explicitly, never above Opus; workers run tests in the foreground; one SFI owns PATH-SYMBOL §1 files.

## R1 record (branch creation), 2026-09-29

Re-derived in the worktree (PYTHONPATH=src):

| Fact | Bound basis | R1 value | Match |
|---|---|---|---|
| `origin/main` (ls-remote) | `d6c706bb4e43…` | `d6c706bb4e43cc15eefcda35f40d66eb58abe9ed` | yes |
| tree | `31d6dceb…` | `31d6dcebaf4fa076ec33d387a4e527d983518373` | yes |
| Alembic heads | `7d9a450dfd07` (sole) | `7d9a450dfd07 (head)`, single | yes |
| Revision files | 108 | 108 | yes |
| `Capability` | 178 | 178 | yes |
| `Purpose` | 47 | 47 | yes |
| `IdKind` members / `rcev` | 130 / absent | 130 / absent | yes |
| ChatLLM profile | `chatllm-data-v3` | `chatllm-data-v3` | yes |
| DATA_REQUIRED / CONDITIONAL / COMPAT / CONTROL_PLANE / OPERATOR_DECISION / RETIRED | 69/90/2/15/2/0 | 69/90/2/15/2/0 | yes |
| Audit vocabulary (latest restating revision `7d9a450dfd07`) | 189 / 47 | 189 / 47 (comments at AT literals) | yes |
| Source / test modules | 357 / 588 | 357 `*.py` under `src` / 588 `test_*.py` under `tests` | yes |

- PR #287: OPEN, CONFLICTING, head `b9b2b203cda2bf19c95e48d82b3f87ace99ed030`; files `docs/plans/relationship-intelligence-implementation-plan.md`, `ops/nas/preserved-runtime-env-preflight.py`, `tests/architecture/test_nas_preserved_runtime_env_preflight.py`. Unchanged from the plan (sequencing dependency at WP-RE-07). Only open PR.
- §9 branches: `cursor/stage-a-post-pr278-rebase-4d70` @ `f01825af`, `handoff/stage-a-candidate-pre-pr278-20260924` @ `dce96b19`, `claude/festive-fermi-lh0oat` @ `5a57f265`: dormant, no PR; classification unchanged (none).
- Main has not moved since the bound SHA, so no WP is invalidated (N3 not fired). All controlling-source SHA-256 values verified by the Orchestrator.

## Checkpoint ledger

| CP | WP | Head | Tree | RE-AC | FAST | DB lane (local PG) | Notes |
|---|---|---|---|---|---|---|---|
| CP-RE-01 | WP-RE-01 | `bf1bfe9c61496275440a13be1be3fd8d4eb94962` | `8f9f2b38fcef0b35d877c82820429973ceb0dc75` | 001-017 | green: 25,169 passed / 74 skipped / 0 failed; ruff, format, mypy (522 files) clean | PG 15.15 local, PGTZ=UTC: new DB modules + meeting app 114 passed; recovery `tests/concurrency` 15 passed; migration_empty_to_head 9 passed; migration_edge subset 179 passed (worker full lane 1,052 passed) | revision `1d9b248e7f83` (down `7d9a450dfd07`); N-conditions none fired |
| CP-RE-02 | WP-RE-02 | `97cae35bb8185ef6f082143321ca028bf7966cfe` | `7bc006d28f280e678ab200ee9e9003e1b8c8bbba` | 018-030 | green: 25,188 passed / 74 skipped / 0 failed; ruff, format, mypy (522) clean | PG 15 local, PGTZ=UTC: WP-02 + task/commitment/project/continuity + record-event DB modules 195 passed; full `-m recovery` 46 passed (worker: full tests/database 1,689 passed) | no N fired; T-12 premise finding (below) |
| CP-RE-03 | WP-RE-03 | `9102e2f2642a3ef6bf7cc16b93ecd8460fa79509` | `ee2238f806f4e0bff42dc1850b1ac107a20aff85` | 031-043 | green: 25,206 passed / 74 skipped / 0 failed; ruff, format, mypy (522) clean | PG 15 local, PGTZ=UTC: 32 constraint/project-controls/project-create/tbr DB modules 468 passed; full `-m recovery` 46 passed (worker: full tests/database 1,713 passed) | no N fired; T-10 no 40P01/lock_timeout |
| CP-RE-04 | WP-RE-04 | `d442f923705025ff03c323c06caf9a0840d367ea` | `d1025a5765c2dc1aa8a9202d17218a78e1cb3892` | 044-051 | green: 25,274 passed / 74 skipped / 0 failed; ruff, format, mypy (522) clean | PG 15 local, PGTZ=UTC: entity/identity/memory/review/reenrichment/record-event DB modules + no-payload 916 passed; full `-m recovery` 46 passed | no N fired (N8 resolved as not-fired, MR-05); T-15 no 40P01 |
| CP-RE-05 | WP-RE-05 | the commit that adds this row (SHA recorded in CP-RE-06) | | 052-056 | green: 25,299 passed / 74 skipped / 0 failed; ruff, format, mypy (522) clean | PG 15 local, PGTZ=UTC: meeting DB/concurrency + record_event DB modules 185 passed; full `-m recovery` 46 passed | no N fired; T-13 no 40P01 |

**CP-RE-01 out-of-matrix mechanical edits (as reported to the Manager):**
- C5/C6 fan-out: 34 `HEAD_PIN_FILES` plus the control file `tests/schema/test_constraint_authoring_capability_migration.py`, 24 revision-count pins, and `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`.
- `KNOWLEDGE_TABLES_BY_REVISION` in `tests/schema/test_extraction_schema_migration.py`.
- The trigger inventory in `tests/schema/test_capture_schema_migration.py`.
- The 5 hand-kept stacked-table lists (audit/entity/entity_assertion_provenance/enrollment/entity_relationship_types migration tests).
- The `tests/unit/test_identifiers.py` prefix set.
- `tests/schema/test_meeting_records_migration.py`: head and link assertions, plus `at=REVISION` in the two downgrade-refusal tests.
- `TABLES_SHA256` re-pin in `tests/architecture/test_capture_project_binding.py` (MR-01).
- Registry entries in `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` and `tests/architecture/test_principal_is_never_caller_supplied.py` (`VERIFIED_CALLER_STATEMENTS`).
- Head-citing docs forced by `test_readme_state_claims.py`: `README.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`, `docs/architecture/system-context.md`, `ops/runbooks/gateway-operations.md`, `ops/runbooks/mcp-and-cli-operations.md`.
- `docs/plans/mcv-completion-plan.md`: head, count and module-count lines, plus a remeasurement paragraph. No OD-9 text.
- `docs/plans/relationship-intelligence-implementation-plan.md` cells :660/:661/:663/:664. These overlap PR #287.
- Schema strengthening: `'' <> ALL (changed_fields)`.

## Working notes

(Orchestrator notes; updated per WP.)

### WP-RE-01 (CP-RE-01)

- SFI worker (opus) did Phase A (substrate) and Phase B (adapter/flush/tests). The Orchestrator re-ran FAST (unit+schema 14,915; architecture 5,857 passed / 71 skipped; other 4,397 passed / 3 skipped), ruff, format, mypy, and the DB/recovery/migration subsets itself.
- Port member `record_events` is a non-abstract refusing default. U1-U4 override it, and T-18 enforces this.
- `RecordEventAuthority` = the union of `MutationAuthority` and `MemoryAuthority` (6 values).
- Schema strengthening found in testing: `'' <> ALL (changed_fields)` in the changed_fields CHECK.
- Prove-reds: 24 guards, each isolated. Two first attempts were masked or defective and were fixed before recording (N13 handled by a new non-masked test `test_a_refused_batch_rolls_back_the_canonical_change`). T-09 mutant gave 40P01. No deadlock or lock_timeout in the unmutated runs.
- Mechanical out-of-matrix edits:
  - C5/C6 head and revision-count fan-out: 34 HEAD_PIN_FILES plus the control file, and 24 revision-count files.
  - Five hand-kept stacked-table lists.
  - `KNOWLEDGE_TABLES_BY_REVISION`, the trigger inventory, and `test_identifiers.py` prefix set.
  - `TABLES_SHA256` re-pin (`test_capture_project_binding.py`; tables.py diff is purely additive).
  - `test_principal_partition_is_reached_through_the_guard.py` and `test_principal_is_never_caller_supplied.py` registry entries.
  - Head-citing docs forced by `test_readme_state_claims.py` (README.md, 00_ARCHITECTURE_INDEX.md, system-context.md, gateway-operations.md, mcp-and-cli-operations.md).
  - Count cells in both guarded docs/plans files: the relationship-intelligence plan :660/:661/:663/:664 cells overlap PR #287. No OD-9 text.
- Local environment divergences: PG 15 locally vs PG 17 in CI. Two `test_health_probe.py` failures assert PG 17. Local time zone needs `PGTZ=UTC`.
- Deferred to WP-RE-06: G1-MG-013 `CHECKED_VOCABULARY`. Deferred to WP-RE-07: unbound stale head comments (mcp-and-cli-operations.md:494,533; ops/nas configs; mcv-limitations.md).

### WP-RE-02 (CP-RE-02)

- Emitters:
  - Task (`_mutate` APPLIED only; typed diff incl. the implicit `role` clear; transition closure fields);
  - `continuity.tasks.create` (receipt = OPENED lifecycle event; `author_task` returns it; the port signature is updated);
  - `bulk_confirm` (applied members, `mutations` order);
  - Commitment create/update/close;
  - Project create, then the bound Entity (causation = the Project event, receipts None);
  - Project update/close (APPLIED and not replayed; an identical update gives `("version",)`).
- `invoke` raises InternalError if a committed refusal has staged drafts (G1-TX-006).
- `_continuity_project_mutation` takes `lock_project` before `mutate()`. This is the same row and lock the writer takes first, so the lock order is unchanged.
- **Finding (T-12 premise):** the plan expected "concurrent same-name creates ⇒ one pair". Repository truth: `_mint_bound_project_entity` claims the name with an unlocked SELECT and there is no unique constraint (tables.py `projects`/`entities` indexes only), so both creates commit. This behaviour exists independently of this feature and is out of scope. The test asserts one pair per committed create instead. The RE-AC-028 text is met. This was referred to the Manager for a ruling.
- Mechanical edits:
  - `docs/plans/relationship-intelligence-implementation-plan.md` :660 (FAST 25,188) and :664 (DB 2,999), which are contended with PR #287;
  - `docs/plans/mcv-completion-plan.md` module counts (359/602).
- CP-RE-01 CI at `bf1bfe9c`: repository-checks run 36616266822 had all 9 jobs succeed, including `database-tier`. frontend-quality run 36616266764 had classify and required succeed; visual failed (continue-on-error, Darwin goldens).

### WP-RE-03 (CP-RE-03)

- Constraint, Category, Settings, sync and legacy-import emitters stage only on the U4 / `_Mutation.uow` / `active_uow` stager.
  - `create_published` emits one final `created`, with its substeps suppressed.
  - `close_with_follow_up` emits the predecessor `state_changed`, then the successor `created`, whose causation is the predecessor.
  - `reorder` emits one `updated` per Category in `wanted` order.
  - Settings events use `record_id = project_id`.
  - Legacy import emits Category events, then record events, as one batch (actor `system`, token `constraint_legacy_import.apply`).
  - Sync apply and resolve (accept_external, manual_patch, reopen) are covered; control rows emit nothing.
- MR-02(b) is satisfied. The T-12 concurrent test proves the same batch via equal `xmin` (plus `recorded_at` and `correlation_id`), the bound Entity via `project_entity_links`, causation pointing at the create's own Project event, and no cross-linking. Two prove-reds were recorded.
- RE-AC-043 prove-red: a new deterministic test, `test_a_composite_waiting_on_a_domain_lock_holds_no_allocator_lock`, gives 40P01 3/3 under the per-substep allocation mutant and is green unmutated.
- N13 was found and fixed: the resolve mutant stayed green, so manual_patch and reopen resolve tests were added.
- Edits outside the listed paths:
  - `domain/record_events.py`: the `source_receipt_id` check changed from "a known IdKind" to the any-kind opaque shape that matches the DDL CHECK. This was forced by the settings ledger's `cpsh_` receipt, which by design is not an `IdKind`. The hardened package §3.5 says only "opaque identifiers".
  - `tests/database/test_constraint_schema_invariants.py`: 7 `SimpleNamespace` stand-in units of work gain `record_events` (a test-double consequence).
  - The `_FakeUnitOfWork` doubles in `tests/unit/test_constraint_management_service.py` and `tests/unit/test_project_controls_settings_service.py`.
  - Doc count cells: `relationship-intelligence-implementation-plan.md` :660 (25,206) and :664 (3,023), contended with #287; `mcv-completion-plan.md` (359/608).
- CP-RE-02 CI at `97cae35b`: repository-checks run 36631335712 succeeded on all 9 jobs. frontend-quality run 36631335886 had classify and required succeed; visual failed (continue-on-error).
- Note: this CP-RE-03 ledger row and these notes were written after the CP-RE-03 commit (a script error) and are committed with CP-RE-04.

### WP-RE-04 (CP-RE-04)

- Phases were serialized on the SFI worker:
  - 4A: Entity seams S-A/S-B/S-C, derived drafts incl. MR-05 E5-E10, `resolve_mention` (G1-EM-002), review promotion RP1/RP2 (OD-6), memory M1-M4 (OD-8), stager injection, T-20, and the N9 guard.
  - 4B: merge/split seams, root = the lowest-entity_id Entity redirect/restore, staged first; all other events caused by the root; memory events de-duplicated; context-link owner; feed version; G1-EM-017; V-001; fail-closed on N17/N19.
  - 4C: W5 rebind emitter (OD-5; R-008 flush placement), T-17, T-18 extensions (W5, memory never root, X1-X3 dormant writers), and `tests/security/test_record_events_carry_no_payload.py` including the MR-06 one-column guard.
- MR-07: the exact reassignment columns come from the `_bound_records` domain objects. There is no new read, no new lock, and no signature change.
- `A/entity_authoring.py` is intentionally unchanged (decision 3): `entity_source_capability` returns `review.decide` exactly for the REVIEW_PROMOTION actor, which is admitted only on the promotion path.
- Prove-reds: 4A 21, 4B 17 (re-run after MR-07), 4C 15. All red on assertions. W5 flush-failure rollback is proven behaviourally rather than by mutant.
- Edits outside the matrix:
  - Mechanical:
    - registry entries in `test_principal_is_never_caller_supplied.py`;
    - `DECLARED_TABLE_REACH` and reasons in `test_every_capability_reaching_a_memory_row_is_declared.py`;
    - T-20 READS;
    - fakes and stubs in `tests/conftest.py`, `tests/evaluation/resolution_harness.py`, `tests/unit/test_identity_correction.py` and `tests/unit/test_identity_split_service.py` (MR-04 precedent);
    - count cells in `relationship-intelligence-implementation-plan.md` :660/:661/:664 (#287 contended) and module counts in `mcv-completion-plan.md` (359/619).
  - **MR-06:** `evidence/acceptance/RI-FINAL-COMPLETION-RM-AC-DELTA-20260828.md` (RM-API-AC-002 claim, classification column only).
- Stager-less repositories use a private unflushed buffer. `test_record_event_stager_injection.py` requires `stager=` at every writing construction in `src`.
- CI at `9102e2f2` (CP-RE-03): repository-checks 36644032291 succeeded on all jobs. frontend-quality 36644032408 had classify and required succeed; visual failed (continue-on-error).

### WP-RE-05 (CP-RE-05)

- The SFI worker was retired on the Manager's instruction. A fresh opus worker took over as SFI with a compact handoff brief (`scratchpad/WORKER-BRIEF-WP-RE-05.md`). The retired worker had completed, with no live children, per the harness completion notice; ListAgents is not in the Orchestrator toolset.
- Meeting emitters MT1-MT4:
  - a new series stages series `created` first, then meeting `created` with causation = the series event;
  - material updates stage `updated` with exact scalar names plus attendees/attachments/notes;
  - a series retitle stages `updated {title}`;
  - NO_OP and replay stage nothing.
- OD-7 (i) / D-21: `series_version: int | None` on `MeetingView` and `MeetingListEntry`, populated by the SQL read/list subquery. A standalone meeting refuses it.
- Departure from P2b (exactness, following MR-07 and the E9 precedent): a cancel or uncancel names `{cancelled_at, status}`.
- T-13 has 3 tests. The allocator-last hazard is proven red. The ascending entity-lock order is guarded by the existing `test_meeting_writes.py`, because FOR SHARE locks cannot deadlock, so the T-13 prove-red would stay green there.
- Mechanical/guard-forced edits:
  - `service.py` passes capability and correlation;
  - `tests/conftest.py` fake `_Meetings` carries `series_version`;
  - `tests/contract/test_meeting_contracts.py` `EXPECTED_FIELDS` gains `series_version` (exact-set guard, no weakening);
  - count cells: `relationship-intelligence-implementation-plan.md` :660 (25,299) and :664 (3,084), contended with #287;
  - `mcv-completion-plan.md` module count 359/623.
- No `web/` edit: the web app does not consume meetings.
- CI at `d442f923` (CP-RE-04): repository-checks 36664088723 succeeded on all jobs. frontend-quality 36664088720 had classify and required succeed; visual failed (continue-on-error).

## Manager rulings

- **MR-01 (2026-09-29):** the `TABLES_SHA256` re-pin in `tests/architecture/test_capture_project_binding.py` is MECHANICAL and ACCEPTED, because the tables.py diff against the base only adds lines and the captures Table is unchanged. Each later tables.py edit re-pins it under the same rule, provided the captures Table stays unchanged. CP-RE-01 was accepted by the Manager, and draft PR #297 is open.

- **MR-02 (2026-09-29):** the T-12 reframe is ACCEPTED as a correction to a plan premise, not a weakening.
  - RE-AC-028 says only "Project create emits Project + bound Entity in causal order".
  - The "concurrent same-name ⇒ one pair" clause exists only in the TRANSACTION matrix T-12 row.
  - Evidence: `_mint_bound_project_entity` (`src/my_pa/infrastructure/persistence/continuity_authoring.py`) claims the canonical name with an unlocked `SELECT entities.entity_id WHERE canonical_name = …`. Neither `projects` nor `entities` in `tables.py` has a unique constraint on the name (indexes only: `projects_by_principal`, `projects_by_principal_state`, `entities_by_principal`, `entities_by_entity_type`). Two concurrent same-name creates therefore both commit.
  - Conditions:
    - the test runs the two creates truly concurrently, behind a barrier;
    - for each committed create it asserts exactly one Project event followed by one Entity event, in the same batch, with causation pointing at that create's own Project event;
    - it asserts no cross-linking between the two creates.
  - The race is NOT fixed and no issue is opened; the Manager reports it to the operator as a separate candidate work item.
  - CP-RE-02 was accepted.

- **MR-03 (2026-09-29):** the `source_receipt_id` relaxation in `domain/record_events.py` is ACCEPTED as a correction toward the specification.
  - Hardened package §3.5 requires only "opaque identifiers".
  - `RECEIPT_IDENTIFIER_PATTERN` is byte-equivalent to the migration and `tables.py` CHECK `^[a-z]+_[A-Za-z0-9]{8,64}$`.
  - `event_id`, `principal_id`, causation and correlation keep their exact-kind checks.
  - The `cpsh_` provenance is kept.
- **MR-04 (2026-09-29):** the stager additions are ACCEPTED as mechanical test-double consequences, with assertions unchanged. They are the `SimpleNamespace` stand-ins in `tests/database/test_constraint_schema_invariants.py` and the `_FakeUnitOfWork` doubles in `tests/unit/test_constraint_management_service.py` and `tests/unit/test_project_controls_settings_service.py`. CP-RE-03 was accepted.

- **MR-05 (2026-09-29):** N8 did NOT fire. The `_advance_entity` parent-Entity advance (`P/entity_authoring.py` `_mutate` :455, `_advance_entity` :821-845) on the six identifier/alias operations is an enumerated compound write.
  - Citation: Gate-1 evidence P2b emitter matrix (`scratchpad/sources/gate1-evidence/P2b-emitter-matrix.md`, SHA-256 `38c601a0beaa5fb4e1992622cc76afe2b8c71ee694d470c80113ec8d3a78d10b`), §3.5 rows E5-E10 (lines 251-256), and finding G1-EM-001(a) (line 494).
  - Option (a) is the planned behaviour: a derived `entity` `updated` with `record_version = outcome.entity_version` and `changed_fields = ("version",)`; causation is the primary child event; it carries the same receipt, actor, authority and capability as the primary event.
  - E7/E10 order: primary replacement `created`, then the predecessor `state_changed`, then the `entity` `updated`.
  - P2b §3.5-§3.7 and §3.9 are the row-level reference for WP-RE-04, subordinate to the rulings where they differ.
  - Worker design decisions 1-7 are accepted. Decision 3: `src/my_pa/application/entity_authoring.py` is intentionally unchanged. `review.decide` comes from one domain helper keyed on the REVIEW_PROMOTION actor (OD-6), and a REVIEW_PROMOTION actor is already refused off the review path.
  - No GATE2_BLOCKED receipt.

- **WP-RE-04 P2b departures (2026-09-29, accepted as repository-truth corrections):**
  - E18: observation reject/defer is `updated {resolution_version}`, because `decide_observation` sets no state for them. Only quarantine is `state_changed`.
  - E9: alias retire is `{retired_at, state}`, because `_transition_alias` also sets `retired_at`.
- **MR-06 (2026-09-29):** option (a) is ACCEPTED. Under OD-8 (i), merge and split read `relationship_memory_versions`, but only the `classification` column plus the join key, to stamp memory events. This is a change to accepted privacy claim RM-API-AC-002, and the Manager surfaces it to the operator.
  - Claim source edited: `evidence/acceptance/RI-FINAL-COMPLETION-RM-AC-DELTA-20260828.md`. It is a live guard-parsed claim document. The claim must name only the `classification` column plus keys, and it keeps the dated WP-RE-04 paragraph.
  - The one-column limit is guard-enforced, with a single-guard prove-red.
  - The edit is listed among the CP-RE-04 out-of-matrix edits.
- **MR-07 (2026-09-29):** the S5 over-approximation is NOT accepted. `changed_fields` must name the exact changed column plus `version`.
  - Use the recorded effect state if it names the column. Otherwise use one same-transaction read, with no new lock and no order change.
  - STOP if this would need a repository signature change outside the matrix.
  - Test: a multi-column family where only one column references the source.

## Review outcome and final state

Pending.
