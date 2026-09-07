"""Stable, read-only classification of the durable browser-authentication state.

`classify_auth_state` is a pure function of an already-assembled snapshot. It
never queries a store and never mutates, merges, reassigns, or repairs rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import (
    LOCAL_ACCOUNT_SUBJECT,
    AccountIdentityProvider,
)

__all__ = [
    "AuthState",
    "AuthStateKind",
    "AuthStateReason",
    "AuthStateSnapshot",
    "LocalAccountView",
    "classify_auth_state",
]


class AuthStateKind(StrEnum):
    UNINITIALIZED = "uninitialized"
    READY = "ready"
    INCONSISTENT = "inconsistent"


class AuthStateReason(StrEnum):
    BOOTSTRAP_REQUIRED = "bootstrap_required"
    READY = "ready"
    LOCAL_ACCOUNT_BINDING_INVALID = "local_account_binding_invalid"
    LOCAL_ACCOUNT_WITHOUT_CREDENTIAL = "local_account_without_credential"
    FOREIGN_ACTIVE_CREDENTIAL = "foreign_active_credential"
    MULTIPLE_ACTIVE_CREDENTIAL_PRINCIPALS = "multiple_active_credential_principals"
    FOREIGN_ACTIVE_SESSION = "foreign_active_session"
    FOREIGN_ACTIVE_RECOVERY_SET = "foreign_active_recovery_set"
    IMPOSSIBLE_GRANT_OR_CHALLENGE_STATE = "impossible_grant_or_challenge_state"
    PARTIAL_DURABLE_STATE = "partial_durable_state"


@dataclass(frozen=True, slots=True)
class LocalAccountView:
    """The identity fields an inspector needs to judge the fixed local row."""

    principal_id: UUID
    identity_provider: AccountIdentityProvider
    identity_subject: str
    tid: str | None
    oid: str | None


@dataclass(frozen=True, slots=True)
class AuthStateSnapshot:
    """Durable facts already loaded by a caller. One id per active row."""

    local_accounts: tuple[LocalAccountView, ...] = ()
    active_credential_principal_ids: tuple[UUID, ...] = ()
    active_session_principal_ids: tuple[UUID, ...] = ()
    active_recovery_set_principal_ids: tuple[UUID, ...] = ()
    impossible_grant_or_challenge_state: bool = False


@dataclass(frozen=True, slots=True)
class AuthState:
    kind: AuthStateKind
    reasons: tuple[AuthStateReason, ...]
    active_credential_count: int
    active_session_count: int
    active_recovery_set_count: int

    @property
    def bootstrap_required(self) -> bool:
        return self.kind is AuthStateKind.UNINITIALIZED


def _valid_local(account: LocalAccountView) -> bool:
    return (
        account.principal_id == LOCAL_OPERATOR_UUID
        and account.identity_provider is AccountIdentityProvider.LOCAL
        and account.identity_subject == LOCAL_ACCOUNT_SUBJECT
        and account.tid is None
        and account.oid is None
    )


def _unique(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(values))


def classify_auth_state(snapshot: AuthStateSnapshot) -> AuthState:
    """Classify production browser-auth readiness without side effects."""
    credential_count = len(snapshot.active_credential_principal_ids)
    session_count = len(snapshot.active_session_principal_ids)
    recovery_count = len(snapshot.active_recovery_set_principal_ids)
    credential_principals = _unique(snapshot.active_credential_principal_ids)
    session_principals = _unique(snapshot.active_session_principal_ids)
    recovery_principals = _unique(snapshot.active_recovery_set_principal_ids)

    local_valid = len(snapshot.local_accounts) == 1 and _valid_local(snapshot.local_accounts[0])
    binding_invalid = bool(snapshot.local_accounts) and not local_valid
    foreign_credentials = any(value != LOCAL_OPERATOR_UUID for value in credential_principals)
    multiple_credential_principals = len(credential_principals) > 1
    foreign_sessions = any(value != LOCAL_OPERATOR_UUID for value in session_principals)
    foreign_recovery = any(value != LOCAL_OPERATOR_UUID for value in recovery_principals)
    has_credentials = credential_count > 0
    has_other_authority = session_count > 0 or recovery_count > 0
    authority_without_credentials = has_other_authority and not has_credentials
    credentials_without_valid_local = has_credentials and not local_valid
    partial = authority_without_credentials or credentials_without_valid_local
    conflicting = (
        binding_invalid
        or foreign_credentials
        or multiple_credential_principals
        or foreign_sessions
        or foreign_recovery
        or snapshot.impossible_grant_or_challenge_state
        or partial
    )

    if not has_credentials and not conflicting:
        return AuthState(
            kind=AuthStateKind.UNINITIALIZED,
            reasons=(AuthStateReason.BOOTSTRAP_REQUIRED,),
            active_credential_count=credential_count,
            active_session_count=session_count,
            active_recovery_set_count=recovery_count,
        )

    ready = (
        local_valid
        and credential_principals == (LOCAL_OPERATOR_UUID,)
        and not foreign_sessions
        and not foreign_recovery
        and not snapshot.impossible_grant_or_challenge_state
        and not partial
    )
    if ready:
        return AuthState(
            kind=AuthStateKind.READY,
            reasons=(AuthStateReason.READY,),
            active_credential_count=credential_count,
            active_session_count=session_count,
            active_recovery_set_count=recovery_count,
        )

    reasons: list[AuthStateReason] = []
    if binding_invalid:
        reasons.append(AuthStateReason.LOCAL_ACCOUNT_BINDING_INVALID)
    if local_valid and not has_credentials:
        reasons.append(AuthStateReason.LOCAL_ACCOUNT_WITHOUT_CREDENTIAL)
    if foreign_credentials:
        reasons.append(AuthStateReason.FOREIGN_ACTIVE_CREDENTIAL)
    if multiple_credential_principals:
        reasons.append(AuthStateReason.MULTIPLE_ACTIVE_CREDENTIAL_PRINCIPALS)
    if foreign_sessions:
        reasons.append(AuthStateReason.FOREIGN_ACTIVE_SESSION)
    if foreign_recovery:
        reasons.append(AuthStateReason.FOREIGN_ACTIVE_RECOVERY_SET)
    if snapshot.impossible_grant_or_challenge_state:
        reasons.append(AuthStateReason.IMPOSSIBLE_GRANT_OR_CHALLENGE_STATE)
    if partial:
        reasons.append(AuthStateReason.PARTIAL_DURABLE_STATE)
    if not reasons:
        reasons.append(AuthStateReason.PARTIAL_DURABLE_STATE)
    return AuthState(
        kind=AuthStateKind.INCONSISTENT,
        reasons=tuple(reasons),
        active_credential_count=credential_count,
        active_session_count=session_count,
        active_recovery_set_count=recovery_count,
    )
