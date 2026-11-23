# Communications ingestion

**Status: UNEXECUTED / OPERATOR-GATED.** Nothing in this runbook has been run against the NAS or
the production database. Applying the migration, adding the overlay, admitting the sources,
running the backfill and turning the poll on are operator actions. They belong to the one
consolidated activation of the communications contract section 20.6 (Manager ruling R-OP-7) and
are written here so that activation can bundle them. The contract is
[`docs/architecture/communications-intelligence-contract.md`](../../docs/architecture/communications-intelligence-contract.md)
sections 1, 9, 10, 11, 18 and 19.

## 1. What it does

The ChatLLM collector writes `communications_evidence_v2` publications into the `mcp` file
workspace. my-pa **reads** them; it never writes, renames or trashes them.

- **Sources.** One `ingest_sources` row per admitted location: a workspace, a folder
  (`path_prefix`) and a name pattern (`file_pattern`, `fnmatch`, one folder, no recursion).
  Admission is this runbook's operator command, never a capability, and writes no audit row
  (`admitted_by = operator_cli`).
- **Snapshots.** A file is identified by its SHA-256. Known bytes are never re-ingested; new
  bytes at a known path supersede that path's previous snapshot; the same bytes at another path
  are an alias.
- **Runs.** Each poll, `run-once` or backfill is one `ingest_runs` row (`schedule`, `operator`
  or `backfill`) with an outcome (`completed`, `partial`, `failed`) and code counts. Every
  snapshot commits or rolls back alone, oldest declared window first.
- **The poll.** On the `cycles` worker plane (`apps/worker.py run --plane cycles`), every 900 s
  by default, under its own session advisory lock. A scheduled poll reads a file only once its
  size and version token held still across two consecutive polls, so a new file is ingested one
  to two intervals after the collector finishes it.

## 2. Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MY_PA_COMMUNICATIONS_INGEST_ENABLED` | `false` | Off: the cycles plane runs no ingestion poll. With it and `MY_PA_CYCLE_SCHEDULER_ENABLED` both off, the plane exits 2 (`plane cycles disabled`). |
| `MY_PA_COMMUNICATIONS_INGEST_POLL_SECONDS` | `900` | The poll interval, 60 to 86,400 s. |
| `MY_PA_FILES_WORKSPACES` | unset | Set by the overlay to `mcp=/srv/my-pa/workspaces/mcp;mode=read_only`. |

`MY_PA_COMMUNICATIONS_ENABLED` (the contract's read switch) is not introduced here: WP3a adds no
read capability for it to gate. It arrives with the reads in WP4.

## 3. Prerequisites

1. **Migration head.** The image contains revision `52a829ef718a` (the ingestion and
   communications tables) and the database is migrated to it before anything below runs. Every
   command refuses unless `--expected-alembic-head` equals the single `alembic_version` row.
2. **The overlay.** [`ops/nas/remote/compose.comms-ingest.remote.example.yml`](../nas/remote/compose.comms-ingest.remote.example.yml)
   is added after [`ops/nas/remote/compose.cycle-scheduler.remote.example.yml`](../nas/remote/compose.cycle-scheduler.remote.example.yml)
   in the `-f` list the live project already uses ([`cycle-scheduler.md`](cycle-scheduler.md)
   section 4). It gives the cycles service a **read-only** bind of the `mcp` subtree and names
   it a `read_only` workspace. `MY_PA_REMOTE_UID` needs read access to the subtree.
3. **`ST_RDONLY` refusal.** A `read_only` workspace refuses to compose unless the kernel reports
   its mount read-only. The plane then exits 2 with `plane cycles workspace_misconfigured` and
   the command refuses with `workspace_misconfigured`. Fix the bind (`read_only: true`), never
   the mode.
4. **Hard links are not read.** A file with more than one hard link may be a link to something
   outside the workspace, so the store refuses to read it. The run counts it
   `skipped_unreadable` and writes nothing for it. The collector must write ordinary files.

## 4. Running the command

Every invocation carries the two target assertions. The database comes from
`MY_PA_DATABASE_URL` (the owner-only env file), is never an argument and is never printed.

```sh
python apps/cli/communications_ingest.py \
  --expected-database my_pa --expected-alembic-head 52a829ef718a <command> ...
```

On the NAS the command runs as a one-shot container of the cycles service, so it sees the same
env file and the same read-only workspace:

```sh
docker compose -p my-pa-remote-mcp -f ... \
  -f ops/nas/remote/compose.cycle-scheduler.remote.example.yml \
  -f ops/nas/remote/compose.comms-ingest.remote.example.yml \
  --profile remote-mcp run --rm --no-deps my-pa-cycle-scheduler \
  python apps/cli/communications_ingest.py --expected-database my_pa \
  --expected-alembic-head 52a829ef718a coverage --source isrc_...
```

Output is one JSON line: source ids, run ids, closed codes, counts and UTC timestamps. Exit `0`
done, `1` refused (`{"refused": CODE}`), `2` usage, `3` a run finished `partial` or `failed`.
`coverage` and `aggregate` refuse `source_not_found` for a source id that was never admitted.

## 5. Admission

Admit the canonical folder, then the two rich publications (Manager ruling R2), each as its own
source naming its exact file. Record the three printed `ingest_source_id` values.

```sh
python apps/cli/communications_ingest.py <assertions> admit \
  --consumer communications_evidence_v2 --workspace mcp \
  --path-prefix "My PA/Daily Intelligence/communications/" --file-pattern "*-comms.json"
python apps/cli/communications_ingest.py <assertions> admit \
  --consumer communications_evidence_v2 --workspace mcp \
  --path-prefix "<RICH_FOLDER_1>/" --file-pattern "<RICH_FILE_1>" --disabled
python apps/cli/communications_ingest.py <assertions> admit \
  --consumer communications_evidence_v2 --workspace mcp \
  --path-prefix "<RICH_FOLDER_2>/" --file-pattern "<RICH_FILE_2>" --disabled
```

`<RICH_FOLDER_n>` is the publication's workspace-relative folder under `My PA/Daily
Intelligence/`, and `<RICH_FILE_n>` its file name. A name containing `*`, `?` or `[` is written
with each such character in brackets (`[*]`). The rich sources are admitted `--disabled`: they
are one-off publications, so the scheduled poll has nothing to watch there, and a backfill
works on a disabled source. A second admission of the same location refuses
`source_already_admitted`; an unregistered consumer refuses `consumer_not_registered`.

## 6. Backfill

Dry run first. It lists, reads, parses and counts exactly as the backfill will, and writes
nothing (no run, no snapshot, no path):

```sh
python apps/cli/communications_ingest.py <assertions> backfill --source <CANONICAL> --dry-run
```

Check `outcome: completed`, `snapshots_new` equal to the number of publications, and
`snapshots_rejected: 0`. Then backfill each source:

```sh
python apps/cli/communications_ingest.py <assertions> backfill --source <CANONICAL>
python apps/cli/communications_ingest.py <assertions> backfill --source <RICH_1>
python apps/cli/communications_ingest.py <assertions> backfill --source <RICH_2>
```

`--file NAME` (repeatable) or `--glob PATTERN` narrows a backfill. Files are applied oldest
window first, one transaction each, so a stopped backfill leaves a consistent prefix: run it
again and the ingested SHA-256 values are counted `snapshots_already_known`. A rerun of a
finished backfill writes only its run row and one run link per snapshot.

## 7. Monitoring

```sh
python apps/cli/communications_ingest.py <assertions> coverage --source <CANONICAL>
python apps/cli/communications_ingest.py <assertions> coverage --source <CANONICAL> \
  --from 2026-10-17T04:00:00Z --to 2026-11-20T14:12:05Z
python apps/cli/communications_ingest.py <assertions> aggregate \
  --source <CANONICAL> --source <RICH_1> --source <RICH_2>
```

- `coverage`: merged intervals (inclusive ends), `gap_count` and `gap_seconds`, `freshness_seconds`
  (now minus the latest covered instant), per-lane states (`not_authorized` is reported as such),
  and `rolling_30d`: the 30 days ending at the latest covered instant (`start` is `end` minus
  30 days, `end` is `latest_covered`), `complete` or `partial` with its gaps, or `none` with null
  `start`/`end` when nothing is covered. Read `freshness_seconds` for staleness (no new
  publication since `latest_covered`) and `rolling_30d` for holes inside the covered span; the
  rolling read never turns `partial` just because the newest publication is late.
  A source with less than 30 days of covered history reads `partial`, with one leading gap,
  until 30 days are covered; that is expected after a first admission or a short backfill.
  `--from`/`--to` reads one range the same way, over exactly the instants given.
- `aggregate`: snapshots by status, rejection codes, superseded paths, runs by trigger and
  outcome; observations by classification, folder role and lane verification; quarantined
  records and reasons; distinct items and messages; multi-lane items; messages flagged
  `identity_conflict`; identifiers per kind; and the merged coverage of all named sources.
- The poll's log line is `{"event": "comms_ingest.run", "sources": N, "outcomes": {...},
  "counts": {...}}`. `comms_ingest.skipped` means another process held the poll's lock;
  `comms_ingest.failed` means the poll raised and is retried after the interval.

Read-only checks over the run log (the operator's read-only `psql` route):

```sql
SELECT trigger, outcome, count(*) FROM knowledge.ingest_runs GROUP BY 1, 2 ORDER BY 1, 2;
SELECT started_at, finished_at, outcome, counts->'snapshots_failed', counts->'snapshots_rejected'
FROM knowledge.ingest_runs ORDER BY started_at DESC LIMIT 10;
SELECT status, rejection_code, count(*) FROM knowledge.ingest_snapshots GROUP BY 1, 2;
```

## 8. Enabling the poll

Uncomment `MY_PA_COMMUNICATIONS_INGEST_ENABLED: "true"` in the overlay and recreate the cycles
service. The first poll after a start only observes files (`skipped_unstable`); the second reads
them, and known bytes link `already_known` without a write.

## 9. Failure recovery

- **Failed or partial run.** The failed snapshot's transaction rolled back alone
  (`snapshots_failed`); the rest committed. The next poll or a rerun of the backfill retries it,
  and idempotency makes the retry safe. A run with nothing but failures is `failed`.
- **Rejected snapshot.** Status `rejected` with its `rejection_code`; the row never changes and no
  communications row or coverage window is written. Its path is placed like any snapshot's: it
  supersedes that path's current row, so the path now points at the rejected snapshot. A file
  refused while it was still changing is not rejected: it is `skipped_changing` and retried. To
  recover, the collector publishes corrected bytes, which are a new snapshot and supersede the
  rejected one at the path. Re-publishing the *earlier good* bytes does not recover the path: it
  is a path revert (below), writes nothing, and the path keeps pointing at the rejected snapshot
  (the earlier snapshot's observations and coverage stay).
- **Re-publication.** New bytes at a known path are a new snapshot; the path's earlier row is
  superseded, its observations stay, and coverage keeps both windows (they merge).
- **Path revert.** Earlier bytes reappearing at a path a newer snapshot superseded are counted
  `snapshots_path_reverted` and nothing is written: supersession is one-way, so the newer
  snapshot stays current for that path.
- **`lock_held`.** `run-once` and `backfill` (not `--dry-run`) hold the poll's advisory lock
  (`COMMS_INGEST_LOCK_KEY`, the cycles plane's own) for the whole run. While the scheduled poll
  or another operator run holds it, the command refuses `lock_held` (exit 1) at once and writes
  nothing; run it again when that run has finished (a poll logs `comms_ingest.run`). A poll that
  finds the lock held by an operator run logs `comms_ingest.skipped` and retries next interval.
- **`identity_kind_mismatch` quarantine.** A record whose provider id is already stored under
  the other identity kind is quarantined, for example an item first seen without a Message-ID
  (`provider_id_only`) and later published with one. The two key spaces never merge (ADR-022
  decision 4). This is expected, not a fault. The quarantine recurs, one row per snapshot that
  carries that provider id, and `records_identity_kind_mismatch` rises with each, until WP3b adds
  the explicit join. Nothing already stored is changed or lost: the earlier message keeps its
  observations, and the Message-ID message is built from the other provider ids that carry it.
  The quarantined records stay out of the communications rows until then. No operator action.
- **Restart.** Stability memory lives in the process. After a restart the first poll observes
  and the second reads; already-ingested digests are only linked.
- **Too large or unreadable.** Over the consumer's byte limit is `skipped_too_large`; an
  unreadable or hard-linked file is `skipped_unreadable`. Neither writes a snapshot.

## 10. Disabling

- **Stop the poll.** Comment the switch out again and recreate the service, or `disable` each
  source (`enable`/`disable` govern only the scheduled poll). With the daily cycle also off the
  plane exits 2.
- **Rows stay.** Nothing here deletes a snapshot, run or communication row, and the revision's
  downgrade refuses while rows exist.

## 11. Residuals

- `poll_enabled` stops at the first source whose workspace is unavailable; the poll is then
  logged `comms_ingest.failed` and retried after the interval.
- Every run (poll, `run-once` and backfill) reads and prepares every fresh file before its first
  snapshot transaction, holding each file's bytes and parsed publication together until the run
  applies them: at most the consumer's limit (64 MiB) times the number of fresh files, plus the
  parsed form. The first poll or backfill over the canonical 29-file folder holds all of them at
  once; size the cycles container's memory for that.
- A file whose parse raises (not a rejection: the handler failed) is counted `snapshots_failed`,
  writes nothing and is not remembered as finished, so every later poll reads and prepares it
  again until its bytes change. A `snapshots_failed` count that recurs every poll is that file.
- `aggregate` counts are over the rows the named sources' snapshots produced, deduplicated
  across sources; the WP1 file-level aggregate counts each publication separately.
