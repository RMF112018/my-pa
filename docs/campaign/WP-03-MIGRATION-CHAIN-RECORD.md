# WP-03 — Persistence and Alembic migration-chain reconciliation: record

Repo-local record of what WP-03 re-authored onto the operating lineage, what it
attempted and reverted, what it declined, and what it carries forward. Every SHA,
count, and constraint figure below was re-derived in `/Users/bobbyfetting/mypa-wp03`
at execution time — from `git rev-parse`, from parsing `migrations/versions/`, or
from `pg_catalog` on a live PostgreSQL 17.10. Nothing here is transcribed from a
brief or from an earlier record.

## Lineage

| Fact | Value |
|---|---|
| Operating lineage | `recovery/pre-20260805-utc-rollback-c9fb513` |
| Base head before WP-03 | `81589cc851905f9d63f5faf0690322682d1e8b85` |
| Base tree before WP-03 | `7eb87fa18f7a9f6718c6c9441dbecdf98453d543` |
| WP-03 branch | `bf/wp-03-migration-chain-reconciliation` |
| Head at which every figure below was measured | `cff9d1c0ea82f4c42666f4b198ee5c509c3ac85d` |
| Tree at that head | `6ae37148f014e8af804705a82f9bfa8fbb64e007` |

`cff9d1c…` is the branch head after the five implementation commits and the one
correction commit that closed review finding F1. This record is the commit that
follows it; the head after the merging step is recorded there, not here.

**Note on `CAMPAIGN-BRIEF.md`'s `operating_lineage_head`.** It read
`60f8ccfba72cff3cd9be10164fca1f19af8d84e7`, which is the *parent* of the true
lineage head. `git rev-parse recovery/pre-20260805-utc-rollback-c9fb513` and its
`origin/` counterpart both return `81589cc…`. The brief has been corrected.

## Chain facts, derived by parsing

Both figures below come from parsing the `revision` / `down_revision` assignments
out of every `migrations/versions/*.py` with `ast`, then computing the set of
revisions that no other revision names as its parent. `README.md` is not a
revision and is excluded by extension.

| | Revisions | Heads | Base | Walk length from head |
|---|---|---|---|---|
| Base `81589cc…` | 21 | `d2e3f4a5b6c7` (exactly one) | `5d75f23847c9` | 21 |
| Result `cff9d1c…` | 22 | `9d4e7a3b1c62` (exactly one) | `5d75f23847c9` | 22 |

The walk from head to base visits every revision file at both ends, so the chain
is linear with no orphan and no second head. `alembic heads` against a live
server reports `9d4e7a3b1c62 (head)`, agreeing with the parse.

## What was re-authored

Fourteen of the fifteen commits WP-02 deferred conflict under 3-way merge against
this lineage, so the source commits below were used as **specifications, not
cherry-picks**. Each item names what it was authored *from*.

1. **The seven-fact downgrade-convergence guard** —
   `tests/schema/test_every_revision_denotes_one_schema.py` (new). Authored from
   `c34d5f02` (measure convergence against a server and delete the parser),
   `8c94e6f2` (four kinds of fact, not constraints alone), `91afbad5` (seven
   kinds, closing the residue shapes), and `cd80ae1c` (state the snapshot's reach
   by enumeration rather than a stale count). It walks the chain out of
   `ScriptDirectory`, names no revision or table in any assertion, and compares
   constraints, columns, indexes, non-internal triggers, relations with their
   kind, schemas, and extensions. Installed and measured against the chain **as
   it then stood**, before the revision below was added, so what it says about
   the later revision is a result rather than an expectation.
2. **Revision `9d4e7a3b1c62`, re-chained onto `d2e3f4a5b6c7`**, with its ORM
   narrowing. Authored from `0cf63f24` (the revision), `8e7d6a32` (the
   `tables.py` CHECK narrowing, which alone would make the declaration assert a
   constraint the database lacks), and the revision half of `dac9c375` (restore
   the vocabulary the revision below denotes). On its source branch this revision
   sat on a 15-revision chain that has none of `8c4d1e7a2b90`, `9d5e2f7b4c61`, or
   the WP-00…WP-06 principal revisions, so it was re-chained rather than replayed.
   It lands here as `migrations/versions/20260809_9d4e7a3b1c62_narrow_the_extraction_status_vocabulary.py`.
3. **The subset assertion at the declaration** —
   `tests/schema/test_extraction_schema_migration.py`. Authored from `e37ee053`.
   Replaces a derivation the narrowing removed with an assertion that the stored
   status vocabulary is the outcome vocabulary less `quarantined`, plus a
   detector that reads the vocabulary off the constraint.
4. **The refusal test** — `tests/search_quality/test_lexical_search.py`. Authored
   from `e2127124`. The old test planted a `quarantined` row in `extractions` and
   asserted the read side counted it nowhere; the narrowed constraint refuses
   that row, so the premise can no longer be arranged. It is replaced by a test
   that asserts the server refuses the insert **and names the constraint that did
   it**, so a row rejected by some other check cannot pass as this claim.
5. **The call-site correction** — `src/my_pa/infrastructure/persistence/extraction.py`
   and `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`.
   Authored from `6667d70e`. Names the three `extracted_text_in_scope` call sites
   instead of counting two of them, and states the enum-derivation guard's
   raw-SQL limit at its measured scope on **this** chain rather than at the scope
   the source branch measured on its own.

Two consequential edits were authored in WP-03 rather than ported:
`docs/architecture/system-context.md` (its chain figure moved with the chain) and
`README.md` / `docs/plans/mcv-completion-plan.md` / `tests/architecture/test_readme_state_claims.py`
(spelled counts the tree forced).

## What was NOT done, and why

### 1. `355a0f8b` / `6348b246` — WP-12E revision `a7c3e8d1f642`: attempted and reverted

Re-chaining it is **DDL-coherent and application-incompatible**. Both halves of
that sentence were measured here, not taken on report.

Re-chained onto `9d4e7a3b1c62` in a throwaway copy of the tree, `alembic upgrade
head` ran the whole chain through
`9d4e7a3b1c62 -> a7c3e8d1f642` without error. The application then could not
write to it:

- It installs three insert-path triggers —
  `native_run_requires_exact_frozen_inputs` (`BEFORE INSERT` on
  `knowledge.native_sync_runs`), `native_job_requires_exact_frozen_run`
  (`BEFORE INSERT OR UPDATE` on `knowledge.native_sync_jobs`), and
  `native_checkpoint_requires_admitted_page` (`BEFORE INSERT` on
  `knowledge.native_checkpoints`), backed by the functions
  `native_run_snapshot_is_exact`, `native_job_matches_frozen_run`, and
  `native_checkpoint_follows_admission`. Each refuses a write whose inputs are not
  already frozen or already admitted, which is every write the live
  `SqlNativeSourceRepository` makes.
- **And**, independently of the triggers, it adds three `NOT NULL` columns with no
  usable default that the live insert path never supplies:
  `native_sync_runs.bridge_id` and `native_sync_runs.adapter_identity` (both
  `SET NOT NULL` after a backfill, so new rows have nothing), which
  `append_run` does not name; and `native_sync_jobs.read_mode` (added `NOT NULL
  DEFAULT`, then `DROP DEFAULT` in the same revision), which `enqueue_job` does
  not name. So even with the triggers dropped it would still fail.

Measured: **8 failed, 211 passed, 4 errors** in `tests/schema` against live
PostgreSQL 17.10 with the revision re-chained — eight failures across
`test_native_source_schema_migration.py` and `test_capture_schema_migration.py`,
four fixture-setup errors in `test_audit_durability.py`. The same 8 + 4 was
reported independently by review. The probe copy was discarded; nothing under
`migrations/versions/` in this branch was touched by it.

Making those writes legal requires WP-12E's **application half** — roughly 707
lines of `src/my_pa/infrastructure/persistence/native_sources.py`, a new
`application/native_baseline.py`, and a widening of the application contract.
That is feature behavior, and a migration-chain package is not where feature
behavior lands. **Deferred to the work package that carries WP-12E's application
half**, which must carry both together or neither.

### 2. `288bdb14`, `dcc97266`, and the test half of `dac9c375` — superseded within their own branch

These three build and then harden
`tests/schema/test_every_downgrade_restores_the_vocabulary_below_it.py` — the
regular-expression reader over Alembic's `--sql` output. `c34d5f02`, later on the
**same source branch**, deletes that file and replaces it with the server-measured
guard. Replaying them here would replay a design that the branch which authored
them rejected. Their intent survives in item 1 of "What was re-authored", which is
the replacement, not a weakening of it.

### 3. `6e491c24` — code-inert here, and out of scope

WP-02 deferred it to WP-03 on the ground that it touches `migrations/env.py`.
That is the whole of its migration-chain surface, and read at the file it is a
docstring plus one `# statement-timeout-exempt:` marker comment — **code-inert
here**, because the marker's only consumer,
`tests/architecture/test_every_engine_is_bounded_or_exempt.py`, does not exist in
this lineage, and because WP-S01 has already landed the single-parse change that
`env.py` line 34 now reads. Everything else in the commit is the settings /
statement-timeout package's, which is where it belongs. It is also already on
`origin/main`, which is at `6e491c24…`.

## Decision D-09 — WP-03 adds no principal scoping to the native-source plane

**Decision.** WP-03 does not partition, and does not add `principal_id` to, any
table in the native-source plane. Deferred to **WP-04**.

**Premise, measured on live PostgreSQL 17.10 at head `cff9d1c…`:**

- `a7c3e8d1f642` contains **zero** `CREATE TABLE` and zero `op.create_table`. It
  is an alteration of four existing tables: `knowledge.native_sync_runs`,
  `knowledge.native_sync_jobs`, `knowledge.native_checkpoints`, and
  `knowledge.native_admission_authorities`.
- Those four are created **unpartitioned** by revisions already on this chain —
  the first three by `20260804_8c4d1e7a2b90`, the fourth by
  `20260805_9d5e2f7b4c61`.
- All **22** tables in the `knowledge` schema whose names begin `native_` or
  `source_` are unpartitioned (`relkind = 'r'`, no partition parent, no partition
  child) and **none** carries a `principal_id` column.

So the WP-02 acceptance condition that WP-12E's baseline tables "must be
principal-partitioned before admission" rests on a false premise: the revision
creates no tables to partition, and the tables it alters were never WP-12E's to
scope. Partitioning a subset of the plane would leave partitioned children joined
to unpartitioned parents — a worse shape than the uniform one that exists now.
The condition is moot in any case, because the revision was not admitted (see
"What was NOT done", item 1).

**What the canonical WP-03 acceptance clause actually asks** is that principal
constraints and indexes be **preserved**, and that is verified rather than
asserted. Counted from `pg_catalog`:

| Fact | Count |
|---|---|
| `principal_id_is_an_opaque_identifier` CHECK constraints | 30 |
| Indexes whose name contains `by_principal` | 39 (of which 31 end in `_by_principal`) |
| `a_capture_key_admits_one_submission_per_principal` | 1 |

Identical **by name set**, not merely by count, across all three states: at
`d2e3f4a5b6c7`, at the new head `9d4e7a3b1c62`, and after a
`head -> d2e3f4a5b6c7 -> head` round trip. Nothing principal-scoped was added,
dropped, renamed, or moved.

## Decision D-10 — 12 of the 15 deferred commits re-authored; 3 deferred with reasons

**Decision.** WP-03 re-authored twelve of the fifteen commits WP-02 deferred, as
five items of work; three are deferred again, each with a named owner or a named
reason. See "What was re-authored" and "What was NOT done" above.

**Rationale.** Fourteen of the fifteen conflict under 3-way merge, so the choice
was never replay-or-drop; it was re-author-from-specification or drop. Every one
that carries a property this lineage can hold was re-authored and measured here.
The three that were not are not oversights: one is blocked on a body of
application code that does not belong in a migration package, one was superseded
inside the branch that wrote it, and one is out of scope and already on `main`.

## Database acceptance observed

All against a throwaway PostgreSQL **17.10** container on loopback with trust
auth, destroyed after the run. Server version read back with `SHOW server_version`.

| Claim | Observed |
|---|---|
| empty → `head` | applies; `alembic current` reports `9d4e7a3b1c62 (head)` |
| `head` → `base` → `head` | applies both ways |
| prior head `d2e3f4a5b6c7` → `head` | applies |
| `head` → `d2e3f4a5b6c7` → `head` (round trip) | applies; principal name set identical at every stop |
| exactly one head after all of the above | `alembic heads` → `9d4e7a3b1c62 (head)` |
| every revision's downgrade restores what the one below denotes | `tests/schema/test_every_revision_denotes_one_schema.py` passes over all 22 revisions |

## Test figures

| Suite | Base `81589cc…` | Head `cff9d1c…` |
|---|---|---|
| `tests/architecture` | 1397 | 1397 |
| Full suite, collected | 3657 | 3660 |
| Full suite, **executed** against live PostgreSQL 17.10 | — | **3660 passed, 0 failed, 0 errors** |
| `tests/schema` against live PostgreSQL 17.10 | — | 223 passed, 0 failed, 0 errors |

Net **+3**, accounted node-id by node-id from `pytest --collect-only` at both
ends — four added, one replaced:

| Node | |
|---|---|
| `tests/schema/test_every_revision_denotes_one_schema.py::test_every_revision_returns_the_database_to_what_the_one_below_it_denotes` | added |
| `tests/schema/test_extraction_schema_migration.py::test_the_stored_status_vocabulary_is_the_outcome_vocabulary_less_quarantined` | added |
| `tests/schema/test_extraction_schema_migration.py::test_the_detector_reads_the_status_vocabulary_off_the_constraint` | added |
| `tests/search_quality/test_lexical_search.py::test_the_schema_refuses_a_quarantined_outcome_filed_as_an_extraction` | added |
| `tests/search_quality/test_lexical_search.py::test_a_row_filed_in_extractions_as_quarantined_is_not_counted_as_processed` | removed — replaced by the row above |

Nothing was skipped, xfailed, weakened, or deleted to reach these figures.
`ruff check .` clean and `mypy` clean over 164 source files, both at `cff9d1c…`.

`ruff format --check .` is clean at every head in this range, but its **file
count is not a constant of the branch and must be bound to a head**, which the
earlier wording here did not do. This repository's `ruff` formats Markdown as
well as Python, so this record's own file moves the number: **536 files at
`cff9d1c…`** (304 `.py` + 232 `.md`) and **537 files at the head that carries
this record** (304 `.py` + 233 `.md`) — the 537th being
`docs/campaign/WP-03-MIGRATION-CHAIN-RECORD.md` itself. The composition is given
so the figure can be re-derived at either head rather than trusted.

## Carried-forward backlog

Both items need an owning work package. Neither blocks the merge of WP-03, and
neither is in WP-03's scope.

1. **The `render_as_string(hide_password=False)` sites across the test tree — now
   deferred a second time, and it needs an owner.** WP-02 flagged this as a
   redaction note *for WP-03*. WP-03 closed the one site it authored that did not
   need to exist (review finding F1) and is not authorized to sweep the rest.
   Measured at head `cff9d1c…`: **72 sites across 36 test files**, all of them
   under `tests/`, none in production code. They fall into three shapes, and the
   split is what makes this schedulable:
   - **35** are the maintenance-engine shape,
     `create_database_engine(configured.set(database="postgres").render_as_string(hide_password=False))`.
     Every one of these is avoidable by the same one-line change F1 made:
     `create_database_engine` takes a `URL`, so the render is pure loss.
   - **36** write a rendered DSN into `MY_PA_DATABASE_URL` because
     `migrations/env.py` reads the URL from the environment at import time.
     These are **structural**, not sloppy, and cannot be closed without changing
     how Alembic is handed a connection in this repository.
   - **1** (`tests/contract/test_health_probe.py`) renders a deliberately closed
     port for a negative probe.

   The risk is unchanged from WP-02's statement of it: nothing logs these, but a
   rendered traceback over the local could disclose a database password. The
   35-site family is a mechanical, testable change; the 36-site family is a
   design question about `migrations/env.py`. They should be scheduled together
   so the second is not silently taken as the excuse for the first.

2. **The `NativeRunState.RUNNING` widening hazard — must be resolved when item 1
   of "What was NOT done" is rescheduled.** `src/my_pa/domain/native_sources/models.py`
   declares `NativeRunState` with three members (`succeeded`, `partial`,
   `failed`). `tables.py` derives **two** database CHECKs from that one enum:
   `native_run_state_is_known` on `knowledge.native_sync_runs`, and
   `native_bucket_run_state_is_known` on `knowledge.native_bucket_runs`.
   `a7c3e8d1f642` widens only the first, to include `running`; it does not alter
   `native_bucket_runs` at all. So adding `RUNNING` to the enum desyncs the second
   site — the declaration would assert a four-value constraint the database holds
   as three.

   **No test catches this.** The parity guard,
   `test_central_declarations_match_applied_columns_constraints_indexes_and_triggers`,
   compares constraint **names** (`pg_constraint.conname`) against the declared
   names, not `pg_get_constraintdef` text, so a constraint that keeps its name and
   changes its vocabulary is invisible to it. Whoever reschedules WP-12E owns both
   the second `ALTER` and a guard that compares definitions, not names.
