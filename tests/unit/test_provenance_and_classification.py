"""Provenance and classification invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.classification import (
    CLASSIFICATION_RANK,
    Classification,
    classification_max,
    is_cloud_eligible,
)
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.common.provenance import Provenance, TrustLevel

OBSERVED = datetime(2026, 7, 30, 20, 0, 0, tzinfo=UTC)


def _provenance(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "source_id": "src_abc123def456",
        "source_object_id": "obj_abc123def456",
        "version_id": "ver_abc123def456",
        "extractor": "text",
        "extractor_version": "1.0.0",
        "observed_at": OBSERVED,
        "processed_at": OBSERVED + timedelta(seconds=1),
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def test_provenance_binds_source_object_and_version() -> None:
    provenance = _provenance()
    assert provenance.source_id.startswith("src_")
    assert provenance.source_object_id.startswith("obj_")
    assert provenance.version_id.startswith("ver_")


def test_derived_content_defaults_to_source_bound_not_original() -> None:
    assert _provenance().trust_level is TrustLevel.SOURCE_BOUND_DERIVED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "obj_abc123def456"),
        ("source_object_id", "src_abc123def456"),
        ("version_id", "kn_abc123def456"),
    ],
)
def test_wrong_identifier_kind_is_rejected(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _provenance(**{field: value})


def test_extractor_identity_is_required() -> None:
    with pytest.raises(ValueError, match="extractor"):
        _provenance(extractor="")


def test_processing_cannot_precede_observation() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        _provenance(processed_at=OBSERVED - timedelta(seconds=1))


def test_timestamps_are_normalised_to_utc() -> None:
    eastern = datetime(2026, 7, 30, 16, 0, 0, tzinfo=UTC).astimezone()
    provenance = _provenance(observed_at=eastern, processed_at=eastern)
    assert provenance.observed_at.tzinfo is UTC
    assert provenance.processed_at.tzinfo is UTC


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _provenance(observed_at=datetime(2026, 7, 30))


def test_only_synthetic_test_data_is_cloud_eligible() -> None:
    assert is_cloud_eligible(Classification.SYNTHETIC_TEST) is True
    assert is_cloud_eligible(Classification.PRIVATE_LOCAL) is False
    assert is_cloud_eligible(Classification.RESTRICTED_LOCAL) is False


def test_classification_set_matches_the_contract() -> None:
    assert {item.value for item in Classification} == {
        "synthetic_test",
        "private_local",
        "restricted_local",
    }


# --- KLP-WP-01: public rank and rank-max (R6 plan section 5.2; AC-059 slice) ---


def test_cloud_eligibility_is_unchanged_by_the_public_rank() -> None:
    """AC-059: `is_cloud_eligible` still admits exactly `synthetic_test`."""
    assert {c for c in Classification if is_cloud_eligible(c)} == {Classification.SYNTHETIC_TEST}


def test_the_public_rank_orders_synthetic_below_private_below_restricted() -> None:
    assert dict(CLASSIFICATION_RANK) == {
        Classification.SYNTHETIC_TEST: 0,
        Classification.PRIVATE_LOCAL: 1,
        Classification.RESTRICTED_LOCAL: 2,
    }
    assert set(CLASSIFICATION_RANK) == set(Classification)
    with pytest.raises(TypeError):
        CLASSIFICATION_RANK[Classification.RESTRICTED_LOCAL] = 0  # type: ignore[index]


def test_the_rank_equals_the_frozen_sql_rank_function() -> None:
    """The WP-02 SQL function restates exactly these ranks (matrix schema_functions)."""
    import json
    from pathlib import Path

    matrix = (
        Path(__file__).resolve().parents[1] / "architecture" / "klp_implementation_matrix_r6.json"
    )
    body = next(
        row["body"]
        for row in json.loads(matrix.read_text(encoding="utf-8"))["schema_functions"]
        if row["name"].startswith("knowledge.knowledge_classification_rank")
    )
    for classification, rank in CLASSIFICATION_RANK.items():
        assert f"WHEN '{classification.value}' THEN {rank}" in body


def test_relationship_memory_aliases_the_public_rank() -> None:
    from my_pa.domain.relationship import memory

    assert memory._CLASSIFICATION_RANK is CLASSIFICATION_RANK


@pytest.mark.parametrize(
    ("operands", "expected"),
    [
        ((Classification.SYNTHETIC_TEST,), Classification.SYNTHETIC_TEST),
        (
            (Classification.PRIVATE_LOCAL, Classification.SYNTHETIC_TEST),
            Classification.PRIVATE_LOCAL,
        ),
        (
            (Classification.SYNTHETIC_TEST, Classification.RESTRICTED_LOCAL),
            Classification.RESTRICTED_LOCAL,
        ),
        (
            (
                Classification.RESTRICTED_LOCAL,
                Classification.PRIVATE_LOCAL,
                Classification.SYNTHETIC_TEST,
            ),
            Classification.RESTRICTED_LOCAL,
        ),
    ],
)
def test_classification_max_is_the_rank_max(
    operands: tuple[Classification, ...], expected: Classification
) -> None:
    assert classification_max(*operands) is expected


def test_classification_max_is_monotonic_and_order_independent() -> None:
    members = list(Classification)
    for a in members:
        for b in members:
            assert classification_max(a, b) is classification_max(b, a)
            assert CLASSIFICATION_RANK[classification_max(a, b)] >= CLASSIFICATION_RANK[a]


@pytest.mark.parametrize("bad", ["restricted_local", None, 2])
def test_classification_max_refuses_unknown_values(bad: object) -> None:
    with pytest.raises(TypeError):
        classification_max(Classification.PRIVATE_LOCAL, bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        classification_max(bad)  # type: ignore[arg-type]
