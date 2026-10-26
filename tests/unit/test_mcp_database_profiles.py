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


def test_profile_urls_change_only_credentials_and_disable_managed_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from my_pa.bootstrap import mcp_database_profiles as profiles

    settings = load_settings(
        {
            "MY_PA_DATABASE_URL": "postgresql+psycopg://control@db.invalid:5544/my_pa?sslmode=verify-full&channel_binding=require",
            "MY_PA_MCP_DATABASE_PROFILES_ENABLED": "true",
            "MY_PA_MCP_DATABASE_RO_PASSWORD_FILE": "/synthetic/ro",
            "MY_PA_MCP_DATABASE_RW_PASSWORD_FILE": "/synthetic/rw",
            "MY_PA_MCP_DATABASE_EXPECTED_CLUSTER_ID": "123",
            "MY_PA_MANAGED_DOCUMENT_ROOT": "/synthetic/configured-managed-root",
        }
    )
    original = settings.parsed_database_url()
    urls = []
    composed = []

    def factory(url: object, **_kwargs: object) -> MagicMock:
        urls.append(url)
        return MagicMock()

    def compose(actual_settings: object, **kwargs: object) -> SimpleNamespace:
        assert actual_settings is settings
        composed.append(kwargs)
        return SimpleNamespace(service=object())

    def no_reparse(*_args: object, **_kwargs: object) -> None:
        pytest.fail("profile composition must not parse the validated target again")

    monkeypatch.setattr("my_pa.bootstrap.settings.make_url", no_reparse)
    monkeypatch.setattr(profiles, "_password", lambda path: "synthetic-" + path.rsplit("/", 1)[-1])
    monkeypatch.setattr(profiles, "_bind_engine", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(profiles, "create_database_engine", factory)
    monkeypatch.setattr(profiles, "build_gateway_runtime", compose)
    control = SimpleNamespace(work_engine=MagicMock(), audit_engine=MagicMock())
    services = profiles.build_mcp_database_services(settings, control)  # type: ignore[arg-type]
    assert services is not None
    assert [url.username for url in urls] == ["my_pa_mcp_ro", "my_pa_mcp_rw"]
    assert [url.password for url in urls] == ["synthetic-ro", "synthetic-rw"]
    for url in urls:
        assert (url.drivername, url.host, url.port, url.database, url.query) == (
            original.drivername,
            original.host,
            original.port,
            original.database,
            original.query,
        )
    assert original.username == "control" and original.password is None
    assert settings.parsed_database_url() is original
    assert len(composed) == 2
    assert all(kwargs["permit_managed_documents"] is False for kwargs in composed)
    assert all(kwargs["permit_reenrichment"] is False for kwargs in composed)


def test_managed_store_suppression_skips_factory_and_legacy_default_composes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, Mock

    from my_pa.bootstrap import gateway

    settings = load_settings(
        {
            "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
            "MY_PA_MANAGED_DOCUMENT_ROOT": "/synthetic/configured-managed-root",
        }
    )
    store = object()
    factory = Mock(return_value=store)
    monkeypatch.setattr(gateway, "managed_byte_store", factory)
    engine = MagicMock()
    suppressed = gateway.build_gateway_runtime(
        settings,
        data_engine=engine,
        independent_audit_engine=MagicMock(),
        controls_engine=MagicMock(),
        permit_managed_documents=False,
    )
    factory.assert_not_called()
    assert suppressed.service._managed_store_or_none is None
    legacy = gateway.build_gateway_runtime(
        settings,
        data_engine=engine,
        independent_audit_engine=MagicMock(),
        controls_engine=MagicMock(),
    )
    factory.assert_called_once_with(settings, engine)
    assert legacy.service._managed_store_or_none is store


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


# Record lineage S4 x #339 (merge worker M6): the Program-reporting plane in a
# restricted MCP composition. Every value is synthetic.

_S4_PROGRAM_SETTINGS = {
    "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
    "MY_PA_LINEAGE_ENABLED": "true",
    "MY_PA_PROGRAM_REPORTING_ENABLED": "true",
    "MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
}


def test_restricted_composition_never_builds_the_program_engine_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from my_pa.application.service import _PROGRAM_READ_CAPABILITIES
    from my_pa.bootstrap import gateway
    from my_pa.domain.intelligence.source_manifest import ProgramReferenceBlock

    settings = load_settings(_S4_PROGRAM_SETTINGS)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("an injected data engine must not be paired with a settings-built pool")

    monkeypatch.setattr(gateway, "create_database_engine", forbidden)
    # Three distinct engines and pools: #340 refuses an injected data engine
    # that shares an engine or pool with the audit or control path.
    restricted = gateway.build_gateway_runtime(
        settings,
        data_engine=MagicMock(),
        independent_audit_engine=MagicMock(),
        controls_engine=MagicMock(),
        permit_reenrichment=False,
        permit_managed_documents=False,
    )
    service = restricted.service
    assert restricted.program_read_engine is None
    assert service._program_read_unit_of_work is None
    # Both Program reads are withheld; the switch-only S4 names stay served on
    # the injected (restricted) engine, and the profile ceiling trims them.
    assert not _PROGRAM_READ_CAPABILITIES & service.available_capabilities
    assert Capability.REPORTS_MANIFEST in service.available_capabilities
    # `reports.commit` recomputes nothing: the manifest records `not_attempted`.
    recompute = service._program_reference_recompute(
        SimpleNamespace(  # type: ignore[arg-type]
            capability_grants=None, principal=SimpleNamespace(principal_id="principal-s4")
        )
    )
    assert recompute is not None
    block = ProgramReferenceBlock(
        program_entity_ids=("ent_unitprogram00001",),
        overview_sha256="a" * 64,
        source_cutoff_at="2026-10-24T06:30:00.000001Z",
    )
    assert recompute(block)["verification_state"] == "not_attempted"


def test_legacy_composition_still_builds_the_program_engine() -> None:
    from my_pa.application.service import _PROGRAM_READ_CAPABILITIES
    from my_pa.bootstrap.gateway import build_gateway_runtime

    legacy = build_gateway_runtime(load_settings(_S4_PROGRAM_SETTINGS))
    try:
        assert legacy.program_read_engine is not None
        assert legacy.program_read_engine is not legacy.work_engine
        assert legacy.service._program_read_unit_of_work is not None
        assert legacy.service.available_capabilities >= _PROGRAM_READ_CAPABILITIES
    finally:
        legacy.close()


def test_no_profile_ceiling_admits_an_s4_program_reporting_name() -> None:
    from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

    assert len(PROGRAM_REPORTING_CAPABILITIES) == 7
    for profile in McpDatabaseProfile:
        allowed = profile_capabilities(profile)
        assert not PROGRAM_REPORTING_CAPABILITIES & allowed
        assert Capability.REPORTS_COMMIT.value not in allowed


@pytest.mark.parametrize("classification", ["application_read", "application_write"])
def test_the_s4_manifest_table_cannot_be_granted_to_an_mcp_role(classification: str) -> None:
    from unittest.mock import MagicMock

    from my_pa.infrastructure.database.mcp_object_grants import (
        McpObjectGrant,
        McpObjectGrantError,
        _grant_created_mcp_object,
    )

    connection = MagicMock()
    spec = McpObjectGrant(
        schema="knowledge",
        name="intelligence_artifact_manifests",
        creator="synthetic_creator",
        classification=classification,  # type: ignore[arg-type]
        kind="r",
        review_id="SYNTHETIC-S4-REVIEW",
    )
    with pytest.raises(McpObjectGrantError), _grant_created_mcp_object(connection, spec):
        pytest.fail("a protected report object must refuse before CREATE")
    connection.exec_driver_sql.assert_not_called()
    connection.execute.assert_not_called()


# Record lineage S3.1 (S3.1 contract section 7.11, worker N1): remote exposure of
# lineage on the restricted profiles is an operator opt-in from two closed,
# code-owned sets, empty by default; it never issues a grant. Every value is
# synthetic.

#: The #339 ceilings, spelled: the S3.1 default must leave them byte-identical.
_339_READ_CEILING = frozenset(
    {
        "capabilities.get",
        "sources.list",
        "sources.metadata",
        "sources.status",
        "knowledge.search",
        "knowledge.read",
        "knowledge.coverage",
        "capture.read",
        "capture.list",
        "capture.search",
        "tasks.read",
        "tasks.list",
        "tasks.search",
        "tasks.history",
        "tasks.comments.list",
        "commitments.read",
        "commitments.list",
        "commitments.search",
        "commitments.history",
        "commitments.waiting_on",
        "canvas.workspace.get",
        "reports.read",
        "reports.latest",
        "reports.list",
        "reports.search",
        "reports.types.list",
    }
)
_339_WRITE_CEILING = frozenset({"canvas.workspace.put"})
#: Section 7.11, verbatim.
_OPT_IN_READS = frozenset(
    {
        "records.lineage",
        "records.lineage.related",
        "records.associations.history",
        "issues.read",
        "issues.list",
        "issues.history",
        "issues.timeline",
        "issues.handoffs.list",
        "issues.closure_readiness",
        "meetings.notes.versions",
        "meetings.notes.read_version",
        "commitments.v2.read",
        "commitments.v2.list",
        "commitments.v2.search",
        "commitments.v2.waiting_on",
    }
)
_OPT_IN_WRITES = frozenset(
    {
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
        "records.associations.contest",
        "records.associations.reinstate",
        "issues.memberships.add",
        "issues.memberships.end",
        "issues.memberships.correct",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.handoffs.record",
        "issues.handoffs.correct",
        "issues.work.create_task",
        "issues.work.create_commitment",
        "issues.create",
        "issues.update",
    }
)
#: Never admissible (section 7.11).
_NEVER = frozenset(
    {
        "issues.close",
        "issues.reopen",
        "records.associations.confirm",
        "issues.memberships.confirm",
        "issues.project_links.confirm",
        "records.backfill.plan",
        "records.backfill.report",
        "programs.members.resolve",
        "programs.overview",
    }
)
_PROFILE_SETTINGS = {
    "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
    "MY_PA_MCP_DATABASE_PROFILES_ENABLED": "true",
    "MY_PA_MCP_DATABASE_RO_PASSWORD_FILE": "/synthetic/ro/password",
    "MY_PA_MCP_DATABASE_RW_PASSWORD_FILE": "/synthetic/rw/password",
    "MY_PA_MCP_DATABASE_EXPECTED_CLUSTER_ID": "7000000000000000001",
}


def _opted_in(names: str) -> object:
    return load_settings({**_PROFILE_SETTINGS, "MY_PA_MCP_DATABASE_PROFILE_OPT_INS": names})


def _profiles(
    scene: Scene, opt_ins: frozenset[str] = frozenset()
) -> tuple[McpDatabaseServices, object, object]:
    ro = build_service(scene.world, scene.providers, lineage_enabled=True)
    rw = build_service(scene.world, scene.providers, lineage_enabled=True)
    services = McpDatabaseServices(
        ro,
        rw,
        frozenset({"ro"}),
        frozenset({"rw"}),
        (),  # type: ignore[arg-type]
        opt_ins=opt_ins,
    )
    return services, ro, rw


def _granted(scene: Scene, client: str, *names: str) -> RemoteAccessContext:
    capabilities = [Capability(name) for name in names]
    return RemoteAccessContext(
        scene.principal,
        authenticated_client_id=client,
        allowed_capabilities=frozenset(names),
        capability_purposes=frozenset(
            (capability, purpose)
            for capability in capabilities
            for purpose in permitted_purposes(capability)
        ),
    )


def test_default_profile_ceilings_are_byte_identical() -> None:
    from my_pa.contracts.mcp_database_profiles import (
        MCP_PROFILE_READ_CAPABILITIES,
        MCP_PROFILE_WRITE_CAPABILITIES,
    )

    assert {c.value for c in MCP_PROFILE_READ_CAPABILITIES} == _339_READ_CEILING
    assert {c.value for c in MCP_PROFILE_WRITE_CAPABILITIES} == _339_WRITE_CEILING
    for opt_ins in (None, frozenset()):
        read = (
            profile_capabilities(McpDatabaseProfile.READ_ONLY)
            if opt_ins is None
            else profile_capabilities(McpDatabaseProfile.READ_ONLY, opt_ins)
        )
        write = (
            profile_capabilities(McpDatabaseProfile.READ_WRITE)
            if opt_ins is None
            else profile_capabilities(McpDatabaseProfile.READ_WRITE, opt_ins)
        )
        assert read == _339_READ_CEILING
        assert write == _339_READ_CEILING | _339_WRITE_CEILING
    # The setting is default empty, with or without the profiles.
    plain = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})
    assert plain.mcp_database_profile_opt_in_set() == frozenset()
    assert load_settings(_PROFILE_SETTINGS).mcp_database_profile_opt_in_set() == frozenset()
    assert McpDatabaseServices.__dataclass_fields__["opt_ins"].default == frozenset()


def test_an_opt_in_admits_only_admissible_lineage_names() -> None:
    from my_pa.contracts.mcp_database_profiles import (
        MCP_PROFILE_OPT_IN_CAPABILITY_NAMES,
        MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
        MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    )

    assert {c.value for c in MCP_PROFILE_OPT_IN_READ_CAPABILITIES} == _OPT_IN_READS
    assert {c.value for c in MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES} == _OPT_IN_WRITES
    assert MCP_PROFILE_OPT_IN_CAPABILITY_NAMES == _OPT_IN_READS | _OPT_IN_WRITES
    everything = _OPT_IN_READS | _OPT_IN_WRITES
    settings = _opted_in(",".join(sorted(everything)))
    assert settings.mcp_database_profile_opt_in_set() == everything  # type: ignore[attr-defined]
    assert profile_capabilities(McpDatabaseProfile.READ_ONLY, everything) == (
        _339_READ_CEILING | _OPT_IN_READS
    )
    assert profile_capabilities(McpDatabaseProfile.READ_WRITE, everything) == (
        _339_READ_CEILING | _339_WRITE_CEILING | _OPT_IN_READS | _OPT_IN_WRITES
    )
    # One opt-in adds exactly that one name.
    assert profile_capabilities(
        McpDatabaseProfile.READ_ONLY, frozenset({"records.lineage.related"})
    ) == (_339_READ_CEILING | {"records.lineage.related"})


@pytest.mark.parametrize("names", ["arbitrary.sql", "tasks.create", "reports.commit", "issues"])
def test_an_opt_in_outside_the_admissible_set_refuses_composition(names: str) -> None:
    with pytest.raises(SettingsError, match="admissible"):
        _opted_in(names)
    with pytest.raises(SettingsError, match="admissible"):
        _opted_in(f"records.lineage,{names}")
    # And any name at all while the restricted profiles are off.
    with pytest.raises(SettingsError, match="require MCP database profiles"):
        load_settings(
            {
                "MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa",
                "MY_PA_MCP_DATABASE_PROFILE_OPT_INS": "records.lineage",
            }
        )


def test_write_opt_ins_reach_only_the_rw_profile() -> None:
    for name in sorted(_OPT_IN_WRITES):
        opted = frozenset({name})
        assert name not in profile_capabilities(McpDatabaseProfile.READ_ONLY, opted), name
        assert name in profile_capabilities(McpDatabaseProfile.READ_WRITE, opted), name
    for name in sorted(_OPT_IN_READS):
        opted = frozenset({name})
        for profile in McpDatabaseProfile:
            assert name in profile_capabilities(profile, opted), (name, profile)


def test_an_opted_in_write_grant_selects_the_rw_profile(scene: Scene) -> None:
    assert_name = Capability.RECORDS_ASSOCIATIONS_ASSERT.value
    context = _granted(scene, "rw", assert_name)
    # Not opted in: the #339 behaviour -- the ro service, and the write trimmed.
    services, ro, rw = _profiles(scene)
    bound = services.access(context, write_allowed=True)
    assert bound is not None and bound.service is ro
    assert not bound.allowed_capabilities
    # Opted in: the surviving opted-in write grant selects the rw service.
    services, ro, rw = _profiles(scene, frozenset({assert_name}))
    bound = services.access(context, write_allowed=True)
    assert bound is not None and bound.service is rw
    assert bound.allowed_capabilities == frozenset({assert_name})
    # Writes off, or an ro-listed client, still bind the ro service and no write.
    for client, writes in (("rw", False), ("ro", True)):
        bound = services.access(_granted(scene, client, assert_name), write_allowed=writes)
        assert bound is not None and bound.service is ro, (client, writes)
        assert not bound.allowed_capabilities


def test_reports_manifest_is_never_admissible(scene: Scene) -> None:
    from my_pa.contracts.mcp_database_profiles import MCP_PROFILE_OPT_IN_CAPABILITY_NAMES

    name = Capability.REPORTS_MANIFEST.value
    assert name not in MCP_PROFILE_OPT_IN_CAPABILITY_NAMES
    with pytest.raises(SettingsError, match="admissible"):
        _opted_in(name)
    # Even handed straight to the ceiling, it is not admitted.
    for profile in McpDatabaseProfile:
        assert name not in profile_capabilities(profile, frozenset({name}))
    services, _ro, _rw = _profiles(scene, frozenset({name}))
    bound = services.access(_granted(scene, "rw", name), write_allowed=True)
    assert bound is not None and not bound.allowed_capabilities


def test_close_reopen_backfill_confirm_and_program_reads_are_never_admissible() -> None:
    from my_pa.contracts.mcp_database_profiles import MCP_PROFILE_OPT_IN_CAPABILITY_NAMES

    assert not _NEVER & MCP_PROFILE_OPT_IN_CAPABILITY_NAMES
    for name in sorted(_NEVER):
        assert Capability(name)  # every one is a declared name
        with pytest.raises(SettingsError, match="admissible"):
            _opted_in(name)
        for profile in McpDatabaseProfile:
            assert name not in profile_capabilities(profile, frozenset({name})), name


def test_an_opt_in_never_issues_a_grant(scene: Scene) -> None:
    everything = _OPT_IN_READS | _OPT_IN_WRITES
    services, _ro, rw = _profiles(scene, everything)
    # A client granted only a #339 read reaches only that read: the opt-ins
    # widen the ceiling, never the client's own grants.
    granted = _granted(scene, "rw", Capability.CANVAS_WORKSPACE_GET.value)
    bound = services.access(granted, write_allowed=True)
    assert bound is not None
    assert bound.allowed_capabilities == frozenset({Capability.CANVAS_WORKSPACE_GET.value})
    assert bound.capability_purposes <= granted.capability_purposes
    # A client granted one opted-in write reaches that write and nothing else.
    one = Capability.ISSUES_MEMBERSHIPS_ADD.value
    bound = services.access(_granted(scene, "rw", one), write_allowed=True)
    assert bound is not None and bound.service is rw
    assert bound.allowed_capabilities == frozenset({one})
    # No grant at all: nothing, whatever is opted in.
    bound = services.access(
        RemoteAccessContext(
            scene.principal,
            authenticated_client_id="rw",
            allowed_capabilities=frozenset(),
            capability_purposes=frozenset(),
        ),
        write_allowed=True,
    )
    assert bound is not None and not bound.allowed_capabilities
