"""Typed errors and the truthfulness rules on the disclosure envelope."""

from __future__ import annotations

import typing
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from my_pa.contracts.v1 import (
    Coverage,
    CoverageState,
    Disclosure,
    ErrorCode,
    Freshness,
    FreshnessState,
    ProblemDetail,
    ResponseEnvelope,
    RetryGuidance,
    Scope,
    SourceReference,
    Truncation,
    Trust,
    retry_guidance_for,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.provenance import TrustLevel

OBSERVED = datetime(2026, 7, 30, 20, 0, 0, tzinfo=UTC)


def _coverage(**kwargs: object) -> Coverage:
    base: dict[str, object] = {"state": CoverageState.PROCESSED, "eligible": 1, "processed": 1}
    base.update(kwargs)
    return Coverage(**base)  # type: ignore[arg-type]


def _disclosure(**overrides: object) -> Disclosure:
    base: dict[str, object] = {
        "scope": Scope(source_ids=("src_abc123def456",)),
        "coverage": _coverage(),
        "freshness": Freshness(
            observed_at=OBSERVED, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        "trust": Trust(level=TrustLevel.SOURCE_BOUND_DERIVED),
    }
    base.update(overrides)
    return Disclosure(**base)  # type: ignore[arg-type]


def test_all_eleven_error_codes_exist() -> None:
    assert {code.value for code in ErrorCode} == {
        "invalid_request",
        "ambiguous_request",
        "denied",
        "unavailable",
        "unsupported",
        "not_found",
        "conflict",
        "rate_limited",
        "quarantined",
        "cancelled",
        "internal_error",
    }


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_code_has_fixed_retry_guidance(code: ErrorCode) -> None:
    detail = ProblemDetail(
        code=code,
        message="request could not be completed",
        correlation_id="corr_abc123def456",
        retry=retry_guidance_for(code),
    )
    assert detail.retry is retry_guidance_for(code)


def test_contradicting_retry_guidance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires retry guidance"):
        ProblemDetail(
            code=ErrorCode.UNSUPPORTED,
            message="not supported",
            correlation_id="corr_abc123def456",
            retry=RetryGuidance.BOUNDED_RETRY,
        )


def test_denied_is_not_retryable_without_authority_change() -> None:
    assert retry_guidance_for(ErrorCode.DENIED) is RetryGuidance.AFTER_AUTHORITY_CHANGE


def test_unsupported_is_never_retryable() -> None:
    assert retry_guidance_for(ErrorCode.UNSUPPORTED) is RetryGuidance.NO


def test_scope_validates_enrollment_ids_as_well_as_source_ids() -> None:
    # Asymmetric coverage here once left enrollment_ids as an unguarded
    # INV-PKL-005 leak channel while source_ids was pinned.
    assert Scope(enrollment_ids=("enr_abc123def456",))
    for bad in ("src_abc123def456", "/Users/someone/tax.pdf", "enr_bad"):
        with pytest.raises(ValidationError):
            Scope(enrollment_ids=(bad,))


def _carries_a_string(annotation: object) -> bool:
    """Whether `annotation` can hold a str anywhere inside it.

    Walks the annotation rather than comparing it, so `tuple[str, ...]`,
    `str | None`, `list[str]`, and `dict[str, str]` are all detected — an
    identity comparison against a parameterised generic never matches, because
    each subscription builds a new object.

    `object` and `Any` count as string-bearing: they impose no constraint at
    all, so a field annotated that way is a free-text channel by definition.
    """
    if annotation is str or annotation is object or annotation is typing.Any:
        return True
    return any(_carries_a_string(arg) for arg in typing.get_args(annotation))


def _problem(**overrides: object) -> ProblemDetail:
    base: dict[str, object] = {
        "code": ErrorCode.INVALID_REQUEST,
        "message": "request could not be completed",
        "correlation_id": "corr_abc123def456",
        "retry": RetryGuidance.AFTER_CORRECTION,
    }
    base.update(overrides)
    return ProblemDetail(**base)  # type: ignore[arg-type]


def test_problem_detail_has_no_field_that_can_carry_free_form_content() -> None:
    """The public error is the other place a payload could reach a caller.

    `AuditEvent` carries this guarantee structurally; without the same check
    here, a new unbounded `str` field could be added to the public error
    contract with the whole suite still passing.
    """
    # Every field whose annotation can carry a string must be constrained, and
    # the companion tests below prove each constraint actually rejects payload.
    # A new one lands here unlisted and fails.
    constrained = {
        "message": "Field length bounds",
        "correlation_id": "validate_identifier in the model validator",
        "safe_details": "token pattern and arity bound in the model validator",
    }
    string_bearing = {
        name
        for name, field in ProblemDetail.model_fields.items()
        if _carries_a_string(field.annotation)
    }
    # Guards against the check silently matching nothing: an identity comparison
    # against `tuple[str, ...]` is always False, because each subscription of a
    # parameterised generic builds a new object. That made this test blind to
    # every container-of-string field, including safe_details itself.
    assert "safe_details" in string_bearing, "the string detector matched nothing"
    assert not string_bearing - set(constrained), (
        f"unbounded free-text field(s): {sorted(string_bearing - set(constrained))}"
    )
    assert ProblemDetail.model_fields["message"].metadata, "message lost its length bound"


@pytest.mark.parametrize(
    "detail",
    [
        "/Users/someone/tax.pdf",
        "postgres://user:hunter2@db.internal/prod",
        "SELECT ssn FROM people",
        "what is my account number",
        "Field 'x' rejected because value was 4111-1111-1111-1111",
        "a" * 200,
        "UPPERCASE",
    ],
)
def test_safe_details_rejects_free_text(detail: str) -> None:
    with pytest.raises(ValidationError, match="short lowercase tokens"):
        _problem(safe_details=(detail,))


def test_safe_details_accepts_field_name_tokens() -> None:
    assert _problem(safe_details=("scope.source_ids", "purpose")).safe_details


def test_safe_details_arity_is_bounded() -> None:
    with pytest.raises(ValidationError):
        _problem(safe_details=tuple(f"field_{i}" for i in range(100)))


def test_problem_detail_validates_its_correlation_id() -> None:
    for bad in ("corr_bad", "src_abc123def456", "corr_/Users/x", "corr_host.example.com"):
        with pytest.raises(ValidationError):
            ProblemDetail(
                code=ErrorCode.DENIED,
                message="denied",
                correlation_id=bad,
                retry=RetryGuidance.AFTER_AUTHORITY_CHANGE,
            )


def test_source_reference_validates_every_identifier_kind() -> None:
    """`INV-PKL-005`: these three fields are the leak channel if unvalidated."""
    good = {
        "source_id": "src_abc123def456",
        "source_object_id": "obj_abc123def456",
        "version_id": "ver_abc123def456",
    }
    assert SourceReference(**good)
    for field, wrong in (
        ("source_id", "obj_abc123def456"),
        ("source_object_id", "src_abc123def456"),
        ("version_id", "kn_abc123def456"),
    ):
        with pytest.raises(ValidationError):
            SourceReference(**{**good, field: wrong})
    for field in good:
        with pytest.raises(ValidationError):
            SourceReference(**{**good, field: "/Users/someone/tax.pdf"})


def test_error_message_is_length_bounded() -> None:
    with pytest.raises(ValidationError):
        ProblemDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message="x" * 500,
            correlation_id="corr_abc123def456",
            retry=RetryGuidance.CONDITIONAL,
        )


def test_partial_coverage_must_declare_partial_result() -> None:
    with pytest.raises(ValidationError, match="requires partial_result"):
        _disclosure(coverage=_coverage(state=CoverageState.PARTIALLY_PROCESSED, processed=0))


@pytest.mark.parametrize(
    "state",
    [
        CoverageState.PARTIALLY_PROCESSED,
        CoverageState.QUARANTINED,
        CoverageState.UNSUPPORTED,
        CoverageState.UNAVAILABLE,
        CoverageState.STALE,
    ],
)
def test_incomplete_states_cannot_look_complete(state: CoverageState) -> None:
    with pytest.raises(ValidationError, match="requires partial_result"):
        _disclosure(coverage=_coverage(state=state, processed=0))


def test_counts_cannot_exceed_eligible() -> None:
    with pytest.raises(ValidationError, match="cannot exceed eligible"):
        Coverage(state=CoverageState.PROCESSED, eligible=1, processed=1, quarantined=1)


def test_truncation_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="must state a reason"):
        Truncation(is_truncated=True)


def test_untruncated_result_cannot_carry_a_cursor() -> None:
    with pytest.raises(ValidationError, match="cannot carry truncation details"):
        Truncation(is_truncated=False, next_cursor="cursor")


def test_truncated_result_is_partial() -> None:
    with pytest.raises(ValidationError, match="must set partial_result"):
        _disclosure(truncation=Truncation(is_truncated=True, reason="page_size"))


def test_disclosure_defaults_to_private_and_not_cloud_eligible() -> None:
    disclosure = _disclosure()
    assert disclosure.classification.value == "private_local"
    assert disclosure.cloud_eligible is False


@pytest.mark.parametrize(
    "classification", [Classification.PRIVATE_LOCAL, Classification.RESTRICTED_LOCAL]
)
def test_disclosure_cannot_claim_eligibility_the_classification_denies(
    classification: Classification,
) -> None:
    with pytest.raises(ValidationError, match="never cloud eligible"):
        _disclosure(classification=classification, cloud_eligible=True)


def test_synthetic_test_data_may_declare_cloud_eligibility() -> None:
    disclosure = _disclosure(classification=Classification.SYNTHETIC_TEST, cloud_eligible=True)
    assert disclosure.cloud_eligible is True


def test_envelope_requires_exactly_one_of_disclosure_or_error() -> None:
    with pytest.raises(ValidationError, match="exactly one of disclosure or error"):
        ResponseEnvelope(
            request_id="req-1", correlation_id="corr_abc123def456", completed_at=OBSERVED
        )
    with pytest.raises(ValidationError, match="exactly one of disclosure or error"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            disclosure=_disclosure(),
            error=ProblemDetail(
                code=ErrorCode.DENIED,
                message="denied",
                correlation_id="corr_abc123def456",
                retry=RetryGuidance.AFTER_AUTHORITY_CHANGE,
            ),
        )


def test_error_response_cannot_carry_a_result() -> None:
    with pytest.raises(ValidationError, match="cannot carry a result"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"leaked": True},
            error=ProblemDetail(
                code=ErrorCode.DENIED,
                message="denied",
                correlation_id="corr_abc123def456",
                retry=RetryGuidance.AFTER_AUTHORITY_CHANGE,
            ),
        )


def test_error_correlation_id_must_match_the_envelope() -> None:
    with pytest.raises(ValidationError, match="must match the envelope"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            error=ProblemDetail(
                code=ErrorCode.DENIED,
                message="denied",
                correlation_id="corr_zzz999zzz999",
                retry=RetryGuidance.AFTER_AUTHORITY_CHANGE,
            ),
        )
