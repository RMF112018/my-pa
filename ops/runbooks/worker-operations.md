# Worker operations

Running, bounding, and stopping the `my-pa` worker process.

Every command below was executed against a **disposable** database
(`my_pa_worker_runbook_test`, created and dropped for the purpose) on
2026-08-02. Nothing here was run against the canonical `my_pa` database, and
nothing here needs to be: the worker writes to the `knowledge` schema's job
plane, and pointing it at the canonical database before there is work worth
doing would put attempt counts on rows nobody queued.

## What the worker is, and what it does not yet do

`apps/worker.py` claims one queued job under a bounded lease, runs a handler
inside the transaction that will also record the completion, and then completes
or releases it. It stops cleanly on `SIGINT` or `SIGTERM`.

**There is no extraction executor wired to it.** A claimed job is released as
`unavailable`, and after its bounded attempts the job becomes terminal `failed`.
`apps/worker.py`'s module docstring states why: nothing bridges the object
identifiers a source provider mints to the `source_objects` rows the extraction
writer records outcomes against, and building that bridge is a source
registration and enumeration design rather than a lease loop. In practice the
worker finds no work at all, because nothing registers a source.

Read that as: running this worker today is safe and does nothing. It is here so
that the process, its lease discipline, and its shutdown are real and tested
before anything depends on them.

## Configuration

One required variable, and no default (`P00-OD-008`):

```text
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/<database>
```

Supply the password out of band with `PGPASSWORD` or `~/.pgpass`. The worker
adds no configuration of its own; the lease and poll intervals are flags on the
invocation, because they are properties of a particular run rather than of the
installation.

## Running

```bash
# Until signalled.
.venv/bin/python apps/worker.py run

# One iteration and exit — the safe way to see whether there is work.
.venv/bin/python apps/worker.py run --once

# A bounded drain.
.venv/bin/python apps/worker.py run --max-iterations 20 --lease-seconds 60
```

Every run prints counts and nothing else:

```text
owner        worker-9c45135a10897468
iterations   1
claimed      0
completed    0
released     0
lost         0
idle         1
```

`owner` is the lease-owner token this process minted. It is random and names no
machine — `AGENTS.md` §5 keeps hosts out of columns operators read, and
`persistence/jobs.py` refuses a name that could be one. `lost` counts attempts
whose lease was taken by another worker before they finished; their work was
rolled back, which is the intended outcome and not an error to chase.

Observed against the disposable database with one queued job and
`--max-iterations 6`:

```text
iterations 6, claimed 3, completed 0, released 3, idle 3
```

and the job row afterwards:

```text
state=failed  attempt_count=3  max_attempts=3  lease_owner=NULL  last_error_code=unavailable
```

Three attempts, then terminal. The bound is the row's, not the loop's: a job
whose attempts are spent stops being claimable by *any* worker.

## Stopping

Send `SIGINT` (Ctrl-C) or `SIGTERM`. The worker finishes the job it is holding,
releases or completes it, prints its counts, and exits `0`. It does not abandon
a lease, and it does not commit half-finished work: the handler and the
completion share one transaction.

Observed: `kill -TERM` against a worker idling on a 1-second poll exited `0`
within the poll interval and printed its summary.

A second signal is left to Python's default handling. An operator asking twice
is asking for the process to go now.

## Recovery

There is no sweeper and nothing to restart.

- A worker that dies mid-attempt leaves its lease to expire. The next claim by
  any worker reaps and re-claims it, and the attempt the dead worker spent is
  still counted, so the bound converges.
- A job whose final attempt was abandoned is made terminal by the next
  `claim_job`, which reaps before it claims. `sources.status` derives the same
  answer from the same predicate in the meantime, so a status read is honest in
  the window before that happens.
- A worker whose lease expired while it was working discovers it at
  `complete_job`, which matches on the owner. Its work is rolled back rather
  than committed beside the new owner's.

## Checking the job plane

```bash
psql "$MY_PA_DATABASE_URL" -c \
  "SELECT state, count(*) FROM knowledge.jobs GROUP BY state ORDER BY state"

psql "$MY_PA_DATABASE_URL" -c \
  "SELECT operation_id, state, attempt_count, max_attempts, last_error_code \
   FROM knowledge.jobs WHERE state <> 'succeeded' ORDER BY created_at"
```

These were not run as written: the queries above are the ones the checks in this
runbook performed through SQLAlchemy rather than through `psql`, and the client
form is given because it is what an operator has to hand. The columns and values
are the ones observed.

## What this runbook does not cover

Deployment, service supervision, log shipping, retention of the audit trail, and
production activation. All operator-gated (`AGENTS.md` §5). Audit retention in
particular is `P00-OD-013` and is open: `knowledge.audit_events` is append-only
and there is deliberately no procedure here for trimming it.
