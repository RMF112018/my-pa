"""WP-RE-06: the family -> read mapping is explicit, exhaustive and literal (P2c section 2.4).

FAST. `RECORD_EVENT_FAMILY_READS` decides which grant discloses which family,
so every property that keeps it from widening a grant is pinned here:

* exactly the twenty-two `RecordEventFamily` members, each with a non-empty set;
* the literal plan table (section 6.1), so a change is a reviewed decision;
* every mapped read is a read (never a write), never operator-only, and has
  exactly one permitted purpose -- the one the plan names for the family;
* the OD-10 entity floor: `entities.get`, ANDed onto rows 5-14;
* no mapping is derived from a capability name prefix (AST guard).

Nothing here touches a database.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    ENTITY_FLOOR_CAPABILITY,
    ENTITY_FLOOR_FAMILIES,
    RECORD_EVENT_FAMILY_READS,
    RecordEventFamily,
)

ROOT: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"

F = RecordEventFamily
C = Capability

#: Plan section 6.1, row by row: the mapped reads and the one purpose.
EXPECTED: Final[dict[RecordEventFamily, tuple[frozenset[Capability], Purpose]]] = {
    F.TASK: (frozenset({C.TASKS_READ, C.TASKS_LIST}), Purpose.TASK_READ),
    F.COMMITMENT: (frozenset({C.COMMITMENTS_READ, C.COMMITMENTS_LIST}), Purpose.COMMITMENT_READ),
    F.PROJECT: (
        frozenset({C.CONTINUITY_PROJECTS_READ, C.CONTINUITY_PROJECTS}),
        Purpose.CAPTURE_REVIEW,
    ),
    F.ENTITY: (frozenset({C.ENTITIES_GET}), Purpose.ENTITY_READ),
    F.ENTITY_IDENTIFIER: (frozenset({C.ENTITIES_IDENTIFIERS_LIST}), Purpose.ENTITY_READ),
    F.ENTITY_ALIAS: (frozenset({C.ENTITIES_ALIASES_LIST}), Purpose.ENTITY_READ),
    F.ENTITY_ASSIGNMENT: (frozenset({C.ENTITIES_ASSIGNMENTS_LIST}), Purpose.ENTITY_READ),
    F.ENTITY_RELATIONSHIP: (frozenset({C.ENTITIES_RELATIONSHIPS}), Purpose.ENTITY_READ),
    F.ENTITY_OBSERVATION: (frozenset({C.ENTITIES_OBSERVATIONS_LIST}), Purpose.ENTITY_READ),
    F.ENTITY_NAME: (frozenset({C.ENTITIES_NAMES_LIST, C.ENTITIES_PROFILE}), Purpose.ENTITY_READ),
    F.ENTITY_ADDRESS: (
        frozenset({C.ENTITIES_ADDRESSES_LIST, C.ENTITIES_PROFILE}),
        Purpose.ENTITY_READ,
    ),
    F.ENTITY_COMMUNICATION_METHOD: (
        frozenset({C.ENTITIES_COMMUNICATION_LIST, C.ENTITIES_PROFILE}),
        Purpose.ENTITY_READ,
    ),
    F.ENTITY_PROJECT_PARTICIPATION: (
        frozenset({C.ENTITIES_PARTICIPATIONS_LIST, C.ENTITIES_PROFILE}),
        Purpose.ENTITY_READ,
    ),
    F.PERSON_ORGANIZATION_AFFILIATION: (frozenset({C.ENTITIES_PROFILE}), Purpose.ENTITY_READ),
    F.RELATIONSHIP_MEMORY: (
        frozenset({C.RELATIONSHIP_MEMORY_GET, C.RELATIONSHIP_MEMORY_LIST}),
        Purpose.RELATIONSHIP_MEMORY_READ,
    ),
    F.CONSTRAINT: (frozenset({C.CONSTRAINTS_READ, C.CONSTRAINTS_LIST}), Purpose.CONSTRAINT_READ),
    F.CONSTRAINT_CATEGORY: (frozenset({C.CONSTRAINT_CATEGORIES_LIST}), Purpose.CONSTRAINT_READ),
    F.PROJECT_CONTROLS_SETTINGS: (
        frozenset({C.PROJECT_CONTROLS_STATUS}),
        Purpose.CONSTRAINT_READ,
    ),
    F.MEETING: (frozenset({C.MEETINGS_READ, C.MEETINGS_LIST}), Purpose.MEETING_READ),
    F.MEETING_SERIES: (frozenset({C.MEETINGS_READ, C.MEETINGS_LIST}), Purpose.MEETING_READ),
    # WP-RE-08 (Amendment 01; OD-W8-1 (i) no floor, OD-W8-11 both capture reads).
    F.CAPTURE: (frozenset({C.CAPTURE_READ, C.CAPTURE_LIST}), Purpose.CAPTURE_REVIEW),
    F.TASK_COMMENT: (frozenset({C.TASKS_COMMENTS_LIST}), Purpose.TASK_READ),
}


def test_the_table_covers_exactly_the_twenty_two_families() -> None:
    assert set(RECORD_EVENT_FAMILY_READS) == set(RecordEventFamily)
    assert len(RECORD_EVENT_FAMILY_READS) == 22
    assert all(RECORD_EVENT_FAMILY_READS.values())


def test_the_table_is_the_plan_table_literally() -> None:
    assert {family: reads for family, (reads, _) in EXPECTED.items()} == dict(
        RECORD_EVENT_FAMILY_READS
    )


@pytest.mark.parametrize("family", list(RecordEventFamily), ids=lambda family: family.value)
def test_every_mapped_read_is_a_single_purpose_non_operator_read(
    family: RecordEventFamily,
) -> None:
    _, purpose = EXPECTED[family]
    for capability in RECORD_EVENT_FAMILY_READS[family]:
        assert not is_write_capability(capability), capability
        assert not is_operator_only(capability), capability
        assert permitted_purposes(capability) == frozenset({purpose}), capability


def test_the_entity_floor_is_entities_get_on_rows_five_to_fourteen() -> None:
    assert ENTITY_FLOOR_CAPABILITY is Capability.ENTITIES_GET
    assert RECORD_EVENT_FAMILY_READS[F.ENTITY] == frozenset({Capability.ENTITIES_GET})
    assert frozenset(ENTITY_FLOOR_FAMILIES) == {
        F.ENTITY_IDENTIFIER,
        F.ENTITY_ALIAS,
        F.ENTITY_ASSIGNMENT,
        F.ENTITY_RELATIONSHIP,
        F.ENTITY_OBSERVATION,
        F.ENTITY_NAME,
        F.ENTITY_ADDRESS,
        F.ENTITY_COMMUNICATION_METHOD,
        F.ENTITY_PROJECT_PARTICIPATION,
        F.PERSON_ORGANIZATION_AFFILIATION,
    }
    # The floor never stands in for a family's own read.
    for family in ENTITY_FLOOR_FAMILIES:
        assert ENTITY_FLOOR_CAPABILITY not in RECORD_EVENT_FAMILY_READS[family]


_PREFIX_CALLS: Final = frozenset({"startswith", "removeprefix", "partition", "split"})


@pytest.mark.parametrize(
    "relative", ["domain/record_events.py", "application/record_events.py"], ids=str
)
def test_no_mapping_is_derived_from_a_name_prefix(relative: str) -> None:
    tree = ast.parse((ROOT / relative).read_text())
    offending = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _PREFIX_CALLS
    ]
    assert offending == []
