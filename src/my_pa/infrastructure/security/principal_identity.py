"""The R0A authentication boundary: raw claims in, Principal context out.

This is the only module allowed to turn token claims into a
`PrincipalContext`, and it composes exactly three moves, in an order that
cannot be reshuffled by a caller:

1. `reject_caller_supplied_principal(payload)` — the request body may not
   carry identity at all (MU-AC-02);
2. `validate_token_claims(claims, home_tenant_id=…)` — required claims
   present and the `tid` is the Moss home tenant, or denied before any
   repository is touched (MU-AC-03);
3. `resolve_or_create` — the registry maps the validated `(tid, oid)` to its
   one stable `principal_id`, idempotently.

`home_tenant_id` is injected configuration. Tests inject synthetic values;
no live tenant ID, credential, or token library appears anywhere in R0A. The
service holds no connection of its own — the caller owns the transaction,
which keeps "account resolved" and "request served" in one commit or none.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import Connection

from my_pa.domain.identity.user_account import (
    EntraTokenClaims,
    UserAccount,
    reject_caller_supplied_principal,
    validate_token_claims,
)
from my_pa.infrastructure.persistence.principal_scope import PrincipalContext
from my_pa.infrastructure.persistence.user_accounts import UserAccountRepository

__all__ = ["AuthenticatedPrincipal", "PrincipalIdentityService"]


class AuthenticatedPrincipal:
    """The result of one successful authentication: account plus context."""

    __slots__ = ("account", "context")

    def __init__(self, account: UserAccount, context: PrincipalContext) -> None:
        self.account = account
        self.context = context


class PrincipalIdentityService:
    """Resolve authenticated Principals from validated token claims only."""

    def __init__(self, *, home_tenant_id: str) -> None:
        if not home_tenant_id or not home_tenant_id.strip():
            raise ValueError("home_tenant_id is required configuration")
        self._home_tenant_id = home_tenant_id.strip()

    def validate_claims(self, claims: Mapping[str, object]) -> EntraTokenClaims:
        """Validate raw claims against the Moss home tenant, or raise."""
        return validate_token_claims(claims, home_tenant_id=self._home_tenant_id)

    def authenticate(
        self,
        connection: Connection,
        *,
        claims: Mapping[str, object],
        payload: Mapping[str, object] | None = None,
        now: datetime,
    ) -> AuthenticatedPrincipal:
        """Authenticate one request: reject, validate, resolve — in that order.

        `payload` is the request body when there is one; passing it here is
        what makes the caller-supplied-identity rejection un-skippable on the
        authenticated path rather than a check adapters remember to add.
        """
        if payload is not None:
            reject_caller_supplied_principal(payload)
        validated = self.validate_claims(claims)
        account = UserAccountRepository(connection).resolve_or_create(validated, now=now)
        return AuthenticatedPrincipal(
            account=account,
            context=PrincipalContext(principal_id=account.principal_id),
        )
