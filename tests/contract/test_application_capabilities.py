"""All thirty capabilities execute real behaviour, and disclose what they did.

Each test below runs one capability through `ApplicationService.invoke` — the
only public entry point there is — against the real fixture source provider and
in-memory repositories. What "real behaviour" means here is stated per test
rather than assumed: a listing is the provider's own children, a fetch is the
extractor's own outcome, an enrollment is a stored grant with queued work, and a
manifest is derived from the dispatch table rather than from a constant.

Two properties are tested harder than the rest.

**A disclosure is assembled, not asserted.** The coverage tests change a
recorded outcome and require the envelope to change with it. That is the whole
of criterion 4 at this layer; that the port returns what WP-3 persisted is the
`database` tier's claim, in `tests/schema/test_persistence_ports.py`, and
neither proves the other.

**A published limit is an enforced limit.** `D-24` requires the number in the
manifest to come from the code path that enforces it, so the tests change one
configured limit and assert both halves move together. A test that only read the
manifest would pass against a constant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    FakeProviders,
    Scene,
    World,
    build_provider,
    build_service,
    metadata_for,
    operator,
    staged_search,
)

from my_pa.application.commands import (
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    PrepareContext,
    ReadKnowledge,
    Representation,
    SearchKnowledge,
)
from my_pa.application.disclosure import Limitation
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import KnowledgeRecord
from my_pa.contracts.v1.capabilities import Availability, EffectiveLimits, ReadinessState
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.coverage import AggregateLimitation, LimitationReason
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import issue_identifier

#: The fixture tree, by the only thing the port discloses about an entry.
MARKDOWN = "text/markdown"
PLAIN = "text/plain"
PDF = "application/pdf"


def run(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    purpose: Purpose,
    command: object,
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(capability, purpose, scene.principal),
        command,  # type: ignore[arg-type] - the union is exercised member by member
        principal=scene.principal,
    )


def succeeded(envelope: ResponseEnvelope) -> dict[str, object]:
    """Assert the envelope is a success and return its payload."""
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    assert envelope.result is not None
    return envelope.result


# ---- capabilities.get ------------------------------------------------------


def test_capabilities_get_reports_every_capability_as_available(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.CAPABILITIES_GET,
            Purpose.STATUS_OBSERVATION,
            GetCapabilities(),
        )
    )
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    availability = {c["name"]: c["availability"] for c in manifest["capabilities"]}
    assert set(availability) == {c.value for c in Capability}
    assert set(availability.values()) == {Availability.AVAILABLE.value}


def test_readiness_stops_reporting_contracts_only_because_the_manifest_is_derived(
    scene: Scene,
) -> None:
    """Readiness follows the wiring, so it cannot be stale in either direction."""
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.CAPABILITIES_GET,
            Purpose.SECURITY_VALIDATION,
            GetCapabilities(),
        )
    )
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["state"] == ReadinessState.DEGRADED.value
    assert readiness["implemented_capabilities"] == len(Capability)
    assert readiness["limitations"]
    assert "Worker-plane health" in readiness["limitations"][-1]
    assert result["worker_planes"] == [
        {
            "plane": "capture",
            "state": "unavailable",
            "backlog": None,
            "dead_lettered": None,
            "last_heartbeat_at": None,
        },
        {
            "plane": "enrollment",
            "state": "unavailable",
            "backlog": None,
            "dead_lettered": None,
            "last_heartbeat_at": None,
        },
    ]


def test_the_manifest_reports_the_media_types_the_extractor_can_actually_read(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.CAPABILITIES_GET,
            Purpose.STATUS_OBSERVATION,
            GetCapabilities(),
        )
    )
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    types = {c["media_type"]: c["availability"] for c in manifest["content_types"]}
    assert types[MARKDOWN] == Availability.AVAILABLE.value
    assert types[PLAIN] == Availability.AVAILABLE.value
    assert types[PDF] == Availability.DECISION_GATED.value


# ---- sources.list ----------------------------------------------------------


def test_sources_list_returns_the_providers_own_children(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_LIST,
            Purpose.SOURCE_INSPECTION,
            ListSources(source_id=scene.source.source_id),
        )
    )
    objects = result["objects"]
    assert isinstance(objects, list)
    assert len(objects) == 4
    assert "list_children" in scene.provider.calls
    identifiers = {entry["source_object_id"] for entry in objects}
    assert scene.markdown.source_object_id in identifiers


def test_a_listing_discloses_no_path_host_or_locator(scene: Scene, fixture_root: Path) -> None:
    """A media type contains a slash; a locator would contain the fixture root.

    The tokens checked are the ones that only a locator could supply — the
    resolved root, each entry's own name, and its extension — rather than any
    character that happens to appear in `text/markdown`.
    """
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        ListSources(source_id=scene.source.source_id),
    )
    rendered = envelope.to_canonical_json()
    tokens = [str(fixture_root), fixture_root.name, "notes", "list.txt", "statement", "folder"]
    for token in tokens:
        assert token not in rendered, f"a listing disclosed {token!r}"


def test_a_listing_stops_at_the_page_size_and_says_so(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        ListSources(source_id=scene.source.source_id, page_size=2),
    )
    result = succeeded(envelope)
    objects = result["objects"]
    assert isinstance(objects, list)
    assert len(objects) == 2
    assert envelope.disclosure is not None
    assert envelope.disclosure.truncation.is_truncated
    assert envelope.disclosure.truncation.reason == "page_size_reached"
    assert envelope.disclosure.partial_result
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations


# ---- sources.metadata ------------------------------------------------------


def test_sources_metadata_lists_no_mutating_operation(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_METADATA,
            Purpose.SOURCE_INSPECTION,
            GetSourceMetadata(
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
            ),
        )
    )
    assert result["media_type"] == MARKDOWN
    assert result["supported_operations"] == ["metadata", "fetch"]
    for forbidden in ("write", "delete", "rename", "move", "upload"):
        assert forbidden not in str(result["supported_operations"])


def test_sources_metadata_reports_what_has_happened_to_the_object(scene: Scene) -> None:
    scene.world.record_outcome(
        enrollment_id=scene.enrollment.enrollment_id,
        source_object_id=scene.markdown.source_object_id,
        status=ExtractionStatus.QUARANTINED,
    )
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_METADATA,
            Purpose.SOURCE_INSPECTION,
            GetSourceMetadata(
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
            ),
        )
    )
    assert result["status"] == SourceStatusState.QUARANTINED.value


# ---- sources.fetch ---------------------------------------------------------


def test_sources_fetch_returns_the_decoded_text(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_FETCH,
            Purpose.CONTENT_EXTRACTION,
            FetchSource(
                source_id=scene.source.source_id,
                source_object_id=scene.markdown.source_object_id,
            ),
        )
    )
    assert result["representation"] == Representation.NORMALIZED_TEXT.value
    assert "Quarterly revenue review" in str(result["text"])
    assert scene.provider.calls == ["metadata", "fetch"]


def test_sources_fetch_returns_raw_bytes_when_asked_for_them(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_FETCH,
            Purpose.SOURCE_INSPECTION,
            FetchSource(
                source_id=scene.source.source_id,
                source_object_id=scene.plain.source_object_id,
                representation=Representation.RAW_BYTES,
            ),
        )
    )
    assert result["representation"] == Representation.RAW_BYTES.value
    assert isinstance(result["content_base64"], str)
    assert result["byte_count"] == scene.plain.size_bytes


def test_a_pdf_is_reported_unsupported_rather_than_returned_as_empty_text(
    scene: Scene,
) -> None:
    """`P00-OD-003` is open, so a PDF is refused explicitly and never coerced."""
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.SOURCES_FETCH,
        Purpose.CONTENT_EXTRACTION,
        FetchSource(
            source_id=scene.source.source_id,
            source_object_id=scene.pdf.source_object_id,
        ),
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNSUPPORTED


# ---- sources.status --------------------------------------------------------


def test_sources_status_answers_for_a_source(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_STATUS,
            Purpose.STATUS_OBSERVATION,
            GetSourceStatus(source_id=scene.source.source_id),
        )
    )
    assert result == {"subject": "source", "state": SourceStatusState.CONFIGURED.value}


def test_sources_status_derives_an_enrollments_state_from_its_coverage(
    scene: Scene,
) -> None:
    for object_id in scene.enrollment.scope.object_ids:
        scene.world.record_outcome(
            enrollment_id=scene.enrollment.enrollment_id,
            source_object_id=object_id,
            status=ExtractionStatus.EXTRACTED,
        )
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_STATUS,
            Purpose.STATUS_OBSERVATION,
            GetSourceStatus(enrollment_id=scene.enrollment.enrollment_id),
        )
    )
    assert result["state"] == SourceStatusState.COMPLETE_FOR_SCOPE.value


def test_sources_status_answers_for_an_operation(scene: Scene) -> None:
    operation_id = issue_identifier(IdKind.OPERATION)
    scene.world.jobs[operation_id] = (
        scene.enrollment.enrollment_id,
        SourceStatusState.RUNNING,
    )
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_STATUS,
            Purpose.STATUS_OBSERVATION,
            GetSourceStatus(operation_id=operation_id),
        )
    )
    assert result == {"subject": "operation", "state": SourceStatusState.RUNNING.value}


def test_sources_status_answers_for_an_object(scene: Scene) -> None:
    scene.world.record_outcome(
        enrollment_id=scene.enrollment.enrollment_id,
        source_object_id=scene.pdf.source_object_id,
        status=ExtractionStatus.UNSUPPORTED,
    )
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_STATUS,
            Purpose.STATUS_OBSERVATION,
            GetSourceStatus(source_object_id=scene.pdf.source_object_id),
        )
    )
    assert result == {"subject": "object", "state": SourceStatusState.UNSUPPORTED.value}


# ---- sources.enroll --------------------------------------------------------


def enrollment_command(scene: Scene, key: str) -> EnrollSource:
    return EnrollSource(
        source_id=scene.source.source_id,
        media_types=(MARKDOWN,),
        idempotency_key=key,
        object_ids=(scene.markdown.source_object_id,),
    )


def test_sources_enroll_persists_a_grant_and_queues_exactly_one_operation(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_ENROLL,
            Purpose.BOUNDED_ENROLLMENT,
            enrollment_command(scene, "enroll-key-0001"),
        )
    )
    assert result["created"] is True
    assert isinstance(result["operation_id"], str)
    assert len(scene.world.jobs) == 1
    assert any(e.enrollment_id == result["enrollment_id"] for e in scene.world.enrollments)


def test_an_enrollment_retry_returns_the_same_grant_and_queues_nothing_more(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    first = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_ENROLL,
            Purpose.BOUNDED_ENROLLMENT,
            enrollment_command(scene, "enroll-key-0002"),
        )
    )
    second = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_ENROLL,
            Purpose.BOUNDED_ENROLLMENT,
            enrollment_command(scene, "enroll-key-0002"),
        )
    )
    assert second["enrollment_id"] == first["enrollment_id"]
    assert second["created"] is False
    assert second["operation_id"] is None
    assert len(scene.world.jobs) == 1


def test_a_reused_key_with_a_different_request_is_a_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    run(
        service,
        scene,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        enrollment_command(scene, "enroll-key-0003"),
    )
    envelope = run(
        service,
        scene,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        EnrollSource(
            source_id=scene.source.source_id,
            media_types=(PLAIN,),
            idempotency_key="enroll-key-0003",
            object_ids=(scene.plain.source_object_id,),
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT


def test_an_enrollment_deeper_than_the_configured_ceiling_is_refused(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        EnrollSource(
            source_id=scene.source.source_id,
            media_types=(MARKDOWN,),
            idempotency_key="enroll-key-0004",
            root_object_id=scene.folder.source_object_id,
            depth=3,
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
    assert "max_enrollment_depth" in envelope.error.safe_details


# ---- knowledge.search ------------------------------------------------------


def test_knowledge_search_returns_the_page_and_the_disclosure_the_index_produced(
    scene: Scene,
) -> None:
    outcome = staged_search(scene)
    scene.world.searches[scene.enrollment.enrollment_id] = outcome
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.KNOWLEDGE_SEARCH,
        Purpose.KNOWLEDGE_SEARCH,
        SearchKnowledge(enrollment_id=scene.enrollment.enrollment_id, query="revenue"),
    )
    result = succeeded(envelope)
    matches = result["matches"]
    assert isinstance(matches, list)
    assert matches[0]["knowledge_id"] == outcome.matches[0].knowledge_id
    assert envelope.disclosure == outcome.disclosure


def test_a_query_with_no_terms_is_an_invalid_request_and_not_an_empty_result(
    scene: Scene,
) -> None:
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.KNOWLEDGE_SEARCH,
        Purpose.KNOWLEDGE_SEARCH,
        SearchKnowledge(enrollment_id=scene.enrollment.enrollment_id, query="   "),
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST


# ---- knowledge.read --------------------------------------------------------


def staged_record(
    scene: Scene, text: str = "Quarterly revenue review.", *, is_truncated: bool = False
) -> KnowledgeRecord:
    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type=MARKDOWN,
        text=text,
        is_truncated=is_truncated,
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


@pytest.mark.parametrize("stored_truncated", [False, True])
def test_knowledge_read_returns_the_record_and_its_mandatory_provenance(
    scene: Scene, stored_truncated: bool
) -> None:
    """Every provenance field the answer publishes, against a value staged here.

    `extractor` and `extractor_version` are asserted against the literals
    `staged_record` writes, not against `record.provenance.extractor` — an
    assertion whose expected value is read back out of the object under test
    passes whatever that object holds, which is the shape the end-to-end
    slice carried until this package.

    `stored_truncated` is parametrized because `False` alone proves nothing:
    the read path spells this field `record.is_truncated or cut`, so a `False`
    row and a code path that dropped the stored flag entirely give the same
    answer. The `True` row is the one that measures it, and it is bounded by
    nothing — no page size is narrowed here — so `cut` is `False` and only the
    stored flag can carry it through.
    """
    record = staged_record(scene, is_truncated=stored_truncated)
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.KNOWLEDGE_READ,
        Purpose.KNOWLEDGE_READ,
        ReadKnowledge(
            knowledge_id=record.knowledge_id, enrollment_id=scene.enrollment.enrollment_id
        ),
    )
    result = succeeded(envelope)
    assert result["text"] == record.text
    assert result["is_truncated"] is stored_truncated
    provenance = result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["source_id"] == scene.source.source_id
    assert provenance["version_id"] == scene.markdown.version_id
    assert provenance["trust_level"] == TrustLevel.SOURCE_BOUND_DERIVED.value
    assert provenance["extractor"] == "my_pa.text"
    assert provenance["extractor_version"] == "1"
    assert provenance["observed_at"] == "2026-08-01T00:00:00.000Z"


def test_a_bounded_read_truncates_truthfully(scene: Scene) -> None:
    record = staged_record(scene, text="a" * 100)
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.KNOWLEDGE_READ,
        Purpose.KNOWLEDGE_READ,
        ReadKnowledge(
            knowledge_id=record.knowledge_id,
            enrollment_id=scene.enrollment.enrollment_id,
            max_characters=10,
        ),
    )
    result = succeeded(envelope)
    assert result["text"] == "a" * 10
    assert result["character_count"] == 100
    assert envelope.disclosure is not None
    assert envelope.disclosure.truncation.is_truncated
    assert envelope.disclosure.partial_result
    assert Limitation.TEXT_TRUNCATED_TO_REQUESTED_MAXIMUM.value in envelope.disclosure.limitations


def test_a_metadata_only_read_returns_no_text(scene: Scene) -> None:
    record = staged_record(scene)
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.KNOWLEDGE_READ,
            Purpose.KNOWLEDGE_READ,
            ReadKnowledge(
                knowledge_id=record.knowledge_id,
                enrollment_id=scene.enrollment.enrollment_id,
                metadata_only=True,
            ),
        )
    )
    assert "text" not in result
    assert result["character_count"] == len(record.text)


def test_a_record_outside_the_stated_grant_is_not_found(scene: Scene) -> None:
    """The same answer as a record that does not exist, as section 10 requires."""
    record = staged_record(scene)
    other = scene.world.add_enrollment(
        source_id=scene.source.source_id,
        principal_id=scene.principal.principal_id,
        object_ids=(scene.plain.source_object_id,),
        accepted_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.KNOWLEDGE_READ,
        Purpose.KNOWLEDGE_READ,
        ReadKnowledge(knowledge_id=record.knowledge_id, enrollment_id=other.enrollment_id),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.NOT_FOUND


# ---- disclosure is assembled from real coverage ----------------------------


def test_changing_the_recorded_coverage_changes_the_disclosed_envelope(
    scene: Scene,
) -> None:
    """Criterion 4: the envelope follows the outcomes, not a constant."""
    service = build_service(scene.world, scene.providers)
    command = ListSources(source_id=scene.source.source_id)

    before = run(service, scene, Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, command)
    assert before.disclosure is not None
    assert before.disclosure.coverage.processed == 0
    assert before.disclosure.coverage.state is CoverageState.ELIGIBLE
    assert Limitation.NO_EXTRACTED_TEXT_IN_SCOPE.value in before.disclosure.limitations

    for object_id in scene.enrollment.scope.object_ids:
        scene.world.record_outcome(
            enrollment_id=scene.enrollment.enrollment_id,
            source_object_id=object_id,
            status=ExtractionStatus.EXTRACTED,
        )

    after = run(service, scene, Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, command)
    assert after.disclosure is not None
    assert after.disclosure.coverage.processed == 4
    assert after.disclosure.coverage.state is CoverageState.PROCESSED
    assert Limitation.NO_EXTRACTED_TEXT_IN_SCOPE.value not in after.disclosure.limitations


def test_a_recorded_limitation_reaches_the_envelope(scene: Scene) -> None:
    limitation = AggregateLimitation(
        reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN, affected_count=3
    )
    scene.world.limitations[scene.enrollment.enrollment_id] = (limitation,)
    service = build_service(scene.world, scene.providers)
    envelope = run(
        service,
        scene,
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        ListSources(source_id=scene.source.source_id),
    )
    assert envelope.disclosure is not None
    assert limitation.disclosure in envelope.disclosure.limitations


# ---- sources.enroll: enumeration at acceptance -----------------------------


class Grove:
    """A three-level tree, one source over it, and a grant that reaches it.

    The provider is opened over `tmp_path` itself so that the directory below it
    is a *child* and therefore has an identifier a request can name as its root.
    `SourceProvider` speaks only in `obj_…` and has no "identify the root" call,
    so a root selector can only ever name something a listing disclosed — which
    is the real constraint an operator works under, not a test convenience.

    The shape, and every enumeration assertion below is decidable by reading it:

        tree/  a.md  b.txt  deep/
        tree/deep/  c.md  deeper/
        tree/deep/deeper/  d.md

    Two files at level one, one more at level two, one more at level three, and a
    container at every level to prove containers are descended and not counted.

    `bootstrap` is an enrollment over the same source naming one object, and it
    exists only so policy resolves the request's scope to a source the principal
    holds a grant over. It is not the enrollment any test asserts about.
    """

    def __init__(self, world: World, tmp_path: Path) -> None:
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.md").write_bytes(b"# A\n\nfirst level\n")
        (tree / "b.txt").write_bytes(b"first level, plain\n")
        deep = tree / "deep"
        deep.mkdir()
        (deep / "c.md").write_bytes(b"# C\n\nsecond level\n")
        deeper = deep / "deeper"
        deeper.mkdir()
        (deeper / "d.md").write_bytes(b"# D\n\nthird level\n")

        self.world = world
        self.principal = operator()
        self.source = world.add_source()
        self.provider = build_provider(tmp_path, self.source.source_id)
        self.root = next(iter(self.provider.list_children()))
        assert self.root.kind is ObjectKind.CONTAINER
        self.bootstrap = world.add_enrollment(
            source_id=self.source.source_id,
            principal_id=self.principal.principal_id,
            object_ids=(self.root.source_object_id,),
        )
        self.providers = FakeProviders({self.source.source_id: self.provider})
        self.provider.calls.clear()

    def enroll(
        self,
        service: ApplicationService,
        *,
        key: str,
        depth: int = 0,
        max_items: int | None = None,
    ) -> ResponseEnvelope:
        return service.invoke(
            metadata_for(Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT, self.principal),
            EnrollSource(
                source_id=self.source.source_id,
                media_types=(MARKDOWN, PLAIN),
                idempotency_key=key,
                root_object_id=self.root.source_object_id,
                depth=depth,
                max_items=max_items,
            ),
            principal=self.principal,
        )


def deep_limits(depth: int) -> EffectiveLimits:
    """The default limits with the enrollment-depth ceiling raised to `depth`.

    `DEFAULT_LIMITS` puts it at zero, which is the product default and what
    `docs/specs` section 9.6 asks for; a test about the walk has to be allowed to
    ask for one.
    """
    return EffectiveLimits(
        max_page_size=DEFAULT_LIMITS.max_page_size,
        default_page_size=DEFAULT_LIMITS.default_page_size,
        max_fetch_bytes=DEFAULT_LIMITS.max_fetch_bytes,
        max_enrollment_depth=depth,
    )


def test_enrolling_a_root_records_the_object_set_the_walk_found(
    world: World, tmp_path: Path
) -> None:
    """Criterion 1 at this layer: the grant carries a measured scope, not a promise.

    At depth zero the walk is one `list_children` call and the answer is the two
    files at the first level — `deep/` is a container and holds no content to be
    eligible for, so it is descended past rather than counted.

    Both halves are asserted because either alone is satisfiable by an accident:
    the recorded set says what was stored, and the disclosed `eligible` says the
    coverage read that same set. A denominator of two beside a stored set of two
    is the property; a non-empty result on both sides is what makes the zero that
    a mismatched identifier produces visible.
    """
    grove = Grove(world, tmp_path)
    service = build_service(world, grove.providers)
    envelope = grove.enroll(service, key="grove-depth-zero")

    result = succeeded(envelope)
    enrollment_id = str(result["enrollment_id"])
    assert result["created"] is True
    assert world.scopes[enrollment_id] == (
        *(
            o.source_object_id
            for o in grove.provider.list_children(grove.root.source_object_id)
            if o.kind is ObjectKind.FILE
        ),
    )
    assert len(world.scopes[enrollment_id]) == 2
    assert envelope.disclosure is not None
    assert envelope.disclosure.coverage.eligible == 2


def test_enumeration_walks_exactly_depth_plus_one_levels(world: World, tmp_path: Path) -> None:
    """Depth is levels of listing, and the level count is `depth + 1`.

    `domain.source.enrollment` fixes depth zero as "the named root itself and its
    immediate children — never a walk", so zero is one listing. Each further
    level adds exactly the files one directory deeper: two, then three, then
    four, against the tree `Grove` documents.

    Written as three enrollments over one tree rather than as three trees,
    because the fixture is then the constant and the depth is the only variable.
    Changing `depth + 1` to `depth` in `_enumerate` leaves the depth-one case
    reporting two objects instead of three.
    """
    grove = Grove(world, tmp_path)
    found: dict[int, int] = {}
    for depth in (0, 1, 2):
        service = build_service(world, grove.providers, deep_limits(depth))
        result = succeeded(grove.enroll(service, key=f"grove-depth-{depth}", depth=depth))
        found[depth] = len(world.scopes[str(result["enrollment_id"])])

    assert found == {0: 2, 1: 3, 2: 4}


def test_enumeration_refuses_a_scope_larger_than_max_items(world: World, tmp_path: Path) -> None:
    """The ceiling stops the walk, and the refusal takes the enrollment with it.

    `max_items` is the enrollment's own ceiling and `_enumerate` restates none of
    its own: the walk stops at `max_items + 1` objects and refuses. The refusal
    raises out of the transaction, so `accept_enrollment` rolls back and the
    over-large enrollment does not exist rather than existing over a scope
    silently truncated to fit — which is the laundering `docs/specs` section 12
    forbids.

    The control is in the same test and is what makes the refusal about the
    ceiling: one more item of headroom over the identical tree accepts, and
    stores both objects.
    """
    grove = Grove(world, tmp_path)
    service = build_service(world, grove.providers)

    refused = grove.enroll(service, key="grove-over-ceiling", max_items=1)
    assert refused.error is not None
    assert refused.error.code is ErrorCode.INVALID_REQUEST
    assert "max_items" in refused.error.safe_details
    assert world.jobs == {}

    allowed = grove.enroll(service, key="grove-at-ceiling", max_items=2)
    result = succeeded(allowed)
    assert len(world.scopes[str(result["enrollment_id"])]) == 2


def test_a_root_that_encloses_no_extractable_object_is_refused(
    world: World, tmp_path: Path
) -> None:
    """An enrollment nobody can enumerate is never accepted.

    The whole argument for enumerating at acceptance rests on this: there is no
    instant at which a stored enrollment has an unmeasured denominator, because
    the empty enumeration refuses and its refusal rolls `accept_enrollment` back
    with it. `invalid_request` rather than `internal_error` — the operator named
    a root that holds nothing, which is a fact about the request.

    The control is the sibling call in the same test over the same tree: the
    non-empty root accepts, so the refusal is about what was under the root and
    not about the machinery failing to see anything at all.
    """
    grove = Grove(world, tmp_path)
    empty = tmp_path / "tree" / "empty"
    empty.mkdir()
    service = build_service(world, grove.providers, deep_limits(1))
    hollow = next(
        child
        for child in grove.provider.list_children(grove.root.source_object_id)
        if child.kind is ObjectKind.CONTAINER
        and child.source_object_id != grove.root.source_object_id
        and not tuple(grove.provider.list_children(child.source_object_id))
    )

    refused = service.invoke(
        metadata_for(Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT, grove.principal),
        EnrollSource(
            source_id=grove.source.source_id,
            media_types=(MARKDOWN,),
            idempotency_key="grove-hollow-root",
            root_object_id=hollow.source_object_id,
        ),
        principal=grove.principal,
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.INVALID_REQUEST
    assert world.jobs == {}
    assert world.rollbacks == 1

    accepted = succeeded(grove.enroll(service, key="grove-hollow-control"))
    assert len(world.scopes[str(accepted["enrollment_id"])]) == 2


def test_an_enroll_over_a_source_with_no_provider_stores_nothing(
    world: World, tmp_path: Path
) -> None:
    """No adapter means no enumeration, and no enumeration means no grant.

    `unavailable` rather than `not_found`: the source row exists and the operator
    can see it in `sources.list`, so reporting it absent would describe a wiring
    gap as a fact about the corpus. What matters beyond the code is that nothing
    is left behind — the acceptance had already run inside the transaction when
    the lookup failed, and the rollback is what makes that not a stored
    enrollment with no measured scope.

    What this tier can prove is that the transaction ended by exception, which is
    `World.rollbacks`; that no work was queued and no scope was recorded; and
    that the same request against a lookup which *does* serve the source does all
    three. What it cannot prove is that the acceptance row itself vanished —
    `FakeUnitOfWork` counts how the block ended and undoes nothing, the same
    limitation `_Audit` carries — and that claim belongs to the `database` tier,
    against a server that can actually roll one back.
    """
    grove = Grove(world, tmp_path)
    service = build_service(world, FakeProviders({}))
    refused = grove.enroll(service, key="grove-no-provider")

    assert refused.error is not None
    assert refused.error.code is ErrorCode.UNAVAILABLE
    assert world.rollbacks == 1
    assert world.jobs == {}
    # No enumerated set for anything but the bootstrap grant, which is what
    # "no measured scope was stored" looks like from here.
    assert set(world.scopes) == {grove.bootstrap.enrollment_id}

    served = build_service(world, grove.providers)
    result = succeeded(grove.enroll(service=served, key="grove-provider-control"))
    assert len(world.jobs) == 1
    assert len(world.scopes[str(result["enrollment_id"])]) == 2


def test_a_retried_enroll_re_enumerates_nothing(world: World, tmp_path: Path) -> None:
    """Criterion 4: the retry makes no provider call at all.

    `record_scope` and `enqueue` are both gated on `acceptance.created`, so the
    same idempotency key carrying the same normalized request enumerates nothing
    and queues nothing. **The assertion is on the provider's call log and not on
    the row count**, and that is the point of the test rather than a stylistic
    choice: `record_scope` inserts under a primary key, so the stored set is
    identical whether the walk ran again or not, and a row-count assertion would
    pass with the gate removed.

    The first call's log is the control: it is non-empty, so an empty second log
    means "did not walk" rather than "the log was never written".
    """
    grove = Grove(world, tmp_path)
    service = build_service(world, grove.providers)

    first = succeeded(grove.enroll(service, key="grove-retry"))
    walked = [call for call in grove.provider.calls if call == "list_children"]
    grove.provider.calls.clear()

    second = succeeded(grove.enroll(service, key="grove-retry"))

    assert walked == ["list_children"]
    assert grove.provider.calls == []
    assert second["created"] is False
    assert second["operation_id"] is None
    assert second["enrollment_id"] == first["enrollment_id"]
    assert len(world.scopes[str(first["enrollment_id"])]) == 2
    assert len(world.jobs) == 1


def test_a_root_selector_reports_the_measured_total_and_neither_removed_token(
    world: World, tmp_path: Path
) -> None:
    """Criterion 3 at this layer, in the place a clamp test used to stand.

    `test_a_root_selector_never_claims_whole_scope_coverage` asserted the
    opposite of this until WP-4B3: with no persisted object set a root selector
    had no denominator, so the state was held at `partially_processed` and two
    tokens said why. The enumerated set is that denominator, so the state is now
    the counts' own and the tokens are gone from the vocabulary.

    One of two enumerated objects is extracted, so the honest reading is
    `partially_processed` over `eligible == 2` — a number neither outcome count
    produces, which is what makes this an assertion about the stored set.
    """
    grove = Grove(world, tmp_path)
    service = build_service(world, grove.providers)
    enrolled = succeeded(grove.enroll(service, key="grove-disclosure"))
    enrollment_id = str(enrolled["enrollment_id"])
    world.record_outcome(
        enrollment_id=enrollment_id,
        source_object_id=world.scopes[enrollment_id][0],
        status=ExtractionStatus.EXTRACTED,
    )

    envelope = service.invoke(
        metadata_for(Capability.SOURCES_STATUS, Purpose.STATUS_OBSERVATION, grove.principal),
        GetSourceStatus(enrollment_id=enrollment_id),
        principal=grove.principal,
    )
    disclosure = envelope.disclosure
    assert envelope.error is None, envelope.error
    assert disclosure is not None
    assert disclosure.coverage.eligible == 2
    assert disclosure.coverage.processed == 1
    assert disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" not in disclosure.limitations
    assert "scope_is_source_wide_not_root_bounded" not in disclosure.limitations
    assert Limitation.SCOPE_NOT_FULLY_EXTRACTED.value in disclosure.limitations


# ---- D-24: the published limit is the enforced limit -----------------------


def published_limits(service: ApplicationService, scene: Scene) -> dict[str, int]:
    result = succeeded(
        run(
            service,
            scene,
            Capability.CAPABILITIES_GET,
            Purpose.STATUS_OBSERVATION,
            GetCapabilities(),
        )
    )
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    limits = manifest["limits"]
    assert isinstance(limits, dict)
    return limits


def test_changing_the_configured_fetch_ceiling_moves_the_published_and_enforced_bound(
    scene: Scene,
) -> None:
    narrow = EffectiveLimits(
        max_page_size=DEFAULT_LIMITS.max_page_size,
        default_page_size=DEFAULT_LIMITS.default_page_size,
        max_fetch_bytes=8,
        max_enrollment_depth=DEFAULT_LIMITS.max_enrollment_depth,
    )
    service = build_service(scene.world, scene.providers, narrow)
    assert published_limits(service, scene)["max_fetch_bytes"] == 8

    result = succeeded(
        run(
            service,
            scene,
            Capability.SOURCES_FETCH,
            Purpose.SOURCE_INSPECTION,
            FetchSource(
                source_id=scene.source.source_id,
                source_object_id=scene.plain.source_object_id,
                representation=Representation.RAW_BYTES,
            ),
        )
    )
    assert result["byte_count"] == 8
    assert result["is_truncated"] is True


def test_changing_the_configured_page_size_moves_the_published_and_enforced_bound(
    scene: Scene,
) -> None:
    narrow = EffectiveLimits(
        max_page_size=1,
        default_page_size=1,
        max_fetch_bytes=DEFAULT_LIMITS.max_fetch_bytes,
        max_enrollment_depth=DEFAULT_LIMITS.max_enrollment_depth,
    )
    service = build_service(scene.world, scene.providers, narrow)
    assert published_limits(service, scene)["max_page_size"] == 1

    envelope = run(
        service,
        scene,
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        ListSources(source_id=scene.source.source_id, page_size=50),
    )
    result = succeeded(envelope)
    objects = result["objects"]
    assert isinstance(objects, list)
    assert len(objects) == 1
    assert envelope.disclosure is not None
    assert envelope.disclosure.truncation.is_truncated


def test_a_configured_page_size_cannot_exceed_the_bound_search_enforces(
    scene: Scene,
) -> None:
    """The published number is the enforced one even where the domain is stricter."""
    wide = EffectiveLimits(
        max_page_size=1000,
        default_page_size=1000,
        max_fetch_bytes=DEFAULT_LIMITS.max_fetch_bytes,
        max_enrollment_depth=DEFAULT_LIMITS.max_enrollment_depth,
    )
    service = build_service(scene.world, scene.providers, wide)
    limits = published_limits(service, scene)
    assert limits["max_page_size"] == 100
    assert limits["default_page_size"] == 100


def test_context_prepare_returns_empty_evidence_without_an_enrollment(scene: Scene) -> None:
    """No staged search: knowledge is unavailable rather than a complete no-match."""
    service = build_service(scene.world, scene.providers)
    result = succeeded(
        run(
            service,
            scene,
            Capability.CONTEXT_PREPARE,
            Purpose.CONTEXT_PREPARATION,
            PrepareContext(query="quarterly"),
        )
    )
    assert result["evidence"] == []
    assert result["total_items"] == 0
    assert result["instruction_authority"] is False
    assert "quarterly" not in result["query_fingerprint"]
    assert "planes_not_searched" not in result["limitations"]
    knowledge = next(row for row in result["coverage"] if row["plane"] == "knowledge")
    assert knowledge["state"] == "unavailable"
