"""Exact-client publication proof only; no canonical operation is executed."""

from types import SimpleNamespace

import pytest
from apps.gateway import remote_access_context
from tests.conftest import Scene
from tests.contract.test_chatllm_mcp_gateway import RESOURCE, _session

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.adapters.mcp.remote import create_remote_mcp_app, is_remote_write, remote_tool_names
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

CLIENT = "synthetic-personal-chatgpt"
ALL = frozenset(Capability)


def _settings(*, selected: bool = True, enabled: bool = True) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://localhost/synthetic_my_pa",
        mcp_chatllm_gateway_enabled=enabled,
        mcp_chatllm_gateway_oauth_client_ids=CLIENT,
        mcp_chatllm_operator_oauth_client_ids=CLIENT if selected else "",
        knowledge_manager_oauth_client_ids=CLIENT,
        knowledge_checkpoint_signing_key="synthetic-checkpoint-key-000000000000",
    )


def _context(
    scene: Scene,
    *,
    client: str = CLIENT,
    selected: bool = True,
    writes: bool = True,
    grants: frozenset[Capability] = ALL,
) -> object:
    return remote_access_context(
        _settings(selected=selected),
        SimpleNamespace(available_capabilities=ALL),  # type: ignore[arg-type]
        SimpleNamespace(
            principal=scene.principal,
            client_id=client,
            capabilities=grants,
            capability_purposes=frozenset((c, p) for c in grants for p in permitted_purposes(c)),
            write_allowed=writes,
        ),  # type: ignore[arg-type]
    )


@pytest.mark.anyio
async def test_full_inventory_catalog_without_execution(scene: Scene) -> None:
    service = SimpleNamespace(available_capabilities=ALL)
    context = _context(scene)
    app = create_remote_mcp_app(
        service,  # type: ignore[arg-type]
        resolve_access=lambda _header: context,  # type: ignore[return-value]
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource=RESOURCE,
        authorization_servers=("https://mcp.example.invalid",),
    )

    async def exercise(session: object) -> set[str]:
        import json

        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == {"my_pa.describe", "my_pa.read", "my_pa.write", "my_pa.operator"}
        capabilities: set[str] = set()
        cursor = None
        while True:
            args = {"limit": 100}
            if cursor is not None:
                args["cursor"] = cursor
            response = await session.call_tool("my_pa.describe", args)
            page = json.loads(response.content[0].text)
            capabilities.update(row["capability"] for row in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return capabilities

    names = await _session(app, exercise)
    # Record lineage S3: the operator-only backfill pair is never remotely
    # published (local CLI only, S3 contract sections 6.1 and 8.3).
    assert names == {c.value for c in ALL} - {
        Capability.RECORDS_BACKFILL_PLAN.value,
        Capability.RECORDS_BACKFILL_REPORT.value,
        # Record lineage S3.1 (S3.1 contract section 7.13): Issue close and
        # reopen and the 3 confirms are operator-only -- attested to the local
        # operator surface -- so they are never remotely published either.
        Capability.ISSUES_CLOSE.value,
        Capability.ISSUES_REOPEN.value,
        Capability.RECORDS_ASSOCIATIONS_CONFIRM.value,
        Capability.ISSUES_MEMBERSHIPS_CONFIRM.value,
        Capability.ISSUES_PROJECT_LINKS_CONFIRM.value,
    }
    # The deployed 190 remain individually present after main added report types
    # and record lineage S1 added the `issues.`, `records.` and `meetings.notes.` names.
    deployed = {
        c.value
        for c in ALL
        if not c.value.startswith(("reports.types.", "issues.", "records.", "meetings.notes."))
        # Record lineage S4's seven Program-reporting names are not deployed either.
        and c.value not in PROGRAM_REPORTING_CAPABILITIES
    }
    assert len(deployed) == 190
    assert deployed <= names


@pytest.mark.parametrize("selected,client", [(False, CLIENT), (True, "synthetic-other")])
def test_operator_ceiling_is_exact_and_default_closed(
    scene: Scene, selected: bool, client: str
) -> None:
    context = _context(scene, selected=selected, client=client)
    assert not context.compact_operator_publication
    names = remote_tool_names(SimpleNamespace(available_capabilities=ALL), writes_enabled=True)
    assert not any(is_operator_only(Capability(name)) for name in names)


def test_configuration_requires_exact_compact_membership() -> None:
    assert not Settings(
        database_url="postgresql+psycopg://localhost/synthetic_my_pa"
    ).compact_operator_publication_for_client(CLIENT)
    assert not _settings(enabled=False).compact_operator_publication_for_client(CLIENT)
    assert not _settings().compact_operator_publication_for_client(CLIENT + "-suffix")
    with pytest.raises(ValueError, match="must be a subset"):
        Settings(
            database_url="postgresql+psycopg://localhost/synthetic_my_pa",
            mcp_chatllm_operator_oauth_client_ids=CLIENT,
        )


def test_missing_grant_and_client_write_gate_are_preserved(scene: Scene) -> None:
    missing = ALL - {Capability.SOURCES_ENROLL}
    context = _context(scene, grants=missing)
    assert Capability.SOURCES_ENROLL.value not in context.allowed_capabilities
    readonly = _context(scene, writes=False)
    assert not any(is_remote_write(Capability(name)) for name in readonly.allowed_capabilities)


def test_process_write_gate_withholds_every_write_and_operator() -> None:
    names = remote_tool_names(
        SimpleNamespace(available_capabilities=ALL),
        writes_enabled=False,
        compact_operator_publication=True,
    )
    assert not any(is_remote_write(Capability(name)) for name in names)
    assert not any(is_operator_only(Capability(name)) for name in names)


@pytest.mark.parametrize(
    "capability", [Capability.GOODNOTES_PULL, Capability.GOODNOTES_COMPLETE, Capability.GSQS_START]
)
def test_effectful_protocol_calls_use_write_wrapper(capability: Capability) -> None:
    assert is_remote_write(capability)
    assert facade_kind(capability) == "write"


def test_every_canonical_write_remains_remote_write_gated() -> None:
    for capability in Capability:
        if is_write_capability(capability):
            assert is_remote_write(capability), capability.value


def test_payload_cannot_select_operator_ceiling() -> None:
    from my_pa.adapters.mcp.chatllm_gateway import prepare_compact_call
    from my_pa.application.errors import InvalidRequestError

    with pytest.raises(InvalidRequestError):
        prepare_compact_call(
            "my_pa.operator",
            {
                "capability": "sources.enroll",
                "arguments": {},
                "compact_operator_publication": True,
                "authenticated_client_id": CLIENT,
            },
            allowed_canonical=frozenset(c.value for c in ALL),
        )
