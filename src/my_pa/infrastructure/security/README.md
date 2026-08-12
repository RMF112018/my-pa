# Security Boundary

**Status:** `IMPLEMENTING` (was `SCAFFOLD_ONLY`; activated by WP-01, the R0A
Identity Foundation work package of the ratified Moss v4.0 campaign — see
[`docs/campaign/WORK-PACKAGE-MAP.md`](/docs/campaign/WORK-PACKAGE-MAP.md)).

This directory owns the authentication boundary that turns validated token
claims into a Principal context:

- [`principal_identity.py`](principal_identity.py) —
  `PrincipalIdentityService`: rejects caller-supplied identity, validates
  `(tid, oid)` claims against the injected Moss home tenant ID, and resolves
  the stable `principal_id` through the registry. Synthetic claims only; no
  live credential or tenant value appears here.
- [`entra_token.py`](entra_token.py) — `EntraTokenVerifier`: proves a presented
  bearer token was issued by the configured authority for this application and
  is currently valid, and hands its raw claims on. It decides nothing about
  identity. **This is the one module in the tree permitted to import PyJWT**
  (`tests/architecture/test_scope_and_hygiene.py` confines it here the way it
  confines Starlette to the transport), and the algorithm allowlist is pinned to
  `RS256` rather than read from the token, which is the defence against the
  `alg: none` and HS256-with-the-public-key attacks. No key, PEM, or token
  literal is committed; the tests mint an RSA keypair at runtime.

`WP-05` wired both into the composition root:
`bootstrap.gateway.entra_authenticator` is the production call site, reached
when `MY_PA_AUTH_MODE=entra`. An unconfigured `entra` mode refuses to start
rather than downgrading.

Credentials, live source-system access, tenant activation, deployment, and
production activation remain out of scope and separately gated. No live tenant,
application registration, issuer, or key is named anywhere in this repository.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
