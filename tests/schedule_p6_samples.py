"""Synthetic sample payloads for the 7 P6 XER capabilities (S7-4a).

The transport-parity, negative-evidence and policy suites keep one valid
payload per handler-backed capability. Every id, path and digest here is
synthetic; each payload passes its command's own strict-input validation
(schedule XER import contract section 10.3), so a transport reaches
authorization and the P6 switch's composition check (off in those worlds).
"""

from __future__ import annotations

from typing import Any, Final

from my_pa.application.commands import (
    ImportScheduleP6Publication,
    ListScheduleP6Activities,
    ListScheduleP6AvailableFields,
    ListScheduleP6Calendars,
    ListScheduleP6FieldValues,
    ListScheduleP6Relationships,
    SetScheduleP6CapturedFields,
)
from my_pa.domain.identity.operation import Capability

__all__ = ["SCHEDULE_P6_CAPABILITIES", "schedule_p6_commands", "schedule_p6_payloads"]

#: The 7 P6 names, each withheld unless the P6 switch is on over the Schedule plane.
SCHEDULE_P6_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6,
        Capability.SCHEDULE_P6_FIELDS_AVAILABLE,
        Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED,
        Capability.SCHEDULE_P6_ACTIVITIES_LIST,
        Capability.SCHEDULE_P6_RELATIONSHIPS_LIST,
        Capability.SCHEDULE_P6_CALENDARS_LIST,
        Capability.SCHEDULE_P6_FIELD_VALUES_LIST,
    }
)


def schedule_p6_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload per P6 name; `tag` (lowercase alphanumeric) marks the suite."""
    series = f"sser_{tag}p6series01"
    publication = f"spub_{tag}p6publi01"
    return {
        Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6: {
            "project_id": f"prj_{tag}p6project1",
            "series_name": "Synthetic P6 Series",
            "workspace_id": "syn",
            "path": "exports/synthetic.xer",
            "expected_version": "fv1_" + "a" * 64,
            "expected_sha256": "b" * 64,
            "format": "p6_xer",
            "idempotency_key": f"p6-{tag}-import-0001",
        },
        Capability.SCHEDULE_P6_FIELDS_AVAILABLE: {"series_id": series},
        Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED: {
            "series_id": series,
            "field_keys": ["xer:TASK.est_wt"],
            "expected_sequence": 0,
            "idempotency_key": f"p6-{tag}-select-0001",
        },
        Capability.SCHEDULE_P6_ACTIVITIES_LIST: {"publication_id": publication},
        Capability.SCHEDULE_P6_RELATIONSHIPS_LIST: {"publication_id": publication},
        Capability.SCHEDULE_P6_CALENDARS_LIST: {"publication_id": publication},
        Capability.SCHEDULE_P6_FIELD_VALUES_LIST: {"publication_id": publication},
    }


def schedule_p6_commands(tag: str) -> dict[Capability, Any]:
    """The same samples as built commands."""
    payloads = schedule_p6_payloads(tag)
    selection = dict(payloads[Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED])
    selection["field_keys"] = tuple(selection["field_keys"])
    return {
        Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6: ImportScheduleP6Publication(
            **payloads[Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6]
        ),
        Capability.SCHEDULE_P6_FIELDS_AVAILABLE: ListScheduleP6AvailableFields(
            **payloads[Capability.SCHEDULE_P6_FIELDS_AVAILABLE]
        ),
        Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED: SetScheduleP6CapturedFields(**selection),
        Capability.SCHEDULE_P6_ACTIVITIES_LIST: ListScheduleP6Activities(
            **payloads[Capability.SCHEDULE_P6_ACTIVITIES_LIST]
        ),
        Capability.SCHEDULE_P6_RELATIONSHIPS_LIST: ListScheduleP6Relationships(
            **payloads[Capability.SCHEDULE_P6_RELATIONSHIPS_LIST]
        ),
        Capability.SCHEDULE_P6_CALENDARS_LIST: ListScheduleP6Calendars(
            **payloads[Capability.SCHEDULE_P6_CALENDARS_LIST]
        ),
        Capability.SCHEDULE_P6_FIELD_VALUES_LIST: ListScheduleP6FieldValues(
            **payloads[Capability.SCHEDULE_P6_FIELD_VALUES_LIST]
        ),
    }
