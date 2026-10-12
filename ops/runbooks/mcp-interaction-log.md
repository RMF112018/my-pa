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
- **JSON keys.** Any object key that, lower-cased with `-` read as `_`, is one
  of `authorization`, `proxy_authorization`, `cookie`, `set_cookie`,
  `access_token`, `refresh_token`, `id_token`, `token`, `bearer`,
  `client_secret`, `secret`, `password`, `passphrase`, `api_key`, `apikey`,
  `private_key`, `signing_key`, `code_verifier`, `assertion`,
  `client_assertion`, `session_token`, `credential` or `credentials` has its
  value replaced by `"[REDACTED]"`, whatever the value's type.
- **Every string.** `Bearer <token>` becomes `Bearer [REDACTED]`, and any
  JWT-shaped run (`eyJ<…>.<…>.<…>`) becomes `[REDACTED]`. Both are matched anywhere
  in the string, without a word boundary; over-redaction is the safe direction.
- **JSON inside strings.** A string that is itself a JSON object or array (MCP
  `TextContent.text` carries the response envelope that way) is parsed,
  redacted by the same rules, and re-serialised, up to four levels deep.
- **Text that is not JSON** (or a body that overflowed the capture buffer) is
  redacted as text: `"key": "value"` pairs for the key list above — plain, one
  escaping level down (`\"key\":\"value\"`), and single-quoted as a Python repr
  prints them — plus the Bearer and JWT patterns.
- **NUL characters**, which PostgreSQL text and JSONB cannot hold, and
  unencodable surrogates are replaced with U+FFFD and flagged in
  `diagnostics.capture.nul_replaced`.
- `diagnostics.capture.redactions` counts the replacements made.

Redaction is pattern-based. A credential carried under an unlisted key in a
non-credential shape would be stored; treat the log as sensitive regardless.

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
- An exchange is queued **after** its last response byte is sent, into a
  bounded queue (1024). A full queue drops the exchange and counts it.
- Parsing, redaction, hashing and the insert run on one daemon writer thread,
  on a dedicated engine with a 2-second statement timeout, separate from the
  pools that serve requests.
- **If the database is unavailable or slow**, the insert fails, the row is
  dropped and counted, and nothing is retried. Requests are unaffected. Each
  write failure prints one count-only line on the container's standard error,
  for example
  `mcp-interaction-log write_failed dropped=0 write_failures=3 capture_errors=0`
  — never a body, header or identifier.
- The counts since the last successful write ride on the **next row that is
  written**, as `diagnostics.capture.dropped_before` and
  `write_failures_before`. A gap in the log therefore shows up on the row after
  it.
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
