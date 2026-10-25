"""MCP protocol metadata through real authorization with synthetic transactions."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.exc import SQLAlchemyError
from tests.conftest import FakeUnitOfWork, Scene, build_service

import my_pa.application.service as service_module
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices
from my_pa.contracts.mcp_database_witness import current_mcp_database_witness
from my_pa.contracts.ports import AuditSink, UnitOfWork
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize(
    "client,enabled,write_allowed,failure,expected_profile",
    [
        ("ro", True, True, None, "ro"),
        ("rw", True, True, None, "rw"),
        ("rw", True, False, None, "ro"),
        ("ro", False, True, None, None),
        ("ro", True, True, "audit_commit", None),
        ("ro", True, True, "work", None),
        ("ro", True, True, "missing_begin", None),
    ],
)
async def test_status_metadata_requires_bound_request_transaction_and_committed_audit(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
    compact: bool,
    client: str,
    enabled: bool,
    write_allowed: bool,
    failure: str | None,
    expected_profile: str | None,
) -> None:
    service = build_service(scene.world, scene.providers)
    ro, rw, control, audit = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    commits: list[bool] = []
    threads: list[int] = []
    caller_thread = threading.get_ident()

    def committed(*_args: object) -> None:
        if failure == "audit_commit":
            raise SQLAlchemyError("SYNTHETIC_PRIVATE_DRIVER_MARKER")
        commits.append(True)

    audit.begin.return_value.__exit__.side_effect = committed

    class WitnessUnitOfWork(FakeUnitOfWork):
        def __enter__(self) -> UnitOfWork:
            result = super().__enter__()
            threads.append(threading.get_ident())
            witness = current_mcp_database_witness.get()
            if witness is not None and failure != "missing_begin":
                witness.data_begin(
                    witness.binding.data_engine,
                    pool=witness.binding.data_pool,
                    read_only=client == "ro" or not write_allowed,
                )
            return result

        @property
        def audit(self) -> AuditSink:
            return SqlAlchemyAuditSink(audit)

    monkeypatch.setattr(service, "_unit_of_work", lambda: WitnessUnitOfWork(scene.world))
    if failure == "work":

        def broken(*_args: object) -> None:
            raise RuntimeError("SYNTHETIC_PRIVATE_HANDLER_MARKER")

        monkeypatch.setattr(
            service_module,
            "_HANDLERS",
            {
                **_HANDLERS,
                Capability.CAPABILITIES_GET: broken,
            },
        )
    profiles = McpDatabaseServices(
        service,
        service,
        frozenset({"ro"}),
        frozenset({"rw"}),
        (ro, rw),
        witness_enabled=enabled,
        controls_engine=control,
    )
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id=client,
        compact_publication=compact,
        allowed_capabilities=frozenset(c.value for c in Capability),
        capability_purposes=frozenset((c, p) for c in Capability for p in permitted_purposes(c)),
    )
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda _: profiles.access(context, write_allowed=write_allowed),
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        name = "my_pa.read" if compact else "capabilities.get"
        arguments = {"capability": "capabilities.get", "arguments": {}} if compact else {}
        response = await session.call_tool(name, arguments)
        rendered = response.model_dump_json(by_alias=True)
        for marker in (
            "SYNTHETIC_PRIVATE_DRIVER_MARKER",
            "SYNTHETIC_PRIVATE_HANDLER_MARKER",
            "current_user",
            "SELECT ",
            "SHOW ",
            "db.invalid",
            "client-ro",
        ):
            assert marker not in rendered
        assert current_mcp_database_witness.get() is None
        if expected_profile is None:
            assert response.meta is None
        else:
            assert response.meta is not None
            witness = response.meta["my_pa_database_witness"]
            envelope = json.loads(response.content[0].text)
            assert witness == {
                "version": 1,
                "correlation_id": envelope["correlation_id"],
                "effective_profile": expected_profile,
                "data_role_identity_match": True,
                "database_identity_match": True,
                "transaction_read_only": expected_profile == "ro",
                "audit_committed": True,
                "audit_engine_independent": True,
                "control_engine_independent_configured": True,
            }
            assert commits and all(t != caller_thread for t in threads)
        # Ordinary reads carry no witness even with server eligibility enabled.
        other = await session.call_tool(
            "my_pa.read" if compact else "sources.list",
            {"capability": "sources.list", "arguments": {}} if compact else {},
        )
        assert other.meta is None
        # Caller cannot inject server-only eligibility or response evidence.
        forged = await session.call_tool(
            name,
            {
                **arguments,
                "database_witness": {"audit_committed": True},
            },
        )
        assert forged.is_error and forged.meta is None
        assert current_mcp_database_witness.get() is None


@pytest.mark.anyio
async def test_unknown_client_cannot_forge_witness_eligibility(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(
        service,
        service,
        frozenset({"ro"}),
        frozenset({"rw"}),
        (MagicMock(), MagicMock()),
        witness_enabled=True,
        controls_engine=MagicMock(),
    )
    context = RemoteAccessContext(scene.principal, authenticated_client_id="unknown")
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda _: profiles.access(context, write_allowed=True),
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
    ):
        response = await http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "capabilities.get",
                    "arguments": {
                        "database_witness": {"effective_profile": "rw", "audit_committed": True},
                    },
                },
            },
        )
        assert response.status_code == 401
        assert "my_pa_database_witness" not in response.text
        assert current_mcp_database_witness.get() is None
