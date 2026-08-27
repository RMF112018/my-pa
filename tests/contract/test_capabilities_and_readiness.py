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

import re
from dataclasses import fields, is_dataclass
from typing import Final

import pytest
from pydantic import ValidationError

from my_pa.application import commands
from my_pa.application.capabilities import (
    CONTINUATION_FIELD_NAMES,
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
    assert len(names) == len(Capability) == 102
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
        "commitments.search",
        "commitments.history",
        "commitments.waiting_on",
        "commitments.create",
        "commitments.update",
        "commitments.close",
        "context.prepare",
        "context.feedback",
        "goodnotes.work",
        "goodnotes.content",
        "gsqs.start",
        "gsqs.status",
        "gsqs.step",
        "entities.search",
        "entities.get",
        "entities.resolve",
        "entities.context",
        "entities.relationships",
        "entities.unresolved_mentions",
        "entities.assignments.list",
        "entities.assignments.create",
        "entities.assignments.revise",
        "entities.assignments.end",
        "entities.relationships.create",
        "entities.relationships.revise",
        "entities.relationships.end",
        "entities.observations.list",
        "entities.observe",
        "entities.unresolved_mentions.resolve",
        "goodnotes.propose",
        "reports.begin_cycle",
        "reports.commit",
        "reports.record_run_state",
        "reports.read",
        "reports.latest",
        "reports.list",
        "reports.search",
        "reports.resolve_set",
        "relationship_memory.create",
        "relationship_memory.get",
        "relationship_memory.list",
        "relationship_memory.search",
        "relationship_memory.history",
        "relationship_memory.revise",
        "relationship_memory.archive",
        "relationship_memory.restore",
        "relationship_memory.propose",
        "entities.proposals.create",
        "entities.merge.preview",
        "entities.merge",
        "entities.identifiers.list",
        "entities.aliases.list",
        "entities.create",
        "entities.update",
        "entities.archive",
        "entities.restore",
        "entities.identifiers.bind",
        "entities.identifiers.retire",
        "entities.identifiers.supersede",
        "entities.aliases.add",
        "entities.aliases.retire",
        "entities.aliases.supersede",
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


def test_the_operator_only_set_is_enrollment_and_the_governed_merge() -> None:
    """Three, and the third and fourth are the first knowledge-plane members.

    This test was named `test_only_sources_enroll_is_operator_only` and asserted
    a set of one for every package up to `WP-RI-B-06`. The name is corrected
    rather than the assertion loosened: the claim it was making -- that
    `_OPERATOR_ONLY` holds exactly what somebody decided it holds -- is the same
    claim, and the set it holds has changed.

    The test `_OPERATOR_ONLY` applies is whether a capability *widens the scope a
    later request is evaluated against*. Enrolling a source does. A governed
    merge does too: afterwards every alias, identifier, assignment, edge,
    observation, proposal, review case and memory that named a merged-away entity
    is reached through the survivor, so a grant issued before the merge returns
    records it did not return before. The preview is in beside the apply because
    it reads the exact identities of two people, which is the disclosure the
    apply's authority exists to protect.
    """
    operator_only = {s.name for s in manifest().capabilities if s.operator_only}
    assert operator_only == {
        Capability.SOURCES_ENROLL,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
    }
    assert is_operator_only(Capability.SOURCES_ENROLL)
    assert is_operator_only(Capability.ENTITIES_MERGE_PREVIEW)
    assert is_operator_only(Capability.ENTITIES_MERGE)
    # And no capture, review, continuity, document, task, commitment, report,
    # entity-authoring or memory name joined them, which is the half of this
    # claim that keeps the boundary from spreading by precedent.
    assert not any(
        is_operator_only(capability)
        for capability in Capability
        if capability.value.startswith(("capture.", "review.", "relationship_memory."))
    )


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


def test_the_continuation_limitation_describes_the_build_that_publishes_it() -> None:
    """A limitation is a claim about *this* build, not about the contract.

    Three versions of this sentence have been wrong. It was a hardcoded
    "listings issue no continuation cursor" that outlived its condition when
    `entities.relationships` began issuing one. Deriving it from the commands
    that accept `after` fixed that and introduced the opposite falsehood — a
    default build reported that capability `not_implemented` in the very
    envelope promising it paged. Intersecting with the served set fixed *that*
    and left a third: `knowledge.search` pages via a field called `cursor`, is
    served in every build, and was being described as unpageable.

    All three are asserted, because each fix has so far produced the next.
    """
    withheld = {capability for capability in Capability if capability.value.startswith("entities.")}
    default = build_readiness_report(manifest(implemented=EVERYTHING - withheld))
    composed = build_readiness_report(manifest())

    def _cursor_line(report: ReadinessReport) -> str:
        lines = [line for line in report.limitations if "continuation cursor" in line]
        assert len(lines) == 1, lines
        return lines[0]

    default_line = _cursor_line(default)
    assert "knowledge.search" in default_line, (
        "a build serving a paginated capability must say so, whatever its field is called"
    )
    assert "entities.relationships" not in default_line, (
        "a build that withholds a capability must not advertise its cursor"
    )

    composed_line = _cursor_line(composed)
    assert "entities.relationships" in composed_line
    assert "knowledge.search" in composed_line


#: Field names that read as a continuation token. Deliberately wider than the
#: set the derivation honours, so a command introducing a new spelling fails
#: here instead of being silently unread.
_CONTINUATION_SHAPED: Final = re.compile(r"cursor|after|offset|page_token|continuation", re.I)


def test_no_command_carries_a_continuation_field_the_derivation_cannot_read() -> None:
    """A third spelling must fail loudly, not go unread.

    `capabilities.get` derives its continuation limitation from the field names
    in `CONTINUATION_FIELD_NAMES`. That derivation read only `after` until
    `knowledge.search` — paginated since long before this plane, via a field
    called `cursor` — was found publishing the opposite of its own behaviour in
    every build. The failure was not the missing name; it was that a name the
    derivation did not know cost nothing to introduce.
    """
    unread: list[str] = []
    for member in vars(commands).values():
        capability = getattr(member, "capability", None)
        if not isinstance(capability, Capability) or not is_dataclass(member):
            continue
        for field in fields(member):
            if _CONTINUATION_SHAPED.search(field.name) and (
                field.name not in CONTINUATION_FIELD_NAMES
            ):
                unread.append(f"{capability.value}.{field.name}")
    assert not unread, (
        "these fields read as continuation tokens but are not in "
        f"`CONTINUATION_FIELD_NAMES`, so `capabilities.get` will describe their "
        f"capability as unpageable: {unread}"
    )
