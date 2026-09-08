"""The write record for one explicit typed edge between two Constraints.

PC-CM-IMP-WP06. `knowledge.project_constraint_relationships` has had a read
projection since WP03 (`read_models.ConstraintRelationshipRow`) and no writer at
all. Close + Follow-up is the one accepted operation that creates an edge — the
successor is `FOLLOW_UP_OF` the predecessor — so this module exists to give that
one write a domain shape, and deliberately nothing more.

**Why here and not in `read_models.py`.** That module is the read plane's
canonical shape vocabulary, guarded as such by
`tests/architecture/test_constraint_read_plane_boundaries.py`; a write record
whose fields include `principal_id` does not belong in a file whose rule is that
no view carries the partition key. This is the write half, in its own module,
beside `revision.py` and `history.py` which are write halves too.

**Direction is a fact, not a convention.** `source_constraint_id`
`FOLLOW_UP_OF` `target_constraint_id` reads left to right: the successor is the
source and the predecessor is the target. Getting that backwards would invert
every follow-up chain a reader is shown, so it is stated once, here, and
asserted by the tests rather than remembered at each call site.

`created_by_history_id` is not decoration: an edge that no receipt accounts for
is an edge nobody can say who made, and the stored table requires it. There is
no mutator and no delete: v1 has no relationship editing surface, and dispatch
§9.16 forbids a general relationship authoring API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "ConstraintRelationship",
    "ConstraintRelationshipError",
    "ConstraintRelationshipType",
]


class ConstraintRelationshipError(ValueError):
    """A relationship record violated a structural invariant. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintRelationshipType(StrEnum):
    """The v1 relationship vocabulary. One member, restated by the stored CHECK."""

    FOLLOW_UP_OF = "follow_up_of"


@dataclass(frozen=True, slots=True)
class ConstraintRelationship:
    """One row of `knowledge.project_constraint_relationships`, as written.

    Both ends are in the same Principal partition and the same Project by
    construction — the stored composite foreign keys say so too — and a
    Constraint never relates to itself.
    """

    relationship_id: str
    principal_id: str
    project_id: str
    source_constraint_id: str
    target_constraint_id: str
    relationship_type: ConstraintRelationshipType
    created_by_history_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.relationship_id, IdKind.PROJECT_CONSTRAINT_RELATIONSHIP)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        validate_identifier(self.source_constraint_id, IdKind.PROJECT_CONSTRAINT)
        validate_identifier(self.target_constraint_id, IdKind.PROJECT_CONSTRAINT)
        validate_identifier(self.created_by_history_id, IdKind.PROJECT_CONSTRAINT_HISTORY)
        if not isinstance(self.relationship_type, ConstraintRelationshipType):
            raise ConstraintRelationshipError(
                "constraint_relationship_type_unknown",
                "a constraint relationship names one known relationship type",
            )
        if self.source_constraint_id == self.target_constraint_id:
            raise ConstraintRelationshipError(
                "constraint_relationship_is_reflexive",
                "a constraint does not relate to itself",
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
