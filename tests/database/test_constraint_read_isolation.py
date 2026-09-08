"""PC-CM-IMP-WP03 §L T1-T3: the Constraint read plane cannot cross a partition.

Every test here seeds two Principals and two Projects and then asks one of them
a question whose wrong answer would be the other's data. What is being proved is
not that a filter happens to exclude the foreign rows, but that the statement
could not have returned them: the list, the overview, the detail read, the
Category list and the continuation cursor are each asked separately, because
each is a different statement and a partition predicate is only true where it is
written.

The three answers a foreign subject may receive are all the answers an absent
one receives. A foreign Constraint is `NotFoundError`, a foreign Project is the
same unavailable answer an unconfigured one gives, and a cursor issued in
another partition is the same conflict a cursor issued under a different filter
gives — none of them says the subject exists somewhere else.

Every identifier, code, label and date is synthetic and disposable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.application.errors import ConflictError, NotFoundError, SafeDetail, UnavailableError
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import ConstraintListQuery, ConstraintListScope
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_isoaaaa01"
PRINCIPAL_B: Final = "prn_isobbbb02"
PROJECT_A: Final = "prj_isoaaaa01"
PROJECT_B: Final = "prj_isobbbb02"
CATEGORY_A: Final = "ccat_isoaaaa01"
CATEGORY_B: Final = "ccat_isobbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_iso{ordinal:06d}"


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


CONSTRAINT_A: Final = _id("cst", 1)
CONSTRAINT_B: Final = _id("cst", 2)
ABSENT: Final = _id("cst", 99)

#: A second Project of Principal A's own, so that "a cursor from another
#: Project" can be asked inside one partition. Across Principals the Project
#: read fails first, which proves the partition but not the binding.
PROJECT_A2: Final = "prj_isoaaaa03"
CATEGORY_A2: Final = "ccat_isoaaaa03"


def _both_partitions(connection: Connection) -> SqlConstraintManagementRepository:
    """One published Constraint in each Principal's own Project."""
    repository = _world(connection)
    repository.insert_constraint(PRINCIPAL_A, _constraint(constraint_id=CONSTRAINT_A))
    repository.insert_constraint(
        PRINCIPAL_B,
        _constraint(
            constraint_id=CONSTRAINT_B,
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_B,
            category_id=CATEGORY_B,
            constraint_code="9.99",
            description="The other Principal's switchgear",
            reference="RFI-999",
        ),
    )
    return repository


def test_a_register_page_contains_only_the_asking_principals_rows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL),
            now=NOW,
        )
        assert [entry.constraint_id for entry in page.entries] == [CONSTRAINT_A]
        assert all(entry.project_id == PROJECT_A for entry in page.entries)
        mirrored = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_B,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL),
            now=NOW,
        )
        assert [entry.constraint_id for entry in mirrored.entries] == [CONSTRAINT_B]


def test_a_search_term_that_matches_the_other_partition_returns_nothing(
    migrated_engine: Engine,
) -> None:
    """The foreign row's own words are the strongest test of the predicate."""
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL, search_text="RFI-999"),
            now=NOW,
        )
        assert page.entries == ()


def test_a_foreign_constraint_reads_exactly_as_an_absent_one_does(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        with pytest.raises(NotFoundError) as foreign:
            SERVICE.read_constraint(
                repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT_B, now=NOW
            )
        with pytest.raises(NotFoundError) as absent:
            SERVICE.read_constraint(
                repository, principal_id=PRINCIPAL_A, constraint_id=ABSENT, now=NOW
            )
        assert str(foreign.value) == str(absent.value)
        assert foreign.value.safe_details == absent.value.safe_details
        assert repository.read_constraint(PRINCIPAL_A, CONSTRAINT_B) is None


def test_the_overview_counts_exclude_the_foreign_partition(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        overview = SERVICE.read_overview(
            repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
        )
        assert overview.total_open == 1
        assert overview.in_my_court == 1
        assert overview.needs_attention == 0
        assert overview.draft == 0


def test_a_foreign_project_is_unavailable_rather_than_named(migrated_engine: Engine) -> None:
    """No count, no name, and no statement that it exists in another partition."""
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        with pytest.raises(UnavailableError) as error:
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_B, now=NOW
            )
        assert error.value.safe_details == (SafeDetail.PROJECT_ID,)
        assert PROJECT_B not in str(error.value)


def test_a_foreign_projects_categories_are_not_listed_and_not_readable(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        assert (
            SERVICE.list_categories(repository, principal_id=PRINCIPAL_A, project_id=PROJECT_B)
            == ()
        )
        with pytest.raises(NotFoundError):
            SERVICE.read_category(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                category_id=CATEGORY_B,
            )


def test_a_foreign_category_filter_matches_nothing_rather_than_failing(
    migrated_engine: Engine,
) -> None:
    """A filter is not a lookup: a foreign Category narrows to zero, silently."""
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, category_ids=frozenset({CATEGORY_B})
            ),
            now=NOW,
        )
        assert page.entries == ()


def test_a_foreign_entity_party_filter_matches_nothing(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _both_partitions(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, bic_party_refs=frozenset({_id("ent", 7)})
            ),
            now=NOW,
        )
        assert page.entries == ()


def _first_page_cursor(repository: SqlConstraintManagementRepository) -> str:
    """A real, valid continuation token issued to Principal A for Project A."""
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL, limit=1),
        now=NOW,
    )
    assert page.is_truncated
    assert page.next_cursor is not None
    return page.next_cursor


def test_a_cursor_from_another_partition_is_refused_the_same_way_either_way(
    migrated_engine: Engine,
) -> None:
    """Foreign Principal and foreign Project are one answer, not two.

    The Principal and the Project are both inside the cursor's binding digest,
    so replaying a token across either boundary fails to validate rather than
    being caught by a later check — and the two failures are the same error with
    the same detail, so neither says which boundary was crossed.
    """
    with migrated_engine.begin() as connection:
        repository = _world(connection)
        for ordinal in (1, 2):
            repository.insert_constraint(
                PRINCIPAL_A,
                _constraint(constraint_id=_id("cst", ordinal), constraint_code=f"1.0{ordinal}"),
            )
        repository.insert_constraint(
            PRINCIPAL_B,
            _constraint(
                constraint_id=_id("cst", 5),
                principal_id=PRINCIPAL_B,
                project_id=PROJECT_B,
                category_id=CATEGORY_B,
                constraint_code="5.01",
            ),
        )
        _seed_project(connection, PRINCIPAL_A, PROJECT_A2)
        repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_A2))
        repository.insert_category(
            PRINCIPAL_A, _category(CATEGORY_A2, PRINCIPAL_A, PROJECT_A2, "AA2", 1)
        )
        token = _first_page_cursor(repository)
        with pytest.raises(ConflictError) as foreign_principal:
            SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_B,
                project_id=PROJECT_B,
                query=ConstraintListQuery(scope=ConstraintListScope.ALL, limit=1, cursor=token),
                now=NOW,
            )
        with pytest.raises(ConflictError) as foreign_project:
            SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A2,
                query=ConstraintListQuery(scope=ConstraintListScope.ALL, limit=1, cursor=token),
                now=NOW,
            )
        assert foreign_principal.value.safe_details == (SafeDetail.CURSOR,)
        assert foreign_project.value.safe_details == (SafeDetail.CURSOR,)
        assert str(foreign_principal.value) == str(foreign_project.value)


def test_a_cursor_replayed_in_its_own_partition_still_works(migrated_engine: Engine) -> None:
    """The control: the refusals above are about the partition, not the token."""
    with migrated_engine.begin() as connection:
        repository = _world(connection)
        for ordinal in (1, 2):
            repository.insert_constraint(
                PRINCIPAL_A,
                _constraint(constraint_id=_id("cst", ordinal), constraint_code=f"1.0{ordinal}"),
            )
        token = _first_page_cursor(repository)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(scope=ConstraintListScope.ALL, limit=1, cursor=token),
            now=NOW,
        )
        assert [entry.constraint_id for entry in page.entries] == [_id("cst", 2)]
