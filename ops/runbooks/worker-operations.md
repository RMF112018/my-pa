# Worker operations

Running, bounding, and stopping the `my-pa` worker process.

Every command below was executed against a **disposable** database
(`my_pa_worker_runbook_test`, created and dropped for the purpose) on
2026-08-03, **and none of them was re-executed for WP-6** — this file is unchanged
since `6660dbb` and no transcript in it was produced at head `1a4c9e77b2d5`. They
were not re-run because WP-6 adds no work to the extraction job plane this
runbook drives; the capture outbox it creates is consumed by nothing until WP-7.
*Disclosure added 2026-08-03: the date above is the same string the re-executed
runbooks use for their 2026-08-03 markers, so date alone cannot tell a reader
which transcripts are current. It is the head that discriminates, and this file's
is `af3d35efb9c0`.*

*Amended 2026-08-29: the "Which plane" section below was added by the RI
remediation campaign, so this file is **no longer unchanged since `6660dbb`**.
Nothing in that section is a transcript — the re-enrichment counts shown there
are the shape `apps/worker.py::_report_reenrichment` prints, read from the
source. Every transcript in this file is still the 2026-08-03 `enrollment` run
described above, and none was re-executed.*

Nothing here was run against the canonical `my_pa` database, and
nothing here needs to be: the worker writes to the `knowledge` schema's job
plane, and pointing it at the canonical database before there is work worth
doing would put attempt counts on rows nobody queued.

## What the worker is, and what it does

`apps/worker.py` claims one queued job under a bounded lease, runs the extraction
executor, and then completes or releases the job. It stops cleanly on `SIGINT` or
`SIGTERM`.

One claimed job is one enrollment's outstanding objects. For each, the provider
its source is configured with is asked to describe and read the object, the text
extractor decides what came back, and the outcome is stored — an extraction, an
`unsupported` row, or a quarantine with the reason that stopped it.

**Work commits per object, and that is a property to know before reading a job
row.** The bytes cannot be read inside a database transaction
(`docs/architecture/module-boundaries.md` section 10), so the handler is given
the engine rather than an open connection and opens one short transaction per
object. Each of those transactions re-asserts the lease as its first statement,
so a worker whose lease has been taken stops writing at the object it lost it on.
What it had already committed stays, is true, and is skipped by the worker that
takes over — convergence, not a partial write to be cleaned up.

## Getting there from nothing

A worker finds work only when a source has been registered and part of it
enrolled. Both steps are operator commands:

```bash
# 1. Configure a root. Prints the source_id and the root_object_id, never the root.
.venv/bin/python apps/cli/sources.py register \
    --provider fixture --root fixtures/mcv/root \
    --label "MCV fixture corpus" --classification synthetic_test

# 2. Grant a bounded enrollment over it. Operator-only, authorized, and audited.
.venv/bin/python apps/cli/invoke.py sources.enroll \
    --request-id req-0002 --purpose bounded_enrollment \
    --principal-id prn_00000000000000000000000000 \
    --requested-at 2026-08-03T07:00:00Z \
    --payload '{"source_id":"<src_…>","root_object_id":"<obj_…>","depth":0,
                "media_types":["text/markdown","text/plain"],
                "idempotency_key":"runbook-1","max_items":100,"max_bytes":65536}'

# 3. Run the worker.
.venv/bin/python apps/worker.py run --max-iterations 2
```

Observed, in that order, against the disposable database and `fixtures/mcv/root`.
Step 1 printed a `source_id` and a `root_object_id` and no path. Step 2 answered
`created: true` with `coverage.eligible = 4` and `state: queued` — the four files
under the root, measured at acceptance rather than estimated. Step 3 printed
`claimed 1, completed 1, idle 1`, and the enrollment then read:

```text
eligible 4  processed 2  unsupported 2  quarantined 0  state partially_processed
```

The two `unsupported` rows are `handbook.pdf` and `opaque.bin`. **A PDF is
reported, not skipped**: `P00-OD-003` is open, no PDF library is a dependency of
this repository, and the honest answer is a counted `unsupported` outcome rather
than an absence. `partially_processed` is the truthful state for a scope that
holds objects this extractor does not read.

Re-running `sources.py register` over the same root prints the same
`source_id` and `root_object_id`: registration is idempotent on
`(provider_kind, native_root)`. A root that is not an existing directory is
refused with exit `1` and the message `the configured root is not an existing
directory`, which names the defect and not the path.

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

### Which plane

One process serves one plane, named by `--plane`. `apps/worker.py` derives the
flag's `choices` from its own closed `_PLANES` set, so a plane cannot exist that
the flag will not accept, and running more than one plane means running the
command more than once. There are three:

```bash
# The default. Extraction over enrolled source objects.
.venv/bin/python apps/worker.py run --plane enrollment

# The capture pipeline over stored capture versions.
.venv/bin/python apps/worker.py run --plane capture

# Relationship Intelligence re-enrichment.
.venv/bin/python apps/worker.py run --plane reenrichment
```

- `enrollment` is what the rest of this runbook is about, and what `run` with no
  `--plane` selects.
- `capture` runs the capture pipeline over one stored capture version. It reads
  no source, opens no socket and calls no model: everything it works from is text
  already in the database.
- **`reenrichment`** is the Relationship Intelligence plane, added with the RI
  remediation work. One claimed item is one durable invalidation: the binding's
  exact subject, input, producer and policy versions are re-read and locked, and
  the item is applied only if none of them has moved since it was registered.
  What it applies is a deterministic re-resolution of mention→identity linkage
  against the corrected identity graph — there is no derived cache anywhere in
  this repository to invalidate, so the obligation is met by recomputation. It
  reads no source, opens no socket and calls no model either.

**`reenrichment` is not on the shared job loop, and the reason is in the table
rather than in a preference.** `knowledge.entity_reenrichment_work` is
deliberately not a `JobPlane`: it carries its own lease columns, its own
`next_attempt_at`, a terminal vocabulary that includes `partial` and `stale`, and
a version-currency fence no job plane has. So it has its own loop in
`infrastructure/jobs/reenrichment.py`, and it prints its own counts rather than
the shared ones — `succeeded`, `partial`, `stale`, `failed`, `idle` and
`rebound` in place of `completed`, `released` and `lost`:

```text
owner        worker-<token>
plane        reenrichment
iterations   …
claimed      …
succeeded    …
partial      …
stale        …
failed       …
idle         …
rebound      …
```

`partial` is the line to read first. A re-enrichment that produced some of its
intended effects settles `partial` rather than `succeeded` or `failed`, because
both of those would be false, and the migration that admitted the state
(`b727e870d45e`) pairs it with a `limitations` column that must be written with
it. `stale` means a version moved between registration and apply and the item was
correctly not applied. Neither is an error to chase.

The heartbeat is the same content-free row the other two planes write;
`worker_health.record_worker_heartbeat` admits `reenrichment` as a plane, so an
absent re-enrichment worker and a working one are no longer the same observation.
It differs only in where it finds the Principals to report for: there is no
`JobPlane.table` to select from, so the outstanding partition comes from
`entity_reenrichment_work` itself.

`--poll-seconds` still overrides the interval, so an operator sets one flag
either way. The operator document for the plane this serves is
[`relationship-intelligence.md`](relationship-intelligence.md).

**Not executed.** The transcripts in the rest of this runbook are from observed
`enrollment` runs. The `reenrichment` output above is the shape
`apps/worker.py::_report_reenrichment` prints, read from the source rather than
captured from a run; no re-enrichment worker has been run against a populated
queue here.

Every run prints counts and nothing else. Observed against the disposable
database with one queued enrollment and `--max-iterations 2`:

```text
owner        worker-44556ee7c883fb38
iterations   2
claimed      1
completed    1
released     0
lost         0
idle         1
```

`owner` is the lease-owner token this process minted. It is random and names no
machine — `AGENTS.md` §5 keeps hosts out of columns operators read, and
`persistence/jobs.py` refuses a name that could be one. `idle 1` is the second
iteration finding an empty queue, which is how the loop reports "nothing to do"
rather than by blocking.

`lost` counts attempts whose lease was taken by another worker before they
finished. Such an attempt stopped writing at the object it lost the lease on and
never reported the job finished; the objects it had committed before that are
kept and are skipped by the worker that took over. It is the intended outcome and
not an error to chase.

`released` counts attempts that failed. A failed attempt returns the job to
`queued` while attempts remain and to `failed` once they do not — three attempts,
then terminal, with the error code of the last one. The bound is the row's, not
the loop's: a job whose attempts are spent stops being claimable by *any* worker.

## Stopping

Send `SIGINT` (Ctrl-C) or `SIGTERM`. The worker finishes the job it is holding,
releases or completes it, prints its counts, and exits `0`. It does not abandon a
lease, so nothing is left `running` for another worker to wait out.

It does not *undo* the objects it had already recorded, and that is deliberate
rather than an oversight: those outcomes were committed under a live lease, they
are true, and the next run starts from the objects that have no outcome yet.

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
- A worker whose lease expired while it was working discovers it at the *next
  object it tries to write*: every write transaction re-asserts the lease as its
  first statement and rolls back when it is gone. It also discovers it at
  `complete_job`, which matches on the owner, so `succeeded` is never written by
  a worker that no longer holds the job. What it committed under the live lease
  stays; the worker that takes over is offered only the objects with no outcome,
  so nothing is done twice.

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
