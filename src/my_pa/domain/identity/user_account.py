"""Provider-neutral user accounts and provider-specific claim validation.

This is the *user* identity plane the v4.0 Moss package introduces. It is
deliberately not `Principal`/`PrincipalKind` from `principal.py`: those name
authenticated *actors* of the control plane (operator, gateway, worker); a
`UserAccount` names an authenticated Moss *person*, and its `principal_id` is
the partition key every durable user-scoped record carries.

Three rules are enforced here, in the domain, so no adapter can relax them:

* **Canonical identity is `(identity_provider, identity_subject)`.** Entra's
  `(tid, oid)` remains a provider-specific uniqueness key; local accounts do
  not invent either claim.
* **A Principal derives only from validated token claims.**
  `validate_token_claims` is the single constructor of `EntraTokenClaims`, and
  it fails closed: a missing `tid`, a missing `oid`, or a `tid` that is not the
  Moss home tenant raises before any domain access is possible (MU-AC-02,
  MU-AC-03).
* **Caller-supplied identity is rejected, not ignored.**
  `reject_caller_supplied_principal` raises when a request payload attempts to
  carry `principal_id`, `principalId`, `tid`, or `oid`, so the attempt is denied
  and auditable rather than silently overwritten by the server-derived value.

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

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID

__all__ = [
    "FORBIDDEN_IDENTITY_FIELDS",
    "LOCAL_ACCOUNT_SUBJECT",
    "SYNTHETIC_TENANT_ID",
    "AccountIdentityProvider",
    "CallerSuppliedPrincipalError",
    "ConsentState",
    "EntraTokenClaims",
    "ForeignTenantError",
    "MissingClaimError",
    "PrincipalScopeGrant",
    "TokenClaimsError",
    "UserAccount",
    "UserLifecycleState",
    "local_user_account",
    "reject_caller_supplied_principal",
    "validate_token_claims",
]


class AccountIdentityProvider(StrEnum):
    """The bounded identity sources the fixed deployment currently supports."""

    ENTRA = "entra"
    SYNTHETIC = "synthetic"
    LOCAL = "local"


LOCAL_ACCOUNT_SUBJECT = "local-operator"
SYNTHETIC_TENANT_ID = "11111111-2222-3333-4444-555555555555"


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
#: `principalId` is the same identifier in the BFF JSON vocabulary. Provider and
#: subject keys stay off this set: adding them would require a scanner update
#: outside this package, and the closed Entra/principal names already catch
#: caller-chosen identity.
FORBIDDEN_IDENTITY_FIELDS: frozenset[str] = frozenset({"principal_id", "principalId", "tid", "oid"})


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
    identity_provider: AccountIdentityProvider
    identity_subject: str
    tid: str | None
    oid: str | None
    upn: str | None
    display_name: str | None
    first_seen_at: datetime
    last_authenticated_at: datetime | None
    consent_state: ConsentState
    lifecycle_state: UserLifecycleState
    home_tenant_verified: bool

    def __post_init__(self) -> None:
        if not self.identity_subject.strip():
            raise ValueError("identity_subject is required")
        ensure_utc(self.first_seen_at)
        if self.last_authenticated_at is not None:
            ensure_utc(self.last_authenticated_at)
        if self.identity_provider is AccountIdentityProvider.LOCAL:
            if self.principal_id != LOCAL_OPERATOR_UUID:
                raise ValueError("the local account must use LOCAL_OPERATOR_UUID")
            if self.identity_subject != LOCAL_ACCOUNT_SUBJECT:
                raise ValueError("the local account subject is fixed")
            if self.tid is not None or self.oid is not None:
                raise ValueError("a local account has no Entra tid or oid")
            return
        if not self.tid or not self.tid.strip() or not self.oid or not self.oid.strip():
            raise ValueError("Entra-shaped accounts require tid and oid")
        if self.identity_subject != f"{self.tid}:{self.oid}":
            raise ValueError("Entra-shaped identity_subject is tid:oid")
        if self.identity_provider is AccountIdentityProvider.SYNTHETIC:
            if self.tid != SYNTHETIC_TENANT_ID:
                raise ValueError("synthetic accounts use SYNTHETIC_TENANT_ID")
        elif self.tid == SYNTHETIC_TENANT_ID:
            raise ValueError("entra accounts do not use the synthetic tenant")


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


def local_user_account(*, account_id: UUID, now: datetime) -> UserAccount:
    """Construct the one fixed local account without caller-selected identity."""
    return UserAccount(
        id=account_id,
        principal_id=LOCAL_OPERATOR_UUID,
        identity_provider=AccountIdentityProvider.LOCAL,
        identity_subject=LOCAL_ACCOUNT_SUBJECT,
        tid=None,
        oid=None,
        upn=None,
        display_name="Local operator",
        first_seen_at=now,
        last_authenticated_at=now,
        consent_state=ConsentState.PENDING,
        lifecycle_state=UserLifecycleState.ACTIVE,
        home_tenant_verified=False,
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
