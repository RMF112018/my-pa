# Canonical TypeScript contract boundary

This directory is the web/BFF mirror of the current Python application contract. It is a supporting implementation reference, not an independent product specification or domain authority.

## Authority

Current technical authority is:

1. Python transport-neutral contracts under `src/my_pa/contracts/`;
2. domain vocabulary/invariants under `src/my_pa/domain/`;
3. application capability behavior under `src/my_pa/application/`;
4. generated/checked web contract material and parity tests in this tree.

Accepted product/UX intent remains Drive-owned. Historical frontend packages or work-package labels do not override current repository contracts.

## Boundary rules

- `gateway.json` is the generated/checked gateway contract used by the web tier.
- Python wire `snake_case` is adapted to TypeScript/browser conventions at the BFF/decoder boundary; do not change wire semantics in UI components.
- Browser code must not invent a Principal, gateway credential, authorization result, or domain lifecycle state.
- Error/refusal/disclosure shapes remain bounded and must not expose credentials, sensitive source content, or cross-Principal confirmation.
- A backend contract change must update the generated/checked mirror and the applicable Python/web parity tests in the same bounded change.

Capability-owned decoders live under `web/src/lib/api/decode/`; BFF route behavior is documented in [API and BFF contracts](../../../docs/reference/api-bff-contracts.md).
