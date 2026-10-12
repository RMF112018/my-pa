# Remote MCP interaction log

The remote MCP gateway (`apps/gateway.py mcp-remote`) can record every HTTP
exchange on its `/mcp` route, request and response bodies included, in the
PostgreSQL table `observability.mcp_interactions`. It exists so the operator
can see exactly what a remote client sent and what the server answered when a
tool call misbehaves. It is **off by default**. This runbook covers what the
log stores, the operator risk acceptance it depends on, how to switch it on,
how to read it, and how to keep it to 14 days.

**Status: the production procedures here are UNEXECUTED.** No command in
this runbook has been run against the NAS or production: enabling the log,
applying the migration there, granting the role and scheduling the purge are
operator acts (`AGENTS.md` §5 and §8.2) that this change does not perform. What
has been executed is the CLI itself — `list`, `show`, `search` and `purge`,
including dry-run, batch draining and the 14-day boundary — against a
disposable PostgreSQL 15 database, by
`tests/database/test_mcp_interactions_cli.py`.

## Scope

- **Captured:** every exchange on `/mcp` (POST, GET, DELETE), one row each.
  That includes the endpoint's own refusals: `401 invalid_token`,
  `403 insufficient_scope` and `503 temporarily_unavailable`.
- **Not captured:** the OAuth routes (`/authorize`, `/token`, `/register`,
  revocation and the rest), health, readiness and protected-resource metadata.
  Those routes carry credentials and are not JSON-RPC, so the capture
  middleware passes them through untouched.
- **Not captured either:** the local stdio MCP server, the HTTP gateway
  (`apps/gateway.py run`) and the operator CLI. The log covers the remote
  process only.

## Operator risk acceptance (2026-10-11)

`AGENTS.md` §5 says logs must exclude message bodies "by default". This log is
an **explicit exception to that default, accepted by the operator on
2026-10-11** under `AGENTS.md` §8.2, which reserves the "acceptance of material
… privacy … risk" to the operator. The accepted terms:

1. full request and response bodies of remote `/mcp` exchanges are stored, after
   the redaction below;
2. access is operator-only: the log is read through
   `apps/cli/mcp_interactions.py` in a local-operator process, and there is no
   capability, MCP tool, HTTP route or remote read path for it;
3. rows are kept for 14 days and then purged.

The default stays `false` because §5's default still governs every
deployment that has not made this choice. Switching it on is how the choice is
made, and the gateway prints a `notice` line on standard error at start-up
whenever it is on.

## What one row holds

| Column | Holds |
| --- | --- |
| `interaction_id` | `mcpi_` + 32 lowercase hex |
| `recorded_at` | set by the database trigger at insert; callers cannot backdate it, and retention is keyed on it |
| `started_at`, `latency_ms` | request arrival (application clock), and the time from arrival to the last response byte |
| `http_method`, `http_status` | the HTTP exchange; `http_status` is null if no response was started |
| `oauth_client_id`, `principal_id`, `principal_kind` | the authenticated context; null for `invalid_token` / `insufficient_scope`, which are refused before authentication completes |
| `mcp_session_id` | the `mcp-session-id` header, null in stateless mode |
| `jsonrpc_method`, `jsonrpc_id` | e.g. `tools/call`; `batch` for an array |
| `tool_name`, `capability` | the `tools/call` tool, and the canonical capability (the façade's `arguments.capability`, else the tool name) |
| `correlation_id` | the ProblemDetail correlation id in the response, when present |
| `outcome` | one of `ok`, `tool_error`, `jsonrpc_error`, `http_error`, `auth_refused`, `unavailable`, `unparsed` |
| `error_code` | ProblemDetail code, JSON-RPC error code, or endpoint error token |
| `request_bytes`, `response_bytes` | the **full raw wire size** of each body |
| `request_sha256`, `response_sha256` | see [Digests](#digests) |
| `request_truncated`, `response_truncated` | true when the stored body is a prefix |
| `request_body`, `response_body` | the redacted body as JSONB, when it is JSON and fits the cap |
| `request_body_text`, `response_body_text` | the redacted UTF-8 prefix, when the body was truncated or is not JSON |
| `request_headers` | allowlisted request headers only |
| `diagnostics` | `is_error`, `problem`, `jsonrpc_error`, `endpoint_error`, and `capture` (parse results, digest scopes, redaction count, NUL flag, and the drop/failure counters) |

At most one of `*_body` and `*_body_text` is set per side; a truncated side
never has `*_body`.

## Redaction

Redaction happens on the gateway's writer thread **before** truncation, so a
credential past the cap never appears and one straddling it is never stored in
part. The rules, as `src/my_pa/adapters/mcp_interaction_capture.py` implements
them:

- **Headers are allowlisted.** Only `content-type`, `accept`, `user-agent`,
  `mcp-protocol-version`, `origin` and `content-length` are stored.
  `authorization`, `cookie`, `set-cookie`, `proxy-authorization` and every
  other header are never read into a row.
- **JSON keys.** Keys are normalised — lower-cased, with `-`, `_` and spaces
  removed, so `access_token`, `Access-Token` and `accessToken` are one key. A
  key is a credential key when its normalised form is one of `authorization`,
  `proxyauthorization`, `cookie`, `setcookie`, `accesstoken`, `refreshtoken`,
  `idtoken`, `token`, `bearer`, `clientsecret`, `secret`, `password`,
  `passphrase`, `apikey`, `privatekey`, `signingkey`, `codeverifier`,
  `assertion`, `clientassertion`, `sessiontoken`, `credential`, `credentials`,
  `secretkey`, `accesskey`, `authorizationcode`, `secrets`, `pwd` or `passwd`,
  **or ends with** `token`, `secret`, `secrets`, `password`, `passwd`,
  `passphrase`, `apikey`, `accesskey`, `secretkey`, `privatekey`,
  `signingkey`, `credential`, `credentials` or `cookie` (so `auth_token`,
  `oauth_token`, `github_token`, `x_api_key`, `db_password`,
  `aws_secret_access_key`, `aws_access_key`, `lease_token` and MCP's
  `progressToken` are redacted). Its value is replaced by `"[REDACTED]"`,
  whatever the value's type. `tokens`, `max_tokens`, `token_count`, the bare
  key `code` and every domain `*_code` field do not match and are kept.
- **Keys are text too.** Every key that is not itself a credential key goes
  through the string rules below, so a URL with userinfo, a `Bearer` token or a
  JWT used as an object key is redacted like any other string — at the top
  level and inside embedded documents alike. If redaction makes two keys of
  one object equal (`"Bearer A"` and `"Bearer B"` both become
  `"Bearer [REDACTED]"`), the later one gets the next free ` #2`, ` #3`, …
  suffix, so no value is silently merged away.
- **Metadata columns** (`jsonrpc_id`, `jsonrpc_method`, `tool_name`,
  `capability`, `oauth_client_id`, `principal_id`, `mcp_session_id`) and stored
  header values are redacted **whole** by the string rules, **then** cut to 256
  characters, so a credential straddling the cut is never stored in part.
- **JSON numbers PostgreSQL cannot store.** `NaN`, `Infinity`, `-Infinity`
  and numbers that overflow to infinity (`1e999`) are parsed and stored as the
  strings they were written as (`"NaN"`, `"1e999"`), and
  `diagnostics.capture.non_finite_replaced` is `true`. Without this JSONB
  would refuse the row and the exchange would go unlogged.
- **Every string**, in this order:
  - a PEM or PGP private-key block (a `-----BEGIN` line naming a `PRIVATE KEY`
    or `PRIVATE KEY BLOCK`) becomes `[REDACTED]` up to and including its
    matching `END` line; if the next `-----` is anything else (a near-miss
    `END`, another armour line) or the text ends first, everything up to that
    point is redacted and the near-miss line is kept;
  - `"key": value` pairs for the keys above become `"key": "[REDACTED]"`,
    where value is a string or a non-string scalar (number,
    `true`/`false`/`null`). As text, a key matches with `-`, `_`, `.` or a space
    between its words (so `oauth.token` and `a.b.client_secret` match), in any
    case, and the suffix rule allows up to 64 characters before the suffix;
  - the same pairs inside an escaped JSON string, at the four escaping levels
    the JSON path follows — one, three, seven or fifteen backslashes before
    each quote (each embedding doubles the backslashes and adds one). The value
    runs to the first quote with that many backslashes or fewer, so a deeper
    level's escaped quote inside the value is redacted with it; a quote run of
    more than fifteen backslashes is not treated as a pair;
  - `'key': value` pairs as a Python repr prints them (`True`/`False`/`None`
    as scalars);
  - a credential value **cut off by the end of the text** (`"refresh_token":"ABC`
    with no closing quote, plain or at any of the four escaping levels) is
    redacted to the end;
  - `key=value` in a query string or form body (`client_secret=…&code_verifier=…`)
    becomes `key=[REDACTED]`, the value running to `&`, whitespace, a quote or a
    backslash; the key must start a word and contain no spaces;
  - the password in URL userinfo: `scheme://user:password@host` becomes
    `scheme://user:[REDACTED]@host` (scheme up to 32 characters, user and
    password up to 256 each);
  - a credential header line — `Cookie:`, `Set-Cookie:`, `Authorization:` or
    `Proxy-Authorization:` with any scheme (`Bearer`, `Basic`, `Token`,
    `Digest`, …), `X-Api-Key:` / `Api-Key:`, and any `*-Token:` or `*-Secret:`
    header — keeps its name and loses its value (`Authorization: [REDACTED]`, up
    to the end of the line, a quote or a backslash);
  - a colon-style credential line, as YAML, `.env`-style dumps and logs write
    it: at the start of a line (after at most 64 spaces or tabs), a credential
    key in its one-word form (`password`, `api_key`, `client_secret`,
    `x_api_key`, `DB_PASSWORD`, …), up to 16 spaces or tabs on each side of the
    colon, then the value to the end of the line, which becomes `[REDACTED]`.
    `password_hint:` and a `password:` in the middle of a line are not matched;
  - `Bearer <token>` becomes `Bearer [REDACTED]` (any case);
  - `Basic <base64>` becomes `Basic [REDACTED]`. Only the word `basic` is
    case-insensitive; the run must be eight or more base64 characters and
    contain a digit, an **upper-case** letter, `+`, `/` or `=`, so prose such as
    "basic information about the project" is kept;
  - a JWT: in any dotted base64url run (`x.y.z…`), everything from the first
    `eyJ` onward is replaced by `[REDACTED]` when at least two dots follow it,
    so a token glued to preceding text is still caught.
- **JSON inside strings.** A string that is itself a JSON object or array (MCP
  `TextContent.text` carries the response envelope that way) is parsed,
  redacted by the same rules, and re-serialised, up to four levels deep.
- **Text that is not JSON** (or a body that overflowed the capture buffer, or
  was never read whole) is redacted by the string rules above, applied to the
  whole text.
- **NUL characters**, which PostgreSQL text and JSONB cannot hold, and
  unencodable surrogates are replaced with U+FFFD and flagged in
  `diagnostics.capture.nul_replaced`.
- `diagnostics.capture.redactions` counts the replacements made.

**Every pattern is linear by construction.** The writer thread runs them over
bodies an untrusted client chooses, so each is built so that no start can
rescan text a later start will scan: scans start only at the first character
of a run, every prefix and escape run is bounded, and every body or value scan
stops at the first terminator of its kind. A unit test probes **every compiled
pattern** with worst-case shapes (many start tokens, filler, a near-miss
terminator at the end, and start tokens of decreasing length). It measures
thread CPU time, so a busy host cannot skew it, and compares one 512 K-character
run with sixteen 32 K runs of the same shape: linear costs the same either way,
quadratic about 16 times more, and the limit is 4. Each pattern is also run
against every other pattern's shapes (8 K / 128 K), at 1 MiB under a 10-second
CPU backstop, and each probe runs in a subprocess killed after 60 seconds, so a
quadratic regression fails within a minute. Measured on the development
machine, the slowest pattern on its worst shape takes about 0.1 s at 1 MiB, and
the slowest whole-family run through all rules (`redact_text`) about 0.6 s.

**Stated limits.** Redaction is pattern-based; treat the log as sensitive
regardless.

- A credential under an unlisted key that is not otherwise credential-shaped
  is stored.
- On the **text** path (non-JSON, truncated or overflowed bodies) a credential
  key whose value is an array or an object (`"apiKey": ["…"]`, `"secret":
  {…}`) is not redacted: matching nested values linearly is not possible with
  these patterns, and none is attempted. On the JSON path such values are
  redacted whole.
- On the text path a key is matched only as written without escapes: a key
  that itself contains an escaped quote or backslash (`"pass\"word"`), or a
  pair escaped at a level other than one, three, seven or fifteen backslashes,
  is not recognised as a credential pair (the Bearer, Basic, JWT, userinfo and header rules still apply
  to its value).
- `progressToken`, `lease_token` and `idempotency_token` are redacted although
  they are not secrets (over-redaction is the safe direction).

## Digests

`request_sha256` / `response_sha256` are the SHA-256 of the **redacted,
untruncated** body as the capture module serialises it: the compact redacted
JSON (`ensure_ascii=False`, `(",", ":")` separators) for a JSON body, the
redacted UTF-8 text otherwise, the empty string for an empty body. They are
**never** a digest of the raw wire body, so a stored digest cannot be used to
confirm a guess at a credential the redaction removed. They identify and
deduplicate what was stored; they are not a wire-integrity check.

`diagnostics.capture.request_hash_scope` / `response_hash_scope` say what the
digest covers: `redacted_full` normally, `redacted_prefix` when the body was not
fully captured (larger than the 16 MiB per-body capture buffer, or never read
by the app — e.g. a request refused before its body was read). The byte counts
remain the full wire sizes in both cases.

## Body cap

Each stored body is capped at **256 KiB (262 144 bytes)** of its redacted
serialisation. A body over the cap is stored as a UTF-8-safe prefix in
`*_body_text` with `*_truncated = true`. Bodies past the 16 MiB capture buffer
are counted in full but only the buffered prefix is redacted, hashed and
stored.

## Failure isolation

- The middleware only tees the ASGI messages; it never changes them, and every
  capture step is wrapped so an exception in it is counted and the request
  proceeds as it would without the log.
- An exchange is queued **after** its last response byte is sent, into a queue
  bounded twice: at most **1024** exchanges, and at most **64 MiB** of body
  bytes held by all queued exchanges together. An exchange that would exceed
  either bound is dropped and counted (`dropped`); the request never waits.
  Each body buffers at most 16 MiB, so the queue's memory bound is 64 MiB
  rather than 1024 x 2 x 16 MiB. The tee keeps references to the chunks the
  server sends and joins each body once on the event loop after the response
  is sent: a single-chunk body (the usual case) is not copied, a multi-chunk
  body is copied once (at most 16 MiB per direction). The budget is released
  as the writer takes each exchange.
- The writer engine has no connect timeout of its own (`create_database_engine`
  takes none), so an unreachable host that does not refuse the connection
  holds only the writer thread for the operating system's connect timeout;
  meanwhile the queue fills and further exchanges are dropped and counted.
- Parsing, redaction, hashing and the insert run on one daemon writer thread,
  on a dedicated engine with a 2-second statement timeout, separate from the
  pools that serve requests.
- **If the database is unavailable or slow**, the insert fails, the row is
  dropped and counted, and nothing is retried. Requests are unaffected. The
  first write failure prints one count-only line on the container's standard
  error, and further failures print at most one more line per 60 seconds (an
  outage is not a line per request), for example
  `mcp-interaction-log write_failed dropped=0 write_failures=1 capture_errors=0`
  — never a body, header or identifier. The full count rides on the next
  written row.
- The counts since the last successful write ride on the **next row that is
  written**, as `diagnostics.capture.dropped_before` and
  `write_failures_before`. A gap in the log therefore shows up on the row after
  it.
- **Drops are reported when they happen**, not only on the next row: the first
  drop prints one count-only line on standard error, and further drops print
  at most one more line per 60 seconds, for example
  `mcp-interaction-log dropped dropped=17 write_failures=0 capture_errors=0`.
  The line is printed outside the recorder's lock and never carries a body,
  header or identifier.
- On shutdown the writer gets up to 2 seconds to flush; anything still queued
  is counted as dropped (`abandoned=<n>` on standard error).

## Enable it in production

Prerequisites, each a separate operator act:

1. The database is at revision `c8f7ae406d47` (see [Migration](#migration)).
2. The database role in the remote env file's `MY_PA_DATABASE_URL` can use the
   `observability` schema and `INSERT`, `SELECT` and `DELETE` on
   `observability.mcp_interactions`. The migration grants nothing; roles are
   provisioned outside Alembic. If the remote role owns the schema this holds
   already. Without it every write is a counted failure and the log stays
   empty.

Then:

1. In the owner-only remote env file (the file named by
   `MY_PA_REMOTE_ENV_FILE`; template `ops/nas/remote/remote.env.example`), set

   ```text
   MY_PA_MCP_INTERACTION_LOG_ENABLED=true
   ```

2. Recreate the remote MCP container so it reads the file, using the Compose
   invocation in [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md)
   ("Deploy, verify, and connect") with your own env-file paths:

   ```bash
   docker compose --env-file <remote-compose-env> \
     -f ops/nas/remote/compose.yml --profile remote-mcp \
     up -d --no-build --force-recreate my-pa-mcp-remote
   ```

3. Confirm the start-up `notice` line in the container's log
   (`docker logs <remote-mcp-container>`), make one client call, and confirm a
   row with `list` below.

To switch it off, set the variable to `false` (or remove it) and recreate the
container the same way. Switching off stops new rows; it does not delete the
existing ones, which age out through the purge.

## Read it

The CLI runs in a local-operator process — in production, inside the remote
MCP container, whose env file sets `MY_PA_AUTH_MODE=local_operator` and the
database URL. In any other auth mode it prints a `refused` line and exits 1
before connecting. The database URL is never an argument and never printed.

```bash
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py list --limit 20
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py \
  search --client <oauth-client-id> --outcome tool_error --last 2h
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py \
  search --capability tasks.list --since 2026-10-11T00:00:00Z --until 2026-10-12T00:00:00Z
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py \
  search --correlation-id <correlation-id>
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py show <interaction-id>
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py show <interaction-id> --json
```

- `list [--limit N]` — the newest exchanges, newest first, one summary line
  each (`recorded_at`, id, client, HTTP and JSON-RPC method, tool, capability,
  outcome, error code, status, latency, request/response bytes) and a trailing
  `interactions <n>`. Never a body. `N` is 1–1000, default 50.
- `search` — the same lines, filtered. Every filter is an exact match and they
  combine with AND: `--client`, `--tool`, `--capability`, `--correlation-id`,
  `--outcome`, and a window on `recorded_at`: `--since` (inclusive) or
  `--last <n>s|m|h|d` (from now), and `--until` (exclusive). Instants are ISO
  8601 **with an offset** (`Z` or `+hh:mm`); a naive instant is refused. No
  filter at all is accepted and is the same as `list`.
- `show <interaction-id> [--json]` — one full record: every column, the
  allowlisted headers, the diagnostics and the **redacted bodies**. `--json`
  prints one JSON object. An unknown or malformed id prints a `refused` line and
  exits 1.

Every string printed has control, C1 and bidirectional-formatting characters
escaped as `\uXXXX`, so a stored body cannot drive the terminal.

Exit status: `0` success, `1` refused (non-operator process, malformed argument,
unknown interaction, or a database error named by type only), `2` a command
line `argparse` rejects, `3` purge has expired rows remaining.

## Retention and purge

The table is append-only at the database. Triggers refuse every `UPDATE` and
`TRUNCATE`, and refuse a `DELETE` unless the transaction set the purge switch
**and** the row's `recorded_at` is more than 14 days old. The purge command is
the only code that sets that switch. Retention is fixed at 14 days in code and
in the trigger; there is no option to shorten it.

**Nothing purges automatically.** The 14 days is a floor the database
enforces, not a sweep. Rows older than that stay until the purge runs, and the
repository has no scheduler (`ops/systemd` and `ops/launchd` are scaffold
only), so schedule it.

```bash
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py purge --dry-run
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py purge
docker exec <remote-mcp-container> python apps/cli/mcp_interactions.py purge --batch-size 5000
```

Each invocation deletes **one** batch of the oldest expired rows (default 1000,
at most 10 000) in one committed transaction and prints
`deleted=<n> remaining=<n>`. It exits `3` while expired rows remain — run it
again — and `0` when none do. This mirrors
`apps/cli/knowledge_source_profiles.py drain-revalidation`: every run is one
short, bounded transaction under the CLI's 30-second statement timeout, and an
interrupted run loses nothing. `--dry-run` deletes nothing, reports every
expired row as remaining, and always exits `0`, so a re-run loop never spins on
it. Rows another purge holds are skipped, so two concurrent purges do not block
each other; at worst one reports `deleted=0` with work remaining.

### Daily DSM Task Scheduler job

In DSM, Control Panel → Task Scheduler → Create → Scheduled Task →
User-defined script, run as `root`, daily at a quiet hour. Script (substitute
the container name; on DSM `docker` is usually `/usr/local/bin/docker`):

```sh
#!/bin/sh
# Purge MCP interaction log rows older than 14 days. At most 50 batches a run;
# exit 3 means a backlog remains for the next run, and DSM reports the task failed.
container="<remote-mcp-container>"
runs=0
while [ "$runs" -lt 50 ]; do
  docker exec "$container" python apps/cli/mcp_interactions.py purge --batch-size 1000
  status=$?
  [ "$status" -eq 3 ] || exit "$status"
  runs=$((runs + 1))
done
exit 3
```

Enable the task's e-mail notification on abnormal termination so a refused
run (exit 1), a database error, or a persistent backlog (exit 3) is seen.

## Migration

The table, its indexes and its triggers are revision `c8f7ae406d47`
(`migrations/versions/20261011_c8f7ae406d47_mcp_interaction_log.py`), whose
`down_revision` is `a591b81f10a2`. Apply it with the ordinary Alembic upgrade
in [`remote-mcp-cloudflare.md`](remote-mcp-cloudflare.md) or
[`postgres-operations.md`](postgres-operations.md), against a database you have
backed up and are authorised to migrate.

**Downgrading below `c8f7ae406d47` discards the log**: it drops the triggers,
their functions, the table and the `observability` schema. The rows are
bounded-retention telemetry and nothing references them, so the downgrade does
not refuse while rows exist. Export anything you need with `show --json` first.
