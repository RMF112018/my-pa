"""Pure auth-state classification. Fast tier; no database."""

from __future__ import annotations

from uuid import uuid4

from my_pa.domain.identity.auth_state import (
    AuthStateKind,
    AuthStateReason,
    AuthStateSnapshot,
    LocalAccountView,
    classify_auth_state,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import (
    LOCAL_ACCOUNT_SUBJECT,
    AccountIdentityProvider,
)

FOREIGN = uuid4()


def _local() -> LocalAccountView:
    return LocalAccountView(
        principal_id=LOCAL_OPERATOR_UUID,
        identity_provider=AccountIdentityProvider.LOCAL,
        identity_subject=LOCAL_ACCOUNT_SUBJECT,
        tid=None,
        oid=None,
    )


def test_empty_store_is_uninitialized() -> None:
    state = classify_auth_state(AuthStateSnapshot())
    assert state.kind is AuthStateKind.UNINITIALIZED
    assert state.bootstrap_required
    assert state.reasons == (AuthStateReason.BOOTSTRAP_REQUIRED,)
    assert state.active_credential_count == 0


def test_valid_local_row_without_credentials_is_uninitialized() -> None:
    snapshot = AuthStateSnapshot(local_accounts=(_local(),))
    state = classify_auth_state(snapshot)
    assert state.kind is AuthStateKind.UNINITIALIZED
    assert state.reasons == (AuthStateReason.BOOTSTRAP_REQUIRED,)
    assert AuthStateReason.LOCAL_ACCOUNT_WITHOUT_CREDENTIAL not in state.reasons
    assert snapshot.local_accounts[0].principal_id == LOCAL_OPERATOR_UUID


def test_ready_requires_bound_local_account_and_local_credentials() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_credential_principal_ids=(LOCAL_OPERATOR_UUID, LOCAL_OPERATOR_UUID),
            active_session_principal_ids=(LOCAL_OPERATOR_UUID,),
            active_recovery_set_principal_ids=(LOCAL_OPERATOR_UUID,),
        )
    )
    assert state.kind is AuthStateKind.READY
    assert state.reasons == (AuthStateReason.READY,)
    assert state.active_credential_count == 2
    assert state.active_session_count == 1
    assert state.active_recovery_set_count == 1


def test_invalid_local_binding_is_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(
                LocalAccountView(
                    principal_id=FOREIGN,
                    identity_provider=AccountIdentityProvider.LOCAL,
                    identity_subject=LOCAL_ACCOUNT_SUBJECT,
                    tid=None,
                    oid=None,
                ),
            )
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.LOCAL_ACCOUNT_BINDING_INVALID in state.reasons


def test_local_account_with_sessions_but_no_credential_is_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_session_principal_ids=(LOCAL_OPERATOR_UUID,),
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.LOCAL_ACCOUNT_WITHOUT_CREDENTIAL in state.reasons
    assert AuthStateReason.PARTIAL_DURABLE_STATE in state.reasons


def test_foreign_active_credential_is_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_credential_principal_ids=(FOREIGN,),
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.FOREIGN_ACTIVE_CREDENTIAL in state.reasons
    assert AuthStateReason.PARTIAL_DURABLE_STATE not in state.reasons


def test_multiple_active_credential_principals_are_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_credential_principal_ids=(LOCAL_OPERATOR_UUID, FOREIGN),
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.MULTIPLE_ACTIVE_CREDENTIAL_PRINCIPALS in state.reasons
    assert AuthStateReason.FOREIGN_ACTIVE_CREDENTIAL in state.reasons


def test_foreign_session_and_recovery_are_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_credential_principal_ids=(LOCAL_OPERATOR_UUID,),
            active_session_principal_ids=(FOREIGN,),
            active_recovery_set_principal_ids=(FOREIGN,),
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.FOREIGN_ACTIVE_SESSION in state.reasons
    assert AuthStateReason.FOREIGN_ACTIVE_RECOVERY_SET in state.reasons


def test_impossible_grant_state_is_inconsistent() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(
            local_accounts=(_local(),),
            active_credential_principal_ids=(LOCAL_OPERATOR_UUID,),
            impossible_grant_or_challenge_state=True,
        )
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.IMPOSSIBLE_GRANT_OR_CHALLENGE_STATE in state.reasons


def test_credentials_without_local_account_are_partial_durable_state() -> None:
    state = classify_auth_state(
        AuthStateSnapshot(active_credential_principal_ids=(LOCAL_OPERATOR_UUID,))
    )
    assert state.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.PARTIAL_DURABLE_STATE in state.reasons


def test_classifier_does_not_mutate_the_snapshot() -> None:
    snapshot = AuthStateSnapshot(
        local_accounts=(_local(),),
        active_credential_principal_ids=(LOCAL_OPERATOR_UUID,),
    )
    first = classify_auth_state(snapshot)
    second = classify_auth_state(snapshot)
    assert first == second
    assert snapshot.local_accounts[0].principal_id == LOCAL_OPERATOR_UUID
