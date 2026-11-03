"""Schedule Scenarios S6-1: the CPM engine's golden vectors G01-G24 (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 3.4-3.12.
Each expectation below is the contract's table, transcribed (instants written
`MM-DD HH:MM`, 2027 unless the month is 12); `A` is the key `x:A`. Each vector
also pins its frozen `result_sha256` (section 3.12: a change needs an engine
version bump), G02 pins its `content_sha256`, and the operation budget is
exact for G02 (P16).
"""

from __future__ import annotations

import time
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.canonical import (
    content_bytes,
    content_sha256,
    result_bytes,
    result_sha256,
)
from my_pa.domain.schedule.scenario.cpm import (
    CPM_OPERATION_BUDGET,
    CRITICAL_PATH_COUNT_CAP,
    ENGINE_VERSION,
    MAX_CRITICAL_PATHS,
    CpmIssueCode,
    CpmResult,
    CpmStatus,
    result_document,
    run_cpm,
)
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_CONTENT_BYTES,
    MAX_RELATIONSHIPS,
    ActivityState,
    content_problem,
    format_instant,
)
from tests.fixtures.schedule_scenario import (
    DAY,
    GOLDEN_NETWORKS,
    at,
    link,
    maximal_network,
    network,
    task,
)

Row = dict[str, object]


def row(
    es: str,
    ef: str,
    ls: str | None = None,
    lf: str | None = None,
    tf: int | None = 0,
    ff: int | None = 0,
    *,
    rs: str | None = None,
) -> Row:
    """One activity's expectation; `ls`/`lf` omitted = "same", `rs` omitted = ES."""
    return {
        "early_start": es,
        "remaining_start": rs if rs is not None else es,
        "early_finish": ef,
        "late_start": ls if ls is not None else es,
        "late_finish": lf if lf is not None else ef,
        "total_float_minutes": tf,
        "free_float_minutes": ff,
    }


def complete(es: str, ef: str) -> Row:
    return {
        "early_start": es,
        "remaining_start": None,
        "early_finish": ef,
        "late_start": es,
        "late_finish": ef,
        "total_float_minutes": None,
        "free_float_minutes": None,
        "state": ActivityState.COMPLETE,
        "critical": False,
    }


Issue = tuple[str, str | None, str | None, str | None]


def on(code: CpmIssueCode, activity: str | None = None) -> Issue:
    return (code.value, None if activity is None else f"x:{activity}", None, None)


def between(code: CpmIssueCode, pred: str, succ: str) -> Issue:
    return (code.value, None, f"x:{pred}", f"x:{succ}")


C = CpmIssueCode

#: vector -> {"activities", "paths", "issues", "slack", "summary", "considered"}.
EXPECTED: Final[dict[str, dict[str, object]]] = {
    "G01": {
        "activities": {"A": row("01-04 08:00", "01-06 16:00")},
        "paths": [["A"]],
        "issues": [],
        "summary": {"project_finish": "01-06 16:00"},
    },
    "G02": {
        "activities": {
            "A": row("01-04 08:00", "01-04 16:00"),
            "B": row("01-05 08:00", "01-06 16:00"),
            "C": row("01-05 08:00", "01-05 16:00", "01-06 08:00", "01-06 16:00", 480, 480),
            "D": row("01-07 08:00", "01-07 16:00"),
        },
        "paths": [["A", "B", "D"]],
        "issues": [],
        "slack": {("A", "B"): 0, ("A", "C"): 0, ("B", "D"): 0, ("C", "D"): 480},
    },
    "G03": {
        "activities": {
            "A": row("01-04 08:00", "01-06 16:00"),
            "B": row("01-05 08:00", "01-06 16:00", "01-06 08:00", "01-07 16:00", 480, 480),
            "C": row("01-07 08:00", "01-07 16:00"),
        },
        "paths": [["A", "C"]],
        "issues": [],
    },
    "G04": {
        "activities": {
            "A": row("01-04 08:00", "01-05 16:00"),
            "B": row("01-05 12:00", "01-06 12:00"),
        },
        "paths": [["A", "B"]],
        "issues": [],
    },
    "G05": {
        "activities": {
            "A": row("01-04 08:00", "01-04 16:00"),
            "B": row("01-06 08:00", "01-06 16:00"),
        },
        "paths": [["A", "B"]],
        "issues": [on(C.DANGLING_FINISH, "A")],
    },
    "G06a": {
        "activities": {
            "A": row("01-08 08:00", "01-08 16:00"),
            "B": row("01-12 08:00", "01-12 16:00"),
        },
        "paths": [["A", "B"]],
        "issues": [],
        "slack": {("A", "B"): 0},
    },
    "G06b": {
        "activities": {
            "A": row("01-08 08:00", "01-08 16:00", "01-09 08:00", "01-09 16:00", 480, 0),
            "B": row("01-13 08:00", "01-13 16:00"),
        },
        "paths": [["B"]],
        "issues": [],
    },
    "G06c": {
        "activities": {
            "A": row("01-08 08:00", "01-08 16:00", "01-09 08:00", "01-09 16:00", 480, 0),
            "B": row("01-11 08:00", "01-11 16:00"),
        },
        "paths": [["B"]],
        "issues": [],
        "slack": {("A", "B"): 0},
    },
    "G07": {
        "activities": {"A": row("01-04 08:00", "01-07 16:00")},
        "paths": [["A"]],
        "issues": [],
    },
    "G08": {
        "activities": {
            "A": row("01-04 08:00", "01-05 16:00", "12-31 08:00", "01-01 16:00", -960, -960),
            "B": row("01-06 08:00", "01-07 16:00", "01-04 08:00", "01-05 16:00", -960, -960),
            "C": row("01-06 12:00", "01-07 12:00", "01-07 08:00", "01-07 16:00", 240, 240),
        },
        "paths": [["A", "B"]],
        "issues": [on(C.FINISH_NO_LATER_THAN_VIOLATED, "B")],
        "summary": {"negative_float_count": 2},
    },
    "G09": {
        "activities": {
            "A": row("01-04 08:00", "01-05 16:00", "01-01 08:00", "01-04 16:00", -480, -480),
            "B": row("01-05 08:00", "01-05 16:00"),
        },
        "paths": [["A"], ["B"]],
        "issues": [
            on(C.MANDATORY_CONSTRAINT_OVERRIDES_LOGIC, "B"),
            between(C.RELATIONSHIP_VIOLATED, "A", "B"),
        ],
        "slack": {("A", "B"): -480},
    },
    "G10": {
        "activities": {
            "A": row("01-04 08:00", "01-08 16:00", "01-01 08:00", "01-07 16:00", -480, -480),
        },
        "paths": [["A"]],
        "issues": [on(C.MUST_FINISH_BY_VIOLATED)],
    },
    "G11a": {
        "activities": {
            "A": complete("01-04 08:00", "01-04 16:00"),
            "B": row("01-05 08:00", "01-07 16:00", "01-06 08:00", "01-07 16:00", rs="01-06 08:00"),
            "C": row("01-08 08:00", "01-08 16:00"),
            "E": row("01-05 08:00", "01-11 16:00", "01-11 08:00", "01-11 16:00", rs="01-11 08:00"),
        },
        "paths": [["B", "C", "E"]],
        "issues": [between(C.OUT_OF_SEQUENCE, "C", "E")],
        "slack": {("A", "B"): 480},
    },
    "G11b": {
        "activities": {
            "A": complete("01-04 08:00", "01-04 16:00"),
            "B": row("01-05 08:00", "01-07 16:00", "01-06 08:00", "01-07 16:00", rs="01-06 08:00"),
            "C": row("01-08 08:00", "01-08 16:00"),
            "E": row(
                "01-05 08:00",
                "01-06 16:00",
                "01-08 08:00",
                "01-08 16:00",
                960,
                960,
                rs="01-06 08:00",
            ),
        },
        "paths": [["B", "C"]],
        "issues": [between(C.OUT_OF_SEQUENCE, "C", "E")],
        "considered": {("C", "E"): False},
    },
    "G12": {
        "activities": {
            "M0": row("01-04 00:00", "01-04 00:00", "01-04 08:00", "01-04 08:00"),
            "A": row("01-04 08:00", "01-04 16:00"),
            "M1": row("01-04 16:00", "01-04 16:00"),
        },
        "paths": [["M0", "A", "M1"]],
        "issues": [],
    },
    "G13": {
        "activities": {
            "A": {"total_float_minutes": 0},
            "B": row("01-05 08:00", "01-06 16:00"),
            "C": row("01-05 08:00", "01-06 16:00"),
            "E": {
                "early_start": "01-07 08:00",
                "early_finish": "01-07 16:00",
                "total_float_minutes": 0,
            },
        },
        "paths": [["A", "B", "E"], ["A", "C", "E"]],
        "issues": [],
        "summary": {"critical_path_count": 2},
    },
    "G14": {
        "rejected": True,
        "issues": [on(C.CYCLE_DETECTED)],
        "summary": {"cycle": ["x:A", "x:B", "x:C"], "cycle_length": 3, "residual_count": 4},
    },
    "G15": {
        "activities": {
            "A": {"total_float_minutes": 0},
            "B": {"total_float_minutes": 0},
            "E": {"total_float_minutes": 0},
            "C": row("01-05 08:00", "01-05 16:00", "01-06 08:00", "01-06 16:00", 480, 0),
            "X": row("01-06 08:00", "01-06 16:00", "01-07 08:00", "01-07 16:00", 480, 480),
        },
        "paths": [["A", "B", "E"]],
        "issues": [],
    },
    "G16": {"rejected": True, "issues": [on(C.MISSING_DURATION, "A")]},
    "G17": {
        "activities": {"A": row("01-06 08:00", "01-06 16:00")},
        "paths": [["A"]],
        "issues": [],
    },
    "G18": {
        "activities": {
            "A": row("01-04 08:00", "01-05 16:00", "01-01 08:00", "01-04 16:00", -480, -480),
            "B": row("01-06 08:00", "01-06 16:00", "01-05 08:00", "01-05 16:00", -480, -480),
        },
        "paths": [["A", "B"]],
        "issues": [on(C.START_NO_LATER_THAN_VIOLATED, "B")],
    },
    "G19": {
        "activities": {
            "A": row("01-06 08:00", "01-06 16:00"),
            "B": row("01-04 08:00", "01-04 16:00", "01-06 08:00", "01-06 16:00", 960, 960),
        },
        "paths": [["A"]],
        "issues": [],
    },
    "G20": {
        "activities": {"A": row("01-06 08:00", "01-06 16:00")},
        "paths": [["A"]],
        "issues": [on(C.MANDATORY_CONSTRAINT_BEFORE_DATA_DATE, "A")],
    },
    "G21": {
        "activities": {
            "A": row("01-05 08:00", "01-06 16:00", "01-06 08:00", "01-06 16:00", rs="01-06 08:00"),
        },
        "paths": [["A"]],
        "issues": [on(C.CONSTRAINT_IGNORED_STARTED, "A")],
    },
    "G22": {
        "activities": {
            "A": row("01-05 08:00", "01-07 16:00", "01-06 08:00", "01-07 16:00", rs="01-06 08:00"),
            "B": row("01-06 08:00", "01-06 16:00", "01-07 08:00", "01-07 16:00", 480, 480),
        },
        "paths": [["A"]],
        "issues": [on(C.DANGLING_FINISH, "A")],
    },
    "G23": {
        "activities": {
            "A": row("01-06 08:00", "01-06 16:00"),
            "B": row("01-05 08:00", "01-06 16:00", "01-06 08:00", "01-06 16:00", rs="01-06 08:00"),
        },
        "paths": [["A"], ["B"]],
        # Sorted by code in table order: out_of_sequence before dangling_finish.
        "issues": [between(C.OUT_OF_SEQUENCE, "A", "B"), on(C.DANGLING_FINISH, "A")],
        "considered": {("A", "B"): False},
    },
    "G24": {"rejected": True, "issues": [on(C.HORIZON_EXCEEDED, "A")]},
}

#: Frozen by S6-1 (section 3.12); a change needs an engine-version bump.
RESULT_SHA256: Final[dict[str, str]] = {
    "G01": "d41e4b620245083b85653ac8feab0d1151b98ef6f99b666989ca72a8f0a882b7",
    "G02": "4cb033f9a3986b7c8a546b42016be9f0c9f5ed77756eba10b7898746f882e353",
    "G03": "e2f996037325695ebc670c3f7bf78d1c0b043753d2451777808c5b64bde6acf7",
    "G04": "c62a2f6a988a3fc0065e5c000bdf18b7714411319191c3998eff96a35f0cc8ee",
    "G05": "6fd8b1039979cd173a5c30e1631635188252f6a9c38dd1d83275e4285131f3a3",
    "G06a": "7b07d357f0ae495f1fe2ee7a1fb6281c3c583e885f8faae55b6354c4f9638676",
    "G06b": "c428c02a8d291e0640827861e10c0d9e4379f491f080c692f00191214afabea6",
    "G06c": "195f7cb1fa7db08210f4089783eb9726f675fee149cdc0c8f3335d8bbe086524",
    "G07": "a591a8a944f8a9873be00def2bfc4b2e477df364d1e1096b71b70f5089902787",
    "G08": "d5c66ef1aa68acd52207433c4a3ff133fbb6064e24bddc4d9b8b2d608d3db3df",
    "G09": "2db77a782390130358a6e92107564ce98b20757d39523fc8c718958f8f59cdd2",
    "G10": "729885a0e17cace228c13ceed3d59b65625e14de68ece7073b939c8de85d610f",
    "G11a": "91db161a8ed6da60d9db0129017a5da26b85d159320ee7523d86d270ac8f5980",
    "G11b": "647ab044de5598126f5a6f0baeb0d5422d0c05c32333617f538c485e26f94ff9",
    "G12": "07dea15fd390cc2a887e6add07312dd36959e5a81cc1038eae89e84cfc9edde5",
    "G13": "2921b47c9bd7ff8e8ff0ccbfbed1700117012ed4ae955b977062f693a5f5a3d3",
    "G14": "1c2fd498481f1a01521c2b3105aad9ce22ac5040d33ea0b8fdc01ab442d87928",
    "G15": "12c3633db05d986aad5cb31aab7940d4cd84e06ec54c85526e898475413f0a60",
    "G16": "5c893f9edb2f5015f2feee11b2833d2c7a52242df52e89a2edd3c718fea1f109",
    "G17": "7b84ff60c8d356ae759d369946ed47cb1182f99e886d42d292cdebbd03fdb40b",
    "G18": "0b83a830ab9d6f436bd11c5d3379710160f7f75cc726548a134a04a1ccfcd16d",
    "G19": "22d51a225cafb38f4bbce40eb325341d609c797f7f78613bbc375ee7bd6ceefd",
    "G20": "387755c43dc968b51f9af50815e9c1269277016e6fe5eb337ba2cb0c7677dce2",
    "G21": "0ae467cb3f1147a09a8e8c35d091199b2699164789cca073b4b51a05d15b73f6",
    "G22": "711f64959e29fa8a36e406fd96a58928ee3bb3dfc0cb7f95ffc932e6776ba49c",
    "G23": "934f236f037c04663ccf533c238b7ae7d1c16e22f9f779570e7c0efb4b014d9f",
    "G24": "247ec2adf00ca364846555d41e1570679d1f74f55f9fe12b6f2d4fb62b5b77e4",
}

#: G02's frozen content digest (section 3.12).
G02_CONTENT_SHA256: Final = "738090e45c1c3073ba0c4837d4aa753e125ec49d1d457337703e3e079eef73b8"

#: G02's exact operation count under the section 3.11 counting rule (P16), by hand:
#: sort 4 pops + 4 relationships; forward 4 + 4 + 4 shifts + 4 snaps + 4 advances;
#: backward 4 + 4 + 4 shifts + 4 snap-backs + 4 retreats; slack 4 + 4 + 4 relationship
#: W + 4 TF W; critical paths 3 depth-first steps (A, B, D) + 3 DP nodes = 70.
G02_OPERATIONS: Final = 70


def _instant(value: str | None) -> str | None:
    return None if value is None else format_instant(at(value))


def _activity_fields(result: CpmResult, name: str) -> dict[str, object]:
    found = {item.key: item for item in result.activities}[f"x:{name}"]
    fields: dict[str, object] = {
        "early_start": format_instant(found.early_start),
        "remaining_start": None
        if found.remaining_start is None
        else format_instant(found.remaining_start),
        "early_finish": format_instant(found.early_finish),
        "late_start": format_instant(found.late_start),
        "late_finish": format_instant(found.late_finish),
        "total_float_minutes": found.total_float_minutes,
        "free_float_minutes": found.free_float_minutes,
        "state": found.state,
        "critical": found.critical,
    }
    return fields


def _expected_fields(spec: dict[str, object]) -> dict[str, object]:
    instants = {"early_start", "remaining_start", "early_finish", "late_start", "late_finish"}
    return {
        name: _instant(value) if name in instants else value  # type: ignore[arg-type]
        for name, value in spec.items()
    }


@pytest.mark.parametrize("vector", sorted(EXPECTED))
def test_golden_network_matches(vector: str) -> None:
    expected = EXPECTED[vector]
    result = run_cpm(GOLDEN_NETWORKS[vector])
    issues = [
        (issue.code.value, issue.activity_key, issue.pred, issue.succ) for issue in result.issues
    ]
    assert issues == expected["issues"]
    summary = expected.get("summary", {})
    assert isinstance(summary, dict)
    if expected.get("rejected"):
        assert result.status is CpmStatus.REJECTED
        assert result.summary.project_finish is None
        assert result.activities == result.relationships == result.critical_paths == ()
        for name, value in summary.items():
            actual = getattr(result.summary, name)
            assert (list(actual) if isinstance(actual, tuple) else actual) == value, name
        return
    assert result.status is CpmStatus.COMPUTED
    activities = expected["activities"]
    assert isinstance(activities, dict)
    for name, spec in activities.items():
        actual = _activity_fields(result, name)
        for field, value in _expected_fields(spec).items():
            assert actual[field] == value, (name, field)
        if spec.get("total_float_minutes") is not None:
            # Critical = incomplete and TF <= the threshold (0 in every vector).
            assert actual["critical"] is (spec["total_float_minutes"] <= 0), name  # type: ignore[operator]
    assert [[key.removeprefix("x:") for key in path] for path in result.critical_paths] == (
        expected["paths"]
    )
    by_pair = {(item.pred, item.succ): item for item in result.relationships}
    for (pred, succ), slack in expected.get("slack", {}).items():  # type: ignore[attr-defined]
        assert by_pair[(f"x:{pred}", f"x:{succ}")].slack_minutes == slack, (pred, succ)
    for (pred, succ), considered in expected.get("considered", {}).items():  # type: ignore[attr-defined]
        item = by_pair[(f"x:{pred}", f"x:{succ}")]
        assert item.considered is considered
        assert item.slack_minutes is None
        assert item.driving is False
    for name, value in summary.items():
        actual = getattr(result.summary, name)
        assert actual == (at(value) if name == "project_finish" else value), name


def test_every_golden_vector_is_expected_and_frozen() -> None:
    assert sorted(EXPECTED) == sorted(GOLDEN_NETWORKS)
    assert sorted(RESULT_SHA256) == sorted(GOLDEN_NETWORKS)


@pytest.mark.parametrize("vector", sorted(GOLDEN_NETWORKS))
def test_golden_result_sha256_is_frozen(vector: str) -> None:
    result = run_cpm(GOLDEN_NETWORKS[vector])
    document = result_document(result)
    assert document["engine_version"] == ENGINE_VERSION == "my-pa-cpm-v1"
    assert document["input_content_sha256"] == content_sha256(GOLDEN_NETWORKS[vector])
    assert result_sha256(document) == RESULT_SHA256[vector]


def test_g02_content_sha256_is_frozen() -> None:
    assert content_sha256(GOLDEN_NETWORKS["G02"]) == G02_CONTENT_SHA256


def test_operation_budget_is_exact() -> None:
    content = GOLDEN_NETWORKS["G02"]
    assert run_cpm(content).operations == G02_OPERATIONS
    exact = run_cpm(content, operation_budget=G02_OPERATIONS)
    assert exact.status is CpmStatus.COMPUTED
    assert result_document(exact) == result_document(run_cpm(content))
    short = run_cpm(content, operation_budget=G02_OPERATIONS - 1)
    assert short.status is CpmStatus.REJECTED
    assert [(issue.code, issue.activity_key, issue.pred, issue.succ) for issue in short.issues] == [
        (CpmIssueCode.OPERATION_BUDGET_EXCEEDED, None, None, None)
    ]
    assert short.summary.project_finish is None
    assert short.activities == ()


def test_operation_budget_is_keyword_only_and_production_sized() -> None:
    assert CPM_OPERATION_BUDGET == 4_000_000
    content = GOLDEN_NETWORKS["G01"]
    with pytest.raises(TypeError):
        run_cpm(content, 10)  # type: ignore[misc]
    with pytest.raises(ValueError, match="non-negative"):
        run_cpm(content, operation_budget=-1)


def test_topological_order_is_key_ordered() -> None:
    # Five unrelated activities and a fan-in: Kahn's min-heap pops by key, so
    # the order never depends on the order the records were given in.
    content = network(
        [task(name, DAY) for name in ("E", "C", "A", "D", "B", "F")],
        [link("E", "F"), link("A", "F")],
    )
    result = run_cpm(content)
    order = sorted(result.activities, key=lambda item: item.topo_index)
    assert [item.key for item in order] == ["x:A", "x:B", "x:C", "x:D", "x:E", "x:F"]
    chained = network(
        [task(name, DAY) for name in ("A", "B", "C", "D")],
        [link("D", "A"), link("C", "B")],
    )
    order = sorted(run_cpm(chained).activities, key=lambda item: item.topo_index)
    # The heap holds {C, D}: C pops and frees B; {B, D}: B pops; then D frees A.
    assert [item.key for item in order] == ["x:C", "x:B", "x:D", "x:A"]


def _diamond_ladder(rungs: int) -> list[object]:
    activities = [task("S0", DAY)]
    relationships = []
    for rung in range(rungs):
        top, bottom, join = f"T{rung:02d}", f"U{rung:02d}", f"S{rung + 1}"
        activities += [task(top, DAY), task(bottom, DAY), task(join, DAY)]
        relationships += [
            link(f"S{rung}", top),
            link(f"S{rung}", bottom),
            link(top, join),
            link(bottom, join),
        ]
    return [activities, relationships]


def test_critical_path_enumeration_is_bounded() -> None:
    activities, relationships = _diamond_ladder(6)
    result = run_cpm(network(activities, relationships))  # type: ignore[arg-type]
    assert result.summary.critical_path_count == 2**6
    assert len(result.critical_paths) == MAX_CRITICAL_PATHS == 16
    assert result.summary.critical_paths_truncated is True
    assert len(set(result.critical_paths)) == 16
    # Depth-first, successors in key order: the first path takes every top rung.
    assert result.critical_paths[0][1] == "x:T00"
    assert all(len(path) == 13 for path in result.critical_paths)


def test_critical_path_count_saturates() -> None:
    activities, relationships = _diamond_ladder(20)
    result = run_cpm(network(activities, relationships))  # type: ignore[arg-type]
    assert CRITICAL_PATH_COUNT_CAP < 2**20
    assert result.summary.critical_path_count == CRITICAL_PATH_COUNT_CAP
    assert len(result.critical_paths) == 16
    assert result.summary.critical_paths_truncated is True


def test_project_finish_is_the_latest_early_finish() -> None:
    result = run_cpm(GOLDEN_NETWORKS["G15"])
    assert result.summary.project_finish == max(item.early_finish for item in result.activities)
    assert result.summary.project_finish == at("01-08 16:00")


def test_maximal_network_operations_and_time_are_reported() -> None:
    """R8 ruling R-5 / S6-U06: the maximal network is measured (target <= 10 s)."""
    content = maximal_network()
    assert len(content.activities) == MAX_ACTIVITIES
    assert len(content.relationships) == MAX_RELATIONSHIPS
    assert content_problem(content) is None
    assert len(content_bytes(content)) <= MAX_CONTENT_BYTES
    started = time.perf_counter()
    result = run_cpm(content)
    elapsed = time.perf_counter() - started
    size = len(result_bytes(result_document(result)))
    print(f"maximal network: {result.operations} operations, {elapsed:.2f} s, {size} result bytes")
    assert result.status is CpmStatus.COMPUTED
    assert result.operations <= 2_100_000 < CPM_OPERATION_BUDGET
    assert size <= 64 * 1024 * 1024
    assert elapsed <= 10.0
