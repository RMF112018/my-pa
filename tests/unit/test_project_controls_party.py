"""Unit tests for the PC-CM-IMP-WP01 party-reference vocabulary."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ProjectConstraint,
    in_my_court,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef, PartyRefError

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
ENTITY_A = "ent_aaaa0001aaaa0001aaaa"
ENTITY_B = "ent_bbbb0002bbbb0002bbbb"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_party_kinds_are_exactly_three() -> None:
    assert {k.value for k in PartyKind} == {"principal", "entity", "unresolved"}


def test_principal_party_carries_no_identity_and_no_label() -> None:
    party = PartyRef(PartyKind.PRINCIPAL)
    assert party.entity_id is None
    assert party.label is None
    assert not any("prn_" in str(v) for v in dataclasses.astuple(party) if v is not None)
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.PRINCIPAL, entity_id=ENTITY_A)
    assert excinfo.value.code == "party_entity_id_forbidden"
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.PRINCIPAL, label="Me")
    assert excinfo.value.code == "party_label_forbidden"


def test_entity_party_requires_an_ent_identity() -> None:
    party = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A, label="Acme")
    assert party.entity_id == ENTITY_A
    assert PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A).label is None
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.ENTITY)
    assert excinfo.value.code == "party_entity_id_required"
    with pytest.raises(InvalidIdentifierError):
        PartyRef(PartyKind.ENTITY, entity_id=PRINCIPAL_ID)
    with pytest.raises(InvalidIdentifierError):
        PartyRef(PartyKind.ENTITY, entity_id="Acme Corp")


def test_unresolved_party_keeps_wording_and_rejects_identity() -> None:
    party = PartyRef(PartyKind.UNRESOLVED, label="J. Smith (Acme)")
    assert party.label == "J. Smith (Acme)"
    assert party.entity_id is None
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.UNRESOLVED, entity_id=ENTITY_A, label="x")
    assert excinfo.value.code == "party_entity_id_forbidden"
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.UNRESOLVED)
    assert excinfo.value.code == "party_label_required"
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.UNRESOLVED, label="   ")
    assert excinfo.value.code == "party_label_required"


def test_entity_label_when_present_is_nonblank() -> None:
    with pytest.raises(PartyRefError) as excinfo:
        PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A, label=" ")
    assert excinfo.value.code == "party_label_blank"


def test_party_refs_are_frozen_values() -> None:
    party = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A)
    with pytest.raises(dataclasses.FrozenInstanceError):
        party.entity_id = ENTITY_B  # type: ignore[misc]
    assert party == PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A)


def test_bic_and_responsible_are_distinct_ordered_collections() -> None:
    a = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A)
    b = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_B)
    me = PartyRef(PartyKind.PRINCIPAL)
    other = PartyRef(PartyKind.UNRESOLVED, label="Vendor")
    constraint = ProjectConstraint(
        constraint_id="cst_aaaa0001aaaa0001aaaa",
        principal_id=PRINCIPAL_ID,
        lifecycle_state=ConstraintLifecycleState.DRAFT,
        origin=ConstraintOrigin.PRODUCT,
        created_at=T0,
        updated_at=T0,
        date_identified=date(2026, 9, 1),
        bic=(b, a, a, other),
        responsible=(me, b),
    )
    assert constraint.bic == (b, a, a, other)
    assert constraint.responsible == (me, b)
    assert constraint.bic != constraint.responsible
    assert len(constraint.bic) == 4
    assert constraint.bic.count(a) == 2
    # Responsible containing the Principal does not put it in my court.
    assert in_my_court(ConstraintLifecycleState.IDENTIFIED, constraint.bic) is False


def test_in_my_court_uses_identity_never_wording() -> None:
    proven = frozenset({ENTITY_A})
    entity = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A, label="Bobby")
    lookalike = PartyRef(PartyKind.UNRESOLVED, label="Bobby")
    state = ConstraintLifecycleState.IN_PROGRESS
    assert in_my_court(state, (entity,), proven) is True
    assert in_my_court(state, (lookalike,), proven) is False
    assert in_my_court(state, (lookalike, entity), proven) is True
    # The label is inert: a different label on the same identity still counts,
    # and the proven set is keyed by id, so a label there matches nothing.
    assert in_my_court(state, (PartyRef(PartyKind.ENTITY, entity_id=ENTITY_A),), proven) is True
    assert in_my_court(state, (entity,), frozenset({"Bobby"})) is False
