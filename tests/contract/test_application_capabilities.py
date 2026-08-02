"""All eight capabilities execute real behaviour, and disclose what they did.

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

from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeProviders,
    FakeUnitOfWork,
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
    assert readiness["state"] == ReadinessState.READY.value
    assert readiness["implemented_capabilities"] == len(Capability)
    assert readiness["limitations"]


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


def staged_record(scene: Scene, text: str = "Quarterly revenue review.") -> KnowledgeRecord:
    record = KnowledgeRecord(
        knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        enrollment_id=scene.enrollment.enrollment_id,
        media_type=MARKDOWN,
        text=text,
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


def test_knowledge_read_returns_the_record_and_its_mandatory_provenance(
    scene: Scene,
) -> None:
    record = staged_record(scene)
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
    provenance = result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["source_id"] == scene.source.source_id
    assert provenance["version_id"] == scene.markdown.version_id
    assert provenance["trust_level"] == TrustLevel.SOURCE_BOUND_DERIVED.value


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


def test_a_root_selector_never_claims_whole_scope_coverage(
    world: World, fixture_root: Path
) -> None:
    """No measured denominator means no state that asserts the whole scope."""
    principal = operator()
    source = world.add_source()
    provider = build_provider(fixture_root, source.source_id)
    children = list(provider.list_children())
    root = next(c for c in children if c.kind is ObjectKind.CONTAINER)
    enrollment = world.add_enrollment(
        source_id=source.source_id,
        principal_id=principal.principal_id,
        root_object_id=root.source_object_id,
    )
    world.record_outcome(
        enrollment_id=enrollment.enrollment_id,
        source_object_id=root.source_object_id,
        status=ExtractionStatus.EXTRACTED,
    )
    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        providers=FakeProviders({source.source_id: provider}),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, principal),
        ListSources(source_id=source.source_id),
        principal=principal,
    )
    assert envelope.disclosure is not None
    assert envelope.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert envelope.disclosure.partial_result
    assert Limitation.ELIGIBLE_TOTAL_NOT_PERSISTED.value in envelope.disclosure.limitations
    assert Limitation.SCOPE_IS_SOURCE_WIDE.value in envelope.disclosure.limitations


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
