"""Synthetic profile/configuration boundaries; no credentials or live endpoint."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices, _password
from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.contracts.mcp_database_profiles import (
    McpDatabaseProfile,
    profile_capabilities,
)
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from tests.conftest import Scene, build_service


def test_profile_configuration_is_default_off_and_disjoint() -> None:
    settings = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})
    assert not settings.mcp_database_profiles_enabled
    assert not settings.mcp_database_ro_clients()
    with pytest.raises(SettingsError, match="disjoint"):
        load_settings(
            {
                "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
                "MY_PA_MCP_DATABASE_RO_CLIENT_IDS": "same",
                "MY_PA_MCP_DATABASE_RW_CLIENT_IDS": "same",
            }
        )
    with pytest.raises(SettingsError, match="protected files"):
        load_settings(
            {
                "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
                "MY_PA_MCP_DATABASE_PROFILES_ENABLED": "true",
            }
        )


def test_protected_file_refusals_never_echo_or_chain_secret(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    secret = "synthetic-password-marker-0000000000000000"  # noqa: S105 - public fixture
    path = tmp_path / "password"
    path.write_text(secret + "\n")
    path.chmod(0o400)
    assert _password(str(path)) == secret
    for mode in (0o600, 0o444, 0o644):
        path.chmod(mode)
        with pytest.raises(SettingsError) as error:
            _password(str(path))
        assert secret not in str(error.value)
        assert error.value.__context__ is None and error.value.__cause__ is None
    path.chmod(0o400)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(SettingsError):
        _password(str(link))
    path.unlink()
    with pytest.raises(SettingsError):
        _password(str(path))


def test_all_protected_writes_and_unknown_capabilities_stay_blocked() -> None:
    for profile in McpDatabaseProfile:
        allowed = profile_capabilities(profile)
        for capability in (
            Capability.REPORTS_COMMIT,
            Capability.REPORTS_BEGIN_CYCLE,
            Capability.TASKS_CREATE,
            Capability.CAPTURE_CREATE,
            Capability.ENTITIES_CREATE,
            Capability.SOURCES_ENROLL,
        ):
            assert capability.value not in allowed
        assert "arbitrary.sql" not in allowed
    assert Capability.CANVAS_WORKSPACE_PUT.value not in profile_capabilities(
        McpDatabaseProfile.READ_ONLY
    )
    assert Capability.CANVAS_WORKSPACE_PUT.value in profile_capabilities(
        McpDatabaseProfile.READ_WRITE
    )


@pytest.mark.parametrize("client", ["ro", "rw"])
@pytest.mark.parametrize(
    "capability",
    [
        capability
        for capability in Capability
        if permitted_purposes(capability)
        & {
            Purpose.ISSUE_AUTHORING,
            Purpose.RECORD_LINEAGE_AUTHORING,
            Purpose.ISSUE_WORK_AUTHORING,
            Purpose.LINEAGE_BACKFILL,
        }
    ],
)
def test_lineage_grants_cannot_select_rw_or_expand_profile(
    scene: Scene, client: str, capability: Capability
) -> None:
    ro = build_service(
        scene.world, scene.providers, lineage_enabled=True, lineage_backfill_enabled=True
    )
    rw = build_service(
        scene.world, scene.providers, lineage_enabled=True, lineage_backfill_enabled=True
    )
    profiles = McpDatabaseServices(ro, rw, frozenset({"ro"}), frozenset({"rw"}), ())  # type: ignore[arg-type]
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id=client,
        allowed_capabilities=frozenset({capability.value}),
        capability_purposes=frozenset((capability, p) for p in permitted_purposes(capability)),
    )
    bound = profiles.access(context, write_allowed=True)
    assert bound is not None and bound.service is ro
    assert not bound.allowed_capabilities
    assert not bound.capability_purposes


def test_concurrent_profile_binding_is_request_local_and_never_escalates(scene: Scene) -> None:
    ro = build_service(scene.world, scene.providers)
    rw = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(ro, rw, frozenset({"client-ro"}), frozenset({"client-rw"}), ())  # type: ignore[arg-type]
    original = RemoteAccessContext(
        scene.principal,
        allowed_capabilities=frozenset(c.value for c in Capability),
        capability_purposes=frozenset((c, p) for c in Capability for p in permitted_purposes(c)),
    )

    def check(index: int) -> None:
        client = ("client-ro", "client-rw", "unknown")[index % 3]
        writes = index % 2 == 0
        bound = profiles.access(
            replace(original, authenticated_client_id=client), write_allowed=writes
        )
        if client == "unknown":
            assert bound is None
        else:
            assert bound is not None
            assert bound.principal is original.principal
            assert bound.service is (rw if client == "client-rw" and writes else ro)
            assert (Capability.CANVAS_WORKSPACE_PUT.value in bound.allowed_capabilities) == (
                client == "client-rw" and writes
            )
            assert all(c.value in bound.allowed_capabilities for c, p in bound.capability_purposes)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, range(120)))
    assert original.service is None
    denied = replace(
        original,
        principal=replace(scene.principal, authenticated=False),
        authenticated_client_id="client-rw",
    )
    assert profiles.access(denied, write_allowed=True) is None


def test_nonregular_file_refuses_without_waiting_for_a_writer(tmp_path: Path) -> None:
    import os

    tmp_path.chmod(0o700)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o400)
    with pytest.raises(SettingsError):
        _password(str(fifo))


def test_disabled_composition_opens_no_file_or_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    from my_pa.bootstrap.gateway import GatewayRuntime
    from my_pa.bootstrap.mcp_database_profiles import build_mcp_database_services

    settings = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("default-off composition must not read credentials or create pools")

    monkeypatch.setattr("my_pa.bootstrap.mcp_database_profiles._password", forbidden)
    monkeypatch.setattr("my_pa.bootstrap.mcp_database_profiles.create_database_engine", forbidden)
    assert build_mcp_database_services(settings, Mock(spec=GatewayRuntime)) is None


@pytest.mark.parametrize(
    "query", ["options=-c+role%3Downer", "user=owner", "host=elsewhere", "service=unreviewed"]
)
def test_profile_query_cannot_override_role_or_target(query: str) -> None:
    values = {
        "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa?" + query,
        "MY_PA_MCP_DATABASE_PROFILES_ENABLED": "true",
        "MY_PA_MCP_DATABASE_RO_PASSWORD_FILE": "/synthetic/ro",
        "MY_PA_MCP_DATABASE_RW_PASSWORD_FILE": "/synthetic/rw",
        "MY_PA_MCP_DATABASE_EXPECTED_CLUSTER_ID": "123",
    }
    with pytest.raises(SettingsError, match="transport query"):
        load_settings(values)


def test_profile_transport_security_options_are_preserved() -> None:
    settings = load_settings(
        {
            "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa?sslmode=verify-full&channel_binding=require",
            "MY_PA_MCP_DATABASE_PROFILES_ENABLED": "true",
            "MY_PA_MCP_DATABASE_RO_PASSWORD_FILE": "/synthetic/ro",
            "MY_PA_MCP_DATABASE_RW_PASSWORD_FILE": "/synthetic/rw",
            "MY_PA_MCP_DATABASE_EXPECTED_CLUSTER_ID": "123",
        }
    )
    assert settings.parsed_database_url().query["sslmode"] == "verify-full"
    assert settings.parsed_database_url().query["channel_binding"] == "require"


@pytest.mark.parametrize(
    "grant_state",
    ["read_scope", "missing_purpose", "wrong_purpose", "no_grants", "unsupported_write"],
)
def test_effective_read_only_grants_never_select_rw_pool(scene: Scene, grant_state: str) -> None:
    from my_pa.domain.identity.purpose import Purpose

    ro = build_service(scene.world, scene.providers)
    rw = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(ro, rw, frozenset(), frozenset({"rw"}), ())  # type: ignore[arg-type]
    read = Capability.CANVAS_WORKSPACE_GET
    write = Capability.CANVAS_WORKSPACE_PUT
    names = frozenset({read.value, write.value})
    purposes = frozenset(
        {(read, Purpose.CANVAS_WORKSPACE_READ), (write, Purpose.CANVAS_WORKSPACE_AUTHORING)}
    )
    if grant_state == "read_scope":
        names = frozenset({read.value})
    if grant_state == "missing_purpose":
        purposes = frozenset({(read, Purpose.CANVAS_WORKSPACE_READ)})
    if grant_state == "wrong_purpose":
        purposes = frozenset({(write, Purpose.CANVAS_WORKSPACE_READ)})
    if grant_state == "no_grants":
        purposes = frozenset()
    if grant_state == "unsupported_write":
        names = frozenset({read.value, Capability.REPORTS_COMMIT.value})
        purposes = frozenset({(Capability.REPORTS_COMMIT, Purpose.REPORT_AUTHORING)})
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id="rw",
        allowed_capabilities=names,
        capability_purposes=purposes,
    )
    bound = profiles.access(context, write_allowed=True)
    assert bound is not None and bound.service is ro
    assert write.value not in bound.allowed_capabilities
    # A fresh, admitted write regrant, not a stale profile/session, selects RW again.
    restored = profiles.access(
        replace(
            context,
            allowed_capabilities=frozenset({read.value, write.value}),
            capability_purposes=frozenset({(write, Purpose.CANVAS_WORKSPACE_AUTHORING)}),
        ),
        write_allowed=True,
    )
    assert restored is not None and restored.service is rw
