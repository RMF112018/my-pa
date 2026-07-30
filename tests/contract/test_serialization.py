"""Deterministic serialisation, roundtrips, and strict parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from my_pa.contracts.v1 import (
    CONTRACT_VERSION,
    Coverage,
    CoverageState,
    Disclosure,
    Freshness,
    FreshnessState,
    ProblemDetail,
    RequestMetadata,
    ResponseEnvelope,
    Scope,
    SourceReference,
    Trust,
)
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

OBSERVED = datetime(2026, 7, 30, 20, 0, 0, tzinfo=UTC)


def _disclosure() -> Disclosure:
    return Disclosure(
        scope=Scope(source_ids=("src_abc123def456",), enrollment_ids=("enr_abc123def456",)),
        coverage=Coverage(state=CoverageState.PROCESSED, eligible=2, processed=2),
        freshness=Freshness(
            observed_at=OBSERVED, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("source_version",)),
        source_references=(
            SourceReference(
                source_id="src_abc123def456",
                source_object_id="obj_abc123def456",
                version_id="ver_abc123def456",
            ),
        ),
    )


def _request() -> RequestMetadata:
    return RequestMetadata(
        request_id="req-1",
        capability=Capability.KNOWLEDGE_SEARCH,
        purpose=Purpose.KNOWLEDGE_SEARCH,
        principal_id="prn_gateway00001",
        scope=Scope(source_ids=("src_abc123def456",)),
        requested_at=OBSERVED,
    )


def _envelope() -> ResponseEnvelope:
    return ResponseEnvelope(
        request_id="req-1",
        correlation_id="corr_abc123def456",
        completed_at=OBSERVED,
        result={"items": []},
        disclosure=_disclosure(),
    )


MODELS = [_request(), _disclosure(), _envelope()]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: type(m).__name__)
def test_serialisation_is_stable_across_calls(model: object) -> None:
    first = model.to_canonical_json()  # type: ignore[attr-defined]
    for _ in range(5):
        assert model.to_canonical_json() == first  # type: ignore[attr-defined]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: type(m).__name__)
def test_roundtrip_preserves_value_and_bytes(model: object) -> None:
    payload = json.loads(model.to_canonical_json())  # type: ignore[attr-defined]
    restored = type(model).model_validate(payload)
    assert restored == model
    assert restored.to_canonical_json() == model.to_canonical_json()  # type: ignore[attr-defined]


def test_canonical_json_sorts_keys() -> None:
    keys = list(json.loads(_disclosure().to_canonical_json()).keys())
    assert keys == sorted(keys)


def test_equal_values_built_differently_serialise_identically() -> None:
    eastern = timezone(timedelta(hours=-4))
    a = Freshness(observed_at=OBSERVED, state=FreshnessState.STALE)
    b = Freshness(
        observed_at=datetime(2026, 7, 30, 16, 0, 0, tzinfo=eastern), state=FreshnessState.STALE
    )
    assert a.to_canonical_json() == b.to_canonical_json()


def test_timestamps_serialise_as_rfc3339_utc() -> None:
    payload = json.loads(_envelope().to_canonical_json())
    assert payload["completed_at"] == "2026-07-30T20:00:00.000Z"
    assert payload["disclosure"]["freshness"]["observed_at"].endswith("Z")


@pytest.mark.parametrize(
    "model_type", [RequestMetadata, Disclosure, ResponseEnvelope, Scope, Coverage, ProblemDetail]
)
def test_unknown_fields_are_rejected(model_type: type) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model_type.model_validate({"definitely_not_a_field": "x"})


def test_unknown_field_rejected_on_otherwise_valid_payload() -> None:
    payload = json.loads(_request().to_canonical_json())
    payload["smuggled"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RequestMetadata.model_validate(payload)


def test_models_are_frozen() -> None:
    disclosure = _disclosure()
    with pytest.raises(ValidationError):
        disclosure.partial_result = True  # type: ignore[misc]


def test_wrong_contract_version_is_rejected() -> None:
    payload = json.loads(_request().to_canonical_json())
    payload["contract_version"] = "v2"
    with pytest.raises(ValidationError, match="unsupported contract_version"):
        RequestMetadata.model_validate(payload)


def test_contract_version_defaults_to_v1() -> None:
    assert _request().contract_version == CONTRACT_VERSION == "v1"


def test_naive_timestamp_is_rejected() -> None:
    payload = json.loads(_request().to_canonical_json())
    payload["requested_at"] = "2026-07-30T20:00:00"
    with pytest.raises(ValidationError):
        RequestMetadata.model_validate(payload)


def test_malformed_identifier_is_rejected() -> None:
    payload = json.loads(_request().to_canonical_json())
    payload["principal_id"] = "prn_bad"
    with pytest.raises(ValidationError):
        RequestMetadata.model_validate(payload)


def test_scope_rejects_wrong_identifier_kind() -> None:
    with pytest.raises(ValidationError):
        Scope(source_ids=("obj_abc123def456",))


def test_public_payload_carries_no_path_or_host() -> None:
    rendered = _envelope().to_canonical_json()
    for token in ("/Users/", "/home/", "postgres://", "ssh", "://", "\\\\"):
        assert token not in rendered
