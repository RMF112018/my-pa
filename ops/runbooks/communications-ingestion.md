# Communications ingestion

**Status: UNEXECUTED / OPERATOR-GATED.** Nothing in this runbook has been run against the NAS or
the production database. Applying the migration, adding the overlay, admitting the sources,
running the backfill and turning the poll on are operator actions. They belong to the one
consolidated activation of the communications contract section 20.6 (Manager ruling R-OP-7) and
are written here so that activation can bundle them. The contract is
[`docs/architecture/communications-intelligence-contract.md`](../../docs/architecture/communications-intelligence-contract.md)
sections 1, 9, 10, 11, 18 and 19. Section 11 below is the meeting sync source (`meeting_sync_v1`,
communications intelligence WP3b): its admission, the reconciliation pass that gates it, and its
monitoring; its contract is
[`docs/architecture/meeting-sync-v1-contract.md`](../../docs/architecture/meeting-sync-v1-contract.md).

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
| `MY_PA_COMMUNICATIONS_INGEST_ENABLED` | `false` | Off: the cycles plane runs no ingestion poll, and so no scheduled meeting sync staging or apply (section 11.8). With it, `MY_PA_CYCLE_SCHEDULER_ENABLED` and `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` all off, the plane exits 2 (`plane cycles disabled`). |
| `MY_PA_COMMUNICATIONS_INGEST_POLL_SECONDS` | `900` | The poll interval, 60 to 86,400 s. |
| `MY_PA_FILES_WORKSPACES` | unset | Set by the overlay to `mcp=/srv/my-pa/workspaces/mcp;mode=read_only`. |

`MY_PA_COMMUNICATIONS_ENABLED` (the contract's read switch) is not introduced here: WP3a adds no
read capability for it to gate. It arrives with the reads in WP4.

## 3. Prerequisites

1. **Migration.** The image contains revision `52a829ef718a` (the ingestion and
   communications tables) and, for meeting sync (section 11), `61fafdfd2986` (the meeting sync
   staging and reconciliation tables, on `52a829ef718a`); the database is migrated to the
   image's single Alembic head before anything below runs. Every command refuses unless
   `--expected-alembic-head` equals the single `alembic_version` row.
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
  --expected-database my_pa --expected-alembic-head <HEAD> <command> ...
```

`<HEAD>` is the revision the database was migrated to (the image's single Alembic head, read
with the operator's read-only `psql` route from `public.alembic_version`); it is not
`52a829ef718a` once the WP3b revision is deployed.

On the NAS the command runs as a one-shot container of the cycles service, so it sees the same
env file and the same read-only workspace:

```sh
docker compose -p my-pa-remote-mcp -f ... \
  -f ops/nas/remote/compose.cycle-scheduler.remote.example.yml \
  -f ops/nas/remote/compose.comms-ingest.remote.example.yml \
  --profile remote-mcp run --rm --no-deps my-pa-cycle-scheduler \
  python apps/cli/communications_ingest.py --expected-database my_pa \
  --expected-alembic-head <HEAD> coverage --source isrc_...
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
them, and known bytes link `already_known` without a write. Each poll also runs the meeting sync
applier (section 11), which writes nothing to Meetings until the reconciliation latch exists.

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
  decision 4). This is expected, not a fault. The quarantine recurs, one row per record that
  carries that provider id (two records of one snapshot are two rows), and
  `records_identity_kind_mismatch` rises with each. There is no join: it was ruled out of scope
  (WP3b ruling D11) and the separation stands; a one-direction attach is a WP4 candidate if this
  count is non-zero on real data, so report it when it is. Nothing already stored is changed or
  lost: the earlier message keeps its observations, and the Message-ID message is built from the
  other provider ids that carry it. The quarantined records stay out of the communications rows.
  No operator action.
- **Restart.** Stability memory lives in the process. After a restart the first poll observes
  and the second reads; already-ingested digests are only linked.
- **Too large or unreadable.** Over the consumer's byte limit is `skipped_too_large`; an
  unreadable or hard-linked file is `skipped_unreadable`. Neither writes a snapshot.

## 10. Disabling

- **Stop the poll.** Comment the switch out again and recreate the service, or `disable` each
  source. For a communications source `enable`/`disable` govern only the scheduled poll; a
  disabled `meeting_sync_v1` source also has its staged publications held from Meetings
  (section 11.8). With the daily cycle and the project-reports poll also off the plane exits 2.
- **Rows stay.** Nothing here deletes a snapshot, run or communication row, and the revision's
  downgrade refuses while rows exist.

## 11. Meeting sync

The ChatLLM calendar collector writes `meeting_sync_v1` publications into the `mcp` workspace;
my-pa ingests them on the same lifecycle, poll and command as communications, then applies them
to Meetings. Sync is **stage-then-apply** (WP3b ruling D1): ingestion only stages; nothing
reaches a Meeting until the Principal has completed the reconciliation pass (section 11.4).
Everything here is part of the R-OP-7 consolidated activation and is unexecuted.

### 11.1 What it does

- **Staging.** A `meeting_sync_v1` snapshot is staged in its own transaction: one
  `meeting_sync_publications` row (stamp, counts, the declared `coverage`) and one
  `meeting_sync_events` row per accepted record (key and provider-owned fields only; no attendee,
  body or description). A quarantined record is counted only (`records_quarantined_<reason>`,
  ruling D14), never stored. Staged events are kept indefinitely (no retention yet).
- **Applying.** After each poll, in the same `comms_ingest` step and under its lock, and after
  every `run-once` and `backfill` (not `--dry-run`), `MeetingSyncApplier.apply_pending` applies
  every staged, unapplied publication of **every** `meeting_sync_v1` source of the Principal
  (whichever `--source` the command named): per source in `(generated_at_utc, file_sha256)`
  order, each publication in its own transaction, events in key order. It creates, updates and
  cancels Meetings as actor `system` (never deletes one), writes Meeting history and Record Events
  (`system.meeting_provider.sync`), and no audit row (ruling D9).
- **The gate.** Until the latch exists the applier writes nothing and counts
  `unapplied_awaiting_reconciliation`.

### 11.2 Prerequisites

1. **Migration** `61fafdfd2986` (section 3) and the overlay of section 3 (the meetings folder is
   under the same read-only `mcp` subtree).
2. **The collector (R-OP-8).** The operator applies the
   [collector checklist](../../docs/architecture/meeting-sync-v1-contract.md#8-collector-implementation-notes)
   once, at **schema version `1.1.0`**, before admission. Check in particular:
   - folder `My PA/Daily Intelligence/meetings/`, one `YYYYMMDD-meetings.json` per UTC date of
     `generated_at_utc`, written under another name and renamed into place;
   - `generated_at_utc` strictly increasing (persist the last stamp; last stamp plus 1 s when the
     clock does not move forward);
   - every timed event whose current start is no earlier than `generated_at_utc` minus 30 days
     (the collector lookback the pass relies on), occurrences expanded, cancelled ones sent as
     `cancelled`, all-day events and recurrence masters not sent, no body or description;
   - **`coverage`** `{start_utc, end_utc, calendar_refs}` on every publication whose calendar read
     completed: only calendars read completely over the whole window are listed; when none was,
     `coverage` is omitted. Never an empty or partial object: it rejects the whole publication
     (`invalid_coverage`). Without `coverage` my-pa never marks a binding `not_seen`.
3. **The client (R-OP-2, D13).** The reconciliation pass runs through the operator's connected
   client: activate ChatLLM profile `chatllm-data-v16` (instead of v15) and grant
   `meetings.provider.review` and `meetings.provider.reconcile`, with
   `meetings.provider.bind`, to the **operator profile only**, as part of the consolidated
   activation's grants.

### 11.3 Admission and staging

```sh
python apps/cli/communications_ingest.py <assertions> admit \
  --consumer meeting_sync_v1 --workspace mcp \
  --path-prefix "My PA/Daily Intelligence/meetings/" --file-pattern "*-meetings.json"
python apps/cli/communications_ingest.py <assertions> backfill --source <MEETINGS> --dry-run
python apps/cli/communications_ingest.py <assertions> backfill --source <MEETINGS>
```

Record the printed `ingest_source_id` as `<MEETINGS>`. The backfill stages what the folder
already holds; with the poll on (section 8) later files are staged as they arrive. The run's
`counts` carry `records_total`, `records_staged` and `records_quarantined` (and one
`records_quarantined_<reason>` per reason), with `records_total = records_staged +
records_quarantined`; its `meeting_sync_apply` object reads
`{"unapplied_awaiting_reconciliation": N}` until the pass is complete. A rejected snapshot
(for example `invalid_coverage`, or a missing `generated_at_utc`) stages nothing; the collector
must publish corrected bytes.

### 11.4 The reconciliation pass

The pass exists so sync does not duplicate the Meetings already made by hand (sync never matches
by title or time). It is done once, through the connected client, and it is one-way.

1. **Review.** `meetings.provider.review` answers the pass state (`pending`, `unreviewed_count`),
   up to 100 in-scope Meetings per page (not cancelled, starting no earlier than 30 days ago,
   with neither a binding nor a mark; page with `after` = `next_after`), and beside them the
   staged calendar events whose key is bound to nothing: at most 200 per page, by start then
   key, with `unbound_provider_events_total` and `unbound_provider_events_truncated` (more
   remain). While `unbound_provider_events_next` is not `null`, review again with
   `events_after` = that value to read the next page of events, until it is `null`: every
   event is reachable before the latch. If a new publication is staged during the sweep,
   restart the event sweep without `events_after`. The event cursor and the Meetings' `after` are
   independent. The two lists are never paired: the operator decides every match.
2. **Reconcile.** `meetings.provider.reconcile` with up to 50 items per call, each either
   `bind` (the Meeting, its `expected_version`, and the event's `provider_event_ref` from the
   review, or its full key; `adopt_provider_series` when the Meeting's series must follow the
   provider's) or `no_provider_event` (a Meeting the calendar does not have). Items are
   independent: a refused item changes nothing and the others apply. To retry it, either
   resend the **same batch** under the same idempotency key with the item fixed in place (the
   other items replay; the fixed one is evaluated again), or send the fixed item under a
   **new** idempotency key. Do not resend only the fixed item under the same key: its index
   may change, and a bind item's derived key is the batch key plus its index, so it collides with
   the bind item that had that index in the first send and is refused `idempotency_conflict`.
   There is no "mark all". Bound keys leave the event list, so repeat review then reconcile
   until `unreviewed_count` is `0`.
3. **Latch.** The reconcile that leaves no in-scope Meeting unreviewed answers `pass.state`
   `complete` and `sync_enabled: true`: the latch is recorded once and cannot be undone. When
   nothing is left to review, a reconcile with `items: []` records it.
4. **First apply.** The next poll, `run-once` or `backfill` applies every staged publication,
   the ones staged before the latch included: unbound events become new Meetings, bound ones
   update their Meetings. Check its `meeting_sync_apply` counts (section 11.6).

### 11.5 After the latch

- **Post-latch duplicate risk.** A Meeting made by hand after the latch, for an event the
  calendar also carries, is not matched: sync creates a second Meeting for that event. There is
  no delete or merge. Cancel the hand-made one (`meetings.update` with `status` `cancelled`) and
  keep the synced one, which sync keeps current. To avoid it, create calendar meetings in the
  calendar, not by hand, or bind the hand-made Meeting (`meetings.provider.bind`, or a
  reconcile item) before the publication carrying its event is applied.
- **The review stays usable.** It still lists in-scope Meetings without a binding or mark and
  the unbound staged events, so a hand-made Meeting can be bound or marked later; the latch is
  unaffected.
- **Unbind and tombstones.** An unbind (`meetings.provider.bind` `unbind`) records a tombstone
  for that key: sync then skips the key (`events_skipped_unbound_key_suppressed`) instead of
  creating a duplicate Meeting, and the review lists the event `suppressed: true`. Binding the
  key again (to that or another Meeting) wins; the tombstone stays, and there is no way to
  release it so sync re-creates the Meeting.
- **`not_seen`.** A bound event missing from a publication whose `coverage` lists its calendar,
  with its Meeting's current start inside the window, marks the **binding** `not_seen`
  (`bindings_marked_not_seen`). It is state only: the Meeting is never changed or cancelled, and
  the next publication that carries the event restores it. Any quarantined record in the
  publication suppresses the whole pass (`not_seen_suppressed_quarantine`). An event moved out
  of the window may read `not_seen` until it is seen again.

### 11.6 Monitoring

The poll logs one `meeting_sync.apply` line after each `comms_ingest.run`, with the applier's
counts; `run-once` and `backfill` print the same object under `meeting_sync_apply`. All are closed
names and integers:

| Count | Meaning |
| --- | --- |
| `unapplied_awaiting_reconciliation` | staged publications waiting for the latch (before the pass only) |
| `publications_applied` | publications applied this call |
| `publications_skipped_stale`, `publications_skipped_ordering_conflict` | a stamp older than, or equal to, the source's newest applied publication: nothing applied (a producer clock regression shows here) |
| `publications_held_source_disabled` | staged publications of a disabled source, held (section 11.8) |
| `publications_failed` | a publication whose transaction failed (section 11.7) |
| `events_created`, `events_updated`, `events_unchanged`, `events_replayed`, `events_skipped` | per event; each skip also counts `events_skipped_<diagnostic>` (for example `stale_record_skipped`, `cancelled_unknown_skipped`, `unbound_key_suppressed`) |
| `bindings_marked_not_seen`, `not_seen_suppressed_quarantine` | section 11.5 |

Read-only checks (the operator's read-only `psql` route):

```sql
SELECT ingest_source_id, apply_outcome, count(*), max(generated_at_utc)
FROM knowledge.meeting_sync_publications GROUP BY 1, 2 ORDER BY 1, 2;
SELECT ingest_source_id, snapshot_id, generated_at_utc, quarantined_count
FROM knowledge.meeting_sync_publications WHERE applied_at IS NULL
ORDER BY ingest_source_id, generated_at_utc LIMIT 10;
SELECT completed_at, reviewed_meetings FROM knowledge.meeting_provider_reconciliation_passes;
SELECT provider_state, count(*) FROM knowledge.meeting_provider_bindings GROUP BY 1;
SELECT count(*) FROM knowledge.meeting_provider_key_tombstones;
```

### 11.7 `publications_failed`

A publication whose apply transaction raised rolled back alone, stays unapplied, and **blocks
its source**: the applier stops that source's pass there, so no later publication of it can be
applied ahead of it, and every later poll retries it. The other sources continue. `run-once` and
`backfill` exit `3` while it fails, and the poll step reports the attempt failed.

- **Find it.** It is the source's oldest unapplied publication after the latch (the second query
  of section 11.6). The counts carry no error text, by design.
- **Transient** (a lock timeout, a restart): it clears on the next poll; `publications_failed`
  stops and `publications_applied` resumes.
- **Persistent** (it recurs every poll): the failure is in the data or the code, not the
  schedule. Disable the source (section 11.8) so the poll stops retrying, take a copy of the
  database into an isolated environment and run `run-once` there to reproduce it, and fix the
  cause. Nothing is skipped by hand: there is no command that marks a publication applied.

### 11.8 Disabling

- `disable --source <MEETINGS>` stops the poll staging new files **and** holds the source's staged
  publications: once the latch exists they are counted `publications_held_source_disabled` and
  nothing of theirs reaches a Meeting (a disable committed during a run holds the rest of that
  source). A backfill of a disabled source still stages. `enable --source <MEETINGS>` resumes
  them, in order, at the next poll or `run-once`.
- Turning the poll off (`MY_PA_COMMUNICATIONS_INGEST_ENABLED`, section 10) stops scheduled
  staging and applying alike: there is no separate apply schedule. An operator `run-once` or
  `backfill` still applies what is staged for every enabled source, once the latch exists.
- Nothing deletes staged publications, events, marks, the latch or tombstones; the WP3b
  revision's downgrade refuses while any exists.

## 12. Residuals

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
- Meeting sync: a Meeting made by hand after the latch can be duplicated (section 11.5);
  `not_seen` is only as good as the collector's `coverage` claim; a tombstone cannot be released;
  staged publications and events are never pruned (retention deferred, ruling D14).
