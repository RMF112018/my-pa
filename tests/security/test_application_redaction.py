"""Nothing sensitive reaches a log, an audit row, or an error payload.

`AGENTS.md` section 5 and `docs/specs` sections 10 and 13 name the same five
things: source content, query text, paths, hosts, and credentials. This file
plants each of them where it would most easily escape and then requires it not
to appear in any of the three sinks.

The three sinks are checked differently on purpose.

**Errors.** `application.errors` looks the message up from a table keyed by the
error code, so there is no parameter a value could be interpolated into. That is
a structural claim, and it is asserted structurally: every message this system
can produce is enumerated and checked, rather than one message being inspected
after one failure.

**Audit.** `AuditEvent` has no field a payload fits in. So the check is over the
events an actual run produced, rendered whole, for the planted markers — which
also covers the fields that *are* free-form enough to worry about, such as the
policy version.

**Logs.** The application emits none. That is checked with `caplog` at `DEBUG`
across every capability rather than asserted in prose, because "we do not log"
is the kind of claim one `logger.debug(request)` invalidates silently.

The disclosure envelope and a `sources.fetch` result are deliberately *not*
included in the sinks: a fetch returns content because that is the request, and
an envelope carries opaque identifiers because that is the contract. The rule is
about what leaks *beside* an answer, not about the answer.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from tests.conftest import Scene, World, build_service, metadata_for, operator

from my_pa.application.commands import (
    FetchSource,
    GetSourceMetadata,
    ListSources,
    ReadKnowledge,
    SearchKnowledge,
)
from my_pa.application.errors import (
    AmbiguousRequestError,
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    QuarantinedError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
    problem_detail,
)
from my_pa.contracts.ports import EvidenceUnavailableError
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

#: The five things that must never appear. Each is planted somewhere a run will
#: touch it, and each is distinctive enough that a substring search is decisive.
MARKER_QUERY = "MARKERQUERYTERM"
MARKER_CONTENT = "MARKERDOCUMENTBODY"
MARKER_CREDENTIAL = "MARKERCREDENTIALVALUE"
MARKER_HOST = "marked-host.invalid"


@pytest.fixture
def marked_root(tmp_path: Path) -> Path:
    """A tree whose one document carries a marker, under a marked directory name."""
    root = tmp_path / f"{MARKER_HOST}-corpus"
    root.mkdir()
    (root / "notes.md").write_bytes(f"# Notes\n\n{MARKER_CONTENT}\n".encode())
    (root / "list.txt").write_bytes(b"pallets\n")
    (root / "statement.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "folder").mkdir()
    return root


@pytest.fixture
def marked(world: World, marked_root: Path) -> Scene:
    return Scene(world, marked_root)


def markers(root: Path) -> tuple[str, ...]:
    return (MARKER_QUERY, MARKER_CONTENT, MARKER_CREDENTIAL, MARKER_HOST, str(root), root.name)


def assert_clean(text: str, root: Path, where: str) -> None:
    for marker in markers(root):
        assert marker not in text, f"{where} disclosed {marker!r}"


def audit_text(world: World) -> str:
    return " ".join(repr(event) for event in world.audit)


def test_every_public_message_this_system_can_produce_is_a_fixed_sentence() -> None:
    """The structural half: there is no parameter a value could enter through.

    Every error type is rendered and its message compared against the one the
    code implies. A message that interpolated request state could not satisfy
    this for two different requests, and an error that gained a free-text
    constructor argument would not compile against it.
    """
    correlation_id = issue_identifier(IdKind.CORRELATION)
    errors: list[ApplicationError] = [
        InvalidRequestError(SafeDetail.QUERY),
        AmbiguousRequestError(SafeDetail.ENROLLMENT_ID),
        DeniedError(),
        UnavailableError(),
        UnsupportedError(SafeDetail.MEDIA_TYPE_NOT_EXTRACTABLE),
        NotFoundError(SafeDetail.KNOWLEDGE_ID),
        ConflictError(SafeDetail.CURSOR),
        QuarantinedError(SafeDetail.PROCESSING_STOPPED),
        InternalError(),
    ]
    for error in errors:
        problem = problem_detail(error, correlation_id=correlation_id)
        assert problem.message == problem_detail(error, correlation_id=correlation_id).message
        assert problem.correlation_id == correlation_id
        for detail in problem.safe_details:
            assert detail in {member.value for member in SafeDetail}


def test_a_refused_query_puts_nothing_of_the_query_into_the_error(
    marked: Scene, marked_root: Path
) -> None:
    """The query is the single most sensitive string in the system."""
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH, marked.principal),
        SearchKnowledge(
            enrollment_id=marked.enrollment.enrollment_id,
            query=f"{MARKER_QUERY}\x00",
        ),
        principal=marked.principal,
    )
    assert envelope.error is not None
    assert_clean(envelope.to_canonical_json(), marked_root, "a refused query")
    assert_clean(audit_text(marked.world), marked_root, "the audit trail")


def test_a_denial_discloses_neither_the_scope_nor_the_reason(
    marked: Scene, marked_root: Path
) -> None:
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, operator()),
        ListSources(source_id=marked.source.source_id),
        principal=operator(),
    )
    assert envelope.error is not None
    assert_clean(envelope.to_canonical_json(), marked_root, "a denial")


def test_a_traversal_denial_discloses_no_path(marked: Scene, marked_root: Path) -> None:
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION, marked.principal),
        GetSourceMetadata(
            source_id=marked.source.source_id,
            source_object_id=issue_identifier(IdKind.SOURCE_OBJECT),
        ),
        principal=marked.principal,
    )
    assert envelope.error is not None
    assert_clean(envelope.to_canonical_json(), marked_root, "a traversal denial")


def test_a_store_failure_discloses_neither_a_host_nor_a_credential(
    marked: Scene, marked_root: Path
) -> None:
    """A port failure carries nothing, so a URL with a password in it cannot escape."""
    marked.world.failures["coverage"] = EvidenceUnavailableError(
        f"postgresql+psycopg://someone:{MARKER_CREDENTIAL}@{MARKER_HOST}:5432/my_pa"
    )
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, marked.principal),
        ListSources(source_id=marked.source.source_id),
        principal=marked.principal,
    )
    assert envelope.error is not None
    assert_clean(envelope.to_canonical_json(), marked_root, "a store failure")


def test_reading_a_records_content_does_not_put_it_into_the_audit_trail(
    marked: Scene, marked_root: Path
) -> None:
    """The content is returned to the caller and recorded nowhere."""
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION, marked.principal),
        FetchSource(
            source_id=marked.source.source_id,
            source_object_id=marked.markdown.source_object_id,
        ),
        principal=marked.principal,
    )
    assert envelope.error is None
    assert envelope.result is not None
    assert MARKER_CONTENT in str(envelope.result["text"]), "the caller asked for this"
    assert MARKER_CONTENT not in audit_text(marked.world)
    assert_clean(
        " ".join(repr(event) for event in marked.world.audit),
        marked_root,
        "the audit trail",
    )


def test_a_fetch_result_carries_no_path_even_though_it_carries_content(
    marked: Scene, marked_root: Path
) -> None:
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION, marked.principal),
        FetchSource(
            source_id=marked.source.source_id,
            source_object_id=marked.markdown.source_object_id,
        ),
        principal=marked.principal,
    )
    rendered = envelope.to_canonical_json()
    for marker in (MARKER_HOST, str(marked_root), marked_root.name, "notes"):
        assert marker not in rendered, f"a fetch disclosed {marker!r}"


def test_no_capability_writes_to_a_log(marked: Scene, caplog: pytest.LogCaptureFixture) -> None:
    """ "We do not log" is the kind of claim one debug line invalidates silently."""
    record = staged_record(marked)
    marked.world.searches[marked.enrollment.enrollment_id] = staged_search_for(marked)
    service = build_service(marked.world, marked.providers)
    requests: list[tuple[Capability, Purpose, object]] = [
        (
            Capability.SOURCES_LIST,
            Purpose.SOURCE_INSPECTION,
            ListSources(source_id=marked.source.source_id),
        ),
        (
            Capability.SOURCES_FETCH,
            Purpose.CONTENT_EXTRACTION,
            FetchSource(
                source_id=marked.source.source_id,
                source_object_id=marked.markdown.source_object_id,
            ),
        ),
        (
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=marked.enrollment.enrollment_id, query=MARKER_QUERY),
        ),
        (
            Capability.KNOWLEDGE_READ,
            Purpose.KNOWLEDGE_READ,
            ReadKnowledge(
                knowledge_id=record.knowledge_id,
                enrollment_id=marked.enrollment.enrollment_id,
            ),
        ),
    ]
    with caplog.at_level(logging.DEBUG):
        for capability, purpose, command in requests:
            service.invoke(
                metadata_for(capability, purpose, marked.principal),
                command,  # type: ignore[arg-type] - exercised member by member
                principal=marked.principal,
            )
    assert caplog.records == [], "the application emitted a log record"


def staged_record(scene: Scene) -> object:
    from datetime import UTC, datetime

    from my_pa.contracts.ports import KnowledgeRecord
    from my_pa.domain.common.provenance import Provenance

    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type="text/markdown",
        text=MARKER_CONTENT,
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


def staged_search_for(scene: Scene) -> object:
    from tests.conftest import staged_search

    return staged_search(scene)


def test_an_envelope_is_still_a_complete_answer(marked: Scene) -> None:
    """A control: redaction that removed the answer would satisfy every test above."""
    service = build_service(marked.world, marked.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, marked.principal),
        ListSources(source_id=marked.source.source_id),
        principal=marked.principal,
    )
    assert isinstance(envelope, ResponseEnvelope)
    assert envelope.error is None
    assert envelope.disclosure is not None
    assert envelope.result is not None
    objects = envelope.result["objects"]
    assert isinstance(objects, list)
    assert len(objects) == 4
