"""Deterministic serialisation, roundtrips, and strict parsing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def test_identifier_fields_reject_path_and_host_shaped_values() -> None:
    """The enforceable half of "no leakage": every opaque ID field rejects them.

    Free-prose fields such as `limitations` accept arbitrary strings by design,
    so asserting that a payload this test itself constructed contains no path
    would prove nothing. The guarantee that can be tested is that the fields
    required to be opaque refuse path-, host-, and URL-shaped values.
    """
    payload = json.loads(_envelope().to_canonical_json())
    for bad in ("corr_/Users/someone", "corr_host.example.com", "corr_a@b", "corr_x://y"):
        payload["correlation_id"] = bad
        with pytest.raises(ValidationError):
            ResponseEnvelope.model_validate(payload)


def test_result_rejects_a_set_because_its_order_is_unstable() -> None:
    with pytest.raises(ValidationError, match="no stable order"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"tags": {"alpha", "bravo", "charlie"}},
            disclosure=_disclosure(),
        )


def test_result_rejects_a_nested_set() -> None:
    with pytest.raises(ValidationError, match="no stable order"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"outer": [{"inner": {"a", "b"}}]},
            disclosure=_disclosure(),
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_result_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(ValidationError, match="not representable in JSON"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"ratio": value},
            disclosure=_disclosure(),
        )


def test_result_accepts_ordered_containers() -> None:
    envelope = ResponseEnvelope(
        request_id="req-1",
        correlation_id="corr_abc123def456",
        completed_at=OBSERVED,
        result={"tags": ["alpha", "bravo"], "nested": {"count": 2, "ok": True}},
        disclosure=_disclosure(),
    )
    assert json.loads(envelope.to_canonical_json())["result"]["tags"] == ["alpha", "bravo"]


def test_serialisation_is_identical_across_processes() -> None:
    """Stability within one process cannot detect hash-seed-dependent ordering.

    Each subprocess gets a different PYTHONHASHSEED, so a container whose order
    depended on hashing would produce different bytes here.
    """
    program = """
import sys
from datetime import UTC, datetime
from my_pa.contracts.v1 import (
    Coverage, CoverageState, Disclosure, Freshness, FreshnessState,
    ResponseEnvelope, Scope, Trust,
)
from my_pa.domain.common.provenance import TrustLevel

observed = datetime(2026, 7, 30, 20, 0, 0, tzinfo=UTC)
disclosure = Disclosure(
    scope=Scope(source_ids=("src_abc123def456",)),
    coverage=Coverage(state=CoverageState.PROCESSED, eligible=1, processed=1),
    freshness=Freshness(observed_at=observed, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION),
    trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("source_version",)),
)
envelope = ResponseEnvelope(
    request_id="req-1",
    correlation_id="corr_abc123def456",
    completed_at=observed,
    result={"zeta": 1, "alpha": [3, 2, 1], "mid": {"b": True, "a": None}},
    disclosure=disclosure,
)
sys.stdout.write(envelope.to_canonical_json())
"""
    outputs = set()
    for seed in ("0", "1", "12345", "99999"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        outputs.add(completed.stdout)
    assert len(outputs) == 1, f"serialisation varied across hash seeds: {outputs}"
