"""Remote MCP transport controls without duplicating application policy."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from base64 import b64encode

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import Scene, build_service, staged_record, staged_search
from tests.contract.test_transport_parity import document, payloads_for

import my_pa.adapters.mcp.remote as remote_module
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app, remote_tool_names
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_remote_profile_is_deterministic_read_only(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = remote_tool_names(service, writes_enabled=False)
    assert first == remote_tool_names(service, writes_enabled=False)
    assert Capability.KNOWLEDGE_SEARCH.value in first
    assert Capability.CAPTURE_CREATE.value not in first
    assert Capability.SOURCES_ENROLL.value not in first
    assert Capability.DOCUMENTS_CREATE.value not in first


@pytest.mark.anyio
async def test_streamable_http_initializes_lists_and_invokes(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda authorization: (
            RemoteAccessContext(scene.principal) if authorization == "Bearer synthetic" else None
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        request = document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {})
        request.pop("principal_id")
        result = await session.call_tool(
            Capability.CAPABILITIES_GET.value,
            request,
        )
        forged = await session.call_tool(
            Capability.CAPABILITIES_GET.value,
            {**request, "principal_id": "prn_00000000000000000000000000000000"},
        )
    assert initialized.server_info.name == "my-pa"
    assert Capability.KNOWLEDGE_SEARCH.value in {tool.name for tool in listed.tools}
    assert Capability.CAPTURE_CREATE.value not in {tool.name for tool in listed.tools}
    capability_tool = next(
        tool for tool in listed.tools if tool.name == Capability.CAPABILITIES_GET.value
    )
    assert "principal_id" not in capability_tool.input_schema["properties"]
    assert json.loads(result.content[0].text)["error"] is None
    assert forged.is_error is True
    assert json.loads(forged.content[0].text)["code"] == "invalid_request"


@pytest.mark.anyio
async def test_health_and_disabled_readiness_are_safe(scene: Scene) -> None:
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: None,
        allowed_hosts=("testserver",),
        remote_enabled=False,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    assert ready.status_code == 503 and ready.json() == {"status": "unavailable"}


@pytest.mark.anyio
async def test_origin_publishes_metadata_and_challenges_missing_credentials(scene: Scene) -> None:
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: None,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        refused = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert metadata.status_code == 200
    assert metadata.json() == {
        "resource": "https://mcp.example.invalid/mcp",
        "authorization_servers": ["https://issuer.example.invalid"],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["my-pa.read"],
    }
    assert refused.status_code == 401
    assert refused.json() == {"error": "invalid_token"}
    assert refused.headers["WWW-Authenticate"] == (
        'Bearer resource_metadata="https://mcp.example.invalid/'
        '.well-known/oauth-protected-resource/mcp"'
    )


@pytest.mark.anyio
async def test_authenticated_client_without_grants_gets_insufficient_scope(scene: Scene) -> None:
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal, allowed_capabilities=frozenset()
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        refused = await client.post("/mcp", headers={"Authorization": "Bearer empty"})
    assert refused.status_code == 403
    assert refused.json() == {"error": "insufficient_scope"}
    assert refused.headers["WWW-Authenticate"] == (
        'Bearer error="insufficient_scope", scope="my-pa.read"'
    )


@pytest.mark.anyio
async def test_timed_out_authentication_keeps_its_capacity_slot(scene: Scene) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def slow_resolver(_authorization: str | None) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.08)
        with lock:
            active -= 1

    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=slow_resolver,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        max_concurrent_calls=1,
        call_timeout_seconds=0.01,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        responses = await asyncio.gather(*(client.post("/mcp") for _ in range(3)))
        await asyncio.sleep(0.3)
    assert {response.status_code for response in responses} == {503}
    assert peak == 1


@pytest.mark.anyio
async def test_cancelled_request_keeps_running_authentication_charged(scene: Scene) -> None:
    lock = threading.Lock()
    started = threading.Event()
    active = 0
    peak = 0

    def slow_resolver(_authorization: str | None) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        started.set()
        time.sleep(0.08)
        with lock:
            active -= 1

    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=slow_resolver,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        max_concurrent_calls=1,
        call_timeout_seconds=0.01,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        cancelled = asyncio.create_task(client.post("/mcp"))
        while not started.is_set():
            await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        responses = await asyncio.gather(*(client.post("/mcp") for _ in range(2)))
        await asyncio.sleep(0.2)
    assert {response.status_code for response in responses} == {503}
    assert peak == 1


@pytest.mark.anyio
async def test_remote_request_and_result_bounds_fail_safely(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remote_module, "MAX_REMOTE_RESULT_BYTES", 1)
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(scene.principal),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
    ):
        oversized = await http.post(
            "/mcp",
            content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"content-type": "application/json"},
        )
        async with (
            streamable_http_client("http://testserver/mcp", http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            await session.initialize()
            request = document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {})
            request.pop("principal_id")
            bounded = await session.call_tool(Capability.CAPABILITIES_GET.value, request)
    assert oversized.status_code == 413
    assert bounded.is_error is True
    assert json.loads(bounded.content[0].text)["code"] == "internal_error"


@pytest.mark.anyio
async def test_remote_write_e2e_is_idempotent_and_independently_disableable(scene: Scene) -> None:
    capability = Capability.DOCUMENTS_CREATE
    revise_capability = Capability.DOCUMENTS_REVISE
    purpose = Purpose.DOCUMENT_AUTHORING
    payload = {
        "title": "Synthetic remote document",
        "media_type": "text/markdown",
        "content": b64encode(b"# Synthetic remote document").decode("ascii"),
        "idempotency_key": "remote-document-create-0001",
    }
    request = document(capability, scene.principal.principal_id, payload)
    request.pop("principal_id")

    def application(*, writes_enabled: bool) -> object:
        return create_remote_mcp_app(
            build_service(scene.world, scene.providers),
            resolve_access=lambda _authorization: RemoteAccessContext(
                scene.principal,
                allowed_capabilities=frozenset({capability.value, revise_capability.value}),
                capability_purposes=frozenset(
                    {(capability, purpose), (revise_capability, purpose)}
                ),
            ),
            allowed_hosts=("testserver",),
            remote_enabled=True,
            writes_enabled=writes_enabled,
            resource="https://mcp.example.invalid",
            authorization_servers=("https://issuer.example.invalid",),
            scopes=frozenset({"my-pa.write"}),
        )

    async def calls(app: object) -> tuple[object, object, object, set[str]]:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Authorization": "Bearer synthetic"},
            ) as http,
            streamable_http_client("http://testserver/mcp", http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            first = await session.call_tool(capability.value, request)
            replay = await session.call_tool(capability.value, request)
            body = json.loads(first.content[0].text)
            stale_request = document(
                revise_capability,
                scene.principal.principal_id,
                {
                    "document_id": body.get("result", {})
                    .get("receipt", {})
                    .get("document_id", "mdoc_00000000000000000000000000000000"),
                    "expected_version_number": 99,
                    "title": "Synthetic stale revision",
                    "media_type": "text/markdown",
                    "content": b64encode(b"# stale").decode("ascii"),
                    "idempotency_key": "remote-document-revise-stale-0001",
                },
            )
            stale_request.pop("principal_id")
            conflict = await session.call_tool(revise_capability.value, stale_request)
            return first, replay, conflict, names

    first, replay, conflict, enabled_names = await calls(application(writes_enabled=True))
    refused, _, _, disabled_names = await calls(application(writes_enabled=False))
    first_body = json.loads(first.content[0].text)
    replay_body = json.loads(replay.content[0].text)
    assert first.is_error is False and replay.is_error is False
    first_receipt = first_body["result"]["receipt"]
    replay_receipt = replay_body["result"]["receipt"]
    assert first_receipt["created"] is True and replay_receipt["created"] is False
    assert {key: value for key, value in first_receipt.items() if key != "created"} == {
        key: value for key, value in replay_receipt.items() if key != "created"
    }
    assert conflict.is_error is True
    assert json.loads(conflict.content[0].text)["error"]["code"] == "conflict"
    assert capability.value in enabled_names
    assert capability.value not in disabled_names
    assert refused.is_error is True
    assert [event.capability for event in scene.world.audit].count(capability) == 2
    assert [event.capability for event in scene.world.audit].count(revise_capability) == 1


@pytest.mark.anyio
async def test_remote_dependency_failures_and_reconnect_are_safe(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)

    def app(*, failing_auth: bool = False, failing_ready: bool = False) -> object:
        def resolver(_authorization: str | None) -> RemoteAccessContext:
            if failing_auth:
                raise RuntimeError("synthetic auth outage")
            return RemoteAccessContext(scene.principal)

        def readiness() -> bool:
            if failing_ready:
                raise RuntimeError("synthetic database outage")
            return True

        return create_remote_mcp_app(
            service,
            resolve_access=resolver,
            readiness=readiness,
            allowed_hosts=("testserver",),
            remote_enabled=True,
            resource="https://mcp.example.invalid",
            authorization_servers=("https://issuer.example.invalid",),
            scopes=frozenset({"my-pa.read"}),
        )

    for instance in (app(), app()):
        async with (
            instance.router.lifespan_context(instance),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=instance),
                base_url="http://testserver",
                headers={"Authorization": "Bearer synthetic"},
            ) as http,
            streamable_http_client("http://testserver/mcp", http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            assert (await session.initialize()).server_info.name == "my-pa"

    for instance, expected in ((app(failing_auth=True), 401), (app(failing_ready=True), 503)):
        async with (
            instance.router.lifespan_context(instance),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=instance), base_url="http://testserver"
            ) as client,
        ):
            response = await (
                client.post("/mcp", headers={"Authorization": "Bearer synthetic"})
                if expected == 401
                else client.get("/readyz")
            )
        assert response.status_code == expected


@pytest.mark.anyio
async def test_remote_read_only_reference_client_matrix(scene: Scene) -> None:
    record = staged_record(scene, text="quarterly remote acceptance")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    payloads = payloads_for(scene, record)
    capabilities = (
        Capability.CAPABILITIES_GET,
        Capability.SOURCES_LIST,
        Capability.SOURCES_METADATA,
        Capability.SOURCES_FETCH,
        Capability.SOURCES_STATUS,
        Capability.KNOWLEDGE_SEARCH,
        Capability.KNOWLEDGE_READ,
        Capability.KNOWLEDGE_COVERAGE,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_SEARCH,
        Capability.REVIEW_LIST,
        Capability.CONTINUITY_PULSE,
        Capability.CONTINUITY_SITUATIONS,
        Capability.CONTINUITY_PROJECTS,
        Capability.DOCUMENTS_READ,
        Capability.DOCUMENTS_LIST,
    )
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=frozenset(capability.value for capability in capabilities),
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        for capability in capabilities:
            request = document(capability, scene.principal.principal_id, payloads[capability])
            request.pop("principal_id")
            answer = await session.call_tool(capability.value, request)
            assert answer.is_error is False, (capability.value, answer.content)
