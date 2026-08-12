"""Bearer token in, raw claims out — and nothing else.

This module owns exactly one step of the authentication boundary: proving that a
presented token was issued by the configured authority, for this application,
and is currently valid. It does **not** decide who the caller is. That is
`principal_identity.PrincipalIdentityService`'s, which takes the claims this
returns, validates `(tid, oid)` against the Moss home tenant, and resolves the
one stable `principal_id`. Keeping the two apart is what lets every identity
rule stay testable with synthetic claims and no token at all.

**PyJWT is a declared dependency, and this is the module it is confined to**
(`AGENTS.md` section 6). The four questions that policy asks:

* *Current use.* RS256 signature verification against a rotating JWKS, plus the
  registered-claim checks (`aud`, `iss`, `exp`, `nbf`) that have to happen in the
  same pass as the signature. The standard library has no JWS implementation;
  hand-rolling one is where the alg-confusion family of defects lives — a token
  declaring `alg: none`, or an HS256 token signed with the RSA *public* key the
  verifier publishes — and both are verification bugs that look like working
  code until someone tries them.
* *Maintenance cost.* Small, and already paid: `mcp` declares `pyjwt[crypto]`
  transitively, so the distribution is installed in every environment this
  repository builds today. What changes is that it becomes a *declared* direct
  requirement with its own floor, so a resolver may not drop it silently.
* *Security surface.* It parses and verifies a token this process was handed. It
  opens no socket of its own; the JWKS fetch is `jwt.PyJWKClient`'s, over
  `urllib`, to the issuer URL an operator configured and to nothing else.
* *Removal path.* A hand-written JWS verifier over `cryptography`, which is
  already installed for the same reason. That would mean owning the algorithm
  allowlist, the key selection, and the registered-claim clock arithmetic — the
  three places this class of defect actually occurs — so the removal path exists
  and is deliberately not the default.

**Verification is configured explicitly, never inferred from the token.** The
algorithm list is pinned to `RS256` here rather than read from the token's own
header, which is the whole of the `alg` defence: a token asking to be verified
with `none`, or with `HS256` against the published public key, names an
algorithm that is not on the list and is refused before any key is used.
`aud`, `iss`, `exp` and `nbf` are required and verified, so a token minted for
another application, by another issuer, or outside its validity window is
refused for that reason and not for an incidental one.

**Nothing about the token reaches the caller.** Every failure leaves as one
`TokenVerificationError` carrying a fixed sentence. PyJWT's own messages are
informative — "Audience doesn't match", "Signature has expired" — and each of
them is an oracle a prober can use to learn what a deployment expects. The
exception is raised outside the handler for the reason `bootstrap.settings`
raises outside its handler: `__cause__` and `__context__` both stay empty, so no
renderer of the chain can print what was suppressed at the top level.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

import jwt

from my_pa.domain.identity.user_account import TokenClaimsError

__all__ = [
    "ALLOWED_ALGORITHMS",
    "REQUIRED_CLAIMS",
    "EntraTokenVerifier",
    "SigningKeySource",
    "TokenVerificationError",
    "jwks_signing_key_source",
]

#: The one signature algorithm this verifier accepts. A tuple rather than a
#: parameter: a deployment that could widen it could widen it to `none`.
ALLOWED_ALGORITHMS: Final = ("RS256",)

#: Registered claims a token must carry to be considered at all. `tid` and `oid`
#: are deliberately absent — they are identity rather than validity, and
#: `domain.identity.user_account.validate_token_claims` is the one place that
#: reads them.
REQUIRED_CLAIMS: Final = ("exp", "nbf", "aud", "iss")

#: Resolves the key a token should be verified with. Injected rather than built
#: inside the verifier so that a test supplies a synthetic key and a composition
#: root supplies the issuer's JWKS, and so the verifier itself never opens a
#: connection.
SigningKeySource = Callable[[str], jwt.PyJWK]


class TokenVerificationError(TokenClaimsError):
    """A presented token did not verify. Carries nothing from the token.

    A subclass of the domain's `TokenClaimsError` so a transport catches one
    type for every authentication failure and cannot answer a signature failure
    differently from a foreign-tenant failure by accident.
    """

    def __init__(self) -> None:
        super().__init__("the presented bearer token did not verify; access is denied")


def jwks_signing_key_source(jwks_uri: str) -> SigningKeySource:
    """The issuer's published keys, fetched and cached by `jwt.PyJWKClient`.

    Configuration names the URL; nothing here defaults one. Entra rotates its
    signing keys, so a pinned public key would be a deployment that stops working
    on a schedule nobody controls — the JWKS is the shape that survives rotation.
    """
    if not jwks_uri.strip():
        raise ValueError("a JWKS URI is required configuration")
    client = jwt.PyJWKClient(jwks_uri.strip(), cache_keys=True)

    def signing_key(token: str) -> jwt.PyJWK:
        return client.get_signing_key_from_jwt(token)

    return signing_key


class EntraTokenVerifier:
    """Verifies one bearer token against one configured application and issuer."""

    __slots__ = ("_audience", "_issuer", "_signing_key")

    def __init__(self, *, audience: str, issuer: str, signing_key: SigningKeySource) -> None:
        if not audience.strip():
            raise ValueError("an expected audience is required configuration")
        if not issuer.strip():
            raise ValueError("an expected issuer is required configuration")
        self._audience = audience.strip()
        self._issuer = issuer.strip()
        self._signing_key = signing_key

    def claims(self, token: str) -> Mapping[str, Any]:
        """The verified claims of `token`, or `TokenVerificationError`.

        Composed inside the handler and raised outside it, so neither
        `__cause__` nor `__context__` carries PyJWT's message — see the module
        docstring on why that message is an oracle rather than a diagnostic.
        """
        decoded: dict[str, Any] | None = None
        try:
            decoded = jwt.decode(
                token,
                key=self._signing_key(token),
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": list(REQUIRED_CLAIMS),
                },
            )
        except jwt.PyJWTError:
            # Deliberately one branch for every verification failure: a bad
            # signature, an unaccepted algorithm, a wrong audience, a wrong
            # issuer, an expired or not-yet-valid token, a missing required
            # claim, and a key the issuer does not publish are all "this token
            # does not authenticate you". Distinguishing them for the caller
            # would publish what the deployment expects.
            decoded = None
        if decoded is None:
            raise TokenVerificationError
        return decoded
