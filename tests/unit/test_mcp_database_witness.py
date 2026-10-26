"""Synthetic transaction events and commit acknowledgements; no live database."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.bootstrap import gateway, mcp_database_profiles
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices
from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.contracts.mcp_database_profiles import McpDatabaseProfile
from my_pa.contracts.mcp_database_witness import (
    McpDatabaseWitness,
    McpWitnessBinding,
    current_mcp_database_witness,
)
from my_pa.domain.audit.events import AuditEvent, AuditOutcome
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from tests.conftest import WHEN, Scene, build_service

CORRELATION = "corr_" + "a" * 32


def _event() -> AuditEvent:
    return AuditEvent(
        audit_id="audit_" + "a" * 32,
        correlation_id=CORRELATION,
        principal_id="prn_" + "a" * 32,
        capability=Capability.CAPABILITIES_GET,
        purpose=Purpose.STATUS_OBSERVATION,
        outcome=AuditOutcome.ALLOWED,
        policy_version=POLICY_VERSION,
        recorded_at=WHEN,
    )


def test_flag_is_default_off_and_requires_profiles() -> None:
    values = {"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"}
    assert not load_settings(values).mcp_database_witness_enabled
    with pytest.raises(SettingsError, match="requires database profiles"):
        load_settings({**values, "MY_PA_MCP_DATABASE_WITNESS_ENABLED": "true"})
    with pytest.raises(SettingsError):
        load_settings({**values, "MY_PA_MCP_DATABASE_WITNESS_ENABLED": "maybe"})


@pytest.mark.parametrize("shared", ["audit", "control"])
def test_injected_data_engine_cannot_be_audit_or_control(shared: str) -> None:
    settings = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})
    data, other = MagicMock(), MagicMock()
    with pytest.raises(ValueError, match="independent"):
        gateway.build_gateway_runtime(
            settings,
            data_engine=data,
            independent_audit_engine=data if shared == "audit" else other,
            controls_engine=data if shared == "control" else other,
        )


def test_default_composition_still_allows_shared_audit_and_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})
    data, shared = MagicMock(), MagicMock()
    monkeypatch.setattr(gateway, "create_database_engine", lambda *_args, **_kwargs: data)
    runtime = gateway.build_gateway_runtime(
        settings, independent_audit_engine=shared, controls_engine=shared
    )
    assert runtime.work_engine is data and runtime.audit_engine is shared


@pytest.mark.parametrize(
    "client,write_allowed,grant_write,expected",
    [
        ("ro", True, True, "ro"),
        ("rw", True, True, "rw"),
        ("rw", False, True, "ro"),
        ("rw", True, False, "ro"),
        ("unknown", True, True, None),
    ],
)
def test_only_known_bound_client_gets_effective_profile_witness(
    scene: Scene, client: str, write_allowed: bool, grant_write: bool, expected: str | None
) -> None:
    service = build_service(scene.world, scene.providers)
    ro, rw, control = MagicMock(), MagicMock(), MagicMock()
    profiles = McpDatabaseServices(
        service,
        service,
        frozenset({"ro"}),
        frozenset({"rw"}),
        (ro, rw),
        witness_enabled=True,
        controls_engine=control,
    )
    capabilities = {Capability.CAPABILITIES_GET}
    if grant_write:
        capabilities.add(Capability.CANVAS_WORKSPACE_PUT)
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id=client,
        allowed_capabilities=frozenset(c.value for c in capabilities),
        capability_purposes=frozenset((c, p) for c in capabilities for p in permitted_purposes(c)),
        # Even a previously stamped server context must be replaced, not reused.
        database_witness=McpWitnessBinding(
            McpDatabaseProfile.READ_WRITE, rw, control, rw.pool, control.pool
        ),
    )
    bound = profiles.access(context, write_allowed=write_allowed)
    if expected is None:
        assert bound is None
    else:
        assert bound is not None and bound.database_witness is not None
        assert bound.database_witness.profile.value == expected
        assert bound.database_witness.data_engine is (rw if expected == "rw" else ro)
    assert (
        profiles.access(
            replace(context, principal=replace(scene.principal, authenticated=False)),
            write_allowed=True,
        )
        is None
    )
    disabled = replace(profiles, witness_enabled=False).access(context, write_allowed=True)
    assert disabled is None or disabled.database_witness is None


def _hooks(
    monkeypatch: pytest.MonkeyPatch, *, ro: bool
) -> tuple[MagicMock, MagicMock, dict[str, Callable[[MagicMock], None]]]:
    hooks: dict[str, Callable[[MagicMock], None]] = {}

    def register(
        _engine: object, name: str
    ) -> Callable[[Callable[[MagicMock], None]], Callable[[MagicMock], None]]:
        def decorate(callback: Callable[[MagicMock], None]) -> Callable[[MagicMock], None]:
            hooks[name] = callback
            return callback

        return decorate

    monkeypatch.setattr(mcp_database_profiles.event, "listens_for", register)
    engine, control = MagicMock(), MagicMock()
    mcp_database_profiles._bind_engine(engine, control, "synthetic_role", "123", ro=ro)
    trusted = control.connect.return_value.__enter__.return_value
    trusted.exec_driver_sql.side_effect = [
        MagicMock(one=lambda: ("my_pa", "123", "10", "127.0.0.1", 5432, "170001")),
        MagicMock(scalar_one=lambda: "20"),
    ]
    return engine, control, hooks


def test_identity_probe_is_not_the_request_begin_even_with_reused_pool_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, control, hooks = _hooks(monkeypatch, ro=True)
    connection = MagicMock()
    connection.info = {"mcp_profile_identity_verified": True}
    statements: list[str] = []

    def execute(statement: str) -> MagicMock:
        statements.append(statement)
        if statement.startswith("SELECT current_database"):
            # Model the identity SELECT's autobegin, including stale pool info.
            hooks["begin"](connection)
            return MagicMock(
                one=lambda: (
                    "my_pa",
                    "synthetic_role",
                    "synthetic_role",
                    "20",
                    "10",
                    "127.0.0.1",
                    5432,
                    "170001",
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                )
            )
        return MagicMock(scalar_one=lambda: "on")

    connection.exec_driver_sql.side_effect = execute
    witness = McpDatabaseWitness(
        McpWitnessBinding(McpDatabaseProfile.READ_ONLY, engine, control, engine.pool, control.pool)
    )
    token = current_mcp_database_witness.set(witness)
    try:
        hooks["engine_connect"](connection)
        connection.rollback.assert_called_once()
        assert witness._data_begins == 0
        assert "SHOW transaction_read_only" not in statements
        # The real unit-of-work begin follows the completed identity rollback.
        hooks["begin"](connection)
        witness.audit_committed(object(), CORRELATION, pool=object())
        assert witness.metadata(CORRELATION)["my_pa_database_witness"]["transaction_read_only"]
        assert statements[-2:] == ["SET TRANSACTION READ ONLY", "SHOW transaction_read_only"]
    finally:
        current_mcp_database_witness.reset(token)
    # Same pooled info on the next request still cannot produce extra SHOW off.
    statements.clear()
    hooks["begin"](connection)
    assert statements == ["SET TRANSACTION READ ONLY"]


@pytest.mark.parametrize("ro,observed", [(True, "off"), (True, "malformed"), (False, "malformed")])
def test_bad_actual_transaction_setting_never_becomes_positive_evidence(
    monkeypatch: pytest.MonkeyPatch, ro: bool, observed: str
) -> None:
    engine, control, hooks = _hooks(monkeypatch, ro=ro)
    connection = MagicMock()
    connection.info = {"mcp_profile_identity_verified": True}
    connection.exec_driver_sql.return_value.scalar_one.return_value = observed
    witness = McpDatabaseWitness(
        McpWitnessBinding(McpDatabaseProfile.READ_ONLY, engine, control, engine.pool, control.pool)
    )
    token = current_mcp_database_witness.set(witness)
    try:
        with pytest.raises(SettingsError):
            hooks["begin"](connection)
        witness.audit_committed(object(), CORRELATION, pool=object())
        assert not witness.metadata(CORRELATION)
    finally:
        current_mcp_database_witness.reset(token)


@pytest.mark.parametrize("fail_at", [None, "insert", "commit"])
def test_audit_acknowledgement_follows_successful_commit_only(fail_at: str | None) -> None:
    data, control, audit = object(), object(), MagicMock()
    witness = McpDatabaseWitness(
        McpWitnessBinding(McpDatabaseProfile.READ_ONLY, data, control, object(), object())
    )
    witness.data_begin(data, pool=witness.binding.data_pool, read_only=True)
    transaction = audit.begin.return_value
    connection = transaction.__enter__.return_value

    def insert(_statement: object) -> None:
        assert not witness.metadata(CORRELATION)
        if fail_at == "insert":
            raise SQLAlchemyError("synthetic sensitive content")

    connection.execute.side_effect = insert
    if fail_at == "commit":
        transaction.__exit__.side_effect = SQLAlchemyError("synthetic sensitive content")
    token = current_mcp_database_witness.set(witness)
    try:
        if fail_at:
            with pytest.raises(Exception, match="could not be recorded") as error:
                SqlAlchemyAuditSink(audit).record(_event())
            assert "sensitive content" not in str(error.value)
            assert error.value.__context__ is None
            assert not witness.metadata(CORRELATION)
        else:
            SqlAlchemyAuditSink(audit).record(_event())
            transaction.__exit__.assert_called_once()
            assert witness.metadata(CORRELATION)["my_pa_database_witness"]["audit_committed"]
    finally:
        current_mcp_database_witness.reset(token)


@pytest.mark.parametrize("case", ["wrong_correlation", "same_audit", "same_control", "two_begins"])
def test_incomplete_or_ambiguous_evidence_is_closed(case: str) -> None:
    data = object()
    control = data if case == "same_control" else object()
    witness = McpDatabaseWitness(
        McpWitnessBinding(McpDatabaseProfile.READ_ONLY, data, control, object(), object())
    )
    witness.data_begin(data, pool=witness.binding.data_pool, read_only=True)
    if case == "two_begins":
        witness.data_begin(data, pool=witness.binding.data_pool, read_only=True)
    witness.audit_committed(data if case == "same_audit" else object(), CORRELATION, pool=object())
    assert not witness.metadata("corr_" + "b" * 32 if case == "wrong_correlation" else CORRELATION)


def test_executor_threads_and_pooled_engine_reuse_do_not_mix_requests() -> None:
    data, control, audit = object(), object(), object()
    barrier = Barrier(4)

    def run(index: int) -> str:
        assert current_mcp_database_witness.get() is None
        corr = f"corr_{index:032d}"
        witness = McpDatabaseWitness(
            McpWitnessBinding(McpDatabaseProfile.READ_WRITE, data, control, object(), object())
        )
        token = current_mcp_database_witness.set(witness)
        try:
            barrier.wait(timeout=5)
            current_mcp_database_witness.get().data_begin(
                data, pool=witness.binding.data_pool, read_only=index % 2 == 0
            )
            current_mcp_database_witness.get().audit_committed(audit, corr, pool=object())
            observed = witness.metadata(corr)["my_pa_database_witness"]
            assert observed["correlation_id"] == corr
            assert observed["transaction_read_only"] is (index % 2 == 0)
            return corr
        finally:
            current_mcp_database_witness.reset(token)
            assert current_mcp_database_witness.get() is None

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(run, range(12)))) == 12


@pytest.mark.parametrize("shared", ["audit", "control"])
def test_real_option_engine_shared_pool_is_rejected_without_connecting(shared: str) -> None:
    from sqlalchemy import create_engine

    settings = load_settings({"MY_PA_DATABASE_URL": "postgresql+psycopg://test@db.invalid/my_pa"})
    data = create_engine("sqlite://")
    other = create_engine("sqlite://")
    alias = data.execution_options()
    assert alias is not data and alias.pool is data.pool
    try:
        with pytest.raises(ValueError, match=r"independent.*pools"):
            gateway.build_gateway_runtime(
                settings,
                data_engine=data,
                independent_audit_engine=alias if shared == "audit" else other,
                controls_engine=alias if shared == "control" else other,
            )
    finally:
        data.dispose()
        other.dispose()


@pytest.mark.parametrize("shared", ["audit", "control"])
def test_real_option_engine_shared_pool_cannot_produce_positive_witness(shared: str) -> None:
    from sqlalchemy import create_engine

    data = create_engine("sqlite://")
    other = create_engine("sqlite://")
    alias = data.execution_options()
    control = alias if shared == "control" else other
    audit = alias if shared == "audit" else other
    assert alias is not data and alias.pool is data.pool
    witness = McpDatabaseWitness(
        McpWitnessBinding(
            McpDatabaseProfile.READ_ONLY,
            data,
            control,
            data.pool,
            control.pool,
        )
    )
    try:
        witness.data_begin(data, pool=data.pool, read_only=True)
        witness.audit_committed(audit, CORRELATION, pool=audit.pool)
        assert not witness.metadata(CORRELATION)
    finally:
        data.dispose()
        other.dispose()


def test_observed_data_pool_must_match_server_binding() -> None:
    data, control = object(), object()
    witness = McpDatabaseWitness(
        McpWitnessBinding(
            McpDatabaseProfile.READ_ONLY,
            data,
            control,
            object(),
            object(),
        )
    )
    witness.data_begin(data, pool=object(), read_only=True)
    witness.audit_committed(object(), CORRELATION, pool=object())
    assert not witness.metadata(CORRELATION)
