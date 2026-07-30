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


@pytest.mark.parametrize(
    ("capability", "purpose"),
    [
        (capability, purpose)
        for capability, purpose in itertools.product(Capability, Purpose)
        if purpose not in permitted_purposes(capability)
    ],
)
def test_every_mismatched_purpose_is_denied(capability: Capability, purpose: Purpose) -> None:
    principal = OPERATOR if is_operator_only(capability) else GATEWAY
    decision = evaluate(_request(principal=principal, capability=capability, purpose=purpose))
    assert not decision.allowed
    assert decision.reason is DenialReason.PURPOSE_NOT_PERMITTED_FOR_CAPABILITY


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
