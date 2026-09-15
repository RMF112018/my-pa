"""PC-CM-RUN01-WP05: the two Project Controls commands, at the boundary.

What a command refuses is what never reaches a service, so each refusal here is
checked for the field it names as well as for happening at all. Nothing in this
module reaches a repository: a command is a validated request object and
validating one is the whole of what it does.
"""

from __future__ import annotations

from typing import Final, get_args

import pytest

from my_pa.adapters.normalization import _BUILDERS
from my_pa.application.commands import (
    Command,
    ConfigureProjectControls,
    ReadProjectControlsStatus,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.identity.operation import Capability

PROJECT: Final = "prj_pcaaaa0001aaaa"
ZONE: Final = "America/Chicago"
KEY: Final = "pc-configure-0001"


def _configure(**overrides: object) -> ConfigureProjectControls:
    values: dict[str, object] = {
        "project_id": PROJECT,
        "timezone_name": ZONE,
        "idempotency_key": KEY,
    }
    values.update(overrides)
    return ConfigureProjectControls(**values)  # type: ignore[arg-type]


# --- membership ---------------------------------------------------------------


def test_both_commands_are_members_of_the_dispatched_union() -> None:
    """Union membership is what creates the MCP tool, so it is asserted here."""
    members = {member.capability for member in get_args(Command.__value__)}
    assert Capability.PROJECT_CONTROLS_CONFIGURE in members
    assert Capability.PROJECT_CONTROLS_STATUS in members


def test_both_capabilities_have_a_normalizer() -> None:
    assert Capability.PROJECT_CONTROLS_CONFIGURE in _BUILDERS
    assert Capability.PROJECT_CONTROLS_STATUS in _BUILDERS


def test_the_capabilities_are_the_declared_names() -> None:
    assert ConfigureProjectControls.capability is Capability.PROJECT_CONTROLS_CONFIGURE
    assert ReadProjectControlsStatus.capability is Capability.PROJECT_CONTROLS_STATUS


# --- ConfigureProjectControls -------------------------------------------------


def test_a_well_formed_configure_is_accepted_verbatim() -> None:
    command = _configure(expected_version=3, client_context="web")
    assert command.project_id == PROJECT
    assert command.timezone_name == ZONE
    assert command.idempotency_key == KEY
    assert command.expected_version == 3
    assert command.correlation_id is None


def test_the_timezone_name_is_carried_through_without_repair() -> None:
    """The command performs no trim and no case folding; the domain refuses instead."""
    command = _configure(timezone_name="america/chicago")
    assert command.timezone_name == "america/chicago"


@pytest.mark.parametrize("project_id", ["", "not-an-identifier", "cst_pcaaaa0001aaaa", 17])
def test_a_malformed_project_id_names_project_id(project_id: object) -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        _configure(project_id=project_id)
    assert SafeDetail.PROJECT_ID in refusal.value.safe_details


@pytest.mark.parametrize("timezone_name", ["", "   ", None, 17, b"America/Chicago"])
def test_a_blank_or_non_string_timezone_is_refused(timezone_name: object) -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        _configure(timezone_name=timezone_name)
    assert SafeDetail.SELECTOR in refusal.value.safe_details


@pytest.mark.parametrize("key", [None, "", "short", 12345678, "has space here", "x" * 200])
def test_a_missing_or_malformed_idempotency_key_names_the_key(key: object) -> None:
    """The key is required, and the type is checked before the content."""
    with pytest.raises(InvalidRequestError) as refusal:
        _configure(idempotency_key=key)
    assert SafeDetail.IDEMPOTENCY_KEY in refusal.value.safe_details


def test_the_idempotency_key_is_required_rather_than_defaulted() -> None:
    """There is no shape of this command that carries no key."""
    with pytest.raises(TypeError):
        ConfigureProjectControls(project_id=PROJECT, timezone_name=ZONE)  # type: ignore[call-arg]


@pytest.mark.parametrize("expected_version", [-1, True, 1.0, "1"])
def test_a_malformed_expected_version_names_expected_version(expected_version: object) -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        _configure(expected_version=expected_version)
    assert SafeDetail.EXPECTED_VERSION in refusal.value.safe_details


def test_a_null_expected_version_is_accepted_and_is_the_default() -> None:
    assert _configure().expected_version is None
    assert _configure(expected_version=None).expected_version is None


@pytest.mark.parametrize("field", ["client_context", "correlation_id"])
def test_a_blank_context_or_correlation_field_is_refused(field: str) -> None:
    with pytest.raises(InvalidRequestError):
        _configure(**{field: "   "})


def test_the_command_carries_no_principal_and_no_server_owned_field() -> None:
    """The Principal comes from the authenticated boundary and never from here."""
    fields = set(ConfigureProjectControls.__dataclass_fields__) - {"capability"}
    assert fields == {
        "project_id",
        "timezone_name",
        "idempotency_key",
        "expected_version",
        "client_context",
        "correlation_id",
    }


# --- ReadProjectControlsStatus ------------------------------------------------


def test_a_well_formed_status_read_is_accepted() -> None:
    assert ReadProjectControlsStatus(project_id=PROJECT).project_id == PROJECT


@pytest.mark.parametrize("project_id", ["", "not-an-identifier", "cst_pcaaaa0001aaaa", 17])
def test_a_malformed_status_project_id_names_project_id(project_id: object) -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        ReadProjectControlsStatus(project_id=project_id)  # type: ignore[arg-type]
    assert SafeDetail.PROJECT_ID in refusal.value.safe_details


def test_the_status_read_names_only_a_project() -> None:
    fields = set(ReadProjectControlsStatus.__dataclass_fields__) - {"capability"}
    assert fields == {"project_id"}
