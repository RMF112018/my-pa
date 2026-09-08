"""PC-CM-IMP-WP03 §L T15: what a Register search reaches, and what it cannot.

The search is a bounded substring match over exactly four persisted columns —
Constraint Code, description, reference and current update. No `to_tsvector`
index exists on any Constraint column, so this is an `ILIKE` against a declared
ESCAPE rather than full-text ranking, and the tests below hold it to the two
properties that choice makes load-bearing: the term is escaped rather than
stripped, so `%` finds a per-cent sign instead of every row; and the predicate is
never the only one, so it is always conjoined with the Principal, the Project
and a SQL `LIMIT`.

The columns *not* searched are asserted as directly as the ones that are. A
closure commentary and a void reason are stored on the same row and are outside
the approved field set, so a term that appears only there finds nothing — a
search surface grows by contract, not by a column being nearby.

Every code, reference and phrase here is synthetic.
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
    MAX_SEARCH_CHARACTERS,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintQueryError,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_srhaaaa01"
PRINCIPAL_B: Final = "prn_srhbbbb02"
PROJECT_A: Final = "prj_srhaaaa01"
PROJECT_B: Final = "prj_srhbbbb02"
CATEGORY_A: Final = "ccat_srhaaaa01"
CATEGORY_B: Final = "ccat_srhbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_srh{ordinal:06d}"


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


BY_CODE: Final = _id("cst", 1)
BY_DESCRIPTION: Final = _id("cst", 2)
BY_REFERENCE: Final = _id("cst", 3)
BY_UPDATE: Final = _id("cst", 4)
BY_CLOSURE: Final = _id("cst", 5)
FOREIGN: Final = _id("cst", 6)


def _searchable(connection: Connection) -> SqlConstraintManagementRepository:
    """One Constraint carrying the sought term in each of the four fields, and two decoys."""
    repository = _world(connection)
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=BY_CODE,
            constraint_code="3.14",
            description="Nothing notable",
            reference=None,
            current_update=None,
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=BY_DESCRIPTION,
            constraint_code="1.02",
            description="Switchgear SUBMITTAL is at 50% review",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=BY_REFERENCE,
            constraint_code="1.03",
            description="Nothing notable",
            reference="RFI_204",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=BY_UPDATE,
            constraint_code="1.04",
            description="Nothing notable",
            current_update="Vendor confirmed a shipping date",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=BY_CLOSURE,
            constraint_code="1.05",
            description="Nothing notable",
            lifecycle_state=ConstraintLifecycleState.CLOSED,
            completion_date=date(2026, 9, 11),
            closure_commentary="Resolved by the ironmongery schedule",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_B,
        _constraint(
            constraint_id=FOREIGN,
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_B,
            category_id=CATEGORY_B,
            constraint_code="1.06",
            description="Switchgear submittal in the other partition",
        ),
    )
    return repository


def _found(repository: SqlConstraintManagementRepository, term: str, **fields: object) -> list[str]:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL, search_text=term, **fields),
        now=NOW,
    )
    return sorted(entry.constraint_id for entry in page.entries)


def test_the_search_reaches_each_of_the_four_approved_fields(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert _found(repository, "3.14") == [BY_CODE]
        assert _found(repository, "switchgear") == [BY_DESCRIPTION]
        assert _found(repository, "RFI_204") == [BY_REFERENCE]
        assert _found(repository, "shipping") == [BY_UPDATE]


def test_a_term_that_appears_only_outside_the_four_fields_finds_nothing(
    migrated_engine: Engine,
) -> None:
    """The closure commentary is on the row and is still not searchable."""
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert _found(repository, "ironmongery") == []
        assert BY_CLOSURE in _found(repository, "1.05")


def test_matching_ignores_case(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert _found(repository, "SUBMITTAL") == _found(repository, "submittal")
        assert _found(repository, "SwItChGeAr") == [BY_DESCRIPTION]


def test_pattern_characters_are_escaped_rather_than_interpreted(
    migrated_engine: Engine,
) -> None:
    """A per-cent sign is a per-cent sign, and an underscore matches an underscore."""
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert _found(repository, "50%") == [BY_DESCRIPTION]
        assert _found(repository, "%%") == []
        assert _found(repository, "RFI_204") == [BY_REFERENCE]
        assert _found(repository, "RFIX204") == []


def test_a_blank_term_is_no_predicate_rather_than_an_error(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert len(_found(repository, "   ")) == 5
        assert ConstraintListQuery(search_text="  ").search_text is None


def test_a_term_outside_its_bounds_is_refused_at_the_request(
    migrated_engine: Engine,
) -> None:
    """Bounded where the request is built, so no code path holds an unbounded one."""
    with migrated_engine.begin() as connection:
        _searchable(connection)
        with pytest.raises(ConstraintQueryError):
            ConstraintListQuery(search_text="x")
        with pytest.raises(ConstraintQueryError):
            ConstraintListQuery(search_text="x" * (MAX_SEARCH_CHARACTERS + 1))
        assert ConstraintListQuery(search_text="x" * MAX_SEARCH_CHARACTERS).search_text is not None


def test_a_search_never_leaves_the_principal_or_the_project(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        assert _found(repository, "other partition") == []
        assert _found(repository, "switchgear") == [BY_DESCRIPTION]
        _seed_project(connection, PRINCIPAL_A, "prj_srhaaaa03")
        repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, "prj_srhaaaa03"))
        elsewhere = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id="prj_srhaaaa03",
            query=ConstraintListQuery(scope=ConstraintListScope.ALL, search_text="switchgear"),
            now=NOW,
        )
        assert elsewhere.entries == ()


def test_a_search_page_is_still_bounded_by_its_limit(migrated_engine: Engine) -> None:
    """The search predicate narrows the page; it never removes the ceiling on it."""
    with migrated_engine.begin() as connection:
        repository = _searchable(connection)
        page = SERVICE.list_constraints(
            repository,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            query=ConstraintListQuery(
                scope=ConstraintListScope.ALL, search_text="Nothing notable", limit=2
            ),
            now=NOW,
        )
        assert len(page.entries) == 2
        assert page.is_truncated is True
        assert page.next_cursor is not None
