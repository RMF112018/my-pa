"""Deterministic serialisation, roundtrips, and strict parsing."""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import types
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
from my_pa.contracts.v1.base import NondeterministicValueError, ensure_deterministic
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


def test_envelope_rejects_a_wrong_contract_version() -> None:
    # The envelope carries its own check, separate from RequestMetadata's.
    payload = json.loads(_envelope().to_canonical_json())
    payload["contract_version"] = "v2"
    with pytest.raises(ValidationError, match="unsupported contract_version"):
        ResponseEnvelope.model_validate(payload)


def test_nested_result_containers_are_copied_not_aliased() -> None:
    """A frozen envelope's bytes must not change through a caller's reference.

    Pydantic copies only the top-level field, so without rebuilding, a nested
    dict the caller still holds could have a set put back into it after
    validation, changing the serialised output of a supposedly frozen model.
    """
    nested = {"tags": ["alpha"]}
    envelope = ResponseEnvelope(
        request_id="req-1",
        correlation_id="corr_abc123def456",
        completed_at=OBSERVED,
        result={"inner": nested},
        disclosure=_disclosure(),
    )
    before = envelope.to_canonical_json()

    nested["tags"] = ["omega", "beta"]
    nested["smuggled"] = ["/Users/someone/tax.pdf"]

    assert envelope.result is not None
    assert envelope.result["inner"] is not nested
    assert envelope.to_canonical_json() == before


@pytest.mark.parametrize(
    ("label", "build"),
    [
        ("dict_in_dict", lambda held: {"outer": held}),
        ("dict_in_list", lambda held: {"outer": [held]}),
        ("dict_in_tuple", lambda held: {"outer": (held,)}),
        ("dict_in_list_in_list", lambda held: {"outer": [[held]]}),
        ("dict_in_dict_in_list", lambda held: {"outer": [{"mid": held}]}),
    ],
)
def test_alias_is_severed_through_every_container_path(label: str, build: object) -> None:
    """The rebuild must cover the list branch too, not only the dict branch.

    Pinning only dict-in-dict left the list branch free to regress: reverting it
    alone passed the whole suite while the original mutation attack succeeded one
    container level over.
    """
    held: dict[str, object] = {"tags": ["alpha"]}
    envelope = ResponseEnvelope(
        request_id="req-1",
        correlation_id="corr_abc123def456",
        completed_at=OBSERVED,
        result=build(held),  # type: ignore[operator]
        disclosure=_disclosure(),
    )
    before = envelope.to_canonical_json()

    held["tags"] = {"omega", "beta", "gamma"}
    held["smuggled"] = "/Users/someone/tax.pdf"

    assert envelope.to_canonical_json() == before, f"{label}: alias survived the rebuild"
    assert "smuggled" not in envelope.to_canonical_json()


def test_non_string_object_keys_are_rejected_by_the_helper() -> None:
    with pytest.raises(NondeterministicValueError, match="keys must be strings"):
        ensure_deterministic({1: "a"})


@pytest.mark.parametrize(
    "shape",
    [
        collections.OrderedDict({"tags": ["a", "b"]}),
        collections.defaultdict(list, {"tags": ["a", "b"]}),
        type("DictSub", (dict,), {})({"tags": ["a", "b"]}),
        type("ListSub", (list,), {})(["a", "b"]),
    ],
    ids=["ordered_dict", "defaultdict", "dict_subclass", "list_subclass"],
)
def test_container_subclasses_are_rejected_by_the_exact_type_check(shape: object) -> None:
    """Contents are deterministic, so only the exact-type check can reject these.

    Earlier fixtures carried a set inside, which meant the test passed even when
    the exact-type check was relaxed to `isinstance` — the inner set raised
    instead. It proved the set guard twice and the type guard never.
    """
    with pytest.raises(NondeterministicValueError, match="not an accepted JSON container"):
        ensure_deterministic(shape)


@pytest.mark.parametrize(
    "payload",
    [
        {"i": 0, "j": -1, "k": 2**62},
        {"f": 0.0, "g": -1.5, "h": 1e308},
        {"s": "", "t": "value", "u": "unicode ✓"},
        {"b": True, "c": False, "n": None},
        {"nested": {"list": [1, 2.5, "x", True, None], "tuple_becomes_list": (1, 2)}},
    ],
)
def test_accepted_values_survive_the_rebuild_unchanged(payload: dict[str, object]) -> None:
    """The rebuild must preserve values, not merely reject bad ones.

    Rejection was thoroughly tested while fidelity was not, so rewriting every
    int or float to zero during the walk would have gone unnoticed.
    """
    rebuilt = ensure_deterministic(payload)
    expected = json.loads(json.dumps(payload, default=list))
    assert rebuilt == expected


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


def _bypass_shapes() -> dict[str, object]:
    """Containers Pydantic accepts that are not `dict`, `list`, or `tuple`.

    Each of these once slipped past the guard unwalked, carrying a hash-ordered
    set to the wire. `MappingProxyType` matters most: it is this package's own
    idiom for read-only mappings, so it sits on the path a contributor following
    local convention would take.
    """
    return {
        "mapping_proxy": types.MappingProxyType({"tags": {"a", "b", "c"}}),
        "deque": collections.deque([{"a", "b"}]),
        "generator": ({"a", "b"} for _ in range(1)),
        "dict_keys": {"a": 1, "b": 2}.keys(),
        "set": {"a", "b"},
        "frozenset": frozenset({"a", "b"}),
        "bytes": b"raw",
        "custom_object": object(),
    }


@pytest.mark.parametrize("shape", list(_bypass_shapes()))
def test_containers_outside_the_allowlist_are_rejected(shape: str) -> None:
    """The guard is an allowlist, so an unrecognised container cannot slip past.

    The earlier blocklist version tested for `set` and walked only concrete
    `dict`/`list`/`tuple`, so every shape here reached serialisation unchecked.
    """
    with pytest.raises(ValidationError):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"payload": _bypass_shapes()[shape]},
            disclosure=_disclosure(),
        )


def test_excessive_nesting_fails_as_validation_not_recursion_error() -> None:
    deep: object = "leaf"
    for _ in range(200):
        deep = [deep]
    with pytest.raises(ValidationError, match="levels deep"):
        ResponseEnvelope(
            request_id="req-1",
            correlation_id="corr_abc123def456",
            completed_at=OBSERVED,
            result={"deep": deep},
            disclosure=_disclosure(),
        )


def test_key_order_is_canonical_across_processes() -> None:
    """Keys are inserted in hash order, so this fails if `sort_keys` is dropped.

    An earlier version of this test used a fixed literal payload. Because
    `canonical_json` sorts keys and CPython dicts iterate in insertion order,
    that payload produced identical bytes even with the determinism guard
    removed entirely — it could not fail. Building the dict by iterating a set
    makes insertion order genuinely hash-dependent.
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
# Insertion order here follows set iteration, which varies with PYTHONHASHSEED.
payload = {key: len(key) for key in {"zeta", "alpha", "mid", "kappa", "beta", "omega"}}
envelope = ResponseEnvelope(
    request_id="req-1",
    correlation_id="corr_abc123def456",
    completed_at=observed,
    result=payload,
    disclosure=disclosure,
)
sys.stdout.write(envelope.to_canonical_json())
"""
    outputs = set()
    insertion_orders = set()
    for seed in ("0", "1", "12345", "99999"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", program], capture_output=True, text=True, check=True, env=env
        )
        outputs.add(completed.stdout)
        probe = subprocess.run(
            [sys.executable, "-c", 'print(list({"zeta","alpha","mid","kappa","beta","omega"}))'],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        insertion_orders.add(probe.stdout)

    # If the seeds did not actually perturb set iteration, this test would be
    # asserting nothing, so require that they did.
    assert len(insertion_orders) > 1, "PYTHONHASHSEED did not vary set order; test is vacuous"
    assert len(outputs) == 1, f"serialisation varied across hash seeds: {outputs}"
