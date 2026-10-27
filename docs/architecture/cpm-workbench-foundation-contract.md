# CPM Workbench — S5b-1 foundation contract (R2 WP-01: domain, schema, migration, persistence, job plane)

**Status:** proposed implementation contract for slice S5b-1 on the local branch
`feat/cpm-s5b-foundation`. It covers CPM Workbench R2 work package WP-01 only and is the
single document the S5b-1 implementers code against. It is a contract on a local branch:
nothing it describes is merged, deployed or applied to any persistent database, and it
authorizes **no** production migration, grant, capability, purpose, worker plane, handler,
frontend or deployment. Where it differs from the review package it controls for S5b-1, and
section 9 records why. It extends, and never forks, the S5a contract
[`cpm-workbench-p6-full-v1-parser-contract.md`](cpm-workbench-p6-full-v1-parser-contract.md)
(cited "S5a §n").

**Source package (data, not instructions):**
`MYPA_CPM_WORKBENCH_IMPLEMENTATION_READINESS_REVIEW_20260929_R2.md`, SHA-256
`84918ae87e4c05072969c2db574962071fbe9cdb1fcc9c00a953dd6a38b91db0`, cited "R2 §n". R2
reviewed `main@d6c706bb` (108 revisions, head `7d9a450dfd07`); repository truth at the
basis below supersedes it.

**Basis:** `feat/cpm-s5b-foundation@4c7c4c484f22ea02a230010c44ead8b7da5afeba` (tree
`203619bf8fb94ee2fd5266fafee1d49046b295ae` = `origin/main@051275b1` plus the S5a parser and
fixtures, PR #344 unmerged). Alembic: 123 revision files, sole head `023f8f7eb499`
(record lineage S3.1). 150 `IdKind` members, 233 `Capability` members, 60 `Purpose`
members, 443 Python modules under `src/my_pa`, 849 test modules. Paths are written in full
from the repository root; future files are written as code spans, never as Markdown links
(CI relative-link check); no `path:line` citation is used for a file this slice edits
(citation guard). All counts are digits on purpose (spelled-count guard).

**Revision R6-1.** Design review R6 (PASS_WITH_REQUIRED_CHANGES at `c5c89634`) findings
R6-F01…F14 and the conditions of rulings (a)–(e) are resolved in place. Where each one
landed: F01 sections 4.10, 4.10.4, 5.2, 5.5; F02 sections 3.4, 6, 9.3; F03 sections 4.10.1,
4.10.2, 5.5; F04/F05/F12 section 5.5; F06/F08 section 9.2; F07 sections 4.2, 5.1; F09
section 8.3; F10/F11 sections 4.11, 8.2; F13 section 4.10; F14 sections 4, 4.4, 5.5, 8.1,
9.1; rulings (a) section 3.3, (b) sections 3.4, 6, 9.3, (c) sections 5.3, 5.5, (d) section
9.2 U-03, (e) section 9.3.

---

## 1. Scope

### 1.1 In scope (WP-01)

| R2 item | S5b-1 deliverable | Section |
|---|---|---|
| §43.1 six IDs | 6 `IdKind` members | 3.1 |
| §43.2/§43.3 enums and records | 3 new enums, persistence records, admission request, series name, request digest, typed outcomes, effective status | 5.1–5.3 |
| §18 seven tables | `schedule_series`, `schedule_publications`, `schedule_activities`, `schedule_jobs`, `schedule_parser_runs`, `schedule_rows`, `schedule_import_issues` in `src/my_pa/infrastructure/persistence/tables.py` and the frozen revision | 4 |
| §9.3/§18.8.1–2 support uniques | `(enrollment_id, principal_id)` on `knowledge.enrollments`, `(version_id, source_object_id)` on `knowledge.source_object_versions` | 3.4, 4.9 |
| §16.15/§17.3/§18 guards | lifecycle, set-once, terminal-immutability, append-only and TRUNCATE triggers | 4.10 |
| §8.2 dedicated UoW | `ScheduleRepository`, `ScheduleUnitOfWork` (ports), `SqlScheduleRepository`, `SqlAlchemyScheduleUnitOfWork` | 5.4–5.6 |
| §23 idempotency, §24 transaction methods | repository methods, lease-checked | 5.5 |
| §25 `SCHEDULE_JOBS` | the `JobPlane` constant only | 3.3 |
| §19 migration | one frozen revision on `023f8f7eb499` | 6 |
| §35 partition | principal-guard registry entry | 3.5 |

### 1.2 Explicitly out of scope

- WP-03: the schedule job handler (`infrastructure/jobs/schedule.py`), the provider read, the
  240 s budget, **`apps/worker.py` plane registration, `worker_heartbeats.plane` widening,
  the `worker_health.py` allowlist and health map, the `ApplicationService._capabilities_get`
  worker fallback** (section 3.3), the 7 capabilities, 2 purposes, the `audit_events`
  vocabulary widening (section 3.2), commands, normalization builders, policy, authorization,
  SafeDetails, ChatLLM policy/profile, remote MCP, `ScheduleApplication`, paged reads,
  `ScheduleCursor`, `ScheduleChange`/`ScheduleChangeKind`, `domain/schedule/compare.py`,
  gateway composition of the Schedule UoW factory, the fake Schedule UoW in
  `tests/conftest.py`.
- WP-04: security/evaluation suites, runbooks, `docs/architecture/cpm-workbench.md`,
  current-state prose about the feature, generated web fixtures.
- Parser integration and any change to S5a parser behaviour or goldens.
- Frontend, any default switched on, any deployment, any grant, any live/NAS/production
  database.

### 1.3 What "done" means for S5b-1

One additive revision on `023f8f7eb499` that is the sole head; `tables.py` mirrors it; the
dedicated repository and UoW implement every section 5.5 method against a synthetic
PostgreSQL 15 database; every section 8.2 guard is proved red by breaking exactly that guard;
FAST, the database and migration tiers selected by marker, ruff, ruff format, mypy (current
and floor-pinned) and the shard partition proof are green; nothing is served, no worker can
run a `schedule` plane, nothing is granted.

---

## 2. Repository reauthentication and divergence table

| # | R2 claim | Repository truth at the basis | Decision |
|---|---|---|---|
| T-01 | Head `7d9a450dfd07`, 108 revisions (§19.1) | Sole head `023f8f7eb499` in `migrations/versions/20261025_023f8f7eb499_record_lineage_s31.py`; 123 revision files; `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py::test_the_chain_is_readable_and_non_empty` pins 123 | New revision `down_revision = "023f8f7eb499"`, 124 files; head literal and count move in lockstep (section 7, I6-A) |
| T-02 | Six IDs `sser/spub/sprun/srow/sact/siss` (§43.1) | `IdKind` has 150 members (S1 added `irs ipme irl irv ian`, S2 `ihnd`, S3 `ihcr lbfr`); none of the 6 strings is a member; none is a string prefix of a member or prefixed by one (measured over all 150, section 3.1); `git grep -w` of each `<p>_` over `src tests web/src migrations` finds nothing | Adopt the 6 prefixes unchanged |
| T-03 | IDs guarded | `tests/unit/test_identifiers.py`: `test_contract_prefixes_are_stable` is an exact set equality; `test_project_controls_prefixes_are_unique_across_every_kind` asserts global uniqueness; `test_knowledge_prefixes_are_disjoint_from_every_other_prefix_and_the_forbidden_set` asserts no `prefix_` overlap with Knowledge prefixes | Add the 6 to the exact set (lockstep); the two uniqueness tests then cover them |
| T-04 | `tables.py` + byte-hash guards (§41) | `tests/architecture/test_capture_project_binding.py` pins `TABLES_SHA256` (whole file) under the MR-01 rule "purely additive, `captures` unchanged"; `tables.py` derives closed sets from live enums (`_one_of`, `_each_one_of`, `_is_identifier`) | Add the 7 tables; re-pin `TABLES_SHA256` mechanically |
| T-05 | Support uniques on `enrollments`/`source_object_versions` (§9.3) | Both tables are created by historical revision `7e5a1fb93d62` through `METADATA.create_all` over **copies of the live declarations** (`_historical_knowledge_tables`); a constraint declared on either in `tables.py` would retroactively change that revision's DDL (the `D-48` hazard; S1 F20 precedent `a_capture_version_digest_is_identified_within_its_capture`) | Both uniques are **database-only**: added by the new revision, **not** declared in `tables.py`, recorded by a comment beside each declaration; `tables.py` foreign keys may still reference them (S1 precedent) — D-04 |
| T-06 | Leading columns of the support uniques | `enrollments.enrollment_id` and `source_object_versions.version_id` are each the single-column primary key | Both composites are unique **by implication** on any existing data; a duplicate scan is unreachable — D-05 |
| T-07 | `enrollment_objects` PK `(enrollment_id, source_object_id)` (§9.3) | Present, named `an_enrollment_holds_an_object_once` | Referenced directly |
| T-08 | `projects` same-Principal composite FK pattern | `UNIQUE (project_id, principal_id)` named `a_project_is_identified_within_its_principal` | Referenced by `schedule_series` |
| T-09 | principal_scope guard registry (§35, §42) | `tests/architecture/test_principal_partition_is_reached_through_the_guard.py`: exact sets `REACHED_THROUGH_THE_GUARD`, `STATEMENT_LEVEL`, `PER_MODULE_ONLY`, `HAND_WRITTEN_COMPARISONS`, `UNPARTITIONED_JOB_STATEMENTS`; raw `text()` must carry the partition | Register `infrastructure/persistence/schedule.py` in `REACHED_THROUGH_THE_GUARD` and `PER_MODULE_ONLY` (the `constraints.py`/`issues.py` shape); no hand-written comparison, no `text()` — section 3.5 |
| T-10 | JobPlane tables (§18.4: "same columns/state semantics") | `src/my_pa/infrastructure/persistence/jobs.py`: `JobPlane(table, subject, subject_kind, owner_table, owner_key, owner_column, lease_generation=None, pause_cause=None)`; `ENROLLMENT_JOBS` (`jobs`), `CAPTURE_JOBS` (`capture_jobs`). Columns of `jobs`: `operation_id` PK, subject, `state` (`JobState` 4), `attempt_count`, `max_attempts` (default 3, `BETWEEN 1 AND 30`), `lease_owner`, `lease_expires_at`, `last_error_code` (11 public `ErrorCode`s), `next_attempt_at`, `dead_lettered_at`, `created_at`, `updated_at`, `principal_id`; CHECKs lease pair, running-iff-leased, failed-iff-dead-lettered, attempts bounded. Functions: `enqueue_job` (not idempotent; resolves Principal from `owner_table` by `owner_key`), `claim_job` (reaps, `FOR UPDATE SKIP LOCKED`), `hold_lease` (`FOR UPDATE`, bool), `complete_job`, `release_job`, `reap_abandoned_jobs`, `job_for`/`job_state` (derive `failed` for an abandoned final attempt via `_abandoned`) | `schedule_jobs` copies the column set and CHECKs with frozen literals, adds `UNIQUE (publication_id)` and identity/terminal guards (section 4.4); `SCHEDULE_JOBS` reuses every function unchanged |
| T-11 | Worker plane closure (§25) | `worker_heartbeats.plane` CHECK `plane IN ('capture', 'enrollment', 'reenrichment')`, frozen last by `b727e870d45e`; `src/my_pa/infrastructure/persistence/worker_health.py` admits the same 3 for heartbeats and reports health for `capture`/`enrollment` only; `apps/worker.py` `_JOB_PLANES` = enrollment, capture; `_PLANES` adds `reenrichment`; `SqlAlchemyUnitOfWork` worker-health read and `ApplicationService` fallback enumerate `("capture", "enrollment")` | **Nothing changes in WP-01**; all of it moves with the handler in WP-03 — D-02 |
| T-12 | Dedicated UoW precedent (§8.2) | `TaskManagementUnitOfWork`, `CommitmentManagementUnitOfWork`, `ConstraintManagementUnitOfWork` in `src/my_pa/contracts/ports.py`; `SqlAlchemyConstraintManagementUnitOfWork(engine)` owns `engine.begin()`, hands out a repository on that connection, never commits inside the repository; `ApplicationService.__init__` takes `constraint_management_unit_of_work: Callable[[], ConstraintManagementUnitOfWork] \| None`, built in `src/my_pa/bootstrap/gateway.py` from the work engine | Same shape; ApplicationService/gateway composition is WP-03 |
| T-13 | Append-only + TRUNCATE pattern | S1 `lineage_rows_are_append_only()` (raises `restrict_violation`), `lineage_relations_refuse_truncate()` (statement-level, refuses only when the table holds a row, so fixture `TRUNCATE … CASCADE` on empty tables passes); S2/S3 reuse them; downgrade refuses first with a `DO` block raising `restrict_violation` | Same bodies under CPM-owned names — D-13 |
| T-14 | App-role GRANT pattern | S1–S3.1 revisions execute **no `GRANT`/`REVOKE`** (ADR-015 decision 10; S3.1 §5); tests assert `"GRANT " not in` the revision text; MCP data roles `my_pa_mcp_ro`/`my_pa_mcp_rw` gain privileges only through a reviewed `McpObjectGrant` (`src/my_pa/infrastructure/database/mcp_object_grants.py`); Record Event owner/migrator/runtime roles exist only in `src/my_pa/infrastructure/database/record_event_roles.py` (operator-applied) | No GRANT, no REVOKE, no `McpObjectGrant`; tables are owned by the migrating role exactly as every lineage table — section 4.11 |
| T-15 | Downgrade refusal convention | `DO $$ … RAISE EXCEPTION '…' USING ERRCODE = 'restrict_violation'` before any drop; drops in reverse creation order, tables `RESTRICT` | Same |
| T-16 | Migration test tiers | `tests/db/fixtures.py`: files ending `_migration.py` default to `migration_edge`; `migration_empty_to_head` explicit; other `database` tests default to `database_clone`; no-marker tests are FAST; `--strict-markers` | Section 8 assigns tiers |
| T-17 | Historical-edit guard | Revisions are frozen text; `test_no_revision_derives_a_closed_set_from_an_enum.py` reads only `Table`-emitting revisions and pins the count; `test_capture_project_binding.py` pins one historical revision's bytes | New revision is raw DDL with no `my_pa` import; no historical file is edited |
| T-18 | S5a types (§43.2) | `src/my_pa/domain/schedule/model.py` already defines `ScheduleRowType`, `ScheduleCellState`, `ScheduleIssueSeverity`, `ScheduleFieldCode`, `ScheduleIssueCode` (23), `SchedulePublicationStatus`, `ISSUE_SEVERITY`, `TERMINAL_OUTCOMES`, the records of S5a §3.3, `normalize_activity_id`, `normalize_display_text`, `stable_link_candidates`; `src/my_pa/domain/schedule/canonical.py` defines `CELLS_SCHEMA`, `canonical_json_bytes`, `cell_evidence_object`, `cell_evidence_bytes`, `parse_result_sha256`. Missing: `SchedulePublicationRole`, `ScheduleBaselineKind`, `ScheduleParserRunStatus` | Reuse all S5a symbols unchanged; add only the 3 enums and section 5 symbols to the same 2 modules |
| T-19 | `domain/schedule` imports | `tests/architecture/test_cpm_full_parser_scope.py::test_schedule_import_allowlist` admits only `my_pa.domain.schedule` (+ stdlib) under `domain/schedule` | Widen exactly to add `my_pa.domain.common.identifiers` (lockstep, I6-A) — D-18 |
| T-20 | Audit frozen sets (§18.8.4, §19.9) | `audit_events.capability_is_known`/`purpose_is_known` were last restated by `023f8f7eb499`; `tables.py` `_CURRENT_AUDIT_CAPABILITIES` derives from the live `Capability` enum, so a database set wider than the enum is a schema-ahead gap the lineage slices had to measure explicitly | **Not widened in WP-01** — D-01 |
| T-21 | Live-table ALTER is production-relevant | Production runs `main@051275b1` at `023f8f7eb499` | Section 4.9 lock analysis; section 9.3 operator gate |

---

## 3. Decisions the slice boundary forces

### 3.1 IDs

| Member | Prefix | Issued for |
|---|---|---|
| `IdKind.SCHEDULE_SERIES` | `sser` | `schedule_series.series_id` |
| `IdKind.SCHEDULE_PUBLICATION` | `spub` | `schedule_publications.publication_id` |
| `IdKind.SCHEDULE_PARSER_RUN` | `sprun` | `schedule_parser_runs.parser_run_id` |
| `IdKind.SCHEDULE_ROW` | `srow` | `schedule_rows.row_id` |
| `IdKind.SCHEDULE_ACTIVITY` | `sact` | `schedule_activities.schedule_activity_id` |
| `IdKind.SCHEDULE_IMPORT_ISSUE` | `siss` | `schedule_import_issues.issue_id` |

Appended after `LINEAGE_BACKFILL_RUN` with a comment block in the file's style ("Checked
against all 150 prior members before use … none collides, no member is a prefix of any, and
none is a prefix of a member"). Collision result (measured at the basis): nearest neighbours
`sub`, `src`, `span`, `sit`, `stage`, `sevd`, `sobs`, `smem` — none equal, none a
`str.startswith` prefix in either direction. `schedule_jobs.operation_id` reuses
`IdKind.OPERATION` (`op`). Count 150 → 156.

### 3.2 Audit vocabulary — not widened (D-01)

No capability or purpose exists until WP-03, and `_CURRENT_AUDIT_CAPABILITIES` in `tables.py`
derives from the live `Capability` enum, so a widened database set would open a schema-ahead
gap that a lineage-style ahead-contract would have to measure for a whole slice. The audit
sets track real capabilities. **WP-01 neither restates nor widens `capability_is_known` or
`purpose_is_known`.** WP-03 owns a second CPM revision that admits the 7 names and 2 purposes
with byte-copied BEFORE texts from the then-latest restating revision.

### 3.3 Worker plane — `SCHEDULE_JOBS` only (D-02)

| Surface | WP-01 | Why |
|---|---|---|
| `SCHEDULE_JOBS` in `src/my_pa/infrastructure/persistence/jobs.py` | **added** (exported in `__all__`) | admission must enqueue the publication's one job and every §24 write must `hold_lease`; a `JobPlane` constant runs nothing |
| `apps/worker.py` `_JOB_PLANES`/`_PLANES` | unchanged | no handler exists; `--plane schedule` must stay an argparse error |
| `worker_heartbeats.plane` CHECK and `tables.py` mirror | unchanged | nothing can report a `schedule` heartbeat without a runnable plane |
| `worker_health.record_worker_heartbeat` allowlist, `worker_plane_health` map, `SqlAlchemyUnitOfWork` worker-health read, `ApplicationService` fallback | unchanged | no health surface may report a plane that cannot run |

```python
#: CPM Workbench S5b-1: one job per admitted Schedule publication (R2 section 25).
#: Not registered in `apps/worker.py` until WP-03 adds its handler.
SCHEDULE_JOBS: Final = JobPlane(
    schedule_jobs,
    "publication_id",
    IdKind.SCHEDULE_PUBLICATION,
    owner_table=schedule_publications,
    owner_key="publication_id",
    owner_column="principal_id",
)
```

Consequence, stated: a `schedule_jobs` row can exist only through the repository admission
method, which no capability reaches in WP-01, so production holds none.

**Four-surface guard (ruling (a)).** FAST
`tests/architecture/test_cpm_workbench_foundation_scope.py::test_schedule_plane_is_not_runnable_before_its_handler`
asserts `"schedule"` is absent from each of the 4 surfaces separately, so WP-03 must flip
each explicitly:

| # | Surface | Read as |
|---|---|---|
| 1 | `apps/worker.py` `_PLANES` and `_JOB_PLANES` | imported module attributes |
| 2 | heartbeat CHECK literal at head | `worker_plane_is_known` text on `tables.worker_heartbeats` |
| 3 | `worker_health` heartbeat allowlist and health map | `record_worker_heartbeat(..., plane="schedule")` raises `ValueError` and `worker_plane_health(..., plane_name="schedule")` raises `ValueError` (in-memory: both validate before any statement; a principal identifier is passed, the connection is a `MagicMock` that must see no call) |
| 4 | `ApplicationService` worker-plane fallback tuple and the `SqlAlchemyUnitOfWork` worker-health read | AST of `src/my_pa/application/service.py` and `src/my_pa/infrastructure/persistence/unit_of_work.py`: no `"schedule"` string literal inside the `("capture", "enrollment")` plane tuples |

**WP-03's revision is additive only:** a later revision on top of this one, restating the
audit and heartbeat CHECKs from byte-copied BEFORE texts; it never edits this revision.
Nothing in WP-01 depends on that revision existing (D-03).

### 3.4 Support uniques on live tables

| Table | New constraint (name) | Columns | Why it cannot fail | Rows expected |
|---|---|---|---|---|
| `knowledge.enrollments` | `an_enrollment_is_identified_within_its_principal` | `(enrollment_id, principal_id)` | `enrollment_id` is the single-column PK, so every composite is distinct | one row per accepted enrollment (operator-scale; unmeasured in production — U-01) |
| `knowledge.source_object_versions` | `a_source_version_is_identified_with_its_object` | `(version_id, source_object_id)` | `version_id` is the single-column PK | one row per observed source version (unmeasured — U-01) |

Mechanics (D-05). Everything runs inside the one revision transaction
(`transaction_per_migration=True` in `migrations/env.py`), and **PostgreSQL holds every lock
until that transaction commits**. The live-table work is therefore the **last** thing
`upgrade()` does (section 6, R6-F02): every CPM table, index, function and trigger already
exists, so the window in which live tables are locked is only steps 2–5 below plus commit.

1. `SET LOCAL lock_timeout = '10s'` as the first statement of `upgrade()` (and of
   `downgrade()`). `SET LOCAL` is transaction-scoped: it does not survive the revision
   transaction (tested). A lock not obtained within 10 s aborts the whole revision with
   SQLSTATE `55P03` (`lock_not_available`) and rolls back everything, leaving the database at
   `023f8f7eb499` (tested). No `statement_timeout` is set: `migrations/env.py` builds the
   migration engine with `statement_timeout_ms=None` on purpose, and an index build must not
   be killed halfway.
2. **Catalog preflight** (no row scan): a `DO` block raises `restrict_violation` with
   `'cpm workbench preflight: % no longer has its single-column primary key %'` unless
   `pg_constraint` holds a `contype = 'p'` constraint on `knowledge.enrollments` whose
   `conkey` is exactly `enrollment_id`, and likewise `version_id` on
   `knowledge.source_object_versions`. This is the reachable form of "refuse rather than
   guess": if the PK premise holds, duplicates are impossible; if it does not, nothing is
   altered.
3. `CREATE UNIQUE INDEX <name> ON knowledge.<table> (<cols>)` — takes `SHARE` (writers wait,
   readers continue) **held until commit**; the build is linear in table size.
4. `ALTER TABLE knowledge.<table> ADD CONSTRAINT <name> UNIQUE USING INDEX <name>` — takes
   `ACCESS EXCLUSIVE`, **held until commit**: from here to commit every reader of
   `enrollments` and `source_object_versions` (gateway source-scope authorization, the
   enrollment worker, searches) waits. Step 5 and commit are the only work left, so the
   window is short; it is not "milliseconds" and the operator gate says so (section 9.3).
5. `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` for the 4 FKs into existing tables
   (`schedule_series → projects`, `schedule_publications → enrollments`,
   `→ enrollment_objects`, `→ source_object_versions`): each takes `SHARE ROW EXCLUSIVE` on
   the referenced table, held until commit; validation scans the new, empty referencing
   tables only.

An index-only FK target (no `ADD CONSTRAINT … USING INDEX`, avoiding `ACCESS EXCLUSIVE`) is
**not** adopted: it is unproven on the scratch PostgreSQL 15 and would make the uniques
invisible as constraints. `CONCURRENTLY` is not used (it cannot run in the revision
transaction). Downgrade drops only these 2 constraints (`ALTER TABLE … DROP CONSTRAINT`,
`ACCESS EXCLUSIVE`, which drops the index), under the same `lock_timeout`. Section 9.3 states
the deploy-time operator gate.

### 3.5 Principal partition

Every new table has `principal_id text NOT NULL` with `_is_identifier(…, PRINCIPAL)`.
`src/my_pa/infrastructure/persistence/schedule.py` builds every statement with module-local
`_mine(table, principal_id)` over `partition_criterion` / `principal_scoped`, inserts with
`_bound(table, principal_id, values)` over `principal_bound_values`, and joins two partitioned
tables with `matching_partition_criterion` — the `constraints.py` shape. `enrollment_objects`
(no partition column) is read only joined to `enrollments` under `_mine(enrollments, …)`;
`source_object_versions` (source plane, unpartitioned) is read only by the exact
`(version_id, source_object_id)` pair the admission request names after the enrollment join
has proved membership. Registry edits: add the module to `REACHED_THROUGH_THE_GUARD` and to
`PER_MODULE_ONLY` with a reason in the file's style. `jobs.py` statement-level accounting is
unchanged (`SCHEDULE_JOBS` uses the same generic functions; `UNPARTITIONED_JOB_STATEMENTS`
counts do not move).

### 3.6 Trigger functions — own, not reused (D-13)

The lineage functions' semantics match, but CPM gets byte-equivalent bodies under its own
names so its downgrade drops only CPM objects and a later lineage edit cannot change CPM
behaviour. Section 4.10 lists every function.

---

## 4. Exact schema (schema `knowledge`)

Conventions for every table below: `text` identifiers with `_is_identifier` CHECKs (name
`<column>_is_an_opaque_identifier`); every foreign key `ON DELETE RESTRICT`, `MATCH SIMPLE`;
timestamps `timestamptz NOT NULL DEFAULT now()` unless stated; closed sets are **frozen
literals in the revision** and `_one_of`/`_each_one_of` from the live enum in `tables.py`
(literals in **sorted** order in both, identical text — R6-F14; `tables.py` builds the error-code set with `_literals(ErrorCode)`, not the enum-order join `jobs` uses); constraint names are ≤ 63 bytes. "SHA" means CHECK
`<col> ~ '^[0-9a-f]{64}$'`.

### 4.1 `schedule_series` (append-only)

| Column | Type | Null | Default | CHECK (name) |
|---|---|---|---|---|
| `series_id` | text | no | — | PK `schedule_series_pkey`; `sser` |
| `principal_id` | text | no | — | `prn` |
| `project_id` | text | no | — | `prj` |
| `name` | text | no | — | `a_schedule_series_name_is_normalized`: `char_length(name) BETWEEN 1 AND 200 AND name = btrim(name, ' ') AND position('  ' in name) = 0 AND name !~ '[[:cntrl:]]'` |
| `name_key` | text | no | — | `a_schedule_series_key_is_bounded`: `char_length(name_key) BETWEEN 1 AND 800` |
| `created_at` | timestamptz | no | `now()` | |

- UNIQUE `a_schedule_series_name_is_unique_within_its_project (principal_id, project_id, name_key)`.
- UNIQUE `a_schedule_series_is_identified_within_its_project (series_id, principal_id, project_id)`.
- FK `a_schedule_series_names_a_project_of_its_principal (project_id, principal_id) → projects (project_id, principal_id)`.
- Index `schedule_series_by_project (principal_id, project_id, created_at, series_id)`.
- Triggers: `schedule_series_are_append_only` (F1), `schedule_series_refuse_truncate` (F2).

### 4.2 `schedule_publications`

| Column | Type | Null | Default | Rule |
|---|---|---|---|---|
| `publication_id` | text | no | — | PK; `spub` |
| `principal_id`, `project_id`, `series_id` | text | no | — | `prn`/`prj`/`sser` |
| `enrollment_id` | text | no | — | `enr` |
| `source_object_id` | text | no | — | `obj` |
| `source_version_id` | text | no | — | `ver` |
| `idempotency_key` | text | no | — | `a_schedule_idempotency_key_is_bounded`: `idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'` (the `a_project_history_idempotency_key_is_bounded` / `CONSTRAINT_IDEMPOTENCY_KEY_PATTERN` precedent, R6-F07) |
| `request_digest` | text | no | — | SHA, `a_schedule_request_digest_is_sha256` |
| `publication_role` | text | no | — | `a_schedule_publication_role_is_known`: `IN ('baseline','reference','update')` |
| `baseline_kind` | text | yes | — | `a_schedule_baseline_kind_is_known`: `IS NULL OR IN ('contract','working')` |
| `expected_data_date` | date | yes | — | |
| `supersedes_publication_id` | text | yes | — | `spub`; `a_schedule_publication_does_not_supersede_itself`: `supersedes_publication_id IS NULL OR supersedes_publication_id <> publication_id` |
| `status` | text | no | `'queued'` | `a_schedule_publication_status_is_known`: `IN ('complete','failed','partial','processing','queued','review_required')` |
| `document_sha256` | text | yes | — | SHA when set |
| `document_size_bytes` | bigint | yes | — | `a_schedule_document_is_pinned_whole`: `(document_sha256 IS NULL) = (document_size_bytes IS NULL) AND (document_size_bytes IS NULL OR document_size_bytes BETWEEN 0 AND 16777216)` |
| `published_schedule_title` | text | yes | — | `a_schedule_title_is_bounded`: `IS NULL OR char_length BETWEEN 1 AND 300` |
| `data_date`, `run_date` | date | yes | — | |
| `accepted_parser_run_id` | text | yes | — | `sprun` |
| `page_count`, `row_count`, `activity_count`, `ambiguous_row_count`, `issue_count` | integer | yes | — | `a_schedule_publication_count_is_not_negative`: each `IS NULL OR >= 0` |
| `admitted_at` | timestamptz | no | `now()` | |
| `processing_started_at`, `completed_at` | timestamptz | yes | — | |
| `updated_at` | timestamptz | no | `now()` | |

Row CHECKs:

- `a_schedule_baseline_has_its_kind`: `(publication_role = 'baseline') = (baseline_kind IS NOT NULL)`.
- `a_schedule_publication_records_its_progress`:
  - `status = 'queued'` ⇒ `processing_started_at`, `completed_at`, `accepted_parser_run_id`, `document_sha256`, the 5 counts, title, `data_date`, `run_date` all NULL;
  - `status = 'processing'` ⇒ `processing_started_at` NOT NULL; `completed_at`, `accepted_parser_run_id`, the 5 counts, title, dates NULL;
  - `status IN ('complete','partial','review_required')` ⇒ `processing_started_at`, `completed_at`, `accepted_parser_run_id`, `document_sha256`, the 5 counts NOT NULL;
  - `status = 'failed'` ⇒ `processing_started_at`, `completed_at`, `issue_count` NOT NULL, `issue_count >= 1`; `accepted_parser_run_id`, `page_count`, `row_count`, `activity_count`, `ambiguous_row_count`, title, dates NULL.

Uniques and indexes:

- U1 `a_schedule_publication_key_is_used_once (principal_id, idempotency_key)`.
- U2 `a_schedule_source_version_is_published_once_per_series (principal_id, series_id, source_version_id)`.
- U3 `a_schedule_publication_is_identified_within_its_series (publication_id, principal_id, project_id, series_id)`.
- U4 `a_schedule_publication_is_identified_within_its_principal (publication_id, principal_id)` (the `schedule_jobs` target; `JobPlane` inserts carry no project/series).
- Partial unique index `a_schedule_publication_is_superseded_once ON (principal_id, supersedes_publication_id) WHERE supersedes_publication_id IS NOT NULL`.
- Index `schedule_publications_by_series (principal_id, series_id, admitted_at, publication_id)`.
- Index `schedule_publications_by_status (principal_id, project_id, status)`.

Foreign keys:

| Name | Columns → target |
|---|---|
| `a_schedule_publication_names_its_series` | `(series_id, principal_id, project_id) → schedule_series (series_id, principal_id, project_id)` |
| `a_schedule_publication_names_an_enrollment_of_its_principal` | `(enrollment_id, principal_id) → enrollments (enrollment_id, principal_id)` (database-only unique, section 3.4) |
| `a_schedule_publication_names_an_enrolled_object` | `(enrollment_id, source_object_id) → enrollment_objects (enrollment_id, source_object_id)` |
| `a_schedule_publication_names_a_version_of_its_object` | `(source_version_id, source_object_id) → source_object_versions (version_id, source_object_id)` (database-only unique) |
| `a_schedule_publication_supersedes_within_its_series` | `(supersedes_publication_id, principal_id, project_id, series_id) → schedule_publications (publication_id, principal_id, project_id, series_id)` |
| `a_schedule_publication_accepts_one_of_its_runs` | `(accepted_parser_run_id, publication_id, principal_id) → schedule_parser_runs (parser_run_id, publication_id, principal_id)`; created by `ALTER TABLE` after `schedule_parser_runs` exists; `use_alter=True` in `tables.py` (circular) |

Triggers: `a_schedule_publication_follows_its_lifecycle` (F3, `BEFORE INSERT OR UPDATE OR
DELETE`), `a_schedule_publication_has_its_job` (F4, constraint trigger `AFTER INSERT`,
`DEFERRABLE INITIALLY DEFERRED`), `schedule_publications_refuse_truncate` (F2).

### 4.3 `schedule_activities` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `schedule_activity_id` | text | no | PK; `sact` |
| `principal_id`, `project_id`, `series_id` | text | no | `prn`/`prj`/`sser` |
| `published_activity_id` | text | no | `a_schedule_activity_id_is_exact`: `char_length BETWEEN 1 AND 256 AND published_activity_id = btrim(published_activity_id)` |
| `created_at` | timestamptz | no | `now()` |

- UNIQUE `a_schedule_activity_id_is_unique_within_its_series (principal_id, series_id, published_activity_id)`.
- UNIQUE `a_schedule_activity_is_identified_with_its_published_id (schedule_activity_id, principal_id, series_id, published_activity_id)` (row stable-link target).
- FK `a_schedule_activity_belongs_to_its_series (series_id, principal_id, project_id) → schedule_series (series_id, principal_id, project_id)`.
- Triggers F1 `schedule_activities_are_append_only`, F2 `schedule_activities_refuse_truncate`.
- No name, date, duration, hierarchy or first-seen column (R2 §16.14).

### 4.4 `schedule_jobs` (mutable lease state; existing JobPlane semantics)

| Column | Type | Null | Default | Rule |
|---|---|---|---|---|
| `operation_id` | text | no | — | PK; `op` |
| `publication_id` | text | no | — | `spub` |
| `state` | text | no | `'queued'` | `a_schedule_job_state_is_known`: `IN ('failed','queued','running','succeeded')` |
| `attempt_count` | integer | no | `0` | |
| `max_attempts` | integer | no | `3` | |
| `lease_owner` | text | yes | — | |
| `lease_expires_at` | timestamptz | yes | — | |
| `last_error_code` | text | yes | — | `a_schedule_job_error_code_is_public`: `IS NULL OR IN ('ambiguous_request','cancelled','conflict','denied','internal_error','invalid_request','not_found','quarantined','rate_limited','unavailable','unsupported')` |
| `next_attempt_at` | timestamptz | no | `now()` | |
| `dead_lettered_at` | timestamptz | yes | — | |
| `created_at`, `updated_at` | timestamptz | no | `now()` | |
| `principal_id` | text | no | — | `prn` |

CHECKs copied from `jobs` with frozen literals: `a_schedule_lease_has_an_owner_and_an_expiry`
`(lease_owner IS NULL) = (lease_expires_at IS NULL)`; `a_schedule_job_is_running_exactly_while_leased`
`(state = 'running') = (lease_owner IS NOT NULL)`; `a_failed_schedule_job_is_dead_lettered`
`(state = 'failed') = (dead_lettered_at IS NOT NULL)`; `a_schedule_job_attempts_are_bounded`
`attempt_count >= 0 AND max_attempts BETWEEN 1 AND 30 AND attempt_count <= max_attempts`.

- UNIQUE `a_schedule_publication_has_one_job (publication_id)`.
- UNIQUE `a_schedule_job_is_identified_with_its_publication (operation_id, publication_id, principal_id)` (parser-run target).
- FK `a_schedule_job_names_a_publication_of_its_principal (publication_id, principal_id) → schedule_publications (publication_id, principal_id)`.
- Indexes `schedule_jobs_by_state (state, created_at)`, `schedule_jobs_by_principal_claim_order (principal_id, state, next_attempt_at, created_at)`.
- Trigger `a_schedule_job_keeps_its_identity` (F5): INSERT requires `state = 'queued'`, `attempt_count = 0`, `lease_owner IS NULL`; UPDATE refuses any change of `operation_id`, `publication_id`, `principal_id`, `max_attempts`, `created_at`, and refuses every update of a row whose `OLD.state IN ('succeeded','failed')`; DELETE refused. Every `jobs.py` write (`claim_job`, `complete_job`, `release_job`, `reap_abandoned_jobs`) touches only `state`, `attempt_count`, lease, error, retry, dead-letter and `updated_at` columns of a `queued`/`running` row, so the existing functions run unchanged (D-11).
- Trigger F2 `schedule_jobs_refuse_truncate`.

### 4.5 `schedule_parser_runs`

| Column | Type | Null | Rule |
|---|---|---|---|
| `parser_run_id` | text | no | PK; `sprun` |
| `principal_id`, `project_id`, `series_id`, `publication_id` | text | no | `prn`/`prj`/`sser`/`spub` |
| `operation_id` | text | no | `op` |
| `attempt_number` | integer | no | `a_schedule_attempt_is_positive`: `>= 1` |
| `parser_name`, `parser_version`, `profile_id` | text | no | `a_schedule_parser_identity_is_bounded`: each `char_length BETWEEN 1 AND 64` |
| `profile_version` | integer | no | `>= 1` (same CHECK) |
| `pypdfium2_version`, `pdfium_version` | text | no | `a_schedule_parser_engine_is_bounded`: each `BETWEEN 1 AND 64` |
| `document_sha256` | text | no | SHA |
| `status` | text | no | `a_schedule_parser_run_status_is_known`: `IN ('failed','parsed','running')`, default `'running'` |
| `page_count`, `row_count`, `issue_count`, `warning_count` | integer | yes | `>= 0`; `warning_count <= issue_count` |
| `parse_result_sha256` | text | yes | SHA when set (S5a `parse_result_sha256`) |
| `failure_code` | text | yes | `a_schedule_parser_failure_code_is_known`: `IS NULL OR IN (<23 issue codes>)` |
| `started_at` | timestamptz | no | `now()` |
| `completed_at` | timestamptz | yes | |

- `a_schedule_parser_run_records_its_outcome`: `running` ⇒ `completed_at`, the 4 counts, `parse_result_sha256`, `failure_code` NULL; `parsed` ⇒ `completed_at`, the 4 counts, `parse_result_sha256` NOT NULL and `failure_code` NULL; `failed` ⇒ `completed_at` NOT NULL, the 4 counts and `parse_result_sha256` NULL (`failure_code` NULL means the attempt ended without a deterministic code — abandoned or transient — D-09).
- UNIQUE `a_schedule_parser_run_is_identified_within_its_publication (parser_run_id, publication_id, principal_id)`.
- UNIQUE `a_schedule_attempt_starts_one_parser_run (publication_id, attempt_number)`.
- Partial unique index `a_schedule_parse_is_accepted_once ON (publication_id, parser_name, parser_version, profile_id, profile_version, document_sha256) WHERE status = 'parsed'`.
- FK `a_schedule_parser_run_names_its_publication (publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- FK `a_schedule_parser_run_names_its_job (operation_id, publication_id, principal_id) → schedule_jobs (operation_id, publication_id, principal_id)`.
- Index `schedule_parser_runs_by_publication (principal_id, publication_id, status)`.
- Triggers `a_schedule_parser_run_follows_its_lifecycle` (F6), F2 `schedule_parser_runs_refuse_truncate`.

### 4.6 `schedule_rows`

| Column | Type | Null | Rule |
|---|---|---|---|
| `row_id` | text | no | PK; `srow` |
| `principal_id`, `project_id`, `series_id`, `publication_id`, `parser_run_id` | text | no | ID CHECKs |
| `schedule_activity_id` | text | yes | `sact`; NULL at insert, set once (F7) |
| `row_ordinal`, `page_number`, `physical_line_ordinal` | integer | no | `a_schedule_row_position_is_positive`: each `>= 1` |
| `row_type` | text | no | `a_schedule_row_type_is_known`: `IN ('activity','ambiguous','milestone','project_summary','wbs_summary')` |
| `indent_level` | integer | yes | `a_schedule_row_indent_is_not_negative`: `IS NULL OR >= 0` |
| `parent_row_id` | text | yes | `srow` |
| `hierarchy_path` | text[] | yes | `a_schedule_row_hierarchy_is_bounded`: `IS NULL OR cardinality(hierarchy_path) <= 32` |
| `published_activity_id` | text | yes | `a_schedule_row_activity_id_is_exact`: `IS NULL OR (char_length BETWEEN 1 AND 256 AND = btrim(…))` |
| `activity_name` | text | yes | `a_schedule_row_name_is_bounded`: `IS NULL OR char_length BETWEEN 1 AND 2000` |
| `od_state`, `rd_state`, `start_state`, `finish_state` | text | no | `a_schedule_row_<x>_state_is_known`: `IN ('ambiguous','extraction_failed','published_blank','published_value')` |
| `od_value`, `rd_value` | numeric(12,3) | yes | `a_schedule_row_<od\|rd>_is_typed`: `(<x>_value IS NOT NULL) = (<x>_state = 'published_value') AND (<x>_value IS NULL OR <x>_value >= 0)` |
| `start_date`, `finish_date` | date | yes | `a_schedule_row_<start\|finish>_is_typed`: `(<x>_date IS NOT NULL) = (<x>_state = 'published_value')` |
| `start_marker`, `finish_marker` | text | yes | `a_schedule_row_<start\|finish>_marker_is_known`: `<x>_marker IS NULL OR (<x>_marker = '*' AND <x>_date IS NOT NULL)` |
| `bbox_x0_mpt`, `bbox_y0_mpt`, `bbox_x1_mpt`, `bbox_y1_mpt` | integer | no | `a_schedule_row_box_is_ordered`: `bbox_x0_mpt <= bbox_x1_mpt AND bbox_y0_mpt <= bbox_y1_mpt` |
| `page_width_mpt`, `page_height_mpt` | integer | no | `a_schedule_row_page_is_sized`: both `> 0` |
| `cell_evidence` | jsonb | no | `a_schedule_row_cell_evidence_is_bounded` (below) |
| `warning_codes` | text[] | no | default `'{}'`; `a_schedule_row_warnings_are_bounded`: `cardinality(warning_codes) <= 16`; `a_schedule_row_warning_codes_are_known`: `warning_codes <@ ARRAY[<23 issue codes>]` |
| `created_at` | timestamptz | no | `now()` |

Row-type identity, `a_schedule_row_identity_matches_its_type` (S5a §6.1 exactly):
`(row_type IN ('activity','milestone') AND published_activity_id IS NOT NULL AND activity_name IS NOT NULL) OR (row_type IN ('project_summary','wbs_summary') AND published_activity_id IS NULL AND activity_name IS NOT NULL) OR (row_type = 'ambiguous' AND published_activity_id IS NULL AND activity_name IS NULL)`.

Stable link only on ID-bearing rows, `a_schedule_row_links_only_an_activity_or_milestone`:
`schedule_activity_id IS NULL OR row_type IN ('activity','milestone')`. Because every such row
has a non-NULL `published_activity_id`, the `MATCH SIMPLE` stable-link FK below is always
checked when a link is set.

`cell_evidence` storage bound: `jsonb_typeof(cell_evidence) = 'object' AND cell_evidence ->> 'schema' = 'cpm-full-cells-v1' AND (cell_evidence -> 'cells') ?& ARRAY['activity_id','activity_name','original_duration','remaining_duration','start','finish'] AND octet_length(cell_evidence::text) <= 32768`.
The 16 KiB bound of R2 §18.6 is on the **canonical bytes** (`cell_evidence_bytes`, S5a §6.3),
which `jsonb::text` does not reproduce (it adds a space after every `:` and `,`, at most
doubling the length; non-ASCII is shorter than `\uXXXX`), so the database bound is 2 × 16,384
and the exact 16,384 bound is the application validation hook (section 5.3,
`validate_row_for_persistence`) — D-20.

Uniques, FKs, indexes:

- UNIQUE `a_schedule_row_ordinal_is_unique_within_its_run (parser_run_id, row_ordinal)` (publication order).
- UNIQUE `a_schedule_row_is_identified_within_its_run (row_id, parser_run_id)` (parent target).
- FK `a_schedule_row_belongs_to_its_run (parser_run_id, publication_id, principal_id) → schedule_parser_runs`.
- FK `a_schedule_row_belongs_to_its_publication (publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- FK `a_schedule_row_parent_is_in_its_run (parent_row_id, parser_run_id) → schedule_rows (row_id, parser_run_id)`.
- FK `a_schedule_row_links_its_exact_activity (schedule_activity_id, principal_id, series_id, published_activity_id) → schedule_activities (schedule_activity_id, principal_id, series_id, published_activity_id)` — same Principal, same Series, **same exact published ID**.
- Index `schedule_rows_by_published_id (parser_run_id, published_activity_id) WHERE published_activity_id IS NOT NULL`.
- Index `schedule_rows_by_stable_activity (principal_id, schedule_activity_id, publication_id) WHERE schedule_activity_id IS NOT NULL`.
- Index `schedule_rows_by_parent (parser_run_id, parent_row_id) WHERE parent_row_id IS NOT NULL`.
- Triggers `a_schedule_row_changes_only_by_linking` (F7), F2 `schedule_rows_refuse_truncate`.

### 4.7 `schedule_import_issues` (append-only)

| Column | Type | Null | Rule |
|---|---|---|---|
| `issue_id` | text | no | PK; `siss` |
| `principal_id`, `project_id`, `series_id`, `publication_id` | text | no | ID CHECKs |
| `parser_run_id` | text | yes | `sprun` |
| `severity` | text | no | `a_schedule_issue_severity_is_known`: `IN ('error','warning')` |
| `code` | text | no | `a_schedule_issue_code_is_known`: `IN (<23 issue codes>)` |
| `page_number`, `row_ordinal` | integer | yes | `a_schedule_issue_position_is_positive`: each `IS NULL OR >= 1` |
| `field` | text | yes | `a_schedule_issue_field_is_known`: `IS NULL OR IN ('activity_id','activity_name','finish','hierarchy','original_duration','remaining_duration','start')` |
| `created_at` | timestamptz | no | `now()` |

- `a_schedule_issue_severity_matches_its_code`: `(severity = 'warning') = (code IN ('duplicate_text_object_collapsed','header_od_occluded'))` (S5a `ISSUE_SEVERITY`).
- `a_schedule_issue_row_has_its_run`: `row_ordinal IS NULL OR parser_run_id IS NOT NULL`.
- No raw text, filename, locator, exception, stack or path column (R2 §18.7).
- FK `a_schedule_issue_belongs_to_its_publication (publication_id, principal_id, project_id, series_id) → schedule_publications` U3.
- FK `a_schedule_issue_belongs_to_its_run (parser_run_id, publication_id, principal_id) → schedule_parser_runs` (applies only when `parser_run_id` is set).
- FK `a_schedule_issue_names_a_row_of_its_run (parser_run_id, row_ordinal) → schedule_rows (parser_run_id, row_ordinal)` (applies only when both set).
- Index `schedule_import_issues_by_publication (principal_id, publication_id, severity, code)`.
- Triggers F1 `schedule_import_issues_are_append_only` (`BEFORE UPDATE OR DELETE`), `a_schedule_issue_is_recorded_while_processing` (F8, `BEFORE INSERT`), F2 `schedule_import_issues_refuse_truncate`.

### 4.8 The composite FK graph (summary)

| From | To | Binds |
|---|---|---|
| series | `projects` | same Principal |
| publications | series | same Principal/Project/Series |
| publications | `enrollments` | enrollment owned by the Principal |
| publications | `enrollment_objects` | object enrolled |
| publications | `source_object_versions` | version of that object |
| publications | publications (supersedes) | same Principal/Project/Series |
| publications | parser runs (accepted) | run of this publication |
| activities | series | same Principal/Project/Series |
| jobs | publications | same Principal |
| parser runs | publications, jobs | same Principal/Project/Series; this publication's one job |
| rows | parser runs, publications, rows (parent), activities | same run; same Series; same run parent; exact-ID stable link |
| issues | publications, parser runs, rows | same publication; same run; a row of that run |

The 4 FKs into existing tables (series → `projects`; publications → `enrollments`, `enrollment_objects`, `source_object_versions`) are added by `ALTER TABLE` at the very end of `upgrade()` (section 6, R6-F02); every other FK is inline or, for the accepted run, added right after the run table. All `ON DELETE RESTRICT` (deliberate; U-10). No runtime path deletes from `projects`, `enrollments`,
`enrollment_objects`, `sources`, `source_objects` or `source_object_versions` (`git grep` of
`.delete(`/`DELETE FROM` over `src` and `apps` at the basis finds none).

### 4.9 Existing tables

Only the 2 database-only uniques of section 3.4. No other existing table, column, CHECK,
trigger, index or vocabulary changes; no legacy `schedule.*`/`procore` table is touched.
`tables.py` gains a comment beside `enrollments` and beside `source_object_versions` naming
the new database-only constraint and its revision.

### 4.10 Functions and triggers

All trigger functions (F1–F8) are `LANGUAGE plpgsql`, in `knowledge`, take no argument, and raise with
`ERRCODE = 'restrict_violation'` (transition/immutability) or `'check_violation'` (a
deferred completeness rule). Messages carry no identifier or content.

| # | Function | Attached as | Rule |
|---|---|---|---|
| F1 | `schedule_relations_are_append_only()` | `BEFORE UPDATE OR DELETE FOR EACH ROW` on series, activities, import issues | `'% is append-only', TG_TABLE_NAME` (S1 body) |
| F2 | `schedule_relations_refuse_truncate()` | `BEFORE TRUNCATE FOR EACH STATEMENT` on all 7 | refuses only when the table holds a row (S1 body) |
| F3 | `a_schedule_publication_follows_its_lifecycle()` | `BEFORE INSERT OR UPDATE OR DELETE FOR EACH ROW` on publications | see 4.10.1 |
| F4 | `a_schedule_publication_has_its_job()` | constraint trigger `AFTER INSERT`, deferred, on publications | at commit `EXISTS (SELECT 1 FROM knowledge.schedule_jobs WHERE publication_id = NEW.publication_id AND principal_id = NEW.principal_id)`, else `check_violation` (D-12) |
| F5 | `a_schedule_job_keeps_its_identity()` | `BEFORE INSERT OR UPDATE OR DELETE FOR EACH ROW` on jobs | section 4.4 |
| F6 | `a_schedule_parser_run_follows_its_lifecycle()` | `BEFORE INSERT OR UPDATE OR DELETE FOR EACH ROW` on parser runs | see 4.10.2 |
| F7 | `a_schedule_row_changes_only_by_linking()` | `BEFORE INSERT OR UPDATE OR DELETE FOR EACH ROW` on rows | see 4.10.3 |
| F8 | `a_schedule_issue_is_recorded_while_processing()` | `BEFORE INSERT FOR EACH ROW` on import issues | publication `status = 'processing'`; when `parser_run_id` is set, that run `status = 'running'` |
| F9 | `schedule_run_outcome(run_id text) RETURNS text` | not a trigger: `LANGUAGE sql STABLE`, called by F3, F6 and the repository | the frozen S5a outcome ladder over the run's stored issues and rows (section 4.10.4) |

**Schema qualification (RR1-F01).** Every table a function body F1–F9 names is written
schema-qualified as `knowledge.<table>` (for example `knowledge.schedule_jobs`,
`knowledge.schedule_parser_runs`, `knowledge.schedule_rows`,
`knowledge.schedule_import_issues`, `knowledge.schedule_publications`), so no body depends on
`search_path`; the shorthand table names in this section's prose denote those qualified names.

**F9 call sites (RR1-F03).** F9 takes a bare `run_id` and carries no Principal predicate, and
the principal-partition registry scan cannot see inside SQL functions. It is therefore called
only (i) inside triggers F3/F6 with `NEW.accepted_parser_run_id` or the row's own
`parser_run_id`, which the composite FKs already bind to the row's Principal, or (ii) by
`SqlScheduleRepository` with a run identifier it has just read under `_mine` (partitioned) in
the same transaction. No other caller may pass a caller-supplied run identifier.

Triggers are created with the default `ENABLE` (origin) mode, as every lineage trigger, so
`session_replication_role = replica` bypasses them; `ENABLE ALWAYS` is **not** adopted (the
lineage test harnesses seed under replica, and the owner can disable any trigger anyway —
U-06 stands; R6-F14 item 5 declined).

#### 4.10.1 F3 — publication lifecycle

- **INSERT:** `NEW.status = 'queued'` (the progress CHECK then forces every processing column
  NULL). When `supersedes_publication_id` is set, the predecessor's `source_version_id` must
  differ from `NEW.source_version_id` (the FK already proves same Principal/Project/Series).
- **DELETE:** refused.
- **UPDATE:** refused when `OLD.status IN ('complete','partial','review_required','failed')`
  (terminal immutability). Admission columns never change: `publication_id`,
  `principal_id`, `project_id`, `series_id`, `enrollment_id`, `source_object_id`,
  `source_version_id`, `idempotency_key`, `request_digest`, `publication_role`,
  `baseline_kind`, `expected_data_date`, `supersedes_publication_id`, `admitted_at`
  (`IS DISTINCT FROM` on each). Legal transitions only:

| From → to | Allowed changes besides `updated_at` |
|---|---|
| `queued → processing` | `processing_started_at` NULL → value |
| `processing → processing` | `document_sha256`/`document_size_bytes` NULL → value (set once); nothing else |
| `processing → complete \| partial \| review_required` | the terminal columns; `document_*` unchanged if already set |
| `processing → failed` | `completed_at`, `issue_count`; `document_*` unchanged if already set |

  Any other pair (including `queued → terminal` and a same-status `queued` update) is refused.
- **No running run at terminal (R6-F03):** every transition to a terminal status is refused
  while any `schedule_parser_runs` row of this publication has `status = 'running'`.
- **Terminal verification** on `processing → complete|partial|review_required` (reads only):
  the accepted run (FK proves it belongs to this publication) has `status = 'parsed'` and
  `document_sha256 = NEW.document_sha256`; `NEW.page_count = run.page_count`;
  `NEW.row_count = run.row_count = count(rows of the run)`;
  `NEW.activity_count = count(rows of the run with row_type IN ('activity','milestone'))`;
  `NEW.ambiguous_row_count = count(rows with row_type = 'ambiguous')`;
  `NEW.issue_count = run.issue_count = count(issues with parser_run_id = run)`;
  **`NEW.status = knowledge.schedule_run_outcome(NEW.accepted_parser_run_id)`** (R6-F01: the
  terminal status is the issue-derived outcome, never the caller's choice; a run whose
  derived outcome is `failed` cannot be accepted at all);
  for `complete|partial`: **no** activity/milestone row of the run has
  `schedule_activity_id IS NULL`; for `review_required`: **no** row of the run has
  `schedule_activity_id IS NOT NULL`.
- **Failed verification** on `processing → failed`: `NEW.issue_count` equals the count of
  this publication's issue rows and at least one of them has `severity = 'error'`.

#### 4.10.2 F6 — parser run lifecycle

- **INSERT:** `status = 'running'`; the publication has `status = 'processing'` and
  `document_sha256 = NEW.document_sha256` (bytes are pinned before parsing).
- **DELETE:** refused.
- **UPDATE:** refused when `OLD.status <> 'running'`; refused unless the publication has
  `status = 'processing'` (R6-F03: no run changes under a terminal publication); `NEW.status` must differ from
  `OLD.status` (`running → parsed | failed` only); every column except `status`,
  `completed_at`, the 4 counts, `parse_result_sha256` and `failure_code` is unchanged.
  `running → parsed` additionally requires `NEW.row_count = count(rows of the run)`,
  `NEW.issue_count = count(issues of the run)`, `NEW.warning_count = count(issues of the run
  with severity 'warning')`, and **no issue of the run carries a failed-ladder code**
  (section 4.10.4; R6-F01): a FAILED parse ends only through `fail_publication`.

#### 4.10.4 F9 — the frozen outcome ladder (S5a `derive_outcome`)

The revision freezes the S5a §5.13 ladder as literal sets (sorted), and
`knowledge.schedule_run_outcome(run_id)` returns, first match wins:

| # | Condition over the run's `schedule_import_issues.code` and `schedule_rows.row_type` | Result |
|---|---|---|
| 1 | any code in `('bounds_exceeded','corrupt_pdf','encrypted_pdf','image_only_pdf','parser_exception','processing_budget_exceeded','source_too_large','unsupported_layout','unsupported_media_type')` | `'failed'` |
| 2 | any code in `('activity_like_row_missing_id','duplicate_activity_id','expected_data_date_mismatch','header_signature_mismatch','page_metadata_mismatch','row_wrap_unsupported')`, or any row with `row_type = 'ambiguous'` | `'review_required'` |
| 3 | any code in `('ambiguous_cell','hierarchy_ambiguous','invalid_date','invalid_duration','overlapping_cell_text')` | `'partial'` |
| 4 | otherwise (`header_od_occluded`, `duplicate_text_object_collapsed` do not downgrade) | `'complete'` |

`source_version_changed` is in no set: it is never a run issue (S5a raises on it; F8 lets it
in only as a run-less issue). The 3 sets plus the 2 warnings plus `source_version_changed`
partition the 23 codes exactly; a FAST test asserts the partition against
`model._FAILED_CODES`, `_REVIEW_CODES`, `_PARTIAL_CODES` and `ISSUE_SEVERITY`, and a database
parity test asserts `schedule_run_outcome` equals `derive_outcome` for every single code and
for the ambiguous-row case (`test_sql_outcome_ladder_equals_derive_outcome`).

#### 4.10.3 F7 — rows: immutable content, set-once link

- **INSERT:** `NEW.schedule_activity_id IS NULL`; the run has `status = 'running'`; the
  publication has `status = 'processing'`; a set `parent_row_id` names a row whose
  `row_ordinal < NEW.row_ordinal` (the FK already proves it is in the same run).
- **DELETE:** refused.
- **UPDATE:** `to_jsonb(NEW) - 'schedule_activity_id' = to_jsonb(OLD) - 'schedule_activity_id'`
  (every content/provenance column unchanged); `OLD.schedule_activity_id IS NULL AND
  NEW.schedule_activity_id IS NOT NULL` (NULL → value, once; never cleared or changed); the
  run has `status = 'parsed'`; the publication has `status = 'processing'` (no link once
  terminal). The stable-link FK proves Principal, Series and exact published ID.

### 4.11 Grants

The revision executes **no `GRANT` and no `REVOKE`** and does not call
`src/my_pa/infrastructure/database/mcp_object_grants.py`; tables are owned by the role that
runs the migration, exactly as every S1–S3.1 lineage table. Roles: the migrating/application
role (owner) holds owner privileges; **`my_pa_mcp_ro`, `my_pa_mcp_rw` and `PUBLIC` hold
none**; the Record Event `my_pa_owner`/`my_pa_migrator`/`my_pa_runtime` roles are not
referenced. Tested (R6-F11) statically (no `GRANT`/`REVOKE`/`mcp_object_grants` in the
revision) and in the catalog after empty→head: `pg_class.relacl IS NULL` for all 7 tables;
on the scratch cluster the test creates `my_pa_mcp_ro`/`my_pa_mcp_rw` as `NOLOGIN` roles if
absent and asserts `has_table_privilege(<role>, 'knowledge.<table>',
'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')` is false for `PUBLIC`, both roles and all 7 tables;
`relacl` of `knowledge.enrollments` and `knowledge.source_object_versions` is byte-identical
before upgrade, after upgrade and after downgrade (`test_no_grant_beyond_the_owner`,
`test_live_table_acls_are_unchanged`). Production default privileges and runtime-role reach
are a blocking operator gate (section 9.3).

---

## 5. Domain and persistence symbols

### 5.1 Enums (`src/my_pa/domain/schedule/model.py`)

Reused unchanged from S5a: `ScheduleRowType`, `ScheduleCellState`, `ScheduleIssueSeverity`,
`ScheduleFieldCode`, `ScheduleIssueCode`, `SchedulePublicationStatus`, `ISSUE_SEVERITY`,
`TERMINAL_OUTCOMES`. New (`StrEnum`, lower-snake values, declaration order canonical):

| Enum | Members |
|---|---|
| `SchedulePublicationRole` | `UPDATE`, `BASELINE`, `REFERENCE` |
| `ScheduleBaselineKind` | `WORKING`, `CONTRACT` |
| `ScheduleParserRunStatus` | `RUNNING`, `PARSED`, `FAILED` |
| `ScheduleAdmissionOutcome` | `CREATED`, `REPLAYED` |
| `ScheduleAdmissionRefusal` | `PROJECT_NOT_FOUND`, `SERIES_NOT_FOUND`, `ENROLLMENT_NOT_FOUND`, `SOURCE_OBJECT_NOT_ENROLLED`, `SOURCE_VERSION_NOT_FOUND`, `UNSUPPORTED_MEDIA_TYPE`, `MEDIA_TYPE_NOT_ENROLLED`, `SOURCE_TOO_LARGE`, `SUPERSEDED_PUBLICATION_NOT_FOUND`, `SUPERSEDED_PUBLICATION_NOT_TERMINAL`, `SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION`, `SUPERSEDED_PUBLICATION_HAS_SUCCESSOR`, `IDEMPOTENCY_KEY_CONFLICT`, `SOURCE_VERSION_CONFLICT` |

`ScheduleChangeKind` is WP-03. Constants: `MAX_SERIES_NAME_CHARACTERS = 200`,
`MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS = 256`, `MAX_ACTIVITY_NAME_CHARACTERS = 2000`,
`MAX_HIERARCHY_LABEL_CHARACTERS = 2000`, `MAX_CELL_EVIDENCE_BYTES = 16384`,
`MAX_SCHEDULE_SOURCE_BYTES = 16777216`, `MAX_SCHEDULE_BATCH = 1000`,
`MAX_SCHEDULE_IDEMPOTENCY_KEY_CHARACTERS = 128`, `SCHEDULE_IDEMPOTENCY_KEY_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")` (R6-F07), `SCHEDULE_MEDIA_TYPE = "application/pdf"`.

### 5.2 Records (frozen slots dataclasses, `__post_init__` invariants, fixed `ValueError` messages, IDs via `validate_identifier`)

| Record | Fields |
|---|---|
| `ScheduleSeriesName` | `name: str`, `key: str` (built only by `normalize_series_name`) |
| `ScheduleSeries` | `series_id`, `principal_id`, `project_id`, `name`, `name_key`, `created_at: datetime` |
| `ScheduleImportRequest` | `project_id`, `series_id: str \| None`, `series_name: ScheduleSeriesName \| None` (exactly one set), `enrollment_id`, `source_object_id`, `source_version_id`, `publication_role`, `baseline_kind: ScheduleBaselineKind \| None` (set iff `BASELINE`), `expected_data_date: date \| None`, `supersedes_publication_id: str \| None`, `idempotency_key: str` (matches `SCHEDULE_IDEMPOTENCY_KEY_PATTERN`) |
| `SchedulePublication` | every section 4.2 column, typed (`status: SchedulePublicationStatus`, roles as enums, counts `int \| None`) |
| `ScheduleParserIdentity` | `parser_name`, `parser_version`, `profile_id`, `profile_version: int`, `pypdfium2_version`, `pdfium_version` (from `ScheduleParseResult` + `ScheduleParseEngine`) |
| `ScheduleParserRun` | every section 4.5 column, typed |
| `StableScheduleActivity` | `schedule_activity_id`, `principal_id`, `project_id`, `series_id`, `published_activity_id`, `created_at` |
| `StoredScheduleRow` | `row_id`, `parser_run_id`, `publication_id`, `schedule_activity_id: str \| None`, `parent_row_id: str \| None`, `row: ParsedScheduleRow` (content is the S5a record, field for field) |
| `ScheduleImportIssue` | `issue_id`, `publication_id`, `parser_run_id: str \| None`, `issue: ScheduleParseIssue` |
| `ScheduleLease` | `operation_id`, `owner`, `attempt: int` (from `LeasedJob`) |
| `ScheduleAdmission` | `series: ScheduleSeries`, `publication: SchedulePublication`, `operation_id: str`, `outcome: ScheduleAdmissionOutcome`, `series_created: bool` |
| `SchedulePlan` | `publication: SchedulePublication`, `attempt: int`, `terminal: bool`, `max_fetch_bytes: int \| None` (= `min(enrollments.max_bytes, 16777216)` when `terminal` is false, `None` when true) — R6-F05 |
| `ScheduleParserRunStart` | `run: ScheduleParserRun`, `reused: bool` |
| `ScheduleCanonicalizationProgress` | `linked: int`, `created: int`, `remaining: int` |
| `ScheduleFinalization` | `accepted_parser_run_id`, `published_schedule_title`, `data_date`, `run_date` — **no status field**: `finalize_publication` derives the status (R6-F01) |

### 5.3 Pure functions

| Function | Module | Contract |
|---|---|---|
| `normalize_series_name(raw: str) -> ScheduleSeriesName` | `model.py` | R2 §10.1: NFC; every run of `str.isspace()` characters → one ASCII space; strip; reject (raise `InvalidScheduleSeriesNameError(ValueError)`) when any character's `unicodedata.category` is `Cc`, `Cf`, `Cs`, `Co` or `Cn`, or length not in 1..200; `key = unicodedata.normalize("NFC", name.casefold())` |
| `schedule_import_request_digest(principal_id: str, request: ScheduleImportRequest) -> str` | `canonical.py` | `hashlib.sha256(b"cpm-schedule-import-v1\n" + canonical_json_bytes({"principal_id": principal_id, "request": {...}})).hexdigest()`, where `request` has exactly the keys `project_id`, `series_id`, `series_name_key`, `enrollment_id`, `source_object_id`, `source_version_id`, `publication_role`, `baseline_kind`, `expected_data_date` (ISO `YYYY-MM-DD`), `supersedes_publication_id`, absent values `null`; `idempotency_key` is excluded; `canonical_json_bytes` is the S5a encoder (sorted keys, compact, ASCII, no NaN) — D-14 |
| `validate_row_for_persistence(row: ParsedScheduleRow) -> None` | `model.py` | raises `ScheduleRowBoundsError(ValueError)` when `len(cell_evidence_bytes(row)) > 16384`, the published ID exceeds 256, the name exceeds 2000, any hierarchy label exceeds 2000 or is empty, or the path exceeds 32; the repository calls it for every row before any insert of a batch (lives in `canonical.py` if the import order requires). **Failure path (ruling (c)):** `insert_rows` raises `ScheduleRowBoundsError` and writes nothing; the attempt (WP-03's handler; WP-01's test plays it) then calls `fail_publication(BOUNDS_EXCEEDED, parser_run_id=<the running run>)` — a deterministic `failed`, never a transient retry (`test_row_bounds_violation_fails_the_publication`). The per-label bound (non-empty, ≤ 2000) is **domain-only**: the database checks only `cardinality(hierarchy_path) <= 32`, since a CHECK cannot iterate array elements without a helper function |
| `effective_publication_status(status: SchedulePublicationStatus, *, job_failed: bool) -> SchedulePublicationStatus` | `model.py` | `FAILED` when `status in {QUEUED, PROCESSING}` and `job_failed`; else `status` (R2 §10.6, no write-on-read) |

The database half of §10.1 is the section 4.1 CHECK (length, trim, no double space, no ASCII/C1
control); the category rule and the casefold key are domain-only (SQL has no casefold).

### 5.4 Ports (`src/my_pa/contracts/ports.py`, after the Constraint Management ports)

```python
class ScheduleLeaseLostError(Exception): ...           # the caller's lease is gone; nothing written
class ScheduleAdmissionRejectedError(Exception):       # typed rejection; the UoW rolls back
    reason: ScheduleAdmissionRefusal
class ScheduleIntegrityError(Exception):               # a §24 precondition failed (fixed code, no content)
    code: str

class ScheduleRepository(ABC):
    # admission (one transaction, no lease)
    def admit_publication(self, principal_id: str, request: ScheduleImportRequest,
                          request_digest: str) -> ScheduleAdmission: ...
    # worker transactions (each begins with hold_lease)
    def begin_processing(self, principal_id: str, publication_id: str,
                         lease: ScheduleLease) -> SchedulePlan: ...
    def pin_document(self, principal_id: str, publication_id: str, lease: ScheduleLease,
                     document_sha256: str, document_size_bytes: int) -> None: ...
    def start_parser_run(self, principal_id: str, publication_id: str, lease: ScheduleLease,
                         identity: ScheduleParserIdentity) -> ScheduleParserRunStart: ...
    def insert_rows(self, principal_id: str, parser_run_id: str, lease: ScheduleLease,
                    rows: Sequence[ParsedScheduleRow]) -> int: ...
    def insert_issues(self, principal_id: str, publication_id: str, lease: ScheduleLease,
                      parser_run_id: str | None, issues: Sequence[ScheduleParseIssue]) -> int: ...
    def finish_parser_run(self, principal_id: str, parser_run_id: str, lease: ScheduleLease, *,
                          parsed: ScheduleParseCounts | None, parse_result_sha256: str | None,
                          failure_code: ScheduleIssueCode | None) -> ScheduleParserRun: ...
    def canonicalize_batch(self, principal_id: str, parser_run_id: str, lease: ScheduleLease,
                           limit: int = 1000) -> ScheduleCanonicalizationProgress: ...
    def finalize_publication(self, principal_id: str, publication_id: str, lease: ScheduleLease,
                             finalization: ScheduleFinalization) -> SchedulePublication: ...
    def fail_publication(self, principal_id: str, publication_id: str, lease: ScheduleLease,
                         code: ScheduleIssueCode, parser_run_id: str | None) -> SchedulePublication: ...
    # point reads (no lease, partitioned; cross-Principal answers None)
    def get_series(self, principal_id: str, series_id: str) -> ScheduleSeries | None: ...
    def get_publication(self, principal_id: str, publication_id: str) -> SchedulePublication | None: ...
    def get_effective_status(self, principal_id: str,
                             publication_id: str) -> SchedulePublicationStatus | None: ...
    def get_parser_runs(self, principal_id: str,
                        publication_id: str) -> tuple[ScheduleParserRun, ...]: ...

class ScheduleUnitOfWork(ABC):
    def __enter__(self) -> ScheduleUnitOfWork: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...   # commit on success, else roll back
    @property
    def schedules(self) -> ScheduleRepository: ...
```

`ScheduleUnitOfWork` is **not** added to `UnitOfWork`, has no `record_events` member and no
`projects` member (D-21). Paged/cursor reads are WP-03.

### 5.5 Transaction methods (`SqlScheduleRepository`, `src/my_pa/infrastructure/persistence/schedule.py`)

**Lease rule (every worker method).** First statement: `hold_lease(connection,
lease.operation_id, owner=lease.owner, plane=SCHEDULE_JOBS)`; `False` →
`ScheduleLeaseLostError` (the UoW rolls back; nothing written). Then the job row is read
partitioned and must name `publication_id` (or the run's publication) and the caller's
Principal, else `ScheduleLeaseLostError`. Without a worker process, tests obtain a lease with
`claim_job(connection, owner=…, lease_seconds=…, principal_id=…, plane=SCHEDULE_JOBS)` in a
committed transaction, and expire it by `UPDATE schedule_jobs SET lease_expires_at = now() -
interval '1 second'` (permitted by F5 on a running row).

| Method | Order inside the one transaction | Outcomes |
|---|---|---|
| `admit_publication` | (1) partitioned read of a publication by `(principal_id, idempotency_key)`: found → digest equal ⇒ `REPLAYED` (series, publication, its job's `operation_id`), else raise `IDEMPOTENCY_KEY_CONFLICT`; (2) project owned (`_mine(projects)`) else `PROJECT_NOT_FOUND`; (3) enrollment owned else `ENROLLMENT_NOT_FOUND`; `(enrollment_id, source_object_id)` in `enrollment_objects` (joined) else `SOURCE_OBJECT_NOT_ENROLLED`; `(source_version_id, source_object_id)` in `source_object_versions` else `SOURCE_VERSION_NOT_FOUND`; `media_type = 'application/pdf'` else `UNSUPPORTED_MEDIA_TYPE`; `'application/pdf' = ANY(enrollments.media_types)` else `MEDIA_TYPE_NOT_ENROLLED`; `size_bytes IS NULL OR <= 16777216` else `SOURCE_TOO_LARGE`; (4) series: by `series_id` (partitioned, same project) else `SERIES_NOT_FOUND`, or by `(project_id, name_key)` — absent ⇒ create later; (5) existing series: publication by `(principal_id, series_id, source_version_id)` → same `publication_role`, `baseline_kind`, `expected_data_date`, `supersedes_publication_id` ⇒ `REPLAYED`, else `SOURCE_VERSION_CONFLICT`; (6) `supersedes_publication_id`: `SELECT … FOR UPDATE` partitioned in the same project/series else `SUPERSEDED_PUBLICATION_NOT_FOUND`; effective status terminal else `…_NOT_TERMINAL`; different `source_version_id` else `…_SAME_SOURCE_VERSION`; no publication already supersedes it else `…_HAS_SUCCESSOR`; (7) writes: series `INSERT … ON CONFLICT (principal_id, project_id, name_key) DO NOTHING RETURNING`, re-select on a lost race; publication `INSERT … ON CONFLICT DO NOTHING RETURNING`; no row ⇒ re-run (1), (5), (6) and classify (replay or the matching conflict); inserted ⇒ `enqueue_job(connection, publication_id, plane=SCHEDULE_JOBS)` | `ScheduleAdmission(CREATED \| REPLAYED)`; every rejection is `ScheduleAdmissionRejectedError(reason)` raised, so the UoW rolls back any series row of step 7 (D-16). A cross-Principal Project/Series/enrollment/publication is the matching `*_NOT_FOUND`, indistinguishable from absent |
| `begin_processing` | lease; publication `FOR UPDATE` (partitioned); `queued` → `processing` (`processing_started_at = now()`); `processing` unchanged; **terminal → `SchedulePlan(terminal=True, max_fetch_bytes=None)` and no write** (R6-F05: a reclaimed attempt after a committed terminal outcome lets the handler return normally so the generic job completes, R2 §22/§24); otherwise read `enrollments.max_bytes` | `SchedulePlan` |
| `pin_document` | lease; publication `FOR UPDATE`; status `processing`; NULL → set; already set and equal ⇒ no-op; different ⇒ `ScheduleIntegrityError("document_changed")` | — |
| `start_parser_run` | lease; publication must be `processing` with a pinned document; existing `parsed` run with the exact identity and document digest ⇒ return it (`reused=True`); existing `running` run of `lease.attempt` ⇒ return it; every `running` run of an earlier attempt → `failed` (`failure_code` NULL, `completed_at = now()`); insert a `running` run (`attempt_number = lease.attempt`, `operation_id = lease.operation_id`) | `ScheduleParserRunStart` |
| `insert_rows` | `1 <= len(rows) <= 1000` else `ValueError`; `validate_row_for_persistence` on every row first; lease; run `running`; **`row.row_ordinal` is stored verbatim** (R6-F04): the batch's ordinals must be strictly consecutive and its first must equal `coalesce(max(row_ordinal), 0) + 1` of the run, else `ScheduleIntegrityError("row_ordinal_gap")` and nothing is written; issue `srow` IDs; map `parent_row_ordinal` → `parent_row_id` from the same run (this batch or earlier); `cell_evidence = cell_evidence_object(row)`; `bbox_*_mpt` from `row.box`; one multi-row insert. Issues naming a `row_ordinal` are inserted only after that row (the issue→row FK is immediate). No write batch is retried inside one attempt: any failure releases the attempt, and F6's count equalities fail a duplicated issue batch closed (intended backstop) | rows inserted |
| `insert_issues` | `0 < len(issues) <= 1000`; lease; `parser_run_id` (if set) is a `running` run of the publication; severity from the record (DB re-checks) | issues inserted |
| `finish_parser_run` | lease; exactly one of `parsed` (with digest) / `failure_code` path; `parsed`: counts from `ScheduleParseCounts` (`rows`, `pages`, `issues`, `warnings`); F6 verifies against stored rows/issues | `ScheduleParserRun` |
| `canonicalize_batch` | lease; run `parsed`, publication `processing`; **outcome gate (R6-F01): `schedule_run_outcome(run) IN ('complete','partial')`**, plus no duplicate `published_activity_id` among the run's activity/milestone rows, else `ScheduleIntegrityError("identity_gate")`; next ≤ `limit` unlinked activity/milestone rows in `row_ordinal` order; `INSERT INTO schedule_activities … ON CONFLICT (principal_id, series_id, published_activity_id) DO NOTHING` with the values **sorted by `published_activity_id`** so concurrent canonicalizations of 2 publications of one Series take index locks in one order (R6-F12; a `40P01` deadlock is still a transient attempt failure, and re-entry is safe); select their IDs; `UPDATE schedule_rows SET schedule_activity_id = … WHERE schedule_activity_id IS NULL` | progress (re-entrant after lease loss: already-linked rows are skipped) |
| `finalize_publication` | lease; publication `FOR UPDATE`; accepted run `parsed`; **status = `schedule_run_outcome(run)`** (R6-F01; `failed` ⇒ `ScheduleIntegrityError("status_mismatch")`); counts derived by SQL from the run's rows/issues; `COMPLETE`/`PARTIAL` require zero unlinked ID-bearing rows, `REVIEW_REQUIRED` zero linked rows, else `ScheduleIntegrityError("incomplete_canonicalization")`; **every other `running` run of the publication → `failed` (`failure_code` NULL, `completed_at = now()`)** (R6-F03); one UPDATE to terminal (F3 re-verifies all of it) | `SchedulePublication` |
| `fail_publication` | lease; publication `FOR UPDATE`, `processing`; `ISSUE_SEVERITY[code]` must be `ERROR`; when `parser_run_id` is given that run must still be `running` (F8): insert the issue of `code` unless an issue with the same `code` and `parser_run_id IS NOT DISTINCT FROM` the given run exists (R6-F14), then set the run `failed` with `failure_code = code`; without a run (for example `source_version_changed`) insert the run-less issue under the same de-duplication; **then every remaining `running` run of the publication → `failed` (`failure_code` NULL)** (R6-F03); then status `failed`, `issue_count` = this publication's issue rows, `completed_at = now()` — one transaction | `SchedulePublication` |
| `get_effective_status` | partitioned publication + `job_for(…, plane=SCHEDULE_JOBS)` (which derives `failed` for an abandoned final attempt); `effective_publication_status` | status or `None` |

### 5.6 `SqlAlchemyScheduleUnitOfWork`

`__init__(self, engine: Engine)`; `__enter__` opens `engine.begin()` and refuses re-entry;
`__exit__` commits on success and rolls back otherwise; `schedules` returns
`SqlScheduleRepository(connection)` and raises `RuntimeError` outside a transaction — the
`SqlAlchemyConstraintManagementUnitOfWork` shape minus the Record Event buffer. Isolation:
the engine default (`READ COMMITTED`); races are resolved by the uniques plus
`ON CONFLICT DO NOTHING` re-reads and the predecessor `FOR UPDATE`.

### 5.7 Idempotency outcomes (R2 §23)

| Situation | Result |
|---|---|
| same key, same digest | `REPLAYED`, original publication and `operation_id` |
| same key, different digest | `IDEMPOTENCY_KEY_CONFLICT` |
| different key, same Principal+Series+source version, same role/baseline kind/expected date/supersedes | `REPLAYED` |
| … any of those 4 differ | `SOURCE_VERSION_CONFLICT` |
| same source version, different Series (same Principal) | `CREATED`, a separate publication |
| second successor of one predecessor | `SUPERSEDED_PUBLICATION_HAS_SUCCESSOR` (partial unique under a race) |
| second job for one publication | impossible (`UNIQUE (publication_id)`; enqueue only on insert) |
| second `parsed` run with the exact identity | impossible (partial unique); `start_parser_run` reuses it |
| second row at one ordinal | impossible (unique) |
| second Stable Activity for one exact ID in a Series | impossible (unique; `ON CONFLICT DO NOTHING`) |
| second link of a row | refused by F7 |

---

## 6. Migration plan

- File `migrations/versions/<YYYYMMDD>_<rev>_cpm_workbench_foundation.py`, generated by
  `alembic revision` against the re-authenticated sole head; `<rev>` is whatever Alembic
  issues (12 hex). `down_revision = "023f8f7eb499"`. Docstring in the S1 style: what it
  does in order, "No role grant changes", "No backfill", downgrade refusal, operator
  authority.
- Imports: `from alembic import op`, `typing.Final` only — no `my_pa` module.
- Frozen literals: the 23 issue codes, 7 field codes, 5 row types, 4 cell states, 6
  publication statuses, 3 run statuses, 3 roles, 2 baseline kinds, 2 severities, 4 job
  states, 11 error codes, written out; none derived from an enum or `MetaData`.

**upgrade()** in order (R6-F02: every CPM object first, the live-table work last, so live
tables are locked only from step 6 to commit):

1. `SET LOCAL lock_timeout = '10s'` (transaction-local; section 3.4 step 1).
2. `CREATE TABLE` in order: `schedule_series`, `schedule_publications`,
   `schedule_activities`, `schedule_jobs`, `schedule_parser_runs`, `schedule_rows`,
   `schedule_import_issues`, each followed by its `CREATE [UNIQUE] INDEX` statements. These
   `CREATE TABLE` statements carry **no FK into an existing table** (no reference to
   `projects`, `enrollments`, `enrollment_objects` or `source_object_versions`) and no
   accepted-run FK; every FK among the 7 new tables is inline.
3. `ALTER TABLE knowledge.schedule_publications ADD CONSTRAINT
   a_schedule_publication_accepts_one_of_its_runs FOREIGN KEY …`.
4. `CREATE FUNCTION` F1–F9.
5. `CREATE TRIGGER` / `CREATE CONSTRAINT TRIGGER` (section 4.10), from a `_triggers()` tuple.
6. PK catalog preflight (section 3.4 step 2).
7. The 2 support uniques: `CREATE UNIQUE INDEX` ×2, then `ADD CONSTRAINT … USING INDEX` ×2.
8. The 4 FKs into existing tables by `ALTER TABLE … ADD CONSTRAINT`:
   `a_schedule_series_names_a_project_of_its_principal`,
   `a_schedule_publication_names_an_enrollment_of_its_principal`,
   `a_schedule_publication_names_an_enrolled_object`,
   `a_schedule_publication_names_a_version_of_its_object`.

`tables.py` declares every FK on its table as usual (only the accepted-run FK needs
`use_alter=True`); the ordering above is the revision's, and the
`test_frozen_ddl_names_every_declared_constraint` name parity still holds.

**downgrade()** in order:

1. `SET LOCAL lock_timeout = '10s'` (R6-F02, ruling (b): `DROP CONSTRAINT` on a live table
   takes `ACCESS EXCLUSIVE`).
2. Refusal `DO` block: `IF EXISTS (SELECT 1 FROM knowledge.schedule_series) OR EXISTS (…
   schedule_publications) OR … (all 7) THEN RAISE EXCEPTION 'cpm workbench rows exist;
   refusing to downgrade <rev>' USING ERRCODE = 'restrict_violation'`.
3. `DROP TRIGGER` in reverse; `DROP FUNCTION knowledge.<name>(<signature>)` in reverse
   (`(text)` for F9, `()` for the rest).
4. Drop `a_schedule_publication_accepts_one_of_its_runs`.
5. `DROP TABLE … RESTRICT` in reverse creation order (this removes the 4 FKs into existing
   tables with their tables).
6. `ALTER TABLE knowledge.source_object_versions DROP CONSTRAINT
   a_source_version_is_identified_with_its_object`; same for
   `an_enrollment_is_identified_within_its_principal` on `enrollments` — last, so live
   tables are locked only from step 5 to commit.

No audit or heartbeat vocabulary is restated in either direction.

---

## 7. Work split (at most 2 serial packages)

| Package | Owns (writes only these) |
|---|---|
| **I6-A** schema | `src/my_pa/domain/common/identifiers.py`; `src/my_pa/domain/schedule/model.py`, `canonical.py`, `__init__.py` (section 5.1–5.3 symbols); `src/my_pa/infrastructure/persistence/tables.py` (7 tables + 2 comments); `migrations/versions/<…>_cpm_workbench_foundation.py`; NEW `tests/schema/test_cpm_workbench_migration.py`; NEW `tests/database/test_cpm_workbench_schema_guards.py`; NEW `tests/unit/test_schedule_foundation_domain.py`; lockstep edits: `tests/unit/test_identifiers.py` (6 prefixes), `tests/architecture/test_capture_project_binding.py` (`TABLES_SHA256` + comment line), `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` (123 → 124 and its comment), `tests/architecture/test_cpm_full_parser_scope.py` (allowlist, D-18), `TABLES_ABOVE` in `tests/schema/test_audit_schema_migration.py` and `tests/schema/test_enrollment_objects_migration.py` (+7 tables), the head literal in every test module that pins `023f8f7eb499` as head (51 files at the basis, `git grep -l 023f8f7eb499 -- tests`; S3.1's own suites keep naming their revision and only move their `HEAD`), and the revision-count/head claims bound by `tests/architecture/test_readme_state_claims.py` and the spelled-count guard (`README.md`, `docs/architecture/00_ARCHITECTURE_INDEX.md`, `docs/architecture/system-context.md`, `ops/runbooks/gateway-operations.md`, `ops/runbooks/mcp-and-cli-operations.md`, and any other file those guards bind — re-measured, in each file's own style) |
| **I6-B** persistence | `src/my_pa/contracts/ports.py` (section 5.4); NEW `src/my_pa/infrastructure/persistence/schedule.py`; `src/my_pa/infrastructure/persistence/jobs.py` (`SCHEDULE_JOBS` + `__all__`); NEW `tests/database/test_cpm_workbench_persistence.py`; NEW FAST `tests/architecture/test_cpm_workbench_foundation_scope.py`; lockstep: `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` (registry), module/test-count and mypy-file pins in `docs/plans/mcv-completion-plan.md` and `docs/plans/relationship-intelligence-implementation-plan.md` (`tests/architecture/test_spelled_counts_match_the_sets_they_name.py::test_section_3_states_the_module_counts_it_says_it_derives`, `tests/architecture/test_claimed_test_counts_match_collection.py`; re-measured with the commands those rows name, dated paragraph, prior demoted to "Historical"), `tests/ci_shard_weights.json` only if `python -m tests.ci_shard verify` requires it |

I6-A lands first; I6-B starts from I6-A's head. Neither edits `apps/worker.py`,
`src/my_pa/infrastructure/persistence/worker_health.py`, `src/my_pa/application/*`,
`src/my_pa/bootstrap/*`, `tests/conftest.py`, or any S5a parser module.

---

## 8. Test plan and crosswalk

### 8.1 Modules and markers

| Module | Tier | Content |
|---|---|---|
| `tests/unit/test_schedule_foundation_domain.py` | FAST | enums, records, `normalize_series_name`, digest golden vectors, `validate_row_for_persistence`, `effective_publication_status` |
| `tests/schema/test_cpm_workbench_migration.py` | static tests: no `database` marker, so they run in FAST **and** carry the auto-applied `migration_edge` marker (`tests/db/fixtures.py`, `_migration.py` filename rule — R6-F14); database tests: explicit `migration_empty_to_head`, otherwise the `migration_edge` default | graph, freeze, offline SQL, empty→head, predecessor→head, preflight, downgrade |
| `tests/database/test_cpm_workbench_schema_guards.py` | `database` (`database_clone` default) | every CHECK/FK/unique/trigger at head |
| `tests/database/test_cpm_workbench_persistence.py` | `database` (`database_clone`) | repository/UoW, idempotency, lease, partition |
| `tests/architecture/test_cpm_workbench_foundation_scope.py` | FAST | `schedule` plane not runnable; no `GRANT`; ports not on `UnitOfWork` |

### 8.2 R2 clause → test

| R2 | Test (module: function) |
|---|---|
| §43.1 | unit `test_identifiers.py::test_contract_prefixes_are_stable` (+6); domain: `test_schedule_id_kinds_have_their_prefixes` |
| §43.2 | domain: `test_new_enums_have_exact_members_and_order`; migration: `test_frozen_literals_equal_the_domain_enums` |
| §10.1 | domain: `test_series_name_normalization_vectors`, `test_series_name_rejects_each_category`; guards: `test_series_name_check_refuses_untrimmed_doubled_and_control` |
| §9.2, §9.3, AC-004 | persistence: `test_admission_refuses_each_unproven_binding` (parametrized over the 8 binding refusals), `test_cross_principal_bindings_are_not_found`; guards: `test_publication_cannot_cross_enrollment_object_or_version` |
| §10.2, §23, AC-025 | persistence: `test_same_key_same_request_replays`, `test_same_key_different_request_conflicts`, `test_same_version_same_series_replays_when_metadata_agrees`, `test_same_version_same_series_conflicts_when_metadata_differs`, `test_same_version_other_series_is_a_new_publication`, `test_rejected_admission_writes_nothing`, `test_failed_version_cannot_be_reimported_into_its_series` (R6-F06: pins U-09 — a failed, effective-failed or review-required publication of version V in Series S makes every later admission of V into S replay or conflict) |
| §10.3, AC-027 | guards: `test_baseline_kind_is_required_exactly_for_baseline` |
| §10.4 | persistence: `test_supersession_rules`; guards: `test_supersession_is_same_series_once_and_not_self` |
| §21, §24 finalization, R6-F01 | domain: `test_outcome_ladder_sets_partition_the_issue_codes`; guards: `test_sql_outcome_ladder_equals_derive_outcome` (parametrized over all 23 codes + the ambiguous-row case), `test_terminal_status_must_equal_the_derived_outcome`, `test_parsed_run_refuses_a_failed_ladder_code`; persistence: `test_finalize_derives_the_status`, `test_canonicalize_refuses_a_review_or_failed_outcome` |
| R6-F03 | guards: `test_no_terminal_transition_while_a_run_is_running`, `test_parser_run_cannot_change_under_a_terminal_publication`; persistence: `test_fail_publication_closes_running_runs`, `test_finalize_closes_other_running_runs` |
| R6-F04/F05 | persistence: `test_row_ordinals_are_stored_verbatim_and_gaps_refused`, `test_begin_processing_on_a_terminal_publication_returns_a_terminal_plan` |
| §10.6, AC-026 | domain: `test_effective_status_derivation`; persistence: `test_exhausted_job_reads_effective_failed_without_writing` |
| §16.15, §17.3, AC-021/022 | guards: `test_row_content_is_immutable`, `test_row_link_is_set_once`, `test_row_link_requires_parsed_run_and_processing_publication`, `test_link_binds_exact_id_and_series`; persistence: `test_review_required_publication_links_nothing`, `test_canonicalization_is_resumable_after_lease_loss` |
| §17.2, AC-023 | guards: `test_four_state_typed_value_matrix` (parametrized OD/RD/Start/Finish × 4 states × value present/absent) |
| §18.1–18.7, AC-036 | migration: `test_empty_to_head_creates_exactly_the_seven_tables`, `test_frozen_ddl_names_every_declared_constraint`, `test_runtime_metadata_matches_the_revision` |
| §18.8.1–2 | migration: `test_support_uniques_exist_and_existing_rows_survive`, `test_preflight_refuses_without_the_primary_key`, `test_live_table_work_is_last_in_the_upgrade` (offline SQL order: no statement matching the qualified, word-bounded names `knowledge.enrollments`, `knowledge.enrollment_objects`, `knowledge.source_object_versions` or `knowledge.projects` — regex `\bknowledge\.(enrollments\|enrollment_objects\|source_object_versions\|projects)\b` — precedes the last `CREATE TRIGGER`, so column names such as `project_id` or `enrollment_id` cannot match; RR1-F02), `test_lock_timeout_is_transaction_local` (a fresh transaction after upgrade and after downgrade reads the server default), `test_a_held_lock_aborts_the_upgrade_cleanly` (another connection holds `ROW EXCLUSIVE` on `knowledge.enrollments` in an open transaction; upgrade fails with SQLSTATE `55P03`; the database is still at `023f8f7eb499` with none of the 7 tables, functions or the 2 uniques) |
| §4.11, R6-F11 | migration: `test_the_revision_writes_no_row_and_grants_nothing` (static), `test_no_grant_beyond_the_owner` (`relacl IS NULL`; `has_table_privilege` false for `PUBLIC`, `my_pa_mcp_ro`, `my_pa_mcp_rw`), `test_live_table_acls_are_unchanged` |
| R6-F08 | guards: `test_source_delete_is_refused_while_a_publication_references_it` (`DELETE FROM knowledge.sources` / `source_objects` fail with `foreign_key_violation` while a publication exists; pins U-10) |
| §19.13, AC-036 | migration: `test_downgrade_refuses_while_any_cpm_row_exists` (parametrized over 7 tables), `test_clean_downgrade_removes_only_cpm_objects_and_reupgrades` |
| §19.3, §19.14 | migration: `test_the_revision_is_the_single_head_on_023f8f7eb499`, `test_the_revision_imports_no_package_module`, `test_the_revision_writes_no_row_and_grants_nothing` |
| §20, AC-024 | persistence: `test_row_round_trips_the_parsed_record_field_for_field` |
| §21, §22 | persistence: `test_fail_publication_records_a_safe_issue_and_terminalizes` |
| ruling (d), R6-F12 | persistence: `test_orphan_stable_activity_is_reused_not_duplicated` (a canonicalization batch runs, the publication then fails; a later publication of the same Series links the same `schedule_activity_id`), `test_stable_activities_are_inserted_in_published_id_order` |
| §24, AC-030 | persistence: `test_every_worker_write_refuses_after_lease_loss` (parametrized over the 9 lease methods), `test_row_batch_is_at_most_one_thousand`, `test_finalization_verifies_completeness` |
| §25, AC-029 (WP-01 part) | scope: `test_schedule_plane_is_not_runnable_before_its_handler`; persistence: `test_admission_enqueues_exactly_one_schedule_job` |
| §35 | `test_principal_partition_is_reached_through_the_guard.py` (registry); persistence: `test_other_principal_reads_none_and_writes_nothing`, `test_schedule_jobs_are_partitioned` (R6-F10: `claim_job(principal_id=<other>, plane=SCHEDULE_JOBS)` returns `None` and `job_for(…, principal_id=<other>, plane=SCHEDULE_JOBS)` returns `None`; extending `tests/security/test_cross_principal_queue_isolation.py` stays with WP-04) |
| §36 bounds, ruling (c) | domain: `test_row_bounds_are_enforced_before_persistence`; persistence: `test_row_bounds_violation_fails_the_publication`; guards: `test_cell_evidence_hierarchy_and_warning_bounds` |

### 8.3 Prove-red table (break exactly one guard, show the named test fails for that reason, revert)

| # | Mutation | Must fail |
|---|---|---|
| P01–P06 | delete one `IdKind` member's prefix line in the exact set | `test_contract_prefixes_are_stable` |
| P07 | series name CHECK: drop the `btrim` clause | `test_series_name_check_refuses_untrimmed_doubled_and_control` |
| P08 | drop `a_schedule_baseline_has_its_kind` | `test_baseline_kind_is_required_exactly_for_baseline` |
| P09 | drop `a_schedule_publication_records_its_progress` | `test_publication_progress_columns_follow_status` |
| P10 | drop each `a_schedule_row_<x>_is_typed` (4 runs) | `test_four_state_typed_value_matrix[<x>]` |
| P11 | drop `a_schedule_row_identity_matches_its_type` | `test_row_identity_matches_type` |
| P12 | drop `a_schedule_row_links_only_an_activity_or_milestone` | `test_only_id_bearing_rows_link` |
| P13 | relax cell-evidence / hierarchy / warnings CHECKs (3 runs) | `test_cell_evidence_hierarchy_and_warning_bounds[<x>]` |
| P14 | drop `a_schedule_issue_severity_matches_its_code` | `test_issue_severity_matches_code` |
| P15 | drop each FK of section 4.8 (one per run) | the matching `test_<fk>_refuses_a_cross_binding` |
| P16 | drop U1 / U2 / partial supersession unique / `a_schedule_publication_has_one_job` / parsed-run partial unique / row-ordinal unique / activity-ID unique (one per run) | the matching idempotency test of section 8.2 or `test_<unique>_holds` |
| P17 | F3: remove the terminal-immutability branch | `test_terminal_publication_is_immutable` |
| P18 | F3: allow `queued → complete` | `test_publication_transitions_are_forward_only` |
| P19 | F3: drop the admission-column comparison | `test_admission_columns_are_immutable` |
| P20 | F3: drop the link-completeness verification | `test_complete_requires_every_id_row_linked` |
| P21 | F3: drop the `review_required` zero-link verification | `test_review_required_rejects_any_link` |
| P22 | F4: drop the trigger | `test_publication_without_job_fails_at_commit` |
| P23 | F5: drop the terminal branch | `test_terminal_job_is_immutable` |
| P24 | F6: allow `parsed → failed` | `test_terminal_parser_run_is_immutable` |
| P25 | F6: drop the row-count equality | `test_parsed_run_counts_match_rows` |
| P26 | F7: drop the content comparison | `test_row_content_is_immutable` |
| P27 | F7: allow value → other value | `test_row_link_is_set_once` |
| P28 | F7: drop the publication-processing condition | `test_row_link_requires_parsed_run_and_processing_publication` |
| P29 | F8: drop the trigger | `test_issue_is_refused_after_terminal` |
| P30 | F1 on each append-only table (3 runs) | `test_<table>_is_append_only` |
| P31 | F2 on each table (7 runs) | `test_<table>_refuses_truncate_when_it_holds_rows` |
| P32 | downgrade refusal: drop one table from the `DO` block (7 runs) | `test_downgrade_refuses_while_any_cpm_row_exists[<table>]` |
| P33 | remove the PK preflight | `test_preflight_refuses_without_the_primary_key` |
| P34 | add `GRANT SELECT … TO PUBLIC` to the revision | `test_the_revision_writes_no_row_and_grants_nothing`, catalog `test_no_grant_beyond_the_owner` |
| P35 | remove the module from the partition registry | `test_every_module_naming_a_partitioned_table_is_guarded_or_registered` |
| P36 | partition: drop `_mine` from `get_publication` | `test_other_principal_reads_none_and_writes_nothing` |
| P37 | admission: compare key without the digest | `test_same_key_different_request_conflicts` |
| P38 | admission: ignore `expected_data_date` in source-version replay | `test_same_version_same_series_conflicts_when_metadata_differs` |
| P39 | remove `hold_lease` from one worker method (9 runs) | `test_every_worker_write_refuses_after_lease_loss[<method>]` |
| P40 | register `schedule` in `apps/worker.py` `_PLANES` | `test_schedule_plane_is_not_runnable_before_its_handler` |
| P41 | skip `validate_row_for_persistence` | `test_row_bounds_are_enforced_before_persistence` |
| P42 | F3: drop the `status = schedule_run_outcome(...)` check | `test_terminal_status_must_equal_the_derived_outcome` |
| P43 | F9: move one code between ladder sets (one run per set) | `test_sql_outcome_ladder_equals_derive_outcome[<code>]` |
| P44 | F6: drop the failed-ladder-code refusal on `running → parsed` | `test_parsed_run_refuses_a_failed_ladder_code` |
| P45 | `finalize_publication`: take the status from the caller | `test_finalize_derives_the_status` |
| P46 | `canonicalize_batch`: drop the outcome gate | `test_canonicalize_refuses_a_review_or_failed_outcome` |
| P47 | F3: drop the no-running-run-at-terminal check | `test_no_terminal_transition_while_a_run_is_running` |
| P48 | F6: drop the publication-processing condition on UPDATE | `test_parser_run_cannot_change_under_a_terminal_publication` |
| P49 | `fail_publication` / `finalize_publication`: skip closing running runs (2 runs) | `test_fail_publication_closes_running_runs` / `test_finalize_closes_other_running_runs` |
| P50 | F3 INSERT: drop the predecessor-version-differs check | `test_supersession_needs_a_different_source_version` |
| P51 | F3: allow `document_*` value → other value while processing | `test_pinned_document_is_set_once` |
| P52 | F3: drop the failed `issue_count` equality, then (separately) the at-least-one-error check (2 runs) | `test_failed_publication_counts_its_issues` / `test_failed_publication_needs_an_error_issue` |
| P53 | F3: drop the DELETE refusal | `test_publication_is_never_deleted` |
| P54 | F5: drop the comparison of each identity column (5 runs: `operation_id`, `publication_id`, `principal_id`, `max_attempts`, `created_at`) | `test_job_identity_column_is_immutable[<column>]` |
| P55 | F5: drop the INSERT shape check; drop the DELETE refusal (2 runs) | `test_job_is_inserted_queued_and_unleased` / `test_job_is_never_deleted` |
| P56 | F6 INSERT: drop the processing-publication condition; drop the digest equality (2 runs) | `test_parser_run_starts_only_on_a_pinned_processing_publication[<case>]` |
| P57 | F6: drop the column-immutability comparison | `test_parser_run_identity_is_immutable` |
| P58 | F6: drop the `issue_count` equality; drop the `warning_count` equality (2 runs) | `test_parsed_run_counts_match_issues[<count>]` |
| P59 | F7 INSERT: drop `schedule_activity_id IS NULL` | `test_row_is_inserted_unlinked` |
| P60 | F7 INSERT: drop the parent-ordinal check | `test_parent_row_precedes_its_child` |
| P61 | F7 UPDATE: drop the run-`parsed` condition | `test_row_link_requires_a_parsed_run` |
| P62 | F7 UPDATE: allow value → NULL; allow value → same value (2 runs) | `test_row_link_cannot_be_cleared` / `test_row_link_cannot_be_reset` |
| P63 | F8: drop the run-`running` branch | `test_run_issue_requires_a_running_run` |
| P64 | drop `a_schedule_series_name_is_unique_within_its_project` | `test_series_name_key_is_unique_within_its_project` |
| P65 | drop `a_schedule_attempt_starts_one_parser_run` | `test_one_parser_run_per_attempt` |
| P66 | drop `a_schedule_issue_row_has_its_run` | `test_row_issue_needs_its_run` |
| P67 | `a_schedule_publication_records_its_progress`: drop one status branch (4 runs: queued, processing, parsed-terminal, failed) | `test_publication_progress_columns_follow_status[<branch>]` (each case violates only its own branch) |
| P68 | drop the `a_schedule_issue_names_a_row_of_its_run` FK | `test_issue_row_ordinal_names_a_row_of_its_run` |
| P69 | downgrade: omit one support-unique drop (2 runs) | `test_clean_downgrade_removes_only_cpm_objects_and_reupgrades` |
| P70 | `SET` instead of `SET LOCAL` for `lock_timeout` | `test_lock_timeout_is_transaction_local` |
| P71 | remove `lock_timeout` from `upgrade()` | `test_a_held_lock_aborts_the_upgrade_cleanly` (fails by timing out its own bounded wait instead of seeing `55P03`) |
| P72 | move the support-unique step before the `CREATE TABLE` steps | `test_live_table_work_is_last_in_the_upgrade` |
| P73 | `GRANT SELECT` on one CPM table to `my_pa_mcp_ro` in the scratch database before the check | `test_no_grant_beyond_the_owner` |
| P74 | change `RESTRICT` to `CASCADE` on `a_schedule_publication_names_a_version_of_its_object` | `test_source_delete_is_refused_while_a_publication_references_it` |
| P75 | drop `partition_criterion` from the shared `job_for` (then, separately, from the `claim_job` subquery) — 2 runs | `test_schedule_jobs_are_partitioned` (the existing plane tests also redden; that is expected shared coverage, not redundancy) |
| P76 | canonicalization inserts in row order instead of published-ID order | `test_stable_activities_are_inserted_in_published_id_order` |
| P77 | `begin_processing`: raise on terminal instead of returning a terminal plan | `test_begin_processing_on_a_terminal_publication_returns_a_terminal_plan` |
| P78 | `insert_rows`: assign ordinals instead of storing them | `test_row_ordinals_are_stored_verbatim_and_gaps_refused` |
| P79 | the four-surface guard: add `"schedule"` to each surface in turn (4 runs) | `test_schedule_plane_is_not_runnable_before_its_handler` (the message names the surface) |
| P80 | admission: drop the idempotency-key pattern CHECK | `test_idempotency_key_has_the_precedent_shape` |
| P81 | `fail_publication`: compare `parser_run_id` with `=` (run-less de-duplication) | `test_run_less_failure_issue_is_recorded_once` |

A prove-red that stays green is reported as redundancy, a masked test or an unreachable
hazard, never as "covered" (for example, a CHECK that a trigger already forces is expected
to be redundant on its own; the implementer reports which).

### 8.4 Commands (foreground, chunked, `PYTHONPATH=src`, `~/my-pa/.venv/bin/python`)

FAST over the new and touched modules; `-m "database and not migration_edge and not
migration_empty_to_head and not migration"` over the 2 new database modules;
`-m migration_empty_to_head` and `-m migration_edge` over the migration module; the full
`tests/architecture` directory; `ruff check`, `ruff format --check`, `mypy` (current and the
floor venv); `python -m tests.ci_shard verify --lane fast --shards 3 -m "<FAST expression>"`.
Homebrew `postgres@15` scratch cluster (`initdb --auth=trust`, loopback, `PGTZ=UTC`, no
inline password), removed at the end.

---

## 9. Deviations, residuals and operator gates

### 9.1 Deviations from R2

| ID | R2 | S5b-1 | Reason |
|---|---|---|---|
| D-01 | §18.8.4/§19.9 widen audit sets in this migration | not widened; WP-03's revision does it | no capability exists; the audit sets and `_CURRENT_AUDIT_CAPABILITIES` track the live enum (section 3.2) |
| D-02 | §18.8.3/§19.8/§25 heartbeat CHECK, worker map, health, fallback | only `SCHEDULE_JOBS`; the rest with the handler in WP-03 | no runnable plane without a handler, no health for a plane that cannot run (section 3.3) |
| D-03 | §19.2/AC-036 "one" revision | CPM takes 2 revisions (WP-01 schema; WP-03 vocabularies) | consequence of D-01/D-02 |
| D-04 | §18.8 support uniques in `tables.py` | database-only, commented in `tables.py` | `7e5a1fb93d62` builds both tables from live declarations (S1 F20 precedent) |
| D-05 | §19.4 add uniques (preflight implied by the brief) | `CREATE UNIQUE INDEX` + `USING INDEX` under `lock_timeout`; catalog PK preflight instead of a duplicate scan | duplicates are impossible while the PKs hold; the reachable failure is a missing PK |
| D-06 | §18 columns | `series_id` also on parser runs, rows and issues; extra U4 on publications; job/run composite uniques | same-Series composite FKs and the `JobPlane` insert shape |
| D-07 | §18.6 "normalized row bbox" | integer-millipoint box + page size stored; the normalized box is `normalized_box_strings(...)` at read | lossless superset; one derivation (S5a §6.2) |
| D-08 | §18.6 ambiguous "may carry partial source fields" | ambiguous rows carry neither ID nor name | S5a §6.1 record invariant; DB equals the domain |
| D-09 | §18.5 run columns | adds engine versions, `parse_result_sha256`, `issue_count`; NULL `failure_code` on `failed` = abandoned/transient | S5a §3.3 says WP-01 persists `engine`; determinism provenance; R2 makes the code nullable |
| D-10 | §18.5 index "operation/attempt" | `UNIQUE (publication_id, attempt_number)` + job FK; earlier `running` runs closed `failed` by the next attempt | one run per attempt; no forever-`running` evidence |
| D-11 | §18.4 "same semantics as existing JobPlane tables" | same columns/CHECKs/functions; adds identity immutability, no DELETE, terminal immutability, TRUNCATE refusal | protects effective-status truth; no `jobs.py` path writes what these refuse |
| D-12 | §18.4 exactly one job | adds deferred "has its job" trigger | at-least-one at commit + `UNIQUE` = exactly one |
| D-13 | §19.7 reuse existing pattern | own functions with the S1 bodies | plane-local downgrade and evolution |
| D-14 | §23 "canonical request digest" (unspecified) | section 5.3 form over the casefold name key with the S5a encoder | one canonical JSON in the plane; key-equivalent names replay |
| D-15 | §10.2 "role/baseline/supersession/assertion metadata" | compares role, baseline kind, expected Data Date, supersedes; enrollment ignored | enrollment is the authorization path, not publication meaning |
| D-16 | §23 typed results | success returned typed; every rejection raised as typed `ScheduleAdmissionRejectedError` | guarantees rollback of a series created earlier in the transaction |
| D-17 | §10.4 terminal predecessor | terminal-ness application-checked by effective status under `FOR UPDATE`; DB checks structure and differing version | effective status needs the job's derived state |
| D-18 | §8.1 domain stdlib | `domain/schedule` may import `my_pa.domain.common.identifiers` | records validate their IDs; S5a allowlist widened by exactly that module |
| D-19 | §18.3/§18.6 "bounded" | ID 256, name 2000, label 2000 characters; validator before insert | an oversized parse fails deterministically instead of a CHECK error mid-batch |
| D-20 | §18.6 16 KiB CHECK | DB 32,768 bytes of `jsonb::text`; exact 16,384 canonical bytes in the hook | `jsonb::text` is not the canonical encoding |
| D-21 | §8.2 dedicated UoW | no `record_events`, no `projects` member | derived evidence emits no Record Event in WP-01; ownership is proved by partitioned reads |
| D-22 | §43.3 `ScheduleChange`, `ScheduleCursor`, `ScheduleApplication`, paged reads | WP-03 | comparison/cursor/read services are WP-03 by §44 |
| D-23 | §18.2 counts | `activity_count` = activity + milestone rows; `issue_count` = accepted run's issues (failed: all of the publication's) | exact derivation the F3 trigger verifies |
| D-24 | §42 test module names | section 8.1 names | one module per tier |
| D-25 | §10.1 `name_key = casefold(name)` | `name_key = NFC(casefold(name))` | `str.casefold` can leave a non-NFC string; re-normalizing makes equal keys byte-equal (R6-F14) |
| D-26 | §23/§9.1 idempotency key unspecified | `^[A-Za-z0-9_-]{8,128}$` | the repository's project-history and Constraint Management precedent; no free text in a key column (R6-F07) |
| D-27 | §24 finalization "issue-derived status" (unspecified form) | the S5a ladder frozen as SQL `schedule_run_outcome`; `finalize_publication` derives the status; F3 enforces equality; canonicalization gated on `complete`/`partial` | the caller cannot choose a status the evidence does not support (R6-F01) |

### 9.2 Residuals and unknowns

| ID | Item | Owner |
|---|---|---|
| U-01 | Production row counts of `enrollments` and `source_object_versions` are unknown here (no production access) | operator, before deploy |
| U-02 | Production default privileges (`ALTER DEFAULT PRIVILEGES`) for the migrating role are unknown; a default grant to an MCP role would extend to the 7 tables | operator, before deploy |
| U-03 | A Stable Activity created by a canonicalization batch whose publication never finalizes stays (immutable) with no eligible observation. Ruling (d): kept, not prevented (preventing would break §24's bounded batches). **WP-03 reads must treat a Stable Activity as visible only when it has a linked row in a `complete` or `partial` publication, and must never present `schedule_activities.created_at` as first-seen.** A later eligible publication of the same Series re-uses it through `ON CONFLICT` (`test_orphan_stable_activity_is_reused_not_duplicated`) | WP-03 reads |
| U-04 | S5a U-18: an ID whose source differs only in space-run length across publications merges into one Stable Activity | WP-04 corpus |
| U-05 | `[[:cntrl:]]` follows the server ctype for non-ASCII; the full category rule is domain-only | accepted |
| U-06 | Owner/superuser can disable triggers (S1 §4.3, CR-014) | operator-gated role separation |
| U-07 | Until WP-03, `schedule` jobs are claimable by no worker and invisible to health; nothing creates one in production | WP-03 |
| U-08 | F3 terminal verification (and F9) scans up to 25,000 rows and 50,000 issues of the accepted run inside the finalization transaction (indexes `a_schedule_row_ordinal_is_unique_within_its_run`, `schedule_import_issues_by_publication`) | WP-04 performance |
| U-09 | (R6-F06) A `failed`, effective-failed or `review_required` publication of source version V in Series S blocks V in S for good: a new key replays it or conflicts (U2), even after transient exhaustion or a parser fix; only a new source version (with `supersedes`) or another Series admits it. Consistent with R2 §23; pinned by `test_failed_version_cannot_be_reimported_into_its_series` | WP-03 (surfaced conflict reason), WP-04 (operator documentation) |
| U-10 | (R6-F08) The CPM FKs are `RESTRICT` while `sources → enrollments → enrollment_objects` and `source_objects → source_object_versions` cascade: once a publication exists, deleting its `sources`/`source_objects` row fails as a whole. No such path exists today; a future retention or erasure design must handle CPM rows first. Pinned by `test_source_delete_is_refused_while_a_publication_references_it` | WP-04 / future retention design |

### 9.3 Operator gates

Nothing below is performed by an agent: production stays out of agent reach, and this
contract authorizes **no grant and no revoke**.

1. **Lock window.** Deploying this revision alters 2 live tables at the end of the revision
   transaction (section 3.4): `SHARE` on each from its index build, then `ACCESS EXCLUSIVE`
   from `ADD CONSTRAINT … USING INDEX`, and `SHARE ROW EXCLUSIVE` on `projects`,
   `enrollments`, `enrollment_objects` and `source_object_versions` from the 4 new FKs —
   **all held until the revision commits**. While `ACCESS EXCLUSIVE` is held every reader of
   those 2 tables (gateway source-scope authorization, the enrollment worker) waits. Before
   deploy: read-only `count(*)` of both tables, a quiet window for the gateway and the
   enrollment worker, a backup, and confirmation that both PKs exist (the preflight refuses
   otherwise). **A `55P03` (`lock_not_available`) abort is a clean, retryable outcome** —
   the whole revision rolls back; retry in a quieter window; never raise the 10 s timeout
   without a new review. The same applies to a downgrade.
2. **Blocking pre-deploy privilege gate (ruling (e)), read-only:**
   1. Before the migration run
      `SELECT defaclrole::regrole, defaclnamespace::regnamespace, defaclobjtype, defaclacl FROM pg_default_acl;`.
      If any entry would apply to tables the migrating role creates in `knowledge` and names
      `PUBLIC`, `my_pa_mcp_ro` or `my_pa_mcp_rw`, **STOP**: removing it is a separate
      operator-authorized change, never part of this revision.
   2. Name the roles the gateway and worker connect as, and confirm they reach the lineage
      tables through the mechanism the 7 new tables will use (owner identity or default
      privilege), by comparing `relacl` and owner of a lineage table such as
      `knowledge.record_links`. If the Record Event roles (`my_pa_runtime`,
      `my_pa_migrator`, `my_pa_owner`) are in use and the runtime role is not the owner, the
      new tables will be **unreachable** to the runtime: a stop for WP-03 enablement, not
      for this schema-only deploy.
   3. After the migration: `has_table_privilege(<role>, 'knowledge.<table>',
      'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')` is false for `PUBLIC`, `my_pa_mcp_ro` and
      `my_pa_mcp_rw` on all 7 tables, and `relacl` of `knowledge.enrollments` and
      `knowledge.source_object_versions` is byte-identical to before.
   4. Any deviation is a stop and is reported.
3. No production migration, grant, revoke, capability, worker plane or deployment is
   authorized by this contract.
