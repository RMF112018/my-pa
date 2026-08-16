# MCP and CLI operations

Running and calling the two transports that are not HTTP: the Model Context
Protocol server on stdio, and the operator CLI.

Every command below was executed against a **disposable** database
(`my_pa_wp4b2b_runbook_test`, created at head and dropped for the purpose) on
2026-08-02, **except where a transcript is marked otherwise** — three blocks
(`tools/list`, `tools/call capabilities.get`, and `invoke.py capabilities.get`)
were re-executed 2026-08-03 against a disposable database at head
`1a4c9e77b2d5`, and a fourth marker on the `initialize` handshake records that
that block was **left as recorded and not re-run**. Six blocks are carried
unchanged from the 2026-08-02 run. *Scope clause added 2026-08-03: this sentence
was an unqualified universal over a document holding transcripts from two runs at
two heads — the widest instance of that defect in this directory, and the one
nobody had named.*

Nothing here was run against the canonical `my_pa` database. **Measured, and this
is the real reason rather than the polite one:** canonical `my_pa` is at
`6c4d3ea82f10` while the chain ends at `1a4c9e77b2d5`, so it holds no `knowledge`
schema at all and neither transport could serve a request against it — the
composition fails its readiness check rather than reading anything. Even if it
could, it would write audit rows for requests nobody made. *Corrected 2026-08-03:
this said only that pointing a transport at canonical `my_pa` "would be safe to
read from and would write audit rows for requests nobody made".
[`gateway-operations.md`](gateway-operations.md) announced that exact correction
for its own copy of the sentence and the sibling was left uncorrected — an
incomplete class sweep inside a package whose subject is class sweeps.*

[`gateway-operations.md`](gateway-operations.md) covers the HTTP transport, the
error-code-to-status table, and the connection pools. Everything it says about
configuration, the audit trail, and what is *not* covered applies here too: the
three transports are one composition, and the differences are protocol only.

## Withdrawing the MCP surface (WP-28)

Two independent switches, both read once at startup and neither consulted per
request.

`MY_PA_MCP_SURFACE_DISABLED` is the kill switch. It is **off by default and the
surface serves**, which is the opposite default from the remote capture ingress
and is deliberate: this surface is a pipe an operator starts with
`apps/gateway.py mcp`, on stdio, with no socket and no credential, so serving is
already an act rather than an accident. The switch exists to *withdraw* the
surface from a client already using it. Engaged, `tools/list` publishes nothing
**and** `tools/call` is refused before the application is reached — a switch that
only hid the tools would leave every name a client already knows reachable. A
value that is not a boolean spelling refuses to start rather than being read as
`false`.

```
MY_PA_MCP_SURFACE_DISABLED=true apps/gateway.py mcp   # publishes nothing, refuses every call
```

`MY_PA_MCP_CLIENT_ID` binds the surface to a row in the existing capture-client
registry. Empty means no client is bound, which is the default. When it is set,
the process refuses to serve if that client is absent, belongs to another
Principal, or has been **revoked** — so `apps/cli/clients.py revoke` withdraws
this surface at the next start, with no second registry and nothing else to
remember.

**This is identification, not authentication.** stdio carries no credential, so
the process presents no secret and verifies none. Authenticating an external MCP
client needs an ingress that does not exist in this build (`EXT-07`/`EXT-08`,
operator-gated). There is no OAuth authorization server, no PKCE, no resource
indicators and no per-client profile conformance testing; see
`docs/operations/mcv-limitations.md` §13a.

**Restart is required for either switch to take effect.** Both are composed once
in `bootstrap.gateway`, and an already-running process keeps whatever it was
started with. To withdraw a surface immediately, stop the process.

## What is the same, and why that matters

All three transports call one function — `adapters/normalization.normalize` —
and none of them can build a request value of its own. A request that HTTP
refuses, MCP and the CLI refuse, with the same code, the same message, the same
`safe_details`, and the same audit event. That is `SPEC-AC-001`, and
`tests/contract/test_transport_parity.py` holds it over all forty-five capabilities.

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

The NAS-08 placement preserves that lifecycle. Its example client config
launches the opt-in `frontier-mcp` container with `docker compose run --rm
--no-deps -T`; the container command remains exactly `python apps/gateway.py
mcp`. It has stdin, no TTY, no published or exposed port, and no reverse-proxy,
browser, or OAuth route. The example neither activates an external client nor
overrides the existing MCP kill switch.

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

**Re-executed 2026-08-03 and left as recorded, with one difference named.** The
`serverInfo` and the declared capability set came back identical. The
`protocolVersion` did **not**: the installed SDK's client now names
`2025-11-25` in its `initialize`, and the server answered with that. This
transcript is a reply to an `initialize` naming `2025-06-18` and stays as it
was, because rewriting it would record a *different* request's answer under the
old request's heading. What is unchanged is the part this section is about —
one declared capability, `tools`, and nothing else.

## The tool list

`tools/list` returns the tools **this process can serve**, and that is not the
same as the tools this build implements. The build implements forty-five, one per
capability name. A default process publishes **twenty**.

**The six `documents.` tools appear only when `MY_PA_MANAGED_DOCUMENT_ROOT` is
configured**, and nothing else gates them. There is no default location and no
inference: with the variable unset the composition root builds no managed byte
store, `capabilities.get` omits those names, `tools/list` omits those tools, and
a `tools/call` naming one is refused `unsupported`. Set the variable and the
same child publishes all forty-five. An operator who expects `documents.create`
on the list and does not find it should look at that variable first — it is the
only thing that decides it. (Pointing the plane at real storage is `EXT-10` and
remains operator-gated; `docs/operations/mcv-limitations.md` section 13 states
the same gating and the plane's limits.)

Measured at this head against a real child process — `.venv/bin/python
apps/gateway.py mcp` — by
`tests/contract/test_mcp_transport.py::test_a_real_child_process_publishes_only_what_it_was_composed_with`
(unset: twenty, none beginning `documents.`) and
`::test_a_child_with_a_managed_root_publishes_every_capability` (set:
forty-five).

**Re-executed 2026-08-03** — a real `stdio_client` spawning
`.venv/bin/python apps/gateway.py mcp` as a child process, against a disposable
database at head `1a4c9e77b2d5`. It said "eight tools" until this run, and the
four that arrived are the reason the paragraph below is worth having. Observed,
in the order the adapter emits them:

```text
capabilities.get  sources.list      sources.metadata  sources.fetch
sources.status    sources.enroll    knowledge.search  knowledge.read
capture.create    capture.revise    capture.read      capture.list
```

The list is **derived** rather than maintained: the names come from the
capability enum, each tool's description is its command's own documented
summary, and each tool's input schema is built from `RequestMetadata` plus the
fields of the command that capability builds. Nothing about a capability is
written down in the adapter — a new capability appears as a new tool with
the correct schema and nobody edits a list. **That claim is now measured rather
than asserted**: WP-6 added four capabilities and this list grew by four with no
change to `adapters/mcp`, which is what the re-execution above shows.

Observed description for `sources.list`:

```text
`sources.list`: the immediate children of one container.
```

The schema is the document the transport actually reads: the common request
metadata at the top level and the capability's own fields under `payload`.
`capability` is deliberately absent — the tool name carries it, and a document
that names it again is refused.

## Calling a tool

**Current-state correction (2026-08-12):** the tool list is derived from all
**forty-five** current capabilities, and the schema has **forty-eight** revisions
at head `d4a8c1e7b930`. `capabilities.get` also reports content-free
`worker_planes`. The dated transcript below remains historical evidence for its
stated head.

Arguments are the same document the HTTP body carries. Observed for
`capabilities.get` with a valid envelope:

```text
isError: false
one text content block: the response envelope's canonical JSON
result.manifest.capabilities: 12, every one available, readiness.state: ready
```

Re-executed 2026-08-03 in the same session as the tool list above. It recorded
`8` until then.

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

## GoodNotes operator plane

The production-reachable GoodNotes command is `apps/cli/goodnotes.py`. Set
`MY_PA_GOODNOTES_ROOT` to the exact already-admitted source root and
`MY_PA_GOODNOTES_OCR_ROOT` to the separately admitted executable root, and
`MY_PA_GOODNOTES_OCR_EXECUTABLE` to an absolute executable inside it. Optional OCR
arguments are a JSON string list in `MY_PA_GOODNOTES_OCR_ARGUMENTS_JSON`; no
shell is used. In `local_operator` mode the command derives and pins the durable
local Principal. In `entra` mode it requires `--principal-id` as the explicit
owning partition; that identifier selects no authentication authority and the
repository/persistence boundaries still enforce the partition.

Run `reconcile --idempotency-key KEY`. Then use the ordinary authenticated
`review.list`, `review.decide`, and `knowledge.search` capabilities through
`apps/cli/invoke.py`; GoodNotes has no parallel review or search command. Reconcile
first fingerprints the manifest and closes its receipt check, then streams pages
through the aggregate-bounded OCR/model stage, then opens the durable transaction.
Never point it at an unverified root or a live personal source outside the
separately authorized pilot activation.

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

**Re-executed 2026-08-03** against a disposable database at head
`1a4c9e77b2d5`. Observed: exit `0`, and one line of canonical JSON on standard
output — the response envelope, whose `result.manifest` lists **twelve**
capabilities `available`, `application/pdf` `decision_gated`, and
`readiness.state: ready`. Standard error was empty, measured at zero bytes. It
read "eight capabilities" until this run.

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

`context.prepare` / `context.feedback` ChatLLM operating contract, recommended
grants, activation, and rollback are
[`managed-knowledge-context.md`](managed-knowledge-context.md). Production is
not activated. Live Abacus OAuth remains operator-gated.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
