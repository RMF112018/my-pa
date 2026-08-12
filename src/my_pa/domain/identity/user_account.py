"""User accounts: the R0A Principal registry vocabulary and claim validation.

This is the *user* identity plane the v4.0 Moss package introduces. It is
deliberately not `Principal`/`PrincipalKind` from `principal.py`: those name
authenticated *actors* of the control plane (operator, gateway, worker); a
`UserAccount` names an authenticated Moss *person*, and its `principal_id` is
the partition key every durable user-scoped record carries.

Three rules are enforced here, in the domain, so no adapter can relax them:

* **Identity is `(tid, oid)` and nothing else.** `upn` and `display_name` are
  mutable observations — a rename must never fork or reassign an account.
* **A Principal derives only from validated token claims.**
  `validate_token_claims` is the single constructor of `EntraTokenClaims`, and
  it fails closed: a missing `tid`, a missing `oid`, or a `tid` that is not the
  Moss home tenant raises before any domain access is possible (MU-AC-02,
  MU-AC-03).
* **Caller-supplied identity is rejected, not ignored.**
  `reject_caller_supplied_principal` raises when a request payload attempts to
  carry `principal_id`, `tid`, or `oid`, so the attempt is denied and auditable
  rather than silently overwritten by the token-derived value.

Nothing here touches a database, a token library, or a network: synthetic
claims are sufficient to exercise every branch, which is what keeps live
credentials out of R0A entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

__all__ = [
    "FORBIDDEN_IDENTITY_FIELDS",
    "CallerSuppliedPrincipalError",
    "ConsentState",
    "EntraTokenClaims",
    "ForeignTenantError",
    "MissingClaimError",
    "PrincipalScopeGrant",
    "TokenClaimsError",
    "UserAccount",
    "UserLifecycleState",
    "reject_caller_supplied_principal",
    "validate_token_claims",
]


class ConsentState(StrEnum):
    """Whether this Principal's delegated consent is usable."""

    PENDING = "pending"
    GRANTED = "granted"
    REVOKED = "revoked"


class UserLifecycleState(StrEnum):
    """Account lifecycle from the v4.0 domain model (document 09)."""

    INVITED = "invited"
    ACTIVE = "active"
    CONSENT_REQUIRED = "consent_required"
    SCOPE_INSUFFICIENT = "scope_insufficient"
    SUSPENDED = "suspended"
    DEPROVISIONED = "deprovisioned"


class TokenClaimsError(Exception):
    """A token's claims cannot establish a Principal. Fail closed."""


class MissingClaimError(TokenClaimsError):
    """A required claim (`tid` or `oid`) is absent, empty, or not a string."""

    def __init__(self, claim: str) -> None:
        super().__init__(f"token claims are missing a usable '{claim}' claim")
        self.claim = claim


class ForeignTenantError(TokenClaimsError):
    """The token's `tid` is not the Moss home tenant (MU-AC-03).

    The foreign value is deliberately not embedded in the message: a tenant ID
    from an unexpected token is untrusted input and does not belong in logs.
    """

    def __init__(self) -> None:
        super().__init__("token tid is not the Moss home tenant; access is denied")


class CallerSuppliedPrincipalError(TokenClaimsError):
    """A request payload attempted to carry principal identity (MU-AC-02)."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"request payload carries the identity field '{field}'; principal "
            "identity derives only from validated token claims"
        )
        self.field = field


#: Payload keys that would constitute caller-supplied principal identity.
FORBIDDEN_IDENTITY_FIELDS: frozenset[str] = frozenset({"principal_id", "tid", "oid"})


@dataclass(frozen=True, slots=True)
class EntraTokenClaims:
    """The validated identity claims of one Entra token.

    Construct through `validate_token_claims`; a hand-built instance in test
    code represents claims that already passed the boundary.
    """

    tid: str
    oid: str
    upn: str | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class UserAccount:
    """One row of the Principal registry, as the domain sees it."""

    id: UUID
    principal_id: UUID
    tid: str
    oid: str
    upn: str | None
    display_name: str | None
    first_seen_at: datetime
    last_authenticated_at: datetime | None
    consent_state: ConsentState
    lifecycle_state: UserLifecycleState
    home_tenant_verified: bool


@dataclass(frozen=True, slots=True)
class PrincipalScopeGrant:
    """One delegated Microsoft Graph scope consented for one Principal."""

    id: UUID
    principal_id: UUID
    scope: str
    consent_type: str | None
    consented_at: datetime | None
    revoked_at: datetime | None

    @property
    def is_active(self) -> bool:
        """Whether the grant has been consented and not revoked."""
        return self.consented_at is not None and self.revoked_at is None


def _required_string_claim(claims: Mapping[str, object], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise MissingClaimError(name)
    return value.strip()


def _optional_string_claim(claims: Mapping[str, object], name: str) -> str | None:
    value = claims.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def validate_token_claims(claims: Mapping[str, object], *, home_tenant_id: str) -> EntraTokenClaims:
    """Validate raw token claims into `EntraTokenClaims`, or raise.

    `home_tenant_id` is configuration (the Moss single-tenant ID; synthetic in
    every test). The comparison happens *here*, before any repository or
    domain object is reachable, which is what "rejected before domain access"
    means structurally.
    """
    tid = _required_string_claim(claims, "tid")
    oid = _required_string_claim(claims, "oid")
    if tid != home_tenant_id:
        raise ForeignTenantError()
    return EntraTokenClaims(
        tid=tid,
        oid=oid,
        upn=_optional_string_claim(claims, "upn"),
        display_name=_optional_string_claim(claims, "name"),
    )


def reject_caller_supplied_principal(payload: Mapping[str, object]) -> None:
    """Raise if a request payload attempts to carry principal identity.

    Checks the payload and any nested mappings, because `metadata.principal_id`
    style nesting is exactly how a caller would try to smuggle identity. The
    check is a denial, not a sanitizer: overwriting the field silently would
    hide the attempt from audit.
    """
    stack: list[Mapping[str, object]] = [payload]
    while stack:
        mapping = stack.pop()
        for key, value in mapping.items():
            if key in FORBIDDEN_IDENTITY_FIELDS:
                raise CallerSuppliedPrincipalError(key)
            if isinstance(value, Mapping):
                stack.append(value)
