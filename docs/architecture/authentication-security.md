# Authentication and security architecture

Security policy is normative in [`../../SECURITY.md`](../../SECURITY.md). This document explains the implementation boundaries developers must preserve.

## Principal ownership

The acting Principal is server-derived. Browser/API clients do not get to choose a Principal identifier to widen access.

Principal partitioning is enforced across product-owned personal planes such as capture, review, relationship and continuity state. Add cross-Principal denial tests whenever a new persistence/read path could cross that boundary.

## Python gateway authentication

`MY_PA_AUTH_MODE` has two current values:

- `local_operator` — explicit local trust-boundary mode;
- `entra` — bearer-token validation with required tenant/client/issuer/JWKS configuration.

Selecting authenticated mode without required configuration fails startup rather than falling back.

## Browser authentication

The web tier uses:

- `synthetic` for development only, refused in production;
- `passkey` for WebAuthn/passkey authentication.

Passkey authentication produces an opaque server-side SID session. Browser Entra/MSAL and browser local-operator fallback are retired by ADR-011.

The BFF must never send the SID cookie as a gateway bearer or fabricate a credential when the Python gateway is configured for `entra`.

## Remote MCP / OAuth

Remote MCP uses authenticated Streamable HTTP and resource-bound authorization. Refresh-token families are governed by ADR-009. Client authentication, capability/purpose grants and write/operator gates are separate controls.

## Configuration

`src/my_pa/bootstrap/settings.py` is fail-closed:

- unknown `MY_PA_` variables are rejected;
- invalid/out-of-range values are rejected;
- `MY_PA_DATABASE_URL` has no usable default;
- credential-bearing values are redacted from repr/exception paths;
- feature/external-write switches default toward refusal.

## Data handling

Do not commit or log:

- credentials/tokens/private keys;
- database connection strings with secrets;
- personal data or source contents;
- real tenant/application identity values where policy excludes them;
- private NAS/source paths;
- unredacted evidence.

Use synthetic fixtures for automated tests. External model/cloud disclosure requires explicit eligibility for the data involved.

## Source and managed-write boundaries

Original source providers are read-only by default. Managed-document writes are permitted only inside the designated managed store. Product-owned records are a separate PostgreSQL authority class.

Path containment, symlink/hard-link handling, root identity and read bounds are security properties where filesystem code is involved; preserve targeted adversarial tests.

## Logging/observability

Logs and operational output should favor stable identifiers, state and counts rather than payloads/query text. Gateway access logging is intentionally disabled in the current composition.

## Security review triggers

Treat these as security-sensitive feature changes:

- identity/session/authentication;
- Principal derivation/partitioning;
- new remote ingress or network listener;
- new data-disclosure path;
- source/provider filesystem changes;
- managed storage roots;
- credential/secret configuration;
- operator-only or destructive actions;
- external model/service transmission.

Run targeted security/policy tests and request independent review proportional to the boundary affected.
