"""MCP protocol metadata through real authorization with synthetic transactions."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import suppress
from unittest.mock import MagicMock

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolResult
from sqlalchemy.exc import SQLAlchemyError
from tests.conftest import FakeUnitOfWork, Scene, build_service

import my_pa.adapters.mcp.server as server_module
import my_pa.application.service as service_module
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.server import McpAccess
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices
from my_pa.contracts.mcp_database_witness import current_mcp_database_witness
from my_pa.contracts.ports import AuditSink, UnitOfWork
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
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
        ("ro", True, True, "ro_false", None),
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
    raw_answers: list[str] = []
    original_answer = server_module._answer

    def capture_answer(*args: object, **kwargs: object) -> tuple[str, bool, object]:
        result = original_answer(*args, **kwargs)
        raw_answers.append(result[0])
        return result

    monkeypatch.setattr(server_module, "_answer", capture_answer)

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
                    read_only=(client == "ro" or not write_allowed) and failure != "ro_false",
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
        assert response.content[0].text == raw_answers[-1]
        assert response.model_dump(by_alias=True).get("structuredContent") is None
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
            assert len(response.content) == 1
        else:
            assert response.meta is not None
            assert len(response.content) == 2 and response.content[1].type == "text"
            assert json.loads(response.content[1].text) == response.meta
            assert response.content[1].text == json.dumps(
                response.meta, sort_keys=True, separators=(",", ":")
            )
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
        assert len(other.content) == 1
        # Caller cannot inject server-only eligibility or response evidence.
        forged = await session.call_tool(
            name,
            {
                **arguments,
                "database_witness": {"audit_committed": True},
            },
        )
        assert forged.is_error and forged.meta is None
        assert len(forged.content) == 1
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


def _boundary_server(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
    *,
    result_limit: int | None = None,
    timeout: float | None = None,
    release: threading.Event | None = None,
    finished: threading.Event | None = None,
) -> Server[object]:
    """Real service/SDK; synthetic transaction checkpoints isolate response bounds."""
    service = build_service(scene.world, scene.providers)
    data, control, audit = MagicMock(), MagicMock(), MagicMock()
    grants = frozenset({(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION)})
    profiles = McpDatabaseServices(
        service,
        service,
        frozenset({"ro"}),
        frozenset(),
        (data, MagicMock()),
        witness_enabled=True,
        controls_engine=control,
    )
    bound = profiles.access(
        RemoteAccessContext(
            scene.principal,
            authenticated_client_id="ro",
            allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
            capability_purposes=grants,
        ),
        write_allowed=False,
    )
    assert bound is not None
    original = service.invoke

    def invoke(*args: object, **kwargs: object) -> ResponseEnvelope:
        try:
            if release is not None:
                assert release.wait(timeout=5), "synthetic blocked work was not released"
            envelope = original(*args, **kwargs)
            witness = current_mcp_database_witness.get()
            assert witness is not None
            witness.data_begin(data, pool=data.pool, read_only=True)
            witness.audit_committed(audit, envelope.correlation_id, pool=audit.pool)
            return envelope
        finally:
            if finished is not None:
                finished.set()

    monkeypatch.setattr(service, "invoke", invoke)
    access = McpAccess(
        scene.principal,
        allowed_tools=frozenset({Capability.CAPABILITIES_GET.value}),
        allowed_capability_purposes=grants,
        transport=CaptureTransport.REMOTE_CLIENT,
        authenticated_client_id="ro",
        service=service,
        database_witness=bound.database_witness,
    )
    return server_module.create_mcp_server(
        service,
        access_for_request=lambda _: access,
        max_result_bytes=result_limit,
        call_timeout_seconds=timeout,
    )


async def _memory_status(server: Server[object]) -> CallToolResult:
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        serving = asyncio.create_task(
            server.run(
                server_streams[0],
                server_streams[1],
                server.create_initialization_options(),
            )
        )
        try:
            async with ClientSession(client_streams[0], client_streams[1]) as session:
                await session.initialize()
                return await session.call_tool(Capability.CAPABILITIES_GET.value, {})
        finally:
            serving.cancel()
            with suppress(asyncio.CancelledError):
                await serving


@pytest.mark.anyio
async def test_mirror_counts_toward_result_byte_budget_and_overflow_removes_both_channels(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = await _memory_status(_boundary_server(scene, monkeypatch))
    assert not baseline.is_error and baseline.meta is not None and len(baseline.content) == 2
    first_bytes = len(baseline.content[0].text.encode("utf-8"))
    mirror_bytes = len(baseline.content[1].text.encode("utf-8"))
    # The ordinary envelope fits, but adding the real mirror exceeds the cap.
    refused = await _memory_status(
        _boundary_server(
            scene,
            monkeypatch,
            result_limit=first_bytes + mirror_bytes - 1,
        )
    )
    assert refused.is_error and refused.meta is None and len(refused.content) == 1
    assert "my_pa_database_witness" not in refused.model_dump_json(by_alias=True)
    assert json.loads(refused.content[0].text)["code"] == "internal_error"
    # The exact combined boundary fits; no extra field or serialization overhead
    # is substituted for the existing content-byte policy.
    accepted = await _memory_status(
        _boundary_server(
            scene,
            monkeypatch,
            result_limit=first_bytes + mirror_bytes,
        )
    )
    assert not accepted.is_error and accepted.meta is not None and len(accepted.content) == 2
    assert json.loads(accepted.content[1].text) == accepted.meta


@pytest.mark.anyio
async def test_timed_out_witness_work_never_exposes_positive_mirror_or_metadata(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, finished = threading.Event(), threading.Event()
    try:
        response = await _memory_status(
            _boundary_server(
                scene,
                monkeypatch,
                timeout=0.01,
                release=release,
                finished=finished,
            )
        )
        assert response.is_error and response.meta is None and len(response.content) == 1
        assert "my_pa_database_witness" not in response.model_dump_json(by_alias=True)
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5), "synthetic work did not finish"
    # Even when the worker later succeeds, the already returned timeout stays
    # a single failure block with no positive evidence in either channel.
    assert response.meta is None and len(response.content) == 1
    assert current_mcp_database_witness.get() is None
