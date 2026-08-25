# Gateway operations

Running, calling, and stopping the `my-pa` HTTP gateway.

The same composition root also serves the Model Context Protocol on stdio
(`apps/gateway.py mcp`), and there is a third transport in `apps/cli/invoke.py`.
Both are covered by
[`mcp-and-cli-operations.md`](mcp-and-cli-operations.md); everything below about
configuration, statuses, connections, and the audit trail applies to all three,
because they are one composition and differ only in protocol.

Every command below was executed against a **disposable** database
(`my_pa_gateway_runbook_test`, created at head and dropped for the purpose) on
2026-08-02, **except where a transcript is marked otherwise** — one block, the
`capabilities.get` call, was re-executed 2026-08-03 against a disposable database
at head `1a4c9e77b2d5` and says so where it sits. *Scope clause added 2026-08-03:
this sentence was an unqualified universal over a document that had since acquired
a transcript from a different run at a different head, which is what
[`README.md`](README.md) asks a procedure to disclose.* Nothing here was run
against the canonical `my_pa` database.

**Corrected 2026-08-03: the reason first given here was incomplete, and the true
one is stronger.** It said pointing the gateway at canonical `my_pa` "would be
safe to read from and would write audit rows for requests nobody made", which
reads as politeness. Measured: canonical `my_pa` is at `6c4d3ea82f10` while the
chain ends at `1a4c9e77b2d5` (re-measured 2026-08-03; it was `af3d35efb9c0`
until WP-6 added the capture revision) and it carries **no `knowledge` schema**,
so it has
no `knowledge.audit_events` to commit the audit row every served request writes
— every request fails inside the unit of work and the caller is told
`internal_error`, which explains nothing (`D-61`, `D-65`). Run
`.venv/bin/python apps/cli/health.py` against a database before pointing this
process at it; that is what it is for, and
`ops/runbooks/end-to-end-operations.md` makes it step 1.

Everything below therefore describes a gateway over a database at head. **Head is
not the narrowest state in which it answers *something*** — at `9c6b4a18ed72`,
now two revisions behind head and one behind it when this was measured,
`capabilities.get` serves and `sources.list` answers as
it does at head (`D-61`) — but it is the narrowest state in which it answers
*everything*: at that same revision `sources.enroll` returns `internal_error`
because `af3d35efb9c0` creates `enrollment_objects`, and every `capture.*`
request does too, because `1a4c9e77b2d5` creates the capture tables and widens
`audit_events.capability` to admit a capture at all. Point this process at head.

## What the gateway is, and what it does not yet do

`apps/gateway.py` routes the ninety-nine public capabilities over HTTP on
loopback and, in a default process, serves fifty-three of them.
One request is one call to `ApplicationService.invoke`, and the response body is
the envelope that call produced — the transport maps and does not decide.

**Corrected 2026-08-19: this line read "serves the fifty-four public
capabilities", and a default gateway does not.** Three families are composed
only when their variable is set — the six `documents.` names behind
`MY_PA_MANAGED_DOCUMENT_ROOT`, the thirty-one `entities.` names behind
`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` (whose eighteen writes need
`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` as well), and the nine
`relationship_memory.` names behind `MY_PA_RELATIONSHIP_MEMORY_ENABLED` and the
entity plane together. None of the four has a default.
`/v1/{capability}` is a path parameter, so all of them *route*: dispatch
reaches the handler, which refuses with `unsupported` and the transport maps that
to **`501`**. This section already discloses the source-root gate below in the
same detail; it said nothing about these two, which is the omission being
corrected. `capabilities.get` on such a process reports readiness `degraded` and
`12 of 65 capabilities are unwired.` rather than `ready`.

**It is bound to `127.0.0.1` and there is no option to bind elsewhere.** That is
`D-30` and `AGENTS.md` §5: `P00-OD-010` — which authentication mechanism this
uses — is open and reserved to the operator, so the gateway issues, reads, and
requires no credential, and configures no TLS. The address is a constant in the
source rather than a flag with a safe default.

**No root is configured here, and there is no default one.** The three
source-reading capabilities answer `unavailable` for every source no operator
has registered, and the process says so at startup — unconditionally, because
that sentence is true either way and startup reads no store to decide it.
`apps/cli/sources.py register` is what creates a `knowledge.sources` row, and
`P00-OD-009` is untouched by it: the command requires `--root` by exact path, so
which roots are legitimate stays the operator's decision rather than this
composition's. `capabilities.get`, `sources.status`, `sources.enroll`,
`knowledge.search` and `knowledge.read` reach the database and answer for real.

Read that as: running this gateway today is safe and answers truthfully, and the
corpus it can answer about is exactly the one an operator registered and
enrolled — nothing wider, and nothing this repository chose.

## Configuration

One required variable, and no default (`P00-OD-008`):

```text
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/<database>
```

Supply the password out of band with `PGPASSWORD` or `~/.pgpass`. The gateway
adds no configuration of its own; the port is a flag on the invocation, because
it is a property of a particular run.

The limits `capabilities.get` publishes are the configured ones
(`MY_PA_MAX_PAGE_SIZE` and the three beside it), clamped down to the domain's
own ceilings where those are lower. The run below was made with the defaults and
published `max_page_size: 100`, not the configured `200`, because
`domain.search.query.MAX_PAGE_SIZE` is 100 and a published maximum that is not
enforced is not a maximum.

## Running

```bash
# The default port, 8765.
.venv/bin/python apps/gateway.py run

# Somewhere else.
.venv/bin/python apps/gateway.py run --port 9000

# The same capabilities over MCP on stdio; see mcp-and-cli-operations.md.
.venv/bin/python apps/gateway.py mcp
```

Startup prints two lines and nothing more. There is no access log and no
per-request log line: the application emits no log records at all, and a
per-request line is the one place a path, a query, or a principal would reach a
file.

```text
serving     http://127.0.0.1:8765/v1/<capability>
notice      sources.list, sources.metadata and sources.fetch answer 'unavailable' for every source no operator has registered; registration names the source's root by exact path, and this process configures none
```

## Calling it

One route: `POST /v1/<capability>`, `content-type: application/json`, with a
`content-length` — a body with no declared length is refused, because a length
that arrives after the body cannot bound it.

The document carries the common request metadata and the capability's own fields
under `payload`. `principal_id` is correlation input: the acting principal is the
process's own, and a caller naming a different one does not become it.

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/capabilities.get \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-1",
       "purpose":"status_observation",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-02T12:00:00Z",
       "payload":{}}'
```

**Current-state correction (2026-08-23):** the candidate has **ninety-nine**
capabilities and **seventy-five** Alembic revisions at head `3d07af4dc513`.
`capabilities.get` now also returns `worker_planes`; backlog without a live
heartbeat is `worker_absent`/`worker_stale`, never silently healthy. The dated
transcript below remains historical evidence for its stated head.

The Task/Commitment plane comprises the fourteen previously admitted names plus
`commitments.search`, `commitments.history`, and `commitments.update`. Its full
HTTP vocabulary is `tasks.read`, `tasks.list`, `tasks.search`, `tasks.history`,
`tasks.create`, `tasks.update`, `tasks.transition`, `tasks.bulk_preview`,
`tasks.bulk_confirm`, `commitments.read`, `commitments.list`,
`commitments.search`, `commitments.history`, `commitments.waiting_on`,
`commitments.create`, `commitments.update`, and `commitments.close`.

**Re-executed 2026-08-03**, against a disposable database at head
`1a4c9e77b2d5`, because WP-6 changed what this answers. Observed: `200`,
`content-type: application/json`, and an envelope whose `result.manifest` lists
**twelve** capabilities `available`, `application/pdf` `decision_gated`, and
`readiness.state: ready`. No `server` header.

```text
HTTP/1.1 200 OK
content-length: 2509
content-type: application/json
```

```text
result.manifest.capabilities        12, every one `available`
result.manifest.content_types       text/markdown available, text/plain available,
                                    application/pdf decision_gated
result.readiness.state              ready
result.readiness.implemented        12 of 12
```

It read "eight capabilities" until this run. The count came from the four
`capture.*` capabilities WP-6 wired; nothing about the shape of the answer
changed.

**What `readiness.state` measures, since an operator will read it as a probe.**
It counts wired handlers in the manifest, so its *derivation* is build-time. Its
*observation* is not: `ApplicationService._run` opens the unit of work before it
dispatches, so a caller sees this value only from a database that was reachable
and writable and could record the request's audit row. Measured (`D-61`):
unreachable answers `unavailable`; a database before `9c6b4a18ed72`, which
creates `knowledge.audit_events`, answers `internal_error`; and `9c6b4a18ed72`
itself — one revision behind head when that was measured, two behind
`1a4c9e77b2d5` now — answers `ready`, the same as head, while
`sources.enroll` on that same database answers `internal_error`. So this
transcript is accurate and this envelope is a liveness signal, but it diagnoses
nothing and it is **not** a head check: a `ready` here does not mean every
capability will serve. `apps/cli/health.py` is what reports revision against
head, and it is stricter than this envelope on purpose.

A request for a scope the principal does not hold:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/sources.list \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-2","purpose":"source_inspection",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-02T12:00:00Z",
       "payload":{"source_id":"src_0123456789abcdef"}}'
```

Observed: `403`, `error.code: denied`, and no denial reason in the body — the
reason is in the audit trail, where an operator can read it and a caller cannot.

A body that is not JSON:

```text
400 {"code":"invalid_request","correlation_id":"corr_…","message":"the request is
     malformed, incomplete, or contradictory","retry":"after_correction",
     "safe_details":[]}
```

That shape — a problem without an envelope — is what a request the application
never saw answers with. An envelope requires the caller's `request_id`, and a
request that could not be read has none to carry.

A capability that does not exist (`POST /v1/sources.destroy`) is the same `400`.
An unknown *path* is `404` and a non-`POST` method is `405`, both with the same
body shape.

A client that announces a `content-length` and then sends nothing is refused
`400 invalid_request` after five seconds. Observed: the refusal arrived at 5.0s;
the connection itself closed five seconds later, which is uvicorn's keep-alive
idle rather than the gateway still working. The bound exists because the
endpoint reads the body on a worker thread, so an unbounded wait is a thread
held for as long as a client cares to hold it — forty-five such clients stopped
the gateway answering entirely before this bound was added. It is bounded, not
free: while stalled clients hold workers, a real request waits for them to time
out.

## Statuses

The status of an answer the application produced is a function of its error
code, and of nothing else: `200`, then `400` for `invalid_request` and
`ambiguous_request`, `403` for `denied` and `quarantined`, `404` for
`not_found`, `409` for `conflict` and `cancelled`, `429` for `rate_limited`,
`500` for `internal_error`, `501` for `unsupported`, `503` for `unavailable`.

A database that is unreachable answers **`503 unavailable`**, with retry
guidance `conditional` — the store is down, not the gateway. Start PostgreSQL
and retry; nothing needs restarting here. `500 internal_error` means something
this build did not classify, and is a defect to report rather than a condition
to wait out.

## Stopping

Send `SIGINT` (Ctrl-C) or `SIGTERM`. Uvicorn stops accepting, waits for the
requests already in flight, closes the loop, and then re-raises the signal it
captured — so the process exits **by** the signal, status 143 for `SIGTERM`,
rather than returning zero. That is correct: a process stopped by a signal
should report that it was.

**The wait is bounded at thirty seconds** (`timeout_graceful_shutdown`, equal to
the connection pool's own checkout timeout). Without that bound a single request
that never finished was a process that never stopped, which is what stalled
clients produced before the body bound above existed. Two mechanisms now make
the promise keepable, and the runbook is only worth as much as the second one.

Observed: `kill -TERM` against an idle gateway exited within a second with no
further output. The in-flight guarantee is asserted rather than eyeballed —
`tests/contract/test_http_gateway_process.py` holds a request inside `invoke`,
asks for shutdown, releases it, and requires a complete envelope back.

## Connections

The gateway holds **two** pools against one database, five connections each, ten
in total. That is not symmetry: the audit sink writes on its own connection so
that the record of an authorization survives the rollback of the work it
describes, and with one shared pool five concurrent requests would each hold a
work connection while waiting for an audit connection that only another waiting
request could release. `src/my_pa/bootstrap/gateway.py` derives the sizes and
`tests/concurrency/test_gateway_connection_pool.py` measures both compositions.

To see what the gateway is using:

```bash
psql "$MY_PA_DATABASE_URL" -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
```

Ten is the ceiling, not the resting state: both pools open connections lazily.
Observed after the requests above, and after this query opened one of its own,
was **3**. Not run as written; the count was taken through SQLAlchemy, and the
client form is given because it is what an operator has to hand.

## Checking the audit trail

Every request leaves one row, whether it was allowed, denied, or refused for a
capability mismatch.

```bash
psql "$MY_PA_DATABASE_URL" -c \
  "SELECT outcome, capability, purpose, denial_reason, scope_source_id_count \
   FROM knowledge.audit_events ORDER BY recorded_at"
```

Observed after the two requests above:

```text
allowed | capabilities.get | status_observation | (null)               | 0
denied  | sources.list     | source_inspection  | scope_not_authorized | 1
```

No path, no host, no query text, no content — the table has no column for any of
them.

## What this runbook does not cover

Authentication, TLS, ingress, reverse proxies, service supervision, deployment,
and production activation. All operator-gated (`AGENTS.md` §5), and the first
three are `P00-OD-010`, which is open. Audit retention is `P00-OD-013` and is
also open: `knowledge.audit_events` is append-only and there is deliberately no
procedure here for trimming it.
