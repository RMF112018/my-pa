# CPM Workbench — schedule evidence plane

**UNEXECUTED / OPERATOR-GATED.** This is a commissioned pre-execution procedure. No command
in a code block below was run against any shared, NAS or production database, and nothing
here is deployed: the two CPM revisions (`6c2306330ceb`, `621ef6786c64`) exist only on the
branch `feat/cpm-s5b-worker`, production runs the database at `023f8f7eb499`, and the
`MY_PA_SCHEDULE_ENABLED` switch is off by default. What **was** executed: the pre-deploy
checks of section 3 ran only against disposable per-test clones on an isolated scratch
PostgreSQL 15 cluster (`tests/database/test_cpm_workbench_predeploy.py`), and every behaviour
cited below ran in the repository's test tiers on synthetic PDFs. The current-state
description is [`docs/architecture/cpm-workbench.md`](../../docs/architecture/cpm-workbench.md);
the decision record is
[`ADR-016`](../../docs/decisions/ADR-016-cpm-workbench-schedule-evidence.md).

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

**Import roles from Schedule Scenarios S6-2 until S6-3** (schedule scenarios contract
S6-2-D04, sections 12.2 and 14.9): `schedule_publications.import` refuses role `baseline` with
`invalid_request(PUBLICATION_ROLE)` whatever the switches (a baseline import needs the
section 12.3 approval fields, which arrive with S6-3); role `reference` and baseline kind
`working` are retired and refused; `schedule_publications.list` refuses the filter
`publication_role=reference` with `invalid_request(PUBLICATION_ROLE)`. Import role `update`.

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
`schedule_publications`. Nothing in it is public: no capability, command, switch, grant or
ChatLLM surface exists for the plane until S6-3, so after this step the plane is **inert**.
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
3. **Expected `record_links` window.** On the scratch cluster (contract section 14.14:
   PostgreSQL 15.15, Apple M4 Pro) phase C took 0.84 s at 10^5 rows (24.8 MB) and 8.40 s at
   10^6 rows (248.3 MB): about **8.4 µs per row, or 34 ms per MB of heap**, linear. Multiply
   Q3's `record_links` `rows~` (or `bytes=`) by that factor, and allow for the server host
   being slower than the measurement host (its speed is unmeasured, S6-2-U01). **Go/no-go:**
   proceed only when the scaled phase C time is well under 10 s; otherwise stop and review.
   `lock_timeout = '10s'` bounds only the wait to **acquire** each lock, not this validating
   pass, which runs to completion while every lineage call waits.
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
| Q8 runtime reach | after | `has_table_privilege(current_user, …)` | `SELECT`/`INSERT` lacking on any of the 11 tables, or `UPDATE` on `schedule_scenario_write_requests` |
| Q9 plane objects | after | `pg_class`, `pg_proc`, `pg_trigger` | a plane table, one of the 15 plane functions, or trigger G10 absent |
