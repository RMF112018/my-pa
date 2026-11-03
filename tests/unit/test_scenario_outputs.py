"""Schedule Scenarios S6-1: client-asserted output checks (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 4: the server
checks schema, bounds and consistency only — exact keys, integers, binding
equalities, percentile monotonicity, contiguous histograms summing to the
iteration count, keys present in the version, the distribution digest against
its own recomputation, and the kind's required part. It never re-samples.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Final

from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.scenario.canonical import content_sha256, distribution_spec_sha256
from my_pa.domain.schedule.scenario.outputs import (
    OUTPUT_AUTHORITY,
    BaseRunBinding,
    OutputBinding,
    OutputKind,
    OutputRefusal,
    OutputRefusalReason,
    ValidatedOutput,
    validate_output,
)
from tests.fixtures.schedule_scenario import GOLDEN_NETWORKS

R = OutputRefusalReason
CONTENT: Final = GOLDEN_NETWORKS["G02"]
VERSION: Final = "sscv_" + "v" * 26
RUN: Final = "scpm_" + "r" * 26
BINDING: Final = OutputBinding(
    version_id=VERSION,
    content_sha256=content_sha256(CONTENT),
    activity_keys=frozenset(activity.key for activity in CONTENT.activities),
    distribution_spec_sha256=distribution_spec_sha256(CONTENT),
    base_run=BaseRunBinding(run_id=RUN, project_finish="2027-01-07T16:00"),
)


def _document() -> dict[str, object]:
    return {
        "version_id": VERSION,
        "content_sha256": content_sha256(CONTENT),
        "base_cpm_run_id": RUN,
        "kind": "monte_carlo",
        "run_config": {
            "tool_name": "client-mc",
            "tool_version": "1.2.0",
            "seed": "seed_42",
            "iterations": 1000,
            "sampling": "independent",
            "engine": "my-pa-cpm-v1",
            "distribution_spec_sha256": distribution_spec_sha256(CONTENT),
        },
        "deterministic_finish": "2027-01-07T16:00",
        "finish_percentiles": [
            {"p": 10, "finish": "2027-01-07T16:00"},
            {"p": 50, "finish": "2027-01-08T12:00"},
            {"p": 90, "finish": "2027-01-11T16:00"},
        ],
        "finish_histogram": [
            {"start": "2027-01-07T00:00", "end": "2027-01-08T00:00", "count": 300},
            {"start": "2027-01-08T00:00", "end": "2027-01-12T00:00", "count": 700},
        ],
        "activity_criticality": [
            {"activity_key": "x:A", "critical_iterations": 1000},
            {"activity_key": "x:C", "critical_iterations": 120},
        ],
        "activity_finish_percentiles": [
            {"activity_key": "x:D", "percentiles": [{"p": 50, "finish": "2027-01-08T12:00"}]}
        ],
        "sensitivity": [
            {"activity_key": "x:B", "metric": "spearman_rank_milli", "value": 870},
            {"activity_key": "x:B", "metric": "duration_cruciality_milli", "value": -15},
        ],
    }


def _reason(document: object, binding: OutputBinding = BINDING) -> OutputRefusalReason | None:
    outcome = validate_output(document, binding)
    return outcome.reason if isinstance(outcome, OutputRefusal) else None


def test_a_valid_output_is_normalized_and_digested() -> None:
    outcome = validate_output(_document(), BINDING)
    assert isinstance(outcome, ValidatedOutput)
    assert outcome.kind is OutputKind.MONTE_CARLO
    assert outcome.document["schema"] == "schedule-scenario-output-v1"
    assert (
        outcome.payload_sha256
        == hashlib.sha256(
            b"schedule-scenario-output-v1\n" + canonical_json_bytes(dict(outcome.document))
        ).hexdigest()
    )
    minimal = _document()
    for part in (
        "base_cpm_run_id",
        "deterministic_finish",
        "finish_histogram",
        "activity_criticality",
        "activity_finish_percentiles",
        "sensitivity",
    ):
        del minimal[part]
    small = validate_output(minimal, BINDING)
    assert isinstance(small, ValidatedOutput)
    assert small.document["sensitivity"] is None
    assert small.document["base_cpm_run_id"] is None
    assert OUTPUT_AUTHORITY == "client_asserted"


def test_output_distribution_digest_must_match() -> None:
    document = _document()
    document["run_config"]["distribution_spec_sha256"] = "0" * 64  # type: ignore[index]
    assert _reason(document) is R.DISTRIBUTION_DIGEST
    assert _reason(_document()) is None


def test_output_histogram_counts_sum_to_iterations() -> None:
    document = _document()
    document["finish_histogram"][1]["count"] = 699  # type: ignore[index]
    assert _reason(document) is R.HISTOGRAM
    gap = _document()
    gap["finish_histogram"][1]["start"] = "2027-01-08T01:00"  # type: ignore[index]
    assert _reason(gap) is R.HISTOGRAM
    empty_bin = _document()
    empty_bin["finish_histogram"][0]["end"] = "2027-01-07T00:00"  # type: ignore[index]
    assert _reason(empty_bin) is R.HISTOGRAM


def test_binding_equalities() -> None:
    for name, value in (
        ("version_id", "sscv_" + "w" * 26),
        ("content_sha256", "f" * 64),
        ("base_cpm_run_id", "scpm_" + "s" * 26),
        ("deterministic_finish", "2027-01-08T16:00"),
    ):
        document = _document()
        document[name] = value
        assert _reason(document) is R.BINDING, name
    unbound = OutputBinding(
        version_id=BINDING.version_id,
        content_sha256=BINDING.content_sha256,
        activity_keys=BINDING.activity_keys,
        distribution_spec_sha256=BINDING.distribution_spec_sha256,
    )
    assert _reason(_document(), unbound) is R.BINDING
    without_run = _document()
    del without_run["base_cpm_run_id"]
    assert _reason(without_run, unbound) is None


def test_monotonic_percentiles_and_known_keys() -> None:
    document = _document()
    document["finish_percentiles"][1]["p"] = 10  # type: ignore[index]
    assert _reason(document) is R.MONOTONICITY
    document = _document()
    document["finish_percentiles"][2]["finish"] = "2027-01-07T08:00"  # type: ignore[index]
    assert _reason(document) is R.MONOTONICITY
    document = _document()
    document["activity_criticality"][0]["activity_key"] = "x:Z"  # type: ignore[index]
    assert _reason(document) is R.UNKNOWN_ACTIVITY
    document = _document()
    document["activity_criticality"][1]["activity_key"] = "x:A"  # type: ignore[index]
    assert _reason(document) is R.SHAPE
    document = _document()
    document["activity_criticality"][1]["critical_iterations"] = 1001  # type: ignore[index]
    assert _reason(document) is R.SHAPE


def test_kind_requires_its_part() -> None:
    document = _document()
    document["kind"] = "sensitivity"
    assert _reason(document) is None
    document["sensitivity"] = []
    assert _reason(document) is R.KIND_PRESENCE
    document = _document()
    document["kind"] = "criticality"
    del document["activity_criticality"]
    assert _reason(document) is R.KIND_PRESENCE


def test_shape_refusals() -> None:
    mutations = [
        lambda d: d.__setitem__("unexpected", 1),
        lambda d: d.pop("run_config"),
        lambda d: d.__setitem__("schema", "schedule-scenario-output-v2"),
        lambda d: d.__setitem__("kind", "forecast"),
        lambda d: d["run_config"].__setitem__("iterations", 0),
        lambda d: d["run_config"].__setitem__("iterations", 10.0),
        lambda d: d["run_config"].__setitem__("sampling", "correlated"),
        lambda d: d["run_config"].__setitem__("engine", "p6"),
        lambda d: d["run_config"].__setitem__("seed", "has space"),
        lambda d: d["run_config"].__setitem__("tool_name", ""),
        lambda d: d.__setitem__("version_id", "sscn_" + "v" * 26),
        lambda d: d["finish_percentiles"].__setitem__(0, {"p": 100, "finish": "2027-01-07T16:00"}),
        lambda d: d["sensitivity"][0].__setitem__("value", 1001),
        lambda d: d["sensitivity"][0].__setitem__("metric", "pearson"),
        lambda d: d.__setitem__("finish_histogram", [{"start": "x", "end": "y", "count": 1}]),
        lambda d: d.__setitem__(
            "activity_finish_percentiles",
            [
                {
                    "activity_key": "x:D",
                    "percentiles": [{"p": k + 1, "finish": "2027-01-08T12:00"} for k in range(10)],
                }
            ],
        ),
    ]
    for index, mutate in enumerate(mutations):
        document = copy.deepcopy(_document())
        mutate(document)
        assert _reason(document) is R.SHAPE, index
    assert _reason("not an object") is R.SHAPE


def test_output_size_is_bounded() -> None:
    document = _document()
    keys = sorted(BINDING.activity_keys)
    big = OutputBinding(
        version_id=VERSION,
        content_sha256=BINDING.content_sha256,
        activity_keys=frozenset(f"x:{index:060d}" for index in range(25_000)) | set(keys),
        distribution_spec_sha256=BINDING.distribution_spec_sha256,
        base_run=BINDING.base_run,
    )
    document["kind"] = "criticality"
    document["activity_criticality"] = [
        {"activity_key": f"x:{index:060d}", "critical_iterations": 1} for index in range(16_000)
    ]
    assert _reason(document, big) is R.SIZE
