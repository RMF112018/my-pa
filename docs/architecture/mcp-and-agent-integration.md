# MCP and agent integration

MY-PA exposes its canonical application capabilities to model/agent clients through the Model Context Protocol without creating a second domain API.

## Surfaces

### Local MCP
`apps/gateway.py mcp` serves MCP over stdin/stdout. It opens no socket. In local-operator mode the process uses the same composed Principal/application as other local transports.

### Remote MCP
`apps/gateway.py mcp-remote` is a separately enabled authenticated Streamable HTTP surface. It requires explicit origin/OAuth/resource configuration and durable server-side authorization controls. Enabling remote MCP does not itself grant write authority or publish the service externally.

Detailed operational procedures are in `ops/runbooks/mcp-and-cli-operations.md` and `ops/runbooks/remote-mcp-cloudflare.md`.

## One capability model

HTTP, MCP and CLI converge on `src/my_pa/adapters/normalization.py` and the same `ApplicationService`.

MCP tools are derived from:

- the application capabilities the process actually composed;
- the command/schema associated with each capability.

Do not maintain a second hand-written list of tools or a client-specific shadow schema.

## Adding a capability/tool

A new MCP-visible capability normally requires:

1. a canonical capability identifier;
2. request/command schema;
3. application use-case implementation;
4. authorization/purpose/disclosure behavior;
5. persistence/domain implementation if needed;
6. composition availability;
7. MCP schema derivation/parity tests;
8. HTTP/CLI parity tests when the capability belongs on those transports;
9. remote-grant/write classification when remote invocation is possible.

If step 1-6 are correct, MCP publication should follow from canonical wiring rather than an adapter list edit.

## Authorization

Client connectivity is not authority.

Remote requests are bounded by independent controls such as:

- authenticated client/token/resource;
- server-resolved Principal;
- durable capability grant;
- purpose grant;
- feature/composition gate;
- policy gate;
- remote-write gate for writes;
- stronger operator profile where a specific operator-only action requires it.

Do not accept caller-supplied Principal or capability grants.

## ChatLLM and other MCP clients

The canonical MCP catalog is client-neutral. Current code has an optional, default-off compact ChatLLM publication profile for explicitly configured OAuth client IDs on the same remote MCP resource. It changes publication shape, not application authority or public capability semantics.

Do not add client names to capability identifiers. A generic MCP client—including a ChatGPT-compatible client—must satisfy the same transport/authentication/grant contracts unless a separately implemented compatibility profile says otherwise. Do not infer that a client is approved or reachable merely because it speaks MCP.

## Error/result conventions

Transport output must preserve canonical application responses:

- typed error/refusal codes;
- safe details only;
- disclosure/evidence states;
- optimistic-concurrency conflicts;
- idempotent receipts where the capability defines them.

Do not convert `unavailable`, `no_evidence`, denied, unsupported or conflict into an empty success.

## Security

- stdout is the MCP wire for stdio; operational notices belong on stderr.
- remote MCP must validate host/origin/resource/authentication before application authority.
- secrets/tokens are runtime inputs and must not be logged or committed.
- remote MCP never turns local filesystem/source authority into automatic external disclosure.

## Testing

Relevant tests live under `tests/contract/`, `tests/security/`, `tests/policy/` and targeted unit/database suites. Transport-parity tests must cover new capabilities so HTTP/MCP/CLI cannot drift semantically.

See [`../reference/mcp-capabilities.md`](../reference/mcp-capabilities.md).
