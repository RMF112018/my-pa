"""KLP-WP-04: the server-owned direct-admission policy (FAST, unmarked).

KLP-AC-011, 024, 025, 026 (policy half), 030, 031 (decision half), 032, 098,
125. Every predicate below is either one of the eight committed seed rows
(read from the committed matrix copy, so a seed change reaches this module) or a
synthetic Knowledge-owned predicate that the seeds do not contain -- the only
seed that admits autonomously (`organization.operating_requirement`) is
multi-value, so supersession needs a synthetic single-current predicate.

Every identity here is synthetic.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.knowledge_assertion.admission import (
    AdmissionDecision,
    AdmissionEvidence,
    AdmissionPath,
    CurrentFact,
    DirectAdmissionBlocker,
    DirectAdmissionFacts,
    InvalidAdmissionFactsError,
    SourceProfileFacts,
    SubjectResolution,
    decide_direct_admission,
    derive_content_origin,
    independence_key,
    independent_corroboration_keys,
)
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeContentOrigin,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeOriginSystem,
    KnowledgePredicateAdmissionState,
    KnowledgeReadOnlyProofState,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
)
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

NOW: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)
PROFILE: Final = "kdsp_SyntheticProfileA1"
OTHER_PROFILE: Final = "kdsp_SyntheticProfileB2"
HASH: Final = hashlib.sha256(b"synthetic content").hexdigest()

OPERATING: Final = _predicate_from_seed(SEEDS["organization.operating_requirement"])
#: A synthetic Knowledge-owned single-current predicate that admits autonomously.
SINGLE: Final = dataclasses.replace(
    OPERATING,
    predicate_code="synthetic.single_fact",
    cardinality=KnowledgeCardinality.SINGLE_CURRENT,
    conflict_rule=KnowledgeConflictRule.REVIEW_ON_DIFFERENCE,
)


def _profile(**changes: object) -> SourceProfileFacts:
    base = SourceProfileFacts(
        source_profile_id=PROFILE,
        origin_system=KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS,
        authority_ceiling=KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE,
        direct_admission_enabled=True,
        read_only_proof_state=KnowledgeReadOnlyProofState.PROVEN,
        is_synthetic=False,
        disabled=False,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _external(**changes: object) -> AdmissionEvidence:
    base = AdmissionEvidence(
        identity_kind=KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
        role=KnowledgeEvidenceRole.DIRECT,
        content_hash=HASH,
        source_profile_id=PROFILE,
        origin_system=KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS,
        external_object_id="synthetic-doc-1",
        external_version_id="v7",
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _capture(role: KnowledgeEvidenceRole = KnowledgeEvidenceRole.SUPPORTING) -> AdmissionEvidence:
    return AdmissionEvidence(
        identity_kind=KnowledgeEvidenceIdentityKind.CAPTURE,
        role=role,
        content_hash=HASH,
        capture_id="cap_SyntheticCapture1",
    )


def _facts(predicate: KnowledgePredicate = OPERATING, **changes: object) -> DirectAdmissionFacts:
    base = DirectAdmissionFacts(
        predicate=predicate,
        profile=_profile(),
        subject=SubjectResolution.CANONICAL,
        evidence=(_external(),),
        candidate_effective_from=NOW - timedelta(days=1),
        now=NOW,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _current(**changes: object) -> CurrentFact:
    base = CurrentFact(
        assertion_id="kasr_SyntheticCurrent1",
        effective_from=NOW - timedelta(days=10),
        unresolved_counterevidence=False,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


# ---- the admitted baseline -----------------------------------------------------------


def test_every_precondition_held_direct_creates() -> None:
    decision = decide_direct_admission(_facts())
    assert decision == AdmissionDecision(
        path=AdmissionPath.DIRECT_CREATE, reason=KnowledgeSubmissionReason.CREATED
    )
    assert decision.outcome is KnowledgeSubmissionOutcome.DIRECT_CREATED


# ---- KLP-AC-024: server-owned, closed machine reasons -------------------------------


def test_the_decision_carries_only_closed_machine_tokens() -> None:
    decision = decide_direct_admission(_facts(profile=_profile(direct_admission_enabled=False)))
    assert decision.path is AdmissionPath.REVIEW
    assert isinstance(decision.reason, KnowledgeSubmissionReason)
    assert all(isinstance(code, DirectAdmissionBlocker) for code in decision.blockers)
    assert decision.blockers == (DirectAdmissionBlocker.PROFILE_DIRECT_ADMISSION_DISABLED,)


def test_the_policy_reads_no_caller_declared_field() -> None:
    """The facts are server-gathered: no field is named for caller intent."""
    names = {f.name for f in dataclasses.fields(DirectAdmissionFacts)} | {
        f.name for f in dataclasses.fields(AdmissionEvidence)
    }
    forbidden = {
        "excerpt",
        "text",
        "retrieved_at",
        "observed_at",
        "classification",
        "source_classification",
        "content_origin",
        "independence_key",
        "confidence",
        "outcome",
        "admission",
    }
    assert names.isdisjoint(forbidden), names & forbidden


def test_the_decision_names_the_stored_reason_matching_its_outcome() -> None:
    """Every reason the policy can return is legal for its outcome (DDL pairing)."""
    legal = {
        KnowledgeSubmissionOutcome.DIRECT_CREATED: {KnowledgeSubmissionReason.CREATED},
        KnowledgeSubmissionOutcome.DIRECT_SUPERSEDED: {KnowledgeSubmissionReason.SUPERSEDED},
        KnowledgeSubmissionOutcome.REVIEW_QUEUED: {
            KnowledgeSubmissionReason.REQUIRES_REVIEW,
            KnowledgeSubmissionReason.REQUIRES_OPERATOR,
        },
        KnowledgeSubmissionOutcome.REFUSED: {
            KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE,
            KnowledgeSubmissionReason.SOURCE_AUTHORITY_INSUFFICIENT,
            KnowledgeSubmissionReason.SUBJECT_NOT_CANONICAL,
            KnowledgeSubmissionReason.CAPTURE_ARCHIVED,
        },
    }
    decisions = [
        decide_direct_admission(_facts()),
        decide_direct_admission(_facts(SINGLE, current=_current())),
        decide_direct_admission(_facts(profile=_profile(disabled=True))),
        decide_direct_admission(_facts(subject=SubjectResolution.UNRESOLVED)),
        decide_direct_admission(_facts(capture_archived=True)),
        decide_direct_admission(_facts(evidence=(_capture(),))),
        decide_direct_admission(_facts(_predicate_from_seed(SEEDS["project.financial_fact"]))),
    ]
    for decision in decisions:
        assert decision.outcome is not None
        assert decision.reason in legal[decision.outcome]


# ---- KLP-AC-025 / KLP-AC-098: consequential predicates never direct-admit -------------


@pytest.mark.parametrize("code", sorted(SEEDS))
def test_no_seed_but_operating_requirement_ever_direct_admits(code: str) -> None:
    """With every other precondition at its most permissive, only S2 admits."""
    predicate = _predicate_from_seed(SEEDS[code])
    decision = decide_direct_admission(_facts(predicate))
    if code == "organization.operating_requirement":
        assert decision.path is AdmissionPath.DIRECT_CREATE
    elif predicate.canonical_owner.value != "knowledge_assertion":
        assert decision.path is AdmissionPath.DOMAIN_OWNED
        assert decision.reason is None
    else:
        assert decision.path is AdmissionPath.REVIEW
        assert DirectAdmissionBlocker.PREDICATE_NEVER_DIRECT_ADMITS in decision.blockers


@pytest.mark.parametrize(
    "code", sorted(c for c in SEEDS if SEEDS[c]["consequential_class"] != "none")
)
def test_a_consequential_seed_is_blocked_as_consequential(code: str) -> None:
    decision = decide_direct_admission(_facts(_predicate_from_seed(SEEDS[code])))
    assert decision.path in {AdmissionPath.REVIEW, AdmissionPath.DOMAIN_OWNED}
    if decision.path is AdmissionPath.REVIEW:
        assert DirectAdmissionBlocker.CONSEQUENTIAL_PREDICATE in decision.blockers
        assert decision.reason is KnowledgeSubmissionReason.REQUIRES_OPERATOR


def test_organization_payment_terms_is_financial_and_queues_for_the_operator() -> None:
    """KLP-AC-098: even an authoritative, proven, stable submission is queued."""
    predicate = _predicate_from_seed(SEEDS["organization.payment_terms"])
    assert predicate.consequential_class.value == "financial_fact"
    for current in (None, _current()):
        decision = decide_direct_admission(_facts(predicate, current=current))
        assert decision.path is AdmissionPath.REVIEW
        assert decision.reason is KnowledgeSubmissionReason.REQUIRES_OPERATOR
        assert {
            DirectAdmissionBlocker.CONSEQUENTIAL_PREDICATE,
            DirectAdmissionBlocker.PREDICATE_NEVER_DIRECT_ADMITS,
        } <= set(decision.blockers)


def test_the_consequential_guard_holds_on_its_own() -> None:
    """Prove the consequential blocker is independent of the admission policy column.

    The predicate CHECK makes `consequential + authoritative_source`
    unrepresentable, so a forged object (bypassing `__post_init__`) is the only
    way to exercise the second guard alone.
    """
    forged = object.__new__(KnowledgePredicate)
    for name in (f.name for f in dataclasses.fields(KnowledgePredicate)):
        object.__setattr__(forged, name, getattr(OPERATING, name))
    object.__setattr__(
        forged,
        "consequential_class",
        _predicate_from_seed(SEEDS["project.financial_fact"]).consequential_class,
    )
    assert forged.autonomous_admission_policy is (
        KnowledgeAutonomousAdmissionPolicy.AUTHORITATIVE_SOURCE
    )
    decision = decide_direct_admission(_facts(forged))
    assert decision.path is AdmissionPath.REVIEW
    assert decision.blockers == (DirectAdmissionBlocker.CONSEQUENTIAL_PREDICATE,)


# ---- KLP-AC-062 (policy half): only an enabled, proven, authoritative profile --------


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        (
            {"direct_admission_enabled": False},
            DirectAdmissionBlocker.PROFILE_DIRECT_ADMISSION_DISABLED,
        ),
        (
            {"read_only_proof_state": KnowledgeReadOnlyProofState.UNPROVEN},
            DirectAdmissionBlocker.PROFILE_READ_ONLY_UNPROVEN,
        ),
        (
            {"read_only_proof_state": KnowledgeReadOnlyProofState.REVOKED},
            DirectAdmissionBlocker.PROFILE_READ_ONLY_UNPROVEN,
        ),
        (
            {"authority_ceiling": KnowledgeEvidenceAuthority.OBSERVED_SOURCE},
            DirectAdmissionBlocker.PROFILE_CEILING_NOT_AUTHORITATIVE,
        ),
    ],
    ids=["disabled-direct", "unproven", "revoked", "observed-ceiling"],
)
def test_each_profile_control_alone_withholds_direct_admission(
    changes: dict[str, object], blocker: DirectAdmissionBlocker
) -> None:
    decision = decide_direct_admission(_facts(profile=_profile(**changes)))
    assert decision.path is AdmissionPath.REVIEW
    assert decision.reason is KnowledgeSubmissionReason.REQUIRES_REVIEW
    assert decision.blockers == (blocker,)


def test_a_disabled_profile_is_refused_before_anything_else() -> None:
    decision = decide_direct_admission(
        _facts(profile=_profile(disabled=True), subject=SubjectResolution.UNRESOLVED)
    )
    assert decision == AdmissionDecision(
        path=AdmissionPath.REFUSE, reason=KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE
    )


def test_a_profile_below_the_predicate_minimum_authority_is_refused() -> None:
    demanding = dataclasses.replace(
        OPERATING, minimum_evidence_authority=KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE
    )
    decision = decide_direct_admission(
        _facts(
            demanding,
            profile=_profile(
                authority_ceiling=KnowledgeEvidenceAuthority.OBSERVED_SOURCE,
                direct_admission_enabled=False,
            ),
        )
    )
    assert decision.reason is KnowledgeSubmissionReason.SOURCE_AUTHORITY_INSUFFICIENT
    assert decision.path is AdmissionPath.REFUSE


# ---- KLP-AC-011: external direct admission needs a stable version or content hash ----


def test_a_stable_content_hash_without_a_version_admits() -> None:
    decision = decide_direct_admission(_facts(evidence=(_external(external_version_id=None),)))
    assert decision.path is AdmissionPath.DIRECT_CREATE


def test_a_version_without_a_valid_content_hash_admits() -> None:
    decision = decide_direct_admission(_facts(evidence=(_external(content_hash="unhashed"),)))
    assert decision.path is AdmissionPath.DIRECT_CREATE


@pytest.mark.parametrize("version", [None, "", "   "], ids=["none", "empty", "blank"])
def test_neither_a_version_nor_a_content_hash_never_direct_admits(version: str | None) -> None:
    unstable = _external(external_version_id=version, content_hash="not-a-sha256")
    decision = decide_direct_admission(_facts(evidence=(unstable,)))
    assert decision.path is AdmissionPath.REVIEW
    assert decision.blockers == (DirectAdmissionBlocker.EXTERNAL_IDENTITY_UNSTABLE,)


@pytest.mark.parametrize(
    "evidence",
    [
        (_capture(KnowledgeEvidenceRole.DIRECT),),
        (_external(role=KnowledgeEvidenceRole.SUPPORTING),),
        (_external(source_profile_id=OTHER_PROFILE),),
    ],
    ids=["capture-only", "external-only-supporting", "another-profiles-object"],
)
def test_direct_admission_needs_direct_external_evidence_from_the_submitting_profile(
    evidence: tuple[AdmissionEvidence, ...],
) -> None:
    decision = decide_direct_admission(_facts(evidence=evidence))
    assert decision.path is AdmissionPath.REVIEW
    assert decision.blockers == (DirectAdmissionBlocker.NO_DIRECT_EXTERNAL_EVIDENCE,)


def test_cited_counterevidence_or_unavailable_evidence_never_direct_admits() -> None:
    counter = decide_direct_admission(
        _facts(evidence=(_external(), _capture(KnowledgeEvidenceRole.COUNTEREVIDENCE)))
    )
    assert counter.blockers == (DirectAdmissionBlocker.COUNTEREVIDENCE_CITED,)
    unavailable = decide_direct_admission(_facts(evidence=(_external(available=False),)))
    assert unavailable.blockers == (DirectAdmissionBlocker.EVIDENCE_UNAVAILABLE,)


# ---- KLP-AC-026 (policy half): a single canonical subject only -----------------------


@pytest.mark.parametrize(
    "resolution",
    [member for member in SubjectResolution if member is not SubjectResolution.CANONICAL],
)
def test_a_non_canonical_subject_is_refused_never_created(resolution: SubjectResolution) -> None:
    decision = decide_direct_admission(_facts(subject=resolution))
    assert decision == AdmissionDecision(
        path=AdmissionPath.REFUSE, reason=KnowledgeSubmissionReason.SUBJECT_NOT_CANONICAL
    )


def test_an_archived_capture_is_refused() -> None:
    decision = decide_direct_admission(_facts(capture_archived=True))
    assert decision.reason is KnowledgeSubmissionReason.CAPTURE_ARCHIVED


# ---- KLP-AC-030 / KLP-AC-031 (decision half): supersession ---------------------------


def test_a_later_effective_from_with_every_precondition_supersedes() -> None:
    decision = decide_direct_admission(_facts(SINGLE, current=_current()))
    assert decision == AdmissionDecision(
        path=AdmissionPath.DIRECT_SUPERSEDE,
        reason=KnowledgeSubmissionReason.SUPERSEDED,
        supersedes_assertion_id="kasr_SyntheticCurrent1",
    )
    assert decision.outcome is KnowledgeSubmissionOutcome.DIRECT_SUPERSEDED


def test_an_equal_effective_from_supersedes() -> None:
    same = NOW - timedelta(days=3)
    decision = decide_direct_admission(
        _facts(SINGLE, candidate_effective_from=same, current=_current(effective_from=same))
    )
    assert decision.path is AdmissionPath.DIRECT_SUPERSEDE


@pytest.mark.parametrize(
    ("candidate", "current", "blocker"),
    [
        (None, _current(), DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_UNKNOWN),
        (
            NOW,
            _current(effective_from=None),
            DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_UNKNOWN,
        ),
        (
            NOW - timedelta(days=20),
            _current(),
            DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_REGRESSES,
        ),
        (NOW + timedelta(seconds=1), _current(), DirectAdmissionBlocker.SUCCESSOR_FUTURE_DATED),
        (
            NOW - timedelta(days=1),
            _current(unresolved_counterevidence=True),
            DirectAdmissionBlocker.PREDECESSOR_COUNTEREVIDENCE_UNRESOLVED,
        ),
    ],
    ids=[
        "successor-unknown",
        "predecessor-unknown",
        "regresses",
        "future-dated",
        "counterevidence",
    ],
)
def test_each_supersession_precondition_alone_queues_instead(
    candidate: datetime | None, current: CurrentFact, blocker: DirectAdmissionBlocker
) -> None:
    decision = decide_direct_admission(
        _facts(SINGLE, candidate_effective_from=candidate, current=current)
    )
    assert decision.path is AdmissionPath.REVIEW
    assert decision.reason is KnowledgeSubmissionReason.REQUIRES_REVIEW
    assert decision.blockers == (DirectAdmissionBlocker.CURRENT_FACT_DIFFERS, blocker)
    assert decision.supersedes_assertion_id is None


def test_a_newer_observation_alone_never_supersedes() -> None:
    """KLP-AC-030: no observation timestamp reaches the policy at all.

    The candidate was observed *now* (newest) but states no `effective_from`;
    the predecessor is old. Recency of observation is not a fact the policy
    can see, so it cannot establish truth or supersession.
    """
    assert "retrieved_at" not in {f.name for f in dataclasses.fields(AdmissionEvidence)}
    decision = decide_direct_admission(
        _facts(SINGLE, candidate_effective_from=None, current=_current())
    )
    assert decision.path is AdmissionPath.REVIEW
    assert DirectAdmissionBlocker.SUCCESSOR_EFFECTIVE_FROM_UNKNOWN in decision.blockers


def test_supersession_never_happens_without_the_direct_preconditions() -> None:
    decision = decide_direct_admission(
        _facts(SINGLE, profile=_profile(direct_admission_enabled=False), current=_current())
    )
    assert decision.path is AdmissionPath.REVIEW
    assert decision.blockers == (DirectAdmissionBlocker.PROFILE_DIRECT_ADMISSION_DISABLED,)


def test_a_current_slot_on_a_multi_value_predicate_is_refused_as_a_caller_bug() -> None:
    with pytest.raises(InvalidAdmissionFactsError):
        decide_direct_admission(_facts(OPERATING, current=_current()))


def test_a_retired_head_is_refused_as_a_caller_bug() -> None:
    retired = dataclasses.replace(
        OPERATING, admission_state=KnowledgePredicateAdmissionState.RETIRED
    )
    with pytest.raises(InvalidAdmissionFactsError):
        decide_direct_admission(_facts(retired))


# ---- KLP-AC-032 / KLP-AC-125: server-derived origin and independence -----------------


def test_the_content_origin_vocabulary_has_no_unknown_or_derived_token() -> None:
    values = {member.value for member in KnowledgeContentOrigin}
    assert values == {"external_source", "synthetic_source", "capture", "relationship_memory"}
    for forbidden in ("unknown", "ai_generated", "knowledge_assertion", "record_event"):
        assert forbidden not in values
        assert forbidden not in {member.value for member in KnowledgeEvidenceIdentityKind}


@pytest.mark.parametrize(
    ("kind", "synthetic", "expected"),
    [
        (
            KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
            False,
            KnowledgeContentOrigin.EXTERNAL_SOURCE,
        ),
        (
            KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
            True,
            KnowledgeContentOrigin.SYNTHETIC_SOURCE,
        ),
        (KnowledgeEvidenceIdentityKind.CAPTURE, None, KnowledgeContentOrigin.CAPTURE),
        (
            KnowledgeEvidenceIdentityKind.RELATIONSHIP_MEMORY,
            None,
            KnowledgeContentOrigin.RELATIONSHIP_MEMORY,
        ),
    ],
)
def test_content_origin_follows_identity_shape_and_profile_only(
    kind: KnowledgeEvidenceIdentityKind, synthetic: bool | None, expected: KnowledgeContentOrigin
) -> None:
    assert derive_content_origin(kind, profile_is_synthetic=synthetic) is expected


def test_external_content_origin_needs_the_profile_flag() -> None:
    with pytest.raises(InvalidAdmissionFactsError):
        derive_content_origin(
            KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT, profile_is_synthetic=None
        )


def test_the_independence_key_ignores_every_caller_varying_field() -> None:
    base = _external()
    for varied in (
        _external(role=KnowledgeEvidenceRole.SUPPORTING),
        _external(external_version_id="v8"),
        _external(content_hash=hashlib.sha256(b"other bytes").hexdigest()),
        _external(available=False),
        _external(source_profile_id=OTHER_PROFILE),
    ):
        assert independence_key(varied) == independence_key(base)


def test_the_same_object_through_two_profiles_is_one_source() -> None:
    keys = independent_corroboration_keys(
        (_external(), _external(source_profile_id=OTHER_PROFILE, external_version_id="v9"))
    )
    assert len(keys) == 1


def test_distinct_objects_and_origins_are_distinct_sources() -> None:
    keys = independent_corroboration_keys(
        (
            _external(),
            _external(external_object_id="synthetic-doc-2"),
            _external(origin_system=KnowledgeOriginSystem.OUTLOOK_MAIL),
            _capture(),
        )
    )
    assert len(keys) == 4


def test_counterevidence_never_corroborates() -> None:
    keys = independent_corroboration_keys(
        (_external(role=KnowledgeEvidenceRole.COUNTEREVIDENCE), _capture())
    )
    assert keys == {independence_key(_capture())}


def test_trigger_events_have_no_way_into_corroboration() -> None:
    """KLP-AC-125: a `knowledge_assertion` Record Event is a trigger, never evidence.

    The corroboration function reads only cited evidence; its signature admits
    nothing else, so no Knowledge-derived input can count toward independence.
    """
    parameters = inspect.signature(independent_corroboration_keys).parameters
    assert list(parameters) == ["evidence"]
    facts_fields = {f.name for f in dataclasses.fields(DirectAdmissionFacts)}
    assert not any("trigger" in name for name in facts_fields)
