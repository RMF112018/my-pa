"""Synthetic-only PostgreSQL role routing, audit, Principal and future-grant proofs.

Opt-in to an exclusively owned isolated local/CI fixture. Never consumes MY_PA_DATABASE_URL.
A separate expected cluster ID prevents accidental use of another local database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateTable

from my_pa.application.commands import GetCanvasWorkspace, PutCanvasWorkspace
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.mcp_database_profiles import build_mcp_database_services
from my_pa.bootstrap.settings import Settings, SettingsError
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.mcp_object_grants import (
    McpObjectGrant,
    McpObjectGrantError,
    grant_created_mcp_object,
)
from my_pa.infrastructure.persistence.tables import audit_events, canvas_workspaces, enrollments
from tests.conftest import metadata_for, operator

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def synthetic_admin() -> Iterator[Engine]:
    raw = os.environ.get("MCP_PROFILE_TEST_ADMIN_URL", "")
    cluster = os.environ.get("MCP_PROFILE_TEST_CLUSTER_ID", "")
    if not raw or not cluster:
        pytest.skip("explicit owned local synthetic PostgreSQL fixture not supplied")
    url = make_url(raw)
    assert url.host == "127.0.0.1" and url.username == "synthetic_admin" and url.database == "my_pa"
    engine = create_engine(url, pool_size=5, max_overflow=0)
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT system_identifier::text FROM pg_control_system()"
            ).scalar_one()
            == cluster
        )
        c.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS knowledge")
        for role in ("my_pa_mcp_ro", "my_pa_mcp_rw", "creator_a", "creator_b"):
            if not c.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)"), {"r": role}
            ).scalar_one():
                if role.startswith("my_pa_mcp_"):
                    # Public synthetic fixtures, never deployed or copied to NAS.
                    c.exec_driver_sql(
                        f"CREATE ROLE {role} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                        "PASSWORD 'synthetic-role-fixture-0000000000000000'"
                    )
                else:
                    c.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN")
        c.exec_driver_sql("GRANT USAGE ON SCHEMA knowledge TO my_pa_mcp_ro,my_pa_mcp_rw")
        c.exec_driver_sql("GRANT USAGE,CREATE ON SCHEMA knowledge TO creator_a,creator_b")
        for table in (enrollments, audit_events, canvas_workspaces):
            if (
                c.execute(
                    text("SELECT to_regclass(:n)"), {"n": f"knowledge.{table.name}"}
                ).scalar_one()
                is None
            ):
                c.exec_driver_sql(
                    str(
                        CreateTable(table, include_foreign_key_constraints=[]).compile(
                            dialect=engine.dialect
                        )
                    )
                )
                for index in table.indexes:
                    index.create(c)
        c.exec_driver_sql(
            "GRANT SELECT ON knowledge.enrollments,knowledge.canvas_workspaces "
            "TO my_pa_mcp_ro,my_pa_mcp_rw"
        )
        c.exec_driver_sql(
            "GRANT INSERT,UPDATE,DELETE ON knowledge.canvas_workspaces TO my_pa_mcp_rw"
        )
    yield engine
    engine.dispose()


def profile_settings(tmp_path: Path, admin: Engine) -> Settings:
    tmp_path.chmod(0o700)
    paths = []
    for role in ("ro", "rw"):
        path = tmp_path / role
        path.write_text("synthetic-role-fixture-0000000000000000\n")
        path.chmod(0o400)
        paths.append(str(path))
    return Settings(
        database_url=admin.url.render_as_string(hide_password=False),
        mcp_database_profiles_enabled=True,
        relationship_intelligence_enabled=True,
        relationship_intelligence_writes_enabled=True,
        mcp_database_ro_client_ids="client-ro",
        mcp_database_rw_client_ids="client-rw",
        mcp_database_ro_password_file=paths[0],
        mcp_database_rw_password_file=paths[1],
        mcp_database_expected_cluster_id=os.environ["MCP_PROFILE_TEST_CLUSTER_ID"],
    )


def test_real_pools_principal_isolation_write_denial_and_durable_audit(
    synthetic_admin: Engine, tmp_path: Path
) -> None:
    settings = profile_settings(tmp_path, synthetic_admin)
    control = build_gateway_runtime(settings)
    assert control.service._relationship_reenrichment_enabled
    services = build_mcp_database_services(settings, control)
    assert services is not None
    assert not services.read_service._relationship_reenrichment_enabled
    assert not services.write_service._relationship_reenrichment_enabled
    try:
        for engine, role in zip(services.engines, ("my_pa_mcp_ro", "my_pa_mcp_rw"), strict=True):
            with engine.connect() as c:
                assert c.exec_driver_sql("SELECT current_user").scalar_one() == role
                if role.endswith("_ro"):
                    assert c.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
                assert not c.exec_driver_sql(
                    "SELECT has_table_privilege(current_user,'knowledge.audit_events','INSERT')"
                ).scalar_one()
        principal = operator()
        focus = "ent_" + uuid4().hex
        put = PutCanvasWorkspace(
            focus_entity_id=focus,
            scope_entity_id=None,
            expected_version=0,
            positions={focus: {"x": 1.0, "y": 2.0}},
        )
        with synthetic_admin.connect() as c:
            before = c.exec_driver_sql("SELECT count(*) FROM knowledge.audit_events").scalar_one()
        # RO work fails after its independent allowed-decision audit commits.
        refused = services.read_service.invoke(
            metadata_for(put.capability, Purpose.CANVAS_WORKSPACE_AUTHORING, principal),
            put,
            principal=principal,
        )
        assert refused.error is not None
        with synthetic_admin.connect() as c:
            assert (
                c.exec_driver_sql("SELECT count(*) FROM knowledge.audit_events").scalar_one()
                == before + 1
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM knowledge.canvas_workspaces WHERE focus_entity_id=:f"
                    ),
                    {"f": focus},
                ).scalar_one()
                == 0
            )
        written = services.write_service.invoke(
            metadata_for(put.capability, Purpose.CANVAS_WORKSPACE_AUTHORING, principal),
            put,
            principal=principal,
        )
        assert written.error is None
        get = GetCanvasWorkspace(focus_entity_id=focus, scope_entity_id=None)
        own = services.read_service.invoke(
            metadata_for(get.capability, Purpose.CANVAS_WORKSPACE_READ, principal),
            get,
            principal=principal,
        )
        assert own.error is None and own.result["version"] == 1
        other = replace(principal, principal_id="prn_" + "b" * 32)
        hidden = services.read_service.invoke(
            metadata_for(get.capability, Purpose.CANVAS_WORKSPACE_READ, other), get, principal=other
        )
        assert hidden.error is None and hidden.result["version"] == 0
    finally:
        services.close()
        control.close()


def test_wrong_cluster_has_no_legacy_pool_fallback(synthetic_admin: Engine, tmp_path: Path) -> None:
    settings = profile_settings(tmp_path, synthetic_admin)
    control = build_gateway_runtime(settings)
    try:
        with pytest.raises(SettingsError, match="no legacy fallback"):
            build_mcp_database_services(
                settings.model_copy(update={"mcp_database_expected_cluster_id": "0"}), control
            )
    finally:
        control.close()


@pytest.mark.parametrize("creator", ["creator_a", "creator_b"])
def test_future_object_uses_actual_creator_not_schema_owner(
    synthetic_admin: Engine, creator: str
) -> None:
    name = "profile_future_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        c.exec_driver_sql(f"SET LOCAL ROLE {creator}")
        spec = McpObjectGrant(
            "knowledge", name, creator, "application_write", "r", "synthetic-review"
        )
        with grant_created_mcp_object(c, spec):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{name}(id integer)")
        assert c.execute(
            text("SELECT has_table_privilege('my_pa_mcp_ro',:t,'SELECT')"),
            {"t": f"knowledge.{name}"},
        ).scalar_one()
        assert not c.execute(
            text("SELECT has_table_privilege('my_pa_mcp_ro',:t,'UPDATE')"),
            {"t": f"knowledge.{name}"},
        ).scalar_one()
        assert c.execute(
            text("SELECT has_table_privilege('my_pa_mcp_rw',:t,'UPDATE')"),
            {"t": f"knowledge.{name}"},
        ).scalar_one()
        c.rollback()


def test_creator_mismatch_and_protected_object_fail_before_create(synthetic_admin: Engine) -> None:
    with synthetic_admin.connect() as c, c.begin():
        for spec in [
            McpObjectGrant(
                "knowledge", "wrong_creator", "creator_b", "application_read", "r", "review"
            ),
            McpObjectGrant(
                "knowledge", "record_events", "synthetic_admin", "application_write", "r", "review"
            ),
        ]:
            with pytest.raises(McpObjectGrantError), grant_created_mcp_object(c, spec):
                pytest.fail("must refuse before CREATE")


def test_default_public_write_aborts_create_even_when_error_is_caught(
    synthetic_admin: Engine,
) -> None:
    name = "profile_future_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        c.exec_driver_sql("SET LOCAL ROLE creator_a")
        c.exec_driver_sql(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT INSERT ON TABLES TO PUBLIC"
        )
        spec = McpObjectGrant(
            "knowledge", name, "creator_a", "application_read", "r", "synthetic-review"
        )
        with pytest.raises(McpObjectGrantError), grant_created_mcp_object(c, spec):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{name}(id integer)")
        assert (
            c.execute(text("SELECT to_regclass(:t)"), {"t": f"knowledge.{name}"}).scalar_one()
            is None
        )
        c.rollback()


def test_creator_change_inside_create_rolls_back_the_object(synthetic_admin: Engine) -> None:
    name = "profile_future_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        spec = McpObjectGrant(
            "knowledge", name, "synthetic_admin", "application_read", "r", "review"
        )
        with pytest.raises(McpObjectGrantError), grant_created_mcp_object(c, spec):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{name}(id integer)")
            c.exec_driver_sql("SET LOCAL ROLE creator_b")
        assert (
            c.execute(text("SELECT to_regclass(:t)"), {"t": f"knowledge.{name}"}).scalar_one()
            is None
        )
        assert c.exec_driver_sql("SELECT current_user").scalar_one() == "synthetic_admin"


def test_member_role_defaults_do_not_substitute_for_effective_creator(
    synthetic_admin: Engine,
) -> None:
    name = "profile_future_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        c.exec_driver_sql("GRANT creator_a TO creator_b")
        c.exec_driver_sql(
            "ALTER DEFAULT PRIVILEGES FOR ROLE creator_a IN SCHEMA knowledge "
            "GRANT TRUNCATE ON TABLES TO my_pa_mcp_ro"
        )
        c.exec_driver_sql("SET LOCAL ROLE creator_b")
        spec = McpObjectGrant("knowledge", name, "creator_b", "application_read", "r", "review")
        with grant_created_mcp_object(c, spec):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{name}(id integer)")
        assert not c.execute(
            text("SELECT has_table_privilege('my_pa_mcp_ro',:t,'TRUNCATE')"),
            {"t": f"knowledge.{name}"},
        ).scalar_one()
        c.rollback()


def test_sequence_only_gets_usage_for_an_approved_writable_parent(synthetic_admin: Engine) -> None:
    table = "profile_future_" + uuid4().hex
    sequence = "profile_seq_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        c.exec_driver_sql("SET LOCAL ROLE creator_a")
        with grant_created_mcp_object(
            c, McpObjectGrant("knowledge", table, "creator_a", "application_write", "r", "review")
        ):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{table}(id integer)")
        with grant_created_mcp_object(
            c,
            McpObjectGrant(
                "knowledge",
                sequence,
                "creator_a",
                "application_write",
                "S",
                "review",
                sequence_table=("knowledge", table),
            ),
        ):
            c.exec_driver_sql(f"CREATE SEQUENCE knowledge.{sequence} OWNED BY knowledge.{table}.id")
        assert c.execute(
            text("SELECT has_sequence_privilege('my_pa_mcp_rw',:s,'USAGE')"),
            {"s": f"knowledge.{sequence}"},
        ).scalar_one()
        assert not c.execute(
            text("SELECT has_sequence_privilege('my_pa_mcp_ro',:s,'USAGE')"),
            {"s": f"knowledge.{sequence}"},
        ).scalar_one()
        assert not c.execute(
            text("SELECT has_sequence_privilege('my_pa_mcp_rw',:s,'UPDATE')"),
            {"s": f"knowledge.{sequence}"},
        ).scalar_one()
        c.rollback()


def test_excluded_new_object_with_public_column_grant_is_rolled_back(
    synthetic_admin: Engine,
) -> None:
    name = "profile_private_" + uuid4().hex
    with synthetic_admin.connect() as c, c.begin():
        spec = McpObjectGrant("knowledge", name, "synthetic_admin", "excluded", "r", "review")
        with pytest.raises(McpObjectGrantError), grant_created_mcp_object(c, spec):
            c.exec_driver_sql(f"CREATE TABLE knowledge.{name}(private_value text)")
            c.exec_driver_sql(f"GRANT SELECT(private_value) ON knowledge.{name} TO PUBLIC")
        assert (
            c.execute(text("SELECT to_regclass(:t)"), {"t": f"knowledge.{name}"}).scalar_one()
            is None
        )


def test_reused_pool_checks_the_actual_role_on_every_connection(synthetic_admin: Engine) -> None:
    from my_pa.bootstrap.mcp_database_profiles import _bind_engine

    wrong = create_engine(
        synthetic_admin.url.set(
            username="my_pa_mcp_rw",
            password="synthetic-role-fixture-0000000000000000",  # noqa: S106 - public fixture
        )
    )
    try:
        _bind_engine(
            wrong,
            synthetic_admin,
            "my_pa_mcp_ro",
            os.environ["MCP_PROFILE_TEST_CLUSTER_ID"],
            ro=True,
        )
        with pytest.raises(SettingsError, match="identity refused"), wrong.connect():
            pytest.fail("wrong-role connection must not be admitted")
    finally:
        wrong.dispose()


@pytest.mark.parametrize(
    "client,writes,profile",
    [("client-ro", True, "ro"), ("client-rw", True, "rw"), ("client-rw", False, "ro")],
)
def test_request_witness_observes_real_uow_begin_and_independent_audit_commit(
    synthetic_admin: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
    writes: bool,
    profile: str,
) -> None:
    """Observe the request's exact connection and committed row, not another pool probe."""
    import json

    from sqlalchemy import event

    import my_pa.application.service as service_module
    from my_pa.adapters.mcp.remote import RemoteAccessContext
    from my_pa.adapters.mcp.server import _answer
    from my_pa.contracts.mcp_database_witness import current_mcp_database_witness
    from my_pa.domain.capture.submission import CaptureTransport
    from my_pa.domain.identity.operation import Capability, permitted_purposes
    from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

    settings = profile_settings(tmp_path, synthetic_admin).model_copy(
        update={"mcp_database_witness_enabled": True}
    )
    control = build_gateway_runtime(settings)
    services = build_mcp_database_services(settings, control)
    assert services is not None
    seen: list[int] = []
    principal = operator()
    grants = frozenset(
        (c, p)
        for c in (Capability.CAPABILITIES_GET, Capability.CANVAS_WORKSPACE_PUT)
        for p in permitted_purposes(c)
    )
    bound = services.access(
        RemoteAccessContext(
            principal,
            authenticated_client_id=client,
            allowed_capabilities=frozenset(c.value for c, _ in grants),
            capability_purposes=grants,
        ),
        write_allowed=writes,
    )
    assert bound is not None and bound.service is not None and bound.database_witness is not None
    selected_engine = bound.database_witness.data_engine

    def observed_show(
        connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        if statement == "SHOW transaction_read_only":
            assert current_mcp_database_witness.get() is not None
            seen.append(id(connection))

    event.listen(selected_engine, "before_cursor_execute", observed_show)
    original = service_module._HANDLERS[Capability.CAPABILITIES_GET]

    def checked(*args: object) -> object:
        unit = args[1]
        assert isinstance(unit, SqlAlchemyUnitOfWork)
        assert seen == [id(unit._connection)]
        return original(*args)

    monkeypatch.setattr(
        service_module,
        "_HANDLERS",
        {
            **service_module._HANDLERS,
            Capability.CAPABILITIES_GET: checked,
        },
    )
    try:
        for _ in range(2):  # Reuse the actual pool without retaining request evidence.
            seen.clear()
            metadata: dict[str, object] = {}
            result, failed, _image = _answer(
                bound.service,
                principal,
                Capability.CAPABILITIES_GET.value,
                {},
                transport=CaptureTransport.REMOTE_CLIENT,
                allowed_capability_purposes=bound.capability_purposes,
                authenticated_client_id=client,
                database_witness=bound.database_witness,
                response_metadata=metadata,
            )
            assert not failed
            envelope = json.loads(result)
            witness = metadata["my_pa_database_witness"]
            assert witness["correlation_id"] == envelope["correlation_id"]
            assert witness["effective_profile"] == profile
            assert witness["transaction_read_only"] is (profile == "ro")
            assert witness["audit_committed"] is True
            assert witness["audit_engine_independent"] is True
            assert witness["control_engine_independent_configured"] is True
            assert current_mcp_database_witness.get() is None
            # Independent read transaction, synthetic IDs only, proves the
            # authorization event is durable after both request contexts exited.
            with synthetic_admin.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM knowledge.audit_events WHERE correlation_id=:c"),
                        {"c": envelope["correlation_id"]},
                    ).scalar_one()
                    == 1
                )
    finally:
        services.close()
        control.close()


def test_request_witness_never_acknowledges_failed_real_audit_commit(
    synthetic_admin: Engine,
    tmp_path: Path,
) -> None:
    import json

    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    from my_pa.adapters.mcp.remote import RemoteAccessContext
    from my_pa.adapters.mcp.server import _answer
    from my_pa.domain.capture.submission import CaptureTransport
    from my_pa.domain.identity.operation import Capability

    settings = profile_settings(tmp_path, synthetic_admin).model_copy(
        update={"mcp_database_witness_enabled": True}
    )
    control = build_gateway_runtime(settings)
    services = build_mcp_database_services(settings, control)
    assert services is not None
    principal = operator()
    grants = frozenset({(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION)})
    bound = services.access(
        RemoteAccessContext(
            principal,
            authenticated_client_id="client-ro",
            allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
            capability_purposes=grants,
        ),
        write_allowed=False,
    )
    assert bound is not None and bound.database_witness is not None and bound.service is not None

    def refuse_commit(_connection: object) -> None:
        raise SQLAlchemyError("synthetic commit refusal")

    event.listen(control.audit_engine, "commit", refuse_commit)
    try:
        metadata: dict[str, object] = {}
        result, failed, _image = _answer(
            bound.service,
            principal,
            Capability.CAPABILITIES_GET.value,
            {},
            transport=CaptureTransport.REMOTE_CLIENT,
            allowed_capability_purposes=grants,
            authenticated_client_id="client-ro",
            database_witness=bound.database_witness,
            response_metadata=metadata,
        )
        assert failed and not metadata
        envelope = json.loads(result)
        with synthetic_admin.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM knowledge.audit_events WHERE correlation_id=:c"),
                    {"c": envelope["correlation_id"]},
                ).scalar_one()
                == 0
            )
    finally:
        event.remove(control.audit_engine, "commit", refuse_commit)
        services.close()
        control.close()
