# Daily Morning Intelligence cycle scheduler

**Status: UNEXECUTED / OPERATOR-GATED.** Nothing in this runbook has been run against the NAS.
Deploying the image, adding the overlay, and turning the switch on are operator actions.
The contract is the ADR-010 amendment of 2026-11-20
([`docs/decisions/ADR-010-intelligence-artifact-report-plane.md`](../../docs/decisions/ADR-010-intelligence-artifact-report-plane.md)).

## 1. What it does

At 00:00 `America/New_York` every day, the `cycles` worker plane (`apps/worker.py run --plane cycles`) does two things for business date *D* (the local date):

1. **Close.** Every `open` or `running` `morning_intelligence` cycle of the operator Principal dated before *D* is closed. It becomes `complete` if any artifact was committed under it, and `cancelled` otherwise. Each cycle closes in its own transaction. A failed close is logged and retried on the next run.
2. **Begin.** It calls `reports.begin_cycle` for *D* with the idempotency key `auto-morning_intelligence-<D>`. This runs even if the close step failed. If ChatLLM already began a cycle for *D*, the call returns that cycle (`created: false, replayed: true`). A ChatLLM call made after this run likewise gets the scheduler's cycle.

When the process starts, it runs at once for the current local date. That is the catch-up rule. Missed earlier dates are never backfilled. Rerunning for the same date writes nothing new. A session advisory lock admits one run at a time across processes.

The same plane also runs the communications ingestion poll when `MY_PA_COMMUNICATIONS_INGEST_ENABLED` is on ([`communications-ingestion.md`](communications-ingestion.md)) and the project-reports ingestion poll when `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` is on ([`project-reports-ingestion.md`](project-reports-ingestion.md)), each as a separate step with its own lock and interval. The plane has three switches (these two and `MY_PA_CYCLE_SCHEDULER_ENABLED`): any one of them alone starts the plane, and only the steps whose switch is on run; with all three off it exits 2.

A new `reports.commit` or `reports.record_run_state` to a closed cycle is refused with `conflict` and the details `cycle_run_id` and `cycle_closed`. ChatLLM producers should call `reports.begin_cycle` for the new date and use the `cycle_run_id` it returns.

## 2. Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MY_PA_CYCLE_SCHEDULER_ENABLED` | `false` | Off: the daily close-and-begin step does not run. With it and both ingestion switches off, the plane exits 2 with `plane cycles disabled` before touching the database. It withholds no capability. |
| `MY_PA_CYCLE_SCHEDULER_TIMEZONE` | `America/New_York` | IANA zone for local midnight. An unknown zone fails settings load. |

The run time (local 00:00) is fixed and not configurable. Neither variable is a secret. The process reads `MY_PA_DATABASE_URL` from the same owner-only env file the remote MCP app uses.

## 3. Prerequisites

- An image built from a commit that contains this plane. **No migration is needed**: the cycle table already has `state`, `version` and `finished_at`.
- The new `reports.begin_cycle` rule (one open cycle per date) and the late-write refusal ship in the serving app in the same image. Recreate `my-pa-mcp-remote` on the new image too, not only the scheduler.

## 4. Enable (remote MCP project, NAS)

Add [`ops/nas/remote/compose.cycle-scheduler.remote.example.yml`](../nas/remote/compose.cycle-scheduler.remote.example.yml) to the `-f` list the live project already uses (the files in the app container's `com.docker.compose.project.config_files` label), with the same env file and image id. Then:

```sh
docker compose -p my-pa-remote-mcp -f ... -f ops/nas/remote/compose.cycle-scheduler.remote.example.yml \
  --profile remote-mcp up -d my-pa-cycle-scheduler
docker logs --tail 20 my-pa-remote-mcp-my-pa-cycle-scheduler-1
```

The first log line should be a JSON object with `"event": "cycle_scheduler.run"`, today's `business_date`, a `cycle_run_id`, and `begin_error: null`. It also carries the counts `closed_complete`, `closed_cancelled`, `already_closed` and `close_failed`, plus `created` and `replayed`. A `"cycle_scheduler.skipped"` line means another process held the lock. A `"cycle_scheduler.failed"` line means the run raised. That date stays due and is retried on the next poll (60 s).

### Read-only verification

Use the read-only `psql` route the operator already uses for production:

```sql
SELECT business_date, state, version, created_at, finished_at
FROM knowledge.intelligence_cycle_runs
WHERE cycle_id = 'morning_intelligence'
ORDER BY business_date DESC, created_at DESC LIMIT 10;
```

Expect exactly one `open` row for today and no `open` or `running` row dated before today. `knowledge.audit_events` has one `reports.begin_cycle` row per scheduler run.

## 5. Rollback

- **Stop scheduling.** Run `docker compose -p my-pa-remote-mcp ... rm -sf my-pa-cycle-scheduler` and drop the overlay from the `-f` list. Setting `MY_PA_CYCLE_SCHEDULER_ENABLED=false` instead stops the daily step; the plane exits 2 only when both ingestion switches are off too. With `restart: unless-stopped`, remove the service rather than leaving it to restart. ChatLLM's `reports.begin_cycle` keeps working.
- **Closed cycles stay closed.** Nothing reopens a cycle. A ChatLLM begin for a date with no open cycle creates a new one.
- **Full code rollback.** Deploying the previous image restores the old `reports.begin_cycle` behaviour (a new key always creates a cycle) and accepts writes to closed cycles again. The rows written meanwhile are valid under both versions.

## 6. Residuals

- The close transition writes no `knowledge.audit_events` row. Its record is the cycle row and the log line.
- Nothing writes `running` or `failed`. A producer still running at midnight gets `cycle_closed` on its next write and must begin the new date's cycle.
- No compose service is added to the NAS core contract stack (`ops/nas/compose.example.yml`). The scheduler runs only in the remote MCP project, where the operator Principal's live data plane runs.
