"""KLP-WP-03/04: how the Knowledge names meet the remote transport (FAST).

* **KLP-AC-016 (WP-03 slice)** -- `knowledge_assertion_authoring` is a
  remote-write purpose; `knowledge_assertion_read` is not.
* **KLP-AC-017 (WP-03 slice)** -- with writes disabled `knowledge.assertions.create`
  is absent from the remote tool list and refused through `my_pa.write`; the five
  reads stay published.
* **KLP-AC-103 (WP-03 slice)** -- `create` is a write and additive (its duplicate
  is a no-write return), and for all six `is_write_capability == is_remote_write`;
  the MCP annotations and the compact describe agree.
* **KLP-AC-018 (WP-03 slice)** -- the remote boundary refuses every server-owned
  Knowledge field, at the top level and inside `payload`, before choosing a
  Purpose; the remote create key is the server-stamped payload hash.

KLP-WP-04 slice A, the discovery pair:

* **KLP-AC-016 (whole)** -- `knowledge_assertion_observation` is a remote-write
  purpose too.
* **KLP-AC-017 (FAST half)** -- with writes disabled submit and checkpoint are
  absent from the remote tool list and refused through `my_pa.write`; with writes
  enabled but no grant, each is denied at the remote boundary. (Grant dropping at
  resolution is `tests/database/test_knowledge_remote_grants.py`.)
* **KLP-AC-103 (whole)** -- both are writes and *not* additive (destructive, as
  the matrix says); for all eight `is_write_capability == is_remote_write`, and
  the MCP annotations and the compact describe agree.
"""

from __future__ import annotations

import json
from typing import Final

import pytest
from tests.conftest import Scene, build_service

from my_pa.adapters.mcp.chatllm_gateway import (
    READ_TOOL,
    WRITE_TOOL,
    facade_kind,
    feature_label,
    prepare_compact_call,
    render_describe,
)
from my_pa.adapters.mcp.remote import _WRITE_PURPOSES, is_remote_write, remote_tool_names
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    KNOWLEDGE_SERVER_OWNED_FIELDS,
    compose_remote_arguments,
)
from my_pa.application.errors import InvalidRequestError, UnsupportedError
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose

CREATE: Final = Capability.KNOWLEDGE_ASSERTIONS_CREATE
READS: Final = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
    }
)
KNOWLEDGE: Final = READS | {CREATE}
PRINCIPAL: Final = Principal(
    principal_id="prn_klpwp03remote0001", kind=PrincipalKind.OPERATOR, authenticated=True
)
_PAYLOAD: Final = {
    "subject_kind": "principal",
    "subject_id": "prn_klpwp03remote0001",
    "predicate_code": "policy.requirement",
    "value": "Synthetic remote value",
}


# ---- KLP-AC-016 -----------------------------------------------------------------


def test_authoring_is_a_remote_write_purpose_and_read_is_not() -> None:
    assert Purpose.KNOWLEDGE_ASSERTION_AUTHORING in _WRITE_PURPOSES
    assert Purpose.KNOWLEDGE_ASSERTION_READ not in _WRITE_PURPOSES


# ---- KLP-AC-103 -----------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_write_classification_agrees_across_domain_remote_and_annotations(
    capability: Capability,
) -> None:
    assert is_write_capability(capability) == is_remote_write(capability)
    assert is_write_capability(capability) is (capability is CREATE)
    tool = next(tool for tool in TOOLS if tool.name == capability.value)
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is (capability is not CREATE)
    assert tool.annotations.destructive_hint is False
    assert facade_kind(capability) == ("write" if capability is CREATE else "read")
    assert feature_label(capability.value) == "knowledge"


def test_create_is_additive_because_its_duplicate_writes_nothing() -> None:
    assert is_write_capability(CREATE)
    assert not is_destructive_capability(CREATE)


def test_describe_agrees_with_the_annotations() -> None:
    allowed = frozenset(capability.value for capability in KNOWLEDGE)
    for capability in KNOWLEDGE:
        described = json.loads(
            render_describe({"capability": capability.value}, allowed_canonical=allowed)
        )
        assert described["item"]["kind"] == facade_kind(capability)
        assert described["item"]["feature"] == "knowledge"
        assert described["item"]["destructive"] is False
        assert described["annotations"]["read_only_hint"] is (capability is not CREATE)
        payload = described["input_schema"]["properties"]["payload"]["properties"]
        assert "idempotency_key" not in payload
        assert KNOWLEDGE_SERVER_OWNED_FIELDS.isdisjoint(payload)


# ---- KLP-AC-017 -----------------------------------------------------------------


def test_writes_disabled_withholds_create_and_keeps_the_reads(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers, knowledge_assertions_enabled=True)
    disabled = remote_tool_names(service, writes_enabled=False)
    enabled = remote_tool_names(service, writes_enabled=True)
    assert CREATE.value not in disabled
    assert {capability.value for capability in READS} <= disabled
    assert {capability.value for capability in KNOWLEDGE} <= enabled


def test_the_plane_off_publishes_none_of_the_six_remotely(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    names = remote_tool_names(service, writes_enabled=True)
    assert not {capability.value for capability in KNOWLEDGE} & names


def test_my_pa_write_refuses_create_when_it_is_not_eligible() -> None:
    reads_only = frozenset(capability.value for capability in READS)
    wrapper = {"capability": CREATE.value, "arguments": {"payload": _PAYLOAD}}
    with pytest.raises(Exception) as refused:
        prepare_compact_call(WRITE_TOOL, wrapper, allowed_canonical=reads_only)
    assert type(refused.value).__name__ == "UnsupportedError"
    allowed = reads_only | {CREATE.value}
    assert prepare_compact_call(WRITE_TOOL, wrapper, allowed_canonical=allowed)[0] == CREATE.value
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(READ_TOOL, wrapper, allowed_canonical=allowed)


# ---- KLP-AC-018 -----------------------------------------------------------------


@pytest.mark.parametrize("field", sorted(KNOWLEDGE_SERVER_OWNED_FIELDS))
@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_a_server_owned_knowledge_field_is_refused_remotely(
    capability: Capability, field: str
) -> None:
    grants = frozenset({(capability, next(iter(permitted_purposes(capability))))})
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=capability.value,
            arguments={"payload": {**_PAYLOAD, field: "smuggled"}},
            principal=PRINCIPAL,
            grants=grants,
        )


def test_the_remote_create_key_is_the_server_stamped_payload_hash() -> None:
    grants = frozenset({(CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING)})
    first = compose_remote_arguments(
        capability_name=CREATE.value,
        arguments={"payload": _PAYLOAD},
        principal=PRINCIPAL,
        grants=grants,
    )
    again = compose_remote_arguments(
        capability_name=CREATE.value,
        arguments={"payload": dict(reversed(list(_PAYLOAD.items())))},
        principal=PRINCIPAL,
        grants=grants,
    )
    changed = compose_remote_arguments(
        capability_name=CREATE.value,
        arguments={"payload": {**_PAYLOAD, "value": "Another value"}},
        principal=PRINCIPAL,
        grants=grants,
    )
    key = first["payload"]["idempotency_key"]
    assert key.startswith("idk_")
    assert again["payload"]["idempotency_key"] == key
    assert changed["payload"]["idempotency_key"] != key
    assert first["purpose"] == Purpose.KNOWLEDGE_ASSERTION_AUTHORING.value
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=CREATE.value,
            arguments={"payload": {**_PAYLOAD, "idempotency_key": "caller-chosen"}},
            principal=PRINCIPAL,
            grants=grants,
        )


# ---- KLP-WP-04: the discovery pair --------------------------------------------------

DISCOVERY: Final = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)
ALL_EIGHT: Final = KNOWLEDGE | DISCOVERY


def test_observation_is_a_remote_write_purpose() -> None:
    assert Purpose.KNOWLEDGE_ASSERTION_OBSERVATION in _WRITE_PURPOSES


@pytest.mark.parametrize("capability", sorted(ALL_EIGHT), ids=lambda c: c.value)
def test_for_all_eight_the_domain_and_remote_write_classifications_agree(
    capability: Capability,
) -> None:
    assert is_write_capability(capability) == is_remote_write(capability)


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_the_discovery_pair_is_a_destructive_write_everywhere(capability: Capability) -> None:
    assert is_write_capability(capability)
    assert is_destructive_capability(capability)
    tool = next(tool for tool in TOOLS if tool.name == capability.value)
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True
    assert facade_kind(capability) == "write"
    assert feature_label(capability.value) == "knowledge"
    described = json.loads(
        render_describe(
            {"capability": capability.value},
            allowed_canonical=frozenset(c.value for c in DISCOVERY),
        )
    )
    assert described["item"]["kind"] == "write"
    assert described["item"]["feature"] == "knowledge"
    assert described["item"]["destructive"] is True
    assert described["annotations"]["read_only_hint"] is False
    payload = described["input_schema"]["properties"]["payload"]["properties"]
    assert "idempotency_key" not in payload
    assert KNOWLEDGE_SERVER_OWNED_FIELDS.isdisjoint(payload)


def test_writes_disabled_withholds_the_discovery_pair(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers, knowledge_assertions_enabled=True)
    assert not {c.value for c in DISCOVERY} & remote_tool_names(service, writes_enabled=False)
    assert {c.value for c in DISCOVERY} <= remote_tool_names(service, writes_enabled=True)
    off = build_service(scene.world, scene.providers)
    assert not {c.value for c in DISCOVERY} & remote_tool_names(off, writes_enabled=True)


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_my_pa_write_refuses_the_discovery_pair_when_not_eligible(capability: Capability) -> None:
    wrapper = {"capability": capability.value, "arguments": {"payload": {}}}
    reads_only = frozenset(c.value for c in READS)
    with pytest.raises(Exception) as refused:
        prepare_compact_call(WRITE_TOOL, wrapper, allowed_canonical=reads_only)
    assert type(refused.value).__name__ == "UnsupportedError"
    eligible = reads_only | {capability.value}
    assert prepare_compact_call(WRITE_TOOL, wrapper, allowed_canonical=eligible)[0] == (
        capability.value
    )
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(READ_TOOL, wrapper, allowed_canonical=eligible)


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_writes_enabled_without_a_grant_is_denied(capability: Capability) -> None:
    other = frozenset({(CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING)})
    with pytest.raises(UnsupportedError):
        compose_remote_arguments(
            capability_name=capability.value,
            arguments={"payload": {}},
            principal=PRINCIPAL,
            grants=other,
        )


# ---- DEV-08 confirmation (Manager ruling, fix round 4) ----------------------------
#
# AC-020 says a bound client asking for `knowledge.assertions.create` or
# `review.decide` is refused; this build answers `unsupported` (DEV-08). The
# Manager accepts that token only if it is the *uniform* answer for any
# capability the caller does not hold -- so the body cannot reveal that the
# client is bound. These nodes drive the real remote surface (the composition
# root's `apps.gateway.remote_access_context`, overlay included, into
# `create_remote_mcp_app`) and compare whole `tools/call` results, correlation id
# stripped.

_DISCOVERY_CLIENT: Final = "klp-wp04-discovery-client"
_OPERATOR_REVIEW_CLIENT: Final = "klp-wp04-operator-review-client"
_UNBOUND_CLIENT: Final = "klp-wp04-unbound-client"
_NO_SUCH_CAPABILITY: Final = "knowledge.assertions.forge"
_RESOURCE: Final = "https://mcp.example.invalid/mcp"
#: Every Knowledge-facing capability, granted to every client below: the deny
#: overlay, not a missing grant row, is what must take create/review.decide away.
_EVERYTHING: Final = frozenset(
    {
        *KNOWLEDGE,
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
        Capability.RECORD_EVENTS_LIST,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
    }
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _bound_app(scene: Scene, client: str, granted: frozenset[Capability]) -> object:
    from types import SimpleNamespace

    from apps.gateway import remote_access_context

    from my_pa.adapters.mcp.remote import create_remote_mcp_app

    service = build_service(scene.world, scene.providers, knowledge_assertions_enabled=True)
    settings = SimpleNamespace(
        knowledge_discovery_oauth_client_id_set=lambda: frozenset({_DISCOVERY_CLIENT}),
        knowledge_operator_review_oauth_client_id_set=lambda: frozenset({_OPERATOR_REVIEW_CLIENT}),
        chatllm_gateway_oauth_client_id_set=frozenset,
        knowledge_manager_oauth_client_id_set=frozenset,
        compact_publication_for_client=lambda _client: False,
    )
    authenticated = SimpleNamespace(
        principal=scene.principal,
        client_id=client,
        capabilities=granted,
        capability_purposes=frozenset(
            (capability, purpose)
            for capability in granted
            for purpose in permitted_purposes(capability)
        ),
        write_allowed=True,
    )
    context = remote_access_context(settings, service, authenticated)  # type: ignore[arg-type]
    return create_remote_mcp_app(
        service,
        resolve_access=lambda _authorization: context,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource=_RESOURCE,
        authorization_servers=("https://mcp.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


async def _call(app: object, name: str) -> tuple[bool, str, dict[str, object]]:
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with (
        app.router.lifespan_context(app),  # type: ignore[attr-defined]
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        published = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool(name, {"payload": {}})
    assert len(result.content) == 1
    body = json.loads(result.content[0].text)  # type: ignore[union-attr]
    correlation = body.pop("correlation_id")
    assert isinstance(correlation, str) and correlation.startswith("corr_")
    return bool(result.is_error), json.dumps(body, sort_keys=True), {"published": published}


def _bound_cases() -> list[tuple[str, str]]:
    return [
        (_DISCOVERY_CLIENT, CREATE.value),
        (_DISCOVERY_CLIENT, Capability.REVIEW_DECIDE.value),
        (_OPERATOR_REVIEW_CLIENT, CREATE.value),
        (_OPERATOR_REVIEW_CLIENT, Capability.KNOWLEDGE_ASSERTIONS_SUBMIT.value),
    ]


@pytest.mark.anyio
async def test_a_bound_client_refusal_is_byte_identical_to_any_ungranted_capability(
    scene: Scene,
) -> None:
    """Bound create/review.decide == unbound never-granted == nonexistent name.

    Reference answers: an unbound client calling a capability it was never
    granted (`review.decide`, published remotely with writes on) and calling a
    name that is no capability at all; plus the bound clients calling a name that
    is no capability. Every one must be the same error result, body for body.
    """
    unbound_granted = frozenset({Capability.KNOWLEDGE_ASSERTIONS_READ})
    reference = await _call(
        _bound_app(scene, _UNBOUND_CLIENT, unbound_granted), Capability.REVIEW_DECIDE.value
    )
    assert reference[0] is True
    assert json.loads(reference[1])["code"] == "unsupported"
    answers = {
        ("unbound", "never_granted"): reference[:2],
        ("unbound", "no_such_capability"): (
            await _call(_bound_app(scene, _UNBOUND_CLIENT, unbound_granted), _NO_SUCH_CAPABILITY)
        )[:2],
    }
    for client in (_DISCOVERY_CLIENT, _OPERATOR_REVIEW_CLIENT):
        answers[(client, "no_such_capability")] = (
            await _call(_bound_app(scene, client, _EVERYTHING), _NO_SUCH_CAPABILITY)
        )[:2]
    for client, name in _bound_cases():
        is_error, body, seen = await _call(_bound_app(scene, client, _EVERYTHING), name)
        assert name not in seen["published"]
        answers[(client, name)] = (is_error, body)
    assert set(answers.values()) == {reference[:2]}, answers


@pytest.mark.anyio
async def test_the_uniform_refusal_is_not_the_answer_of_a_granted_call(scene: Scene) -> None:
    """Control: an unbound client *granted* create reaches the service.

    Without this the node above would also pass if every call were refused
    `unsupported` for an unrelated reason (plane off, writes off, wrong host).
    """
    reference = await _call(
        _bound_app(scene, _UNBOUND_CLIENT, frozenset({CREATE})), Capability.REVIEW_DECIDE.value
    )
    is_error, body, seen = await _call(
        _bound_app(scene, _UNBOUND_CLIENT, frozenset({CREATE})), CREATE.value
    )
    assert CREATE.value in seen["published"]
    assert (is_error, body) != reference[:2]
    assert json.loads(body)["code"] != "unsupported"
