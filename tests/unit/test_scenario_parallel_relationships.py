"""Schedule Scenarios S7-7: parallel relationships, content schema v3 (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.7 and the
S7-7 amendment of `docs/architecture/schedule-scenarios-contract.md` sections
2.3, 2.6 and 2.9 (ADR-023, amendment to ADR-017): at most one relationship per
`(pred, succ, type)`; a content holding 2 or more relationships between one
ordered pair is `schedule-scenario-content-v3` (the v2 shape), runs on the
engine its other content requires, and every v1 and v2 document, digest and
result stays byte-identical. Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.model import ScheduleCellState, ScheduleDateCell, ScheduleDurationCell
from my_pa.domain.schedule.scenario import changeset as changeset_module
from my_pa.domain.schedule.scenario import model as model_module
from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    CONTENT_SCHEMA_V2,
    CONTENT_SCHEMA_V3,
    CONTENT_SCHEMAS,
    ScenarioDecodeError,
    content_bytes,
    content_from_object,
    content_object,
    content_schema,
    content_sha256,
)
from my_pa.domain.schedule.scenario.changeset import (
    ChangeOpError,
    ChangeSetApplied,
    ChangeSetRefusal,
    apply_change_set,
)
from my_pa.domain.schedule.scenario.cpm import (
    ENGINE_VERSION,
    ENGINE_VERSION_V2,
    CpmActivityResult,
    CpmStatus,
    engine_version_for,
    result_document,
    run_cpm,
)
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    PublishedReference,
    RelationshipType,
    ScenarioContent,
    content_problem,
    has_parallel_relationships,
)
from tests.fixtures.schedule_scenario import (
    DAY,
    GOLDEN_NETWORKS,
    at,
    link,
    milestone,
    network,
    task,
)

E = ChangeOpError
_REFERENCE: Final = PublishedReference(
    publication_id="spub_" + "a" * 26,
    published_activity_id="A-100",
    original_duration=ScheduleDurationCell(ScheduleCellState.PUBLISHED_VALUE, Decimal("1.500")),
    remaining_duration=ScheduleDurationCell(ScheduleCellState.PUBLISHED_BLANK, None),
    start=ScheduleDateCell(ScheduleCellState.PUBLISHED_VALUE, date(2027, 1, 4), "*"),
    finish=ScheduleDateCell(ScheduleCellState.PUBLISHED_VALUE, date(2027, 1, 5), None),
)
TYPES: Final = tuple(member.value for member in RelationshipType)


def _ladder(*links: tuple[str, int]) -> ScenarioContent:
    """A (2 days) -> B (2 days) through the given (type, lag) links."""
    return network(
        [task("A", 2 * DAY), task("B", 2 * DAY)],
        [link("A", "B", kind, lag) for kind, lag in links],
    )


def _by_key(content: ScenarioContent) -> dict[str, CpmActivityResult]:
    return {item.key: item for item in run_cpm(content).activities}


# ---- v1 / v2 byte identity ------------------------------------------------------------


def _s6_document(content: ScenarioContent) -> bytes:
    """The S6 canonical bytes, relationships sorted by `(pred, succ)` alone."""
    document = content_object(content)
    rows = document["relationships"]
    assert isinstance(rows, list)
    document["relationships"] = sorted(rows, key=lambda row: (row["pred"], row["succ"]))
    return canonical_json_bytes(document)


@pytest.mark.parametrize("vector", sorted(GOLDEN_NETWORKS))
def test_every_golden_content_keeps_its_v1_bytes_and_digest(vector: str) -> None:
    content = GOLDEN_NETWORKS[vector]
    assert not has_parallel_relationships(content)
    schema = content_schema(content)
    assert schema in (CONTENT_SCHEMA, CONTENT_SCHEMA_V2)
    assert content_bytes(content) == _s6_document(content)
    expected = hashlib.sha256(schema.encode() + b"\n" + _s6_document(content)).hexdigest()
    assert content_sha256(content) == expected
    # One relationship per pair: the result rows carry no `type` (S6 shape).
    document = result_document(run_cpm(content))
    rows = document["relationships"]
    assert isinstance(rows, list)
    assert all("type" not in row for row in rows)


def test_a_v2_content_without_parallel_links_stays_v2() -> None:
    content = network(
        [task("A", DAY), milestone("M", ActivityKind.FINISH_MILESTONE)], [link("A", "M")]
    )
    assert content_schema(content) == CONTENT_SCHEMA_V2
    assert engine_version_for(content) == ENGINE_VERSION_V2


# ---- v3 documents ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "kinds",
    [combo for size in (2, 3, 4) for combo in itertools.combinations(TYPES, size)],
    ids="+".join,
)
def test_every_type_combination_on_one_pair_is_a_v3_document(kinds: tuple[str, ...]) -> None:
    links = [link("A", "B", kind, 60 * index) for index, kind in enumerate(kinds)]
    content = network([task("A", DAY), task("B", DAY)], links)
    assert content_problem(content) is None
    assert has_parallel_relationships(content)
    assert content_schema(content) == CONTENT_SCHEMA_V3
    document = content_object(content)
    assert document["schema"] == CONTENT_SCHEMA_V3
    rows = document["relationships"]
    assert isinstance(rows, list)
    assert [row["type"] for row in rows] == sorted(kinds)
    assert content_from_object(document) == content
    canonical = content_bytes(content)
    assert (
        content_sha256(content)
        == hashlib.sha256(b"schedule-scenario-content-v3\n" + canonical).hexdigest()
    )
    # Any input order gives one record and one canonical form.
    for permuted in itertools.permutations(links):
        again = network([task("A", DAY), task("B", DAY)], permuted)
        assert again == content
        assert content_bytes(again) == canonical
    # The engine runs it on v1 (no v2 feature) and computes.
    assert engine_version_for(content) == ENGINE_VERSION
    assert run_cpm(content).status is CpmStatus.COMPUTED


def test_two_relationships_of_one_type_on_a_pair_are_refused() -> None:
    content = network([task("A", DAY), task("B", DAY)], [link("A", "B"), link("A", "B", lag=60)])
    assert content_problem(content) == "at most 100000 relationships, one per ordered pair and type"


def test_relationships_sort_by_pred_succ_and_type() -> None:
    content = network(
        [task("A", DAY), task("B", DAY), task("C", DAY)],
        [link("B", "C"), link("A", "C", "SS"), link("A", "B", "SS"), link("A", "B", "FF")],
    )
    order = [(r.pred, r.succ, r.type.value) for r in content.relationships]
    assert order == [
        ("x:A", "x:B", "FF"),
        ("x:A", "x:B", "SS"),
        ("x:A", "x:C", "SS"),
        ("x:B", "x:C", "FS"),
    ]


def test_the_schema_label_must_be_the_one_the_content_implies() -> None:
    parallel = _ladder(("SS", 0), ("FF", 0))
    single = _ladder(("SS", 0))
    edged = network(
        [task("A", DAY), milestone("M", ActivityKind.FINISH_MILESTONE)],
        [link("A", "M", "SS"), link("A", "M", "FF")],
    )
    assert content_schema(edged) == CONTENT_SCHEMA_V3
    assert engine_version_for(edged) == ENGINE_VERSION_V2
    assert content_from_object(content_object(edged)) == edged
    for content, wrong in (
        (parallel, CONTENT_SCHEMA),
        (parallel, CONTENT_SCHEMA_V2),
        (edged, CONTENT_SCHEMA_V2),
        (single, CONTENT_SCHEMA_V3),
    ):
        document = content_object(content)
        document["schema"] = wrong
        with pytest.raises(ScenarioDecodeError):
            content_from_object(document)
    assert CONTENT_SCHEMAS == (CONTENT_SCHEMA, CONTENT_SCHEMA_V2, CONTENT_SCHEMA_V3)


def test_a_v3_reference_carries_the_v2_fields_key() -> None:
    # The v3 shape is the v2 shape: `fields` on every non-null published reference.
    content = network(
        [task("A", DAY), task("B", DAY)], [link("A", "B", "SS"), link("A", "B", "FF")]
    )
    referenced = replace(
        content,
        activities=tuple(
            replace(item, published_reference=_REFERENCE) for item in content.activities
        ),
    )
    document = content_object(referenced)
    activities = document["activities"]
    assert isinstance(activities, list)
    assert all(row["published_reference"]["fields"] is None for row in activities)
    assert content_from_object(document) == referenced


# ---- the engine ------------------------------------------------------------------------


def test_an_ss_ff_ladder_gives_the_hand_computed_dates_and_floats() -> None:
    # STD works Mon-Fri 08:00-16:00. A 2 days from Mon 01-04 08:00 to Tue 16:00. B 2
    # days: the SS + 1 day bound is Mon 16:00; the FF + 2 days bound is a finish at
    # Thu 16:00, so a start at Wed 08:00, which drives. Backward through the FF: Thu
    # 16:00 - 2 days = Wed 08:00, snapped back to Tue 16:00; through the SS: Wed 08:00
    # - 1 day = Tue 08:00, + 2 days = Wed 16:00. Both floats 0; the SS slack is 1 day.
    content = _ladder(("SS", DAY), ("FF", 2 * DAY))
    result = run_cpm(content)
    assert result.engine_version == ENGINE_VERSION
    rows = _by_key(content)
    a, b = rows["x:A"], rows["x:B"]
    assert (a.early_start, a.early_finish) == (at("01-04 08:00"), at("01-05 16:00"))
    assert (a.late_start, a.late_finish) == (at("01-04 08:00"), at("01-05 16:00"))
    assert (b.early_start, b.early_finish) == (at("01-06 08:00"), at("01-07 16:00"))
    assert (b.late_start, b.late_finish) == (at("01-06 08:00"), at("01-07 16:00"))
    assert (a.total_float_minutes, b.total_float_minutes) == (0, 0)
    assert (a.free_float_minutes, b.free_float_minutes) == (0, 0)
    links = {(r.pred, r.succ, r.type): r for r in result.relationships}
    assert len(links) == 2
    ss = links[("x:A", "x:B", RelationshipType.SS)]
    ff = links[("x:A", "x:B", RelationshipType.FF)]
    assert (ss.slack_minutes, ss.driving) == (DAY, False)
    assert (ff.slack_minutes, ff.driving) == (0, True)
    # The result document names each row by (pred, succ, type).
    document = result_document(result)
    assert document["relationships"] == [
        {
            "pred": "x:A",
            "succ": "x:B",
            "considered": True,
            "slack_minutes": 0,
            "driving": True,
            "type": "FF",
        },
        {
            "pred": "x:A",
            "succ": "x:B",
            "considered": True,
            "slack_minutes": DAY,
            "driving": False,
            "type": "SS",
        },
    ]
    assert result.critical_paths == (("x:A", "x:B"),)


def test_either_link_alone_gives_a_different_network() -> None:
    # Which link survived decided the dates before S7-7: the SS alone moves B a day early.
    ss_only = _by_key(_ladder(("SS", DAY)))["x:B"]
    both = _by_key(_ladder(("SS", DAY), ("FF", 2 * DAY)))["x:B"]
    assert ss_only.early_start == at("01-05 08:00")
    assert both.early_start == at("01-06 08:00")


def test_the_ladder_matches_a_zero_duration_connector_network() -> None:
    # The per-relationship maths is unchanged: the FF routed through a connector
    # milestone (A -FF 2d-> M -FF 0-> B) gives A and B exactly the ladder's numbers.
    ladder = _ladder(("SS", DAY), ("FF", 2 * DAY))
    connector = network(
        [task("A", 2 * DAY), task("B", 2 * DAY), milestone("M")],
        [link("A", "B", "SS", DAY), link("A", "M", "FF", 2 * DAY), link("M", "B", "FF")],
    )
    assert not has_parallel_relationships(connector)
    left, right = _by_key(ladder), _by_key(connector)
    for name in ("x:A", "x:B"):
        assert replace(left[name], topo_index=0) == replace(right[name], topo_index=0)


def test_input_order_of_parallel_links_changes_nothing() -> None:
    forward = _ladder(("SS", DAY), ("FF", 2 * DAY))
    backward = _ladder(("FF", 2 * DAY), ("SS", DAY))
    assert content_bytes(forward) == content_bytes(backward)
    assert result_document(run_cpm(forward)) == result_document(run_cpm(backward))


def test_two_driving_links_between_one_pair_are_one_critical_path_step() -> None:
    # SS 0 and FF 0 on equal durations: both links have slack 0. The critical path
    # is A -> B once, not twice.
    result = run_cpm(_ladder(("SS", 0), ("FF", 0)))
    assert [r.slack_minutes for r in result.relationships] == [0, 0]
    assert result.critical_paths == (("x:A", "x:B"),)
    assert result.summary.critical_path_count == 1


def test_every_parallel_relationship_counts_in_the_summary() -> None:
    result = run_cpm(_ladder(("SS", 0), ("FF", 0), ("FS", 0), ("SF", 0)))
    assert result.summary.relationship_count == 4
    assert len(result.relationships) == 4
    assert {r.type for r in result.relationships} == set(RelationshipType)


# ---- change sets -----------------------------------------------------------------------


def _applied(parent: ScenarioContent, ops: list[object]) -> ChangeSetApplied:
    outcome = apply_change_set(parent, ops)
    assert isinstance(outcome, ChangeSetApplied), outcome
    return outcome


def _refused(parent: ScenarioContent, ops: list[object]) -> ChangeOpError:
    outcome = apply_change_set(parent, ops)
    assert isinstance(outcome, ChangeSetRefusal), outcome
    return outcome.op_error


def _types(content: ScenarioContent) -> list[tuple[str, int]]:
    return [(r.type.value, r.lag_minutes) for r in content.relationships]


def test_an_add_on_an_occupied_pair_is_refused_unless_parallel() -> None:
    parent = _ladder(("SS", 0))
    add = {"op": "relationship.add", "pred": "x:A", "succ": "x:B", "type": "FF"}
    assert _refused(parent, [add]) is E.RELATIONSHIP_EXISTS
    assert _refused(parent, [{**add, "parallel": False}]) is E.RELATIONSHIP_EXISTS
    assert _refused(parent, [{**add, "parallel": "yes"}]) is E.INVALID_FIELD
    child = _applied(parent, [{**add, "parallel": True, "lag_minutes": 60}]).content
    assert _types(child) == [("FF", 60), ("SS", 0)]
    assert content_schema(child) == CONTENT_SCHEMA_V3
    # The same type on the pair is refused even when parallel.
    same = {**add, "type": "SS", "parallel": True}
    assert _refused(parent, [same]) is E.RELATIONSHIP_EXISTS
    # A parallel add on an empty pair is an ordinary add.
    empty = network([task("A", DAY), task("B", DAY)])
    assert _types(_applied(empty, [{**add, "parallel": True}]).content) == [("FF", 0)]


def test_an_edit_on_a_single_pair_is_unchanged() -> None:
    parent = _ladder(("SS", 0))
    edit = {"op": "relationship.edit", "pred": "x:A", "succ": "x:B", "type": "FF"}
    assert _types(_applied(parent, [edit]).content) == [("FF", 0)]
    lag = {"op": "relationship.edit", "pred": "x:A", "succ": "x:B", "lag_minutes": 30}
    assert _types(_applied(parent, [lag]).content) == [("SS", 30)]


def test_an_edit_on_a_parallel_pair_names_the_relationship_by_type() -> None:
    parent = _ladder(("SS", 0), ("FF", 0))
    base = {"op": "relationship.edit", "pred": "x:A", "succ": "x:B"}
    assert _refused(parent, [{**base, "lag_minutes": 30}]) is E.INVALID_FIELD
    assert _refused(parent, [{**base, "type": "FF"}]) is E.INVALID_FIELD
    assert _refused(parent, [{**base, "type": "FS", "lag_minutes": 30}]) is E.RELATIONSHIP_ABSENT
    child = _applied(parent, [{**base, "type": "FF", "lag_minutes": 30}]).content
    assert _types(child) == [("FF", 30), ("SS", 0)]


def test_a_remove_on_a_parallel_pair_needs_a_type_and_removes_one() -> None:
    parent = _ladder(("SS", 0), ("FF", 0))
    remove = {"op": "relationship.remove", "pred": "x:A", "succ": "x:B"}
    assert _refused(parent, [remove]) is E.INVALID_FIELD
    assert _refused(parent, [{**remove, "type": "FS"}]) is E.RELATIONSHIP_ABSENT
    assert _refused(parent, [{**remove, "type": "XX"}]) is E.INVALID_FIELD
    applied = _applied(parent, [{**remove, "type": "SS"}])
    assert _types(applied.content) == [("FF", 0)]
    assert content_schema(applied.content) == CONTENT_SCHEMA
    # On a single pair the type is optional and, when given, must match.
    single = applied.content
    assert _refused(single, [{**remove, "type": "SS"}]) is E.RELATIONSHIP_ABSENT
    assert _types(_applied(single, [remove]).content) == []
    assert _types(_applied(single, [{**remove, "type": "FF"}]).content) == []


def test_removing_an_activity_counts_every_parallel_relationship() -> None:
    parent = _ladder(("SS", 0), ("FF", 0))
    applied = _applied(parent, [{"op": "activity.remove", "key": "x:B"}])
    assert applied.content.relationships == ()
    assert applied.report.relationships_removed == 2


def test_the_relationship_cap_counts_relationships_not_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cap stays 100,000 relationships; parallel ones each count (shown at a cap of 2).
    monkeypatch.setattr(changeset_module, "MAX_RELATIONSHIPS", 2)
    monkeypatch.setattr(model_module, "MAX_RELATIONSHIPS", 2)
    parent = network(
        [task("A", DAY), task("B", DAY), task("C", DAY)],
        [link("A", "B", "SS"), link("A", "B", "FF")],
    )
    add = {"op": "relationship.add", "pred": "x:B", "succ": "x:C", "type": "FS"}
    assert _refused(parent, [add]) is E.BOUND_EXCEEDED
    three = network(
        [task("A", DAY), task("B", DAY)],
        [link("A", "B", "SS"), link("A", "B", "FF"), link("A", "B")],
    )
    assert content_problem(three) == "at most 100000 relationships, one per ordered pair and type"
