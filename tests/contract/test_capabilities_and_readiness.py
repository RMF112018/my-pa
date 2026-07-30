"""The capability manifest and readiness report are truthful."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.contracts.v1 import (
    Availability,
    CapabilityManifest,
    CapabilityStatus,
    ReadinessReport,
    ReadinessState,
)
from my_pa.domain.identity.operation import Capability, is_operator_only


def test_manifest_lists_every_capability_exactly_once() -> None:
    manifest = build_capability_manifest()
    names = [status.name for status in manifest.capabilities]
    assert len(names) == len(Capability) == 8
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
    }


def test_incomplete_manifest_is_rejected() -> None:
    full = build_capability_manifest()
    with pytest.raises(ValidationError, match="incomplete"):
        CapabilityManifest(
            capabilities=full.capabilities[:-1],
            content_types=full.content_types,
            limits=full.limits,
        )


def test_duplicate_capability_is_rejected() -> None:
    full = build_capability_manifest()
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
    manifest = build_capability_manifest()
    operator_only = {s.name for s in manifest.capabilities if s.operator_only}
    assert operator_only == {Capability.SOURCES_ENROLL}
    assert is_operator_only(Capability.SOURCES_ENROLL)


def test_phase_01_reports_nothing_as_available() -> None:
    manifest = build_capability_manifest()
    assert all(s.availability is Availability.NOT_IMPLEMENTED for s in manifest.capabilities)


def test_pdf_remains_decision_gated_and_is_not_omitted() -> None:
    types = {c.media_type: c.availability for c in build_capability_manifest().content_types}
    assert types["application/pdf"] is Availability.DECISION_GATED
    assert "text/plain" in types
    assert "text/markdown" in types


def test_readiness_reports_contracts_only() -> None:
    report = build_readiness_report()
    assert report.state is ReadinessState.CONTRACTS_ONLY
    assert report.implemented_capabilities == 0
    assert report.total_capabilities == len(Capability)
    assert report.limitations


def test_readiness_cannot_claim_ready_without_implementation() -> None:
    with pytest.raises(ValidationError, match="requires every capability"):
        ReadinessReport(state=ReadinessState.READY, implemented_capabilities=0)


def test_contracts_only_cannot_claim_implemented_capabilities() -> None:
    with pytest.raises(ValidationError, match="requires no implemented capability"):
        ReadinessReport(state=ReadinessState.CONTRACTS_ONLY, implemented_capabilities=3)


def test_readiness_is_derived_from_the_manifest_not_asserted() -> None:
    manifest = build_capability_manifest()
    all_available = manifest.model_copy(
        update={
            "capabilities": tuple(
                s.model_copy(update={"availability": Availability.AVAILABLE})
                for s in manifest.capabilities
            )
        }
    )
    assert build_readiness_report(all_available).state is ReadinessState.READY

    half = manifest.model_copy(
        update={
            "capabilities": (
                manifest.capabilities[0].model_copy(
                    update={"availability": Availability.AVAILABLE}
                ),
                *manifest.capabilities[1:],
            )
        }
    )
    assert build_readiness_report(half).state is ReadinessState.DEGRADED


def test_limits_are_internally_consistent() -> None:
    limits = build_capability_manifest().limits
    assert limits.default_page_size <= limits.max_page_size
    assert limits.max_enrollment_depth == 0


def test_manifest_exposes_no_internal_topology() -> None:
    rendered = build_capability_manifest().to_canonical_json()
    for token in ("postgres", "sqlalchemy", "fastapi", "/Users/", "localhost", "5432", "ssh"):
        assert token not in rendered.lower()
