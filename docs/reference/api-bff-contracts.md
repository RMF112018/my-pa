# API and BFF contracts

## One application contract

Python HTTP, MCP, and CLI are protocol adapters over the same application capability model. Transport code must not create a second authorization, disclosure, or domain behavior.

Primary implementation paths:

- request normalization: `src/my_pa/adapters/normalization.py`;
- application dispatch: `src/my_pa/application/`;
- public shapes: `src/my_pa/contracts/v1/`;
- HTTP: `src/my_pa/adapters/http/`;
- MCP: `src/my_pa/adapters/mcp/`;
- CLI: `src/my_pa/adapters/cli/`;
- composition: `apps/gateway.py`.

## Public envelope behavior

When extending a capability, preserve:

- request metadata normalization;
- server-derived Principal/authorization context;
- strict input validation;
- typed success/error/refusal shape;
- disclosure/provenance semantics;
- safe error details;
- idempotency/expected-version semantics for writes where the domain requires them.

Do not leak ORM/provider objects or provider-specific vocabulary into public contracts.

## Browser BFF

`web/` is a server-side BFF over the Python gateway. It may adapt browser/session concerns but not redefine domain truth.

For a new/changed BFF route:

1. identify the canonical Python capability;
2. resolve the authenticated session server-side;
3. construct only allowed command fields;
4. call the gateway through the shared web HTTP layer;
5. decode the response with a capability-owned decoder;
6. preserve typed refusal/degraded/conflict states;
7. expose only browser-safe data;
8. add route/decoder/contract tests.

The browser must not supply a Principal or Python gateway bearer.

## Contract synchronization

[`web/src/contracts/gateway.json`](../../web/src/contracts/gateway.json) is the generated/checked frontend contract boundary. Follow the [frontend contract boundary README](../../web/src/contracts/README.md) and its parity tests when backend contract shapes change. Do not hand-maintain a divergent browser model to make a UI compile.

## Optimistic concurrency and idempotency

Writes that expose expected versions, idempotency keys, or receipts do so to preserve concurrency/identity guarantees. BFF code must pass and surface those semantics rather than silently retrying as a new operation.

## Testing

Relevant layers include:

- Python command/domain unit tests;
- transport parity/contract tests;
- HTTP/MCP negative evidence;
- web decoder tests;
- BFF route tests;
- focused browser E2E for user-visible flows.

See [Testing and review](../development/testing-and-review.md).
