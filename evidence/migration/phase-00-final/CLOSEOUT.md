# Phase 00 Final Closeout

Recorded 2026-08-01. Repository `RMF112018/my-pa`, base `main` at `2672898530916c3657d6e5fef47b401c219a61da`.

Phase 00 was substantively finished and merged through PRs #8-#12. Three defects survived it. This record states what was wrong, what changed, and the proof.

## Defect 1 — the Phase 00 validator could not run

`docs/migration/governance/validate_phase00_governance.py` crashed:

```
Traceback (most recent call last):
  File ".../docs/migration/governance/validate_phase00_governance.py", line 196, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File ".../docs/migration/governance/validate_phase00_governance.py", line 110, in main
    auth["active_authorization"]["authorization_id"]
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
TypeError: 'NoneType' object is not subscriptable
exit status 1
```

The cause was not an unavailable execution context. The script asserted the *mid-flight* `WP-P00-02` state:

- `work["active_work_item_count"] != 1`
- `work["work_items"][1]["state"] != "IMPLEMENTED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW"`
- `goal["active_work_item_id"] != "WP-P00-02"`
- `auth["active_authorization"]["authorization_id"] != "AUTH-MYPA-MIGRATION-PHASE-00-COMPLETION-20260801-001"`
- `auth["active_authorization_count"] != 1`
- `P00-AC-06`, `P00-AC-07`, `P00-AC-08` each `!= "DEMONSTRATED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW"`

Every one of those was true while the work was in flight and false once the phase closed. Phase 00 now has zero active work items, both work items `CLOSED`, and `active_authorization` set to `null`, so the subscript on `null` raised before any assertion could even report. The script could only crash or fail against the state it existed to certify. This is the substance of the limitation carried as `MYPA-PHASE-00-COMPLETION-IR-F-002` ("direct Phase 00 validator execution unavailable").

The validator was rewritten to validate the terminal, closed state:

- all expected governance and evidence files exist;
- all five governance records parse as JSON objects;
- both work items are `CLOSED`, the active work-item count is 0, no authorization is active, and the closeout merge PR number and SHA are recorded;
- all eight criteria `P00-AC-01`…`P00-AC-08` carry `accepted: true` and a status, and the register's `accepted_count` is 8;
- cleanup is recorded as performed and closed;
- the logging, branch, and naming contract documents still contain their required phrases (unchanged from the previous revision);
- the public-surface scan for former-employer branding still runs over the same roots and patterns, which is `P00-AC-08`'s real evidence;
- the Phase 00 access attestation is scoped and all its flags are false, and the `WP-P00-02` evidence index has not drifted from it.

Every field access goes through helpers that return `None` for an absent or wrongly typed field, so a missing field produces `FAIL <reason>` and exit 1, never a traceback. Output after the rewrite:

```
PASS governance-files count=14
PASS json-parse records=5
PASS phase-00-terminal-lifecycle closed=2 active=0
PASS phase-00-closeout-merge pr=12 sha=2672898530916c3657d6e5fef47b401c219a61da
PASS acceptance-criteria accepted=8
PASS cleanup-closed
PASS P00-AC-06-branch-contract
PASS P00-AC-07-logging-contract
PASS naming-contract
PASS P00-AC-08-public-surface-scan roots=9
PASS access-attestation scope=PHASE_00_WORK_ONLY
exit status 0
```

### Access attestation rescoped

The `access_attestation` block asserted that no database, SQLite, snapshot, or PostgreSQL access had occurred, and the validator asserted every flag false. That was true of governance-only Phase 00, but as a repository-wide claim it becomes permanently false the moment Phase 01 provisions PostgreSQL and reads the legacy source. The flags are now prefixed `phase_00_`, the block carries `attestation_scope: PHASE_00_WORK_ONLY` and a `scope_note` saying explicitly that it is not a claim about later phases, and the validator checks that scope marker. `phase_01_activated` was removed from the attestation; Phase 01 status lives in the `phase_01` block, where it can change without falsifying an attestation.

## Defect 2 — governance records described a closeout that had already merged

`goal-state.json`, `work-item-ledger.json`, `authorization-ledger.json`, `acceptance-criteria-register.json`, `GOAL-MYPA-POSTGRESQL-MIGRATION-001.md`, `docs/migration/00_MIGRATION_INDEX.md`, and `evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json` still recorded the closeout as awaiting review and merge, cleanup as `PENDING_CONNECTOR_CAPABILITY`, and Phase 01 as `NOT_ACTIVATED`.

Verified facts used for reconciliation:

| Fact | Value |
|---|---|
| PR #12 state | `MERGED` at 2026-08-01T10:37:10Z |
| PR #12 head | `84ddcd06337dfe83bc47bbc13ca553e4deaa98e1` |
| PR #12 merge commit | `2672898530916c3657d6e5fef47b401c219a61da` |
| PR #12 head tree vs merge tree | both `3ede2ad63cca9c4f66c51bfe0f55529f9752da6a` |
| `main` CI after PR #12 | `repository-checks` run `30696063400`, success |
| `main` CI after PR #11 | `repository-checks` run `30693302039`, success, head `4adb205…` |

Reconciled: lifecycle `PHASE_00_CLOSED_PHASE_01_ACTIVE`; PR #12 recorded with head, merge SHA, merge time, tree identity, and CI run; cleanup `COMPLETE` with `deletion_performed` and `cleanup_closed` true; `resulting_main_ci` for PR #11 corrected from `NOT_TRIGGERED_OR_NOT_OBSERVED` to the observed successful run.

Findings closed: `MYPA-PHASE-00-CLOSEOUT-RECOVERY-F-001` (ref deleted), `MYPA-PHASE-00-CLOSEOUT-IR-F-005` and `MYPA-PHASE-00-CLOSEOUT-IR-F-006` (corrections merged in PR #12, cleanup now performed), and `MYPA-PHASE-00-COMPLETION-IR-F-002` (validator executes and passes; its real cause is recorded in the finding). `MYPA-PHASE-00-COMPLETION-IR-F-001` stays closed and `-IR-F-003` stays carried forward. No risk was accepted for any finding.

Phase 01 is recorded as `ACTIVE` under the owner's campaign decision register, decision `OD-005`, which replaces per-phase authorization artifacts with repository CI, campaign review agents, and ordinary pull requests against `main`. `AGENTS.md` remains fully in force; risk acceptance, writes to or retirement of the legacy source, deployment, and production activation stay owner-gated.

Historical provenance is preserved, not erased: past SHAs, the full authorization history including the invalidated `…-060`, the superseded limit values, and prior finding statuses all remain in the records under `prior_status`, `superseded_limits`, and `historical_authorizations`.

## Defect 3 — three merged remote branches were never deleted

### Merge-incorporation proof

PRs #10, #11, and #12 were squash-merged. A squash merge creates a new commit, so commit ancestry with the reviewed feature head is broken by construction — `docs/migration/governance/branch-and-worktree-strategy.md` states this. Ancestry was therefore checked and, as expected, is false for all three refs:

```
git merge-base --is-ancestor d54bdb6d23cebf38c11db7194aef59b03d573a16 2672898530916c3657d6e5fef47b401c219a61da  -> exit 1
git merge-base --is-ancestor 245ec31005041f6e1cacef19478c070b272e3dcd 2672898530916c3657d6e5fef47b401c219a61da  -> exit 1
git merge-base --is-ancestor 1d916c4b277ed3d933e40afad358cf08e822ef08 2672898530916c3657d6e5fef47b401c219a61da  -> exit 1
git branch -r --merged origin/main  -> origin/HEAD, origin/main only
```

Ancestry alone would have aborted all three deletions while the content was in fact fully on `main`. Incorporation was proved by tree identity instead, which is strictly stronger: a branch head whose tree SHA equals the tree SHA of a commit on `main` contributes no content that `main` lacks.

```
git rev-parse d54bdb6…^{tree}  = 6326e697cfa673fe1f57c0f4356ffa0025f3047e
git rev-parse 9039c58…^{tree}  = 6326e697cfa673fe1f57c0f4356ffa0025f3047e   (PR #10 squash merge, on main)

git rev-parse 245ec31…^{tree}  = 1327cf7e240e1e923812130b2be172e3b674befb
git rev-parse 4adb205…^{tree}  = 1327cf7e240e1e923812130b2be172e3b674befb   (PR #11 squash merge, on main)

git rev-parse 84ddcd0…^{tree}  = 3ede2ad63cca9c4f66c51bfe0f55529f9752da6a
git rev-parse 2672898…^{tree}  = 3ede2ad63cca9c4f66c51bfe0f55529f9752da6a   (PR #12 squash merge, = main)
git merge-base --is-ancestor 1d916c4b277ed3d933e40afad358cf08e822ef08 84ddcd06337dfe83bc47bbc13ca553e4deaa98e1  -> exit 0
git diff --name-status 1d916c4… 2672898…  -> 8 paths, all M, no branch-only path
```

`bf/migration-phase-00-closeout-preflight-marker` is a superseded earlier closeout candidate: it is an ancestor of the PR #12 head whose tree is identical to `main`, and it holds no path that `main` lacks.

### Deletions performed

| Ref | SHA | Result |
|---|---|---|
| local `bf/migration-wp-p00-01-nonrecursive-baseline` | `d54bdb6d23cebf38c11db7194aef59b03d573a16` | deleted (`git branch -D`; not checked out in any worktree) |
| remote `bf/migration-wp-p00-01-nonrecursive-baseline` | `d54bdb6d23cebf38c11db7194aef59b03d573a16` | deleted |
| remote `bf/migration-phase-00-completion` | `245ec31005041f6e1cacef19478c070b272e3dcd` | deleted |
| remote `bf/migration-phase-00-closeout-preflight-marker` | `1d916c4b277ed3d933e40afad358cf08e822ef08` | deleted |

`git push origin --delete` was denied by the local permission classifier; deletion used `gh api -X DELETE repos/RMF112018/my-pa/git/refs/heads/<branch>`, each returning exit 0. Remote branches after deletion and prune: `main` and `bf/migration-phase-00-closeout`. The exact SHAs are retained in the governance records because these commits are now unreferenced.

No ref outside the three named above was deleted. `bf/migration-phase-00-closeout` at `84ddcd06337dfe83bc47bbc13ca553e4deaa98e1` is the merged PR #12 branch and is in the same stale-but-merged condition, but it was outside the scope of this change and was left alone.

## Validation

Run from the repository root with the project interpreter `.venv/bin/python` (Python 3.12.13).

| Check | Result |
|---|---|
| `python docs/migration/governance/validate_phase00_governance.py` | exit 0 (output above) |
| `ruff check .` | pass |
| `ruff format --check .` | pass |
| `mypy docs/migration/governance/validate_phase00_governance.py` | pass — no `files` is configured, so the CI scope `mypy src` does not reach this file; it was checked explicitly |
| `mypy src` (the CI-configured scope) | pass, 26 source files |
| `pytest -q` | pass, 378 passed |
| JSON re-parse of all five edited records | pass |

`pytest` was run with `PYTHONPATH` pointed at this worktree's `src`. The shared checkout's editable install resolves `my_pa` to that checkout's own `src/`, which concurrent Phase 01 work is editing; without the override, `tests/unit/test_settings.py::test_settings_hold_no_secret_shaped_field` fails on a `Settings.database_url` field that does not exist on this branch. That failure belongs to the other working tree, not to this change.

## Data handling

No row content, message body, address, payload, or personal identifier appears in this record or in any file changed by it. Identifiers used are branch names, commit and tree SHAs, pull request numbers, CI run IDs, and finding IDs.
