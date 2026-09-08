"""PC-CM-IMP-WP03 §L T5-T6: how a Constraint's parties are projected and filtered.

BIC and Responsible are two roles, not one field with a flag, and either can
name several parties. What these tests hold to is the identity rule: the thing a
filter matches on is `party_ref_id`, and the thing a reader is shown is
`display_label`, and the two are never interchanged. A PRINCIPAL party's
identity is the closed token `"principal"` and never a `prn_` value; an ENTITY
party's is its `ent_` identifier; an UNRESOLVED party has no identity at all and
is reachable only as the `"unresolved"` bucket.

The Entity label read is the other half. It is bulk and it is partition-scoped,
so an ENTITY party naming another Principal's Entity gets the same fallback an
Entity nobody has created gets — the foreign display name is never fetched and
never rendered, and the two cases are not distinguishable from the outside.

Every identifier, label and code here is synthetic.
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
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    PRINCIPAL_DISPLAY_LABEL,
    PRINCIPAL_PARTY_REF,
    UNKNOWN_DISPLAY_LABEL,
    UNRESOLVED_PARTY_REF,
    ConstraintListEntry,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintQueryError,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import entities, projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_ptyaaaa01"
PRINCIPAL_B: Final = "prn_ptybbbb02"
PROJECT_A: Final = "prj_ptyaaaa01"
PROJECT_B: Final = "prj_ptybbbb02"
CATEGORY_A: Final = "ccat_ptyaaaa01"
CATEGORY_B: Final = "ccat_ptybbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_pty{ordinal:06d}"


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


CONSTRAINT_ONE: Final = _id("cst", 1)
CONSTRAINT_TWO: Final = _id("cst", 2)
ENTITY_MINE: Final = _id("ent", 1)
ENTITY_OTHER: Final = _id("ent", 2)
ENTITY_FOREIGN: Final = _id("ent", 3)


def _seed_entity(connection: Connection, principal: str, entity_id: str, name: str) -> None:
    connection.execute(
        insert(entities).values(
            entity_id=entity_id,
            principal_id=principal,
            entity_type="organization",
            canonical_name=name.lower(),
            display_name=name,
            status="active",
            created_at=T0,
            updated_at=T0,
            version=1,
        )
    )


def _peopled(connection: Connection) -> SqlConstraintManagementRepository:
    """One Constraint waiting on three parties and answerable by two."""
    repository = _world(connection)
    _seed_entity(connection, PRINCIPAL_A, ENTITY_MINE, "Sample Steel")
    _seed_entity(connection, PRINCIPAL_A, ENTITY_OTHER, "Sample Glazing")
    _seed_entity(connection, PRINCIPAL_B, ENTITY_FOREIGN, "Other Principal Holdings")
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=CONSTRAINT_ONE,
            bic=(
                PartyRef(kind=PartyKind.PRINCIPAL),
                PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_MINE),
                PartyRef(kind=PartyKind.UNRESOLVED, label="the switchgear rep"),
            ),
            responsible=(
                PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_OTHER, label="Glazing, stored"),
                PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_FOREIGN),
            ),
        ),
    )
    return repository


def _only(repository: SqlConstraintManagementRepository) -> ConstraintListEntry:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL),
        now=NOW,
    )
    assert len(page.entries) == 1
    return page.entries[0]


def test_bic_and_responsible_are_separate_ordered_and_multi_valued(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entry = _only(_peopled(connection))
        assert [view.kind for view in entry.bic] == [
            PartyKind.PRINCIPAL,
            PartyKind.ENTITY,
            PartyKind.UNRESOLVED,
        ]
        assert [view.kind for view in entry.responsible] == [PartyKind.ENTITY, PartyKind.ENTITY]
        assert entry.bic != entry.responsible


def test_each_party_kind_carries_the_identity_its_kind_defines(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entry = _only(_peopled(connection))
        principal, entity, unresolved = entry.bic
        assert principal.party_ref_id == PRINCIPAL_PARTY_REF
        assert principal.display_label == PRINCIPAL_DISPLAY_LABEL
        assert principal.entity_id is None
        assert entity.party_ref_id == ENTITY_MINE
        assert entity.entity_id == ENTITY_MINE
        assert entity.display_label == "Sample Steel"
        assert unresolved.party_ref_id is None
        assert unresolved.display_label == "the switchgear rep"


def test_no_returned_model_carries_a_raw_principal_identifier(
    migrated_engine: Engine,
) -> None:
    """The partition is how the row was found, never something the row says."""
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        entry = _only(repository)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT_ONE, now=NOW
        )
        for rendered in (repr(entry), repr(view)):
            assert PRINCIPAL_A not in rendered
            assert PRINCIPAL_B not in rendered
            assert "prn_" not in rendered


def test_a_detail_read_projects_the_same_parties_as_the_list_row(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        entry = _only(repository)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT_ONE, now=NOW
        )
        assert view.bic == entry.bic
        assert view.responsible == entry.responsible


def test_a_party_filter_matches_on_the_reference_and_not_on_the_label(
    migrated_engine: Engine,
) -> None:
    """A display label is presentation text. It is not addressable, by design."""
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=CONSTRAINT_TWO,
                constraint_code="1.02",
                bic=(PartyRef(kind=PartyKind.UNRESOLVED, label="somebody else"),),
            ),
        )
        for reference, expected in (
            (PRINCIPAL_PARTY_REF, [CONSTRAINT_ONE]),
            (ENTITY_MINE, [CONSTRAINT_ONE]),
            (UNRESOLVED_PARTY_REF, [CONSTRAINT_ONE, CONSTRAINT_TWO]),
        ):
            page = SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                query=ConstraintListQuery(
                    scope=ConstraintListScope.ALL, bic_party_refs=frozenset({reference})
                ),
                now=NOW,
            )
            assert sorted(entry.constraint_id for entry in page.entries) == sorted(expected)
        with pytest.raises(ConstraintQueryError):
            ConstraintListQuery(bic_party_refs=frozenset({PRINCIPAL_DISPLAY_LABEL}))


def test_a_party_filter_is_scoped_to_the_role_it_names(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        matched = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL,
                responsible_party_refs=frozenset({ENTITY_OTHER}),
            ),
            now=NOW,
        )
        assert [entry.constraint_id for entry in matched.entries] == [CONSTRAINT_ONE]
        crossed = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, bic_party_refs=frozenset({ENTITY_OTHER})
            ),
            now=NOW,
        )
        assert crossed.entries == ()


def test_a_multi_party_row_is_returned_once_however_many_references_match(
    migrated_engine: Engine,
) -> None:
    """`EXISTS` rather than a join: a filter narrows the page, it never grows it."""
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL,
                bic_party_refs=frozenset({PRINCIPAL_PARTY_REF, ENTITY_MINE, UNRESOLVED_PARTY_REF}),
            ),
            now=NOW,
        )
        assert [entry.constraint_id for entry in page.entries] == [CONSTRAINT_ONE]


def test_a_foreign_entity_party_falls_back_without_naming_the_entity(
    migrated_engine: Engine,
) -> None:
    """The Entity read is `_mine`-scoped, so the foreign name is never fetched."""
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        entry = _only(repository)
        stored, foreign = entry.responsible
        assert stored.display_label == "Glazing, stored"
        assert foreign.party_ref_id == ENTITY_FOREIGN
        assert foreign.display_label == UNKNOWN_DISPLAY_LABEL
        assert "Other Principal Holdings" not in repr(entry)
        assert repository.entity_labels(PRINCIPAL_A, (ENTITY_FOREIGN,)) == {}
        assert repository.entity_labels(PRINCIPAL_A, (ENTITY_MINE,)) == {
            ENTITY_MINE: "Sample Steel"
        }


def test_the_party_read_is_one_bulk_statement_for_a_whole_page(
    migrated_engine: Engine,
) -> None:
    """`parties_for` takes the page, not a row, and returns stored order."""
    with migrated_engine.begin() as connection:
        repository = _peopled(connection)
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=CONSTRAINT_TWO,
                constraint_code="1.02",
                bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
            ),
        )
        rows = repository.parties_for(PRINCIPAL_A, (CONSTRAINT_ONE, CONSTRAINT_TWO))
        assert {row.constraint_id for row in rows} == {CONSTRAINT_ONE, CONSTRAINT_TWO}
        ordered = [
            (row.constraint_id, row.role, row.ordinal)
            for row in rows
            if row.constraint_id == CONSTRAINT_ONE
        ]
        assert ordered == sorted(ordered)
        assert repository.parties_for(PRINCIPAL_B, (CONSTRAINT_ONE, CONSTRAINT_TWO)) == ()
