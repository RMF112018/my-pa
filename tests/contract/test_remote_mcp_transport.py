"""Remote MCP transport controls without duplicating application policy."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from base64 import b64decode, b64encode
from typing import Literal

import httpx2
import pytest
from apps.gateway import _remote_relationship_grant_profile
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import (
    Scene,
    build_service,
    staged_goodnotes_raster,
    staged_goodnotes_work,
    staged_record,
    staged_search,
)
from tests.contract.test_transport_parity import payloads_for

import my_pa.adapters.mcp.remote as remote_module
import my_pa.infrastructure.gsqs_routellm_transport as routellm
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app, remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.adapters.remote_request import SERVER_OWNED_REMOTE_FIELDS
from my_pa.bootstrap.relationship_intelligence_profiles import RELATIONSHIP_GRANT_PROFILES
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.purpose import Purpose


def remote_arguments(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Domain arguments only — the remote MCP caller surface after this change."""
    return {} if not payload else {"payload": dict(payload)}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_remote_profile_is_deterministic_read_only(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = remote_tool_names(service, writes_enabled=False)
    assert first == remote_tool_names(service, writes_enabled=False)
    assert Capability.KNOWLEDGE_SEARCH.value in first
    assert Capability.CAPTURE_CREATE.value not in first
    assert Capability.CONTEXT_FEEDBACK.value not in first
    assert Capability.GOODNOTES_PROPOSE.value not in first
    assert Capability.GOODNOTES_WORK.value in first
    assert Capability.GOODNOTES_CONTENT.value in first
    assert Capability.GSQS_START.value in first
    assert Capability.GSQS_STATUS.value in first
    assert Capability.CONTINUITY_PROJECTS_CREATE.value not in first
    assert Capability.SOURCES_ENROLL.value not in first
    assert Capability.DOCUMENTS_CREATE.value not in first
    assert Capability.TASKS_READ.value in first
    assert Capability.TASKS_LIST.value in first
    assert Capability.TASKS_SEARCH.value in first
    assert Capability.TASKS_HISTORY.value in first
    assert Capability.TASKS_CREATE.value not in first
    assert Capability.TASKS_UPDATE.value not in first
    assert Capability.TASKS_TRANSITION.value not in first
    assert Capability.TASKS_BULK_PREVIEW.value not in first
    assert Capability.TASKS_BULK_CONFIRM.value not in first
    enabled = remote_tool_names(service, writes_enabled=True)
    assert Capability.CAPTURE_CREATE.value in enabled
    assert Capability.CONTEXT_FEEDBACK.value in enabled
    assert Capability.GOODNOTES_PROPOSE.value in enabled
    assert Capability.CONTINUITY_PROJECTS_CREATE.value in enabled
    assert Capability.CONTINUITY_SITUATIONS_CREATE.value in enabled
    assert Capability.CONTINUITY_TASKS_CREATE.value in enabled
    assert Capability.TASKS_CREATE.value in enabled
    assert Capability.TASKS_UPDATE.value in enabled
    assert Capability.TASKS_TRANSITION.value in enabled
    assert Capability.TASKS_BULK_PREVIEW.value in enabled
    assert Capability.TASKS_BULK_CONFIRM.value in enabled
    assert Capability.SOURCES_ENROLL.value not in enabled


def test_only_an_exact_write_enabled_durable_operator_ceiling_sets_the_marker() -> None:
    operator = RELATIONSHIP_GRANT_PROFILES["remote.operator"].capabilities
    reviewer = RELATIONSHIP_GRANT_PROFILES["remote.reviewer"].capabilities

    assert _remote_relationship_grant_profile(operator, write_allowed=True) == "remote.operator"
    assert _remote_relationship_grant_profile(operator, write_allowed=False) is None
    assert _remote_relationship_grant_profile(reviewer, write_allowed=True) is None
    assert (
        _remote_relationship_grant_profile(
            operator - {Capability.ENTITIES_MERGE}, write_allowed=True
        )
        is None
    )
    assert (
        _remote_relationship_grant_profile(
            operator | {Capability.SOURCES_ENROLL}, write_allowed=True
        )
        is None
    )


@pytest.mark.anyio
async def test_remote_operator_merge_requires_both_gates_and_server_owned_grants(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    from my_pa.application.commands import GetCapabilities

    merge_capabilities = frozenset({Capability.ENTITIES_MERGE_PREVIEW, Capability.ENTITIES_MERGE})
    merge_names = frozenset(capability.value for capability in merge_capabilities)
    merge_grants = frozenset(
        (capability, Purpose.ENTITY_IDENTITY_CORRECTION) for capability in merge_capabilities
    )
    service = build_service(scene.world, scene.providers)
    original_invoke = service.invoke
    invoked: list[Capability] = []

    def synthetic_merge_invoke(metadata: object, _command: object, **kwargs: object) -> object:
        capability = metadata.capability
        assert capability in merge_capabilities
        invoked.append(capability)
        substitute = metadata.model_copy(
            update={
                "capability": Capability.CAPABILITIES_GET,
                "purpose": Purpose.STATUS_OBSERVATION,
            }
        )
        return original_invoke(substitute, GetCapabilities(), **kwargs)

    monkeypatch.setattr(service, "invoke", synthetic_merge_invoke)

    def application(
        *,
        writes_enabled: bool,
        marker: Literal["remote.operator"] | None,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = merge_grants,
    ) -> object:
        return create_remote_mcp_app(
            service,
            resolve_access=lambda _authorization: RemoteAccessContext(
                principal=scene.principal,
                allowed_capabilities=merge_names,
                capability_purposes=grants,
                relationship_grant_profile=marker,
            ),
            allowed_hosts=("testserver",),
            remote_enabled=True,
            writes_enabled=writes_enabled,
            resource="https://mcp.example.invalid",
            authorization_servers=("https://issuer.example.invalid",),
            scopes=frozenset({"my-pa.write"}),
        )

    async def exercise(app: object) -> tuple[set[str], object, object]:
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
            preview = await session.call_tool(
                Capability.ENTITIES_MERGE_PREVIEW.value,
                remote_arguments(
                    {
                        "survivor_entity_id": "ent_alice0001alice0001",
                        "expected_survivor_version": 1,
                        "merged_away": [
                            {
                                "entity_id": "ent_alice0002alice0002",
                                "expected_version": 1,
                            }
                        ],
                        "reason": "Synthetic remote operator preview.",
                    }
                ),
            )
            applied = await session.call_tool(
                Capability.ENTITIES_MERGE.value,
                remote_arguments(
                    {
                        "preview_id": "eipv_offswitch0001",
                        "preview_digest": "0" * 64,
                        "reason": "Synthetic remote operator merge.",
                    }
                ),
            )
        return names, preview, applied

    raw_names, raw_preview, _ = await exercise(application(writes_enabled=True, marker=None))
    off_names, off_preview, _ = await exercise(
        application(writes_enabled=False, marker="remote.operator")
    )
    no_purpose_names, no_purpose_preview, _ = await exercise(
        application(writes_enabled=True, marker="remote.operator", grants=frozenset())
    )
    operator_names, operator_preview, operator_apply = await exercise(
        application(writes_enabled=True, marker="remote.operator")
    )

    assert raw_names.isdisjoint(merge_names) and raw_preview.is_error is True
    assert off_names.isdisjoint(merge_names) and off_preview.is_error is True
    assert no_purpose_names >= merge_names and no_purpose_preview.is_error is True
    assert operator_names >= merge_names
    assert Capability.SOURCES_ENROLL.value not in operator_names
    assert operator_preview.is_error is False and operator_apply.is_error is False
    assert invoked == [
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
    ]


@pytest.mark.anyio
async def test_remote_gsqs_start_completes_without_a_caller_idempotency_key(
    scene: Scene,
) -> None:
    """ChatLLM's production MCP path must construct StartGsqsB0 after stamping."""
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=frozenset(
                {Capability.GSQS_START.value, Capability.GSQS_STATUS.value}
            ),
            capability_purposes=frozenset(
                {
                    (Capability.GSQS_START, Purpose.GSQS_B0_EXECUTION),
                    (Capability.GSQS_STATUS, Purpose.GSQS_B0_OBSERVATION),
                }
            ),
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=False,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    request = remote_arguments(
        {
            "authorization_id": "synthetic-b0-commissioning",
            "campaign_class": "SYNTHETIC",
            "repetition": 1,
        }
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
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert Capability.GSQS_START.value in names
        started = await session.call_tool(Capability.GSQS_START.value, request)
    assert started.is_error is False
    envelope = json.loads(started.content[0].text)
    result = envelope["result"]
    assert result["state"] in {"PREPARED", "RUNNING", "COMPLETE"}
    assert result["campaign_class"] == "SYNTHETIC"
    assert result["scoring"] == "NOT_RUN"
    assert result["gold"] == "NOT_ACCESSED"
    assert result["automatic_next_repetition"] is False


def test_canonical_tool_annotations_match_read_and_write_behavior(scene: Scene) -> None:
    tools = {
        tool.name: tool for tool in published_tools(build_service(scene.world, scene.providers))
    }
    writes = {
        Capability.SOURCES_ENROLL,
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_REVISE,
        Capability.REVIEW_DECIDE,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.CONTINUITY_TASKS_CREATE,
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_REVISE,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_RESTORE,
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_BULK_CONFIRM,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_CLOSE,
        Capability.CONTEXT_FEEDBACK,
        Capability.GOODNOTES_PROPOSE,
        Capability.GSQS_START,
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_COMMIT,
        Capability.REPORTS_RECORD_RUN_STATE,
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # Phase B's four. `entities.merge.preview` is here and the membership is
        # the one worth arguing: it mutates no canonical record and it INSERTs a
        # durable control row carrying a digest, an expiry and a consumption
        # state, so describing it as read-only would be an annotation that
        # contradicts the transaction. `tasks.bulk_preview` is the precedent and
        # is in this set for the same reason.
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
        # `RI-ENT-WP-11`'s record-family writes. Every one of them inserts,
        # supersedes or retires a row and appends the mutation-ledger row that
        # accounts for it, so none is read-only.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_END,
    }
    destructive_writes = {
        Capability.CAPTURE_REVISE,
        Capability.REVIEW_DECIDE,
        Capability.DOCUMENTS_REVISE,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_RESTORE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_CONFIRM,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_CLOSE,
        Capability.CONTEXT_FEEDBACK,
        Capability.REPORTS_COMMIT,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # Only one of Phase B's four. The two producer paths insert and never
        # reach an existing record, and the preview creates a control row and
        # mutates none; `entities.merge` redirects entities, reparents and
        # coalesces their children, supersedes self-edges and invalidates
        # dependent proposals.
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT,
        # Two of `RI-ENT-WP-11`'s three per family. A supersession mints a
        # successor *and* marks its predecessor SUPERSEDED, and a retirement
        # moves a live row to RETIRED and releases whatever slot it held; both
        # change a record that already existed. The `add`/`create` verbs insert
        # and reach nothing, which is why they are absent here and present in
        # `_ADDITIVE_WRITE_CAPABILITIES`.
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_END,
    }
    for capability in Capability:
        tool = tools.get(capability.value)
        if tool is None:
            continue
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is (capability not in writes)
        assert tool.annotations.destructive_hint is (capability in destructive_writes)
        assert tool.annotations.open_world_hint is False


def test_the_governed_merge_is_gated_on_two_axes_and_neither_is_derived_from_the_other(
    scene: Scene,
) -> None:
    """Manager ruling R-7, both halves, asserted separately.

    R-7 classifies `entities.merge.preview` a **write** from persistence
    behaviour, and its last line is the part this test exists for: the MCP
    annotation is a *separate axis* from remote write gating, and neither answer
    may be taken from the other. So both are measured here, against the two
    mechanisms that actually decide them.

    **Axis one, remote gating.** `remote_tool_names` intersects a capability's
    permitted purposes with `adapters.mcp.remote._WRITE_PURPOSES`, and both merge
    names permit `entity_identity_correction`, which is in that set. That makes
    the preview remote-write-gated because it *shares a purpose* with the apply --
    the coupling R-7 tells this package to accept rather than work around. It is
    also independently operator-gated and deliberately not left implicit:
    neither reaches an ordinary remote profile, while the exact server-resolved
    ``remote.operator`` profile can admit both. The membership is what keeps the
    write classification true after that operator gate is satisfied.

    **Axis two, the tool annotation.** `adapters.mcp.tools` derives
    `read_only_hint` from `is_write_capability` and `destructive_hint` from
    `is_destructive_capability`, which are `_WRITE_CAPABILITIES` and
    `_WRITE_CAPABILITIES - _ADDITIVE_WRITE_CAPABILITIES`. The preview is a
    non-read-only, non-destructive tool; the apply is non-read-only *and*
    destructive. Neither value is read off the remote profile and neither is read
    off the other.
    """
    from my_pa.adapters.mcp.remote import _WRITE_PURPOSES

    # Axis one, on the derivation `remote_tool_names` runs.
    for capability in (Capability.ENTITIES_MERGE_PREVIEW, Capability.ENTITIES_MERGE):
        assert permitted_purposes(capability) == frozenset({Purpose.ENTITY_IDENTITY_CORRECTION})
        assert permitted_purposes(capability) & _WRITE_PURPOSES
        assert is_operator_only(capability)
    service = build_service(scene.world, scene.providers)
    for writes_enabled in (False, True):
        remote = remote_tool_names(service, writes_enabled=writes_enabled)
        assert Capability.ENTITIES_MERGE_PREVIEW.value not in remote
        assert Capability.ENTITIES_MERGE.value not in remote

    # Axis two, on the tool list the local transport publishes.
    tools = {tool.name: tool for tool in published_tools(service)}
    preview = tools[Capability.ENTITIES_MERGE_PREVIEW.value]
    apply = tools[Capability.ENTITIES_MERGE.value]
    assert preview.annotations is not None and apply.annotations is not None
    assert preview.annotations.read_only_hint is False
    assert preview.annotations.destructive_hint is False
    assert apply.annotations.read_only_hint is False
    assert apply.annotations.destructive_hint is True
    # And the two answers are not the same answer, which is what "separate axis"
    # has to mean to be checkable: one capability, two gates, two verdicts.
    assert preview.annotations.destructive_hint != apply.annotations.destructive_hint


def test_the_two_producer_paths_are_additive_writes_on_both_axes(scene: Scene) -> None:
    """The other half of the four, and the axis that separates them from the merge.

    A proposal is a write of a *request*: it inserts and can reach no existing
    record, which is what puts both names in `_ADDITIVE_WRITE_CAPABILITIES` and
    what makes `destructive_hint` false for each. On the remote axis they are
    write-gated and, unlike the merge, are *reachable* once remote writes are
    enabled -- neither is operator-only, because operator section 16 gives a
    producer client both.
    """
    from my_pa.adapters.mcp.remote import _WRITE_PURPOSES

    service = build_service(scene.world, scene.providers)
    tools = {tool.name: tool for tool in published_tools(service)}
    for capability, purpose in (
        (Capability.ENTITIES_PROPOSALS_CREATE, Purpose.ENTITY_PROPOSAL),
        (Capability.RELATIONSHIP_MEMORY_PROPOSE, Purpose.RELATIONSHIP_MEMORY_PROPOSAL),
    ):
        assert permitted_purposes(capability) == frozenset({purpose})
        assert purpose in _WRITE_PURPOSES
        assert not is_operator_only(capability)
        annotations = tools[capability.value].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False
        assert capability.value not in remote_tool_names(service, writes_enabled=False)
        assert capability.value in remote_tool_names(service, writes_enabled=True)


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
        result = await session.call_tool(Capability.CAPABILITIES_GET.value, remote_arguments())
        forged = await session.call_tool(
            Capability.CAPABILITIES_GET.value,
            {**remote_arguments(), "principal_id": "prn_00000000000000000000000000000000"},
        )
    assert initialized.server_info.name == "my-pa"
    assert Capability.KNOWLEDGE_SEARCH.value in {tool.name for tool in listed.tools}
    assert Capability.CAPTURE_CREATE.value not in {tool.name for tool in listed.tools}
    capability_tool = next(
        tool for tool in listed.tools if tool.name == Capability.CAPABILITIES_GET.value
    )
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(capability_tool.input_schema["properties"])
    assert capability_tool.annotations is not None
    assert capability_tool.annotations.read_only_hint is True
    assert capability_tool.annotations.destructive_hint is False
    assert capability_tool.annotations.open_world_hint is False
    assert capability_tool.meta == {
        "securitySchemes": [{"type": "oauth2", "scopes": ["my-pa.read"]}]
    }
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
        'Bearer resource_metadata="https://mcp.example.invalid/'
        '.well-known/oauth-protected-resource", error="insufficient_scope", '
        'error_description="No approved MCP capability grant is active", scope="my-pa.read"'
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
            bounded = await session.call_tool(Capability.CAPABILITIES_GET.value, remote_arguments())
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
    }
    request = remote_arguments(payload)

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
            stale_request = remote_arguments(
                {
                    "document_id": body.get("result", {})
                    .get("receipt", {})
                    .get("document_id", "mdoc_00000000000000000000000000000000"),
                    "expected_version_number": 99,
                    "title": "Synthetic stale revision",
                    "media_type": "text/markdown",
                    "content": b64encode(b"# stale").decode("ascii"),
                }
            )
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
async def test_remote_project_create_is_visible_on_continuity_projects(scene: Scene) -> None:
    create = Capability.CONTINUITY_PROJECTS_CREATE
    listing = Capability.CONTINUITY_PROJECTS
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=frozenset({create.value, listing.value}),
            capability_purposes=frozenset(
                {
                    (create, Purpose.CONTINUITY_AUTHORING),
                    (listing, Purpose.CAPTURE_REVIEW),
                }
            ),
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
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
        names = {tool.name for tool in (await session.list_tools()).tools}
        created = await session.call_tool(
            create.value, remote_arguments({"name": "MCP Write Acceptance Test"})
        )
        listed = await session.call_tool(listing.value, remote_arguments({"page_size": 20}))
        forged = await session.call_tool(
            create.value,
            {
                **remote_arguments({"name": "Should not land"}),
                "principal_id": "prn_00000000000000000000000000000000",
            },
        )
    assert create.value in names
    assert Capability.SOURCES_ENROLL.value not in names
    assert created.is_error is False
    body = json.loads(created.content[0].text)
    assert body["result"]["name"] == "MCP Write Acceptance Test"
    listed_body = json.loads(listed.content[0].text)
    assert "MCP Write Acceptance Test" in [row["name"] for row in listed_body["result"]["projects"]]
    assert forged.is_error is True
    assert json.loads(forged.content[0].text)["code"] == "invalid_request"


@pytest.mark.anyio
async def test_remote_task_create_is_visible_on_tasks_list(scene: Scene) -> None:
    create = Capability.TASKS_CREATE
    listing = Capability.TASKS_LIST
    reading = Capability.TASKS_READ
    # The write contract admits only evidence already accepted for this
    # Principal. The fake models that durable admission explicitly; production
    # validation remains unchanged and is exercised by the application tests.
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=frozenset({create.value, listing.value, reading.value}),
            capability_purposes=frozenset(
                {
                    (create, Purpose.TASK_AUTHORING),
                    (listing, Purpose.TASK_READ),
                    (reading, Purpose.TASK_READ),
                }
            ),
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
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
        names = {tool.name for tool in (await session.list_tools()).tools}
        created = await session.call_tool(
            create.value,
            remote_arguments(
                {
                    "title": "MCP task write acceptance",
                    "origin_evidence_ref": "cap_origin0001origin0001",
                }
            ),
        )
        listed = await session.call_tool(listing.value, remote_arguments({"page_size": 20}))
        forged = await session.call_tool(
            create.value,
            {
                **remote_arguments(
                    {
                        "title": "Should not land",
                        "origin_evidence_ref": "cap_origin0001origin0001",
                    }
                ),
                "principal_id": "prn_00000000000000000000000000000000",
            },
        )
    assert {create.value, listing.value, reading.value} <= names
    assert created.is_error is False
    body = json.loads(created.content[0].text)
    title = body["result"]["task"]["title"]
    assert title == "MCP task write acceptance"
    listed_body = json.loads(listed.content[0].text)
    assert title in [row["title"] for row in listed_body["result"]["tasks"]]
    assert forged.is_error is True
    assert json.loads(forged.content[0].text)["code"] == "invalid_request"


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
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
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
            request = remote_arguments(payloads[capability])
            answer = await session.call_tool(capability.value, request)
            assert answer.is_error is False, (capability.value, answer.content)


def _continuity_app(scene: Scene) -> object:
    capabilities = (
        Capability.CAPABILITIES_GET,
        Capability.CONTINUITY_PULSE,
        Capability.CONTINUITY_SITUATIONS,
        Capability.CONTINUITY_PROJECTS,
    )
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=frozenset(capability.value for capability in capabilities),
            capability_purposes=frozenset(
                {
                    (Capability.CAPABILITIES_GET, None),
                    (Capability.CONTINUITY_PULSE, Purpose.CAPTURE_REVIEW),
                    (Capability.CONTINUITY_SITUATIONS, Purpose.CAPTURE_REVIEW),
                    (Capability.CONTINUITY_PROJECTS, Purpose.CAPTURE_REVIEW),
                }
            ),
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


@pytest.mark.anyio
async def test_chatllm_legacy_metadata_is_rejected_not_merged(scene: Scene) -> None:
    """The production ChatLLM continuity.projects shape is no longer accepted."""
    app = _continuity_app(scene)
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
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
        schema = listed["continuity.projects"].input_schema
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(schema["properties"])
        answer = await session.call_tool(
            Capability.CONTINUITY_PROJECTS.value,
            {
                "purpose": "Retrieve the user's current projects from their personal assistant",
                "request_id": "projects-list-003",
                "requested_at": "2026-08-15T00:00:00Z",
                "payload": {"page_size": 20},
                "scope": {"source_ids": [], "enrollment_ids": []},
            },
        )
    assert answer.is_error is True
    assert json.loads(answer.content[0].text)["code"] == "invalid_request"


@pytest.mark.anyio
async def test_chatllm_domain_only_continuity_calls_succeed(scene: Scene) -> None:
    app = _continuity_app(scene)
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
        initialized = await session.initialize()
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
        projects = await session.call_tool(
            Capability.CONTINUITY_PROJECTS.value, remote_arguments({"page_size": 20})
        )
        situations = await session.call_tool(
            Capability.CONTINUITY_SITUATIONS.value, remote_arguments({"page_size": 20})
        )
        pulse = await session.call_tool(Capability.CONTINUITY_PULSE.value, remote_arguments())
        capabilities = await session.call_tool(
            Capability.CAPABILITIES_GET.value, remote_arguments()
        )
    assert initialized.server_info.name == "my-pa"
    for name in (
        "continuity.projects",
        "continuity.situations",
        "continuity.pulse",
        "capabilities.get",
    ):
        assert name in listed
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(listed[name].input_schema["properties"])
        assert "Purpose" not in listed[name].input_schema.get("$defs", {})
    for answer in (projects, situations, pulse, capabilities):
        body = json.loads(answer.content[0].text)
        assert answer.is_error is False
        assert body["error"] is None
        assert body["disclosure"] is not None
        assert body["request_id"]
        assert body["correlation_id"]


def _image_blocks(result: object) -> list:
    return [b for b in result.content if getattr(b, "type", None) == "image"]


def _assert_text_only(result: object) -> None:
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert _image_blocks(result) == []


def _content_payload(scene: Scene) -> dict[str, object]:
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    return {
        "run_id": raster.run_id,
        "page_version_id": raster.page_version_id,
        "content_sha256": work.content_sha256,
    }


def _propose_payload(scene: Scene) -> dict[str, object]:
    work = staged_goodnotes_work(scene)
    return {
        "run_id": work.run_id,
        "page_version_id": work.page_version_id,
        "content_sha256": work.content_sha256,
        "schema_version": "note-unit.v1",
        "analyzer_name": "synthetic",
        "analyzer_version": "1",
        "segments": [
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                "transcription": "synthetic note",
                "primary_class": "MEETING",
            }
        ],
    }


def _goodnotes_remote_app(
    scene: Scene,
    *,
    writes_enabled: bool = False,
    remote_enabled: bool = True,
    allowed: frozenset[str] | None = None,
    purposes: frozenset[tuple[Capability, Purpose | None]] | None = None,
) -> object:
    work, content, propose = (
        Capability.GOODNOTES_WORK,
        Capability.GOODNOTES_CONTENT,
        Capability.GOODNOTES_PROPOSE,
    )
    if allowed is None:
        allowed = frozenset({work.value, content.value, propose.value})
    if purposes is None:
        purposes = frozenset(
            {
                (work, Purpose.GOODNOTES_WORK),
                (content, Purpose.GOODNOTES_CONTENT),
                (propose, Purpose.GOODNOTES_PROPOSAL),
            }
        )
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=allowed,
            capability_purposes=purposes,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=remote_enabled,
        writes_enabled=writes_enabled,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


@pytest.mark.anyio
async def test_authorized_goodnotes_content_carries_image_over_streamable_http(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A granted remote content call binds ImageContent to the envelope PNG."""
    invoked: list[object] = []

    def forbidden(*_args: object, **_kwargs: object) -> object:
        invoked.append((_args, _kwargs))
        raise AssertionError("RouteLLM HTTP must not be invoked")

    monkeypatch.setattr(routellm, "post_chat_completion", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    app = _goodnotes_remote_app(scene, writes_enabled=False)
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
        initialized = await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool(
            Capability.GOODNOTES_CONTENT.value, remote_arguments(_content_payload(scene))
        )
    assert initialized.server_info.name == "my-pa"
    assert Capability.GOODNOTES_WORK.value in names
    assert Capability.GOODNOTES_CONTENT.value in names
    assert Capability.GOODNOTES_PROPOSE.value not in names
    assert result.is_error is False
    assert result.content[0].type == "text"
    envelope = json.loads(result.content[0].text)
    payload = envelope["result"]
    assert payload["media_type"] == "image/png"
    assert payload["exact_render_sha256"]
    assert "path" not in payload
    assert len(result.content) == 2
    image = result.content[1]
    assert image.type == "image"
    assert image.mime_type == "image/png"
    assert payload["content_base64"] == image.data
    png = b64decode(image.data)
    assert png.startswith(b"\x89PNG")
    assert hashlib.sha256(png).hexdigest() == payload["digest"]
    assert len(png) == payload["byte_length"]
    assert getattr(result, "structured_content", None) is None
    assert invoked == []


@pytest.mark.anyio
async def test_remote_propose_is_available_only_when_writes_enabled_and_granted(
    scene: Scene,
) -> None:
    """Read-only remote omits propose; a write profile with a grant serves it without an image."""
    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    request = remote_arguments(_propose_payload(scene))

    async def run(app: object) -> tuple[object, set[str]]:
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
            proposed = await session.call_tool(Capability.GOODNOTES_PROPOSE.value, request)
            return proposed, names

    read_only = _goodnotes_remote_app(scene, writes_enabled=False)
    writable = _goodnotes_remote_app(scene, writes_enabled=True)
    ungranted = _goodnotes_remote_app(
        scene,
        writes_enabled=True,
        allowed=frozenset({Capability.GOODNOTES_WORK.value, Capability.GOODNOTES_CONTENT.value}),
        purposes=frozenset(
            {
                (Capability.GOODNOTES_WORK, Purpose.GOODNOTES_WORK),
                (Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_CONTENT),
            }
        ),
    )
    refused, disabled_names = await run(read_only)
    accepted, enabled_names = await run(writable)
    withheld, withheld_names = await run(ungranted)

    assert Capability.GOODNOTES_PROPOSE.value not in disabled_names
    assert refused.is_error is True
    _assert_text_only(refused)

    assert Capability.GOODNOTES_PROPOSE.value in enabled_names
    assert accepted.is_error is False
    _assert_text_only(accepted)
    assert json.loads(accepted.content[0].text)["result"]["proposal_id"]

    assert Capability.GOODNOTES_PROPOSE.value not in withheld_names
    assert withheld.is_error is True
    _assert_text_only(withheld)


@pytest.mark.anyio
async def test_remote_content_oversize_is_an_internal_error_without_an_image(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The remote result ceiling counts the image block and refuses it as text."""
    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    monkeypatch.setattr(remote_module, "MAX_REMOTE_RESULT_BYTES", 1)
    app = _goodnotes_remote_app(scene)
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
        oversized = await session.call_tool(
            Capability.GOODNOTES_CONTENT.value, remote_arguments(_content_payload(scene))
        )
    assert oversized.is_error is True
    assert json.loads(oversized.content[0].text)["code"] == "internal_error"
    _assert_text_only(oversized)


@pytest.mark.anyio
async def test_remote_content_failures_do_not_carry_an_image(scene: Scene) -> None:
    """A digest mismatch, missing grant, unknown tool, and disabled surface stay text-only."""
    staged_goodnotes_work(scene)
    staged_goodnotes_raster(scene)
    payload = _content_payload(scene)
    mismatch_app = _goodnotes_remote_app(scene)
    missing_grant_app = _goodnotes_remote_app(
        scene,
        allowed=frozenset({Capability.GOODNOTES_WORK.value}),
        purposes=frozenset({(Capability.GOODNOTES_WORK, Purpose.GOODNOTES_WORK)}),
    )
    disabled_app = _goodnotes_remote_app(scene, remote_enabled=False)

    async with (
        mismatch_app.router.lifespan_context(mismatch_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=mismatch_app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        mismatch = await session.call_tool(
            Capability.GOODNOTES_CONTENT.value,
            remote_arguments({**payload, "content_sha256": "b" * 64}),
        )
        unknown = await session.call_tool("sources.destroy", remote_arguments())
    assert mismatch.is_error is True
    _assert_text_only(mismatch)
    assert unknown.is_error is True
    _assert_text_only(unknown)

    async with (
        missing_grant_app.router.lifespan_context(missing_grant_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=missing_grant_app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        ungranted = await session.call_tool(
            Capability.GOODNOTES_CONTENT.value, remote_arguments(payload)
        )
    assert Capability.GOODNOTES_CONTENT.value not in names
    assert ungranted.is_error is True
    _assert_text_only(ungranted)

    async with (
        disabled_app.router.lifespan_context(disabled_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=disabled_app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
    ):
        ready = await http.get("/readyz")
        async with (
            streamable_http_client("http://testserver/mcp", http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            await session.initialize()
            disabled = await session.call_tool(
                Capability.GOODNOTES_CONTENT.value, remote_arguments(payload)
            )
    assert ready.status_code == 503
    assert disabled.is_error is True
    _assert_text_only(disabled)
