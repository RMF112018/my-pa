"""Principal binding for the operator-only GoodNotes trigger."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from apps.cli import goodnotes
from pytest import MonkeyPatch

from my_pa.bootstrap.settings import AuthMode
from my_pa.domain.identity.principal import Principal, PrincipalKind


def _settings(mode: AuthMode) -> SimpleNamespace:
    return SimpleNamespace(auth_mode=mode)


def test_entra_goodnotes_requires_and_validates_explicit_owner(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(goodnotes, "load_settings", lambda: _settings(AuthMode.ENTRA))
    with pytest.raises(ValueError, match="requires --principal-id"):
        goodnotes._operator_principal_id(None)
    assert goodnotes._operator_principal_id("prn_fedcba9876543210") == "prn_fedcba9876543210"
    with pytest.raises(ValueError, match="identifier"):
        goodnotes._operator_principal_id("not-a-principal")


def test_local_goodnotes_refuses_a_different_principal(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(goodnotes, "load_settings", lambda: _settings(AuthMode.LOCAL_OPERATOR))
    monkeypatch.setattr(
        goodnotes,
        "local_principal",
        lambda: Principal("prn_0123456789abcdef", PrincipalKind.OPERATOR, True),
    )
    assert goodnotes._operator_principal_id(None) == "prn_0123456789abcdef"
    with pytest.raises(ValueError, match="does not match"):
        goodnotes._operator_principal_id("prn_fedcba9876543210")
