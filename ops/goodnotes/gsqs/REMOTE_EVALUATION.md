# GSQS ChatLLM remote evaluation — Phase B notes

This process is **NOT commissioned**. This document does not claim that the
isolated eval process is deployed, that ChatLLM is connected, that Phase C is
authorized, or that `MEASURED_B0` is established.

`MEASURED_B0` remains `NOT_YET_ESTABLISHED`. Live Cloudflare, DNS, NAS apply,
OAuth client registration, and ChatLLM connector activation are out of scope
for Phase B.

## Isolated architecture

Remote evaluation is a **separate process** from production MCP:

| Surface | Process | Default bind | Resource |
|---|---|---|---|
| Production MCP | `apps/gateway.py mcp-remote` | `127.0.0.1:8766` | production `/mcp` |
| GSQS remote-eval | `apps/gsqs_remote_eval.py` | `127.0.0.1:8767` | `https://my-pa-gsqs.bobby-fetting.me/mcp` |

Adapter: `src/my_pa/adapters/gsqs_remote_eval_mcp.py` (outside `adapters.mcp`
so production package `__init__` is not imported). Process:
`apps/gsqs_remote_eval.py`. Future public host: `my-pa-gsqs.bobby-fetting.me`.
Default bind port: `8767`.

The eval process does not import the production tool registry. It does not
serve `goodnotes.propose`, `goodnotes.work`, or `goodnotes.content`. Compose
example: `ops/nas/compose.gsqs-remote-eval.example.yml` (**EXAMPLE ONLY. NOT
APPLIED.**). Do not edit or apply `ops/nas/remote/compose.yml` from this note.

Settings prefix is `MY_PA_`. The kill switch
`MY_PA_GSQS_REMOTE_EVAL_ENABLED` defaults to `false`. While disabled the
process may still serve `/healthz` (`{"status":"ok"}`); `/readyz` returns 503
and `/mcp` returns 404. No session is required for readiness. Ready JSON is
only `{"status":"ready"}` or `{"status":"unavailable"}` — never session IDs,
rasters, gold, or tokens.

Intended NAS state root: `/srv/my-pa/gsqs-remote-eval`. Settings leave
`MY_PA_GSQS_REMOTE_EVAL_STATE_ROOT` empty until the operator sets it. Tests
must override to a temporary directory and must never use `/srv`. Do not mount
private evaluator gold or a source raster-root beyond the sealed Phase A spool.

## Local vs remote responsibilities

The operator creates the session and opens a repetition **locally**. The remote
process serves only the three evaluation tools against that already-prepared
spool. ChatLLM never creates sessions, never opens repetitions, and never
scores.

## Exact three tools

| Tool | Role |
|---|---|
| `goodnotes.eval.status` | Safe public status of the single active session |
| `goodnotes.eval.next` | Acquire the current leased case and return its PNG as `ImageContent` |
| `goodnotes.eval.submit` | Submit analyzer segments for the outstanding lease |

Scope: `my-pa.gsqs.evaluate`. Resource:
`https://my-pa-gsqs.bobby-fetting.me/mcp`. Future public host:
`my-pa-gsqs.bobby-fetting.me`. Allowed Host values are exact (bind host,
`host:port`, and the public hostname when `MY_PA_GSQS_REMOTE_EVAL_PUBLIC_ORIGIN`
names it). Wildcard hosts and wildcard origins (`*`) are refused.

## Future operator ChatLLM connector steps

Not performed in Phase B. When a later authorization admits a user-level
connector, the expected shape is:

1. Add a **user-level** MCP connector (not workspace-shared production MCP).
2. Transport: Streamable HTTP to `https://my-pa-gsqs.bobby-fetting.me/mcp`.
3. Disable the production MCP connector in that conversation.
4. Open the repetition locally before the remote client calls `next`.
5. Use the frozen prompt only.
6. Retrieve captures locally after the remote session completes.

Do not treat this list as a completed commissioning record.

## Synthetic boundary (NOT commissioned)

Phase B is **NOT commissioned**. Local synthetic enablement does not disclose
handwriting gold, does not establish `MEASURED_B0`, and does not authorize
Phase C. Enabling the process locally with a temporary state root is not a
production activation.

## No Phase C authority

This document grants no Phase C authority, no ChatLLM connection, no DNS or
tunnel change, and no live OAuth client. A later operator decision is required
before any of those.
