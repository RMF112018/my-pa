# End-to-end operations

The ordered sequence for standing the local candidate up from an empty database,
walking one enrollment from registration to `knowledge.read`, and stopping both
processes cleanly.

The four other runbooks each cover one process. This one covers the order, which
is the part none of them can state alone, and it starts where an operator should
start: **ask whether the database can serve this build before doing anything
else.**

Every command below was executed against a **disposable** database
(`my_pa_end_to_end_runbook`, created empty and dropped for the purpose) on
2026-08-03, and **every transcript below is that database's output** — step 1's
`revision none` is the disposable database before step 2 migrates it, not a
reading of anything else.

**Nothing here was run against the canonical `my_pa` database, and nothing here
could be.** That is a different measurement and it is deliberately not in this
document: the probe run against canonical `my_pa` is transcribed in
[`postgres-operations.md`](postgres-operations.md), which recorded it at
`6c4d3ea82f10` against a head of `af3d35efb9c0` — exactly the condition this
sequence refuses to proceed from.

All commands run from the repository root, with one variable exported for the
whole sequence:

```sh
export MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@localhost:5433/my_pa_end_to_end_runbook'
```

There is no default (`P00-OD-008`). The URL carries no password; `~/.pgpass`
supplies it, because an embedded one fails `scram-sha-256` from the host.

## 1. Probe, before anything else

```sh
.venv/bin/python apps/cli/health.py
```

Observed against the freshly created, unmigrated database — exit `1`:

```text
state            not_at_head
server_version   17.10 (Debian 17.10-1.pgdg13+1)
extensions       plpgsql
revision         none
head             af3d35efb9c0
the configured database is not at the migration head and cannot serve this build
```

`revision none` is an empty database, and it is the same `state` an operator gets
for one several revisions behind. `not_at_head` is a statement about the **build**
and not a diagnosis of any one capability: measured, a database before
`9c6b4a18ed72`, which creates `knowledge.audit_events`, answers `internal_error`
to every capability — "the request could not be completed", which names nothing —
while `9c6b4a18ed72` itself, one revision behind head, serves `capabilities.get`
and still fails the capability that enrolls a scope (`D-61`, `D-65`, and
limitation 8 of `docs/operations/mcv-limitations.md`, which names both
boundaries). An empty database is below both, so step 2 is not optional here.

## 2. Migrate to head

```sh
.venv/bin/alembic upgrade head
```

Then probe again. Exit `0`, which is the gate for everything below:

```text
state            ready
server_version   17.10 (Debian 17.10-1.pgdg13+1)
extensions       pg_trgm, plpgsql, unaccent
revision         af3d35efb9c0
head             af3d35efb9c0
```

**Never run this against canonical `my_pa`.** `ops/runbooks/postgres-operations.md`
states why and what an unset variable does; the canonical database is
deliberately not at application head.

## 3. Register a root as a source

```sh
.venv/bin/python apps/cli/sources.py register \
    --provider fixture --root fixtures/mcv/root \
    --label "MCV fixture corpus" --classification synthetic_test
```

```text
source_id        src_d588df089f7422e5fe9df3e722607747
root_object_id   obj_6fdbc46255f01f91dec36e1adac86bb2
provider_kind    fixture
classification   synthetic_test
label            MCV fixture corpus
configured       2026-08-03T13:31:06.306861+00:00
```

The root is never echoed back. Registration is idempotent on
`(provider_kind, native_root)`. `P00-OD-009` is open, so the only root used
anywhere in this repository is the synthetic corpus at `fixtures/mcv/root`.

## 4. Start the gateway

```sh
.venv/bin/python apps/gateway.py run
```

```text
serving     http://127.0.0.1:8765/v1/<capability>
notice      sources.list, sources.metadata and sources.fetch answer 'unavailable' for every source no operator has registered; registration names the source's root by exact path, and this process configures none
```

Loopback only, with no option to bind elsewhere (`D-30`, `P00-OD-010`).

**Steps 5, 7, 8 and 9 must all reach the same running gateway.** That is not
stylistic — see "One process, one principal" below.

## 5. Enroll a bounded scope

```sh
curl -sS -X POST http://127.0.0.1:8765/v1/sources.enroll \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-e2e-1","purpose":"bounded_enrollment",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-03T13:35:00Z",
       "payload":{"source_id":"src_d588df089f7422e5fe9df3e722607747",
                  "root_object_id":"obj_6fdbc46255f01f91dec36e1adac86bb2",
                  "depth":0,"media_types":["text/markdown","text/plain"],
                  "idempotency_key":"runbook-e2e","max_items":100,"max_bytes":65536}}'
```

Observed: `created: true`, `enrollment_id enr_c0b3f774b53aaba2dde1fbd2186a7291`,
and a disclosure carrying `coverage.eligible 4`, `state queued`,
`limitations ["no_extracted_text_in_scope"]`. The four are the files under the
root, enumerated inside the enroll transaction and counted rather than estimated.

## 6. Run the worker

```sh
.venv/bin/python apps/worker.py run --max-iterations 2
```

```text
owner        worker-895d36cf540a4bef
iterations   2
claimed      1
completed    1
released     0
lost         0
idle         1
```

One claimed job is one enrollment's outstanding objects, and work commits per
object. Bounded here so the transcript terminates; step 10 stops the unbounded
form.

## 7. Observe what the worker did

```sh
curl -sS -X POST http://127.0.0.1:8765/v1/sources.status \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-e2e-2","purpose":"status_observation",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-03T13:36:00Z",
       "payload":{"enrollment_id":"enr_c0b3f774b53aaba2dde1fbd2186a7291"}}'
```

Observed: `state partially_complete`, and a disclosure of
`eligible 4, processed 2, unsupported 2, quarantined 0`, `partial_result true`,
`limitations ["scope_not_fully_extracted"]`.

The two `unsupported` are `handbook.pdf` and `opaque.bin`. **A PDF is reported
and counted, never silently skipped** — `P00-OD-003` is open and no PDF library
is a dependency here, so a counted `unsupported` outcome is the honest answer and
an absence would not be. `partially_processed` is the truthful coverage state for
a scope holding objects this extractor does not read.

## 8. Search inside the grant

```sh
curl -sS -X POST http://127.0.0.1:8765/v1/knowledge.search \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-e2e-3","purpose":"knowledge_search",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-03T13:37:00Z",
       "payload":{"enrollment_id":"enr_c0b3f774b53aaba2dde1fbd2186a7291",
                  "query":"flanges","page_size":10}}'
```

Observed: one match, `knowledge_id kn_e0662a8a7df2dbcb42505b734778ecdd`,
`rank strong`, a snippet, and `source_references` naming the `source_object_id`
and `version_id` it came from. The query is not an option of any command line
here and is not logged.

## 9. Read the record and its provenance

```sh
curl -sS -X POST http://127.0.0.1:8765/v1/knowledge.read \
  -H 'content-type: application/json' \
  -d '{"request_id":"req-e2e-4","purpose":"knowledge_read",
       "principal_id":"prn_0123456789abcdef",
       "requested_at":"2026-08-03T13:38:00Z",
       "payload":{"knowledge_id":"kn_e0662a8a7df2dbcb42505b734778ecdd",
                  "enrollment_id":"enr_c0b3f774b53aaba2dde1fbd2186a7291",
                  "max_characters":200}}'
```

Observed: the stored text truncated to 200 characters with
`is_truncated true`, `truncation.reason max_characters_reached`, and a
`provenance` block naming `extractor my_pa.text`, `extractor_version 1`,
`observed_at`, `processed_at`, `trust_level source_bound_derived`, and the same
`source_object_id` and `version_id` step 8 returned. That agreement across the
two capabilities is the end of the slice.

`enrollment_id` is required by both `knowledge.search` and `knowledge.read`: a
record written under one grant cannot be read through another, and a
`knowledge_id` naming nothing inside the stated grant answers `not_found`, the
same answer as one naming nothing at all.

## 10. Stop, in this order

Stop the **worker** first, then the gateway. The worker is the only process that
holds a lease, and stopping it first means no job is mid-flight while the
gateway is going away.

```sh
kill -TERM <worker pid>
```

```text
owner        worker-d586648587462059
iterations   1
claimed      0
completed    0
released     0
lost         0
idle         1
```

`SIGINT` and `SIGTERM` both set one stop event and restore `SIG_DFL`, so a
second signal is not swallowed; the summary is printed from a `finally`.

```sh
kill -TERM <gateway pid>
```

The gateway's shutdown is uvicorn's: it stops accepting, drains in-flight
requests up to `GRACEFUL_SHUTDOWN_SECONDS` (30, derived from the engine's
checkout timeout), and `runtime.close()` releases both connection pools in a
`finally`. A gateway stopped by `SIGTERM` exits *by* `SIGTERM` rather than `0`,
which is why the uvicorn floor is 0.31.1 and not 0.27.

Both processes were observed stopped, and no third signal was needed.

## One process, one principal — the limitation this sequence walked into

`bootstrap.gateway.local_principal()` issues a **fresh** principal identifier per
composition, and `apps/cli/invoke.py` composes a runtime per invocation. So each
`invoke.py` run acts as a principal that has never existed before and holds no
enrollment, and `authorize` reads the authorized scope from the enrollments that
principal holds (`application/authorization.py`).

Measured on this database. `sources.enroll` through `invoke.py` succeeded and
wrote its enrollment; three later `invoke.py` calls to `sources.status` for that
enrollment were each `denied`, `denial_reason scope_not_authorized`, under three
**different** principal identifiers — while the same four capabilities through
one running gateway recorded `allowed` four times under **one** identifier.

Consequences, stated rather than worked around:

- The scoped capabilities — `sources.list`, `sources.metadata`, `sources.fetch`,
  `sources.status`, `knowledge.search`, `knowledge.read` — are usable through
  `apps/cli/invoke.py` **only** for a scope enrolled by the *same* invocation,
  which no single invocation can do. Through a running gateway or a running MCP
  server they work, because that process holds one principal for its lifetime.
- `capabilities.get` is the exception and works from the CLI, because it carries
  no source scope at all (`domain/policy/decision.py`).
- This is not a defect this runbook may fix. Which identity a local principal
  has, and whether it survives a process, is an authentication question, and
  `P00-OD-010` is open and reserved to the operator (`D-30`). It is recorded in
  `docs/operations/mcv-limitations.md` and it is why steps 5 and 7 through 9 use
  one gateway.

## What this sequence does not establish

`docs/operations/mcv-limitations.md` is the list. The four that matter most for
an operator reading this page: the corpus is four synthetic objects and nothing
wider; there is no authentication mechanism and no principal beyond the local
one; recovery is proven for a killed worker and an expired lease and for nothing
else; and a database reachable but lacking `knowledge.audit_events`, which
`9c6b4a18ed72` creates, answers `internal_error` from the application to every
capability, while one revision short of head it answers `internal_error` to
`sources.enroll` alone — which is why step 1 exists and why it checks head
rather than reachability.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
