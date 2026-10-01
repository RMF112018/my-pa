# Goal: CRL-WP-03 Capture lifecycle runtime (archive / restore)

## Identity

- Goal ID: `crl-wp03-capture-lifecycle`
- Request: `MYPA-CRL-WP03-CAPTURE-LIFECYCLE-RUNTIME-IMPLEMENTATION-20261001-001`, SHA-256 `929141a4d070768302149ad9315c9f66a5b13d263b6f65f949958477cadaeaea`, Drive file `1EMNqHHxte8xlolP626-KaYq21l6SckUA`
- Authorization: issued 2026-10-01 by the operator in session 257acc32 (campaign brief plus session amendments A1–A5)
- Approved plan: `CRL-WP03-REBOUND-PLAN.md` (rebinds `docs/plans/capture-lifecycle-implementation-plan.md` to `1b9e8aab`), SHA-256 `7ef282b52203debc5f9468e6ed977c298c35b39d0e59174e7f41372da5b513b5`, Drive file `1fcSNVKUXpPTh3UgoRjOQgZnCXZGEiPkM` (readback MATCH; manifest `1JkUEK9XNwX5QAJ569B5E9OndyYs-T7pv`, receipt `1qjowBfKYQr24iDJ8eMobBMuUx0LDOobs`; index registration pending)
- Manager rulings: MR-C01..C19; operator ruling MR-C20 (below)
- Repository: `RMF112018/my-pa`
- Branch: `bf/crl-wp03-capture-lifecycle-20261001`
- Worktree: `/Users/bobbyfetting/my-pa-wt/crl-wp03-capture-lifecycle`
- Base: `origin/main` `1b9e8aabd0a5b811b4649624f452fff6d3bd81d1`, tree `93216e2e26e9a2e6e3d7e683658655ab464a75b9`; Alembic head `1d9b248e7f83` (109 revisions)
- Head / PR: recorded per checkpoint below
- Drive campaign folder: `1sQm3fOCbo4J5W9ELSKRMar6TbDPnXKxn`

## Objective and scope

Implement the accepted Capture archive/restore lifecycle (`docs/specs/capture-withdrawal-v0.1.md`, ADR-003, ADR-005) as one complete runtime slice on one branch and one PR: domain lifecycle, two additive lifecycle tables in one new revision, archive/restore use case, lifecycle read metadata and selectors, processing suspension with lease-generation fencing, publication fences across every Capture-derived authoritative sink, provenance withdrawal disclosure, `capture` Record Event integration, and `capture.archive` / `capture.restore` exposure. Acceptance: CW-AC-01..10 plus the plan's derived criteria. Terminal state: **PR ready for review, NOT MERGED**; the operator merges (A2).

## Prohibitions

No agent-performed merge; no deploy, NAS or production action; no live grant, ChatLLM profile rollout, config or credential change; no live DB write; no hard delete or destructive lifecycle work; no edit to a historical migration; no new Record Event family or second lifecycle feed; no frontend implementation; no edits to PR #287 or any other branch; never touch `~/my-pa`. Exact-set security guards are designed around, not widened; any widening is proposed to the Manager first. Permission denials are STOPs (A5).

## Execution topology (AGENTS.md §8.3)

Manager → one Orchestrator → workers; at most one Orchestrator and one worker active at any moment (reviewers and census agents count as workers); no model above opus; Phase I checkpoints run serially on one opus implementer; foreground, chunked tests; single-guard prove-reds (a green prove-red is a STOP).

## Manager rulings (received 2026-10-01)

The plan is APPROVED as written. Rulings are numbered by the plan's decision IDs (MR-Cnn = D-nn); the plan has no D-15, so MR-C15 records the consumer-contract scope ruling.

- **MR-C01 (D-1): HELD for the operator.** Re-listing the audit capability vocabulary in the new revision trips `tests/architecture/test_record_events_are_never_rewritten.py:157-158` (only one migration may contain `record_event`). Narrowing that guard edits an exact-set security guard, so it is operator-reserved under AGENTS §8.2 and A5. CP-CRL-07 does not start until the ruling arrives. **Ruled by the operator: see MR-C20.**
- **MR-C02 (D-2):** ACCEPTED. A lifecycle event's `record_version` is the Capture's current head version number; the consumer contract states that `record_version` is not a dedup key.
- **MR-C03 (D-3):** ACCEPTED. Create events are unchanged; they do not name the lifecycle fields.
- **MR-C04 (D-4):** ACCEPTED. `lifecycle_state`, `lifecycle_revision` and `archived_at` on read and list; bounded opt-in history via `include_lifecycle_history` on `capture.read`; no third capability.
- **MR-C05 (D-5):** ACCEPTED. The jobs overlay is an ALTER in the new revision plus a runtime projection; `tables.py` does not gain the job columns (historical `1a4c9e77b2d5` builds `capture_jobs` from it).
- **MR-C06 (D-6):** ACCEPTED. Lifecycle mutations lock the root `FOR NO KEY UPDATE`; other admissions `FOR SHARE`, sorted by root; claim excludes paused rows via `pause_cause` with no root lock; T-21 unchanged.
- **MR-C07 (D-7):** ACCEPTED. The ChatLLM profile identity bumps v4 → v5 as a repository constant only. There is no rollout.
- **MR-C08 (D-8):** ACCEPTED. Work evidence: newly supplied `cap_` refs to an archived Capture are fenced; `asrt_` refs to accepted assertions are allowed (independent downstream record, with disclosure); stored refs are never re-validated.
- **MR-C09 (D-9):** ACCEPTED. Reject, defer and mark_unresolved on an archived Capture's proposals remain allowed.
- **MR-C10 (D-10):** ACCEPTED. `reason_category` is the single server token `owner_stated`.
- **MR-C11 (D-11):** ACCEPTED. Report `evidence_subject_id` is treated as an unverified caller string with no overlay; it is listed as a residual in the PR body.
- **MR-C12 (D-12):** ACCEPTED. Restore evaluates then-current eligibility and sets `pause_cause` for still-ineligible work.
- **MR-C13 (D-13):** ACCEPTED. Paused jobs are excluded from the worker-health backlog only; no public shape change.
- **MR-C14 (D-14):** ACCEPTED. The web fixture and `web/README.md` count changes are mechanical.
- **MR-C15 (plan (b), consumer contract):** IN SCOPE. A docs change to `docs/specs/record-event-consumer-contract-v0.1.md`: bootstrap Captures through `capture.list(lifecycle="all")`, and `record_version` is not a dedup key.
- **MR-C16 (D-16):** ACCEPTED. Policy-paused work is re-evaluated after bounded backoff on `next_attempt_at`, then becomes claimable again; no spin.
- **MR-C17 (D-17):** ACCEPTED, with a condition. New derivation from an archived Capture returns `denied/capture_withdrawn`, which must never reveal a foreign root: a foreign or absent root is still `not_found`.
- **MR-C18 (D-18):** ACCEPTED. A `context.prepare` race drops archived items and discloses the drop.
- **MR-C19 (D-19):** ACCEPTED. PR #287's contended count cells are re-derived to current-main truth and the need for its remeasurement is noted.
- **Proceed:** Phase I CP-CRL-01..06 serially on ONE opus implementer, after re-fetching main. Draft PR after CP-CRL-01 is green, titled `feat(capture): archive/restore lifecycle runtime (CRL-WP-03)`. Report each checkpoint. The plan's (c) ledger, (d) census and "no public reader" conclusions are re-verified against code, with file:line, at CP-CRL-05 and CP-CRL-06. STOP before CP-CRL-07 until MR-C01 is ruled (now ruled by MR-C20; continue CP-CRL-07, 08 and Phase T without waiting unless a stop condition fires).
- **MR-C20 (operator ruling on D-1, 2026-10-01): narrow the guard**, applied at CP-CRL-07 in its own commit citing this ruling. In `tests/architecture/test_record_events_are_never_rewritten.py:157` the bare `"record_event" in text` substring becomes a precise match on references to the two feed TABLES only (`record_events`, `record_event_sequences`), so that a capability token such as `'record_events.list'` does not match, while `op.execute` SQL, SQLAlchemy `Table`/`table()` references and `{SCHEMA}.record_events` are still caught. Every other assertion in that test stays byte-identical. Control tests in the same file: (i) synthetic migration text referencing the feed table in raw SQL and as a table object IS detected; (ii) text containing only the `'record_events.list'` literal is NOT detected. Single-guard prove-red, logged: with the narrowing reverted the new revision trips the guard; re-applied, the guard passes and control (i) still detects. A classifier denial of the edit or its test run is a STOP reported to the Manager.

## Checkpoints

| CP | Head | Tree | Evidence |
|---|---|---|---|
| Phase P | `1b9e8aab` | `93216e2e` | Plan approved; main re-fetched 2026-10-01, unmoved |
| CP-CRL-01 domain | `2ba4af45` | `a61dedcc` | FAST 25,969 passed / 74 skipped / 0 failed (26,043 collected); ruff, format, mypy (525 files) clean; prove-red DIGEST-1/2, ALTERNATION-1/2 all red-then-green (manager `work/CP-CRL-01-prove-red.log`); count re-pins in the two pinned plan docs only |
| CP-CRL-02 schema | `1915097e` | `cb6b8f6c` | Revision `0641c354ca85` (single head, 110 files); MIG lanes 810/810; DB capture/pipeline/jobs/schema-enumerating chunks green (full DB tier not run end to end); FAST 25,989 passed / 74 skipped / 0 failed (26,063 collected); ruff, format, mypy (527) clean; prove-red 8/8 red-then-green (`work/CP-CRL-02-prove-red.log`); Orchestrator re-check: 404 FAST + 20 DB passed |
| CP-CRL-03 use case | (this commit) | (this commit) | Lifecycle use case, revise fence, read/list/search selectors, fake transaction buffer. Unit tests: `tests/unit/test_capture_lifecycle_service.py` and `tests/unit/test_capture_lifecycle_record_event_emitters.py` (12 passed with the section-3 module-count guard). Full FAST, the database record-event file, and T-21 were not re-run in this continuation. Module pins moved to 364/654. |
