"""R0A claim validation is closed before it is open (MU-AC-02, MU-AC-03).

Fast tier: no database. Everything here is synthetic — the "Moss" tenant is a
made-up UUID and the principals are invented, which is the point: the boundary
must be fully exercisable without a live credential anywhere.
"""

from __future__ import annotations

import pytest

from my_pa.domain.identity.user_account import (
    CallerSuppliedPrincipalError,
    EntraTokenClaims,
    ForeignTenantError,
    MissingClaimError,
    reject_caller_supplied_principal,
    validate_token_claims,
)
from my_pa.infrastructure.persistence.principal_scope import (
    MissingPrincipalContextError,
    require_principal_context,
)
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

MOSS_TENANT = "11111111-2222-3333-4444-555555555555"
FOREIGN_TENANT = "99999999-8888-7777-6666-555555555555"


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "tid": MOSS_TENANT,
        "oid": "aaaa0001-0000-0000-0000-000000000001",
        "upn": "synthetic.employee@moss.example",
        "name": "Synthetic Employee",
    }
    claims.update(overrides)
    return claims


def test_valid_moss_claims_produce_validated_claims() -> None:
    validated = validate_token_claims(_claims(), home_tenant_id=MOSS_TENANT)
    assert validated == EntraTokenClaims(
        tid=MOSS_TENANT,
        oid="aaaa0001-0000-0000-0000-000000000001",
        upn="synthetic.employee@moss.example",
        display_name="Synthetic Employee",
    )


def test_a_foreign_tenant_tid_is_rejected() -> None:
    """MU-AC-03: a non-Moss `tid` never reaches domain access."""
    with pytest.raises(ForeignTenantError):
        validate_token_claims(_claims(tid=FOREIGN_TENANT), home_tenant_id=MOSS_TENANT)


def test_the_foreign_tenant_value_is_not_echoed_in_the_error() -> None:
    """An unexpected tenant ID is untrusted input and stays out of messages."""
    with pytest.raises(ForeignTenantError) as denied:
        validate_token_claims(_claims(tid=FOREIGN_TENANT), home_tenant_id=MOSS_TENANT)
    assert FOREIGN_TENANT not in str(denied.value)


@pytest.mark.parametrize("claim", ["tid", "oid"])
def test_a_missing_required_claim_is_rejected(claim: str) -> None:
    absent = _claims()
    del absent[claim]
    with pytest.raises(MissingClaimError) as denied:
        validate_token_claims(absent, home_tenant_id=MOSS_TENANT)
    assert denied.value.claim == claim


@pytest.mark.parametrize("value", ["", "   ", 7, None, ["x"]])
def test_an_unusable_oid_claim_is_rejected(value: object) -> None:
    with pytest.raises(MissingClaimError):
        validate_token_claims(_claims(oid=value), home_tenant_id=MOSS_TENANT)


@pytest.mark.parametrize("field", ["principal_id", "tid", "oid"])
def test_caller_supplied_identity_in_the_payload_is_rejected(field: str) -> None:
    """MU-AC-02: identity arrives only from the token, never from the body."""
    with pytest.raises(CallerSuppliedPrincipalError) as denied:
        reject_caller_supplied_principal({field: "attacker-chosen"})
    assert denied.value.field == field


def test_caller_supplied_identity_nested_in_the_payload_is_rejected() -> None:
    payload: dict[str, object] = {"metadata": {"principal_id": "attacker-chosen"}}
    with pytest.raises(CallerSuppliedPrincipalError):
        reject_caller_supplied_principal(payload)


def test_a_payload_without_identity_fields_passes() -> None:
    reject_caller_supplied_principal({"text": "a capture", "metadata": {"client": "web"}})


def test_missing_principal_context_is_denied_not_defaulted() -> None:
    """Fail closed: no context is a denial, not an implicit broad read."""
    with pytest.raises(MissingPrincipalContextError):
        require_principal_context(None)


def test_the_identity_service_requires_a_home_tenant() -> None:
    with pytest.raises(ValueError, match="home_tenant_id"):
        PrincipalIdentityService(home_tenant_id="  ")


def test_the_identity_service_validates_against_its_configured_tenant() -> None:
    service = PrincipalIdentityService(home_tenant_id=MOSS_TENANT)
    assert service.validate_claims(_claims()).tid == MOSS_TENANT
    with pytest.raises(ForeignTenantError):
        service.validate_claims(_claims(tid=FOREIGN_TENANT))
