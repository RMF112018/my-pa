"""RECR-1: the routing table, and that every family is rereadable by a key it carries.

FAST. `domain.record_events.RECORD_EVENT_ROUTING` names, for each family whose
`record_id` no mapped read accepts as a key, the kind of record a consumer
rereads it through; the feed reader fills `routing_record_id` from the child
row's owner column (`infrastructure.persistence.record_events`, MR-R01).

* **RECR-AC-001** -- the table is the twelve rows written out: `task_comment` to
  `task`, `constraint_category` to `project`, and the ten Entity floor
  families to `entity`; its complement is the ten direct families. The reader's
  owner columns cover exactly those rows, and an affiliation routes to its
  **person** end (MR-R05 (i), RECR-AC-021).
* **RECR-AC-002** -- for every routed family, the routing kind is the lookup key
  of one of that family's mapped reads, shown by the read command's dataclass
  field; for every direct family, a mapped read takes `record_id`'s kind.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Final

from my_pa.application import commands
from my_pa.domain.identity.operation import Capability
from my_pa.domain.record_events import (
    ENTITY_FLOOR_FAMILIES,
    RECORD_EVENT_FAMILY_READS,
    RECORD_EVENT_ROUTING,
    RecordEventFamily,
)
from my_pa.infrastructure.persistence import record_events as feed_persistence

F = RecordEventFamily

#: The routed families' reread: (a mapped read, its key field, the routing kind).
ROUTED_KEYS: Final = {
    F.TASK_COMMENT: (Capability.TASKS_COMMENTS_LIST, "task_id", F.TASK),
    F.CONSTRAINT_CATEGORY: (Capability.CONSTRAINT_CATEGORIES_LIST, "project_id", F.PROJECT),
    F.ENTITY_IDENTIFIER: (Capability.ENTITIES_IDENTIFIERS_LIST, "entity_id", F.ENTITY),
    F.ENTITY_ALIAS: (Capability.ENTITIES_ALIASES_LIST, "entity_id", F.ENTITY),
    F.ENTITY_ASSIGNMENT: (Capability.ENTITIES_ASSIGNMENTS_LIST, "entity_id", F.ENTITY),
    F.ENTITY_RELATIONSHIP: (Capability.ENTITIES_RELATIONSHIPS, "entity_id", F.ENTITY),
    F.ENTITY_OBSERVATION: (Capability.ENTITIES_OBSERVATIONS_LIST, "entity_id", F.ENTITY),
    F.ENTITY_NAME: (Capability.ENTITIES_NAMES_LIST, "entity_id", F.ENTITY),
    F.ENTITY_ADDRESS: (Capability.ENTITIES_ADDRESSES_LIST, "entity_id", F.ENTITY),
    F.ENTITY_COMMUNICATION_METHOD: (Capability.ENTITIES_COMMUNICATION_LIST, "entity_id", F.ENTITY),
    F.ENTITY_PROJECT_PARTICIPATION: (
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        "entity_id",
        F.ENTITY,
    ),
    F.PERSON_ORGANIZATION_AFFILIATION: (Capability.ENTITIES_PROFILE, "entity_id", F.ENTITY),
}

#: The direct families' reread: (a mapped read, the field that takes `record_id`).
DIRECT_KEYS: Final = {
    F.TASK: (Capability.TASKS_READ, "task_id"),
    F.COMMITMENT: (Capability.COMMITMENTS_READ, "commitment_id"),
    F.PROJECT: (Capability.CONTINUITY_PROJECTS_READ, "project_id"),
    F.ENTITY: (Capability.ENTITIES_GET, "entity_id"),
    F.RELATIONSHIP_MEMORY: (Capability.RELATIONSHIP_MEMORY_GET, "memory_id"),
    F.CONSTRAINT: (Capability.CONSTRAINTS_READ, "constraint_id"),
    # The settings emitter sets `record_id` to the Project.
    F.PROJECT_CONTROLS_SETTINGS: (Capability.PROJECT_CONTROLS_STATUS, "project_id"),
    F.MEETING: (Capability.MEETINGS_READ, "meeting_id"),
    F.MEETING_SERIES: (Capability.MEETINGS_LIST, "meeting_series_id"),
    F.CAPTURE: (Capability.CAPTURE_READ, "capture_id"),
    # KLP-WP-03: an event's `record_id` is the `kasr_` assertion itself.
    F.KNOWLEDGE_ASSERTION: (Capability.KNOWLEDGE_ASSERTIONS_READ, "assertion_id"),
}


def _command_fields(capability: Capability) -> set[str]:
    """The dataclass fields of the one request command for `capability`."""
    found = [
        cls
        for _, cls in inspect.getmembers(commands, inspect.isclass)
        if dataclasses.is_dataclass(cls) and cls.__dict__.get("capability") is capability
    ]
    assert len(found) == 1, (capability, [cls.__name__ for cls in found])
    return {field.name for field in dataclasses.fields(found[0])}


# ---- RECR-AC-001 -------------------------------------------------------------------


def test_the_routing_table_is_the_twelve_rows_written_out() -> None:
    assert dict(RECORD_EVENT_ROUTING) == {
        F.TASK_COMMENT: F.TASK,
        F.CONSTRAINT_CATEGORY: F.PROJECT,
        F.ENTITY_IDENTIFIER: F.ENTITY,
        F.ENTITY_ALIAS: F.ENTITY,
        F.ENTITY_ASSIGNMENT: F.ENTITY,
        F.ENTITY_RELATIONSHIP: F.ENTITY,
        F.ENTITY_OBSERVATION: F.ENTITY,
        F.ENTITY_NAME: F.ENTITY,
        F.ENTITY_ADDRESS: F.ENTITY,
        F.ENTITY_COMMUNICATION_METHOD: F.ENTITY,
        F.ENTITY_PROJECT_PARTICIPATION: F.ENTITY,
        F.PERSON_ORGANIZATION_AFFILIATION: F.ENTITY,
    }
    assert set(RECORD_EVENT_ROUTING) == ENTITY_FLOOR_FAMILIES | {
        F.TASK_COMMENT,
        F.CONSTRAINT_CATEGORY,
    }
    direct = set(F) - set(RECORD_EVENT_ROUTING)
    assert direct == set(DIRECT_KEYS)
    assert len(direct) == 11


def test_the_reader_reads_one_owner_column_per_routed_family() -> None:
    owners = {family: owner for family, _, owner in feed_persistence._ROUTING_OWNERS}
    assert len(owners) == len(feed_persistence._ROUTING_OWNERS)
    assert set(owners) == set(RECORD_EVENT_ROUTING)
    # MR-R05 (i), RECR-AC-021: an affiliation routes to its person end.
    affiliation = owners[F.PERSON_ORGANIZATION_AFFILIATION]
    assert affiliation.name == "person_entity_id"
    assert affiliation.table.name == "entity_person_organization_affiliations"
    # The documented reread directions (plan b.1).
    assert owners[F.ENTITY_RELATIONSHIP].name == "from_entity_id"
    assert owners[F.ENTITY_PROJECT_PARTICIPATION].name == "participant_entity_id"
    assert owners[F.TASK_COMMENT].name == "task_id"
    assert owners[F.CONSTRAINT_CATEGORY].name == "project_id"


# ---- RECR-AC-002 -------------------------------------------------------------------


def test_every_family_has_a_read_keyed_by_its_record_or_routing_id() -> None:
    assert set(ROUTED_KEYS) | set(DIRECT_KEYS) == set(F)
    for family, (capability, field, kind) in ROUTED_KEYS.items():
        assert RECORD_EVENT_ROUTING[family] is kind, family
        assert capability in RECORD_EVENT_FAMILY_READS[family], family
        assert field in _command_fields(capability), (family, capability, field)
    for family, (capability, field) in DIRECT_KEYS.items():
        assert capability in RECORD_EVENT_FAMILY_READS[family], family
        assert field in _command_fields(capability), (family, capability, field)
