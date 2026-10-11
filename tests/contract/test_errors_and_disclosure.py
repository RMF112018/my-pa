"""Typed errors and the truthfulness rules on the disclosure envelope."""

from __future__ import annotations

import typing
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from my_pa.application.error_vocabularies import STATIC_VOCABULARIES, VOCABULARY_SOURCES
from my_pa.application.errors import (
    AmbiguousRequestError,
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    QuarantinedError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
    invalid_choice,
    problem_detail,
)
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
from my_pa.contracts.v1.errors import (
    MAX_ALLOWED_VALUE_ENTRIES,
    MAX_ALLOWED_VALUES,
    AllowedValues,
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
    # A nested model is walked through its own fields: a string inside an
    # element model is still a string on the wire.
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return any(
            _carries_a_string(field.annotation) for field in annotation.model_fields.values()
        )
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
        "allowed_values": "detail and value token patterns and both arity bounds",
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


#: The two limitation tokens WP-4B3 deleted from the emittable vocabulary. Both
#: said the same missing fact — nothing persisted the object set under a root, so
#: the denominator was unmeasured and the numerator was gathered from the whole
#: source — and `knowledge.enrollment_objects` is that fact.
REMOVED_TOKENS = ("eligible_total_not_persisted", "scope_is_source_wide_not_root_bounded")


def test_no_disclosure_can_emit_the_two_removed_tokens() -> None:
    """A source-text scan over `src/`, and the reason it is a scan.

    The logic these tokens gated was written out **twice** — once in
    `application.disclosure` and once in `infrastructure.persistence.search` —
    because the two layers may not import each other. That is the shape of this
    campaign's signature defect: a test that built one envelope and asserted the
    token was absent would pass with the other copy fully intact, because no
    request reaches both. Scanning the source is what covers both copies and any
    third nobody has written yet.

    Asserted against the literal strings rather than against `Limitation`, so
    reintroducing either under a new enum member is still caught. The scan reads
    every `.py` under `src/` — its own count is asserted non-zero first, because
    a scan that opened nothing agrees with a clean tree.
    """
    package = Path(__file__).resolve().parents[2] / "src"
    modules = sorted(package.rglob("*.py"))
    assert len(modules) > 50, f"the scan found only {len(modules)} modules"

    offending = {
        f"{module.relative_to(package)}:{number}": token
        for module in modules
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), start=1)
        for token in REMOVED_TOKENS
        if token in line
    }
    assert not offending, f"a deleted limitation token is still in the source: {offending}"


# ---- allowed values (R3) -----------------------------------------------------

CORRELATION = "corr_abc123def456"


def _rendered(error: ApplicationError) -> ProblemDetail:
    return problem_detail(error, correlation_id=CORRELATION)


#: Detail-name segments that say the field holds an identifier or a handle on
#: tenant data. A detail carrying any of them is never a closed vocabulary.
IDENTIFIER_SEGMENTS = frozenset(
    {
        "id",
        "ids",
        "key",
        "keys",
        "ref",
        "refs",
        "reference",
        "references",
        "handle",
        "handles",
        "cursor",
        "digest",
        "sha256",
        "token",
        "url",
    }
)

#: Final detail-name segments that say the field is free text.
FREE_TEXT_SEGMENTS = frozenset(
    {
        "body",
        "comment",
        "content",
        "description",
        "label",
        "markdown",
        "message",
        "name",
        "notes",
        "query",
        "reason",
        "snippet",
        "statement",
        "text",
        "title",
        "value",
    }
)


def _identifier_or_free_text(detail: SafeDetail) -> bool:
    segments = detail.value.split("_")
    return bool(IDENTIFIER_SEGMENTS & set(segments)) or segments[-1] in FREE_TEXT_SEGMENTS


def test_the_detail_name_screen_recognises_what_it_must_refuse() -> None:
    """The screen below is only as good as this: it must fire on real id/text details."""
    for detail in (
        SafeDetail.ENTITY_ID,
        SafeDetail.DEPENDENCY_REPORT_IDS,
        SafeDetail.IDEMPOTENCY_KEY,
        SafeDetail.ORIGIN_EVIDENCE_REF,
        SafeDetail.CURSOR,
        SafeDetail.TEXT,
        SafeDetail.DISPLAY_NAME,
        SafeDetail.CORRECTED_VALUE,
    ):
        assert _identifier_or_free_text(detail), detail


def test_no_static_vocabulary_names_an_identifier_or_free_text_field() -> None:
    """R3: an identifier, a key, a reference or free text is never a vocabulary.

    And the report kinds are not static at all: they become a per-Principal
    registry, so `artifact_kind` must reach a refusal only through the raise
    site's explicit list.
    """
    offending = sorted(d.value for d in STATIC_VOCABULARIES if _identifier_or_free_text(d))
    assert not offending, f"identifier or free-text detail(s) mapped: {offending}"
    assert SafeDetail.ARTIFACT_KIND not in STATIC_VOCABULARIES


def test_every_static_vocabulary_is_a_domain_enum() -> None:
    """R3: every listed value is a member of a domain enum, in declaration order."""
    assert set(STATIC_VOCABULARIES) == set(VOCABULARY_SOURCES)
    assert STATIC_VOCABULARIES, "the table is empty"
    for detail, vocabulary in VOCABULARY_SOURCES.items():
        assert isinstance(detail, SafeDetail), detail
        assert isinstance(vocabulary, type), detail
        assert issubclass(vocabulary, StrEnum), detail
        assert vocabulary.__module__.startswith("my_pa.domain."), (detail, vocabulary.__module__)
        assert STATIC_VOCABULARIES[detail] == tuple(m.value for m in vocabulary), detail
        assert len(STATIC_VOCABULARIES[detail]) <= MAX_ALLOWED_VALUES, detail


def test_every_static_vocabulary_renders_completely() -> None:
    """A value the contract refuses would be dropped silently; none may be."""
    for detail, values in STATIC_VOCABULARIES.items():
        problem = _rendered(InvalidRequestError(detail))
        assert problem.allowed_values == (AllowedValues(detail=detail.value, values=values),)


def test_invalid_choice_lists_the_enum_in_declaration_order() -> None:
    problem = _rendered(invalid_choice(SafeDetail.STAGE, Classification))
    assert problem.safe_details == (SafeDetail.STAGE.value,)
    assert problem.allowed_values == (
        AllowedValues(detail="stage", values=tuple(c.value for c in Classification)),
    )


def test_an_explicit_vocabulary_overrides_the_static_table() -> None:
    detail = SafeDetail.ASSIGNMENT_TYPE
    assert detail in STATIC_VOCABULARIES
    error = InvalidRequestError(detail, allowed_values={detail: ("only_this_one",)})
    assert _rendered(error).allowed_values == (
        AllowedValues(detail=detail.value, values=("only_this_one",)),
    )


def test_an_explicit_vocabulary_for_a_detail_the_error_lacks_is_not_rendered() -> None:
    error = InvalidRequestError(
        SafeDetail.TITLE, allowed_values={SafeDetail.ARTIFACT_KIND: ("focus_report",)}
    )
    assert _rendered(error).allowed_values == ()


def test_a_vocabulary_longer_than_the_bound_is_a_marked_prefix() -> None:
    """R3 bound: 100 values list as the first 64, in order, with `truncated` set."""
    values = tuple(f"value_{index:03d}" for index in range(100))
    entry = AllowedValues.bounded("selector", values)
    assert entry.values == values[:MAX_ALLOWED_VALUES]
    assert entry.truncated is True
    assert MAX_ALLOWED_VALUES == 64
    rendered = _rendered(
        InvalidRequestError(SafeDetail.SELECTOR, allowed_values={SafeDetail.SELECTOR: values})
    )
    assert rendered.allowed_values == (entry,)
    assert AllowedValues.bounded("selector", values[:64]).truncated is False


def test_the_contract_refuses_more_than_the_bound() -> None:
    with pytest.raises(ValidationError):
        AllowedValues(detail="selector", values=tuple(f"v{i}" for i in range(65)))
    with pytest.raises(ValidationError):
        AllowedValues(detail="selector", values=())
    details = tuple(f"field_{index}" for index in range(MAX_ALLOWED_VALUE_ENTRIES + 1))
    assert MAX_ALLOWED_VALUE_ENTRIES == 16
    with pytest.raises(ValidationError):
        _problem(
            safe_details=details[:16],
            allowed_values=tuple(AllowedValues(detail=d, values=("a",)) for d in details),
        )


@pytest.mark.parametrize(
    "value",
    [
        "/Users/someone/tax.pdf",
        "someone@example.com",
        "two words",
        "a" * 65,
        "",
        "-leading",
        "quote'd",
        "x:y",
    ],
)
def test_allowed_values_refuse_anything_but_a_short_token(value: str) -> None:
    with pytest.raises(ValidationError):
        AllowedValues(detail="selector", values=(value,))


def test_allowed_values_accept_upper_and_lower_case_tokens() -> None:
    assert AllowedValues(detail="selector", values=("READY", "all-open", "p1", "v1.2")).values


def test_allowed_values_detail_must_be_a_rejected_field() -> None:
    entry = AllowedValues(detail="priority", values=("p1",))
    assert _problem(safe_details=("priority",), allowed_values=(entry,)).allowed_values
    with pytest.raises(ValidationError, match="detail in safe_details"):
        _problem(safe_details=("title",), allowed_values=(entry,))
    with pytest.raises(ValidationError, match="at most once"):
        _problem(safe_details=("priority",), allowed_values=(entry, entry))
    with pytest.raises(ValidationError):
        AllowedValues(detail="Not A Token", values=("p1",))


def test_only_invalid_request_may_list_allowed_values() -> None:
    entry = AllowedValues(detail="priority", values=("p1",))
    with pytest.raises(ValidationError, match="only invalid_request"):
        ProblemDetail(
            code=ErrorCode.CONFLICT,
            message="conflict",
            correlation_id=CORRELATION,
            retry=RetryGuidance.AFTER_REFRESH,
            safe_details=("priority",),
            allowed_values=(entry,),
        )


@pytest.mark.parametrize(
    "error_type",
    [
        AmbiguousRequestError,
        ConflictError,
        DeniedError,
        InternalError,
        NotFoundError,
        QuarantinedError,
        UnavailableError,
        UnsupportedError,
    ],
)
def test_a_non_invalid_request_error_never_carries_allowed_values(
    error_type: type[ApplicationError],
) -> None:
    detail = SafeDetail.PRIORITY
    assert detail in STATIC_VOCABULARIES
    problem = _rendered(error_type(detail, allowed_values={detail: ("p1",)}))
    assert problem.allowed_values == ()
    assert "allowed_values" not in problem.to_canonical_dict()


def test_a_problem_without_allowed_values_encodes_exactly_as_before() -> None:
    """Backward compatibility, both directions.

    An empty list is omitted, so every existing error keeps its exact bytes; and
    a problem received in the old shape still validates.
    """
    old_shape = {
        "code": "invalid_request",
        "message": "the request is malformed, incomplete, or contradictory",
        "correlation_id": CORRELATION,
        "retry": "after_correction",
        "safe_details": ["title"],
    }
    parsed = ProblemDetail.model_validate(old_shape)
    assert parsed.allowed_values == ()
    assert parsed.to_canonical_dict() == old_shape
    rendered = _rendered(InvalidRequestError(SafeDetail.TITLE))
    assert rendered.to_canonical_dict() == old_shape
    envelope = ResponseEnvelope(
        request_id="req-1", correlation_id=CORRELATION, completed_at=OBSERVED, error=rendered
    )
    assert "allowed_values" not in envelope.to_canonical_json()


def test_a_listed_problem_round_trips_through_its_own_encoding() -> None:
    rendered = _rendered(invalid_choice(SafeDetail.PRIORITY, ("p1", "p2")))
    encoded = rendered.to_canonical_dict()
    assert encoded["allowed_values"] == [
        {"detail": "priority", "values": ["p1", "p2"], "truncated": False}
    ]
    assert ProblemDetail.model_validate(encoded) == rendered


def test_a_value_the_contract_refuses_is_dropped_and_not_a_rendering_failure() -> None:
    error = InvalidRequestError(
        SafeDetail.SELECTOR, allowed_values={SafeDetail.SELECTOR: ("ok_value", "not ok")}
    )
    assert _rendered(error).allowed_values == (
        AllowedValues(detail="selector", values=("ok_value",)),
    )
    only_bad = InvalidRequestError(
        SafeDetail.SELECTOR, allowed_values={SafeDetail.SELECTOR: ("/etc/passwd",)}
    )
    assert _rendered(only_bad).allowed_values == ()


def test_a_bare_string_is_not_a_vocabulary() -> None:
    with pytest.raises(TypeError):
        InvalidRequestError(SafeDetail.SELECTOR, allowed_values={SafeDetail.SELECTOR: "abc"})
