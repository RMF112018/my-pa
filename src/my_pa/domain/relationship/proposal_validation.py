"""Canonical value semantics for typed Entity proposal targets."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.authoring import (
    CALLER_SETTABLE_STATUSES,
    MAX_ENTITY_NAME_CHARACTERS,
    MAX_IDENTIFIER_VALUE_CHARACTERS,
    CallerNamespace,
)
from my_pa.domain.relationship.entity import (
    MAX_DIRECTED_TEXT_CHARACTERS,
    AliasType,
    AssignmentType,
    EntityRelationshipType,
    EntityType,
)

__all__ = ["ResolutionDisposition", "validate_proposal_target"]


class ResolutionDisposition(StrEnum):
    LINK_EXISTING = "link_existing"
    CREATE_NEW = "create_new"
    REJECT = "reject"
    DEFER = "defer"
    QUARANTINE = "quarantine"


_IDS: Final = {
    "entity_id": IdKind.ENTITY,
    "retained_entity_id": IdKind.ENTITY,
    "merged_entity_id": IdKind.ENTITY,
    "from_entity_id": IdKind.ENTITY,
    "to_entity_id": IdKind.ENTITY,
    "scope_entity_id": IdKind.ENTITY,
    "rejected_entity_id": IdKind.ENTITY,
    "identifier_id": IdKind.EXTERNAL_IDENTIFIER,
    "alias_id": IdKind.ENTITY_ALIAS,
    "assignment_id": IdKind.ASSIGNMENT,
    "relationship_id": IdKind.ENTITY_RELATIONSHIP,
    "observation_id": IdKind.ENTITY_OBSERVATION,
    # WP-06 / RI-P4-HIGH-001. `split_identity` names the completed governed merge
    # it reverses, and `PreviewEntitySplit` validates that value against
    # `ENTITY_IDENTITY_OPERATION`. Checked here so the proposal refuses a subject
    # the preview would refuse, rather than storing reviewed intent that cannot
    # survive the one command it exists to reach.
    "source_identity_operation_id": IdKind.ENTITY_IDENTITY_OPERATION,
}


def _text(values: Mapping[str, str | bool], name: str) -> str | None:
    value = values.get(name)
    return value if isinstance(value, str) else None


def _member(values: Mapping[str, str | bool], name: str, vocabulary: type[StrEnum]) -> None:
    value = _text(values, name)
    if value is not None and value not in {member.value for member in vocabulary}:
        raise ValueError(f"a payload names a known {name}")


def _bounded(values: Mapping[str, str | bool], names: tuple[str, ...], maximum: int) -> None:
    for name in names:
        value = _text(values, name)
        if value is not None and len(value.strip()) > maximum:
            raise ValueError(f"a payload's {name} is bounded")


def _moment(values: Mapping[str, str | bool], name: str) -> datetime | None:
    value = _text(values, name)
    if value is None:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"a payload's {name} is an aware ISO-8601 moment") from exc


def validate_proposal_target(kind: str, values: Mapping[str, str | bool]) -> None:
    """Validate the canonical values and cross-field rules for one proposal kind."""
    for name, id_kind in _IDS.items():
        value = _text(values, name)
        if value is not None:
            try:
                validate_identifier(value, id_kind)
            except ValueError as exc:
                raise ValueError(f"a payload names a valid {name}") from exc

    _bounded(values, ("display_name", "canonical_name"), MAX_ENTITY_NAME_CHARACTERS)
    display_limit = (
        MAX_IDENTIFIER_VALUE_CHARACTERS
        if kind in {"bind_identifier", "supersede_identifier"}
        else MAX_ENTITY_NAME_CHARACTERS
    )
    _bounded(values, ("display_value",), display_limit)
    _bounded(
        values,
        ("role", "discipline", "responsibility_class"),
        MAX_DIRECTED_TEXT_CHARACTERS,
    )
    _member(values, "entity_type", EntityType)
    _member(values, "namespace", CallerNamespace)
    _member(values, "alias_type", AliasType)
    _member(values, "assignment_type", AssignmentType)
    _member(values, "relationship_type", EntityRelationshipType)
    _member(values, "disposition", ResolutionDisposition)

    start, end = _moment(values, "effective_from"), _moment(values, "effective_to")
    if start is not None and end is not None and end < start:
        raise ValueError("a payload's effective window is ordered")
    if kind in {"end_assignment", "end_relationship"}:
        effective_end = _moment(values, "effective_end")
        end_now = values.get("end_now", False)
        if not isinstance(end_now, bool) or (effective_end is None) is not end_now:
            raise ValueError("an end payload names exactly one end moment")
    if kind == "update_entity" and not {"display_name", "canonical_name", "status"} & values.keys():
        raise ValueError("an update payload changes at least one field")
    if kind in {"revise_assignment", "revise_relationship"} and len(values) == 1:
        raise ValueError("a revise payload changes at least one field")
    if kind == "record_relationship" and values["from_entity_id"] == values["to_entity_id"]:
        raise ValueError("a relationship's endpoints are distinct")
    if kind == "merge_entities" and values["retained_entity_id"] == values["merged_entity_id"]:
        raise ValueError("a merge's entities are distinct")
    if kind == "update_entity" and "status" in values:
        proposable_statuses = {status.value for status in CALLER_SETTABLE_STATUSES}
        if values["status"] not in proposable_statuses:
            raise ValueError("a payload proposes a status a caller may ask for")
    if kind == "resolve_mention":
        disposition = str(values["disposition"])
        allowed = {
            "link_existing": {"observation_id", "disposition", "entity_id", "reason"},
            "create_new": {
                "observation_id",
                "disposition",
                "entity_type",
                "canonical_name",
                "display_name",
                "reason",
            },
            "reject": {"observation_id", "disposition", "rejected_entity_id", "reason"},
            "defer": {"observation_id", "disposition", "reason"},
            "quarantine": {"observation_id", "disposition", "reason"},
        }
        required = {
            "link_existing": {"entity_id"},
            "create_new": {"entity_type", "canonical_name"},
            "reject": {"reason"},
            "defer": {"reason"},
            "quarantine": {"reason"},
        }
        if not set(values) <= allowed[disposition] or not required[disposition] <= set(values):
            raise ValueError("a resolution payload matches its disposition")
