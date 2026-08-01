# Phase 12 — Legacy Retention

The legacy SQLite database is **retained indefinitely, read-only, and is never
mutated, renamed, moved, or deleted**. This document records what is retained,
why, and under what access rules.

**This phase retires nothing.** `OP-RETIRE-001` was resolved **DO NOT PROCEED**
(decision register `OD-003`). There is deliberately no deletion procedure, no
retirement schedule, and no "when you are ready to delete" section in this
document. Where the planning package implies one, that part of the plan is
superseded — see [Where this contradicts the plan](#where-this-contradicts-the-plan).

Every figure below was read from the live database, from `migration_control`, or
from the source file itself opened read-only. Nothing is copied from a plan or a
report.

## Identity of the retained source

| Property | Value |
| --- | --- |
| Path | `<LOCAL_SENSITIVE_ROOT>/hbpa-migrated-local-data-20260722/db/hb-personal-assistant.sqlite` |
| Bytes | `4,368,125,952` (4.4 GB) |
| sha256 | `9b8c8d8b151735af3773a1c9a3843166a6c1b542f90c6f9823e3821a90a37f6f` |
| Schema version | `128` (`schema_migrations` max, `v128_permanent_source_identity`) |
| Objects | 593 tables + 2 views; 1,732 indexes |
| Rows | 3,323,450 across the 593 base tables |
| Page size | 4,096 bytes |
| Last modified | 2026-07-19 20:25:13 |

The byte count, sha256, and schema version are recorded in
`migration_control.migration_runs` and were **re-verified against the file on
disk on 2026-08-01**. All three match: the file has not drifted since the runs
that read it.

The file has no `-wal` and no `-shm` sidecar. That is the observable evidence
that nothing has opened it in a mutating mode.

`OD-001` records the deviation from the planning basis: the plan bound a
7,417,266,176-byte, schema-135, 610-object snapshot with sha256 `fa3631f7…`,
which does not exist on this machine. The file above is the newest and largest
legacy database present, and the plan's object set is a proper superset of it, so
every object in it still has a disposition.

## Retention posture

- **Retained indefinitely.** No expiry, no review date, no eligibility
  checklist. `OD-003` makes this a property of the campaign, not a period to be
  counted down.
- **Read-only, `immutable=1` access only.** Every read opens it as:

  ```python
  sqlite3.connect(f"file:{path}?immutable=1", uri=True)
  ```

  `immutable=1` is not a convenience — it is what prevents SQLite from creating
  a journal, WAL, or lock file beside the source. Plain and `mode=ro` opens fail
  in this environment anyway, but the requirement stands independently of that.
- **No writes, renames, moves, deletes, or `VACUUM`, at any phase.** Including
  this one.
- **No application component opens it.** The only code in this repository that
  reads it is the migration tooling under `src/my_pa/infrastructure/migration/`,
  which is finished. No application, domain, or repository code path reads
  SQLite, and none may be added.
- **Nothing leaves this machine.** `OD-004`: no row content, payload, address, or
  personal identifier may be written to logs, commits, evidence, or reports, or
  sent to any external service. This document holds counts, table names, and
  hashes only.

If anything ever appears to require writing to this file, that is a defect in
the procedure. Stop and report it.

## Why it is retained rather than retired

Because it is the only copy of data that PostgreSQL deliberately does not hold.

### 59,572 rows deliberately not migrated

Of the source's 3,323,450 rows, 3,263,878 were in scope and 3,263,870 landed in
PostgreSQL. The remaining **59,572 rows (1.79%)** were excluded on purpose and
exist nowhere else. Counted per table from the source, read-only, on 2026-08-01:

| Category | Objects | Rows | Why excluded |
| --- | ---: | ---: | --- |
| FTS virtual and shadow tables | 12 | 32,203 | SQLite index internals, not data (`OD-010`). Rebuilt as PostgreSQL full-text and `pg_trgm` indexes over the migrated base tables. |
| Superseded by a newer authoritative table | 27 | 19,513 | A newer table already holds these facts. Loading both would create two candidate sources of truth (`OD-025`). |
| Operational state, schema-only and empty by design | 85 | 7,828 | Queue cursors, sync watermarks, in-flight run state. Carrying it forward would make a fresh system believe it had already processed work it has not (`OD-025`). Tables exist in PostgreSQL; they are empty. |
| Obsolete or empty | 68 | 24 | `DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE` (`OD-025`). |
| Privacy-gated | 2 | 4 | `raw_content_model_context_packets` (4 rows) and `construction_email_intelligence_deferred_state` (0 rows) — the two tables the privacy gate actually meant (`OD-025`). |
| **Total** | **194** | **59,572** | |

The full per-table list with dispositions is
[`migrations/data/disposition_registry.json`](/migrations/data/disposition_registry.json).

The Phase 10 reconciliation report groups the same facts differently, so the two
should be read together rather than compared line by line. It counts **109
objects not created** holding **51,744 rows** (the first, second, fourth, and
fifth rows above) and reports the empty-by-design tables separately as **90
tables asserted empty** — 85 operational-state plus 4 provenance-only and 1
schema-empty, the last five holding no source rows at all. This table adds the
operational-state tables' 7,828 source rows to the not-created total because the
question here is what only the legacy file holds, and a table that exists in
PostgreSQL but is deliberately empty holds none of them:
51,744 + 7,828 = 59,572.

Two of these categories are genuinely irreplaceable: the 19,513 superseded rows
and the 7,828 operational-state rows. The FTS 32,203 are derivable from base
tables that were migrated, and the 24 obsolete rows are of no consequence — but
they are still only in this file.

The 5,388 rows in the five `*_runs` provenance tables were **not** excluded: they
were withheld by the original operational-state rule and then loaded by run
`ed06aadf-c1de-42f4-bc32-a2ce33c5975a` under `OD-028`, because withholding them
orphaned their derived children. Any earlier statement of a 64,960-row exclusion
predates that correction; 64,960 − 5,388 = 59,572.

### 8 quarantined rows carrying a NUL byte

Recorded in `migration_control.quarantine_records`, error code
`UNSUPPORTED_TEXT_NUL`, error class `DataError`:

| Source table | Column | Rows |
| --- | --- | ---: |
| `source_intelligence_chunks` | `chunk_text` | 6 |
| `source_intelligence_text` | `text_excerpt` | 2 |

PostgreSQL `text` cannot represent U+0000 at any length. `OD-029` refused to
strip the byte: stripping would silently alter stored content to make a load
succeed. Both tables hold derived extracted text and the source retains the
originals unchanged, so the eight rows are recoverable by hand from this file and
from nowhere else.

(`OD-029` named the column `text_content` on both tables. The actual column names
are `chunk_text` and `text_excerpt`, as recorded in `quarantine_records` and
shown above.)

### 15 objects absent from the source at schema 128

These are the plan's schema v129–v135 additions. They are **not** held by the
legacy file either — the file is at schema 128 and never had them. They exist in
neither store, and no target table was created for any of them (`OD-001`).
Recorded so a later reader looking for them finds an explanation rather than
concluding they were lost:

| Object | Planning disposition |
| --- | --- |
| `apple_contact_raw_content` | `MIGRATE_DATA` |
| `apple_contact_structured` | `REBUILD_AND_VALIDATE` |
| `calendar_event_current_selection` | `MIGRATE_DATA` |
| `calendar_event_revisions` | `MIGRATE_DATA` |
| `calendar_event_source_observations` | `MIGRATE_DATA` |
| `contact_current_selection` | `MIGRATE_DATA` |
| `contact_email_hashes` | `DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` |
| `contact_entities` | `MIGRATE_DATA` |
| `contact_linkage_candidates` | `DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` |
| `contact_phone_hashes` | `DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` |
| `contact_revisions` | `MIGRATE_DATA` |
| `contact_source_observations` | `MIGRATE_DATA` |
| `email_message_current_selection` | `MIGRATE_DATA` |
| `email_message_revisions` | `MIGRATE_DATA` |
| `email_message_source_observations` | `MIGRATE_DATA` |

Eleven carry `MIGRATE_DATA`, three are privacy-deferred (and moot — `OD-003`'s
`OP-PRIV-001` and `OP-PRIV-002` gates resolve to "do not populate" and "do not
generate" against tables that do not exist), and one is rebuild-class. This is
also why the `contacts` schema in PostgreSQL has no tables: every object the plan
assigned to that domain is on this list.

### And the load is not re-runnable without it

The 3,263,870 rows in PostgreSQL were produced by reading this file. Any future
rollback-and-reload (see
[`PHASE-11-CUTOVER.md`](PHASE-11-CUTOVER.md#rollback-runbook)) reads it again and
binds to its sha256. Deleting it would make the migration unreproducible even
setting the excluded data aside.

## The backup consideration

**State plainly what this is: a single 4.4 GB file, on one machine, holding the
sole copy of 59,572 rows and 8 quarantined rows that exist nowhere else.**

There is no second copy of *this* file. Its directory does contain older
snapshots of the same database — at roughly 3.6–4.2 GB, dated between
2026-06-25 and 2026-07-11, named for the schema versions they preceded
(`pre-v74`, `pre-v79`, `pre-v122`, and others). Those are earlier states at
earlier schema versions. They are **not** backups of the schema-128 file, and
they must not be treated as one. The whole directory is about 26 GB and is
itself on the same single machine.

The risks, unhedged:

- **Disk failure or filesystem corruption loses the excluded data permanently.**
  PostgreSQL holds 98.2% of the corpus and is separately backed up (see the
  [operations runbook](/ops/runbooks/postgres-operations.md)), but a `pg_dump`
  of `my_pa` does not contain the 59,572 excluded rows or the 8 quarantined ones.
  The two stores are not redundant with each other.
- **Accidental deletion or a stray write is unrecoverable**, and 4.4 GB is large
  enough that it may fall outside whatever retention an ordinary file-history
  tool applies.
- **The file is itself the integrity check.** The recorded sha256 detects
  corruption but does not repair it.

**Recommended, not performed:** at least one verified off-machine copy of this
exact file, with its sha256 recorded and re-verified after transfer, stored under
the same handling rules as the original (it contains personal data — `OD-004`
applies to any copy). This is an operator decision about personal data leaving
this machine, and `AGENTS.md` §5 keeps that decision with the operator. Nothing
in this campaign has copied, transmitted, or backed up this file, and this
document does not authorize doing so.

Verifying the file's identity is safe and read-only, and is the one thing worth
doing periodically:

```sh
shasum -a 256 <LOCAL_SENSITIVE_ROOT>/hbpa-migrated-local-data-20260722/db/hb-personal-assistant.sqlite
# expect 9b8c8d8b151735af3773a1c9a3843166a6c1b542f90c6f9823e3821a90a37f6f
```

## Credentials

`P12-AC-06` asks for migration credentials to be removed at closeout. There are
none to remove. The migration used the same local `my_pa` role the application
uses, whose password is supplied out of band through `MY_PA_DB_PASSWORD` or
`PGPASSWORD` and is not committed; the compose file's `my_pa_local_dev` fallback
is a publicly known placeholder that is only acceptable because the container
binds to `127.0.0.1` alone. No separate migration role, token, or key was
created, so there is no credential whose removal is outstanding. Reading the
source needs no credential at all — it is a file.

## Where this contradicts the plan

The planning package's Phase 12 is titled "Legacy Retention **Retirement** and
Closeout" and is built around eventual deletion. That framing is superseded.
Listed rather than quietly dropped:

| Plan text | Superseded by | Why |
| --- | --- | --- |
| §2 objective: "retirement prerequisites; execute only under separate exact operator authorization" | `OD-003` / `OP-RETIRE-001` **DO NOT PROCEED** | Retirement is refused for this campaign. There are no prerequisites because there is no retirement to prepare for. `HZ-EARLY-RETIRE` is closed by construction. |
| §4 scope: "retention schedule", "cleanup eligibility" | `OD-003` | Retention is indefinite. A schedule implies an end date; there is none. |
| P12-AC-01 "Retention period recorded" | `OD-003` | Recorded as indefinite, with no expiry. |
| P12-AC-04 "Cleanup eligibility checklist" | `OD-003` | Refused. Publishing a checklist would imply a path to deletion that this campaign does not have. |
| P12-AC-05 "Retirement authorization ID present before delete" | `OD-003` | No delete is contemplated, so no authorization is sought. |
| P12-AC-06 "Migration credentials removed post-close" | repository state | Satisfied vacuously — see [Credentials](#credentials). |
| §6: 167 objects assigned to Phase 12, including `REBUILD_AND_VALIDATE`=61 and `ARCHIVE_LEGACY_SOURCE_ONLY`=31 as archive-only | `OD-025` | Both classes are **loaded** into PostgreSQL, not archived. `OD-008` as originally written would have left 48.8% of the corpus permanently absent. 93 tables and 72,375 rows were loaded under phase tag `PHASE-12`. |
| §14 and §17: snapshot sha256 `fa3631f7…`, schema 135, stop condition "schema version ≠ 135" | `OD-001` | The bound source is sha256 `9b8c8d8b…` at schema 128. A stop condition on 135 would halt work on a completed migration. |
| §16 hazard "Early retirement → hard gate + dual authorization" | `OD-003` | Not applicable. There is no retirement to gate. |

`P12-AC-02` (archive identity verified), `P12-AC-03` (access restrictions
documented), and `P12-AC-08` (deferred operator decisions resolved or explicitly
carried) are satisfied by this document, by `OD-025`'s split of the deferred
class, and by the decision register.
