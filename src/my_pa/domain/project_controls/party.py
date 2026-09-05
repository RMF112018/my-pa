"""Constraint party references: who a Constraint is waiting on, and who owns it.

A `ProjectConstraint` carries two ordered party collections, BIC ("ball in
court") and Responsible. Each member is a `PartyRef`, which names a party in
exactly one of three ways and never by string matching:

- `PRINCIPAL` means the authenticated owning Principal directly. It carries no
  identity of its own: the Principal is already the record's partition, and
  putting a raw `prn_` value inside a party reference would make it browser
  data the freeze forbids. No Entity identity is fabricated for the Principal.
- `ENTITY` references a stable `ent_...` identity in the same Principal
  partition. `label` is a presentation snapshot only; authority is the id.
- `UNRESOLVED` preserves meaningful source wording (a legacy workbook cell,
  a typed name) that no Entity has been resolved for. It has no canonical
  identity, and it never establishes In My Court, however closely its wording
  resembles somebody's name.

This module is a leaf: the In My Court rule that consumes these references
lives beside the lifecycle vocabulary in `constraint.py`, because it needs the
active-state set and this module must not import it back.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "PartyKind",
    "PartyRef",
    "PartyRefError",
]


class PartyRefError(ValueError):
    """A party reference was not well-formed for its kind. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PartyKind(StrEnum):
    """The three ways a Constraint party can be named. Exactly three."""

    PRINCIPAL = "principal"
    ENTITY = "entity"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class PartyRef:
    """One member of a BIC or Responsible collection.

    `entity_id` is required exactly when `kind` is `ENTITY` and forbidden
    otherwise. `label` is required and non-blank for `UNRESOLVED` (it *is* the
    preserved source wording), optional presentation text for `ENTITY`, and
    forbidden for `PRINCIPAL`, which has nothing to display that is not already
    the Principal's own authority.
    """

    kind: PartyKind
    entity_id: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if self.kind is PartyKind.ENTITY:
            if self.entity_id is None:
                raise PartyRefError(
                    "party_entity_id_required", "an ENTITY party names an ent_ identity"
                )
            validate_identifier(self.entity_id, IdKind.ENTITY)
        elif self.entity_id is not None:
            raise PartyRefError(
                "party_entity_id_forbidden",
                f"a {self.kind.value.upper()} party carries no entity identity",
            )
        if self.kind is PartyKind.UNRESOLVED:
            if self.label is None or not self.label.strip():
                raise PartyRefError(
                    "party_label_required", "an UNRESOLVED party preserves non-blank source wording"
                )
        elif self.kind is PartyKind.PRINCIPAL and self.label is not None:
            raise PartyRefError(
                "party_label_forbidden", "a PRINCIPAL party carries no label of its own"
            )
        if self.label is not None and not self.label.strip():
            raise PartyRefError("party_label_blank", "a party label, when present, is non-blank")
