"""Enrollment bounds, normalization, and the fingerprint the idempotency key binds.

Needs no database and is not marked `database`. The structural half of the
idempotency rule — one row per key — is proved against a real server in
`tests/schema/test_knowledge_schema_migration.py`; what is proved here is that
the comparison the writer makes is a comparison of the right thing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source import enrollment as module
from my_pa.domain.source.enrollment import (
    DEFAULT_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_BYTES,
    MAX_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_ITEMS,
    Enrollment,
    EnrollmentBoundsError,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.registry import issue_identifier

SOURCE = issue_identifier(IdKind.SOURCE)
PRINCIPAL = issue_identifier(IdKind.PRINCIPAL)
ROOT = issue_identifier(IdKind.SOURCE_OBJECT)
OBJECT_A = issue_identifier(IdKind.SOURCE_OBJECT)
OBJECT_B = issue_identifier(IdKind.SOURCE_OBJECT)
WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _request(**overrides: object) -> EnrollmentRequest:
    values: dict[str, object] = {
        "source_id": SOURCE,
        "principal_id": PRINCIPAL,
        "purpose": Purpose.BOUNDED_ENROLLMENT,
        "scope": EnrollmentScope(root_object_id=ROOT),
        "media_types": ("text/plain", "text/markdown"),
        "policy_version": "mcv-1",
        "idempotency_key": "enroll-0000000001",
        "max_items": 100,
        "max_bytes": 1024,
    }
    values.update(overrides)
    return EnrollmentRequest(**values)  # type: ignore[arg-type]


def test_the_enrollment_module_exposes_its_documented_surface() -> None:
    """Guards every other test here against passing on a gutted module."""
    assert set(module.__all__) == {
        "DEFAULT_ENROLLMENT_DEPTH",
        "MAX_ENROLLMENT_BYTES",
        "MAX_ENROLLMENT_DEPTH",
        "MAX_ENROLLMENT_ITEMS",
        "Enrollment",
        "EnrollmentBoundsError",
        "EnrollmentConflictError",
        "EnrollmentRequest",
        "EnrollmentScope",
    }
    for name in module.__all__:
        assert hasattr(module, name), f"{name} is exported but absent"


def test_the_default_depth_is_zero() -> None:
    """Section 9.6: recursion is asked for, never assumed."""
    assert DEFAULT_ENROLLMENT_DEPTH == 0
    assert EnrollmentScope(root_object_id=ROOT).depth == 0
    assert _request().scope.depth == 0


@pytest.mark.parametrize("depth", list(range(MAX_ENROLLMENT_DEPTH + 1)))
def test_depth_inside_the_bound_is_accepted(depth: int) -> None:
    assert EnrollmentScope(root_object_id=ROOT, depth=depth).depth == depth


@pytest.mark.parametrize("depth", [-1, MAX_ENROLLMENT_DEPTH + 1, 10_000])
def test_an_unbounded_enrollment_cannot_be_constructed(depth: int) -> None:
    with pytest.raises(EnrollmentBoundsError, match="depth must be between"):
        EnrollmentScope(root_object_id=ROOT, depth=depth)


def test_a_boolean_is_not_a_depth() -> None:
    # `bool` subclasses `int`, so `depth=True` would otherwise be accepted as 1.
    with pytest.raises(EnrollmentBoundsError, match="depth must be an integer"):
        EnrollmentScope(root_object_id=ROOT, depth=True)


def test_exactly_one_selector_is_required() -> None:
    with pytest.raises(EnrollmentBoundsError, match="exactly one selector"):
        EnrollmentScope()
    with pytest.raises(EnrollmentBoundsError, match="exactly one selector"):
        EnrollmentScope(object_ids=(OBJECT_A,), root_object_id=ROOT)


def test_an_explicit_object_list_has_no_depth() -> None:
    with pytest.raises(EnrollmentBoundsError, match="no depth"):
        EnrollmentScope(object_ids=(OBJECT_A,), depth=1)


def test_a_selector_only_accepts_object_identifiers() -> None:
    with pytest.raises(InvalidIdentifierError):
        EnrollmentScope(object_ids=(SOURCE,))
    with pytest.raises(InvalidIdentifierError):
        EnrollmentScope(root_object_id=SOURCE)


def test_object_identifiers_are_sorted_and_deduplicated() -> None:
    scope = EnrollmentScope(object_ids=(OBJECT_B, OBJECT_A, OBJECT_B))
    assert scope.object_ids == tuple(sorted({OBJECT_A, OBJECT_B}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_items", 0),
        ("max_items", -1),
        ("max_items", MAX_ENROLLMENT_ITEMS + 1),
        ("max_bytes", 0),
        ("max_bytes", MAX_ENROLLMENT_BYTES + 1),
    ],
)
def test_item_and_byte_ceilings_are_enforced(field: str, value: int) -> None:
    with pytest.raises(EnrollmentBoundsError, match=f"{field} must be between"):
        _request(**{field: value})


def test_an_enrollment_cannot_name_more_objects_than_it_permits() -> None:
    """Two bounds that contradict are `invalid_request`, not a race between them.

    An operator who writes `max_items=1` has said the grant covers one object.
    Neither `EnrollmentScope` nor the `max_items` ceiling can see the other, so
    only the request can refuse this, and it must.
    """
    fifty = tuple(issue_identifier(IdKind.SOURCE_OBJECT) for _ in range(50))
    with pytest.raises(EnrollmentBoundsError, match="max_items is 1 but the selector names 50"):
        _request(max_items=1, scope=EnrollmentScope(object_ids=fifty))


def test_naming_exactly_as_many_objects_as_permitted_is_allowed() -> None:
    two = tuple(issue_identifier(IdKind.SOURCE_OBJECT) for _ in range(2))
    assert _request(max_items=2, scope=EnrollmentScope(object_ids=two)).max_items == 2


def test_the_object_count_is_compared_after_deduplication() -> None:
    """A list that repeats one object names one object, so it fits `max_items=1`."""
    request = _request(max_items=1, scope=EnrollmentScope(object_ids=(OBJECT_A, OBJECT_A)))
    assert request.scope.object_ids == (OBJECT_A,)


def test_a_root_selector_is_not_constrained_by_the_object_count() -> None:
    # A root enrollment names no objects; `max_items` bounds what traversal may
    # yield, which is not knowable at construction.
    assert _request(max_items=1, scope=EnrollmentScope(root_object_id=ROOT)).max_items == 1


@pytest.mark.parametrize("media_types", [(), ("text/plain; charset=utf-8",), ("text",), ("*/*",)])
def test_the_content_type_allowlist_is_required_and_parameter_free(
    media_types: tuple[str, ...],
) -> None:
    with pytest.raises(EnrollmentBoundsError):
        _request(media_types=media_types)


@pytest.mark.parametrize(
    "key",
    [
        "short",
        "/synthetic/fixtures/2026",
        "nas.example.com",
        "operator@example.com",
        "enroll 0000000001",
        "a" * 129,
    ],
)
def test_an_idempotency_key_that_could_carry_a_path_or_host_is_rejected(key: str) -> None:
    with pytest.raises(EnrollmentBoundsError, match="idempotency_key"):
        _request(idempotency_key=key)


def test_a_rejected_idempotency_key_is_not_echoed_back() -> None:
    private = "/synthetic/fixtures/2026"
    with pytest.raises(EnrollmentBoundsError) as raised:
        _request(idempotency_key=private)
    assert private not in str(raised.value)


def test_normalization_makes_a_cosmetic_difference_the_same_request() -> None:
    """A retry that reorders or re-cases its inputs is a retry, not a conflict."""
    plain = _request(
        media_types=("text/plain", "text/markdown"),
        scope=EnrollmentScope(object_ids=(OBJECT_A, OBJECT_B)),
    )
    noisy = _request(
        media_types=(" TEXT/MARKDOWN ", "text/plain", "text/plain"),
        scope=EnrollmentScope(object_ids=(OBJECT_B, OBJECT_A, OBJECT_A)),
    )
    assert plain.normalized() == noisy.normalized()
    assert plain.fingerprint == noisy.fingerprint


def test_the_fingerprint_is_stable_across_calls() -> None:
    request = _request()
    assert request.fingerprint == request.fingerprint
    assert len(request.fingerprint) == 64


@pytest.mark.parametrize(
    "override",
    [
        {"scope": EnrollmentScope(root_object_id=ROOT, depth=1)},
        {"scope": EnrollmentScope(object_ids=(OBJECT_A,))},
        {"media_types": ("text/plain",)},
        {"max_items": 99},
        {"max_bytes": 2048},
        {"policy_version": "mcv-2"},
        {"principal_id": issue_identifier(IdKind.PRINCIPAL)},
        {"source_id": issue_identifier(IdKind.SOURCE)},
        {"purpose": Purpose.SOURCE_INSPECTION},
    ],
)
def test_a_material_change_changes_the_fingerprint(override: dict[str, object]) -> None:
    assert _request().fingerprint != _request(**override).fingerprint


def test_the_idempotency_key_is_not_part_of_what_it_labels() -> None:
    """Folding the key into the fingerprint would make the conflict rule dead code.

    Every key would then agree with itself, and a reused key carrying a
    different request would look identical to a first use.
    """
    assert _request().fingerprint == _request(idempotency_key="enroll-0000000002").fingerprint
    assert "idempotency_key" not in _request().normalized()


def test_a_conflict_names_the_existing_enrollment_and_nothing_else() -> None:
    existing = issue_identifier(IdKind.ENROLLMENT)
    error = EnrollmentConflictError(existing)
    assert error.enrollment_id == existing
    assert existing in str(error)
    for leaked in ("/synthetic", "mcv-1", "enroll-0000000001", "text/plain"):
        assert leaked not in str(error)


def test_a_conflict_cannot_be_raised_with_something_that_is_not_an_enrollment() -> None:
    with pytest.raises(InvalidIdentifierError):
        EnrollmentConflictError(issue_identifier(IdKind.SOURCE))


def test_an_accepted_enrollment_records_the_grant_it_was_accepted_under() -> None:
    request = _request()
    accepted = Enrollment(
        enrollment_id=issue_identifier(IdKind.ENROLLMENT),
        source_id=request.source_id,
        principal_id=request.principal_id,
        purpose=request.purpose,
        scope=request.scope,
        media_types=request.media_types,
        policy_version=request.policy_version,
        request_fingerprint=request.fingerprint,
        max_items=request.max_items,
        max_bytes=request.max_bytes,
        accepted_at=WHEN,
    )
    assert accepted.request_fingerprint == request.fingerprint
    assert accepted.accepted_at == WHEN
    # The key labels the request; it is not part of the accepted grant.
    assert "idempotency_key" not in set(Enrollment.__slots__)


def test_an_accepted_enrollment_requires_an_allowlist() -> None:
    request = _request()
    with pytest.raises(EnrollmentBoundsError, match="allowlist"):
        Enrollment(
            enrollment_id=issue_identifier(IdKind.ENROLLMENT),
            source_id=request.source_id,
            principal_id=request.principal_id,
            purpose=request.purpose,
            scope=request.scope,
            media_types=(),
            policy_version=request.policy_version,
            request_fingerprint=request.fingerprint,
            max_items=request.max_items,
            max_bytes=request.max_bytes,
            accepted_at=WHEN,
        )
