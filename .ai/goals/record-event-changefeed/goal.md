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
| CP-RE-01 | WP-RE-01 | the commit that adds this row (SHA recorded in the CP-RE-02 update and the PR) | | 001-017 | green: 25,169 passed / 74 skipped / 0 failed; ruff, format, mypy (522 files) clean | PG 15.15 local, PGTZ=UTC: new DB modules + meeting app 114 passed; recovery `tests/concurrency` 15 passed; migration_empty_to_head 9 passed; migration_edge subset 179 passed (worker full lane 1,052 passed) | revision `1d9b248e7f83` (down `7d9a450dfd07`); N-conditions none fired |

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

## Review outcome and final state

Pending.
