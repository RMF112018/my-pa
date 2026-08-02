# Gateway operations

Running, calling, and stopping the `my-pa` HTTP gateway.

Every command below was executed against a **disposable** database
(`my_pa_gateway_runbook_test`, created at head and dropped for the purpose) on
2026-08-02. Nothing here was run against the canonical `my_pa` database.
Pointing the gateway at it would be safe to read from and would write audit rows
for requests nobody made, which is the reason not to.

## What the gateway is, and what it does not yet do

`apps/gateway.py` serves the eight public capabilities over HTTP on loopback.
One request is one call to `ApplicationService.invoke`, and the response body is
the envelope that call produced — the transport maps and does not decide.

**It is bound to `127.0.0.1` and there is no option to bind elsewhere.** That is
`D-30` and `AGENTS.md` §5: `P00-OD-010` — which authentication mechanism this
uses — is open and reserved to the operator, so the gateway issues, reads, and
requires no credential, and configures no TLS. The address is a constant in the
source rather than a flag with a safe default.

**No source provider is configured.** The three source-reading capabilities
answer `unavailable` for every source, and the process says so at startup.
Nothing registers a source in production yet (`D-37`, WP-4B3) and no provider
root is authorized (`P00-OD-009`, which needs the operator to name one by exact
path). `capabilities.get`, `sources.status`, `sources.enroll`, `knowledge.search`
and `knowledge.read` reach the database and answer for real.

Read that as: running this gateway today is safe, answers truthfully, and has
no corpus to answer about.

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
# The default port.
.venv/bin/python apps/gateway.py run

# Somewhere else.
.venv/bin/python apps/gateway.py run --port 9000
```

Startup prints two lines and nothing more. There is no access log and no
per-request log line: the application emits no log records at all, and a
per-request line is the one place a path, a query, or a principal would reach a
file.

```text
serving     http://127.0.0.1:8791/v1/<capability>
notice      no source provider is configured; sources.list, sources.metadata and sources.fetch answer 'unavailable' until a source is registered and a root authorized
```

## Calling it

One route: `POST /v1/<capability>`, `content-type: application/json`, with a
`content-length` — a body with no declared length is refused, because a length
that arrives after the body cannot bound it.

The document carries the common request metadata and the capability's own fields
under `payload`. `principal_id` is correlation input: the acting principal is the
process's own, and a caller naming a different one does not become it.

```bash
curl -sS -X POST http://127.0.0.1:8791/v1/capabilities.get \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-1",
       "purpose":"status_observation",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-02T12:00:00Z",
       "payload":{}}'
```

Observed: `200`, `content-type: application/json`, and an envelope whose
`result.manifest` lists eight capabilities `available`, `application/pdf`
`decision_gated`, and `readiness.state: ready`. No `server` header.

A request for a scope the principal does not hold:

```bash
curl -sS -X POST http://127.0.0.1:8791/v1/sources.list \
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

Not run as written; the connection counts in this runbook were observed through
SQLAlchemy, and the client form is given because it is what an operator has to
hand.

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
