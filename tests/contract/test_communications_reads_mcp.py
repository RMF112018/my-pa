"""WP4-S5: `communications.search`, `.read` and `.coverage` at the canonical boundary (FAST).

Communications contract section 16, Manager rulings D7, D8, R11-R13, C2: the
3 names are declared, dispatched, built and published as reads
(`read_only_hint`) under `communications_read` only; scopeless and not
operator-only; `DATA_CONDITIONAL` on the `COMMUNICATIONS` prerequisite at
`chatllm-data-v17`. With `MY_PA_COMMUNICATIONS_ENABLED` off (the default)
every one is withheld from `capabilities.get` and the tool list and answers
the standard `unsupported`, never an empty result. On, the answers carry the
versions and the coverage; a cursor of another Principal or another request
is `conflict` `cursor`; a changed grant set answers `cursor_state:
scope_changed_restart_required`; and refusals name only SafeDetail tokens.
Every value is synthetic. The database evidence of the reads themselves is
`tests/database/test_communications_search.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final, get_args

import pytest
from tests.communications_reads_samples import (
    COMMUNICATIONS_READ_CAPABILITIES,
    communications_payloads,
)
from tests.conftest import DEFAULT_LIMITS, Scene, build_service
from tests.contract.test_transport_parity import document
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import IngestUnitOfWork, IngestWorld
from tests.unit.test_communications_ingest import P, at, pub
from tests.unit.test_communications_ingest import Scene as IngestScene

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
)
from my_pa.application.commands import (
    Command,
    CommunicationsCoverage,
    ReadCommunications,
    SearchCommunications,
)
from my_pa.application.errors import ErrorCode, InvalidRequestError, SafeDetail
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.ports import CommunicationSearchQueryShape, CommunicationSearchRow
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    COMMUNICATIONS_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS

SEARCH: Final = Capability.COMMUNICATIONS_SEARCH
READ: Final = Capability.COMMUNICATIONS_READ
COVERAGE: Final = Capability.COMMUNICATIONS_COVERAGE
READS: Final = (SEARCH, READ, COVERAGE)
NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
WHEN: Final = datetime(2026, 11, 17, 12, tzinfo=UTC)
OPERATOR: Final = Principal(P, PrincipalKind.OPERATOR, authenticated=True)
STRANGER: Final = Principal("prn_commsstranger0001", PrincipalKind.OPERATOR, authenticated=True)
GRANTS: Final = frozenset((capability, Purpose.COMMUNICATIONS_READ) for capability in READS)


# ---- declaration, policy and publication ---------------------------------------------------


def test_the_three_are_declared_dispatched_built_and_published_as_reads() -> None:
    assert [c.value for c in READS] == [
        "communications.search",
        "communications.read",
        "communications.coverage",
    ]
    assert frozenset(READS) == COMMUNICATIONS_READ_CAPABILITIES == COMMUNICATIONS_DATA_NAMES
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert commands[SEARCH] is SearchCommunications
    assert commands[READ] is ReadCommunications
    assert commands[COVERAGE] is CommunicationsCoverage
    tools = {tool.name: tool for tool in TOOLS}
    for capability in READS:
        assert _HANDLERS[capability].__name__ == "_communications"
        assert capability in _BUILDERS
        assert permitted_purposes(capability) == {Purpose.COMMUNICATIONS_READ}
        assert capability in _SCOPELESS
        assert not is_write_capability(capability)
        assert not is_operator_only(capability)
        annotations = tools[capability.value].annotations
        assert annotations is not None and annotations.read_only_hint is True
        assert facade_kind(capability) == "read"
        assert feature_label(capability.value) == "communications"
    users = {c for c in Capability if Purpose.COMMUNICATIONS_READ in permitted_purposes(c)}
    assert users == set(READS)


def test_chatllm_classifies_the_three_conditional_on_communications() -> None:
    # Introduced at v17; later profiles (v19, P6 XER import S7-4a; v20, project-report
    # reads WP4P-S4) contain it.
    assert int(CHATLLM_DATA_PROFILE_VERSION.removeprefix("chatllm-data-v")) >= 17
    for capability in READS:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.COMMUNICATIONS
    base: dict[str, bool] = {
        "managed_documents": False,
        "relationship_intelligence": False,
        "relationship_intelligence_writes": False,
        "relationship_memory": False,
        "constraints": True,
    }
    everything = frozenset(Capability)
    off = composed_capabilities(everything, ChatLLMCompositionPlanes(**base))
    on = composed_capabilities(everything, ChatLLMCompositionPlanes(**base, communications=True))
    assert not off & set(READS)
    assert on - off == set(READS)


def test_the_tool_schemas_publish_the_section_16_bounds() -> None:
    tools = {tool.name: tool.input_schema["properties"]["payload"] for tool in TOOLS}
    search = tools[SEARCH.value]
    assert search["required"] == [] and search["additionalProperties"] is False
    properties = search["properties"]
    assert properties["query"]["maxLength"] == 512
    assert properties["identifiers"]["maxItems"] == 20
    assert properties["participants"]["maxItems"] == 20
    assert properties["participant_mode"]["enum"] == ["any", "all"]
    assert properties["collapse"]["enum"] == ["conversation", "none"]
    assert (properties["limit"]["minimum"], properties["limit"]["maximum"]) == (1, 50)
    assert properties["limit"]["default"] == 20
    assert properties["from_utc"]["format"] == "date-time"
    read = tools[READ.value]["properties"]
    assert (read["message_ids"]["minItems"], read["message_ids"]["maxItems"]) == (1, 25)
    assert read["conversation_id"]["maxLength"] == 2048
    assert read["include_text"]["type"] == "boolean"
    # WP4-R2 G6: both cursors publish the section 16 bound the service enforces.
    for cursor in (properties["cursor"], read["cursor"]):
        assert (cursor["minLength"], cursor["maxLength"]) == (1, 2048)
    coverage = tools[COVERAGE.value]
    assert coverage["required"] == ["from_utc", "to_utc"]
    assert set(coverage["properties"]) == {"from_utc", "to_utc", "source"}


@pytest.mark.parametrize(
    ("capability", "payload", "detail"),
    [
        (SEARCH, {"query": "x" * 513}, SafeDetail.QUERY),
        (SEARCH, {"identifiers": [f"RFI {n}" for n in range(21)]}, SafeDetail.IDENTIFIERS),
        (SEARCH, {"participants": ["a@example.invalid"] * 21}, SafeDetail.PARTICIPANTS),
        (SEARCH, {"participant_mode": "most"}, SafeDetail.PARTICIPANT_MODE),
        (SEARCH, {"limit": 51}, SafeDetail.LIMIT),
        (SEARCH, {"limit": 0}, SafeDetail.LIMIT),
        (SEARCH, {"collapse": "thread"}, SafeDetail.COLLAPSE),
        (SEARCH, {"folder_role": "drafts-ish"}, SafeDetail.FOLDER_ROLE),
        (SEARCH, {"from_utc": "2026-11-02T00:00:00"}, SafeDetail.FROM_UTC),
        (
            SEARCH,
            {"from_utc": "2026-11-02T00:00:00Z", "to_utc": "2026-11-01T00:00:00Z"},
            SafeDetail.TO_UTC,
        ),
        (READ, {}, SafeDetail.MESSAGE_IDS),
        (READ, {"message_ids": ["cmsg_synthetic0001"] * 26}, SafeDetail.MESSAGE_IDS),
        (READ, {"message_ids": ["not-an-id"]}, SafeDetail.MESSAGE_IDS),
        (
            READ,
            {"message_ids": ["cmsg_synthetic0001"], "conversation_id": "c"},
            SafeDetail.CONVERSATION_ID,
        ),
        (READ, {"message_ids": ["cmsg_synthetic0001"], "cursor": "x"}, SafeDetail.CURSOR),
        (READ, {"conversation_id": "c", "include_text": "yes"}, SafeDetail.INCLUDE_TEXT),
        (
            COVERAGE,
            {"from_utc": "2025-01-01T00:00:00Z", "to_utc": "2026-11-20T00:00:00Z"},
            SafeDetail.TO_UTC,
        ),
        (
            COVERAGE,
            {
                "from_utc": "2026-11-01T00:00:00Z",
                "to_utc": "2026-11-20T00:00:00Z",
                "source": "cmsg_synthetic0001",
            },
            SafeDetail.SOURCE,
        ),
    ],
)
def test_a_payload_outside_its_bounds_is_refused_naming_only_its_field(
    capability: Capability, payload: Mapping[str, Any], detail: SafeDetail
) -> None:
    """Refused at normalization, before any switch or read, with one SafeDetail token."""
    with pytest.raises(InvalidRequestError) as raised:
        normalize(capability.value, document(capability, OPERATOR.principal_id, payload))
    assert tuple(raised.value.safe_details) == (detail,)
    rendered = repr(raised.value) + str(raised.value)
    for value in ("x" * 40, "not-an-id", "drafts-ish", "most", "thread"):
        assert value not in rendered


# ---- the switch -----------------------------------------------------------------------------


def test_switch_off_withholds_the_three_and_answers_unsupported(scene: Scene) -> None:
    """D8: the standard disabled refusal, not an empty result; absent from every list."""
    service = build_service(scene.world, scene.providers)
    assert not set(READS) & service.available_capabilities
    manifest = _invoke(service, scene.principal, Capability.CAPABILITIES_GET, {})
    assert manifest.error is None and manifest.result is not None
    availability = {
        entry["name"]: entry["availability"]
        for entry in manifest.result["manifest"]["capabilities"]
    }
    assert {availability[c.value] for c in READS} == {"not_implemented"}
    for capability, payload in communications_payloads("switch").items():
        answer = _invoke(service, scene.principal, capability, payload)
        assert answer.error is not None
        assert answer.error.code is ErrorCode.UNSUPPORTED, capability
        # And a transport dispatching straight into the handler meets the same.
        with pytest.raises(Exception) as raised:
            _HANDLERS[capability](service, None, None, None)
        assert type(raised.value).__name__ == "UnsupportedError"


def test_switch_on_serves_the_three(scene: Scene) -> None:
    on = _service(IngestWorld(), enabled=True)
    off = _service(IngestWorld(), enabled=False)
    assert set(READS) <= on.available_capabilities
    assert on.available_capabilities - off.available_capabilities == set(READS)


# ---- answers with the switch on -----------------------------------------------------------


def _row(n: int) -> CommunicationSearchRow:
    return CommunicationSearchRow(
        message_id=f"cmsg_mcpfast{n:06d}",
        conversation_id=None,
        message_time=WHEN - timedelta(minutes=n),
        subject=f"Synthetic {n}",
        sender_address="alpha@example.invalid",
        has_attachments=False,
        body_state="present",
        search_text_version="comms_search_text_v2",
        search_text_flags=(),
        identity_conflict=False,
        participants_reconciled=False,
        participants_disagreed=False,
        source_unavailable=False,
        tier=3,
        rank=0,
        overlap=0,
        matched_identifier_kinds=(),
        conversation_hits=1,
        snippet=f"text {n}",
    )


def test_a_search_answer_carries_versions_coverage_and_a_cursor() -> None:
    world = IngestWorld()
    world.search_rows = [_row(n) for n in range(3)]
    service = _service(world, enabled=True)
    answer = _invoke(service, OPERATOR, SEARCH, {"limit": 2}, grants=GRANTS)
    assert answer.error is None and answer.result is not None
    payload = answer.result
    assert [r["message_id"] for r in payload["results"]] == [
        "cmsg_mcpfast000000",
        "cmsg_mcpfast000001",
    ]
    assert payload["results"][0]["message_time"] == "2026-11-17T12:00:00.000Z"
    assert payload["versions"]["identifier_version"] == "comms_identifiers_v2"
    assert "search_text_versions" in payload["versions"]
    assert "identifier_version_pending" in payload["versions"]
    assert {"state", "intervals", "gaps", "freshness_seconds", "snapshot_count"} <= set(
        payload["coverage"]
    )
    assert (payload["cursor_state"], payload["query_state"], payload["text_fallback"]) == (
        None,
        None,
        None,
    )
    cursor = payload["next_cursor"]
    assert cursor is not None
    assert answer.disclosure is not None
    truncation = answer.disclosure.truncation
    assert truncation.is_truncated and truncation.next_cursor == cursor

    # The same request continues; another Principal's or another request's is refused.
    following = _invoke(service, OPERATOR, SEARCH, {"limit": 2, "cursor": cursor}, grants=GRANTS)
    assert following.error is None and following.result is not None
    for principal, payload_ in (
        (STRANGER, {"limit": 2, "cursor": cursor}),
        (OPERATOR, {"limit": 2, "query": "other", "cursor": cursor}),
    ):
        refused = _invoke(service, principal, SEARCH, payload_, grants=GRANTS)
        assert refused.error is not None
        assert refused.error.code is ErrorCode.CONFLICT
        assert list(refused.error.safe_details) == [SafeDetail.CURSOR.value]
        assert cursor not in refused.model_dump_json()

    # A changed grant set: an answer that says to restart, with nothing else.
    narrowed = frozenset({(SEARCH, Purpose.COMMUNICATIONS_READ)})
    restart = _invoke(service, OPERATOR, SEARCH, {"limit": 2, "cursor": cursor}, grants=narrowed)
    assert restart.error is None and restart.result is not None
    assert restart.result["cursor_state"] == "scope_changed_restart_required"
    assert restart.result["results"] == []
    assert restart.result["next_cursor"] is None


def test_a_search_states_the_stop_word_fallback() -> None:
    world = IngestWorld()
    world.search_rows = [_row(0)]
    world.query_shape = CommunicationSearchQueryShape(english_nodes=0, simple_nodes=2)
    answer = _invoke(_service(world, enabled=True), OPERATOR, SEARCH, {"query": "The Who"})
    assert answer.error is None and answer.result is not None
    assert answer.result["text_fallback"] == "simple_stopwords"


def _ingested(scene: IngestScene, count: int) -> list[str]:
    messages = [
        s.message(n + 1, selected=at(17, 8 + n), subject=f"Synthetic {n}", content=f"<p>t{n}</p>")
        for n in range(count)
    ]
    scene.ingest("20261117-comms.json", pub(17, messages))
    for key, message in list(scene.world.messages.items()):
        scene.world.messages[key] = replace(message, conversation_id="conv-mcp")
    return sorted(m.message_id for m in scene.world.messages.values())


def test_a_read_answer_carries_versions_coverage_and_never_a_raw_body() -> None:
    scene = IngestScene()
    ids = _ingested(scene, 2)
    service = _service(scene.world, enabled=True)
    answer = _invoke(service, OPERATOR, READ, {"message_ids": [ids[0], "cmsg_notthere00001"]})
    assert answer.error is None and answer.result is not None
    payload = answer.result
    assert payload["not_found"] == ["cmsg_notthere00001"]
    assert payload["identifier_version"] == "comms_identifiers_v2"
    (message,) = payload["messages"]
    assert message["message_id"] == ids[0]
    assert message["search_text_version"] == "comms_search_text_v2"
    assert message["coverage"]["coverage_state"] == "complete"
    assert message["source_pointer"]["text_snapshot_id"].startswith("isnp_")
    assert "<p>" not in answer.model_dump_json()
    # A foreign Principal reads nothing: its ids are not found, as unknown ones.
    foreign = _invoke(service, STRANGER, READ, {"message_ids": [ids[0]]})
    assert foreign.error is None and foreign.result is not None
    assert foreign.result["messages"] == []
    assert foreign.result["not_found"] == [ids[0]]


def test_a_thread_view_pages_with_a_grant_bound_cursor() -> None:
    scene = IngestScene()
    _ingested(scene, 2)
    service = _service(scene.world, enabled=True)
    first = _invoke(service, OPERATOR, READ, {"conversation_id": "conv-mcp"}, grants=GRANTS)
    assert first.error is None and first.result is not None
    assert len(first.result["messages"]) == 2
    assert first.result["next_cursor"] is None


def test_a_coverage_answer() -> None:
    scene = IngestScene()
    _ingested(scene, 1)
    answer = _invoke(
        _service(scene.world, enabled=True),
        OPERATOR,
        COVERAGE,
        {"from_utc": "2026-11-17T00:00:00Z", "to_utc": "2026-11-17T23:59:59Z"},
    )
    assert answer.error is None and answer.result is not None
    payload = answer.result
    assert payload["source"] is None
    assert payload["coverage"]["snapshot_count"] == 1
    assert payload["coverage"]["state"] in {"complete", "partial"}


# ---- helpers ------------------------------------------------------------------------------


def _service(world: IngestWorld, *, enabled: bool) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: IngestUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: NOW,
        communications_enabled=enabled,
    )


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
    *,
    grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
) -> ResponseEnvelope:
    metadata, command = normalize(
        capability.value, document(capability, principal.principal_id, payload)
    )
    return service.invoke(metadata, command, principal=principal, capability_grants=grants)
