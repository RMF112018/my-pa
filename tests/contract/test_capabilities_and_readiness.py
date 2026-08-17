"""The capability manifest and readiness report are truthful, and derived.

The manifest is built from a set of implemented capabilities and a set of
effective limits, and never from a constant inside the builder. That is what
these tests hold: change what is implemented and the manifest changes; change a
limit and the published limit changes. `tests/contract/test_application_capabilities.py`
is where the *real* set is shown to come from the service's own dispatch table,
and where a published limit is shown to be the enforced one; here the builder is
exercised directly, including the states a running service cannot currently
produce.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from my_pa.application.capabilities import (
    DECISION_GATED_MEDIA_TYPE,
    build_capability_manifest,
    build_readiness_report,
)
from my_pa.contracts.v1 import (
    Availability,
    CapabilityManifest,
    CapabilityStatus,
    EffectiveLimits,
    ReadinessReport,
    ReadinessState,
)
from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES
from my_pa.domain.identity.operation import Capability, is_operator_only

#: The limits `D-24` makes the configuration defaults.
LIMITS = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)

EVERYTHING = frozenset(Capability)
NOTHING: frozenset[Capability] = frozenset()


def manifest(implemented: frozenset[Capability] = EVERYTHING) -> CapabilityManifest:
    return build_capability_manifest(implemented=implemented, limits=LIMITS)


def test_manifest_lists_every_capability_exactly_once() -> None:
    names = [status.name for status in manifest().capabilities]
    assert len(names) == len(Capability) == 47
    assert set(names) == set(Capability)
    assert len(set(names)) == len(names)


def test_capability_names_match_the_published_contract() -> None:
    assert {c.value for c in Capability} == {
        "capabilities.get",
        "sources.list",
        "sources.metadata",
        "sources.fetch",
        "sources.status",
        "sources.enroll",
        "knowledge.search",
        "knowledge.read",
        "knowledge.reveal",
        "knowledge.coverage",
        "documents.create",
        "documents.revise",
        "documents.read",
        "documents.list",
        "documents.archive",
        "documents.restore",
        "capture.create",
        "capture.revise",
        "capture.read",
        "capture.list",
        "capture.search",
        "review.list",
        "review.decide",
        "continuity.pulse",
        "continuity.situations",
        "continuity.projects",
        "continuity.projects.create",
        "continuity.situations.create",
        "continuity.tasks.create",
        "tasks.read",
        "tasks.list",
        "tasks.search",
        "tasks.history",
        "tasks.create",
        "tasks.update",
        "tasks.transition",
        "tasks.bulk_preview",
        "tasks.bulk_confirm",
        "commitments.read",
        "commitments.list",
        "commitments.waiting_on",
        "commitments.create",
        "commitments.close",
        "context.prepare",
        "context.feedback",
        "goodnotes.work",
        "goodnotes.propose",
    }


def test_incomplete_manifest_is_rejected() -> None:
    full = manifest()
    with pytest.raises(ValidationError, match="incomplete"):
        CapabilityManifest(
            capabilities=full.capabilities[:-1],
            content_types=full.content_types,
            limits=full.limits,
        )


def test_duplicate_capability_is_rejected() -> None:
    full = manifest()
    with pytest.raises(ValidationError, match=r"duplicates|incomplete"):
        CapabilityManifest(
            capabilities=(*full.capabilities, full.capabilities[0]),
            content_types=full.content_types,
            limits=full.limits,
        )


def test_operator_only_flag_cannot_contradict_the_domain() -> None:
    with pytest.raises(ValidationError, match="contradicts the domain rule"):
        CapabilityStatus(
            name=Capability.SOURCES_ENROLL,
            availability=Availability.NOT_IMPLEMENTED,
            operator_only=False,
        )


def test_only_sources_enroll_is_operator_only() -> None:
    operator_only = {s.name for s in manifest().capabilities if s.operator_only}
    assert operator_only == {Capability.SOURCES_ENROLL}
    assert is_operator_only(Capability.SOURCES_ENROLL)


def test_availability_is_derived_from_what_is_implemented() -> None:
    """The whole point of the change: no constant decides this.

    A build wired for nothing reports nothing available; a build wired for
    everything reports everything; and one capability moving moves exactly one
    row. A manifest built from a constant would answer identically in all three.
    """
    assert all(
        s.availability is Availability.NOT_IMPLEMENTED for s in manifest(NOTHING).capabilities
    )
    assert all(s.availability is Availability.AVAILABLE for s in manifest().capabilities)

    without_read = manifest(EVERYTHING - {Capability.KNOWLEDGE_READ})
    availability = {s.name: s.availability for s in without_read.capabilities}
    assert availability[Capability.KNOWLEDGE_READ] is Availability.NOT_IMPLEMENTED
    assert availability[Capability.KNOWLEDGE_SEARCH] is Availability.AVAILABLE


def test_content_types_are_derived_from_what_the_extractor_reads() -> None:
    types = {c.media_type: c.availability for c in manifest().content_types}
    assert set(types) == SUPPORTED_MEDIA_TYPES | {DECISION_GATED_MEDIA_TYPE}
    for media_type in SUPPORTED_MEDIA_TYPES:
        assert types[media_type] is Availability.AVAILABLE


def test_pdf_remains_decision_gated_and_is_not_omitted() -> None:
    """`P00-OD-003` is an operator decision, not a missing implementation."""
    for implemented in (NOTHING, EVERYTHING):
        types = {c.media_type: c.availability for c in manifest(implemented).content_types}
        assert types[DECISION_GATED_MEDIA_TYPE] is Availability.DECISION_GATED


def test_a_build_that_cannot_read_content_reports_no_readable_media_type() -> None:
    types = {c.media_type: c.availability for c in manifest(NOTHING).content_types}
    for media_type in SUPPORTED_MEDIA_TYPES:
        assert types[media_type] is Availability.NOT_IMPLEMENTED


def test_readiness_reports_contracts_only_only_when_nothing_is_wired() -> None:
    report = build_readiness_report(manifest(NOTHING))
    assert report.state is ReadinessState.CONTRACTS_ONLY
    assert report.implemented_capabilities == 0
    assert report.total_capabilities == len(Capability)
    assert report.limitations


def test_readiness_stops_reporting_contracts_only_when_the_manifest_stops_saying_so() -> None:
    report = build_readiness_report(manifest())
    assert report.state is ReadinessState.READY
    assert report.implemented_capabilities == len(Capability)


def test_readiness_cannot_claim_ready_without_implementation() -> None:
    with pytest.raises(ValidationError, match="requires every capability"):
        ReadinessReport(state=ReadinessState.READY, implemented_capabilities=0)


def test_contracts_only_cannot_claim_implemented_capabilities() -> None:
    with pytest.raises(ValidationError, match="requires no implemented capability"):
        ReadinessReport(state=ReadinessState.CONTRACTS_ONLY, implemented_capabilities=3)


def test_readiness_is_derived_from_the_manifest_not_asserted() -> None:
    half = manifest(frozenset({Capability.CAPABILITIES_GET}))
    assert build_readiness_report(half).state is ReadinessState.DEGRADED
    assert build_readiness_report(half).implemented_capabilities == 1


def test_readiness_limitations_track_the_manifest() -> None:
    """A limitation cannot outlive the condition that produced it."""
    partial = " ".join(build_readiness_report(manifest(NOTHING)).limitations)
    complete = " ".join(build_readiness_report(manifest()).limitations)
    assert "capabilities are unwired" in partial
    assert "capabilities are unwired" not in complete
    assert DECISION_GATED_MEDIA_TYPE in complete
    assert "Model proposals and semantic retrieval are disabled" in complete


def test_nothing_published_claims_the_audit_is_not_durable() -> None:
    """The limitation that did outlive its condition, and the guard against it.

    A readiness line and a disclosure token both said no durable audit store
    existed. WP-4B1 built one — `SqlAlchemyAuditSink` commits each event on its
    own connection into `knowledge.audit_events` — and both sentences stayed on
    the wire, because each was written *beside* the derivation rather than
    inside it. They were inert while nothing served a disclosure and became a
    false statement to a client the moment WP-4B2a did.

    Asserted from both directions: the store is imported here, so the condition
    the claim denied is shown to hold, and every string either module can
    publish is required not to deny it.
    """
    from my_pa.application.disclosure import Limitation
    from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink

    assert callable(SqlAlchemyAuditSink.record), "there is no durable sink to be truthful about"

    published = [
        *build_readiness_report(manifest()).limitations,
        *build_readiness_report(manifest(NOTHING)).limitations,
        *(member.value for member in Limitation),
    ]
    for claim in published:
        assert "audit" not in claim.lower(), f"a published limitation names the audit: {claim}"


def test_limits_are_the_ones_supplied() -> None:
    limits = manifest().limits
    assert limits == LIMITS
    assert limits.default_page_size <= limits.max_page_size
    assert limits.max_enrollment_depth == 0


def test_a_different_configured_limit_produces_a_different_manifest() -> None:
    other = EffectiveLimits(
        max_page_size=25, default_page_size=5, max_fetch_bytes=1024, max_enrollment_depth=2
    )
    published = build_capability_manifest(implemented=EVERYTHING, limits=other).limits
    assert published.max_fetch_bytes == 1024
    assert published.max_page_size == 25
    assert published.max_enrollment_depth == 2


def test_default_page_size_cannot_exceed_the_maximum() -> None:
    with pytest.raises(ValidationError, match="cannot exceed max_page_size"):
        EffectiveLimits(
            max_page_size=10, default_page_size=50, max_fetch_bytes=1024, max_enrollment_depth=0
        )


def test_manifest_rejects_a_wrong_contract_version() -> None:
    full = manifest()
    with pytest.raises(ValidationError, match="unsupported contract_version"):
        CapabilityManifest(
            contract_version="v2",
            capabilities=full.capabilities,
            content_types=full.content_types,
            limits=full.limits,
        )


def test_manifest_rejects_duplicate_content_types() -> None:
    full = manifest()
    with pytest.raises(ValidationError, match="content type manifest contains duplicates"):
        CapabilityManifest(
            capabilities=full.capabilities,
            content_types=(*full.content_types, full.content_types[0]),
            limits=full.limits,
        )


def test_manifest_exposes_no_internal_topology() -> None:
    rendered = manifest().to_canonical_json()
    for token in ("postgres", "sqlalchemy", "fastapi", "/Users/", "localhost", "5432", "ssh"):
        assert token not in rendered.lower()
