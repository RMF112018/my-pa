"""Policy defaults to deny."""

from __future__ import annotations

import itertools

import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import (
    POLICY_VERSION,
    DenialReason,
    PolicyDecision,
    PolicyRequest,
    evaluate,
    validate_policy_version,
)

OPERATOR = Principal(
    principal_id="prn_operator0001", kind=PrincipalKind.OPERATOR, authenticated=True
)
GATEWAY = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY, authenticated=True)
SOURCE = "src_abc123def456"


def _request(**overrides: object) -> PolicyRequest:
    base: dict[str, object] = {
        "principal": GATEWAY,
        "purpose": Purpose.KNOWLEDGE_SEARCH,
        "capability": Capability.KNOWLEDGE_SEARCH,
        "requested_source_ids": frozenset({SOURCE}),
        "authorized_source_ids": frozenset({SOURCE}),
    }
    base.update(overrides)
    return PolicyRequest(**base)  # type: ignore[arg-type]


def test_the_baseline_request_is_allowed() -> None:
    # Without this, every deny assertion below would pass vacuously.
    decision = evaluate(_request())
    assert decision.allowed
    assert decision.reason is None
    assert decision.policy_version == POLICY_VERSION


def test_unauthenticated_principal_is_denied() -> None:
    principal = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY)
    decision = evaluate(_request(principal=principal))
    assert not decision.allowed
    assert decision.reason is DenialReason.PRINCIPAL_NOT_AUTHENTICATED


def test_principal_defaults_to_unauthenticated() -> None:
    principal = Principal(principal_id="prn_gateway00001", kind=PrincipalKind.GATEWAY)
    assert principal.authenticated is False


@pytest.mark.parametrize(
    "kind", [PrincipalKind.LOCAL_MODEL_GATEWAY, PrincipalKind.CLOUD_MODEL_PROVIDER]
)
def test_model_principals_cannot_hold_authority(kind: PrincipalKind) -> None:
    principal = Principal(principal_id="prn_model0000001", kind=kind, authenticated=True)
    decision = evaluate(_request(principal=principal))
    assert not decision.allowed
    assert decision.reason is DenialReason.PRINCIPAL_MAY_NOT_HOLD_AUTHORITY


def test_operator_only_capability_denies_non_operator() -> None:
    decision = evaluate(
        _request(capability=Capability.SOURCES_ENROLL, purpose=Purpose.BOUNDED_ENROLLMENT)
    )
    assert not decision.allowed
    assert decision.reason is DenialReason.OPERATOR_REQUIRED


def test_operator_only_capability_allows_operator() -> None:
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
        )
    )
    assert decision.allowed


def test_empty_scope_is_not_a_wildcard() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset()))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_scope_outside_enrollment_is_denied() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset({"src_zzz999zzz999"})))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_partially_authorized_scope_is_denied() -> None:
    decision = evaluate(_request(requested_source_ids=frozenset({SOURCE, "src_zzz999zzz999"})))
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_enrollment_grants_scope_rather_than_requiring_it() -> None:
    """Enrollment is the operation that creates authorization.

    Requiring the scope to be held already would mean an operator could only
    enroll a source they had already enrolled, making the capability unusable.
    """
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
            requested_source_ids=frozenset({"src_neverseen0001"}),
            authorized_source_ids=frozenset(),
        )
    )
    assert decision.allowed


def test_enrollment_still_requires_a_named_scope() -> None:
    decision = evaluate(
        _request(
            principal=OPERATOR,
            capability=Capability.SOURCES_ENROLL,
            purpose=Purpose.BOUNDED_ENROLLMENT,
            requested_source_ids=frozenset(),
            authorized_source_ids=frozenset(),
        )
    )
    assert not decision.allowed
    assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_enrollment_relaxation_does_not_leak_to_read_capabilities() -> None:
    # The relaxation above must apply to sources.enroll and nothing else.
    for capability in Capability:
        if capability in (Capability.SOURCES_ENROLL, Capability.CAPABILITIES_GET):
            continue
        principal = OPERATOR if is_operator_only(capability) else GATEWAY
        for purpose in permitted_purposes(capability):
            decision = evaluate(
                _request(
                    principal=principal,
                    capability=capability,
                    purpose=purpose,
                    requested_source_ids=frozenset({"src_neverseen0001"}),
                    authorized_source_ids=frozenset(),
                )
            )
            assert not decision.allowed, f"{capability}/{purpose} allowed an unheld scope"
            assert decision.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_capabilities_get_carries_no_source_scope() -> None:
    allowed = evaluate(
        _request(
            capability=Capability.CAPABILITIES_GET,
            purpose=Purpose.STATUS_OBSERVATION,
            requested_source_ids=frozenset(),
            authorized_source_ids=frozenset(),
        )
    )
    assert allowed.allowed
    denied = evaluate(
        _request(capability=Capability.CAPABILITIES_GET, purpose=Purpose.STATUS_OBSERVATION)
    )
    assert not denied.allowed
    assert denied.reason is DenialReason.SCOPE_NOT_AUTHORIZED


def test_private_content_is_never_cloud_eligible() -> None:
    for classification in (Classification.PRIVATE_LOCAL, Classification.RESTRICTED_LOCAL):
        decision = evaluate(_request(to_cloud=True, classification=classification))
        assert not decision.allowed
        assert decision.reason is DenialReason.DESTINATION_NOT_ELIGIBLE


def test_synthetic_test_data_may_leave_the_boundary() -> None:
    decision = evaluate(_request(to_cloud=True, classification=Classification.SYNTHETIC_TEST))
    assert decision.allowed


#: Capability/purpose pairs the contract permits, written out rather than read
#: from `permitted_purposes`. Deriving the mismatch set from the function under
#: test made the suite vacuous under exactly the mutation it existed to catch:
#: opening every purpose emptied the parameter list and the test still passed.
PERMITTED_PAIRS: frozenset[tuple[Capability, Purpose]] = frozenset(
    {
        (Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION),
        (Capability.CAPABILITIES_GET, Purpose.SECURITY_VALIDATION),
        (Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_FETCH, Purpose.SOURCE_INSPECTION),
        (Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION),
        (Capability.SOURCES_STATUS, Purpose.STATUS_OBSERVATION),
        (Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT),
        (Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH),
        (Capability.KNOWLEDGE_READ, Purpose.KNOWLEDGE_READ),
        (Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_CREATE, Purpose.CAPTURE_AUTHORING),
        (Capability.CAPTURE_REVISE, Purpose.CAPTURE_AUTHORING),
        (Capability.CAPTURE_READ, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_LIST, Purpose.CAPTURE_REVIEW),
        (Capability.CAPTURE_SEARCH, Purpose.CAPTURE_REVIEW),
        (Capability.REVIEW_LIST, Purpose.CAPTURE_REVIEW),
        (Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION),
        (Capability.CONTINUITY_PULSE, Purpose.CAPTURE_REVIEW),
        (Capability.CONTINUITY_SITUATIONS, Purpose.CAPTURE_REVIEW),
        (Capability.CONTINUITY_PROJECTS, Purpose.CAPTURE_REVIEW),
        (Capability.KNOWLEDGE_COVERAGE, Purpose.STATUS_OBSERVATION),
    }
)

MISMATCHED_PAIRS = sorted(
    set(itertools.product(Capability, Purpose)) - PERMITTED_PAIRS,
    key=lambda pair: (pair[0].value, pair[1].value),
)


def test_the_permitted_pair_table_matches_the_implementation() -> None:
    derived = {
        (capability, purpose)
        for capability in Capability
        for purpose in permitted_purposes(capability)
    }
    assert derived == PERMITTED_PAIRS


def test_the_mismatch_parametrisation_is_not_empty() -> None:
    # Pins the parameter count, so widening permitted_purposes cannot silently
    # empty the table below. The three numbers are written out rather than
    # derived from each other: the arithmetic is what makes the second a check on
    # the enums, and the literals are what make it a check on the arithmetic.
    assert len(PERMITTED_PAIRS) == 22
    assert len(MISMATCHED_PAIRS) == len(Capability) * len(Purpose) - 22 == 178


@pytest.mark.parametrize(("capability", "purpose"), MISMATCHED_PAIRS)
def test_every_mismatched_purpose_is_denied(capability: Capability, purpose: Purpose) -> None:
    principal = OPERATOR if is_operator_only(capability) else GATEWAY
    decision = evaluate(_request(principal=principal, capability=capability, purpose=purpose))
    assert not decision.allowed
    assert decision.reason is DenialReason.PURPOSE_NOT_PERMITTED_FOR_CAPABILITY


def test_principal_validates_its_identifier() -> None:
    for bad in ("/Users/someone", "prn_bad", "src_abc123def456", "prn_host.example.com"):
        with pytest.raises(ValueError, match="identifier"):
            Principal(principal_id=bad, kind=PrincipalKind.OPERATOR, authenticated=True)


def test_is_operator_requires_authentication() -> None:
    """`evaluate` only survives an unauthenticated operator by short-circuiting.

    Without this, dropping the `authenticated` conjunct from `is_operator` would
    make an unauthenticated operator report True with no test failing, leaving
    the property unsafe for any future caller that checks it directly.
    """
    unauthenticated = Principal(principal_id="prn_operator0001", kind=PrincipalKind.OPERATOR)
    assert unauthenticated.is_operator is False
    assert unauthenticated.may_hold_authority is False
    assert OPERATOR.is_operator is True


def test_every_capability_has_at_least_one_permitted_purpose() -> None:
    for capability in Capability:
        assert permitted_purposes(capability), f"{capability} would be permanently denied"


def test_decision_cannot_be_allowed_with_a_reason() -> None:
    with pytest.raises(ValueError, match="cannot carry a denial reason"):
        PolicyDecision(
            allowed=True,
            policy_version=POLICY_VERSION,
            reason=DenialReason.SCOPE_NOT_AUTHORIZED,
        )


def test_denial_must_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="must carry a reason"):
        PolicyDecision(allowed=False, policy_version=POLICY_VERSION)


def test_decision_validates_its_own_policy_version() -> None:
    """Pinned independently of AuditEvent.

    AuditEvent revalidates, so it provides defence in depth — which means a
    refactor could delete this check and every other test would still pass.
    """
    for bad in ("postgres://user:pw@host/db", "policy-vX", "v1", "", "policy-v1; DROP TABLE"):
        with pytest.raises(ValueError, match="policy version"):
            PolicyDecision(allowed=True, policy_version=bad)


def test_decision_rejects_a_non_string_policy_version() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        PolicyDecision(allowed=True, policy_version=123)  # type: ignore[arg-type]


def test_evaluate_emits_a_well_formed_policy_version() -> None:
    assert validate_policy_version(evaluate(_request()).policy_version) == POLICY_VERSION
