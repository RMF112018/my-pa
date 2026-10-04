"""Golden vectors for the frozen request digest and fingerprint v1 (KLP-WP-01).

AC-009, AC-120 (WP-01 slice). The expected hex digests below were computed once
from the hand-written canonical JSON strings in this file, not by the module
under test, so a silent change to `domain.knowledge_assertion.digest` -- its
key set, encoding, ordering or normalization -- turns these red. A deliberate
change to either formula needs a new version number and a new schema revision
(R6 plan sections 6.2 and 6.5); it must never be made by editing these hexes.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from my_pa.domain.capture.proposal import RiskClass
from my_pa.domain.common.classification import Classification
from my_pa.domain.knowledge_assertion.assertion import KnowledgeAssertionCandidate, KnowledgeValue
from my_pa.domain.knowledge_assertion.digest import (
    DigestEvidence,
    OwnerRef,
    assertion_fingerprint,
    canonical_json_bytes,
    fingerprint_object,
    normalize_text,
    request_digest,
    request_digest_object,
)
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.proposal import KnowledgeProposalDraft
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeNormalizationRule,
    KnowledgeOwnerRefKind,
    KnowledgePredicateAdmissionState,
    KnowledgeQualifierRule,
    KnowledgeReviewRequirement,
    KnowledgeSubjectKind,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)
from my_pa.domain.relationship.entity import EntityType

H1 = "11" * 32
H2 = "22" * 32
H3 = "33" * 32
SCOPE = "ab" * 32

#: Hand-written canonical JSON of vector D1 (autonomous submit, text value).
D1_CANONICAL = (
    '{"effective_from":"2026-10-01T12:00:00.123456Z","effective_to":null,"evidence":['
    '{"content_hash":"' + H3 + '","excerpt_sha256":null,"identity":["cap_Capture0001"],'
    '"identity_kind":"capture","role":"supporting"},'
    '{"content_hash":"' + H1 + '","excerpt_sha256":"' + H2 + '",'
    '"identity":["kdsp_Profile0001","msg-1",""],"identity_kind":"external_object","role":"direct"}],'
    '"normalized_value":"Caf\u00e9 terms net 30","owner_ref":null,'
    '"predicate_code":"organization.payment_terms","qualifier":null,'
    '"scope_digest":"' + SCOPE + '","source_profile_id":"kdsp_Profile0001",'
    '"subject_id":"ent_A1b2C3d4E5f6","subject_kind":"entity",'
    '"trigger_event_ids":["rcev_Aa00000001","rcev_Zz00000002"],"v":1,"value_type":"text"}'
)
D1_DIGEST = "e74338cb2058000d3466947d0cbb5f5d77070b0e3f1412e6885712bd53b09e18"

#: Hand-written canonical JSON of vector D2 (explicit create, datetime value).
D2_CANONICAL = (
    '{"effective_from":null,"effective_to":null,"evidence":[],'
    '"normalized_value":"2026-12-31T23:59:59.000001Z",'
    '"owner_ref":{"id":"tsk_Task00000001","kind":"task"},'
    '"predicate_code":"project.critical_date","qualifier":{"date_kind":"deadline"},'
    '"scope_digest":null,"source_profile_id":null,"subject_id":"prj_Project0001",'
    '"subject_kind":"project","trigger_event_ids":[],"v":1,"value_type":"datetime"}'
)
D2_DIGEST = "6d58632f4bc640133936c69f26b132a283452a7b7956c867547bddfdfa8070e7"

F1_CANONICAL = (
    '{"effective_from":"2026-10-01T12:00:00.123456Z","effective_to":null,'
    '"normalized_value":"Caf\u00e9 terms net 30","predicate_code":"organization.payment_terms",'
    '"qualifier":null,"subject_id":"ent_A1b2C3d4E5f6","subject_kind":"entity",'
    '"temporal_semantics":"observed_state","v":1,"value_type":"text"}'
)
F1_FINGERPRINT = "078a2062f9d877299a0f5198172f626cdf76155a8ab20b2d72a95b7c5c1f45da"

F2_CANONICAL = (
    '{"effective_from":null,"effective_to":null,'
    '"normalized_value":"2026-12-31T23:59:59.000001Z","predicate_code":"project.critical_date",'
    '"qualifier":{"date_kind":"deadline"},"subject_id":"prj_Project0001","subject_kind":"project",'
    '"temporal_semantics":"observed_state","v":1,"value_type":"datetime"}'
)
F2_FINGERPRINT = "ec54bd40037119e0d3171833c8bea1f19dcc871fcc0ebc12cb175f1ed81e3fbd"

EXTERNAL = DigestEvidence(
    identity_kind=KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
    identity=("kdsp_Profile0001", "msg-1", ""),
    content_hash=H1,
    excerpt_sha256=H2,
    role=KnowledgeEvidenceRole.DIRECT,
)
CAPTURE = DigestEvidence(
    identity_kind=KnowledgeEvidenceIdentityKind.CAPTURE,
    identity=("cap_Capture0001",),
    content_hash=H3,
    excerpt_sha256=None,
    role=KnowledgeEvidenceRole.SUPPORTING,
)
#: 14:00:00.123456 at +02:00 is 12:00:00.123456Z.
D1_FROM = datetime(2026, 10, 1, 14, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2)))


def _d1(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "subject_kind": "entity",
        "subject_id": "ent_A1b2C3d4E5f6",
        "predicate_code": "organization.payment_terms",
        "value_type": KnowledgeValueType.TEXT,
        # Decomposed e + combining acute, and messy whitespace: the vector
        # pins NFC and whitespace collapse as well as the encoding.
        "normalized_value": normalize_text("  Cafe\u0301 terms\t\nnet   30 "),
        "qualifier": None,
        "effective_from": D1_FROM,
        "effective_to": None,
        "owner_ref": None,
        "source_profile_id": "kdsp_Profile0001",
        "scope_digest": SCOPE,
        "trigger_event_ids": ["rcev_Zz00000002", "rcev_Aa00000001", "rcev_Zz00000002"],
        "evidence": [EXTERNAL, CAPTURE],
    }
    arguments.update(overrides)
    return request_digest_object(**arguments)  # type: ignore[arg-type]


def _d2() -> dict[str, object]:
    return request_digest_object(
        subject_kind="project",
        subject_id="prj_Project0001",
        predicate_code="project.critical_date",
        value_type=KnowledgeValueType.DATETIME,
        normalized_value="2026-12-31T23:59:59.000001Z",
        qualifier={"date_kind": "deadline"},
        effective_from=None,
        effective_to=None,
        owner_ref=OwnerRef(KnowledgeOwnerRefKind.TASK, "tsk_Task00000001"),
        source_profile_id=None,
        scope_digest=None,
        trigger_event_ids=[],
        evidence=[],
    )


def _f1(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "subject_kind": "entity",
        "subject_id": "ent_A1b2C3d4E5f6",
        "predicate_code": "organization.payment_terms",
        "value_type": KnowledgeValueType.TEXT,
        "normalized_value": "Caf\u00e9 terms net 30",
        "qualifier": None,
        "temporal_semantics": KnowledgeTemporalSemantics.OBSERVED_STATE,
        "effective_from": D1_FROM,
        "effective_to": None,
    }
    arguments.update(overrides)
    return fingerprint_object(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        (D1_CANONICAL, D1_DIGEST),
        (D2_CANONICAL, D2_DIGEST),
        (F1_CANONICAL, F1_FINGERPRINT),
        (F2_CANONICAL, F2_FINGERPRINT),
    ],
)
def test_the_hard_coded_hexes_are_the_sha256_of_their_hand_written_canonical_json(
    canonical: str, expected: str
) -> None:
    """The vectors themselves are internally consistent (independent of the module)."""
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == expected


def test_request_digest_vector_d1_autonomous_text() -> None:
    obj = _d1()
    assert canonical_json_bytes(obj) == D1_CANONICAL.encode("utf-8")
    assert request_digest(obj) == D1_DIGEST


def test_request_digest_vector_d2_explicit_create_datetime() -> None:
    obj = _d2()
    assert canonical_json_bytes(obj) == D2_CANONICAL.encode("utf-8")
    assert request_digest(obj) == D2_DIGEST


def test_fingerprint_vector_f1_text() -> None:
    obj = _f1()
    assert canonical_json_bytes(obj) == F1_CANONICAL.encode("utf-8")
    assert assertion_fingerprint(obj) == F1_FINGERPRINT


def test_fingerprint_vector_f2_datetime_with_qualifier() -> None:
    obj = fingerprint_object(
        subject_kind="project",
        subject_id="prj_Project0001",
        predicate_code="project.critical_date",
        value_type=KnowledgeValueType.DATETIME,
        normalized_value="2026-12-31T23:59:59.000001Z",
        qualifier={"date_kind": "deadline"},
        temporal_semantics=KnowledgeTemporalSemantics.OBSERVED_STATE,
        effective_from=None,
        effective_to=None,
    )
    assert assertion_fingerprint(obj) == F2_FINGERPRINT


# --- Request digest invariance and variance (R6 section 6.2) -----------------


def test_reordered_evidence_gives_the_same_digest() -> None:
    """Both input orders give D1; the canonical order is not the caller's order."""
    assert request_digest(_d1(evidence=[EXTERNAL, CAPTURE])) == D1_DIGEST
    assert request_digest(_d1(evidence=[CAPTURE, EXTERNAL])) == D1_DIGEST


def test_reordered_and_duplicated_triggers_give_the_same_digest() -> None:
    reordered = ["rcev_Aa00000001", "rcev_Zz00000002", "rcev_Aa00000001"]
    assert request_digest(_d1(trigger_event_ids=reordered)) == D1_DIGEST


def test_changed_timestamps_outside_the_object_give_the_same_digest() -> None:
    """retrieved_at / access_last_verified_at are not parameters at all.

    The same instant expressed at another offset is also the same digest: the
    effective bound is normalized to UTC before encoding.
    """
    same_instant = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)
    assert request_digest(_d1(effective_from=same_instant)) == D1_DIGEST
    # Sub-microsecond precision cannot exist in a Python datetime, so truncation
    # is exact: the vector pins six fractional digits.
    assert '"2026-10-01T12:00:00.123456Z"' in D1_CANONICAL


def test_digest_parameters_exclude_volatile_and_server_owned_fields() -> None:
    for excluded in (
        "retrieved_at",
        "access_last_verified_at",
        "idempotency_key",
        "excerpt",
        "classification",
        "epistemic_status",
    ):
        with pytest.raises(TypeError):
            _d1(**{excluded: "anything"})


def test_changed_role_gives_a_different_digest() -> None:
    demoted = DigestEvidence(
        identity_kind=EXTERNAL.identity_kind,
        identity=EXTERNAL.identity,
        content_hash=EXTERNAL.content_hash,
        excerpt_sha256=EXTERNAL.excerpt_sha256,
        role=KnowledgeEvidenceRole.COUNTEREVIDENCE,
    )
    assert request_digest(_d1(evidence=[demoted, CAPTURE])) != D1_DIGEST


def test_changed_owner_ref_gives_a_different_digest() -> None:
    owner = OwnerRef(KnowledgeOwnerRefKind.COMMITMENT, "cmt_Commit000001")
    assert request_digest(_d1(owner_ref=owner)) != D1_DIGEST


def test_changed_trigger_set_gives_a_different_digest() -> None:
    assert request_digest(_d1(trigger_event_ids=["rcev_Aa00000001"])) != D1_DIGEST
    assert request_digest(_d1(trigger_event_ids=[])) != D1_DIGEST


def test_null_fields_are_present_never_absent() -> None:
    obj = _d2()
    for key in ("effective_from", "effective_to", "source_profile_id", "scope_digest"):
        assert key in obj
        assert obj[key] is None
    assert set(obj) == {
        "v",
        "subject_kind",
        "subject_id",
        "predicate_code",
        "value_type",
        "normalized_value",
        "qualifier",
        "effective_from",
        "effective_to",
        "owner_ref",
        "source_profile_id",
        "scope_digest",
        "trigger_event_ids",
        "evidence",
    }


# --- Fingerprint invariance and variance (R6 section 6.5) --------------------


def test_changed_effective_to_gives_a_different_fingerprint() -> None:
    later = datetime(2027, 1, 1, tzinfo=UTC)
    assert assertion_fingerprint(_f1(effective_to=later)) != F1_FINGERPRINT


def test_owner_ref_and_evidence_are_not_fingerprint_inputs() -> None:
    """Changed owner_ref or evidence -> same fingerprint, by construction."""
    with pytest.raises(TypeError):
        _f1(owner_ref=OwnerRef(KnowledgeOwnerRefKind.TASK, "tsk_Task00000001"))
    with pytest.raises(TypeError):
        _f1(evidence=[EXTERNAL])
    # And the same candidate digested with different evidence / owner keeps
    # one fingerprint while its request digest moves.
    assert assertion_fingerprint(_f1()) == F1_FINGERPRINT
    assert request_digest(_d1(evidence=[CAPTURE])) != request_digest(_d1())


def test_the_fingerprint_excludes_predicate_version_and_classification() -> None:
    assert set(_f1()) == {
        "v",
        "subject_kind",
        "subject_id",
        "predicate_code",
        "value_type",
        "normalized_value",
        "qualifier",
        "temporal_semantics",
        "effective_from",
        "effective_to",
    }


def test_the_proposal_fingerprint_equals_the_assertion_fingerprint_of_the_candidate() -> None:
    predicate = KnowledgePredicate(
        predicate_code="organization.payment_terms",
        predicate_version=1,
        admission_state=KnowledgePredicateAdmissionState.ACTIVE,
        value_type=KnowledgeValueType.TEXT,
        cardinality=KnowledgeCardinality.SINGLE_CURRENT,
        temporal_semantics=KnowledgeTemporalSemantics.OBSERVED_STATE,
        qualifier_rule=KnowledgeQualifierRule.NONE,
        allowed_subject_kinds=frozenset({KnowledgeSubjectKind.ENTITY}),
        allowed_entity_types=frozenset({EntityType.ORGANIZATION}),
        canonical_owner=KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION,
        autonomous_admission_policy=KnowledgeAutonomousAdmissionPolicy.NEVER,
        review_requirement=KnowledgeReviewRequirement.REQUIRES_OPERATOR,
        consequential_class=KnowledgeConsequentialClass.FINANCIAL_FACT,
        normalization_rule=KnowledgeNormalizationRule.TEXT_NFC_TRIM_COLLAPSE_WHITESPACE,
        classification_floor=Classification.PRIVATE_LOCAL,
        conflict_rule=KnowledgeConflictRule.REVIEW_ON_DIFFERENCE,
        minimum_evidence_authority=KnowledgeEvidenceAuthority.OBSERVED_SOURCE,
    )
    candidate = KnowledgeAssertionCandidate(
        subject_kind=KnowledgeSubjectKind.ENTITY,
        subject_id="ent_A1b2C3d4E5f6",
        predicate=predicate,
        value=KnowledgeValue.text("  Cafe\u0301 terms\t\nnet   30 "),
        effective_from=D1_FROM,
    )
    proposal = KnowledgeProposalDraft(
        candidate=candidate,
        review_requirement=KnowledgeReviewRequirement.REQUIRES_OPERATOR,
        risk_class=RiskClass.HIGH,
        classification=Classification.PRIVATE_LOCAL,
    )
    assert candidate.fingerprint() == F1_FINGERPRINT
    assert proposal.fingerprint() == F1_FINGERPRINT
