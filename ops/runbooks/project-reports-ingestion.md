# Project reports ingestion (Procore PULSE exports)

**Status: UNEXECUTED / OPERATOR-GATED.** Nothing in this runbook has been run against the NAS or
the production database. Applying the migration, placing the bindings file, `bindings apply`,
the backfill and turning the poll on are operator actions. They belong to the one consolidated
activation of the communications contract section 20.6 (Manager ruling R-OP-7) and are written
here so that activation can bundle them (section 10). The decision is
[`docs/decisions/ADR-024-project-report-source-evidence.md`](../../docs/decisions/ADR-024-project-report-source-evidence.md);
the plan is [`docs/plans/pulse-implementation-plan.md`](../../docs/plans/pulse-implementation-plan.md)
(section 17, as built). The only real-data run so far is the Manager's, on a scratch database
(2026-11-24, counts only; section 5).

## 1. What it does

The operator saves reports in Procore and exports them as CSV into one folder per project in the
`mcp` file workspace. my-pa **reads** them; it never writes, renames or trashes them, and never
calls Procore.

- **Bindings.** The operator's bindings file maps each export folder to one Project and its
  project number. `bindings apply` admits one `ingest_sources` row per folder (consumer
  `pulse_csv_export`, pattern `*.csv`, one folder, no recursion), binds and enables it in one
  transaction. A folder left out of a later file is **retired**: its source is disabled and every
  row stays. There is no other way to admit a project-report source: the communications command
  refuses this consumer `consumer_not_registered`.
- **Snapshots.** A file is identified by its SHA-256 per source. Every raw row is stored (Layer
  A) and reconstructed byte-exact before anything is derived.
- **Derivations.** Each snapshot has one current derivation: `classified` (row roles, typed
  lines, stated totals and their reconciliation) or `quarantined` (rows kept, nothing classified).
  A later derivation supersedes it; nothing is updated in place.
- **The poll.** On the `cycles` worker plane, step `project_reports_ingest`, every 900 s by
  default, under its own session advisory lock (`PROJECT_REPORTS_POLL_LOCK_KEY`). A scheduled
  poll reads a file once its size and version token held still across two consecutive polls,
  then runs the bounded re-derivation sweep (at most 100 snapshots per poll).
- **Money is source evidence** (ADR-024 decision 2): stored in `NUMERIC(20,4)`, never written to
  any product-owned record, and not the ADR-018 controlled financial source.

## 2. Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` | `false` | Off: the cycles plane runs no project-reports step. Any one of `MY_PA_CYCLE_SCHEDULER_ENABLED`, `MY_PA_COMMUNICATIONS_INGEST_ENABLED` and this one starts the plane; with all three off it exits 2 (`plane cycles disabled`). It withholds no capability. |
| `MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS` | `900` | The step interval, 60 to 86,400 s. |
| `MY_PA_FILES_WORKSPACES` | unset | Set by the read-only overlay to `mcp=/srv/my-pa/workspaces/mcp;mode=read_only` ([`communications-ingestion.md`](communications-ingestion.md) section 3). |

No overlay line sets `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` yet: the operator adds it to the
cycles service environment at section 8. There is no read switch here; reads arrive with WP4P.

## 3. Prerequisites

1. **Migration, with the worker stopped.** The image contains revision `0d4e247d03cb` (the
   twelve project-report tables and the view `project_report_current_derivations`, on
   `61fafdfd2986`). Stop the cycles service first, then migrate to the image's single Alembic
   head. The revision takes its locks up front under a 10 s `lock_timeout`: if another session
   holds one, it aborts with `55P03` (or a deadlock error) and leaves the database where it was;
   stop that session and run it again. Nothing is half-applied.
2. **The read-only overlay** of the communications runbook (section 3 there): the cycles service
   reads the `mcp` subtree through a read-only bind, and a mount that is not `ST_RDONLY` refuses
   (`workspace_misconfigured`).
3. **Projects with numbers.** Each Project to bind exists in `knowledge.projects` with its
   project number; a Project without one refuses `project_has_no_number`.

## 4. The bindings file

The file is **operator runtime data**. It is never committed, never baked into an image, never
logged, never printed and never pasted into a ticket or chat. Keep it outside the repository and
outside the image, mode `0600`, owned by the uid the cycles service runs as
(`MY_PA_REMOTE_UID`), for example under the operator's private configuration directory on the
NAS. The command reads it whole (at most 1 MiB) and prints only closed codes, counts and project
numbers.

Schema `my_pa_project_report_bindings_v1`:

```json
{"schema": "my_pa_project_report_bindings_v1", "workspace_id": "mcp",
 "export_root": "<EXPORT_ROOT>",
 "bindings": [{"folder": "<EXPORT_ROOT>/<PROJECT_FOLDER>/REPORTS/PULSE",
               "project_id": "prj_<ID>", "project_number": "<NUMBER>",
               "currency": "USD",
               "reports": [{"slug": "<SAVED_REPORT_SLUG>", "filter": "<WHAT IT SELECTS>"}]}]}
```

- The file is the **whole desired state** of the workspace: a bound folder it omits is retired.
- `currency` defaults to `USD`; `reports` is optional. A filter declaration applies to versions
  first seen at or after it; without one a series' filter semantics are `unknown`.
- Each folder sits strictly inside `export_root`, exists as a directory, binds one Project, and
  is neither nested in nor a duplicate of another folder; each Project appears once.

## 5. Running the command

Every invocation carries the two target assertions. The database comes from
`MY_PA_DATABASE_URL` (the owner-only env file), is never an argument and is never printed.

```sh
python apps/cli/project_reports.py \
  --expected-database my_pa --expected-alembic-head <HEAD> <command> ...
```

On the NAS it runs as a one-shot container of the cycles service, with the bindings file
mounted read-only for the commands that read it:

```sh
docker compose -p my-pa-remote-mcp -f ... \
  -f ops/nas/remote/compose.cycle-scheduler.remote.example.yml \
  -f ops/nas/remote/compose.comms-ingest.remote.example.yml \
  --profile remote-mcp run --rm --no-deps \
  -v <BINDINGS_FILE>:/run/my-pa/bindings.json:ro my-pa-cycle-scheduler \
  python apps/cli/project_reports.py --expected-database my_pa \
  --expected-alembic-head <HEAD> bindings check --file /run/my-pa/bindings.json
```

| Command | Does | Lock |
| --- | --- | --- |
| `bindings check --file F` | validates `F` against the database and the workspace; prints the diff (`add`, `correction`, `filter_update`, `retire`, `unchanged`) and `unbound_folders` (CSV folders under `export_root` the file binds to nothing, listed to `unbound_folder_depth` 3, at most 5,000 directories, `unbound_listing_truncated` when it stopped short) | none; writes nothing |
| `bindings apply --file F` | applies the whole file in one transaction, or refuses it and writes nothing; `writes` counts sources admitted, enabled and disabled, revisions and filter declarations; the same file twice writes nothing the second time | poll lock |
| `run-once --source ID` | one poll of one source (trigger `operator`) | poll lock |
| `backfill --source ID [--file NAME ... \| --glob PATTERN] [--dry-run]` | reads the named files, one name pattern, or every candidate (trigger `backfill`); each snapshot is its own transaction | poll lock, not for `--dry-run` |
| `rederive [--source ID] [--dry-run]` | the re-derivation sweep now, including an `operator_rebuild` of every current derivation, at most 100 snapshots per call (the rest `derivations_deferred`) | poll lock, not for `--dry-run` |
| `coverage [--source ID]` | per source: id, `enabled`, `binding_state`, project number, snapshots, rejected, quarantined; per series (an index, never a slug): versions, date labels, first and last seen, freshness, completeness, quarantine reasons, filter semantics | none |
| `aggregate --source ID ... [--expect FILE]` | the AC-17 figures from stored rows; `--expect` compares every key exactly and lists only the differing ones | none |

There is no `--reason` argument: each revision records the reason its change kind names
(`initial`, `add`, `correction`, `filter_update`, `retire`).

Output is one JSON line. Exit `0` done, `1` refused (`{"command": ..., "refused": CODE}`, nothing
written), `2` usage, `3` a run finished `partial` or `failed` or `rederive` counted
`derivations_failed`, `4` `aggregate --expect` differs.

**`source_unbound`.** `run-once` and `backfill` (with or without `--dry-run`) refuse
`source_unbound` up front when the source has no active binding (a retired folder): no run row and
no snapshot is written, not even a rejected one. Bind the folder again with `bindings apply` if
it should be read. A source that is no project-report source refuses `source_not_found`.

## 6. First apply and backfill

1. `bindings check --file F`. Read the diff: the first time every folder is an `add`, with the
   expected project numbers; check `unbound_folders` is the number of export folders you chose
   not to bind.
2. `bindings apply --file F`. Expect `applied: true` and `writes.sources_admitted` equal to the
   number of folders.
3. `coverage` (no `--source`) lists every source with its `ingest_source_id` and project number;
   record the ids.
4. Per source, `backfill --source ID --dry-run`: `outcome: completed`, `snapshots_ingested` equal
   to the files in the folder, `snapshots_rejected: 0`.
5. Per source, `backfill --source ID`. A stopped backfill leaves a consistent prefix; run it again
   and the digests already held count `snapshots_already_known`.
6. `aggregate --source ID1 --source ID2 --source ID3 --expect <EXPECTED>` (Manager check, counts
   only). `<EXPECTED>` is `tests/fixtures/project_reports/expected/evidence_aggregate_v1.json`
   from a checkout of the deployed commit, mounted read-only like the bindings file (the image
   holds no `tests/`). Exit `0` means every figure matched; exit `4` lists the differing keys.

The Manager's scratch-database run (2026-11-24, at `013b3bcb1`) got: 3 sources bound; 20
snapshots, 0 failed, 0 quarantined; project-number check `match` 3; cross-report check `match` 1;
`aggregate --expect` 340 of 340 (exit 0); a rerun counted 20 `snapshots_already_known`.

## 7. Monitoring

- The step's log lines: `{"event": "project_reports_ingest.run", "sources": N, "outcomes": {...},
  "counts": {...}}` then `{"event": "project_reports.rederive", "counts": {...}}`.
  `project_reports_ingest.skipped` means another process held the poll lock (an operator run or
  `bindings apply`); `project_reports_ingest.failed` means the step raised and is retried after
  the interval. Lines hold codes and counts only.
- `coverage` per source: `freshness_seconds` per series (now minus the latest version's first
  seen), `versions`, `completeness` and `quarantined`.
- The stored cross-report check pairs a buyout summary with a reconciliation only when both
  exports carry the same `YYYYMMDD-` date label: an export without one is never cross-report
  paired in the stored derivations (the stored aggregate records `not_checked`), while the
  file-level `aggregate` pairs one buyout summary with one reconciliation per folder regardless.
- Read-only checks (the operator's read-only `psql` route):

```sql
SELECT trigger, outcome, count(*) FROM knowledge.ingest_runs r
JOIN knowledge.ingest_sources s USING (principal_id, ingest_source_id)
WHERE s.consumer = 'pulse_csv_export' GROUP BY 1, 2 ORDER BY 1, 2;
SELECT state, quarantine_reason, count(*) FROM knowledge.project_report_current_derivations
GROUP BY 1, 2 ORDER BY 1, 2;
```

**Quarantine reasons and the operator action for each** (a quarantined derivation keeps every raw
row and classifies none; its run counts `records_snapshot_quarantined_<reason>`):

| Reason | Meaning | Operator action |
| --- | --- | --- |
| `unknown_header_signature` | the export's columns match no registered adapter (Procore changed the columns, or a new report was saved) | none to recover data; report it so an adapter is added in a PR. Once deployed, the sweep re-derives it automatically (`rederive_adapter`) |
| `malformed_ratio_exceeded` | more than 1 % of the data rows fit no row rule | check the export in Procore and export it again; new bytes are a new snapshot. Report it if a clean export still quarantines |
| `binding_project_number_mismatch` | the project number the export carries is not the bound one | the folder is bound to the wrong Project, or the file is in the wrong folder: correct the bindings file and `bindings apply`; the sweep re-derives (`rederive_binding`) |

**Rejections** (the whole file refused; lifecycle status `rejected`): `not_utf8`, `malformed_csv`,
`invalid_header`, `nul_byte`. Export the report again; corrected bytes are a new snapshot. A file
over 16 MiB is `skipped_too_large` and writes nothing.

## 8. Enabling the poll

Add `MY_PA_PROJECT_REPORTS_INGEST_ENABLED: "true"` to the cycles service environment and recreate
the service. The first poll after a start only observes files (`skipped_unstable`); the second
reads them, and digests already held link `already_known` without a write.

## 9. Day-2 operations

- **A new export appears** in a bound folder: the poll reads it once it is stable. A changed file
  at a known path is a new snapshot and supersedes that path; a new report name is a new series.
- **Procore changes a report's columns**: the new file quarantines `unknown_header_signature`
  with rows kept until an adapter PR is deployed, then re-derives with no operator action.
- **Correcting a binding** (wrong Project, number or currency): edit the file, `bindings check`,
  `bindings apply`. The change is a `correction` revision; the next sweep re-derives each
  snapshot of that source under it. Earlier derivations stay, superseded.
- **Declaring a filter**: add a `reports` entry; apply records a `filter_update`.
- **Retiring a folder**: remove it from the file and apply. The source is disabled, every row
  stays, and `run-once` and `backfill` then refuse `source_unbound`. Adding it back later is an
  `add` that re-enables the same source.
- **Adding a project**: create the Project with its number, add its folder to the file, check,
  apply, backfill.
- **`lock_held`**: a writing command or `bindings apply` found the poll lock held (the scheduled
  step or another operator run). It wrote nothing; run it again when that run has finished.

## 10. Consolidated activation entry (R-OP-7)

In the order of the communications contract section 20.6, after the comms steps:

1. stop the cycles service; apply the migrations (which include `0d4e247d03cb`); section 3;
2. place the bindings file (section 4); `bindings check`, then `bindings apply` (section 6);
3. dry-run backfill, backfill and the `aggregate --expect` check per section 6;
4. set `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` and recreate the cycles service (section 8).

No grant is part of WP3P: the `project_reports.*` reads and their grants arrive with WP4P.

## 11. Recovery and disabling

- **Stop the poll.** Remove the switch and recreate the service. With the other two switches also
  off the plane exits 2. Rows stay.
- **Failed or partial run.** The failed snapshot rolled back alone (`snapshots_failed`); the rest
  committed. A rerun or the next poll retries it; idempotency makes the retry safe. A sweep
  failure is counted `derivations_failed` and retried on the next sweep.
- **Rows are never deleted.** Eleven of the twelve tables are append-only, the binding pointer
  only moves forward, `TRUNCATE` is refused, and the downgrade refuses while any project-report
  row exists. Recovery is switch-off with rows kept, or a binding correction; never a delete.
- **Restart.** Stability memory lives in the process: after a restart the first poll observes and
  the second reads.

## 12. Residuals

- No read capability exists yet (WP4P), so nothing here is visible to a connected client.
- No overlay sets the switch; the operator adds it (section 8).
- Longitudinal behaviour (a second export generation) is proven on synthetic data only.
- Raw rows grow by about one copy of each export per derivation generation; retention is a later
  operator decision.
