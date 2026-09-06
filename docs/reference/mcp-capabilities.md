# MCP capability development

## Architecture

MY-PA exposes application capabilities as MCP tools through the same application service used by HTTP and CLI.

- local MCP: `apps/gateway.py mcp`, stdio, no listening socket;
- remote MCP: `apps/gateway.py mcp-remote`, separately enabled authenticated Streamable HTTP;
- adapter implementation: `src/my_pa/adapters/mcp/`;
- command/application authority: `src/my_pa/application/`;
- capability/purpose vocabulary: `src/my_pa/domain/identity/`.

The published tool catalog is derived from what the composed application can serve. Do not maintain a second hard-coded capability list in documentation.

## Adding a capability/tool

A new MCP-visible operation normally begins **inside** the application, not in MCP:

1. define/extend domain semantics and invariant vocabulary;
2. define transport-neutral command/public shapes;
3. register the capability and purpose/authorization semantics in the canonical identity vocabulary;
4. implement the application use case and persistence/provider ports if needed;
5. make it available through the composition root under explicit feature/security gates;
6. verify generic transport normalization can build it;
7. verify MCP schema derivation/tool publication;
8. add transport-parity and authorization tests;
9. document the current capability/domain reference.

Do not add an MCP-only privileged bypass.

## Authentication and grants

Local stdio process identity is a local composition concern; it is not a credential channel.

Remote MCP uses authenticated server-side identity and durable capability/purpose grants. Authentication alone does not authorize a tool. Feature gates, write gates, policy, Principal partitioning, and operator-only grant ceilings continue to apply.

Never accept a caller-supplied Principal as authority.

## Client compatibility

A client may see only the tools the process is composed to serve. Clients must tolerate typed refusal and unavailable states. ChatGPT/ChatLLM-specific publication profiles may change catalog presentation for an explicitly allowlisted authenticated client, but they do not create a second resource URL, grant vocabulary, or domain implementation.

## Errors and results

Preserve the canonical application envelope/error/refusal semantics. Do not translate a denied operation into an empty success, and do not expose unsafe exception text.

## Testing

For a new MCP tool/capability, include:

- application capability tests;
- schema/tool publication test;
- transport-parity test;
- remote authentication/grant negative tests if remotely reachable;
- write/idempotency/expected-version tests when applicable.

Deep current operation/reference: `ops/runbooks/mcp-and-cli-operations.md` and `ops/runbooks/remote-mcp-cloudflare.md`.
