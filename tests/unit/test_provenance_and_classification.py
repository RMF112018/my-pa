"""Provenance and classification invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.classification import Classification, is_cloud_eligible
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
