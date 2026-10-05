"""Compact publication profile on the existing `/mcp` resource."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import create_engine
from tests.conftest import WHEN, Scene, build_service, staged_task

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    facade_kind,
    facade_tool_names,
    feature_label,
    prepare_compact_call,
)
from my_pa.adapters.mcp.remote import (
    RemoteAccessContext,
    create_remote_mcp_app,
    remote_tool_names,
)
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    remote_tool_schema,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_security_controls,
)

RESOURCE = "https://mcp.example.invalid/mcp"
ISSUER = "https://mcp.example.invalid"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(
    scene: Scene,
    *,
    compact: bool,
    allowed: frozenset[str],
    purposes: frozenset[tuple[Capability, Purpose | None]] | None = None,
    writes_enabled: bool = False,
    operator: bool = False,
) -> object:
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            principal=scene.principal,
            allowed_capabilities=allowed,
            capability_purposes=purposes,
            relationship_grant_profile="remote.operator" if operator else None,
            compact_publication=compact,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=writes_enabled,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
    )


async def _session(app: object, exercise: Callable[..., object]) -> object:
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
        return await exercise(session)


@pytest.mark.anyio
async def test_unselected_client_keeps_canonical_tools(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    assert DESCRIBE_TOOL not in names
    assert Capability.TASKS_SEARCH.value in names
    assert Capability.CAPABILITIES_GET.value in names


@pytest.mark.anyio
async def test_selected_client_lists_only_the_facade(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    compact_names = await _session(_app(scene, compact=True, allowed=allowed), exercise)
    assert compact_names == {DESCRIBE_TOOL, READ_TOOL}
    assert Capability.TASKS_SEARCH.value not in compact_names
    assert names >= {Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value}


@pytest.mark.anyio
async def test_write_umbrella_is_omitted_when_writes_disabled(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.TASKS_CREATE.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(
        _app(scene, compact=True, allowed=allowed, writes_enabled=False),
        exercise,
    )
    assert WRITE_TOOL not in names
    assert READ_TOOL in names


@pytest.mark.anyio
async def test_write_umbrella_appears_when_an_eligible_write_exists(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_CREATE.value})
    purposes = frozenset({(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(
        _app(
            scene,
            compact=True,
            allowed=allowed,
            purposes=purposes,
            writes_enabled=True,
        ),
        exercise,
    )
    assert names == {DESCRIBE_TOOL, WRITE_TOOL}


@pytest.mark.anyio
async def test_operator_tool_requires_operator_profile(scene: Scene) -> None:
    merge = frozenset({Capability.ENTITIES_MERGE_PREVIEW.value, Capability.ENTITIES_MERGE.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    normal = await _session(
        _app(scene, compact=True, allowed=merge, writes_enabled=True, operator=False),
        exercise,
    )
    operator = await _session(
        _app(scene, compact=True, allowed=merge, writes_enabled=True, operator=True),
        exercise,
    )
    assert OPERATOR_TOOL not in normal
    assert OPERATOR_TOOL in operator


@pytest.mark.anyio
async def test_describe_and_read_round_trip(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    purposes = frozenset({(Capability.CAPABILITIES_GET, None)})

    async def exercise(session: ClientSession) -> tuple[object, object, object]:
        listed = await session.list_tools()
        described = await session.call_tool(DESCRIBE_TOOL, {})
        read = await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": {}},
        )
        return listed, described, read

    listed, described, read = await _session(
        _app(scene, compact=True, allowed=allowed, purposes=purposes),
        exercise,
    )
    names = {tool.name for tool in listed.tools}
    assert names == {DESCRIBE_TOOL, READ_TOOL}
    body = json.loads(described.content[0].text)
    assert body["profile"] == "chatllm-gateway-v1"
    assert body["items"][0]["capability"] == Capability.CAPABILITIES_GET.value
    assert read.is_error is False
    envelope = json.loads(read.content[0].text)
    assert envelope["error"] is None


@pytest.mark.anyio
async def test_describe_lookup_matches_remote_schema_and_round_trips(scene: Scene) -> None:
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    read_name = Capability.CAPABILITIES_GET.value
    write_name = Capability.TASKS_CREATE.value
    tools = {tool.name: tool for tool in TOOLS}

    async def exercise(session: ClientSession) -> tuple[object, ...]:
        described_read = await session.call_tool(DESCRIBE_TOOL, {"capability": read_name})
        described_write = await session.call_tool(DESCRIBE_TOOL, {"capability": write_name})
        read_schema = json.loads(described_read.content[0].text)["input_schema"]
        write_schema = json.loads(described_write.content[0].text)["input_schema"]
        read_args = {name: {} for name in read_schema.get("properties", {}) if name != "payload"}
        if "payload" in read_schema.get("properties", {}):
            required = read_schema["properties"]["payload"].get("required", [])
            read_args["payload"] = dict.fromkeys(required, "synthetic") if required else {}
        read = await session.call_tool(READ_TOOL, {"capability": read_name, "arguments": read_args})
        write_payload = {
            "title": "Describe schema write",
            "origin_evidence_ref": "cap_origin0001origin0001",
        }
        write = await session.call_tool(
            WRITE_TOOL,
            {"capability": write_name, "arguments": {"payload": write_payload}},
        )
        invalid = await session.call_tool(
            WRITE_TOOL,
            {"capability": write_name, "arguments": {"payload": {}}},
        )
        return described_read, described_write, read, write, invalid, read_schema, write_schema

    app = _app(
        scene,
        compact=True,
        allowed=frozenset({read_name, write_name}),
        purposes=frozenset(
            {
                (Capability.CAPABILITIES_GET, None),
                (Capability.TASKS_CREATE, Purpose.TASK_AUTHORING),
            }
        ),
        writes_enabled=True,
    )
    (
        described_read,
        described_write,
        read,
        write,
        invalid,
        read_schema,
        write_schema,
    ) = await _session(app, exercise)
    assert json.loads(described_read.content[0].text)["input_schema"] == remote_tool_schema(
        tools[read_name].input_schema
    )
    assert json.loads(described_write.content[0].text)["input_schema"] == remote_tool_schema(
        tools[write_name].input_schema
    )
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(read_schema["properties"])
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(write_schema["properties"])
    assert "idempotency_key" not in write_schema["properties"]["payload"]["properties"]
    write_payload_schema = write_schema["properties"]["payload"]["properties"]
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(write_payload_schema)
    assert read.is_error is False
    assert write.is_error is False
    assert invalid.is_error is True
    assert json.loads(invalid.content[0].text)["code"] == "invalid_request"


@pytest.mark.anyio
async def test_canonical_call_on_compact_client_is_unpublished(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> object:
        return await session.call_tool(Capability.CAPABILITIES_GET.value, {})

    result = await _session(_app(scene, compact=True, allowed=allowed), exercise)
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "unsupported"


@pytest.mark.anyio
async def test_facade_name_on_full_client_is_unpublished(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> object:
        return await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": {}},
        )

    result = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "unsupported"


@pytest.mark.anyio
async def test_protected_resource_metadata_is_unchanged(scene: Scene) -> None:
    compact = _app(
        scene,
        compact=True,
        allowed=frozenset({Capability.CAPABILITIES_GET.value}),
    )
    challenged = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: None,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        compact.router.lifespan_context(compact),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=compact), base_url="http://testserver"
        ) as client,
    ):
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        missing = await client.get("/.well-known/oauth-protected-resource/mcp/chatllm")
        missing_path = await client.post("/mcp/chatllm")
    async with (
        challenged.router.lifespan_context(challenged),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=challenged), base_url="http://testserver"
        ) as client,
    ):
        refused = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert metadata.json()["resource"] == RESOURCE
    assert refused.status_code == 401
    assert "chatllm" not in refused.headers["WWW-Authenticate"]
    assert missing.status_code == 404
    assert missing_path.status_code == 404


@pytest.mark.anyio
async def test_server_owned_fields_in_nested_arguments_still_fail(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    purposes = frozenset({(Capability.CAPABILITIES_GET, None)})

    async def exercise(session: ClientSession) -> object:
        forged = dict.fromkeys(sorted(SERVER_OWNED_REMOTE_FIELDS), "forged")
        return await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": forged},
        )

    result = await _session(
        _app(scene, compact=True, allowed=allowed, purposes=purposes),
        exercise,
    )
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "invalid_request"


def test_full_process_still_publishes_canonical_tools_when_compact_off(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    names = {tool.name for tool in published_tools(service)}
    assert DESCRIBE_TOOL not in names
    assert Capability.CAPABILITIES_GET.value in names


# ------------------------------------------------------------------ WP-MTG-06
#
# The `meetings` family on the compact profile. Every identity, grant and
# write-gate row below lives in a throwaway in-memory SQLite identity store
# built per test; nothing here reads or mutates a live profile, grant or gate.

MEETING_READS: Final = (
    Capability.MEETINGS_READ,
    Capability.MEETINGS_LIST,
    Capability.MEETINGS_SEARCH,
)
MEETING_WRITES: Final = (
    Capability.MEETINGS_CREATE,
    Capability.MEETINGS_UPDATE,
    Capability.MEETINGS_SERIES_UPDATE,
)
MEETINGS: Final = frozenset((*MEETING_READS, *MEETING_WRITES))
_WHEN: Final = datetime(2026, 9, 27, 12, tzinfo=UTC)
_SCOPE: Final = "my-pa.read"
_CLIENT_ID: Final = "synthetic-meetings-client"
_OTHER_CLIENT_ID: Final = "synthetic-other-client"
_CREATE: Final[dict[str, Any]] = {
    "title": "Synthetic compact meeting",
    "start_at": "2026-09-28T13:00:00Z",
    "timezone_name": "UTC",
}


def _exact_grants() -> tuple[tuple[Capability, Purpose, bool], ...]:
    return (
        *((capability, Purpose.MEETING_READ, False) for capability in MEETING_READS),
        *((capability, Purpose.MEETING_AUTHORING, True) for capability in MEETING_WRITES),
    )


@contextmanager
def _identity(
    *,
    global_writes: bool,
    client_writes: bool,
    grants: tuple[tuple[Capability, Purpose, bool], ...],
    other_client_grants: tuple[tuple[Capability, Purpose, bool], ...] = (),
) -> Iterator[RemoteIdentityRepository]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        connection.execute(
            remote_security_controls.insert().values(
                singleton=True, remote_enabled=True, writes_enabled=global_writes, updated_at=_WHEN
            )
        )
        repository = RemoteIdentityRepository(connection)
        for oauth_client_id, rows, writes in (
            (_CLIENT_ID, grants, client_writes),
            (_OTHER_CLIENT_ID, other_client_grants, True),
        ):
            client = repository.register_client(
                oauth_client_id=oauth_client_id,
                client_name=oauth_client_id,
                redirect_uris='["https://client.example.invalid/callback"]',
                registered_scopes=_SCOPE,
                now=_WHEN,
                writes_enabled=writes,
            )
            for capability, purpose, is_write in rows:
                repository.grant(
                    remote_client_id=client,
                    external_scope=_SCOPE,
                    capability=capability,
                    purpose=purpose,
                    resource=RESOURCE,
                    is_write=is_write,
                    now=_WHEN,
                )
        yield repository


def _resolved_app(
    scene: Scene,
    repository: RemoteIdentityRepository,
    *,
    process_writes: bool,
    oauth_client_id: str = _CLIENT_ID,
    knowledge: bool = False,
) -> object:
    """The composition root's resolution (`apps/gateway.py`), over the synthetic store."""
    service = build_service(scene.world, scene.providers, knowledge_assertions_enabled=knowledge)
    resolution = repository.authenticate(
        oauth_client_id=oauth_client_id,
        token_scopes=frozenset({_SCOPE}),
        resource=RESOURCE,
        now=_WHEN,
    )
    assert resolution is not None
    capabilities = frozenset(capability.value for capability in resolution.capabilities)
    if not resolution.write_allowed:
        capabilities &= remote_tool_names(service, writes_enabled=False)
    context = RemoteAccessContext(
        principal=scene.principal,
        authenticated_client_id=oauth_client_id,
        allowed_capabilities=capabilities,
        capability_purposes=resolution.capability_purposes,
        compact_publication=True,
    )
    return create_remote_mcp_app(
        service,
        resolve_access=lambda _authorization: context,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=process_writes,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({_SCOPE}),
    )


def _body(result: object) -> dict[str, Any]:
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


async def _discover(session: ClientSession) -> tuple[set[str], list[str], object]:
    names = {tool.name for tool in (await session.list_tools()).tools}
    described = await session.call_tool(DESCRIBE_TOOL, {"feature": "meetings"})
    items = [str(item["capability"]) for item in _body(described)["items"]]
    written = await session.call_tool(
        WRITE_TOOL,
        {"capability": Capability.MEETINGS_CREATE.value, "arguments": {"payload": _CREATE}},
    )
    return names, items, written


def test_meeting_facade_kind_and_feature_label() -> None:
    """Reads route to `my_pa.read`, the three writes to `my_pa.write` (plan D-06)."""
    for capability in MEETING_READS:
        assert facade_kind(capability) == "read"
    for capability in MEETING_WRITES:
        assert facade_kind(capability) == "write"
    for capability in MEETINGS:
        assert feature_label(capability.value) == "meetings"
    everything = frozenset(capability.value for capability in MEETINGS)
    assert facade_tool_names(everything) == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}


@pytest.mark.parametrize("capability", sorted(MEETINGS), ids=lambda c: c.value)
def test_a_meeting_capability_on_the_wrong_wrapper_is_refused(capability: Capability) -> None:
    allowed = frozenset(item.value for item in MEETINGS)
    wrapper = {"capability": capability.value, "arguments": {"payload": {}}}
    right = WRITE_TOOL if capability in MEETING_WRITES else READ_TOOL
    wrong = READ_TOOL if capability in MEETING_WRITES else WRITE_TOOL
    assert prepare_compact_call(right, wrapper, allowed_canonical=allowed)[0] == capability.value
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(wrong, wrapper, allowed_canonical=allowed)
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(OPERATOR_TOOL, wrapper, allowed_canonical=allowed)


@pytest.mark.anyio
async def test_the_wrong_wrapper_is_refused_over_the_transport(scene: Scene) -> None:
    before = dict(scene.world.meetings)

    async def exercise(session: ClientSession) -> tuple[object, object]:
        write_as_read = await session.call_tool(
            READ_TOOL,
            {"capability": Capability.MEETINGS_CREATE.value, "arguments": {"payload": _CREATE}},
        )
        read_as_write = await session.call_tool(
            WRITE_TOOL,
            {
                "capability": Capability.MEETINGS_READ.value,
                "arguments": {"payload": {"meeting_id": scene.meeting_id}},
            },
        )
        return write_as_read, read_as_write

    with _identity(global_writes=True, client_writes=True, grants=_exact_grants()) as repository:
        app = _resolved_app(scene, repository, process_writes=True)
        write_as_read, read_as_write = await _session(app, exercise)
    for refused in (write_as_read, read_as_write):
        assert refused.is_error is True  # type: ignore[attr-defined]
        assert _body(refused)["code"] == "invalid_request"
    assert scene.world.meetings == before


@pytest.mark.anyio
async def test_all_gates_and_exact_grants_publish_the_meeting_family_and_write(
    scene: Scene,
) -> None:
    before = len(scene.world.meetings)

    async def exercise(session: ClientSession) -> tuple[object, ...]:
        names, items, written = await _discover(session)
        replayed = await session.call_tool(
            WRITE_TOOL,
            {
                "capability": Capability.MEETINGS_CREATE.value,
                "arguments": {"payload": dict(reversed(list(_CREATE.items())))},
            },
        )
        looked_up = await session.call_tool(
            DESCRIBE_TOOL, {"capability": Capability.MEETINGS_CREATE.value}
        )
        return names, items, written, replayed, looked_up

    with _identity(global_writes=True, client_writes=True, grants=_exact_grants()) as repository:
        app = _resolved_app(scene, repository, process_writes=True)
        names, items, written, replayed, looked_up = await _session(app, exercise)
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    assert sorted(items) == sorted(capability.value for capability in MEETINGS)
    assert written.is_error is False, written  # type: ignore[attr-defined]
    assert replayed.is_error is False, replayed  # type: ignore[attr-defined]
    first, second = _body(written)["result"], _body(replayed)["result"]
    # Reordered object keys stamp the same server key, so the retry is a replay
    # of the one Meeting rather than a second one.
    assert first["meeting"]["meeting_id"] == second["meeting"]["meeting_id"]
    assert len(scene.world.meetings) == before + 1
    lookup = _body(looked_up)
    assert lookup["item"] == {
        "capability": Capability.MEETINGS_CREATE.value,
        "kind": "write",
        "feature": "meetings",
        "summary": lookup["item"]["summary"],
        "destructive": False,
        "idempotent": False,
    }
    payload_schema = lookup["input_schema"]["properties"]["payload"]
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(payload_schema["properties"])
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(lookup["input_schema"]["properties"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("process_writes", "global_writes", "client_writes"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
        (False, False, False),
    ],
    ids=["process-off", "global-off", "client-off", "all-off"],
)
async def test_a_meeting_write_needs_the_process_global_and_client_gates(
    scene: Scene, *, process_writes: bool, global_writes: bool, client_writes: bool
) -> None:
    before = dict(scene.world.meetings)
    with _identity(
        global_writes=global_writes, client_writes=client_writes, grants=_exact_grants()
    ) as repository:
        app = _resolved_app(scene, repository, process_writes=process_writes)
        names, items, written = await _session(app, _discover)
    assert names == {DESCRIBE_TOOL, READ_TOOL}
    assert sorted(items) == sorted(capability.value for capability in MEETING_READS)
    assert written.is_error is True  # type: ignore[attr-defined]
    assert _body(written)["code"] == "unsupported"
    assert scene.world.meetings == before


@pytest.mark.anyio
async def test_a_meeting_write_needs_its_own_exact_write_grant(scene: Scene) -> None:
    """Another Meeting write's grant, or a read-purpose grant, is not this one's."""
    before = dict(scene.world.meetings)
    reads = tuple(row for row in _exact_grants() if row[0] in MEETING_READS)
    sibling = (*reads, (Capability.MEETINGS_UPDATE, Purpose.MEETING_AUTHORING, True))
    wrong_purpose = (*reads, (Capability.MEETINGS_CREATE, Purpose.MEETING_READ, True))

    with _identity(global_writes=True, client_writes=True, grants=sibling) as repository:
        app = _resolved_app(scene, repository, process_writes=True)
        names, items, written = await _session(app, _discover)
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    assert Capability.MEETINGS_CREATE.value not in items
    assert Capability.MEETINGS_UPDATE.value in items
    assert _body(written)["code"] == "unsupported"

    with _identity(global_writes=True, client_writes=True, grants=wrong_purpose) as repository:
        app = _resolved_app(scene, repository, process_writes=True)
        _, _, misgranted = await _session(app, _discover)
    assert misgranted.is_error is True  # type: ignore[attr-defined]
    assert _body(misgranted)["code"] == "unsupported"
    assert scene.world.meetings == before


@pytest.mark.anyio
async def test_describe_lists_only_the_authenticated_clients_meeting_names(scene: Scene) -> None:
    """Two clients in one store: each sees its own grants and nothing of the other's."""
    other_rows = ((Capability.MEETINGS_SEARCH, Purpose.MEETING_READ, False),)

    async def exercise(session: ClientSession) -> tuple[list[str], object]:
        described = await session.call_tool(DESCRIBE_TOOL, {"feature": "meetings"})
        withheld = await session.call_tool(
            DESCRIBE_TOOL, {"capability": Capability.MEETINGS_READ.value}
        )
        return [str(item["capability"]) for item in _body(described)["items"]], withheld

    with _identity(
        global_writes=True,
        client_writes=True,
        grants=_exact_grants(),
        other_client_grants=other_rows,
    ) as repository:
        own = _resolved_app(scene, repository, process_writes=True)
        other = _resolved_app(
            scene, repository, process_writes=True, oauth_client_id=_OTHER_CLIENT_ID
        )
        own_items, own_lookup = await _session(own, exercise)
        other_items, other_lookup = await _session(other, exercise)
    assert sorted(own_items) == sorted(capability.value for capability in MEETINGS)
    assert _body(own_lookup)["item"]["capability"] == Capability.MEETINGS_READ.value
    assert other_items == [Capability.MEETINGS_SEARCH.value]
    assert other_lookup.is_error is True  # type: ignore[attr-defined]
    assert _body(other_lookup)["code"] == "unsupported"


@pytest.mark.anyio
async def test_a_denied_meeting_write_is_denied_after_authority_change_and_says_nothing(
    scene: Scene,
) -> None:
    """A policy denial past every gate: fixed code, fixed retry, no detail, no write."""
    marker = "MARKERCOMPACTMEETINGDENIAL"
    before = dict(scene.world.meetings)
    unauthenticated = Principal(
        principal_id=scene.principal.principal_id,
        kind=scene.principal.kind,
        authenticated=False,
    )
    grants = frozenset((capability, purpose) for capability, purpose, _ in _exact_grants())
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            principal=unauthenticated,
            allowed_capabilities=frozenset(capability.value for capability in MEETINGS),
            capability_purposes=grants,
            compact_publication=True,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({_SCOPE}),
    )

    async def exercise(session: ClientSession) -> object:
        return await session.call_tool(
            WRITE_TOOL,
            {
                "capability": Capability.MEETINGS_CREATE.value,
                "arguments": {
                    "payload": {
                        **_CREATE,
                        "title": marker,
                        "description": marker,
                        "location_text": marker,
                        "virtual_meeting_url": "https://meet.example.invalid/" + marker,
                        "attendees": [{"display_name": marker, "email": "x@example.invalid"}],
                    }
                },
            },
        )

    denied = await _session(app, exercise)
    assert denied.is_error is True  # type: ignore[attr-defined]
    text = denied.content[0].text  # type: ignore[attr-defined]
    error = json.loads(text)["error"]
    assert error["code"] == "denied"
    assert error["retry"] == "after_authority_change"
    assert error["safe_details"] == []
    assert json.loads(text)["result"] is None
    assert marker not in text
    assert "example.invalid" not in text
    assert scene.world.meetings == before


@pytest.mark.anyio
async def test_compact_task_archive_server_key_replay_and_state_no_op(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compact route stamps a stable key, and refuses caller-owned keys."""
    task = staged_task(scene)
    now = [WHEN]
    service = build_service(scene.world, scene.providers)
    monkeypatch.setattr(service, "_clock", lambda: now[0])
    assert service._tasks is not None
    monkeypatch.setattr(service._tasks, "_clock", lambda: now[0])
    capability = Capability.TASKS_UPDATE
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda _authorization: RemoteAccessContext(
            principal=scene.principal,
            allowed_capabilities=frozenset({capability.value}),
            capability_purposes=frozenset({(capability, Purpose.TASK_AUTHORING)}),
            compact_publication=True,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
    )
    initial_history_count = len(scene.world.task_history_v2)

    async def exercise(session: ClientSession) -> None:
        async def update(payload: dict) -> dict:
            result = await session.call_tool(
                WRITE_TOOL, {"capability": capability.value, "arguments": {"payload": payload}}
            )
            assert result.is_error is False, result.content
            envelope = json.loads(result.content[0].text)
            assert envelope["error"] is None
            return envelope["result"]

        payload = {"task_id": task.task_id, "expected_version": task.version, "archived": True}
        first = await update(payload)
        assert first["task"]["version"] == task.version + 1
        assert datetime.fromisoformat(first["task"]["archived_at"]) == WHEN
        first_receipt = scene.world.task_history_v2[-1]
        assert first_receipt.idempotency_key.startswith("idk_")
        now[0] += timedelta(seconds=30)
        replay = await update(payload)
        assert replay == {**first, "replayed": True}
        assert len(scene.world.task_history_v2) == initial_history_count + 1
        now[0] += timedelta(seconds=30)
        repeat = await update({**payload, "expected_version": first["task"]["version"]})
        assert repeat["history"]["outcome"] == "no_op"
        assert repeat["task"] == first["task"]
        assert scene.world.task_history_v2[-1].idempotency_key != first_receipt.idempotency_key
        now[0] += timedelta(seconds=30)
        restore_payload = {
            **payload,
            "expected_version": first["task"]["version"],
            "archived": False,
        }
        restored = await update(restore_payload)
        assert restored["task"]["archived_at"] is None
        assert restored["task"]["version"] == task.version + 2
        now[0] += timedelta(seconds=30)
        assert await update(restore_payload) == {**restored, "replayed": True}
        now[0] += timedelta(seconds=30)
        repeat_restore = await update(
            {**restore_payload, "expected_version": restored["task"]["version"]}
        )
        assert repeat_restore["history"]["outcome"] == "no_op"
        assert repeat_restore["task"] == restored["task"]
        assert len(scene.world.task_history_v2) == initial_history_count + 4
        before = tuple(scene.world.task_history_v2)
        for arguments in (
            {"payload": {**payload, "idempotency_key": "forged-key"}},
            {"payload": payload, "idempotency_key": "forged-key"},
        ):
            refused = await session.call_tool(
                WRITE_TOOL, {"capability": capability.value, "arguments": arguments}
            )
            assert refused.is_error is True
            assert json.loads(refused.content[0].text)["code"] == "invalid_request"
        assert tuple(scene.world.task_history_v2) == before
        assert scene.world.tasks_v2[0].version == task.version + 2
        assert scene.world.tasks_v2[0].archived_at is None

    await _session(app, exercise)


@pytest.mark.anyio
@pytest.mark.parametrize("guard", ["writes_disabled", "missing_grant", "wrong_purpose"])
async def test_compact_task_archive_keeps_write_authorization_guards(
    scene: Scene, guard: str
) -> None:
    task = staged_task(scene)
    before = tuple(scene.world.task_history_v2)
    allowed = (
        frozenset({Capability.CAPABILITIES_GET.value})
        if guard == "missing_grant"
        else frozenset({Capability.TASKS_UPDATE.value})
    )
    purposes = (
        frozenset({(Capability.TASKS_UPDATE, Purpose.TASK_READ)})
        if guard == "wrong_purpose"
        else frozenset({(Capability.TASKS_UPDATE, Purpose.TASK_AUTHORING)})
    )

    async def exercise(session: ClientSession) -> None:
        refused = await session.call_tool(
            WRITE_TOOL,
            {
                "capability": Capability.TASKS_UPDATE.value,
                "arguments": {
                    "payload": {
                        "task_id": task.task_id,
                        "expected_version": task.version,
                        "archived": True,
                    }
                },
            },
        )
        assert refused.is_error is True

    await _session(
        _app(
            scene,
            compact=True,
            allowed=allowed,
            purposes=purposes,
            writes_enabled=guard != "writes_disabled",
        ),
        exercise,
    )
    assert scene.world.tasks_v2 == [task]
    assert tuple(scene.world.task_history_v2) == before


# ---- KLP-WP-03 (KLP-AC-022 WP-03 slice) -------------------------------------------

KNOWLEDGE_READS: Final = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
    }
)
KNOWLEDGE: Final = KNOWLEDGE_READS | {Capability.KNOWLEDGE_ASSERTIONS_CREATE}


def _knowledge_grants() -> tuple[tuple[Capability, Purpose, bool], ...]:
    return (
        *((capability, Purpose.KNOWLEDGE_ASSERTION_READ, False) for capability in KNOWLEDGE_READS),
        (Capability.KNOWLEDGE_ASSERTIONS_CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING, True),
    )


def test_knowledge_facade_kind_and_feature_label() -> None:
    """Five reads route to `my_pa.read`, create to `my_pa.write`; no new façade tool."""
    for capability in KNOWLEDGE_READS:
        assert facade_kind(capability) == "read"
    assert facade_kind(Capability.KNOWLEDGE_ASSERTIONS_CREATE) == "write"
    for capability in KNOWLEDGE:
        assert feature_label(capability.value) == "knowledge"
    everything = frozenset(capability.value for capability in KNOWLEDGE)
    assert facade_tool_names(everything) == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_a_knowledge_capability_on_the_wrong_wrapper_is_refused(capability: Capability) -> None:
    allowed = frozenset(item.value for item in KNOWLEDGE)
    wrapper = {"capability": capability.value, "arguments": {"payload": {}}}
    write = capability is Capability.KNOWLEDGE_ASSERTIONS_CREATE
    right, wrong = (WRITE_TOOL, READ_TOOL) if write else (READ_TOOL, WRITE_TOOL)
    assert prepare_compact_call(right, wrapper, allowed_canonical=allowed)[0] == capability.value
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(wrong, wrapper, allowed_canonical=allowed)


@pytest.mark.anyio
async def test_a_knowledge_read_through_my_pa_read_is_audited_by_its_canonical_name(
    scene: Scene,
) -> None:
    """The façade adds no tool; the audit row names the canonical capability.

    The reveal names a capture-plane `asrt_` identifier, which the handler answers
    `not_found` before reaching the plane, so this FAST world needs no Knowledge
    repository to prove the routing and the audit.
    """
    scene.world.audit.clear()

    async def exercise(session: ClientSession) -> tuple[set[str], object, object]:
        names = {tool.name for tool in (await session.list_tools()).tools}
        described = await session.call_tool(DESCRIBE_TOOL, {"feature": "knowledge"})
        revealed = await session.call_tool(
            READ_TOOL,
            {
                "capability": Capability.KNOWLEDGE_ASSERTIONS_REVEAL.value,
                "arguments": {"payload": {"assertion_id": "asrt_compactgateway0001"}},
            },
        )
        return names, described, revealed

    with _identity(
        global_writes=False, client_writes=False, grants=_knowledge_grants()
    ) as repository:
        app = _resolved_app(scene, repository, process_writes=False, knowledge=True)
        names, described, revealed = await _session(app, exercise)
    assert names == {DESCRIBE_TOOL, READ_TOOL}
    items = {str(item["capability"]) for item in _body(described)["items"]}
    # Writes disabled: create is dropped at grant resolution, the reads remain.
    assert items >= {capability.value for capability in KNOWLEDGE_READS}
    assert Capability.KNOWLEDGE_ASSERTIONS_CREATE.value not in items
    assert _body(revealed)["error"]["code"] == "not_found"
    audited = [event.capability for event in scene.world.audit]
    assert Capability.KNOWLEDGE_ASSERTIONS_REVEAL in audited


@pytest.mark.anyio
async def test_knowledge_create_needs_writes_on_and_its_write_grant(scene: Scene) -> None:
    """AC-017 (WP-03 slice): writes off -> no write wrapper; on -> published."""

    async def exercise(session: ClientSession) -> tuple[set[str], set[str]]:
        names = {tool.name for tool in (await session.list_tools()).tools}
        described = await session.call_tool(DESCRIBE_TOOL, {"feature": "knowledge"})
        return names, {str(item["capability"]) for item in _body(described)["items"]}

    with _identity(global_writes=True, client_writes=True, grants=_knowledge_grants()) as repo:
        app = _resolved_app(scene, repo, process_writes=True, knowledge=True)
        names, items = await _session(app, exercise)
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    assert Capability.KNOWLEDGE_ASSERTIONS_CREATE.value in items
    with _identity(global_writes=True, client_writes=True, grants=_knowledge_grants()) as repo:
        app = _resolved_app(scene, repo, process_writes=False, knowledge=True)
        names, items = await _session(app, exercise)
    assert WRITE_TOOL not in names
    assert Capability.KNOWLEDGE_ASSERTIONS_CREATE.value not in items
