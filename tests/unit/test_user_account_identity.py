"""Provider-neutral UserAccount identity contracts. Fast tier; no database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import (
    FORBIDDEN_IDENTITY_FIELDS,
    LOCAL_ACCOUNT_SUBJECT,
    SYNTHETIC_TENANT_ID,
    AccountIdentityProvider,
    CallerSuppliedPrincipalError,
    ConsentState,
    UserAccount,
    UserLifecycleState,
    local_user_account,
    reject_caller_supplied_principal,
)

WHEN = datetime(2026, 9, 7, 12, tzinfo=UTC)
OID = "aaaa0001-0000-0000-0000-000000000001"


def _entra(**overrides: object) -> UserAccount:
    values: dict[str, object] = {
        "id": uuid4(),
        "principal_id": uuid4(),
        "identity_provider": AccountIdentityProvider.ENTRA,
        "identity_subject": f"tenant-a:{OID}",
        "tid": "tenant-a",
        "oid": OID,
        "upn": None,
        "display_name": None,
        "first_seen_at": WHEN,
        "last_authenticated_at": None,
        "consent_state": ConsentState.PENDING,
        "lifecycle_state": UserLifecycleState.ACTIVE,
        "home_tenant_verified": True,
    }
    values.update(overrides)
    return UserAccount(**values)  # type: ignore[arg-type]


def test_local_user_account_is_the_fixed_operator_without_entra_claims() -> None:
    account_id = uuid4()
    account = local_user_account(account_id=account_id, now=WHEN)
    assert account.id == account_id
    assert account.principal_id == LOCAL_OPERATOR_UUID
    assert account.identity_provider is AccountIdentityProvider.LOCAL
    assert account.identity_subject == LOCAL_ACCOUNT_SUBJECT
    assert account.tid is None
    assert account.oid is None
    assert account.upn is None
    assert account.lifecycle_state is UserLifecycleState.ACTIVE


def test_local_account_rejects_fake_entra_claims_and_foreign_uuid() -> None:
    with pytest.raises(ValueError, match="LOCAL_OPERATOR_UUID"):
        local = local_user_account(account_id=uuid4(), now=WHEN)
        UserAccount(
            id=local.id,
            principal_id=uuid4(),
            identity_provider=AccountIdentityProvider.LOCAL,
            identity_subject=LOCAL_ACCOUNT_SUBJECT,
            tid=None,
            oid=None,
            upn=None,
            display_name=local.display_name,
            first_seen_at=WHEN,
            last_authenticated_at=WHEN,
            consent_state=ConsentState.PENDING,
            lifecycle_state=UserLifecycleState.ACTIVE,
            home_tenant_verified=False,
        )
    with pytest.raises(ValueError, match="tid or oid"):
        UserAccount(
            id=uuid4(),
            principal_id=LOCAL_OPERATOR_UUID,
            identity_provider=AccountIdentityProvider.LOCAL,
            identity_subject=LOCAL_ACCOUNT_SUBJECT,
            tid=SYNTHETIC_TENANT_ID,
            oid=OID,
            upn=None,
            display_name=None,
            first_seen_at=WHEN,
            last_authenticated_at=WHEN,
            consent_state=ConsentState.PENDING,
            lifecycle_state=UserLifecycleState.ACTIVE,
            home_tenant_verified=False,
        )


def test_entra_and_synthetic_require_tid_oid_subject() -> None:
    entra = _entra()
    assert entra.identity_subject == f"{entra.tid}:{entra.oid}"
    synthetic = _entra(
        identity_provider=AccountIdentityProvider.SYNTHETIC,
        tid=SYNTHETIC_TENANT_ID,
        identity_subject=f"{SYNTHETIC_TENANT_ID}:{OID}",
    )
    assert synthetic.identity_provider is AccountIdentityProvider.SYNTHETIC
    with pytest.raises(ValueError, match="tid and oid"):
        _entra(tid=None, identity_subject=f":{OID}")
    with pytest.raises(ValueError, match="tid:oid"):
        _entra(identity_subject="not-tid-oid")
    with pytest.raises(ValueError, match="synthetic tenant"):
        _entra(tid=SYNTHETIC_TENANT_ID, identity_subject=f"{SYNTHETIC_TENANT_ID}:{OID}")
    with pytest.raises(ValueError, match="SYNTHETIC_TENANT_ID"):
        _entra(
            identity_provider=AccountIdentityProvider.SYNTHETIC,
            identity_subject=f"other:{OID}",
            tid="other",
        )


def test_forbidden_identity_fields_include_bff_principal_id() -> None:
    assert frozenset({"principal_id", "principalId", "tid", "oid"}) == FORBIDDEN_IDENTITY_FIELDS
    with pytest.raises(CallerSuppliedPrincipalError) as denied:
        reject_caller_supplied_principal({"principalId": str(LOCAL_OPERATOR_UUID)})
    assert denied.value.field == "principalId"
