"""Knowledge Assertion domain contract (KLP-WP-01).

- Closed-vocabulary parity: every WP-01 enum equals the committed R6 matrix
  `closed_vocabularies` list, members and order (R6 plan section 4). The plan
  names `tests/unit/test_knowledge_vocabulary_parity.py` for this; that module
  is not in KLP-WP-01's owned paths, so the parity lives here.
- AC-005 (WP-01 slice): exactly one typed value branch; any other shape refused.
- The structural predicate-version rule and the anti-EAV predicate contract.
- Evidence identity shapes and the observed external class (rank-max of profile
  floor and sibling max).
- The causal provenance model and the frozen Record Event mapping table.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

from my_pa.domain.capture.proposal import RiskClass
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion import vocabulary
from my_pa.domain.knowledge_assertion.assertion import (
    SUBJECT_ID_KINDS,
    InvalidKnowledgeAssertionError,
    KnowledgeAssertionCandidate,
    KnowledgeValue,
    validate_qualifier,
)
from my_pa.domain.knowledge_assertion.digest import InvalidKnowledgeValueError
from my_pa.domain.knowledge_assertion.evidence import (
    EvidenceIdentity,
    InvalidKnowledgeEvidenceError,
    observed_external_classification,
)
from my_pa.domain.knowledge_assertion.predicate import (
    STRUCTURAL_FIELDS,
    InvalidPredicateError,
    KnowledgePredicate,
    require_structural_successor,
)
from my_pa.domain.knowledge_assertion.proposal import (
    InvalidKnowledgeProposalError,
    KnowledgeProposalDraft,
)
from my_pa.domain.knowledge_assertion.provenance import (
    CAUSAL_RATE_LIMIT,
    KNOWLEDGE_EVENT_ACTOR_CLASSES,
    KNOWLEDGE_EVENT_AUTHORITIES,
    KNOWLEDGE_MUTATION_EVENTS,
    MAX_CAUSAL_DEPTH,
    CausalKey,
    CausalParent,
    CausalPosition,
    CausalRefusal,
    KnowledgeEventOrigin,
    resolve_causal_position,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KNOWLEDGE_CLASSIFICATION_FLOORS,
    RESPONSE_ONLY_SUBMISSION_REASONS,
    STORED_SUBMISSION_REASONS,
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeMutationKind,
    KnowledgeNormalizationRule,
    KnowledgePredicateAdmissionState,
    KnowledgeQualifierRule,
    KnowledgeReviewRequirement,
    KnowledgeSubjectKind,
    KnowledgeSubmissionReason,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)
from my_pa.domain.record_events import RecordEventActorClass, RecordEventAuthority
from my_pa.domain.relationship.entity import EntityType

MATRIX_PATH = (
    Path(__file__).resolve().parents[1] / "architecture" / "klp_implementation_matrix_r6.json"
)
VOCABULARY_MODULE = "src/my_pa/domain/knowledge_assertion/vocabulary.py"


def _matrix() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return loaded


MATRIX = _matrix()
VOCABULARIES: dict[str, dict[str, Any]] = MATRIX["closed_vocabularies"]
WP01_KEYS = sorted(
    key for key, row in VOCABULARIES.items() if row["python_module"] == VOCABULARY_MODULE
)


# --- Closed-vocabulary parity -------------------------------------------------


def test_wp01_owns_the_expected_number_of_vocabulary_enums() -> None:
    assert len(WP01_KEYS) == 35
    declared = {
        name
        for name, value in vars(vocabulary).items()
        if isinstance(value, type)
        and issubclass(value, StrEnum)
        and value.__module__ == vocabulary.__name__
    }
    assert declared == {VOCABULARIES[key]["python_enum"] for key in WP01_KEYS}


@pytest.mark.parametrize("key", WP01_KEYS)
def test_each_vocabulary_enum_equals_the_matrix_list_in_order(key: str) -> None:
    row = VOCABULARIES[key]
    enum_type = getattr(vocabulary, row["python_enum"])
    assert [member.value for member in enum_type] == row["values"]
    assert [member.name for member in enum_type] == [value.upper() for value in row["values"]]


@pytest.mark.parametrize(
    ("key", "existing"),
    [
        ("classification", Classification),
        ("knowledge_entity_type", EntityType),
        ("risk_class", RiskClass),
    ],
)
def test_reused_existing_enums_equal_the_matrix_lists(key: str, existing: type[StrEnum]) -> None:
    assert [member.value for member in existing] == VOCABULARIES[key]["values"]


def test_the_classification_floor_subset_equals_the_matrix() -> None:
    assert [floor.value for floor in KNOWLEDGE_CLASSIFICATION_FLOORS] == VOCABULARIES[
        "knowledge_classification_floor"
    ]["values"]


def test_the_later_wps_additions_are_not_declared_by_wp01() -> None:
    """OperatorSurface and the '+1' members belong to WP-03/04/06."""
    from my_pa.domain.capture.review import ReviewSubjectKind
    from my_pa.domain.context.prepared import ContextPlane, SourceAuthorityClass
    from my_pa.domain.record_events import RecordEventFamily

    assert not hasattr(vocabulary, "OperatorSurface")
    for enum_type in (ReviewSubjectKind, RecordEventFamily, ContextPlane):
        assert "knowledge_assertion" not in {member.value for member in enum_type}
    assert "product_owned_knowledge_assertion" not in {m.value for m in SourceAuthorityClass}


def test_the_stored_submission_reasons_exclude_exactly_the_response_only_two() -> None:
    assert {reason.value for reason in RESPONSE_ONLY_SUBMISSION_REASONS} == {
        "idempotency_conflict",
        "checkpoint_conflict",
    }
    assert len(STORED_SUBMISSION_REASONS) == len(KnowledgeSubmissionReason) - 2 == 20
    assert list(STORED_SUBMISSION_REASONS) == [
        reason
        for reason in KnowledgeSubmissionReason
        if reason not in RESPONSE_ONLY_SUBMISSION_REASONS
    ]
    assert "stored subset" in VOCABULARIES["knowledge_submission_reason"]["used_by"][0]


def test_the_matrix_submission_vocabularies_agree_with_the_closed_vocabularies() -> None:
    assert MATRIX["submission_reasons"] == VOCABULARIES["knowledge_submission_reason"]["values"]
    assert MATRIX["submission_outcomes"] == VOCABULARIES["knowledge_submission_outcome"]["values"]
    assert MATRIX["canonical_owners"] == VOCABULARIES["knowledge_canonical_owner"]["values"]


def test_subject_kinds_map_to_the_matrix_id_kinds() -> None:
    expected = {row["name"]: row["id_kind"] for row in MATRIX["subject_kinds"]}
    assert {kind.value: id_kind.name for kind, id_kind in SUBJECT_ID_KINDS.items()} == expected


# --- Predicates ---------------------------------------------------------------


def _predicate_from_seed(row: dict[str, Any]) -> KnowledgePredicate:
    return KnowledgePredicate(
        predicate_code=row["predicate_code"],
        predicate_version=row["predicate_version"],
        admission_state=KnowledgePredicateAdmissionState(row["admission_state"]),
        value_type=KnowledgeValueType(row["value_type"]),
        cardinality=KnowledgeCardinality(row["cardinality"]),
        temporal_semantics=KnowledgeTemporalSemantics(row["temporal_semantics"]),
        qualifier_rule=KnowledgeQualifierRule(row["qualifier_rule"]),
        allowed_subject_kinds=frozenset(
            KnowledgeSubjectKind(k) for k in row["allowed_subject_kinds"]
        ),
        allowed_entity_types=frozenset(EntityType(t) for t in row["allowed_entity_types"]),
        canonical_owner=KnowledgeCanonicalOwner(row["canonical_owner"]),
        autonomous_admission_policy=KnowledgeAutonomousAdmissionPolicy(
            row["autonomous_admission_policy"]
        ),
        review_requirement=KnowledgeReviewRequirement(row["review_requirement"]),
        consequential_class=KnowledgeConsequentialClass(row["consequential_class"]),
        normalization_rule=KnowledgeNormalizationRule(row["normalization_rule"]),
        classification_floor=Classification(row["classification_floor"]),
        conflict_rule=KnowledgeConflictRule(row["conflict_rule"]),
        minimum_evidence_authority=KnowledgeEvidenceAuthority(row["minimum_evidence_authority"]),
        fingerprint_version=row["fingerprint_version"],
    )


SEEDS = {row["predicate_code"]: row for row in MATRIX["initial_predicates"]}


@pytest.mark.parametrize("code", sorted(SEEDS))
def test_every_matrix_seed_predicate_satisfies_the_registry_contract(code: str) -> None:
    assert _predicate_from_seed(SEEDS[code]).predicate_code == code


def _payment_terms(**overrides: object) -> KnowledgePredicate:
    base = _predicate_from_seed(SEEDS["organization.payment_terms"])
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _critical_date(**overrides: object) -> KnowledgePredicate:
    base = _predicate_from_seed(SEEDS["project.critical_date"])
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"predicate_code": "PaymentTerms"},  # not <namespace>.<name>
        {"predicate_code": "organization.payment.terms"},
        {"predicate_version": 0},
        {"temporal_semantics": KnowledgeTemporalSemantics.HISTORICAL},  # single_current
        {"conflict_rule": KnowledgeConflictRule.COEXIST},  # single_current needs review
        {"normalization_rule": KnowledgeNormalizationRule.DATETIME_UTC_MICROSECOND},
        {"autonomous_admission_policy": KnowledgeAutonomousAdmissionPolicy.AUTHORITATIVE_SOURCE},
        {"classification_floor": Classification.SYNTHETIC_TEST},
        {"fingerprint_version": 2},
        {"allowed_entity_types": frozenset()},  # entity subject needs entity types
        {"allowed_subject_kinds": frozenset()},
        {"value_type": "text"},  # a raw string is not a closed token
    ],
)
def test_illegal_predicate_rows_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidPredicateError):
        _payment_terms(**overrides)


def test_a_date_kind_qualifier_is_only_for_datetime_values() -> None:
    with pytest.raises(InvalidPredicateError):
        _critical_date(
            value_type=KnowledgeValueType.TEXT,
            normalization_rule=KnowledgeNormalizationRule.TEXT_NFC_TRIM_COLLAPSE_WHITESPACE,
        )


def test_a_domain_owned_predicate_never_direct_admits() -> None:
    seed = SEEDS["organization.operating_requirement"]
    predicate = _predicate_from_seed(seed)
    assert (
        predicate.autonomous_admission_policy
        is KnowledgeAutonomousAdmissionPolicy.AUTHORITATIVE_SOURCE
    )
    with pytest.raises(InvalidPredicateError):
        dataclasses.replace(predicate, canonical_owner=KnowledgeCanonicalOwner.ENTITY)


def test_a_successor_version_may_change_policy_but_never_structure() -> None:
    head = _payment_terms()
    successor = dataclasses.replace(
        head,
        predicate_version=2,
        review_requirement=KnowledgeReviewRequirement.REQUIRES_REVIEW,
        minimum_evidence_authority=KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE,
    )
    require_structural_successor(head, successor)
    structural_changes: dict[str, object] = {
        "allowed_entity_types": frozenset({EntityType.ORGANIZATION, EntityType.PERSON}),
        "canonical_owner": KnowledgeCanonicalOwner.CONSTRAINTS,
        "temporal_semantics": KnowledgeTemporalSemantics.ATEMPORAL,
    }
    for name, value in structural_changes.items():
        changed = dataclasses.replace(head, predicate_version=2, **{name: value})  # type: ignore[arg-type]
        with pytest.raises(InvalidPredicateError, match=name):
            require_structural_successor(head, changed)


def test_the_structural_field_list_matches_the_wp02_trigger() -> None:
    assert set(STRUCTURAL_FIELDS) <= {f.name for f in dataclasses.fields(KnowledgePredicate)}
    assert STRUCTURAL_FIELDS == (
        "value_type",
        "cardinality",
        "temporal_semantics",
        "qualifier_rule",
        "allowed_subject_kinds",
        "allowed_entity_types",
        "canonical_owner",
        "normalization_rule",
        "fingerprint_version",
    )


def test_a_successor_must_be_head_plus_one_of_the_same_open_code() -> None:
    head = _payment_terms()
    with pytest.raises(InvalidPredicateError):
        require_structural_successor(head, dataclasses.replace(head, predicate_version=3))
    with pytest.raises(InvalidPredicateError):
        require_structural_successor(
            head,
            dataclasses.replace(head, predicate_code="organization.terms", predicate_version=2),
        )
    retired = dataclasses.replace(head, admission_state=KnowledgePredicateAdmissionState.RETIRED)
    assert not retired.is_open_for_intake
    with pytest.raises(InvalidPredicateError, match="retired"):
        require_structural_successor(retired, dataclasses.replace(head, predicate_version=2))


# --- AC-005: exactly one typed value branch ----------------------------------


def test_text_and_datetime_values_each_carry_exactly_their_own_branch() -> None:
    text = KnowledgeValue.text("  Net   30 ")
    assert (text.value_text, text.value_datetime) == ("Net 30", None)
    stamp = datetime(2026, 12, 31, tzinfo=UTC)
    instant = KnowledgeValue.instant(stamp)
    assert (instant.value_text, instant.value_datetime) == (None, stamp)
    assert instant.normalized == "2026-12-31T00:00:00.000000Z"


@pytest.mark.parametrize(
    "shape",
    [
        {"value_type": KnowledgeValueType.TEXT},  # neither branch
        {"value_type": KnowledgeValueType.DATETIME},
        {
            "value_type": KnowledgeValueType.TEXT,
            "value_text": "Net 30",
            "value_datetime": datetime(2026, 1, 1, tzinfo=UTC),
        },  # both branches
        {
            "value_type": KnowledgeValueType.DATETIME,
            "value_text": "Net 30",
            "value_datetime": datetime(2026, 1, 1, tzinfo=UTC),
        },
        {"value_type": KnowledgeValueType.TEXT, "value_datetime": datetime(2026, 1, 1, tzinfo=UTC)},
        {"value_type": KnowledgeValueType.DATETIME, "value_text": "2026-01-01T00:00:00Z"},
        {"value_type": "text", "value_text": "Net 30"},  # unclosed type token
        {"value_type": KnowledgeValueType.TEXT, "value_text": "  Net 30"},  # not normalized
    ],
)
def test_any_other_value_shape_is_refused(shape: dict[str, Any]) -> None:
    with pytest.raises((InvalidKnowledgeAssertionError, InvalidKnowledgeValueError)):
        KnowledgeValue(**shape)


def test_a_naive_datetime_branch_is_refused() -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        KnowledgeValue.instant(datetime(2026, 1, 1))
    with pytest.raises(InvalidKnowledgeValueError):
        KnowledgeValue.instant("2026-01-01T00:00:00Z")


def test_a_candidate_value_must_match_its_predicate_value_type() -> None:
    with pytest.raises(InvalidKnowledgeAssertionError, match="value_type"):
        KnowledgeAssertionCandidate(
            subject_kind=KnowledgeSubjectKind.PROJECT,
            subject_id="prj_Project0001",
            predicate=_critical_date(),
            value=KnowledgeValue.text("next Friday"),
            qualifier={"date_kind": "deadline"},
        )


def test_proposals_use_the_same_single_typed_branch() -> None:
    """A proposal holds a candidate, so it cannot hold an untyped value."""
    with pytest.raises(InvalidKnowledgeProposalError):
        KnowledgeProposalDraft(
            candidate={"value": "Net 30"},  # type: ignore[arg-type]
            review_requirement=KnowledgeReviewRequirement.REQUIRES_REVIEW,
            risk_class=RiskClass.LOW,
            classification=Classification.PRIVATE_LOCAL,
        )


def _candidate(**overrides: object) -> KnowledgeAssertionCandidate:
    arguments: dict[str, Any] = {
        "subject_kind": KnowledgeSubjectKind.PROJECT,
        "subject_id": "prj_Project0001",
        "predicate": _critical_date(),
        "value": KnowledgeValue.instant(datetime(2026, 12, 31, tzinfo=UTC)),
        "qualifier": {"date_kind": "deadline"},
    }
    arguments.update(overrides)
    return KnowledgeAssertionCandidate(**arguments)


def test_candidate_subject_and_qualifier_rules() -> None:
    assert _candidate().qualifier == {"date_kind": "deadline"}
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(subject_id="ent_A1b2C3d4E5f6")  # prefix does not match kind
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(subject_kind=KnowledgeSubjectKind.ENTITY, subject_id="ent_A1b2C3d4E5f6")
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(qualifier=None)
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(qualifier={"date_kind": "birthday"})
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(qualifier={"date_kind": "deadline", "note": "x"})
    with pytest.raises(InvalidKnowledgeAssertionError):
        _candidate(
            effective_from=datetime(2026, 2, 1, tzinfo=UTC),
            effective_to=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert validate_qualifier(KnowledgeQualifierRule.NONE, None) is None
    with pytest.raises(InvalidKnowledgeAssertionError):
        validate_qualifier(KnowledgeQualifierRule.NONE, {"date_kind": "deadline"})


def test_subject_kind_id_kinds_cover_every_subject_kind() -> None:
    assert set(SUBJECT_ID_KINDS) == set(KnowledgeSubjectKind)
    assert SUBJECT_ID_KINDS[KnowledgeSubjectKind.EVIDENCE_REF] is IdKind.KNOWLEDGE_EVIDENCE_REF


# --- Evidence -----------------------------------------------------------------

HASH = "ab" * 32


def test_evidence_identity_has_exactly_one_shape() -> None:
    external = EvidenceIdentity(
        KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
        HASH,
        source_profile_id="kdsp_Profile0001",
        external_object_id="AAMkAD/x==",
    )
    assert external.identity == ("kdsp_Profile0001", "AAMkAD/x==", "")
    capture = EvidenceIdentity(
        KnowledgeEvidenceIdentityKind.CAPTURE, HASH, capture_id="cap_Capture0001"
    )
    assert capture.identity == ("cap_Capture0001",)
    assert sorted([external, capture], key=EvidenceIdentity.canonical_sort_key) == [
        capture,
        external,
    ]
    for illegal in (
        {"capture_id": "cap_Capture0001", "source_profile_id": "kdsp_Profile0001"},
        {"capture_id": "mem_Memory000001"},
        {},
    ):
        with pytest.raises(InvalidKnowledgeEvidenceError):
            EvidenceIdentity(KnowledgeEvidenceIdentityKind.CAPTURE, HASH, **illegal)
    with pytest.raises(InvalidKnowledgeEvidenceError):
        EvidenceIdentity(KnowledgeEvidenceIdentityKind.CAPTURE, "XYZ", capture_id="cap_Capture0001")
    with pytest.raises(InvalidKnowledgeEvidenceError):
        EvidenceIdentity(
            KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
            HASH,
            source_profile_id="kdsp_Profile0001",
            external_object_id="bad\nid",
        )


def test_observed_external_class_is_rank_max_of_profile_floor_and_sibling_max() -> None:
    restricted = Classification.RESTRICTED_LOCAL
    assert (
        observed_external_classification(profile_is_synthetic=False, sibling_classifications=[])
        is Classification.PRIVATE_LOCAL
    )
    assert (
        observed_external_classification(profile_is_synthetic=True, sibling_classifications=[])
        is Classification.SYNTHETIC_TEST
    )
    # A sibling under any profile/version of the same origin keeps a restriction.
    assert (
        observed_external_classification(
            profile_is_synthetic=True, sibling_classifications=[restricted]
        )
        is restricted
    )
    assert (
        observed_external_classification(
            profile_is_synthetic=False,
            sibling_classifications=[Classification.SYNTHETIC_TEST, restricted],
        )
        is restricted
    )


# --- Causal provenance --------------------------------------------------------

KEY = CausalKey("client-a", "entity", "ent_A1b2C3d4E5f6", "organization.payment_terms")


def test_no_knowledge_parent_starts_a_root_at_depth_zero() -> None:
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001", own_key=KEY, parents=[], ancestor_keys=[]
    ) == CausalPosition("kasub_Own0000001", 0)


def test_one_root_is_inherited_at_one_plus_max_depth() -> None:
    parents = [CausalParent("kasub_Root000001", 1), CausalParent("kasub_Root000001", 2)]
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001", own_key=KEY, parents=parents, ancestor_keys=[]
    ) == CausalPosition("kasub_Root000001", 3)


def test_two_roots_are_ambiguous_and_depth_above_four_is_refused() -> None:
    two = [CausalParent("kasub_Root000001", 0), CausalParent("kasub_Root000002", 0)]
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001", own_key=KEY, parents=two, ancestor_keys=[]
    ) == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_ROOT_AMBIGUOUS)
    deepest = [CausalParent("kasub_Root000001", MAX_CAUSAL_DEPTH - 1)]
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001", own_key=KEY, parents=deepest, ancestor_keys=[]
    ) == CausalPosition("kasub_Root000001", MAX_CAUSAL_DEPTH)
    too_deep = [CausalParent("kasub_Root000001", MAX_CAUSAL_DEPTH)]
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001", own_key=KEY, parents=too_deep, ancestor_keys=[]
    ) == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_DEPTH_EXCEEDED)
    assert MAX_CAUSAL_DEPTH == 4
    assert CAUSAL_RATE_LIMIT == 16


def test_a_repeated_lineage_key_is_refused_whatever_the_run() -> None:
    assert resolve_causal_position(
        own_submission_id="kasub_Own0000001",
        own_key=KEY,
        parents=[CausalParent("kasub_Root000001", 0)],
        ancestor_keys=[KEY],
    ) == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_REPEAT)


def test_causal_refusal_reasons_are_stored_reasons() -> None:
    for reason in ("causal_root_ambiguous", "causal_depth_exceeded", "causal_repeat"):
        assert KnowledgeSubmissionReason(reason) in STORED_SUBMISSION_REASONS


def test_the_record_event_mapping_is_total_and_uses_existing_closed_tokens() -> None:
    assert set(KNOWLEDGE_MUTATION_EVENTS) == set(KnowledgeMutationKind)
    assert set(KNOWLEDGE_EVENT_ACTOR_CLASSES) == set(KnowledgeEventOrigin)
    assert set(KNOWLEDGE_EVENT_AUTHORITIES) == set(KnowledgeEventOrigin)
    assert KNOWLEDGE_EVENT_ACTOR_CLASSES == {
        KnowledgeEventOrigin.AUTONOMOUS_SUBMIT: RecordEventActorClass.ASSISTANT,
        KnowledgeEventOrigin.EXPLICIT_CREATE: RecordEventActorClass.PRINCIPAL,
        KnowledgeEventOrigin.REVIEW_PROMOTION: RecordEventActorClass.REVIEW_PROMOTION,
        KnowledgeEventOrigin.SERVER_MAINTENANCE: RecordEventActorClass.SYSTEM,
    }
    assert KNOWLEDGE_EVENT_AUTHORITIES == {
        KnowledgeEventOrigin.AUTONOMOUS_SUBMIT: RecordEventAuthority.SOURCE_BACKED_ASSERTION,
        KnowledgeEventOrigin.EXPLICIT_CREATE: RecordEventAuthority.USER_CONFIRMED_ASSERTION,
        KnowledgeEventOrigin.REVIEW_PROMOTION: RecordEventAuthority.REVIEW_ACCEPTED,
        KnowledgeEventOrigin.SERVER_MAINTENANCE: RecordEventAuthority.SYSTEM_DETERMINISTIC,
    }
    assert KNOWLEDGE_MUTATION_EVENTS[KnowledgeMutationKind.CREATE].kind.value == "created"
    assert KNOWLEDGE_MUTATION_EVENTS[KnowledgeMutationKind.EVIDENCE_ENRICH].kind.value == "updated"
    for kind in ("classify", "revalidation_required", "supersede_predecessor", "archive"):
        assert KNOWLEDGE_MUTATION_EVENTS[KnowledgeMutationKind(kind)].kind.value == "state_changed"
    for event in KNOWLEDGE_MUTATION_EVENTS.values():
        assert list(event.changed_fields) == sorted(set(event.changed_fields))
