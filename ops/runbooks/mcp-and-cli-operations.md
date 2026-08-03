# MCP and CLI operations

Running and calling the two transports that are not HTTP: the Model Context
Protocol server on stdio, and the operator CLI.

Every command below was executed against a **disposable** database
(`my_pa_wp4b2b_runbook_test`, created at head and dropped for the purpose) on
2026-08-02. Nothing here was run against the canonical `my_pa` database.
Pointing either transport at it would be safe to read from and would write audit
rows for requests nobody made, which is the reason not to.

[`gateway-operations.md`](gateway-operations.md) covers the HTTP transport, the
error-code-to-status table, and the connection pools. Everything it says about
configuration, the audit trail, and what is *not* covered applies here too: the
three transports are one composition, and the differences are protocol only.

## What is the same, and why that matters

All three transports call one function — `adapters/normalization.normalize` —
and none of them can build a request value of its own. A request that HTTP
refuses, MCP and the CLI refuse, with the same code, the same message, the same
`safe_details`, and the same audit event. That is `SPEC-AC-001`, and
`tests/contract/test_transport_parity.py` holds it over all eight capabilities.

Practically: **there is no capability reachable from a shell that is not
reachable over HTTP, and no authority that comes with being local.** The CLI is
handed the same principal the gateway is handed, by the same composition root,
and has no option that could change it.

## Configuration

The same single required variable as the gateway, and no default:

```text
MY_PA_DATABASE_URL=postgresql+psycopg://my_pa@localhost:5433/<database>
```

Supply the password out of band with `PGPASSWORD` or `~/.pgpass`. Neither
transport adds configuration of its own, opens a socket, reads a credential, or
configures TLS (`D-30`; `P00-OD-010` is open and reserved to the operator).

---

# The MCP server

## Running it

```bash
.venv/bin/python apps/gateway.py mcp
```

**Stdio only** (`D-26`, `D-30`). The server speaks JSON-RPC on standard input
and standard output and binds nothing. There is no `--host`, no `--port`, and no
transport flag; the SDK's HTTP and SSE transports are never imported.

It is not usually run by hand. An MCP client launches it as a child process and
owns both pipes. The equivalent client configuration is a command and its
arguments:

```json
{
  "command": ".venv/bin/python",
  "args": ["apps/gateway.py", "mcp"],
  "env": { "MY_PA_DATABASE_URL": "postgresql+psycopg://my_pa@localhost:5433/my_pa" }
}
```

**Startup output goes to standard error, and that is load-bearing.** Standard
output is the wire; a single line printed there is a parse failure on the
client's first read, before `initialize` has been answered.

```text
serving     mcp on stdio as my-pa
notice      sources.list, sources.metadata and sources.fetch answer 'unavailable' for every source no operator has registered; registration names the source's root by exact path, and this process configures none
```

## The handshake

Observed, in reply to an `initialize` naming protocol version `2025-06-18`:

```json
{"capabilities": {"experimental": {}, "tools": {"listChanged": false}},
 "protocolVersion": "2025-06-18",
 "serverInfo": {"name": "my-pa", "version": "0.1.0"}}
```

Only `tools` is declared. There are no resources, no prompts, no sampling, and
no completion — those handlers are not registered, so a client asking for one
gets a method-not-found from the SDK rather than an empty list from us.

## The tool list

`tools/list` returns eight tools whose names are the eight capability names.
Observed:

```text
capabilities.get  sources.list  sources.metadata  sources.fetch
sources.status    sources.enroll  knowledge.search  knowledge.read
```

The list is **derived** rather than maintained: the names come from the
capability enum, each tool's description is its command's own documented
summary, and each tool's input schema is built from `RequestMetadata` plus the
fields of the command that capability builds. Nothing about a capability is
written down in the adapter — a ninth capability appears as a ninth tool with
the correct schema and nobody edits a list.

Observed description for `sources.list`:

```text
`sources.list`: the immediate children of one container.
```

The schema is the document the transport actually reads: the common request
metadata at the top level and the capability's own fields under `payload`.
`capability` is deliberately absent — the tool name carries it, and a document
that names it again is refused.

## Calling a tool

Arguments are the same document the HTTP body carries. Observed for
`capabilities.get` with a valid envelope:

```text
isError: false
one text content block: the response envelope's canonical JSON
result.manifest.capabilities: 8, readiness.state: ready
```

`isError` is a function of the envelope's own `error` field and of nothing else,
so a refusal is a tool result rather than a protocol error, and the content
block is the same bytes HTTP would have written as its body.

A request for a scope the principal does not hold:

```text
isError: true
{"...","error":{"code":"denied","message":"the request is not permitted for this
 principal, purpose, and scope","retry":"after_authority_change",
 "safe_details":[]},"result":null}
```

No denial reason in the body — it is in the audit trail, where an operator can
read it and a caller cannot.

A tool that does not exist (`sources.destroy`):

```text
isError: true
{"code":"invalid_request","correlation_id":"corr_…","message":"the request is
 malformed, incomplete, or contradictory","retry":"after_correction",
 "safe_details":[]}
```

That shape — a problem detail with no envelope around it — is what a request the
application never saw answers with, exactly as it is over HTTP. An envelope
requires the caller's `request_id`, and a request that could not be read has
none to carry.

Arguments larger than the transport ceiling are refused the same way, and the
oversized value is not echoed. The ceiling is the HTTP transport's own constant,
imported rather than restated, so all three transports enforce one number.

## Stopping it

Close the client's end of standard input, or signal the process. Either ends the
connection and the process exits `0`. Observed: `exit 0` after the client closed
`stdin` following three tool calls.

There is no graceful-shutdown timeout to configure, and nothing to drain: this
process is the client's child rather than a listening server, and a request
still running when the pipe closes finishes on its worker thread before the
interpreter exits. What a client should *not* do is send a request and
immediately close the pipe — observed, that call is answered
`{"code":-32000,"message":"Connection closed"}` by the client library, because
the connection ended before the reply could be written. The work itself still
completed and its audit row was still written.

---

# The operator CLI

## Running it

```bash
.venv/bin/python apps/cli/invoke.py <capability> [options]
```

One capability per invocation. The envelope is options; the capability's own
fields are one JSON object:

```bash
.venv/bin/python apps/cli/invoke.py capabilities.get \
  --request-id req-1 \
  --purpose status_observation \
  --principal-id prn_0123456789abcdef \
  --requested-at 2026-08-02T12:00:00Z
```

Observed: exit `0`, and one line of canonical JSON on standard output — the
response envelope, whose `result.manifest` lists eight capabilities `available`,
`application/pdf` `decision_gated`, and `readiness.state: ready`. Standard error
was empty.

The full option set is `--request-id`, `--purpose`, `--principal-id`,
`--requested-at`, `--contract-version`, `--scope-source-id` and
`--scope-enrollment-id` (both repeatable), and `--payload`. That is every field
`RequestMetadata` declares except `capability`, which is the positional
argument. There is no option HTTP has and the CLI does not, and no option that
touches authority.

`--principal-id` is correlation input, not identity. The acting principal is the
process's own, and naming a different one does not become it.

```bash
.venv/bin/python apps/cli/invoke.py sources.list \
  --request-id req-2 --purpose source_inspection \
  --principal-id prn_0123456789abcdef --requested-at 2026-08-02T12:00:00Z \
  --payload '{"source_id":"src_0123456789abcdef"}'
```

Observed: exit `1`, and `error.code: denied` — the same answer the same request
gets over HTTP and MCP.

## Exit status and streams

Exit `0` when the envelope carries a result, `1` when it carries an error. There
is no status per error code: the code is in the envelope, which is where a
caller can read it, rather than encoded into eight bits a shell will mangle.

**Standard output carries the answer. Standard error stays empty.** Both halves
are deliberate. A caller redirecting one stream is not silently discarding the
other, and "this transport disclosed nothing" is a claim about one stream.

## What a bad command line does

`argparse`'s own error reporting is replaced. Its default prints a usage message
naming the value it rejected — which would put a `--payload` carrying a search
query onto a terminal and into a shell history — so every parse failure becomes
the same typed refusal instead. Observed:

```bash
.venv/bin/python apps/cli/invoke.py capabilities.get --secret hunter2
```

```text
exit 1
{"code":"invalid_request","correlation_id":"corr_…","message":"the request is
 malformed, incomplete, or contradictory","retry":"after_correction",
 "safe_details":[]}
```

The rejected value does not appear. The same is true of an unknown capability
(`sources.destroy`), a `--payload` that is not JSON, a `--payload` that is not
an object, an extra positional argument, and an option given without a value —
all observed as the identical document above with exit `1`.

`--help` still works and prints option names, never values.

## It is beside the other two, not instead of them

`apps/cli/` holds three operator programs and they share nothing but the
directory:

| Program | Plane |
| --- | --- |
| [`apps/cli/migration.py`](/apps/cli/migration.py) | the legacy-SQLite to PostgreSQL migration control plane — runs, phases, loads, resume |
| [`apps/cli/sources.py`](/apps/cli/sources.py) | source configuration — register a root, observe it, list what is configured |
| [`apps/cli/invoke.py`](/apps/cli/invoke.py) | one public capability, one response envelope |

They have no option in common except `--help`, which
`tests/contract/test_cli_transport.py` holds across all three. A migration phase
is not a capability, registering a source is not a capability, and merging any
two of them would have made one look like another —
`tests/architecture/test_operator_commands_are_not_capabilities.py` decides that
for `sources.py` mechanically rather than by this sentence.

---

## Checking the audit trail

Every request over either transport leaves one row, the same row the gateway
writes. Observed after the calls above — three over MCP, two over the CLI:

```text
allowed | capabilities.get | status_observation | (null)               | 0
denied  | sources.list     | source_inspection  | scope_not_authorized | 1
allowed | capabilities.get | status_observation | (null)               | 0
allowed | capabilities.get | status_observation | (null)               | 0
denied  | sources.list     | source_inspection  | scope_not_authorized | 1
```

There is no column recording which transport carried the request, and that is
correct: authority does not depend on the protocol, so an audit trail that
distinguished them would be recording something that is not part of the
decision. What identifies a run is the principal identifier, which is issued per
process.

## What this runbook does not cover

Authentication, TLS, ingress, exposing either transport beyond the local
machine, service supervision, deployment, and production activation. All
operator-gated (`AGENTS.md` §5); the first three are `P00-OD-010`, which is
open. Nothing here issues, reads, or requires a credential.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
