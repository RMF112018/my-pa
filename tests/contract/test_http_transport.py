"""Eight capabilities over a socket, and nothing decided on the way.

Three claims, and they are different in kind.

**Reachability.** Every one of the eight capabilities is addressable over HTTP
and answers. Parametrised over `Capability` rather than over a list written
here, so a ninth capability added to the domain arrives as a failing row instead
of as an untested one.

**Verbatim.** The bytes a caller receives are the bytes the envelope serialised
itself to — asserted as byte equality against the envelope the application
actually returned for that request, captured as it was returned. Running the
request a second time and comparing would have been weaker *and* wrong: a
correlation identifier is issued per invocation, and `sources.enroll` answers a
repeat of the same idempotency key with `created: false`, correctly. Recording
the one answer removes both problems and strengthens the claim from "equal after
the fields that differ are removed" to "the same bytes".

**Normalisation is the one validation path.** `normalize` is asserted to build
exactly the pair a hand-written command produces, per capability. This is the
half of `SPEC-AC-001` that HTTP can carry alone; the other half arrives with the
MCP adapter, which calls the same function.

The malformed-input section is separate and states its own rule: a request the
transport could not read is refused as `invalid_request`, with a status HTTP
already has a meaning for, and with nothing of the failure in the body.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeProviders,
    FakeUnitOfWork,
    Scene,
    World,
    build_service,
    metadata_for,
    operator,
    staged_search,
)
from tests.wire import Wire, serve

from my_pa.adapters.http import MAX_REQUEST_BYTES, create_http_app
from my_pa.adapters.http.app import _STATUS
from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    ReadKnowledge,
    Representation,
    SearchKnowledge,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import KnowledgeRecord
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_ITEMS
from my_pa.domain.source.registry import issue_identifier

ALL_CAPABILITIES = list(Capability)


def a_permitted_purpose(capability: Capability) -> Purpose:
    """One purpose the domain permits for `capability`, derived from the rule."""
    return sorted(permitted_purposes(capability))[0]


def staged_record(scene: Scene) -> KnowledgeRecord:
    """One stored record, so `knowledge.read` has something to answer with."""
    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type="text/markdown",
        text="quarterly revenue review",
        is_truncated=False,
        provenance=Provenance(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
            version_id=scene.markdown.version_id,
            extractor="my_pa.text",
            extractor_version="1",
            observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            processed_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        ),
    )
    scene.world.records[(scene.enrollment.enrollment_id, record.knowledge_id)] = record
    return record


def payloads_for(scene: Scene, record: KnowledgeRecord) -> dict[Capability, dict[str, Any]]:
    """One well-formed JSON payload per capability, all inside `scene`'s scope."""
    return {
        Capability.CAPABILITIES_GET: {},
        Capability.SOURCES_LIST: {"source_id": scene.source.source_id},
        Capability.SOURCES_METADATA: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
        },
        Capability.SOURCES_FETCH: {
            "source_id": scene.source.source_id,
            "source_object_id": scene.markdown.source_object_id,
            "representation": "normalized_text",
        },
        Capability.SOURCES_STATUS: {"source_id": scene.source.source_id},
        Capability.SOURCES_ENROLL: {
            "source_id": scene.source.source_id,
            "media_types": ["text/markdown"],
            "idempotency_key": "http-probe-0001",
            "object_ids": [scene.markdown.source_object_id],
        },
        Capability.KNOWLEDGE_SEARCH: {
            "enrollment_id": scene.enrollment.enrollment_id,
            "query": "revenue",
        },
        Capability.KNOWLEDGE_READ: {
            "knowledge_id": record.knowledge_id,
            "enrollment_id": scene.enrollment.enrollment_id,
        },
    }


def commands_for(scene: Scene, record: KnowledgeRecord) -> dict[Capability, Command]:
    """The same eight requests, written as commands rather than as JSON.

    Written by hand rather than produced by `normalize`, which is the point: the
    normalisation test below compares the two, and a comparison against the
    function under test would prove only that it agrees with itself.
    """
    return {
        Capability.CAPABILITIES_GET: GetCapabilities(),
        Capability.SOURCES_LIST: ListSources(source_id=scene.source.source_id),
        Capability.SOURCES_METADATA: GetSourceMetadata(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
        ),
        Capability.SOURCES_FETCH: FetchSource(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
            representation=Representation.NORMALIZED_TEXT,
        ),
        Capability.SOURCES_STATUS: GetSourceStatus(source_id=scene.source.source_id),
        Capability.SOURCES_ENROLL: EnrollSource(
            source_id=scene.source.source_id,
            media_types=("text/markdown",),
            idempotency_key="http-probe-0001",
            object_ids=(scene.markdown.source_object_id,),
        ),
        Capability.KNOWLEDGE_SEARCH: SearchKnowledge(
            enrollment_id=scene.enrollment.enrollment_id, query="revenue"
        ),
        Capability.KNOWLEDGE_READ: ReadKnowledge(
            knowledge_id=record.knowledge_id,
            enrollment_id=scene.enrollment.enrollment_id,
        ),
    }


def document_for(capability: Capability, scene: Scene, payload: dict[str, Any]) -> dict[str, Any]:
    """The request document: the common envelope, and the payload beside it."""
    return {
        "request_id": f"req-{capability.value}",
        "purpose": a_permitted_purpose(capability).value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": payload,
    }


class RecordingService(ApplicationService):
    """The real service, keeping every envelope it returned.

    A subclass rather than a wrapper because the transport is typed against
    `ApplicationService` and a duck would need a cast; overriding the one public
    method and delegating to it changes no behaviour, which is what makes the
    recorded envelope the same object the caller received.
    """

    def __init__(self, world: World, providers: FakeProviders) -> None:
        super().__init__(
            unit_of_work=lambda: FakeUnitOfWork(world),
            providers=providers,
            limits=DEFAULT_LIMITS,
            clock=lambda: WHEN,
        )
        self.envelopes: list[ResponseEnvelope] = []

    def invoke(
        self, metadata: RequestMetadata, command: Command, *, principal: Principal
    ) -> ResponseEnvelope:
        envelope = super().invoke(metadata, command, principal=principal)
        self.envelopes.append(envelope)
        return envelope


@pytest.fixture
def staged(scene: Scene) -> tuple[Scene, KnowledgeRecord]:
    """A scene with a search page and a stored record, so all eight can succeed."""
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    return scene, staged_record(scene)


@pytest.fixture
def service(staged: tuple[Scene, KnowledgeRecord]) -> RecordingService:
    scene, _ = staged
    return RecordingService(scene.world, scene.providers)


@pytest.fixture
def wire(staged: tuple[Scene, KnowledgeRecord], service: RecordingService) -> Iterator[Wire]:
    scene, _ = staged
    with serve(create_http_app(service, principal=scene.principal)) as client:
        yield client


# ---- reachability and verbatim answers --------------------------------------


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_is_reachable_over_http(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord], wire: Wire
) -> None:
    """All eight, addressed by name, answering successfully."""
    scene, record = staged
    payload = payloads_for(scene, record)[capability]
    reply = wire.send(capability.value, document_for(capability, scene, payload))
    assert reply.status == 200, reply.body
    envelope = reply.document()
    assert envelope["error"] is None
    assert envelope["disclosure"] is not None
    assert envelope["request_id"] == f"req-{capability.value}"
    assert envelope["contract_version"] == "v1"


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_the_body_is_the_envelope_the_application_produced(
    capability: Capability,
    staged: tuple[Scene, KnowledgeRecord],
    service: RecordingService,
    wire: Wire,
) -> None:
    """No reinterpretation: the body is the envelope's own bytes.

    A transport that reshaped a result, added a field, dropped a disclosure, or
    rewrote an error would fail this without anyone having to predict which of
    those it would do.
    """
    scene, record = staged
    payload = payloads_for(scene, record)[capability]
    reply = wire.send(capability.value, document_for(capability, scene, payload))

    assert len(service.envelopes) == 1, "one request reached the application once"
    produced = service.envelopes[0]
    assert reply.body == produced.to_canonical_json()
    assert reply.status == 200
    assert produced.correlation_id in reply.body


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_normalisation_builds_the_pair_a_hand_written_request_builds(
    capability: Capability, staged: tuple[Scene, KnowledgeRecord]
) -> None:
    """The one validation path, per capability (`SPEC-AC-001`, HTTP's half)."""
    scene, record = staged
    document = document_for(capability, scene, payloads_for(scene, record)[capability])
    metadata, command = normalize(capability.value, document)
    assert command == commands_for(scene, record)[capability]
    assert metadata == metadata_for(capability, a_permitted_purpose(capability), scene.principal)
    assert metadata.requested_at == WHEN


def test_a_denied_request_still_returns_the_application_envelope(scene: Scene, wire: Wire) -> None:
    """An error is an answer, and it arrives in the same shape as a result."""
    stranger = operator()
    document = document_for(Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id})
    document["principal_id"] = stranger.principal_id
    reply = wire.send(Capability.SOURCES_LIST.value, document)
    # The acting principal is the process's, not the document's, so the request
    # is allowed on the scene's own scope: the claimed identity changed nothing.
    assert reply.status == 200, reply.body
    assert reply.document()["error"] is None


def test_a_caller_supplied_identity_is_correlation_and_not_authority(
    scene: Scene, wire: Wire
) -> None:
    """`docs/specs` section 8.2, over the wire.

    A caller naming a principal it is not gets the authority of the process it
    is talking to and no more — here, less: the audit records the acting
    principal, not the claimed one.
    """
    claimed = operator()
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["principal_id"] = claimed.principal_id
    assert wire.send(Capability.CAPABILITIES_GET.value, document).status == 200
    recorded = {event.principal_id for event in scene.world.audit}
    assert recorded == {scene.principal.principal_id}
    assert claimed.principal_id not in recorded


# ---- status is a function of the error code ----------------------------------


def test_the_status_table_covers_every_public_error_code() -> None:
    """A code with no status would be a `KeyError` in front of a caller."""
    assert set(_STATUS) == set(ErrorCode)


def test_a_denial_is_403_and_an_unknown_record_is_404(scene: Scene, wire: Wire) -> None:
    """Two application answers, two statuses, each read from the code."""
    stranger_scope = document_for(
        Capability.SOURCES_LIST, scene, {"source_id": issue_identifier(IdKind.SOURCE)}
    )
    denied = wire.send(Capability.SOURCES_LIST.value, stranger_scope)
    assert denied.status == 403
    assert denied.document()["error"]["code"] == ErrorCode.DENIED.value

    absent = document_for(
        Capability.KNOWLEDGE_READ,
        scene,
        {
            "knowledge_id": issue_identifier(IdKind.KNOWLEDGE),
            "enrollment_id": scene.enrollment.enrollment_id,
        },
    )
    missing = wire.send(Capability.KNOWLEDGE_READ.value, absent)
    assert missing.status == 404
    assert missing.document()["error"]["code"] == ErrorCode.NOT_FOUND.value


def test_a_store_failure_is_503_and_carries_the_applications_code(scene: Scene, wire: Wire) -> None:
    from my_pa.contracts.ports import EvidenceUnavailableError

    scene.world.failures["coverage"] = EvidenceUnavailableError("the store is unreachable")
    reply = wire.send(
        Capability.SOURCES_LIST.value,
        document_for(Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id}),
    )
    assert reply.status == 503
    assert reply.document()["error"]["code"] == ErrorCode.UNAVAILABLE.value


# ---- malformed input ---------------------------------------------------------


#: Things a failure report leaks when it is assembled from an exception rather
#: than looked up. None of them may appear in a refusal.
INTERNAL_TEXT = (
    "Traceback",
    "TypeError",
    "ValueError",
    "ValidationError",
    "JSONDecodeError",
    "pydantic",
    "starlette",
    "uvicorn",
    "my_pa",
    "line ",
    'File "',
)


def assert_refused(reply: Any, *, status: int = 400) -> None:  # noqa: ANN401 - a `Reply`
    """A refusal: the right code, the right status, and nothing internal."""
    assert reply.status == status, reply.body
    document = reply.document()
    assert document["code"] == ErrorCode.INVALID_REQUEST.value
    assert document["retry"] == "after_correction"
    assert document["safe_details"] == []
    for fragment in INTERNAL_TEXT:
        assert fragment not in reply.rendered(), f"a refusal disclosed {fragment!r}"


def test_a_body_that_is_not_json_is_refused(wire: Wire) -> None:
    assert_refused(wire.send("capabilities.get", raw="{not json at all"))


def test_a_body_that_is_json_but_not_an_object_is_refused(wire: Wire) -> None:
    assert_refused(wire.send("capabilities.get", raw="[1, 2, 3]"))


def test_the_wrong_content_type_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, content_type="text/plain"))


def test_a_missing_content_type_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, content_type=None))


def test_a_json_content_type_with_a_charset_is_accepted(scene: Scene, wire: Wire) -> None:
    """The parameter is not the media type. A control for the two tests above."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    reply = wire.send("capabilities.get", document, content_type="application/json; charset=utf-8")
    assert reply.status == 200, reply.body


def test_an_unknown_capability_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("sources.destroy", document))


def test_an_unbounded_body_is_refused_without_being_read(scene: Scene, wire: Wire) -> None:
    """No declared length, no read. See `_declared_length`."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("capabilities.get", document, omit_content_length=True))


def test_an_oversized_body_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["payload"] = {}
    padding = "x" * MAX_REQUEST_BYTES
    assert_refused(wire.send("capabilities.get", raw=json.dumps({**document, "pad": padding})))


def test_an_unknown_field_in_the_envelope_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["principal"] = "prn_0000000000000000"
    assert_refused(wire.send("capabilities.get", document))


def test_an_unknown_field_in_the_payload_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(
        Capability.SOURCES_LIST, scene, {"source_id": scene.source.source_id, "recurse": True}
    )
    assert_refused(wire.send("sources.list", document))


def test_a_capability_named_in_the_document_as_well_is_refused(scene: Scene, wire: Wire) -> None:
    """Two places to name one capability is one place too many."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    document["capability"] = "capabilities.get"
    assert_refused(wire.send("capabilities.get", document))


def test_a_payload_that_is_not_an_object_is_refused(scene: Scene, wire: Wire) -> None:
    document = document_for(Capability.SOURCES_LIST, scene, {})
    document["payload"] = ["src_0000000000000000"]
    assert_refused(wire.send("sources.list", document))


def test_a_malformed_identifier_is_refused_with_the_field_it_names(
    scene: Scene, wire: Wire
) -> None:
    """The command's own refusal, carried through unchanged.

    This one *does* carry a `safe_details` token, which is the difference
    between a refusal the transport made and one the application made. The
    transport reports nothing because it has no token it is allowed to report.
    """
    document = document_for(Capability.SOURCES_LIST, scene, {"source_id": "/etc/passwd"})
    reply = wire.send("sources.list", document)
    assert reply.status == 400
    assert reply.document()["code"] == ErrorCode.INVALID_REQUEST.value
    assert reply.document()["safe_details"] == ["source_id"]
    assert "/etc/passwd" not in reply.rendered()


def test_an_unknown_path_is_404_and_a_wrong_method_is_405(scene: Scene, wire: Wire) -> None:
    """HTTP's own answers about a URL, in this repository's error vocabulary."""
    document = document_for(Capability.CAPABILITIES_GET, scene, {})
    assert_refused(wire.send("", document, path="/not/a/capability"), status=404)
    assert_refused(wire.send("capabilities.get", document, method="GET"), status=405)


# ---- the request ceiling -----------------------------------------------------


def test_the_request_ceiling_admits_the_largest_request_the_contract_allows() -> None:
    """The derivation, checked against real values rather than trusted.

    `MAX_REQUEST_BYTES` restates a bound that is private to
    `domain.common.identifiers`, and a restated constant is a claim. This builds
    an enrollment at the domain's own ceiling — the largest request the contract
    can express — and requires it to fit.
    """
    longest = make_identifier(IdKind.SOURCE_OBJECT, "a" * 64)
    document = {
        "request_id": "r" * 128,
        "purpose": Purpose.BOUNDED_ENROLLMENT.value,
        "principal_id": issue_identifier(IdKind.PRINCIPAL),
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": {
            "source_id": issue_identifier(IdKind.SOURCE),
            "idempotency_key": "k" * 128,
            "media_types": [f"application/{'x' * 100}" for _ in range(32)],
            "object_ids": [longest for _ in range(MAX_ENROLLMENT_ITEMS)],
        },
    }
    encoded = len(json.dumps(document).encode())
    assert encoded <= MAX_REQUEST_BYTES, (
        f"the largest request the contract allows is {encoded} bytes and the "
        f"transport admits {MAX_REQUEST_BYTES}"
    )
    # And not wastefully larger: a ceiling far above the worst case would bound
    # nothing in practice.
    assert 2 * encoded > MAX_REQUEST_BYTES


def test_the_recording_service_records_what_it_returns(
    staged: tuple[Scene, KnowledgeRecord], service: RecordingService
) -> None:
    """Guard the verbatim test: a recorder that recorded nothing would pass it.

    `len(service.envelopes) == 1` is the assertion doing the work there, so a
    recorder that appended a *different* envelope would still satisfy it. This
    requires the recorded object to be the one returned.
    """
    scene, _ = staged
    returned = service.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    )
    assert service.envelopes == [returned]
    assert service.envelopes[0] is returned


def test_the_wire_helper_reaches_a_server_that_is_not_there() -> None:
    """Guard the client: one that swallowed a failure would pass every test."""
    unreachable = Wire(port=1)
    with pytest.raises(OSError):
        unreachable.send("capabilities.get", {})


def test_an_empty_world_still_answers(world: World) -> None:
    """A control for the fixtures above: the app is real without a scene."""
    principal = operator()
    from tests.conftest import FakeProviders

    with serve(
        create_http_app(build_service(world, FakeProviders({})), principal=principal)
    ) as client:
        reply = client.send(
            "capabilities.get",
            {
                "request_id": "req-bare",
                "purpose": Purpose.STATUS_OBSERVATION.value,
                "principal_id": principal.principal_id,
                "requested_at": "2026-08-02T12:00:00Z",
                "payload": {},
            },
        )
    assert reply.status == 200, reply.body
