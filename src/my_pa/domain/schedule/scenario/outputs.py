"""Schedule Scenarios S6-1: client-asserted outputs, checked (contract section 4).

A client computes Monte Carlo (or criticality, or sensitivity) analysis itself
and asserts the result. The server checks **schema, bounds and consistency
only** (section 4.2): exact keys, integer values, the binding equalities, the
percentile and histogram rules, keys that exist in the version, the
distribution digest against the server's own recomputation, and the kind's
required part. It never re-samples and never judges plausibility; the stored
output is labelled `authority = client_asserted`, `authoritative = false`.

Ownership of the version and of the base run is the caller's lookup (S6-3): it
passes what it resolved, and this module compares.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.scenario.canonical import OUTPUT_SCHEMA, output_payload_sha256
from my_pa.domain.schedule.scenario.model import parse_instant

__all__ = [
    "MAX_OUTPUT_BYTES",
    "OUTPUT_AUTHORITY",
    "BaseRunBinding",
    "OutputBinding",
    "OutputKind",
    "OutputRefusal",
    "OutputRefusalReason",
    "ValidatedOutput",
    "validate_output",
]

MAX_OUTPUT_BYTES: Final = 1_048_576
MAX_ITERATIONS: Final = 1_000_000
MAX_PERCENTILES: Final = 99
MAX_HISTOGRAM_BINS: Final = 200
MAX_CRITICALITY_ROWS: Final = 25_000
MAX_ACTIVITY_PERCENTILE_ROWS: Final = 2_000
MAX_ACTIVITY_PERCENTILES: Final = 9
MAX_SENSITIVITY_ROWS: Final = 2_000
OUTPUT_AUTHORITY: Final = "client_asserted"

_TOOL: Final = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
_SEED: Final = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_SUFFIX: Final = r"[A-Za-z0-9]{8,64}"
_VERSION_ID: Final = re.compile(rf"\Asscv_{_ID_SUFFIX}\Z")
_RUN_ID: Final = re.compile(rf"\Ascpm_{_ID_SUFFIX}\Z")


class OutputKind(StrEnum):
    MONTE_CARLO = "monte_carlo"
    CRITICALITY = "criticality"
    SENSITIVITY = "sensitivity"


class OutputEngine(StrEnum):
    MY_PA_CPM_V1 = "my-pa-cpm-v1"
    SERVER_RUNS = "server_runs"
    OTHER = "other"


class SensitivityMetric(StrEnum):
    SPEARMAN_RANK_MILLI = "spearman_rank_milli"
    DURATION_CRUCIALITY_MILLI = "duration_cruciality_milli"


class OutputRefusalReason(StrEnum):
    """Closed; every one maps to the public `invalid_request(OUTPUT)`."""

    SHAPE = "shape"
    SIZE = "size"
    BINDING = "binding"
    DISTRIBUTION_DIGEST = "distribution_digest"
    KIND_PRESENCE = "kind_presence"
    MONOTONICITY = "monotonicity"
    HISTOGRAM = "histogram"
    UNKNOWN_ACTIVITY = "unknown_activity"


@dataclass(frozen=True, slots=True)
class OutputRefusal:
    reason: OutputRefusalReason


@dataclass(frozen=True, slots=True)
class BaseRunBinding:
    """An owned `computed` run of the bound version, as the caller resolved it."""

    run_id: str
    project_finish: str


@dataclass(frozen=True, slots=True)
class OutputBinding:
    """What the server knows about the bound version (section 4.1 "binding")."""

    version_id: str
    content_sha256: str
    activity_keys: frozenset[str]
    distribution_spec_sha256: str
    base_run: BaseRunBinding | None = None


@dataclass(frozen=True, slots=True)
class ValidatedOutput:
    document: Mapping[str, object]
    payload_sha256: str
    kind: OutputKind


class _RefusedError(Exception):
    def __init__(self, reason: OutputRefusalReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _shape() -> _RefusedError:
    return _RefusedError(OutputRefusalReason.SHAPE)


_REQUIRED: Final = frozenset({"version_id", "content_sha256", "kind", "run_config"})
_OPTIONAL: Final = frozenset(
    {
        "schema",
        "base_cpm_run_id",
        "finish_percentiles",
        "finish_histogram",
        "deterministic_finish",
        "activity_criticality",
        "activity_finish_percentiles",
        "sensitivity",
    }
)
_RUN_CONFIG: Final = frozenset(
    {
        "tool_name",
        "tool_version",
        "seed",
        "iterations",
        "sampling",
        "engine",
        "distribution_spec_sha256",
    }
)
_KIND_PART: Final = {
    OutputKind.MONTE_CARLO: "finish_percentiles",
    OutputKind.CRITICALITY: "activity_criticality",
    OutputKind.SENSITIVITY: "sensitivity",
}


def _object(value: object, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _shape()
    return value


def _list(value: object, limit: int) -> list[object]:
    if not isinstance(value, list) or len(value) > limit:
        raise _shape()
    return value


def _int(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise _shape()
    return value


def _match(pattern: re.Pattern[str], value: object) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _shape()
    return value


def _instant(value: object) -> int:
    try:
        return parse_instant(value)
    except ValueError:
        raise _shape() from None


def _enum[E: StrEnum](kind: type[E], value: object) -> E:
    if not isinstance(value, str):
        raise _shape()
    try:
        return kind(value)
    except ValueError:
        raise _shape() from None


def _known(key: object, binding: OutputBinding) -> str:
    if not isinstance(key, str):
        raise _shape()
    if key not in binding.activity_keys:
        raise _RefusedError(OutputRefusalReason.UNKNOWN_ACTIVITY)
    return key


def _percentiles(value: object, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_p, previous_finish = 0, -1
    for raw in _list(value, limit):
        item = _object(raw, frozenset({"p", "finish"}))
        p = _int(item["p"], 1, MAX_PERCENTILES)
        finish = _instant(item["finish"])
        if p <= previous_p or finish < previous_finish:
            raise _RefusedError(OutputRefusalReason.MONOTONICITY)
        previous_p, previous_finish = p, finish
        rows.append({"p": p, "finish": item["finish"]})
    return rows


def _histogram(value: object, iterations: int) -> list[dict[str, object]]:
    bins = _list(value, MAX_HISTOGRAM_BINS)
    rows: list[dict[str, object]] = []
    previous_end: int | None = None
    total = 0
    for raw in bins:
        item = _object(raw, frozenset({"start", "end", "count"}))
        start, end = _instant(item["start"]), _instant(item["end"])
        count = _int(item["count"], 0, MAX_ITERATIONS)
        if start >= end or (previous_end is not None and start != previous_end):
            raise _RefusedError(OutputRefusalReason.HISTOGRAM)
        previous_end = end
        total += count
        rows.append({"start": item["start"], "end": item["end"], "count": count})
    if total != iterations:
        raise _RefusedError(OutputRefusalReason.HISTOGRAM)
    return rows


def _criticality(value: object, iterations: int, binding: OutputBinding) -> list[object]:
    rows: list[object] = []
    seen: set[str] = set()
    for raw in _list(value, MAX_CRITICALITY_ROWS):
        item = _object(raw, frozenset({"activity_key", "critical_iterations"}))
        key = _known(item["activity_key"], binding)
        if key in seen:
            raise _shape()
        seen.add(key)
        rows.append(
            {
                "activity_key": key,
                "critical_iterations": _int(item["critical_iterations"], 0, iterations),
            }
        )
    return rows


def _activity_percentiles(value: object, binding: OutputBinding) -> list[object]:
    rows: list[object] = []
    seen: set[str] = set()
    for raw in _list(value, MAX_ACTIVITY_PERCENTILE_ROWS):
        item = _object(raw, frozenset({"activity_key", "percentiles"}))
        key = _known(item["activity_key"], binding)
        if key in seen:
            raise _shape()
        seen.add(key)
        rows.append(
            {
                "activity_key": key,
                "percentiles": _percentiles(item["percentiles"], MAX_ACTIVITY_PERCENTILES),
            }
        )
    return rows


def _sensitivity(value: object, binding: OutputBinding) -> list[object]:
    rows: list[object] = []
    seen: set[tuple[str, str]] = set()
    for raw in _list(value, MAX_SENSITIVITY_ROWS):
        item = _object(raw, frozenset({"activity_key", "metric", "value"}))
        key = _known(item["activity_key"], binding)
        metric = _enum(SensitivityMetric, item["metric"])
        if (key, metric.value) in seen:
            raise _shape()
        seen.add((key, metric.value))
        rows.append(
            {"activity_key": key, "metric": metric.value, "value": _int(item["value"], -1000, 1000)}
        )
    return rows


def _validated(raw: object, binding: OutputBinding) -> ValidatedOutput:
    if not isinstance(raw, dict) or not _REQUIRED <= set(raw) <= _REQUIRED | _OPTIONAL:
        raise _shape()
    if raw.get("schema", OUTPUT_SCHEMA) != OUTPUT_SCHEMA:
        raise _shape()
    version_id = _match(_VERSION_ID, raw["version_id"])
    content_digest = _match(_SHA256, raw["content_sha256"])
    kind = _enum(OutputKind, raw["kind"])
    config = _object(raw["run_config"], _RUN_CONFIG)
    iterations = _int(config["iterations"], 1, MAX_ITERATIONS)
    if config["sampling"] != "independent":
        raise _shape()
    run_config = {
        "tool_name": _match(_TOOL, config["tool_name"]),
        "tool_version": _match(_TOOL, config["tool_version"]),
        "seed": _match(_SEED, config["seed"]),
        "iterations": iterations,
        "sampling": "independent",
        "engine": _enum(OutputEngine, config["engine"]).value,
        "distribution_spec_sha256": _match(_SHA256, config["distribution_spec_sha256"]),
    }
    base_run_id = raw.get("base_cpm_run_id")
    if base_run_id is not None:
        _match(_RUN_ID, base_run_id)
    deterministic = raw.get("deterministic_finish")
    if deterministic is not None:
        _instant(deterministic)
    parts: dict[str, object] = {
        "finish_percentiles": None,
        "finish_histogram": None,
        "activity_criticality": None,
        "activity_finish_percentiles": None,
        "sensitivity": None,
    }
    if raw.get("finish_percentiles") is not None:
        parts["finish_percentiles"] = _percentiles(raw["finish_percentiles"], MAX_PERCENTILES)
    if raw.get("finish_histogram") is not None:
        parts["finish_histogram"] = _histogram(raw["finish_histogram"], iterations)
    if raw.get("activity_criticality") is not None:
        parts["activity_criticality"] = _criticality(
            raw["activity_criticality"], iterations, binding
        )
    if raw.get("activity_finish_percentiles") is not None:
        parts["activity_finish_percentiles"] = _activity_percentiles(
            raw["activity_finish_percentiles"], binding
        )
    if raw.get("sensitivity") is not None:
        parts["sensitivity"] = _sensitivity(raw["sensitivity"], binding)
    # Binding equalities (section 4.2), after the shape is known to be sound.
    if version_id != binding.version_id or content_digest != binding.content_sha256:
        raise _RefusedError(OutputRefusalReason.BINDING)
    base = binding.base_run
    if base_run_id is not None:
        if base is None or base.run_id != base_run_id:
            raise _RefusedError(OutputRefusalReason.BINDING)
        if deterministic is not None and deterministic != base.project_finish:
            raise _RefusedError(OutputRefusalReason.BINDING)
    if run_config["distribution_spec_sha256"] != binding.distribution_spec_sha256:
        raise _RefusedError(OutputRefusalReason.DISTRIBUTION_DIGEST)
    if not parts[_KIND_PART[kind]]:
        raise _RefusedError(OutputRefusalReason.KIND_PRESENCE)
    document: dict[str, object] = {
        "schema": OUTPUT_SCHEMA,
        "version_id": version_id,
        "content_sha256": content_digest,
        "base_cpm_run_id": base_run_id,
        "kind": kind.value,
        "run_config": run_config,
        "deterministic_finish": deterministic,
        **parts,
    }
    if len(canonical_json_bytes(document)) > MAX_OUTPUT_BYTES:
        raise _RefusedError(OutputRefusalReason.SIZE)
    return ValidatedOutput(
        document=document, payload_sha256=output_payload_sha256(document), kind=kind
    )


def validate_output(raw: object, binding: OutputBinding) -> ValidatedOutput | OutputRefusal:
    """Check one client-asserted output document (section 4.2); never raises for input."""
    try:
        return _validated(raw, binding)
    except _RefusedError as refused:
        return OutputRefusal(refused.reason)
