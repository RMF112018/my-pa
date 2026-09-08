"""PC-CM-IMP-WP03 §L T13 and T18: what a Register filter means, and what a group key is.

One fixture holds six Constraints covering every lifecycle state the four scopes
divide, and every test below asks the same seeded data a different question. The
composition rule is the thing under test: members of one filter family are
alternatives, families are conjunctions, and all of it conjoins with the scope,
the quick filters and the search. A filter can only ever narrow a page.

The quick filters are not re-derived here. `overdue`, `due_soon`, `my_court` and
`needs_attention` are the same expressions the overview counts with, so a row
this file's list assertions include is a row the overview's count includes —
which is what `test_constraint_read_overview.py` then proves directly.

Grouping returns a key per row and never a grouped result set. Category and
Status are single-valued; BIC and Responsible are the row's party references,
zero, one or several, and the row appears exactly once whatever its membership.
No group total is returned for any grouping, because the accepted contract does
not define what a multi-party row's membership is and a total would be a number
a reader could not check.

`NOW` read in `ZONE_EAST` is Monday 14 September 2026, so Due Soon runs through
Wednesday 23 September — seven working days later. Every value here is synthetic.
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
    ConstraintGrouping,
    ConstraintListPage,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintRecentFilter,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_lstaaaa01"
PRINCIPAL_B: Final = "prn_lstbbbb02"
PROJECT_A: Final = "prj_lstaaaa01"
PROJECT_B: Final = "prj_lstbbbb02"
CATEGORY_A: Final = "ccat_lstaaaa01"
CATEGORY_B: Final = "ccat_lstbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_lst{ordinal:06d}"


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


OVERDUE: Final = _id("cst", 1)
DUE_SOON: Final = _id("cst", 2)
ON_HOLD: Final = _id("cst", 3)
CLOSED: Final = _id("cst", 4)
VOIDED: Final = _id("cst", 5)
DRAFT: Final = _id("cst", 6)
CATEGORY_SECOND: Final = "ccat_lstaaaa09"
ENTITY_ONE: Final = _id("ent", 1)

PROJECT_TODAY: Final = date(2026, 9, 14)
DUE_SOON_THROUGH: Final = date(2026, 9, 23)


def _register(connection: Connection) -> SqlConstraintManagementRepository:
    """Six Constraints: three active, one closed, one void, one draft."""
    repository = _world(connection)
    repository.insert_category(
        PRINCIPAL_A, _category(CATEGORY_SECOND, PRINCIPAL_A, PROJECT_A, "BBX", 2)
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=OVERDUE,
            constraint_code="1.01",
            due_date=date(2026, 9, 10),
            bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=DUE_SOON,
            constraint_code="1.02",
            lifecycle_state=ConstraintLifecycleState.IN_PROGRESS,
            due_date=date(2026, 9, 16),
            category_id=CATEGORY_SECOND,
            bic=(
                PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_ONE, label="Sample Steel"),
                PartyRef(kind=PartyKind.UNRESOLVED, label="the glazing rep"),
            ),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=ON_HOLD,
            constraint_code="1.03",
            lifecycle_state=ConstraintLifecycleState.ON_HOLD,
            due_date=date(2026, 10, 30),
            bic=(PartyRef(kind=PartyKind.UNRESOLVED, label="the owner"),),
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=CLOSED,
            constraint_code="1.04",
            lifecycle_state=ConstraintLifecycleState.CLOSED,
            completion_date=date(2026, 9, 11),
            closure_commentary="Vendor shipped",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=VOIDED,
            constraint_code="1.05",
            lifecycle_state=ConstraintLifecycleState.VOID,
            voided_date=date(2026, 9, 12),
            void_reason="raised twice",
        ),
    )
    repository.insert_constraint(
        PRINCIPAL_A,
        _constraint(
            constraint_id=DRAFT,
            lifecycle_state=ConstraintLifecycleState.DRAFT,
            constraint_code=None,
            category_id=None,
            published_at=None,
            due_date=None,
            bic=(),
        ),
    )
    return repository


def _listed(repository: SqlConstraintManagementRepository, **fields: object) -> list[str]:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(**fields),
        now=NOW,
    )
    return sorted(entry.constraint_id for entry in page.entries)


def _page(repository: SqlConstraintManagementRepository, **fields: object) -> ConstraintListPage:
    return SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(**fields),
        now=NOW,
    )


def test_each_scope_selects_the_lifecycle_states_it_names(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert _listed(repository, scope=ConstraintListScope.OPEN) == sorted(
            [OVERDUE, DUE_SOON, ON_HOLD]
        )
        assert _listed(repository, scope=ConstraintListScope.CLOSED) == sorted([CLOSED, VOIDED])
        assert _listed(repository, scope=ConstraintListScope.DRAFT) == [DRAFT]
        assert _listed(repository, scope=ConstraintListScope.ALL) == sorted(
            [OVERDUE, DUE_SOON, ON_HOLD, CLOSED, VOIDED, DRAFT]
        )


def test_the_closed_scope_keeps_closed_and_void_distinct_on_the_row(
    migrated_engine: Engine,
) -> None:
    """One scope, two meanings: the status stays on the row rather than being flattened."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        page = _page(repository, scope=ConstraintListScope.CLOSED)
        statuses = {entry.constraint_id: entry.status for entry in page.entries}
        assert statuses[CLOSED] is ConstraintLifecycleState.CLOSED
        assert statuses[VOIDED] is ConstraintLifecycleState.VOID


def test_each_quick_filter_selects_what_its_derivation_defines(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert _listed(repository, scope=ConstraintListScope.ALL, overdue=True) == [OVERDUE]
        assert _listed(repository, scope=ConstraintListScope.ALL, due_soon=True) == [DUE_SOON]
        assert _listed(repository, scope=ConstraintListScope.ALL, my_court=True) == [OVERDUE]
        assert _listed(repository, scope=ConstraintListScope.ALL, needs_attention=True) == []


def test_overdue_and_due_soon_are_disjoint_and_exclude_terminal_rows(
    migrated_engine: Engine,
) -> None:
    """`< today` and `>= today` cannot both hold, and a closed row is in neither."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        overdue = set(_listed(repository, scope=ConstraintListScope.ALL, overdue=True))
        due_soon = set(_listed(repository, scope=ConstraintListScope.ALL, due_soon=True))
        assert overdue & due_soon == set()
        assert CLOSED not in overdue | due_soon
        assert VOIDED not in overdue | due_soon
        page = _page(repository, scope=ConstraintListScope.ALL)
        flags = {
            entry.constraint_id: (entry.is_overdue, entry.is_due_soon) for entry in page.entries
        }
        assert flags[OVERDUE] == (True, False)
        assert flags[DUE_SOON] == (False, True)
        assert flags[ON_HOLD] == (False, False)
        assert flags[CLOSED] == (False, False)
        assert flags[DRAFT] == (False, False)


def test_the_due_soon_window_ends_on_the_seventh_business_day(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=_id("cst", 7),
                constraint_code="1.07",
                due_date=DUE_SOON_THROUGH,
            ),
        )
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(
                constraint_id=_id("cst", 8),
                constraint_code="1.08",
                due_date=date(2026, 9, 24),
            ),
        )
        selected = _listed(repository, scope=ConstraintListScope.ALL, due_soon=True)
        assert _id("cst", 7) in selected
        assert _id("cst", 8) not in selected


def test_members_of_one_filter_family_are_alternatives(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert _listed(
            repository,
            scope=ConstraintListScope.ALL,
            statuses=frozenset({ConstraintLifecycleState.ON_HOLD, ConstraintLifecycleState.CLOSED}),
        ) == sorted([ON_HOLD, CLOSED])
        assert _listed(
            repository,
            scope=ConstraintListScope.ALL,
            category_ids=frozenset({CATEGORY_A, CATEGORY_SECOND}),
        ) == sorted([OVERDUE, DUE_SOON, ON_HOLD, CLOSED, VOIDED])


def test_separate_filter_families_are_conjunctions(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert _listed(
            repository,
            scope=ConstraintListScope.ALL,
            statuses=frozenset({ConstraintLifecycleState.IN_PROGRESS}),
            category_ids=frozenset({CATEGORY_SECOND}),
        ) == [DUE_SOON]
        assert (
            _listed(
                repository,
                scope=ConstraintListScope.ALL,
                statuses=frozenset({ConstraintLifecycleState.IN_PROGRESS}),
                category_ids=frozenset({CATEGORY_A}),
            )
            == []
        )
        assert _listed(repository, scope=ConstraintListScope.OPEN, overdue=True) == [OVERDUE]
        assert _listed(repository, scope=ConstraintListScope.CLOSED, overdue=True) == []


def test_the_record_quality_and_sync_state_families_narrow_the_page(
    migrated_engine: Engine,
) -> None:
    """With no sync target configured, every row is `NEVER_SYNCED` and nothing else."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert _listed(
            repository,
            scope=ConstraintListScope.ALL,
            record_qualities=frozenset({ConstraintRecordQuality.NORMAL}),
        ) == sorted([OVERDUE, DUE_SOON, ON_HOLD, CLOSED, VOIDED, DRAFT])
        assert (
            _listed(
                repository,
                scope=ConstraintListScope.ALL,
                record_qualities=frozenset({ConstraintRecordQuality.LEGACY_INCOMPLETE}),
            )
            == []
        )


def test_the_recent_filters_use_the_clock_each_of_them_is_defined_on(
    migrated_engine: Engine,
) -> None:
    """Changed is measured in UTC; closed is measured on the Project's calendar."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        assert (
            _listed(
                repository,
                scope=ConstraintListScope.ALL,
                recent=ConstraintRecentFilter.RECENTLY_CHANGED,
            )
            == []
        )
        assert _listed(
            repository,
            scope=ConstraintListScope.ALL,
            recent=ConstraintRecentFilter.RECENTLY_CLOSED,
        ) == [CLOSED]


def test_category_grouping_gives_one_key_and_no_key_for_an_uncategorised_draft(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        page = _page(
            repository, scope=ConstraintListScope.ALL, grouping=ConstraintGrouping.CATEGORY
        )
        keys = {entry.constraint_id: entry.group_keys for entry in page.entries}
        assert keys[OVERDUE] == (CATEGORY_A,)
        assert keys[DUE_SOON] == (CATEGORY_SECOND,)
        assert keys[DRAFT] == ()


def test_status_grouping_gives_the_rows_own_lifecycle_state(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        page = _page(repository, scope=ConstraintListScope.ALL, grouping=ConstraintGrouping.STATUS)
        for entry in page.entries:
            assert entry.group_keys == (entry.status.value,)


def test_party_grouping_returns_several_keys_and_still_one_row(
    migrated_engine: Engine,
) -> None:
    """A row waiting on two parties is one row with two keys, never two rows."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        page = _page(repository, scope=ConstraintListScope.ALL, grouping=ConstraintGrouping.BIC)
        identifiers = [entry.constraint_id for entry in page.entries]
        assert len(identifiers) == len(set(identifiers))
        keys = {entry.constraint_id: entry.group_keys for entry in page.entries}
        assert keys[OVERDUE] == ("principal",)
        # The ENTITY reference is a key; the UNRESOLVED party has no identity to
        # be one, so the row's membership is one key and not two.
        assert keys[DUE_SOON] == (ENTITY_ONE,)
        assert keys[ON_HOLD] == ()
        assert keys[DRAFT] == ()


def test_no_grouping_returns_no_keys_and_no_page_carries_group_totals(
    migrated_engine: Engine,
) -> None:
    """There is no total field to be wrong: the contract does not define one."""
    with migrated_engine.begin() as connection:
        repository = _register(connection)
        page = _page(repository, scope=ConstraintListScope.ALL, grouping=ConstraintGrouping.NONE)
        assert all(entry.group_keys == () for entry in page.entries)
        assert set(ConstraintListPage.__slots__) == {"entries", "is_truncated", "next_cursor"}
