"""Schedule Scenarios S6-1: content records, canonical document and digests (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 2.3-2.8,
3.1, 4.3 and 6.3: the fixed-key canonical object and its strict inverse, the
domain-separated digests, the integer-minute axis, field rules, the
cross-reference check, and the closed vocabularies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.model import ScheduleCellState, ScheduleDateCell, ScheduleDurationCell
from my_pa.domain.schedule.scenario.canonical import (
    ScenarioDecodeError,
    change_set_sha256,
    content_bytes,
    content_from_object,
    content_object,
    content_sha256,
    distribution_spec_sha256,
    output_payload_sha256,
    result_sha256,
    scenario_request_digest,
)
from my_pa.domain.schedule.scenario.model import (
    HORIZON_MINUTES,
    ActivityConstraint,
    ActivityKind,
    ActivityProgress,
    CalendarException,
    ConstraintType,
    DistributionKind,
    DurationDistribution,
    LagCalendar,
    ProgressPolicy,
    PublishedReference,
    RelationshipType,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioRelationship,
    ScenarioSettings,
    VersionLabel,
    content_problem,
    format_instant,
    parse_instant,
)
from tests.fixtures.schedule_scenario import C6, DAY, GOLDEN_NETWORKS, STD, link, network, task

#: Frozen: the canonical content digest of `_rich_content()` (P09).
RICH_CONTENT_SHA256: Final = "78087f7fddaa95dac4b49ade68270e1478ec7532ba37c4acb27ab2f9a766184b"


def _reference() -> PublishedReference:
    value = ScheduleCellState.PUBLISHED_VALUE
    return PublishedReference(
        publication_id="spub_" + "a" * 26,
        published_activity_id="A-100",
        original_duration=ScheduleDurationCell(value, Decimal("1.500")),
        remaining_duration=ScheduleDurationCell(ScheduleCellState.PUBLISHED_BLANK, None),
        start=ScheduleDateCell(value, date(2027, 1, 4), "*"),
        finish=ScheduleDateCell(value, date(2027, 1, 5), None),
    )


def _rich_content() -> ScenarioContent:
    """Every field of section 2.3 set at least once."""
    return ScenarioContent(
        data_date=parse_instant("2027-01-06T00:00"),
        settings=ScenarioSettings(
            default_calendar="std",
            lag_calendar=LagCalendar.SUCCESSOR,
            progress_policy=ProgressPolicy.PROGRESS_OVERRIDE,
            must_finish_by=parse_instant("2027-03-01T16:00"),
            critical_float_threshold_minutes=240,
        ),
        calendars=(
            C6,
            ScenarioCalendar(
                "std",
                STD.week,
                (
                    CalendarException(day=date(2027, 1, 18), intervals=()),
                    CalendarException(day=date(2027, 1, 9), intervals=((480, 720),)),
                ),
            ),
        ),
        activities=(
            ScenarioActivity(
                key="sact_" + "b" * 26,
                name="Pour slab",
                kind=ActivityKind.TASK,
                wbs_path=("Site", "Structure"),
                original_minutes=750,
                remaining_minutes=None,
                constraints=(
                    ActivityConstraint(ConstraintType.FNLT, parse_instant("2027-02-01T16:00")),
                    ActivityConstraint(ConstraintType.SNET, parse_instant("2027-01-11T08:00")),
                ),
                distribution=DurationDistribution(
                    DistributionKind.BOUNDED_NORMAL, min=100, max=900, mean=500, sd=50
                ),
                published_reference=_reference(),
            ),
            ScenarioActivity(
                key="x:added.1",
                name="Cure",
                kind=ActivityKind.TASK,
                calendar="c6",
                original_minutes=DAY,
                remaining_minutes=240,
                progress=ActivityProgress(actual_start=parse_instant("2027-01-05T08:00")),
                distribution=DurationDistribution(
                    DistributionKind.TRIANGULAR, min=200, mode=240, max=480
                ),
            ),
            ScenarioActivity(
                key="x:done",
                name="Mobilize",
                kind=ActivityKind.MILESTONE,
                original_minutes=0,
                remaining_minutes=0,
                progress=ActivityProgress(
                    actual_start=parse_instant("2027-01-04T08:00"),
                    actual_finish=parse_instant("2027-01-04T08:00"),
                ),
            ),
        ),
        relationships=(
            ScenarioRelationship("x:done", "sact_" + "b" * 26, RelationshipType.FS, 0),
            ScenarioRelationship("sact_" + "b" * 26, "x:added.1", RelationshipType.SS, -120),
        ),
    )


def test_instants_round_trip_on_the_axis() -> None:
    assert parse_instant("2000-01-01T00:00") == 0
    assert parse_instant("2100-01-01T00:00") == HORIZON_MINUTES == 52_596_000
    assert format_instant(parse_instant("2027-01-04T08:00")) == "2027-01-04T08:00"
    for bad in (
        "1999-12-31T23:59",
        "2100-01-01T00:01",
        "2027-1-4T08:00",
        "2027-02-30T00:00",
        "2027-01-04T24:00",
        "2027-01-04 08:00",
        "2027-01-04T08:00Z",
        0,
    ):
        with pytest.raises(ValueError):
            parse_instant(bad)


def test_content_object_has_every_key_and_canonical_order() -> None:
    document = content_object(_rich_content())
    assert list(document) == [
        "schema",
        "data_date",
        "settings",
        "calendars",
        "activities",
        "relationships",
    ]
    assert [calendar["key"] for calendar in document["calendars"]] == ["c6", "std"]  # type: ignore[index]
    std = document["calendars"][1]  # type: ignore[index]
    assert [item["date"] for item in std["exceptions"]] == ["2027-01-09", "2027-01-18"]
    activities = document["activities"]
    assert [item["key"] for item in activities] == ["sact_" + "b" * 26, "x:added.1", "x:done"]  # type: ignore[index]
    pour = activities[0]  # type: ignore[index]
    assert set(pour) == {
        "key",
        "name",
        "kind",
        "wbs_path",
        "calendar",
        "original_minutes",
        "remaining_minutes",
        "constraints",
        "progress",
        "distribution",
        "published_reference",
    }
    assert [item["type"] for item in pour["constraints"]] == ["SNET", "FNLT"]
    assert pour["calendar"] is None and pour["progress"] is None
    assert pour["distribution"] == {
        "kind": "bounded_normal",
        "min": 100,
        "mean": 500,
        "sd": 50,
        "max": 900,
    }
    assert pour["published_reference"]["original_duration"] == {
        "state": "published_value",
        "value": "1.500",
    }
    assert pour["published_reference"]["start"] == {
        "state": "published_value",
        "value": "2027-01-04",
        "marker": "*",
    }
    assert [(item["pred"], item["succ"]) for item in document["relationships"]] == [  # type: ignore[index]
        ("sact_" + "b" * 26, "x:added.1"),
        ("x:done", "sact_" + "b" * 26),
    ]
    assert document["settings"] == {
        "default_calendar": "std",
        "lag_calendar": "successor",
        "progress_policy": "progress_override",
        "must_finish_by": "2027-03-01T16:00",
        "critical_float_threshold_minutes": 240,
    }


def test_content_round_trips_through_its_object() -> None:
    content = _rich_content()
    document = json.loads(content_bytes(content))
    assert content_from_object(document) == content
    assert content_bytes(content_from_object(document)) == content_bytes(content)
    for golden in GOLDEN_NETWORKS.values():
        assert content_from_object(json.loads(content_bytes(golden))) == golden


def test_content_sha256_vector() -> None:
    content = _rich_content()
    canonical = canonical_json_bytes(content_object(content))
    expected = hashlib.sha256(b"schedule-scenario-content-v1\n" + canonical).hexdigest()
    assert content_sha256(content) == expected == RICH_CONTENT_SHA256
    assert content_sha256(content) != hashlib.sha256(canonical).hexdigest()


def test_decoding_refuses_every_malformed_object() -> None:
    document = json.loads(content_bytes(_rich_content()))
    mutations = [
        lambda d: d.pop("relationships"),
        lambda d: d.__setitem__("extra", 1),
        lambda d: d.__setitem__("schema", "schedule-scenario-content-v2"),
        lambda d: d["settings"].__setitem__("critical_float_threshold_minutes", True),
        lambda d: d["settings"].__setitem__("lag_calendar", "Predecessor"),
        lambda d: d["activities"][1].__setitem__("remaining_minutes", 1.0),
        lambda d: d["activities"][1].__setitem__("remaining_minutes", "240"),
        lambda d: d["activities"][1].pop("distribution"),
        lambda d: d["activities"][1]["distribution"].__setitem__("sd", 3),
        lambda d: d["activities"][0].__setitem__("key", "y:bad"),
        lambda d: d["activities"][0].__setitem__("name", "  padded "),
        lambda d: d["calendars"][0]["week"].pop(),
        lambda d: d["calendars"][1]["exceptions"][0].__setitem__("date", "2027-1-09"),
        lambda d: d["relationships"][0].__setitem__("type", "fs"),
        lambda d: d.__setitem__("data_date", "2027-01-06"),
    ]
    for index, mutate in enumerate(mutations):
        broken = json.loads(json.dumps(document))
        mutate(broken)
        with pytest.raises(ScenarioDecodeError) as raised:
            content_from_object(broken)
        assert str(raised.value) == "not a valid schedule-scenario-content-v1 object", index


def test_field_rules_are_enforced_by_the_records() -> None:
    with pytest.raises(ValueError, match="milestone"):
        ScenarioActivity(key="x:m", name="M", kind=ActivityKind.MILESTONE, remaining_minutes=5)
    with pytest.raises(ValueError, match="complete"):
        task("A", DAY, started="01-04 08:00", finished="01-04 16:00")
    with pytest.raises(ValueError, match="mandatory"):
        task(
            "A",
            DAY,
            constraints=[(ConstraintType.MSO, "01-04 08:00"), (ConstraintType.SNET, "01-04 08:00")],
        )
    with pytest.raises(ValueError, match="early"):
        task(
            "A",
            DAY,
            constraints=[
                (ConstraintType.SNET, "01-04 08:00"),
                (ConstraintType.FNET, "01-05 08:00"),
            ],
        )
    with pytest.raises(ValueError, match="duration"):
        ScenarioActivity(key="x:a", name="A", kind=ActivityKind.TASK, remaining_minutes=5_256_001)
    with pytest.raises(ValueError, match="key"):
        ScenarioActivity(key="x:" + "a" * 65, name="A", kind=ActivityKind.TASK, remaining_minutes=0)
    with pytest.raises(ValueError, match="lag"):
        ScenarioRelationship("x:a", "x:b", RelationshipType.FS, 1_051_201)
    with pytest.raises(ValueError, match="separated"):
        ScenarioCalendar("bad", (((480, 720), (720, 960)),) + ((),) * 6)
    with pytest.raises(ValueError, match="working minute"):
        ScenarioCalendar("idle", ((),) * 7)
    with pytest.raises(ValueError, match="key"):
        ScenarioCalendar("Std", STD.week)
    with pytest.raises(ValueError, match="threshold"):
        ScenarioSettings("std", critical_float_threshold_minutes=525_601)
    with pytest.raises(ValueError, match="min < max"):
        DurationDistribution(DistributionKind.UNIFORM, min=5, max=5)
    with pytest.raises(ValueError, match="parameters"):
        DurationDistribution(DistributionKind.UNIFORM, min=5, max=9, mode=6)
    with pytest.raises(ValueError, match="sd > 0"):
        DurationDistribution(DistributionKind.BOUNDED_NORMAL, min=0, max=9, mean=4, sd=0)
    with pytest.raises(ValueError, match="finish"):
        ActivityProgress(actual_start=10, actual_finish=9)
    with pytest.raises(ValueError, match="date"):
        CalendarException(day=date(2100, 1, 1), intervals=())


def test_content_problem_names_the_first_broken_reference() -> None:
    good = GOLDEN_NETWORKS["G02"]
    assert content_problem(good) is None
    assert content_problem(replace(good, calendars=())) == "1..32 calendars with unique keys"
    assert (
        content_problem(replace(good, settings=ScenarioSettings("c6")))
        == "the default calendar exists"
    )
    assert (
        content_problem(network([task("A", DAY, calendar="c6")])) == "an activity calendar exists"
    )
    assert (
        content_problem(network([task("A", DAY)], [link("A", "B")]))
        == "both relationship ends exist"
    )
    assert (
        content_problem(network([task("A", DAY)], [link("A", "A")]))
        == "a relationship joins two different activities"
    )
    assert (
        content_problem(network([task("A", DAY, started="01-07 08:00")]))
        == "an actual start is not after the data date"
    )
    duplicate = network([task("A", DAY)])
    assert (
        content_problem(replace(duplicate, activities=duplicate.activities * 2))
        == "at most 25000 activities with unique keys"
    )


def test_permuted_inputs_build_equal_contents() -> None:
    content = _rich_content()
    shuffled = ScenarioContent(
        data_date=content.data_date,
        settings=content.settings,
        calendars=tuple(reversed(content.calendars)),
        activities=tuple(reversed(content.activities)),
        relationships=tuple(reversed(content.relationships)),
    )
    assert shuffled == content
    assert content_sha256(shuffled) == content_sha256(content)


def test_distribution_spec_digest_covers_only_activities_with_a_distribution() -> None:
    content = _rich_content()
    spec = [
        {
            "key": "sact_" + "b" * 26,
            "distribution": {
                "kind": "bounded_normal",
                "min": 100,
                "mean": 500,
                "sd": 50,
                "max": 900,
            },
        },
        {
            "key": "x:added.1",
            "distribution": {"kind": "triangular", "min": 200, "mode": 240, "max": 480},
        },
    ]
    expected = hashlib.sha256(
        b"schedule-scenario-distributions-v1\n" + canonical_json_bytes(spec)
    ).hexdigest()
    assert distribution_spec_sha256(content) == expected
    assert (
        distribution_spec_sha256(GOLDEN_NETWORKS["G01"])
        == hashlib.sha256(b"schedule-scenario-distributions-v1\n[]").hexdigest()
    )


def test_every_digest_is_domain_separated() -> None:
    ops = [{"op": "data_date.set", "at": "2027-01-07T00:00"}]
    assert (
        change_set_sha256(ops)
        == hashlib.sha256(
            b"schedule-scenario-change-set-v1\n"
            + canonical_json_bytes({"schema": "schedule-scenario-change-set-v1", "ops": ops})
        ).hexdigest()
    )
    request = {"version_id": "sscv_" + "c" * 26, "idempotency_key": "k" * 16}
    digest = scenario_request_digest("prn_" + "d" * 26, "schedule_cpm_runs.create", request)
    assert (
        digest
        == hashlib.sha256(
            b"schedule-scenario-request-v1\n"
            + canonical_json_bytes(
                {
                    "principal_id": "prn_" + "d" * 26,
                    "capability": "schedule_cpm_runs.create",
                    "request": {"version_id": "sscv_" + "c" * 26},
                }
            )
        ).hexdigest()
    )
    assert digest == scenario_request_digest(
        "prn_" + "d" * 26, "schedule_cpm_runs.create", {"version_id": "sscv_" + "c" * 26}
    )
    with pytest.raises(ValueError, match="schema"):
        result_sha256({"schema": "other"})
    with pytest.raises(ValueError, match="schema"):
        output_payload_sha256({"schema": "other"})


def test_closed_vocabularies() -> None:
    assert [member.value for member in ConstraintType] == [
        "SNET",
        "FNET",
        "SNLT",
        "FNLT",
        "MSO",
        "MFO",
    ]
    assert [member.value for member in RelationshipType] == ["FS", "SS", "FF", "SF"]
    assert [member.value for member in LagCalendar] == [
        "predecessor",
        "successor",
        "twenty_four_hour",
    ]
    assert [member.value for member in ProgressPolicy] == ["retained_logic", "progress_override"]
    assert [member.value for member in VersionLabel] == ["what_if", "update", "simulation_input"]
    assert [member.value for member in ActivityKind] == ["task", "milestone"]
    assert [member.value for member in DistributionKind] == [
        "triangular",
        "pert",
        "uniform",
        "bounded_normal",
    ]
