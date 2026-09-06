"""PC-CM-IMP-WP03 §L T20-T21: relationships and evidence, as references and never as content.

Both tables are read here for the first time in the repository's history, and
neither has a writer yet — WP06 will add one — so the rows are seeded with
SQLAlchemy Core. That is deliberate: the read plane is being proved against the
shape the schema already admits, not against a writer invented to make the test
pass.

A relationship is projected from the reading Constraint's own end, so the same
stored row is `OUTGOING` to its source and `INCOMING` to its target, and the far
end's Code and status are joined in. The join carries the Principal predicate on
**both** sides, which is why the other Principal reading the same identifier gets
nothing at all rather than a row with a hole in it — the schema's composite
foreign keys already make a cross-partition relationship unwritable, and the read
does not rely on that being true.

Evidence links carry an identifier, a kind and a role, and nothing else. No
captured body, no document title, no provider name and no workbook coordinate
has a field to travel in, so what is cited can be looked up by the plane that
owns it and cannot be duplicated here.

Every identifier and reference here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import RelationshipDirection
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import (
    project_constraint_evidence_links,
    project_constraint_relationships,
    projects,
)

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_relaaaa01"
PRINCIPAL_B: Final = "prn_relbbbb02"
PROJECT_A: Final = "prj_relaaaa01"
PROJECT_B: Final = "prj_relbbbb02"
CATEGORY_A: Final = "ccat_relaaaa01"
CATEGORY_B: Final = "ccat_relbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_rel{ordinal:06d}"


def _seed_project(connection: Connection, principal: str, project: str) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name="Sample Project",
            state="active",
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )


def _category(
    category_id: str, principal: str, project: str, prefix: str, display_order: int
) -> ConstraintCategory:
    return ConstraintCategory(
        category_id=category_id,
        principal_id=principal,
        project_id=project,
        prefix=prefix,
        title=f"Category {prefix}",
        state=ConstraintCategoryState.ACTIVE,
        created_at=T0,
        updated_at=T0,
        display_order=display_order,
    )


def _settings(principal: str, project: str, zone: str = ZONE_EAST) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal,
        project_id=project,
        timezone_name=zone,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _constraint(**overrides: object) -> ProjectConstraint:
    """One published, active Constraint. Every value in it is synthetic."""
    values: dict[str, Any] = {
        "constraint_id": _id("cst", 1),
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "project_id": PROJECT_A,
        "category_id": CATEGORY_A,
        "constraint_code": "1.01",
        "description": "Switchgear submittal outstanding",
        "date_identified": date(2026, 9, 1),
        "due_date": date(2026, 9, 30),
        "bic": (PartyRef(kind=PartyKind.PRINCIPAL),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _world(connection: Connection, *, zone: str = ZONE_EAST) -> SqlConstraintManagementRepository:
    """Both Principals, both Projects, one Category each. Nothing is shared."""
    _seed_project(connection, PRINCIPAL_A, PROJECT_A)
    _seed_project(connection, PRINCIPAL_B, PROJECT_B)
    repository = SqlConstraintManagementRepository(connection)
    repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_A, zone))
    repository.insert_project_settings(PRINCIPAL_B, _settings(PRINCIPAL_B, PROJECT_B, zone))
    repository.insert_category(PRINCIPAL_A, _category(CATEGORY_A, PRINCIPAL_A, PROJECT_A, "AAA", 1))
    repository.insert_category(PRINCIPAL_B, _category(CATEGORY_B, PRINCIPAL_B, PROJECT_B, "BBB", 1))
    return repository


SOURCE: Final = _id("cst", 1)
TARGET: Final = _id("cst", 2)
UNRELATED: Final = _id("cst", 3)
FOREIGN: Final = _id("cst", 4)
RELATIONSHIP: Final = _id("crel", 1)
RECEIPT: Final = _id("chst", 1)
FOREIGN_RECEIPT: Final = _id("chst", 2)
EVIDENCE_CAPTURE: Final = _id("cevd", 1)
EVIDENCE_DOCUMENT: Final = _id("cevd", 2)
CAPTURE_REF: Final = "cap_syntheticevidence01"
DOCUMENT_REF: Final = "mdoc_syntheticevidenc1"


def _receipt(
    principal: str, history_id: str, constraint_id: str, project: str
) -> ConstraintHistoryEntry:
    """One no-op receipt, present only because both tables cite the receipt that made them."""
    return ConstraintHistoryEntry(
        history_id=history_id,
        principal_id=principal,
        constraint_id=constraint_id,
        project_id=project,
        operation=ConstraintMutationOperation.UPDATE,
        actor=ConstraintMutationActor.PRINCIPAL,
        outcome=ConstraintMutationOutcome.NO_OP,
        before_version=1,
        after_version=1,
        occurred_at=T0,
        recorded_at=T0,
    )


def _linked(connection: Connection) -> SqlConstraintManagementRepository:
    """One `follow_up_of` between two of A's Constraints, and two evidence citations."""
    repository = _world(connection)
    repository.insert_constraint(PRINCIPAL_A, _constraint(constraint_id=SOURCE))
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=TARGET,
            constraint_code="1.02",
            lifecycle_state=ConstraintLifecycleState.ON_HOLD,
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A, _constraint(constraint_id=UNRELATED, constraint_code="1.03")
    )
    repository.insert_constraint(
        PRINCIPAL_B,
        _constraint(
            constraint_id=FOREIGN,
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_B,
            category_id=CATEGORY_B,
            constraint_code="9.01",
        ),
    )
    repository.insert_history(PRINCIPAL_A, _receipt(PRINCIPAL_A, RECEIPT, SOURCE, PROJECT_A))
    repository.insert_history(
        PRINCIPAL_B, _receipt(PRINCIPAL_B, FOREIGN_RECEIPT, FOREIGN, PROJECT_B)
    )
    connection.execute(
        insert(project_constraint_relationships).values(
            relationship_id=RELATIONSHIP,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            source_constraint_id=SOURCE,
            target_constraint_id=TARGET,
            relationship_type="follow_up_of",
            created_by_history_id=RECEIPT,
            created_at=T0,
        )
    )
    connection.execute(
        insert(project_constraint_evidence_links).values(
            [
                {
                    "evidence_link_id": EVIDENCE_CAPTURE,
                    "principal_id": PRINCIPAL_A,
                    "project_id": PROJECT_A,
                    "constraint_id": SOURCE,
                    "evidence_kind": "capture",
                    "evidence_ref": CAPTURE_REF,
                    "role": "reference",
                    "created_by_history_id": RECEIPT,
                    "created_at": T0,
                },
                {
                    "evidence_link_id": EVIDENCE_DOCUMENT,
                    "principal_id": PRINCIPAL_A,
                    "project_id": PROJECT_A,
                    "constraint_id": SOURCE,
                    "evidence_kind": "managed_document",
                    "evidence_ref": DOCUMENT_REF,
                    "role": "closure",
                    "created_by_history_id": RECEIPT,
                    "created_at": T0,
                },
            ]
        )
    )
    return repository


def test_a_relationship_is_projected_from_the_reading_constraints_own_end(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        source_view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=SOURCE, now=NOW
        )
        target_view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=TARGET, now=NOW
        )
        (outgoing,) = source_view.relationships
        (incoming,) = target_view.relationships
        assert outgoing.relationship_id == incoming.relationship_id == RELATIONSHIP
        assert outgoing.direction is RelationshipDirection.OUTGOING
        assert incoming.direction is RelationshipDirection.INCOMING
        assert outgoing.relationship_type == "follow_up_of"


def test_the_far_ends_code_and_status_are_joined_from_the_same_partition(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        source_view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=SOURCE, now=NOW
        )
        (outgoing,) = source_view.relationships
        assert outgoing.related_constraint_id == TARGET
        assert outgoing.related_constraint_code == "1.02"
        assert outgoing.related_status is ConstraintLifecycleState.ON_HOLD


def test_a_constraint_with_no_relationship_projects_none(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=UNRELATED, now=NOW
        )
        assert view.relationships == ()


def test_the_other_principal_reads_no_relationship_for_the_same_identifier(
    migrated_engine: Engine,
) -> None:
    """The partition predicate is on both sides of the join, not only the outer row."""
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        assert repository.relationships_for(PRINCIPAL_B, SOURCE) == ()
        assert repository.relationships_for(PRINCIPAL_B, TARGET) == ()
        assert repository.relationships_for(PRINCIPAL_A, FOREIGN) == ()


def test_the_relationship_projection_names_no_receipt_and_no_partition(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        rows = repository.relationships_for(PRINCIPAL_A, SOURCE)
        fields = set(type(rows[0]).__slots__)
        assert fields.isdisjoint(
            {"created_by_history_id", "principal_id", "project_id", "created_at"}
        )
        assert RECEIPT not in repr(rows)
        assert PRINCIPAL_A not in repr(rows)


def test_evidence_links_project_their_reference_kind_and_role(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=SOURCE, now=NOW
        )
        captured, documented = view.evidence_links
        assert (captured.evidence_kind, captured.evidence_ref, captured.role) == (
            "capture",
            CAPTURE_REF,
            "reference",
        )
        assert (documented.evidence_kind, documented.evidence_ref, documented.role) == (
            "managed_document",
            DOCUMENT_REF,
            "closure",
        )


def test_an_evidence_link_carries_no_content_and_no_provider_locator(
    migrated_engine: Engine,
) -> None:
    """There is no field for a body or a workbook coordinate, so neither can travel."""
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        rows = repository.evidence_links_for(PRINCIPAL_A, SOURCE)
        fields = set(type(rows[0]).__slots__)
        assert fields == {"evidence_link_id", "evidence_kind", "evidence_ref", "role"}
        rendered = repr(rows)
        assert RECEIPT not in rendered
        assert PRINCIPAL_A not in rendered
        assert PROJECT_A not in rendered


def test_the_other_principal_reads_no_evidence_for_the_same_identifier(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _linked(connection)
        assert repository.evidence_links_for(PRINCIPAL_B, SOURCE) == ()
        assert repository.evidence_links_for(PRINCIPAL_A, UNRELATED) == ()
