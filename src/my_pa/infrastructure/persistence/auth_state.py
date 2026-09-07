"""Read-only validation of the fixed browser-authentication Principal."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, exists, select

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.auth_state import (
    AuthState,
    AuthStateSnapshot,
    LocalAccountView,
    classify_auth_state,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import AccountIdentityProvider
from my_pa.infrastructure.persistence.auth_grants import auth_grants
from my_pa.infrastructure.persistence.user_accounts import user_accounts
from my_pa.infrastructure.persistence.webauthn_auth import (
    auth_sessions,
    recovery_code_sets,
    webauthn_challenges,
    webauthn_credentials,
)


class AuthStateValidator:
    """Classify state without repairing, merging, reassigning, or deleting it."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def inspect(self, *, now: datetime) -> AuthState:
        instant = ensure_utc(now)
        local_accounts = tuple(
            LocalAccountView(
                principal_id=row.principal_id,
                identity_provider=AccountIdentityProvider(row.identity_provider),
                identity_subject=row.identity_subject,
                tid=row.tid,
                oid=row.oid,
            )
            for row in self._connection.execute(
                select(
                    user_accounts.c.principal_id,
                    user_accounts.c.identity_provider,
                    user_accounts.c.identity_subject,
                    user_accounts.c.tid,
                    user_accounts.c.oid,
                ).where(
                    (user_accounts.c.identity_provider == AccountIdentityProvider.LOCAL.value)
                    | (user_accounts.c.principal_id == LOCAL_OPERATOR_UUID)
                )
            )
        )
        credential_principals = tuple(
            self._connection.execute(
                select(webauthn_credentials.c.principal_id).where(
                    webauthn_credentials.c.revoked_at.is_(None)
                )
            ).scalars()
        )
        session_principals = tuple(
            self._connection.execute(
                select(auth_sessions.c.principal_id).where(
                    auth_sessions.c.revoked_at.is_(None),
                    auth_sessions.c.superseded_by_id.is_(None),
                    auth_sessions.c.idle_expires_at > instant,
                    auth_sessions.c.absolute_expires_at > instant,
                )
            ).scalars()
        )
        recovery_principals = tuple(
            self._connection.execute(
                select(recovery_code_sets.c.principal_id).where(
                    recovery_code_sets.c.revoked_at.is_(None)
                )
            ).scalars()
        )
        return classify_auth_state(
            AuthStateSnapshot(
                local_accounts=local_accounts,
                active_credential_principal_ids=credential_principals,
                active_session_principal_ids=session_principals,
                active_recovery_set_principal_ids=recovery_principals,
                impossible_grant_or_challenge_state=self._impossible_grant_or_challenge_state(),
            )
        )

    def _impossible_grant_or_challenge_state(self) -> bool:
        orphan_challenge = self._connection.execute(
            select(
                exists(
                    select(webauthn_challenges.c.id).where(
                        webauthn_challenges.c.auth_grant_id.is_not(None),
                        ~exists(
                            select(auth_grants.c.id).where(
                                auth_grants.c.id == webauthn_challenges.c.auth_grant_id
                            )
                        ),
                    )
                )
            )
        ).scalar_one()
        both_terminal = self._connection.execute(
            select(
                exists(
                    select(auth_grants.c.id).where(
                        auth_grants.c.consumed_at.is_not(None),
                        auth_grants.c.revoked_at.is_not(None),
                    )
                )
            )
        ).scalar_one()
        return bool(orphan_challenge or both_terminal)
