"""Unit tests for the PC-CM-IMP-WP02 Constraint revision snapshot.

The claim that matters is `from_constraint`'s exactness: a revision that dropped
a field, or reordered a party collection, would be an audit record that quietly
disagrees with the row it claims to record.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.revision import ConstraintRevision, ConstraintRevisionError

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
PROJECT_ID = "prj_aaaa0001aaaa0001aaaa"
CATEGORY_ID = "ccat_aaaa0001aaaa0001aaaa"
CONSTRAINT_ID = "cst_aaaa0001aaaa0001aaaa"
REVISION_ID = "crev_aaaa0001aaaa0001aaaa"
HISTORY_ID = "chst_aaaa0001aaaa0001aaaa"
ENTITY_ONE = "ent_aaaa0001aaaa0001aaaa"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

#: The scalar names a revision snapshots. Plan §C.5 requires the snapshot
#: columns to carry the aggregate's own names and types.
SNAPSHOT_SCALARS = (
    "project_id",
    "category_id",
    "constraint_code",
    "description",
    "date_identified",
    "lifecycle_state",
    "due_date",
    "reference",
    "current_update",
    "completion_date",
    "closure_commentary",
    "voided_date",
    "void_reason",
    "record_quality",
    "origin",
    "published_at",
    "version",
)


def _published() -> ProjectConstraint:
    return ProjectConstraint(
        constraint_id=CONSTRAINT_ID,
        principal_id=PRINCIPAL_ID,
        lifecycle_state=ConstraintLifecycleState.IDENTIFIED,
        origin=ConstraintOrigin.PRODUCT,
        created_at=T0,
        updated_at=T0,
        version=4,
        project_id=PROJECT_ID,
        category_id=CATEGORY_ID,
        constraint_code="2.10",
        description="Long-lead switchgear submittal outstanding",
        date_identified=date(2026, 8, 3),
        due_date=date(2026, 9, 30),
        reference="RFI-114",
        current_update="Vendor confirmed a ship date",
        bic=(
            PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_ONE, label="Acme Electrical"),
            PartyRef(kind=PartyKind.UNRESOLVED, label="the switchgear rep"),
        ),
        responsible=(PartyRef(kind=PartyKind.PRINCIPAL),),
        published_at=T0,
    )


def _revision(**overrides: object) -> ConstraintRevision:
    fields_: dict[str, object] = {
        "revision_id": REVISION_ID,
        "principal_id": PRINCIPAL_ID,
        "constraint_id": CONSTRAINT_ID,
        "history_id": HISTORY_ID,
        "version": 1,
        "lifecycle_state": ConstraintLifecycleState.DRAFT,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "recorded_at": T0,
    }
    fields_.update(overrides)
    return ConstraintRevision(**fields_)  # type: ignore[arg-type]


def test_from_constraint_copies_every_scalar_the_aggregate_carries() -> None:
    constraint = _published()
    revision = ConstraintRevision.from_constraint(
        constraint, revision_id=REVISION_ID, history_id=HISTORY_ID, recorded_at=T0
    )
    for name in SNAPSHOT_SCALARS:
        assert getattr(revision, name) == getattr(constraint, name), name
    assert revision.revision_id == REVISION_ID
    assert revision.history_id == HISTORY_ID
    assert revision.constraint_id == constraint.constraint_id
    assert revision.recorded_at == T0


def test_the_snapshot_names_every_aggregate_scalar_and_invents_none() -> None:
    """A field added to one side without the other is caught here, not in review."""
    aggregate = {field.name for field in fields(ProjectConstraint)}
    snapshot = {field.name for field in fields(ConstraintRevision)}
    unsnapshotted = aggregate - snapshot - {"created_at", "updated_at"}
    assert unsnapshotted == set(), unsnapshotted
    invented = snapshot - aggregate
    assert invented == {"revision_id", "history_id", "recorded_at"}, invented


def test_party_collections_are_snapshotted_in_order_and_kind() -> None:
    constraint = _published()
    revision = ConstraintRevision.from_constraint(
        constraint, revision_id=REVISION_ID, history_id=HISTORY_ID, recorded_at=T0
    )
    assert revision.bic == constraint.bic
    assert [party.kind for party in revision.bic] == [PartyKind.ENTITY, PartyKind.UNRESOLVED]
    assert revision.bic[0].entity_id == ENTITY_ONE
    assert revision.bic[1].label == "the switchgear rep"
    assert revision.responsible == (PartyRef(kind=PartyKind.PRINCIPAL),)


def test_reordering_a_party_collection_produces_a_different_snapshot() -> None:
    constraint = _published()
    reversed_bic = ProjectConstraint(
        **{
            field.name: getattr(constraint, field.name)
            for field in fields(ProjectConstraint)
            if field.name != "bic"
        },
        bic=tuple(reversed(constraint.bic)),
    )
    first = ConstraintRevision.from_constraint(
        constraint, revision_id=REVISION_ID, history_id=HISTORY_ID, recorded_at=T0
    )
    second = ConstraintRevision.from_constraint(
        reversed_bic, revision_id=REVISION_ID, history_id=HISTORY_ID, recorded_at=T0
    )
    assert first != second


def test_a_snapshot_of_a_draft_carries_the_draft_s_absences() -> None:
    draft = ProjectConstraint(
        constraint_id=CONSTRAINT_ID,
        principal_id=PRINCIPAL_ID,
        lifecycle_state=ConstraintLifecycleState.DRAFT,
        origin=ConstraintOrigin.PRODUCT,
        created_at=T0,
        updated_at=T0,
    )
    revision = ConstraintRevision.from_constraint(
        draft, revision_id=REVISION_ID, history_id=HISTORY_ID, recorded_at=T0
    )
    assert revision.project_id is None
    assert revision.constraint_code is None
    assert revision.published_at is None
    assert revision.bic == ()


def test_a_revision_repeats_no_publish_completeness_rule() -> None:
    """A revision records what was, including a shape the aggregate refuses to be."""
    revision = _revision(
        lifecycle_state=ConstraintLifecycleState.CLOSED,
        record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
        origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
        constraint_code="7.03",
        project_id=PROJECT_ID,
    )
    assert revision.completion_date is None
    assert revision.published_at is None
    with pytest.raises(Exception):  # noqa: B017 - the aggregate refuses this exact row
        ProjectConstraint(
            constraint_id=CONSTRAINT_ID,
            principal_id=PRINCIPAL_ID,
            lifecycle_state=ConstraintLifecycleState.CLOSED,
            origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
            record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
            created_at=T0,
            updated_at=T0,
            project_id=PROJECT_ID,
            constraint_code="7.03",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision_id", "chst_aaaa0001aaaa0001aaaa"),
        ("principal_id", "prj_aaaa0001aaaa0001aaaa"),
        ("constraint_id", "crev_aaaa0001aaaa0001aaaa"),
        ("history_id", "crev_aaaa0001aaaa0001aaaa"),
        ("project_id", "ccat_aaaa0001aaaa0001aaaa"),
        ("category_id", "prj_aaaa0001aaaa0001aaaa"),
    ],
)
def test_every_identifier_is_checked_for_its_own_kind(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _revision(**{field: value})


def test_a_revision_version_is_positive() -> None:
    with pytest.raises(ConstraintRevisionError) as refusal:
        _revision(version=0)
    assert refusal.value.code == "constraint_revision_version_not_positive"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("lifecycle_state", "constraint_revision_lifecycle_state_unknown"),
        ("origin", "constraint_revision_origin_unknown"),
        ("record_quality", "constraint_revision_record_quality_unknown"),
    ],
)
def test_every_vocabulary_is_a_member_and_never_a_bare_string(field: str, code: str) -> None:
    with pytest.raises(ConstraintRevisionError) as refusal:
        _revision(**{field: "draft"})
    assert refusal.value.code == code


def test_a_party_snapshot_holds_party_references_and_not_raw_values() -> None:
    with pytest.raises(ConstraintRevisionError) as refusal:
        _revision(bic=("Acme Electrical",))
    assert refusal.value.code == "constraint_revision_party_malformed"


def test_a_naive_recorded_at_is_refused_rather_than_assumed_utc() -> None:
    with pytest.raises(ValueError):
        _revision(recorded_at=datetime(2026, 9, 1, 12, 0))
