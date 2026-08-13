"""Principal selection for the operator-only Apple control commands."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from apps import apple_grant
from apps.cli import apple_credentials

from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.settings import AuthMode, Settings

DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_apple_operator_probe"
PRINCIPAL = "prn_0000000000000001"


def entra_settings() -> Settings:
    return Settings(
        database_url=DSN,
        auth_mode=AuthMode.ENTRA,
        entra_tenant_id="synthetic-tenant",
        entra_client_id="synthetic-client",
        entra_issuer="https://example.invalid/synthetic/v2.0",
        entra_jwks_uri="https://example.invalid/synthetic/keys",
    )


@pytest.mark.parametrize(
    "resolve",
    [apple_grant._operator_principal, apple_credentials._operator_principal],
)
def test_entra_operator_must_explicitly_name_a_valid_owning_principal(
    resolve: Callable[[Settings, str | None], str],
) -> None:
    with pytest.raises(ValueError, match="requires --principal-id"):
        resolve(entra_settings(), None)
    assert resolve(entra_settings(), PRINCIPAL) == PRINCIPAL
    with pytest.raises(ValueError, match="identifier"):
        resolve(entra_settings(), "not-a-principal")


@pytest.mark.parametrize(
    "resolve",
    [apple_grant._operator_principal, apple_credentials._operator_principal],
)
def test_scratch_operator_is_derived_and_cannot_be_overridden(
    resolve: Callable[[Settings, str | None], str],
) -> None:
    settings = Settings(database_url=DSN)
    expected = local_principal().principal_id
    assert resolve(settings, None) == expected
    assert resolve(settings, expected) == expected
    with pytest.raises(ValueError, match="does not match"):
        resolve(settings, PRINCIPAL)
