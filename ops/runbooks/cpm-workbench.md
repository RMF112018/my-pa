# CPM Workbench — schedule evidence plane

**UNEXECUTED / OPERATOR-GATED.** This is a commissioned pre-execution procedure. No command
in a code block below was run against any shared, NAS or production database by this work,
and nothing here is switched on in production. The CPM revisions (`6c2306330ceb`,
`621ef6786c64`) and the code of slices S5a, S5b-1 and S5b-2 are merged on `main` (#344, #345,
#347), as are the Schedule Scenarios slices S6-1, S6-2 and S6-3 (#348, #349, #354; sections 8
and 9). Whether a given database has these revisions applied is read with the existing
Alembic control plane, never assumed from this runbook; the `MY_PA_SCHEDULE_ENABLED` switch is
off by default. What **was** executed: the pre-deploy checks of section 3 ran only against
disposable per-test clones on an isolated scratch PostgreSQL 15 cluster
(`tests/database/test_cpm_workbench_predeploy.py`), and every behaviour cited below ran in the
repository's test tiers on synthetic PDFs. The current-state description is
[`docs/architecture/cpm-workbench.md`](../../docs/architecture/cpm-workbench.md); the decision
record is [`ADR-016`](../../docs/decisions/ADR-016-cpm-workbench-schedule-evidence.md). The
P6 XER import of
[`docs/architecture/schedule-xer-import-contract.md`](../../docs/architecture/schedule-xer-import-contract.md)
under [`ADR-023`](../../docs/decisions/ADR-023-p6-xer-xml-schedule-import.md) is merged
through S7-4b (#392). The S7-5 procedure and evaluation script (section 10) are implemented in
PR #395, and parallel relationships in scenario content v3 (S7-7) are implemented in PR #396.
The operator gates are in section 15 of the contract.

## 1. What the plane does

An operator admits one enrolled schedule PDF version into a Schedule Series of a Project
(`schedule_publications.import`); a `schedule` worker parses it in a contained child process
under the Full-Schedule profile `p6_full_v1`; 6 read capabilities serve publications,
activities, an activity's history across publications and the on-demand change list between
2 publications. Everything is Principal-partitioned, source-bound derived evidence; nothing
is linked to Tasks, Commitments, Constraints or any other domain.

## 2. Deploy order (operator gate 1)

1. **Migration #2 before any code that names a Schedule capability serves a request.**
   `ApplicationService.invoke` audits every call before any handler, switch on or off. Code
   carrying the 7 Schedule names against a database without `621ef6786c64` fails such a call
   closed (`internal_error`) at the audit insert, because the old `capability_is_known` CHECK
   refuses the name.
2. **An audited probe makes the downgrade refusal permanent.** Once `621ef6786c64` is
   applied, any audited call naming a Schedule capability or purpose — including a `denied`
   or `unsupported` probe with the switch off — writes an `audit_events` row, and audit rows
   are never deleted. From then on the downgrade of `621ef6786c64` refuses
   (`restrict_violation`, "cpm workbench vocabulary is in use"). A `schedule` heartbeat row
   has the same effect. This is by design; decide on the downgrade path **before** the first
   probe.
3. **Lock windows.** `6c2306330ceb` takes `SHARE` then `ACCESS EXCLUSIVE` on
   `knowledge.enrollments` and `knowledge.source_object_versions` (2 support uniques) and
   `SHARE ROW EXCLUSIVE` on `projects`, `enrollments`, `enrollment_objects` and
   `source_object_versions` (4 new foreign keys), all held to commit. `621ef6786c64` takes
   `ACCESS EXCLUSIVE` and a validating scan on `knowledge.audit_events` and
   `knowledge.worker_heartbeats`, held to commit (residual U2-06: the production
   `audit_events` row count is unknown here). Read P3 first, take a backup, choose a quiet
   window for the gateway and every worker. Both revisions set `lock_timeout = '10s'`
   locally: a `55P03` (`lock_not_available`) abort rolls the whole revision back and is
   clean and retryable in a quieter window. Never raise the timeout without a new review.
4. Apply both revisions with the existing Alembic control plane, then run the `after`
   checks of section 3. Only then may code naming the Schedule capabilities serve.

## 3. Pre-deploy gates (S5b-1 section 9.3 plus migration #2; operator gate 2)

`ops/postgres/cpm_workbench_predeploy_check.py` connects with `MY_PA_DATABASE_URL`, opens one
transaction whose first statement is `SET TRANSACTION READ ONLY`, issues only catalog
`SELECT`s (`src/my_pa/infrastructure/database/cpm_workbench_predeploy.py`, enforced by
`tests/security/test_cpm_workbench_security.py::test_predeploy_sql_is_select_only`), rolls
back, prints one line per check and never a connection string. Exit 0 = no stop, 1 = a stop
(or settings refused), 2 = usage error. Run it as the role the gateway and worker use.

```sh
# Before applying 6c2306330ceb (and again before 621ef6786c64 if they are deployed apart).
.venv/bin/python ops/postgres/cpm_workbench_predeploy_check.py --phase before
# After both revisions; pass the P5 digest the before run printed.
.venv/bin/python ops/postgres/cpm_workbench_predeploy_check.py --phase after \
    --before-acl-sha256 <digest>
```

| Check | Phase | Reads | Stop when |
|---|---|---|---|
| P0 read-only | both | `transaction_read_only` | not `on` |
| P1 default privileges | before | `pg_default_acl` entries for tables | an entry (global, or in schema `knowledge`) grants to `PUBLIC`, `my_pa_mcp_ro` or `my_pa_mcp_rw` — removing it is a separate operator-authorized change, never part of a revision; judge whether its role is the migrating role |
| P2 primary keys | before | `pg_constraint` | `knowledge.enrollments` or `knowledge.source_object_versions` lacks a single-column PK |
| P3 lock sizing | before | `pg_class.reltuples`, `pg_relation_size` of `enrollments`, `source_object_versions`, `audit_events`, `worker_heartbeats` | never (reported for the quiet-window decision) |
| P4 runtime-role reach | before | `current_user`, `session_user`, owner and privileges on `knowledge.record_links` | the connecting role neither owns nor is granted the lineage table: a stop for **enabling** the plane (the new tables would be unreachable), not for the schema-only deploy. If the Record Event roles (`my_pa_runtime`, `my_pa_migrator`, `my_pa_owner`) are in use and the runtime role is not the owner, stop here |
| P5 ACL snapshot | both | SHA-256 over `relacl` of `enrollments` and `source_object_versions` | after ≠ before, or no before digest given |
| P6 no extra grant | after | `has_table_privilege` for `public` and each existing MCP profile role on the 7 tables | any privilege held, or a CPM table absent |
| P7 vocabulary at head | after | `pg_get_constraintdef` of `capability_is_known`, `purpose_is_known`, `worker_plane_is_known` | a Schedule capability, purpose or the `schedule` plane missing |
| P8 runtime reach | after | `has_table_privilege(current_user, …)` | the role lacks `SELECT`/`INSERT` on any of the 7 tables, or `UPDATE` on publications, jobs, parser runs or rows |

Any deviation is a stop and is reported. Neither revision grants or revokes anything; no
check repairs anything.

## 4. Operator gates (none is performed by an agent)

1. **Deploy order** — section 2.
2. **Pre-deploy checks** — section 3, before and after both revisions.
3. **The switch.** `MY_PA_SCHEDULE_ENABLED` stays `false` everywhere but tests until the
   operator decides otherwise. With it off nothing Schedule-related is served, published,
   planned or runnable (`apps/worker.py run --plane schedule` exits 2 with
   `plane schedule disabled`). Turning it on or off changes no row; jobs queued while it was
   off are claimed only by a schedule worker running with it on.
4. **Import is operator-only and attested-local.** Only the CLI (`apps/cli/invoke.py`) and the
   HTTP gateway stamp an operator surface (the gateway stamps it on every `invoke` request it
   accepts, so any caller the gateway authenticates as the operator — in `entra` mode an
   Entra-authenticated operator — may import; the S3.1 D-16 precedent); stdio MCP, any unattested local caller and every
   remote client are refused (`denied` / `unsupported`). Every import needs an operator
   **source-admission decision**: which source is designated for schedule PDFs (open decision
   **OD-06**) and an enrollment whose media allowlist admits `application/pdf`. No source is
   designated by this change.
5. **Runtime for the schedule worker** (residuals U2-01, U2-10): a network-less container,
   a dedicated UID, a read-only root filesystem, and no write access to any source root. The
   child's rlimits and audit hook do not stop native code from raw socket calls, from
   truncating/unlinking/renaming files the UID may modify, or from forging a well-formed frame
   of fabricated rows.
6. **Pre-merge Linux CI gate (U2-12).** macOS cannot lower `RLIMIT_AS`, so these tests skip on
   the implementation host and are **CI-only, not executed on the implementation host**. The
   PR's ubuntu CI log (the FAST `validate` shards) must show each **executed and passed, not
   skipped**:
   - `tests/unit/test_schedule_parser_isolation.py::test_child_address_space_has_headroom[largest_golden]`
     and `[bounds_maximal]` (each prints its measured `VmPeak`; each requires 2 × `VmPeak` ≤ 1 GiB)
   - `tests/unit/test_schedule_parser_isolation.py::test_largest_golden_parses_under_production_limits[largest_golden]`
     and `[bounds_maximal]`
   - `tests/unit/test_schedule_parser_isolation.py::test_benign_document_parses_under_the_bomb_cap`
   - `tests/unit/test_schedule_parser_isolation.py::test_decompression_bomb_fails_closed_on_linux`
   - `tests/unit/test_schedule_parser_isolation.py::test_child_rlimits_are_set[RLIMIT_AS-expected4]`

   `bounds_maximal` is a synthetic generated at test time at the page cap (250 pages) with
   23,250 rows (93 % of the 25,000-row cap) and 96 % of the character cap. **Risk:** FR7's
   linear extrapolation from macOS RSS gives about 560 MiB at 25,000 rows, above the 512 MiB
   the 2× rule allows; on macOS (no cap, RSS not `VmPeak`) the bounds-maximal child peaked at
   440 MiB. Both are observations, not Linux measurements. If either headroom node fails, the
   1 GiB cap is re-derived as at least 2 × the reported `VmPeak` (and no more than any
   container memory limit), or the admitted bound is reduced (R2 section 36), **before merge**.
   The cap is not changed on an extrapolation alone.
   The decompression bomb's Linux failure code is pinned to the measured member of
   {`bounds_exceeded`, `parser_exception`} only once a CI run reports it.
7. **ChatLLM and remote.** Any `profile-apply` to `chatllm-data-v11` and any remote grant on a
   Schedule read. Import is `CONTROL_PLANE_EXCLUDED`; an active grant on it is reported as
   `UNEXPECTED_CONTROL_PLANE_GRANT`.
8. **Real corpus.** The authorized real-schedule evaluation (R2 section 39, S5a U-01) has not
   been run: no real PDF exists in the repository.
9. **Not implemented.** XER/XML import (lineage WP-05B), supplemental/narrative/adjustment
   evidence (R2 sections 26–28) and cross-domain links (R2 section 33).

## 5. Running it once enabled (UNEXECUTED)

```sh
# Worker: the schedule plane needs the switch and a lease of at least 300 s.
MY_PA_SCHEDULE_ENABLED=true .venv/bin/python apps/worker.py run --plane schedule --lease-seconds 300
# Import: CLI only, as the operator, with an explicit role and an idempotency key.
MY_PA_SCHEDULE_ENABLED=true .venv/bin/python apps/cli/invoke.py schedule_publications.import [options]
```

**Import roles since Schedule Scenarios S6-2 and S6-3** (schedule scenarios contract
sections 12.2, 14.9 and 15; S6-3 is merged, #354): role `reference` and baseline kind
`working` are retired and refused; `schedule_publications.list` refuses the filter
`publication_role=reference` with `invalid_request(PUBLICATION_ROLE)`; a role-`baseline`
import needs the section 12.3 approval fields and is refused while the scenario plane is not
effective, so with only `MY_PA_SCHEDULE_ENABLED` on, import role `update`.

`capabilities.get` then reports the `schedule` plane's backlog, dead-lettered count and
heartbeat, which degrade readiness exactly as the other planes do.
`schedule_publications.read` shows status, counts, issue counts by safe code, the job's
`state`, `attempt_count` and `last_error_code` (one of the 11 public codes) and every parser
run. Nothing logs: there is no logging or metrics emitter in the job plane (contract E-05),
and the child's `stderr` is discarded.

A deterministic failure (corrupt, encrypted or image-only PDF, wrong layout, a bound, a
budget, a native crash, a version change) completes the job and leaves the publication
`failed` or `review_required`; a transient one (provider unavailable, spawn failure, external
`SIGKILL`, invariant breach) releases the job for retry and, after 3 attempts, reads as
effective `failed`.

## 6. Residuals the operator owns

| ID | What | Action |
|---|---|---|
| S5b-1 U-06 | The table owner or a superuser can disable the F1–F9 triggers | role separation (operator-gated) |
| S5b-1 U-09, U2-09 | A `failed`, effective-failed or `review_required` publication of source version V blocks V in its Series for good: a new key replays it or conflicts (`conflict(source_version_id)`), even after transient exhaustion, a budget failure after a legitimately slow persistence, or a parser fix. Only a new source version (with `supersedes_publication_id`) or another Series admits it | document per incident; choose the new version or Series deliberately |
| S5b-1 U-10 | CPM foreign keys are `RESTRICT`: once a publication exists, deleting its `sources` or `source_objects` row fails as a whole | a future retention or erasure design must handle CPM rows first |
| U2-01, U2-10 | native socket calls, non-growing file effects and forged frames are not prevented in the child | gate 5 |
| U2-02 | on macOS a bomb is bounded only by CPU and wall time | production and CI are Linux |
| U2-03 | a worker killed by `SIGKILL` leaves its child running until `RLIMIT_CPU` or a broken pipe ends it (about 152 s CPU at most) | accepted, bounded |
| U2-04 | decoding a maximal frame (cap 128 MiB) can raise worker RSS by several hundred MiB; not measured | size the worker container for it |
| U2-05, U2-11 | persistence of 25,000 rows plus canonicalization was measured at 18.6 s on the implementation host, inside the 60 s reserve; a wall/CPU failure on a re-claim fails a publication whose parse is already stored as a `parsed` run | on a production miss, reduce the admitted bound (R2 section 36) |
| U2-06 | migration #2's validating scan of `audit_events` under `ACCESS EXCLUSIVE` | section 2 step 3 |
| U2-07 | a marker-only Start/Finish change on an equal date is not a v1 change kind | future delta version |
| U2-08 | parser and persistence durations are not recorded | future observability design |
| U2-12 | `RLIMIT_AS` 1 GiB is provisional; the bounds-maximal case may need more than half of it | gate 6 |
| U2-13 | a tiny hostile page (2,610 bytes: 200,000 text-show operations with no positioning) drives PDFium to an early call boundary, then one long native call the cooperative deadline cannot interrupt; the child is ended from outside at the wall (`RLIMIT_CPU` or the parent kill, at most about 152 s of worker time per admission), or stops itself at the early boundary if its deadline has already passed, and the publication fails `processing_budget_exceeded` on its one attempt, no retry | accepted; the import is operator-only — admit only documents from the designated source |
| U2-14 | `tests/ci_shard_weights.json` was weighed on macOS, where the Linux memory tests skip | re-weigh both lanes with `python -m tests.ci_shard weigh` from the first ubuntu CI JUnit of the PR |
| S5a U-01 | no real corpus evaluation | gate 8 |

## 7. Not run, and why

Every command in sections 3 and 5 is unexecuted against anything but the disposable scratch
clones named above: production, NAS and shared databases are outside agent reach, and this
change authorizes no migration, grant, `profile-apply`, source designation, switch change or
deployment.

## 8. Schedule Scenarios revision A (S6-2, schema only)

**UNEXECUTED / OPERATOR-GATED.** Revision `2a90f91dd786` (schedule scenarios contract
[section 14](../../docs/architecture/schedule-scenarios-contract.md), revision A) adds the 11
plane tables, retires the `reference` publication role and the `working` baseline kind,
widens the 6 `record_links` CHECKs from the lineage storage vocabulary and adds trigger G10 on
`schedule_publications`. Nothing in it is public: the capabilities, switch and ChatLLM surface are S6-3's (merged,
#354; section 9), so with revision A alone and the S6-3 switch off the plane is **inert**.
Its pre-deploy checks ran only against disposable per-test clones on an isolated scratch
PostgreSQL 15 cluster (`tests/database/test_schedule_scenarios_predeploy.py`); nothing here
was run against a persistent database.

1. **Prerequisites.** `6c2306330ceb` and `621ef6786c64` are applied first (revision A chains
   from `621ef6786c64`). A database holding a publication with role `baseline` or `reference`
   cannot upgrade (S6-U13: the upgrade refuses with `restrict_violation`); rebuild it rather
   than editing rows.
2. **Quiet window.** Phase C restates the 6 `record_links` CHECKs in one `ALTER TABLE` under
   `ACCESS EXCLUSIVE`, held to commit: every lineage read and write waits (`records.lineage*`,
   `records.associations.*`, the `issues.*` close gate and timeline, the ChatLLM and remote
   lineage reads). Phase A holds `ACCESS EXCLUSIVE` on `schedule_publications`, and the 8 new
   foreign keys `SHARE ROW EXCLUSIVE` on `schedule_publications` and `schedule_series`. Pause
   lineage traffic, the schedule import and every `schedule` worker for the window. Take a
   backup first.
3. **Expected `record_links` window and go/no-go.** On the scratch cluster (contract section
   14.14: PostgreSQL 15.15, Apple M4 Pro, NVMe, a freshly loaded and cached table) phase C
   took 0.84 s at 24.8 MB and 8.40 s at 248.3 MB of `record_links` heap: linear at about
   **34 ms per MB**. The input is Q3's `record_links` **`bytes=`** (`pg_relation_size`,
   exact); `rows~` is only an estimate, and `rows~-1` means the table was never vacuumed or
   analyzed, so read `bytes=` alone. Compute
   `T = bytes / 1,048,576 × 34 ms × 10`, where 10 is the stated host factor for the
   unmeasured server host (a NAS, slower disk, cold cache; S6-2-U01).
   - **Go** when `T ≤ 2 s` (that is, `bytes=` at most about 6,000,000).
   - **Otherwise**, before the real upgrade, the operator restores a copy of the database on
     the server host itself and runs the upgrade there once, timed (the scratch-copy dry run;
     never against the live database). **Go** only when that measured upgrade takes at most
     2 s; otherwise stop and review.

   This window is the validating pass under `ACCESS EXCLUSIVE`; it is not governed by the
   10 s `lock_timeout`, which bounds only the wait to acquire each lock. A lineage call that
   was not paused waits for the lock acquisition plus the whole pass, bounded only by its own
   `statement_timeout` (30 s on the gateway and worker engines): past that it fails with
   `57014` and the caller retries.
4. **Before:** run the checks below as the **runtime role the gateway and worker connect as**
   (Q4 and Q8 judge `current_user`; Q4 also reports the owner of `record_links`, the
   migrating role). Every `before` check must hold; keep Q5's digest.
5. **Upgrade** with the existing Alembic control plane. A `55P03` (`lock_not_available`)
   abort leaves the database at `621ef6786c64` and is clean and retryable in a quieter
   window; never raise the 10 s timeout without a new review.
6. **After:** run the `after` checks with the `before` Q5 digest. Every check must hold.
7. **Downgrade** refuses (`restrict_violation`, "schedule scenarios rows exist") while any
   plane table holds a row, any `record_links` row names an S6 family (`schedule_publication`,
   `schedule_activity`, `schedule_baseline`, `scenario`, `scenario_version`,
   `scenario_output`) or relation (`concerns`, `delays`, `mitigates`), or any publication has
   `baseline_kind = 'approved_update'`. Before any such row exists, it restores every CHECK
   text exactly.
8. **No grant, revoke, switch or capability is part of this step.** The revision is
   grant-free: the new tables and the refusal table's identity sequence are owned by the
   migrating role, exactly as every S1-S5 table. The ChatLLM, switch and grant gates are
   S6-3's runbook section. When S6-3 enables CPM runs, each concurrently computing Principal
   holds at most 1 extra server connection per process outside the gateway's pool of 5 (the
   compute lease, S6-2-U12): count it against `max_connections`.

```sh
# Before revision 2a90f91dd786, as the runtime role.
.venv/bin/python ops/postgres/schedule_scenarios_predeploy_check.py --phase before
# After it; pass the Q5 digest the before run printed.
.venv/bin/python ops/postgres/schedule_scenarios_predeploy_check.py --phase after \
    --before-acl-sha256 <digest>
```

The script (`src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py`) opens one
transaction whose first statement is `SET TRANSACTION READ ONLY`, issues only `SELECT`s and
always rolls back. Every statement reads catalogs except Q2's one operator-wide, cross-Principal
`EXISTS` boolean over `schedule_publications`, which returns no row and no identifier. Exit 0
= no stop, 1 = a stop (or settings refused), 2 = usage error; no line carries a connection
string.

| Check | Phase | Reads | Stop when |
|---|---|---|---|
| Q0 read-only | both | `transaction_read_only` | not `on` |
| Q1 default privileges | before | `pg_default_acl` entries for tables and sequences | an entry (global, or in `knowledge`) grants to `PUBLIC`, `my_pa_mcp_ro` or `my_pa_mcp_rw`; removing it is a separate operator-authorized change |
| Q2 retired roles | before | the 7 S5 tables, then `EXISTS` a `baseline`/`reference` publication | a table absent, the probe unreadable by this role, or `true` |
| Q3 lock sizing | before | `reltuples`, `pg_relation_size` of `record_links`, `schedule_publications`, `schedule_series` | never (step 3's input) |
| Q4 runtime-role reach | before | `current_user`, owner and privileges on `record_links` | the role neither owns nor is granted it |
| Q5 ACL snapshot | both | SHA-256 over `relacl` of `record_links`, `schedule_publications`, `schedule_series` | after ≠ before, or no before digest |
| Q6 no extra grant | after | `has_table_privilege` for `public` and each existing MCP role on the 11 tables; the refusal sequence's `relacl` | any privilege, or the sequence not owner-only |
| Q7 vocabulary at head | after | `pg_get_constraintdef` of `a_record_link_pair_is_admitted`, `a_record_link_from_family_is_known`, `a_schedule_publication_role_is_known` | an S6 relation or family missing, or `reference` still admitted |
| Q8 runtime reach | after | `has_table_privilege(current_user, …)` | `SELECT`/`INSERT` lacking on any of the 11 tables, `UPDATE` lacking on `schedule_scenario_write_requests`, or `SELECT` lacking on `smoke_fixture_retirements` when installed |
| Q9 plane objects | after | `pg_class`, `pg_proc`, `pg_trigger` | a plane table, one of the 15 plane functions, or trigger G10 absent |

## 9. Schedule Scenarios capabilities, switch and client exposure (S6-3)

**UNEXECUTED / OPERATOR-GATED. Nothing in this section was run against any real system.**
S6-3 (schedule scenarios contract
[section 15](../../docs/architecture/schedule-scenarios-contract.md), runbook plan section
15.17) adds 26 capabilities (6 client writes, 4 operator baseline decisions, 16 reads) and 3
purposes, served only while `MY_PA_SCHEDULE_ENABLED` **and**
`MY_PA_SCHEDULE_SCENARIOS_ENABLED` are both on; revision B `b77334135653` (audit vocabulary
only); the ChatLLM data profile `chatllm-data-v13`; and the 6 Schedule lineage families. The
package's executed results are in contract section 15.19. Every command below is
operator-run; an agent performs none of them.

1. **Order.**
   1. S6-2 revision A (`2a90f91dd786`, section 8) is applied. The operator reports
      production at `4c37731671fc`, which includes it; this runbook did not verify it.
   2. **Revision B** (`b77334135653`, `down_revision = "4c37731671fc"`). Take a backup. It
      restates the 2 audit CHECKs (`capability_is_known`, `purpose_is_known`) on
      `knowledge.audit_events` under `ACCESS EXCLUSIVE`, held to commit: every authorized
      request writes `audit_events`, so **the gateway pauses** for the window (and so does
      every worker that audits). Run Q0 and Q10 before (`--phase before`), and Q0 and Q11
      after (`--phase after`), with the commands below. A `55P03` (`lock_not_available`)
      abort leaves the database at `4c37731671fc`; it is clean and retryable in a quieter
      window. **Go/no-go:** the scratch-cluster window (section 15.19: 0.68 s at 100,000
      rows / 16.7 MB and 1.54 s at 1,000,000 rows / 167.2 MB, upgrade wall clock) scaled by
      Q10's `reltuples` and `pg_relation_size` on the production host, times the section
      14.14 host factor of 10. **Go** when that is at most 2 s; otherwise run the upgrade
      once on a restored copy on the server host, timed, and go only when it takes at most
      2 s.
   3. Deploy the S6-3 build with `MY_PA_SCHEDULE_SCENARIOS_ENABLED` **absent** (the plane is
      then off: every scenario name is `unsupported`, the 6 lineage families are withheld,
      and v13 desires exactly the v12 set).
   4. Set `MY_PA_SCHEDULE_ENABLED=true` (if not already) and
      `MY_PA_SCHEDULE_SCENARIOS_ENABLED=true` on the gateway **and** on the schedule worker
      (the worker hands `scenario_plane_effective` to the auto-match hook only with both);
      restart both.

   ```sh
   # Before revision b77334135653, as the runtime role (Q0-Q5 and Q10; read Q10's report).
   .venv/bin/python ops/postgres/schedule_scenarios_predeploy_check.py --phase before
   # After it; pass the Q5 digest the before run printed (Q0, Q5-Q9 and Q11).
   .venv/bin/python ops/postgres/schedule_scenarios_predeploy_check.py --phase after \
       --before-acl-sha256 <digest>
   ```

2. **Commissioning (operator-run, not run).** For each ChatLLM client run `profile-diff`,
   then `profile-plan`, then `profile-apply` at `chatllm-data-v14` (v14 with
   `MY_PA_FILES_WORKSPACE_ROOT` unset desires exactly the v13 set; the
   [`managed-knowledge-context.md`](managed-knowledge-context.md) form):

   ```sh
   python apps/cli/remote_mcp.py profile-diff --oauth-client-id "$CLIENT" --scope my-pa.read \
       --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v21
   python apps/cli/remote_mcp.py profile-plan --oauth-client-id "$CLIENT" --scope my-pa.read \
       --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v21
   # operator-gated; only after the go/no-go below
   python apps/cli/remote_mcp.py profile-apply --oauth-client-id "$CLIENT" --scope my-pa.read \
       --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v21 --apply
   ```

   **Go/no-go is a set rule, not a count** (R10-F05, R10-N02): (i) the diff shows **no
   removal** (nothing revoked or replaced); (ii) every add is in {the 22 below} ∪ {the 6
   S5b-2 reads `schedule_series.list`, `schedule_publications.list`,
   `schedule_publications.read`, `schedule_activities.list`, `schedule_activities.history`,
   `schedule_changes.list` (purpose `schedule_read`)} ∪ {the 11 `chatllm-data-v12` Reports
   names `reports.publish`, `reports.update`, `reports.history`, `reports.archive`,
   `reports.delete`, `reports.restore`, `reports.transfer.begin`, `reports.transfer.append`,
   `reports.transfer.finalize`, `reports.transfer.abort`, `reports.transfer.read_chunk`};
   (iii) all 22 are present. Anything else is a stop. Expected cases: **22** adds (the client
   holds the 6 S5b-2 reads and was applied at v12), **28** (never profiled with
   `MY_PA_SCHEDULE_ENABLED` on; production today: that switch is absent), **33** (holds the
   6 reads, never applied at v12: the Reports commissioning still pending in production),
   **39** (neither). v13 with `MY_PA_SCHEDULE_SCENARIOS_ENABLED` off desires exactly the v12
   set, so a pending Reports commissioning uses v13 after this build.

   The 22: writes `schedule_scenarios.create`, `schedule_scenario_versions.create`,
   `schedule_cpm_runs.create`, `schedule_scenario_outputs.record`,
   `schedule_baselines.propose`, `schedule_baselines.withdraw` (purpose
   `schedule_analysis_authoring`, `--write`); reads `schedule_scenarios.list`,
   `schedule_scenarios.read`, `schedule_scenario_versions.read`,
   `schedule_scenario_versions.activities`, `schedule_scenario_versions.relationships`,
   `schedule_scenario_versions.changes`, `schedule_cpm_runs.read`,
   `schedule_cpm_runs.activities`, `schedule_scenario_outputs.list`,
   `schedule_scenario_outputs.read`, `schedule_series.current`,
   `schedule_series.match_decisions`, `schedule_baselines.list`, `schedule_baselines.read`,
   `schedule_baselines.governing`, `schedule_baselines.compare` (purpose
   `schedule_analysis_read`).

   For a non-ChatLLM remote client (the ChatGPT connector), grant the same 22 with
   `apps/cli/remote_mcp.py grant` (one per name, `--write` for the 6 writes) and set its
   writes flag (`set-client-writes --writes-enabled`); grant the S5b-2 Schedule reads too if
   the client lacks them. The Schedule lineage families need only the lineage grants the
   client already holds (plus each family's read grant to see that family's records).
   **Never** grant the 4 operator names `schedule_baselines.approve`,
   `schedule_baselines.reject`, `schedule_baselines.revoke`,
   `schedule_baselines.set_governing`: an active grant on one is
   `UNEXPECTED_CONTROL_PLANE_GRANT`, and they are never remotely published.

3. **Read-only checks.** Q0-Q11 (`ops/postgres/schedule_scenarios_predeploy_check.py`) as the
   runtime role (step 1). After enablement, `capabilities.get` (operator) lists the 26 as
   available, and a granted remote client's `tools/list` (or `my_pa.describe` with feature
   `schedule` on the compact facade) shows the 22 and never the 4. Neither changes anything.
4. **Measurements the operator owns.** S6-2-U07: the maximal matcher read under J on the
   server host, by an intake import against a Project with 50 Series (stop if it approaches
   the 30 s `statement_timeout`). S6-2-U12: count 1 extra connection per concurrently
   computing Principal per process against `max_connections`. S6-U06/U16: CPM timing and
   calendar cache memory on the server host.
5. **Rollback.** Turn the switches off (no row changes; every scenario read and write is
   `unsupported`, the 6 lineage families are withheld, and existing links to them stay
   confirmable and endable). Downgrade revision B only while no `audit_events` row names a
   plane capability or purpose: the downgrade refuses (`restrict_violation`) otherwise.
   Never delete audit history to make it pass.
6. **Warnings.** Revoking a Baseline is final for its publication, which can never be
   approved again (S6-U15). A change set larger than about 740 KiB cannot be sent
   (`MAX_REQUEST_BYTES` 762,288 bytes); clients split it across versions (S6-3-U01), and a
   very large criticality or Monte Carlo output may not fit at all.
7. **Operator-gated and not performed by an agent:** revisions A and B, both switches,
   every `profile-apply` and `grant`, the measurements, and the deployment.

## 10. P6 XER/XML schedule import (S7)

**UNEXECUTED / OPERATOR-GATED. Nothing in this section was run against any real system.**
The P6 XER import of
[`schedule-xer-import-contract.md`](../../docs/architecture/schedule-xer-import-contract.md)
(cited "contract §n" here) under
[`ADR-023`](../../docs/decisions/ADR-023-p6-xer-xml-schedule-import.md) is merged through
S7-4b (#384, #386, #387, #389, #391, #392); S7-5 adds this procedure and the evaluation script.
The XML format (`p6_xml_v1`, contract §16) and re-capture (S7-6, undecided) are not built:
`format` `p6_xml` answers `unsupported(format)`. Every command below is operator-run; an
agent performs none of them. The operator gates are contract §15 (G-1 to G-10).

### 10.1 What it is

A client admits one P6 XER export that already sits in the files workspace
(`schedule_publications.import_p6`, a client-usable additive write); the bytes are snapshotted
into the database at admission, so the worker never reads the mutable workspace path. The
`schedule` worker parses the snapshot in the contained child under profile `p6_xer_v1`
(catalogue `p6-field-catalogue-v1`), stores typed projects, WBS, activities, relationships and
calendars, the captured optional fields and the observed-field statistics, and links each
activity to its Stable Activity by exact Activity ID (`task_code`) inside the Series. The reads
serve it; the P6 delta `cpm-workbench-p6-delta-v1` compares 2 publications of a Series; a
Scenario's version 1 can be built from a P6 publication (contract §11.5).

### 10.2 Prerequisites

1. **Schema.** The schedule plane revisions (sections 2, 8 and 9 above) and the P6 storage
   revision `d8383150cf72` (the 7 P6 tables and the audit vocabulary for the 7 names) are
   applied; read it with the existing Alembic control plane
   ([`postgres-operations.md`](postgres-operations.md)), never from this runbook. **No further
   migration**: S7-3, S7-4a, S7-4b and S7-5 add none. The downgrade of `d8383150cf72` refuses
   (`restrict_violation`) once any P6 table holds a row, any publication is not `pdf`, or any
   audit row names a P6 capability or purpose (contract §8.3): decide on it before the first
   audited probe, as in section 2 step 2.
2. **Build.** An image from merged `main` carrying S7-4b or later, deployed with
   `MY_PA_SCHEDULE_P6_ENABLED` **absent** first (gate G-4). The deploy and recreate steps are
   those of [`gateway-operations.md`](gateway-operations.md),
   [`worker-operations.md`](worker-operations.md) and
   [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md); the combined release sequence is
   kept outside this repository and is not repeated here.
3. **Files workspace.** The plane of [`files-workspace.md`](files-workspace.md) is
   commissioned (an export reaches the workspace by `files.upload.*` or `files.write_text`).

### 10.3 Switches, worker, quotas

1. **Order.** `MY_PA_SCHEDULE_ENABLED` → `MY_PA_SCHEDULE_P6_ENABLED` →
   `MY_PA_SCHEDULE_SCENARIOS_ENABLED`. The P6 switch is effective only with the schedule
   switch on and an unrestricted composition; off, the 7 names are absent everywhere, each
   handler answers `unsupported`, and the worker fails a `p6_*` job closed as a transient
   `unavailable` without parsing. A Scenario over a P6 publication additionally needs the
   scenario switch (section 9). Set each on the gateway **and** on the schedule worker, then
   restart both (gate G-5). Turning a switch on or off changes no row.
2. **Worker.** The same `schedule` plane as PDFs, with a lease of at least 300 s:

   ```sh
   MY_PA_SCHEDULE_ENABLED=true MY_PA_SCHEDULE_P6_ENABLED=true \
       .venv/bin/python apps/worker.py run --plane schedule --lease-seconds 300
   ```

3. **Quotas** (contract §7.7, placeholders kept by operator decision 2026-11-23).
   `MY_PA_SCHEDULE_P6_SNAPSHOT_QUOTA_BYTES` (default 8 GiB, 1 byte to 1 TiB) bounds the
   retained snapshot bytes per Principal; an import past it answers
   `rate_limited(storage_quota)` and writes nothing; identical bytes are stored once per
   Principal. Import budgets: at most 60 imports an hour and 500 a day per Principal
   (`rate_limited`). File cap 16 MiB (`unsupported(max_bytes)` before any byte is read).

### 10.4 Grants and ChatLLM (gate G-6)

The 7 names: writes `schedule_publications.import_p6` (purpose `schedule_p6_import`) and
`schedule_p6_fields.set_captured` (purpose `schedule_p6_configuration`), both granted with
`--write` and served only to a client with `writes_enabled` (`set-client-writes
--writes-enabled`); reads `schedule_p6_fields.available`, `schedule_p6_activities.list`,
`schedule_p6_relationships.list`, `schedule_p6_calendars.list`,
`schedule_p6_field_values.list` (purpose `schedule_read`). None is operator-only; the remote
principal is the operator, so a grant is the operator's admission decision per client. For a
ChatLLM client the 7 are `DATA_CONDITIONAL` under the prerequisite `SCHEDULE_P6`, from data
profile `chatllm-data-v19` onwards: converge it on the current profile with the
`profile-diff` / `profile-plan` / `profile-apply` form of section 9 step 2 (with the P6 switch
off a profile desires exactly the previous profile's set). For another remote client grant
each name with `apps/cli/remote_mcp.py grant` as in
[`files-workspace.md`](files-workspace.md) section 5.

### 10.5 How a client imports

1. Upload the export into the workspace, then read its version token and digest:
   `files.stat` with `{"workspace_id": "<workspace>", "path": "<dir>/<export>.xer",
   "include_sha256": true}` answers `version` (`fv1_…`) and `sha256`.
2. Before the first import of a new project, the operator runs the conformance script on the
   file (section 10.10); `fail` stops the import.
3. Call `schedule_publications.import_p6` with exactly one of `series_id`, `series_name` or
   `series_auto` (placeholders, never real values):

   ```json
   {
     "project_id": "<prj_…>",
     "series_name": "<series name>",
     "workspace_id": "<workspace>",
     "path": "<dir>/<export>.xer",
     "expected_version": "<the fv1_… version from files.stat>",
     "expected_sha256": "<the 64-hex sha256 from files.stat>",
     "format": "p6_xer",
     "idempotency_key": "<client key>"
   }
   ```

   Optional: `accept_project_identity_change` (default `false`) and
   `supersedes_publication_id`.

   **P6 update files exported as separate project copies.** Such a copy carries another P6
   project id, project short name and project GUID than the earlier exports, so the contract
   §11.1 identity rule finds no shared identity and the import becomes `review_required`
   (`p6_project_identity_changed`). Every update import of such a copy into the same Series
   therefore needs `"accept_project_identity_change": true` **on its first call**: the check
   compares with the Series' earlier `complete` publications, and an accepted copy adds yet
   another identity, so the next copy needs the flag again. The flag waives the only guard
   against importing another project into the Series: confirm first with the evaluation
   script (section 10.10, `--assume-same-project`: `same_project` `false` and a delta with
   few `added` and `removed` activities). The very first import of a Series is never a
   change. A file that moved after the stat answers
   `conflict(expected_version)`, other bytes `conflict(expected_sha256)`, a Series holding a PDF
   publication `conflict(series_format)`; the same bytes already in the Series answer
   `already_present: true` (also for a failed publication of those bytes: a retry needs a
   re-export or another Series). The answer names the publication; the parse runs on the
   worker.

### 10.6 Statuses

| Status | Meaning |
|---|---|
| `queued`, `processing` | admitted; the worker has not finished |
| `complete` | parsed; non-fatal issues are listed (at most 10,000) with their counts by code |
| `review_required` | `p6_project_identity_changed`: no earlier complete P6 publication of the Series shares the project short name or the GUID (contract §11.1); it is never served by the P6 reads and never becomes the identity reference. The same bytes cannot be imported again into that Series (content idempotency answers `already_present: true` with this publication), so set `accept_project_identity_change: true` on the first import of each update copy (section 10.5); after a `review_required`, re-export the file from P6 (new bytes) and import it with the flag and a new `idempotency_key`, or use another Series |
| `failed` | a fatal issue of contract §5.5: `p6_encoding_invalid`, `p6_header_invalid`, `p6_structure_invalid`, `p6_record_width_mismatch`, `p6_bound_exceeded`, `p6_required_table_missing`, `p6_required_field_missing`, `p6_multiple_projects`, `p6_value_invalid` or `p6_unknown_enum_value` on an R field, `p6_duplicate_activity_id`, `p6_reference_dangling`, `p6_wbs_cycle` |

`last_error_code` stays one of the 11 public codes; the `p6_*` codes are the publication's
issues. A transient failure (switch off, worker unavailable) releases the job for retry and,
after 3 attempts, reads as effective `failed`.

### 10.7 Reading the results

- `schedule_publications.read` carries the `p6` block (project identity, export version, data
  date, settings, counts, `source_format`, `capture_event_id`, `encoding`,
  `catalogue_version`); `schedule_publications.list`, `schedule_activities.list` and
  `schedule_activities.history` serve P6 publications too.
- The 5 P6 reads (section 10.4) page at 25 by default (1 to 100), take at most 50 `fields`,
  at most 3 filter predicates and 1 sort key (contract §7.7).
- `schedule_changes.list` between 2 P6 publications of a Series is the P6 delta (contract
  §11.4); a cross-format pair is `unsupported(source_format)`.
- `schedule_scenarios.create` from a P6 publication takes the `p6` object (`{}` for every
  default; `calendars` as `{publication_id, calendar_id}` references, `default_calendar`,
  `calendar_map`, `include_fields`) and answers `p6_snapshot_report` (every contract §11.5
  count, `unmodelled_settings`, `standard_calendar_horizon_exceeded`). The lag calendar and
  progress policy are changed on version 2 with `settings.set`.

### 10.8 Field capture (gate G-8 for personal fields)

`schedule_p6_fields.available` lists the catalogue and the observed fields of a Series with
their capture status; `schedule_p6_fields.set_captured` sets the Series' selection (at most
300 keys, compare-and-swap on `expected_sequence`, `conflict(sequence)` otherwise). A selection
applies from the **next** import; earlier publications keep what they captured. A personal
field is captured only with `include_personal: true` and served only to a holder of the
`schedule_p6_field_values.list` grant.

### 10.9 Troubleshooting by issue code

| Code | What to do |
|---|---|
| `p6_encoding_invalid`, `p6_header_invalid`, `p6_structure_invalid`, `p6_record_width_mismatch` | re-export the XER from P6 unchanged; never edit the file by hand |
| `p6_bound_exceeded` | the issue names the bound (contract §5.4); split the project or reduce the export |
| `p6_required_table_missing`, `p6_required_field_missing` | re-export with the default XER options; run the conformance script and compare its field report |
| `p6_multiple_projects` | export 1 project per file |
| `p6_duplicate_activity_id` | an Activity ID is repeated or empty; fix it in P6 and re-export |
| `p6_reference_dangling`, `p6_wbs_cycle` | the export is inconsistent; re-export |
| `p6_unknown_table`, `p6_unknown_field`, `p6_unknown_enum_value` (T/O) | findings only; report the conformance output (stats only) so the catalogue can be reviewed |
| `p6_export_version_untested` | a P6 version outside the tested range; run the evaluation (section 10.10) before relying on it |
| `p6_calendar_missing`, `p6_calendar_invalid`, `p6_calendar_base_substituted` | the activity keeps its P6 calendar id; a Scenario gives it `my-pa-us-40h-v1` (counted `calendars_defaulted`) unless the request maps it |
| `p6_external_relationship` | stored and flagged; a Scenario drops it (counted) |
| `p6_capture_cap_reached` | optional capture stopped for that publication; reduce the selection |
| `p6_project_identity_changed` | section 10.6 |

### 10.10 Retention, downgrade, conformance and evaluation

- **Retention.** Every snapshot is retained (operator decision 2026-11-23, contract §7.6);
  there is no deletion path. The quota of section 10.3 bounds it.
- **Downgrade.** Section 10.2 step 1. Rollback is the switches off: no row changes, the 7
  names are `unsupported`, stored P6 publications stay readable through the S5 reads while the
  schedule switch is on.
- **Conformance script** (contract §12), read-only and stats only (counts, lengths, shapes,
  names, codes; never a value), one file:

  ```sh
  .venv/bin/python ops/schedule/p6_export_profile.py <export.xer>
  ```

  It prints 1 JSON object: per table and per field the tier, presence, lengths, shapes and
  unknown enum tokens of the P6 vocabulary, the issues with their codes and lines, and the
  verdict `pass`, `pass_with_findings` (exit 0) or `fail` (exit 1); 2 is a usage error.
- **Evaluation script** (S7-5, contract §14), read-only and stats only, the exports of 1
  Project oldest first:

  ```sh
  .venv/bin/python ops/schedule/p6_evaluate.py <v1.xer> <v2.xer> <v3.xer>
  .venv/bin/python ops/schedule/p6_evaluate.py --assume-same-project <v1.xer> <v2.xer> <v3.xer>
  ```

  It prints 1 JSON object (`p6-evaluation-v1`). Per export: the profile verdict and issue
  counts by code; the activity, relationship, WBS and calendar counts and whether each equals
  the records of the file's own table; the contract §11.5 snapshot report (every count,
  `unmodelled_settings`, the number of outrun standard calendars, the content schema, or the
  refusal token); and the engine-vs-P6 oracle (`p6-engine-oracle-v1`). Per consecutive pair of
  the same project (short name or GUID), or every consecutive pair under
  `--assume-same-project` (update files exported as separate project copies, section 10.5):
  `same_project` (the §11.1 rule; `false` means the import needs
  `accept_project_identity_change`) and the delta's counts by change kind, `earlier → later`,
  with `reintroduced` across the run. Exit 1 when any verdict is `fail` (the object is still
  printed) or on an unexpected error (its type only), 0 otherwise, 2 on usage.
- **Reading the oracle.** It builds version 1 with every §11.5 default, runs the engine at
  the data date and compares each activity, joined by Activity ID, with P6's own early start,
  early finish, late start, late finish, total float (hours × 60) and remaining early start:
  per quantity the compared and equal counts by activity state, plus aggregate `equal_share`,
  a histogram of `engine − P6` in minutes (0, ±1..60, ±61..480, ±481..2400, beyond), the
  largest absolute difference, and counts for no P6 value, a value off the engine's axis or
  no engine value (none is a mismatch); then the critical sets (total float at most the
  project threshold, over the activities both give a float). It is **a check, not a claim of
  equivalence**: `unmodelled_settings` names the P6 options the export sets that the engine
  does not model (`ss_lag_from_early_start`, `use_expected_finish`, `total_float_type`,
  `open_ends_critical`, `float_from_project_finish`, `critical_path_longest_path`,
  `multiple_float_paths`, `external_relationships`, `parallel_relationships`,
  `in_progress_start_links`, `progress_actual_dates`). The Scenario keeps links of different
  types between the same ordered pair, such as SS and FF. The oracle flags
  `parallel_relationships` when links of the same type repeat for that pair. The Scenario
  keeps the largest lag and counts the other links in `relationships_parallel_dropped`.
  For `in_progress_start_links`, the engine skips the backward-pass bound of an SS or SF
  link whose predecessor is in progress. P6 applies the bound after subtracting the work
  done since the actual start, so late dates and floats can differ. A difference
  concentrated in progressed activities points at a P6 progress convention, not at an error.
- **Acceptance (gate G-7).** For every nominated export: verdict not `fail`, the 4 counts
  equal, the delta counts between consecutive versions, and the oracle's shares with their
  `unmodelled_settings`; only the stats output leaves the NAS. The scratch-database import of
  each export is the same `import_p6` call on a scratch deployment.
