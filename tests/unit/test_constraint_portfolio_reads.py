"""Unit tests for the PC-CM-RUN01-WP06 cross-Project ("portfolio") Constraint reads.

Pure and fast: no database, no adapter, no clock. The property these tests exist
to hold is the one a portfolio surface is most likely to lose — **a portfolio has
no "today"**. It spans several Projects, each keeps its own IANA timezone, and a
read that resolved one calendar for all of them would classify a Constraint
Overdue on a calendar that is not its Project's. So the central test here fixes a
single UTC instant, puts two Projects on opposite sides of the date line from it,
gives both an identical Constraint with an identical Due Date, and requires the
two answers to differ. If the service ever collapsed to one calendar that test
would fail; it is written so the data could disprove the claim rather than so the
arrangement guarantees it.

The rest is the portfolio's share of what the exact-Project reads already
promise: a Project set that the service narrows and never widens, an unconfigured
Project that contributes nothing rather than failing the whole read, a cursor
that cannot be replayed across a scope, a Project set or a search change, bounded
limits, and refusals that are the same refusals.

Every identifier, code and description below is synthetic.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest

from my_pa.application.constraints import ConstraintReadService
from my_pa.application.errors import ConflictError, InvalidRequestError, UnavailableError
from my_pa.domain.project_controls.category import ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
)
from my_pa.domain.project_controls.read_models import (
    ConstraintCategoryRow,
    ConstraintCursorError,
    ConstraintGrouping,
    ConstraintListCursor,
    ConstraintListPage,
    ConstraintListQuery,
    ConstraintOverviewFacts,
    ConstraintPartyRow,
    ConstraintPortfolioListSpec,
    ConstraintQueryError,
    ConstraintSyncFacts,
    PersistedConstraintRecord,
    ProjectCalendar,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings

SERVICE = ConstraintReadService()

PRINCIPAL = "prn_portfolio01"
OTHER_PRINCIPAL = "prn_portfolio02"

#: Two Projects whose local dates differ at the instant below, and a third that
#: nobody has enrolled in Constraint Management. Sorted order is EAST, TOKYO,
#: UNSET, which is the order the service is required to work in.
PROJECT_EAST = "prj_portfolioa1"
PROJECT_TOKYO = "prj_portfoliob2"
PROJECT_UNSET = "prj_portfolioc3"

#: A Project the *other* Principal owns and has configured, holding a row of its
#: own. Nothing in this module may reach it under `PRINCIPAL`, and the fake below
#: is built so that a service which stopped narrowing would reach it -- which is
#: what makes "a foreign Project yields nothing" a claim about the service
#: rather than about an arrangement that had nothing to find.
PROJECT_OTHER = "prj_portfoliod4"

ZONE_EAST = "America/New_York"
ZONE_TOKYO = "Asia/Tokyo"

#: 2026-09-15 03:30 UTC is still 2026-09-14 in New York and already 2026-09-15
#: in Tokyo. One instant, two Project dates — the whole point of the fixture.
NOW = datetime(2026, 9, 15, 3, 30, tzinfo=UTC)
EAST_TODAY = date(2026, 9, 14)
TOKYO_TODAY = date(2026, 9, 15)

#: A Due Date that falls on one Project's date and before the other's.
SHARED_DUE_DATE = date(2026, 9, 14)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

CATEGORY_EAST = "ccat_portfolioa1"
CATEGORY_TOKYO = "ccat_portfoliob2"


def _settings(
    project_id: str, timezone_name: str, *, principal_id: str = PRINCIPAL
) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal_id,
        project_id=project_id,
        timezone_name=timezone_name,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _record(constraint_id: str, project_id: str, **overrides: object) -> PersistedConstraintRecord:
    fields: dict[str, Any] = {
        "constraint_id": constraint_id,
        "principal_id": PRINCIPAL,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "origin": ConstraintOrigin.PRODUCT,
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
        "project_id": project_id,
        "due_date": SHARED_DUE_DATE,
        "description": "Sample constraint",
    }
    fields.update(overrides)
    return PersistedConstraintRecord(**fields)


def _category(category_id: str, project_id: str, prefix: str) -> ConstraintCategoryRow:
    return ConstraintCategoryRow(
        category_id=category_id,
        project_id=project_id,
        prefix=prefix,
        title=f"Category {prefix}",
        description=None,
        display_order=1,
        state=ConstraintCategoryState.ACTIVE,
        next_sequence=1,
        issued_count=0,
        version=1,
        prefix_locked_at=None,
    )


class _PortfolioRepository:
    """A recording fake of the portfolio read port, and of nothing else.

    **Settings are keyed by `(principal_id, project_id)`**, as the shared
    `tests/conftest.py` fake and the stored composite key both are, so this
    module can hold a second Principal's configured Project and cross-Project
    isolation is something the data could disprove. Keyed by `project_id` alone
    it could not: a test named for principal isolation would have passed because
    the Project had no settings entry, which is what an *unconfigured* Project
    proves and not what the name claims.

    Rows and Categories are filtered by **the Projects the spec named and
    nothing else** — deliberately not by Principal. The real statements are
    Principal-scoped too, but a fake that repeated that scoping would answer
    emptily however wrong the service was, and the property under test is the
    service's own narrowing: the Project set is cut to the Projects whose
    settings this Principal owns, so a foreign Project never reaches the spec.
    Leaving the row read wide is what makes the violation representable — a
    service that stopped narrowing would surface `PROJECT_OTHER`'s row here and
    fail the test rather than quietly pass it.

    Every call records its arguments, which is how "the Principal is threaded to
    every statement" and "the Project set was never widened" are asserted rather
    than assumed.
    """

    def __init__(
        self,
        *,
        settings: Mapping[tuple[str, str], ConstraintProjectSettings],
        records: Sequence[PersistedConstraintRecord] = (),
        categories: Sequence[ConstraintCategoryRow] = (),
        facts: Mapping[str, ConstraintOverviewFacts] | None = None,
        sync: Mapping[str, ConstraintSyncFacts] | None = None,
    ) -> None:
        self._settings = dict(settings)
        self._records = tuple(records)
        self._categories = tuple(categories)
        self._facts = dict(facts or {})
        self._sync = dict(sync or {})
        self.principals: list[str] = []
        self.settings_requests: list[tuple[str, ...]] = []
        self.specs: list[ConstraintPortfolioListSpec] = []
        self.sync_requests: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.category_requests: list[tuple[str, ...]] = []
        self.facts_requests: list[tuple[ProjectCalendar, ...]] = []

    # --- the port ------------------------------------------------------

    def get_project_settings_for(
        self, principal_id: str, project_ids: Collection[str]
    ) -> Mapping[str, ConstraintProjectSettings]:
        self.principals.append(principal_id)
        self.settings_requests.append(tuple(project_ids))
        return {
            project_id: self._settings[(principal_id, project_id)]
            for project_id in project_ids
            if (principal_id, project_id) in self._settings
        }

    def list_portfolio_constraints(
        self, principal_id: str, *, spec: ConstraintPortfolioListSpec
    ) -> tuple[PersistedConstraintRecord, ...]:
        self.principals.append(principal_id)
        self.specs.append(spec)
        in_scope = set(spec.project_ids)
        found = tuple(row for row in self._records if row.project_id in in_scope)
        return found[: spec.fetch_limit]

    def list_categories_for(
        self,
        principal_id: str,
        project_ids: Collection[str],
        *,
        include_states: frozenset[ConstraintCategoryState] | None = None,
    ) -> tuple[ConstraintCategoryRow, ...]:
        self.principals.append(principal_id)
        self.category_requests.append(tuple(project_ids))
        in_scope = set(project_ids)
        return tuple(row for row in self._categories if row.project_id in in_scope)

    def portfolio_sync_summary(
        self,
        principal_id: str,
        project_ids: Collection[str],
        constraint_ids: Collection[str],
    ) -> Mapping[str, ConstraintSyncFacts]:
        self.principals.append(principal_id)
        self.sync_requests.append((tuple(project_ids), tuple(constraint_ids)))
        return {
            project_id: self._sync.get(
                project_id,
                ConstraintSyncFacts(
                    has_target=False,
                    last_verified_at=None,
                    baseline_versions={},
                    open_conflict_counts={},
                ),
            )
            for project_id in project_ids
        }

    def portfolio_overview_facts(
        self,
        principal_id: str,
        *,
        as_of: datetime,
        calendars: Collection[ProjectCalendar],
    ) -> Mapping[str, ConstraintOverviewFacts]:
        self.principals.append(principal_id)
        self.facts_requests.append(tuple(calendars))
        return {
            calendar.project_id: self._facts[calendar.project_id]
            for calendar in calendars
            if calendar.project_id in self._facts
        }

    def parties_for(
        self, principal_id: str, constraint_ids: Collection[str]
    ) -> tuple[ConstraintPartyRow, ...]:
        self.principals.append(principal_id)
        return ()

    def entity_labels(self, principal_id: str, entity_ids: Collection[str]) -> Mapping[str, str]:
        self.principals.append(principal_id)
        return {}


def _both_projects(**kwargs: object) -> _PortfolioRepository:
    return _PortfolioRepository(
        settings={
            (PRINCIPAL, PROJECT_EAST): _settings(PROJECT_EAST, ZONE_EAST),
            (PRINCIPAL, PROJECT_TOKYO): _settings(PROJECT_TOKYO, ZONE_TOKYO),
        },
        **kwargs,
    )


def _page(
    repository: _PortfolioRepository,
    *,
    project_ids: Sequence[str] = (PROJECT_EAST, PROJECT_TOKYO),
    query: ConstraintListQuery | None = None,
    principal_id: str = PRINCIPAL,
) -> ConstraintListPage:
    return SERVICE.list_portfolio_constraints(
        repository,  # type: ignore[arg-type]
        principal_id=principal_id,
        project_ids=project_ids,
        query=query or ConstraintListQuery(),
        now=NOW,
    )


# --- The per-Project calendar ------------------------------------------------


def test_two_projects_read_one_instant_as_two_dates_and_classify_the_same_due_date_apart() -> None:
    """The defining property: a portfolio has as many "todays" as it has Projects.

    One UTC instant, one Due Date, two Projects whose local dates differ across
    it. New York is still on the Due Date, so the row is Due Soon and not
    Overdue; Tokyo has already turned over, so the identical row is Overdue and
    not Due Soon. A service that resolved a single calendar would give both rows
    the same pair of flags, which is what this test is written to catch.
    """
    repository = _both_projects(
        records=(
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfoliob2", PROJECT_TOKYO),
        )
    )
    page = _page(repository)
    by_project = {entry.project_id: entry for entry in page.entries}
    east = by_project[PROJECT_EAST]
    tokyo = by_project[PROJECT_TOKYO]
    assert (east.is_overdue, east.is_due_soon) == (False, True)
    assert (tokyo.is_overdue, tokyo.is_due_soon) == (True, False)


def test_each_projects_own_calendar_reaches_the_statement_and_not_one_shared_date() -> None:
    """The dates the SQL is generated from are per Project, and visibly so."""
    repository = _both_projects()
    _page(repository)
    (spec,) = repository.specs
    resolved = {calendar.project_id: calendar for calendar in spec.calendars}
    assert resolved[PROJECT_EAST].project_today == EAST_TODAY
    assert resolved[PROJECT_TOKYO].project_today == TOKYO_TODAY
    assert resolved[PROJECT_EAST].project_today != resolved[PROJECT_TOKYO].project_today
    for calendar in spec.calendars:
        assert calendar.due_soon_through > calendar.project_today


def test_days_elapsed_is_counted_on_the_rows_own_project_calendar() -> None:
    """A derived age is a business-day count against *this* Project's date."""
    identified = date(2026, 9, 10)
    repository = _both_projects(
        records=(
            _record("cst_portfolioa1", PROJECT_EAST, date_identified=identified),
            _record("cst_portfoliob2", PROJECT_TOKYO, date_identified=identified),
        )
    )
    page = _page(repository)
    ages = {entry.project_id: entry.days_elapsed for entry in page.entries}
    # 2026-09-10 is a Thursday: Thu, Fri, Mon is three working days to the 14th
    # and four to the 15th.
    assert ages[PROJECT_EAST] == 3
    assert ages[PROJECT_TOKYO] == 4


def test_the_overview_reports_each_projects_own_date_timezone_and_counts() -> None:
    repository = _both_projects(
        facts={
            PROJECT_EAST: ConstraintOverviewFacts(
                total_open=3,
                overdue=1,
                due_soon=0,
                in_my_court=0,
                on_hold=0,
                recently_changed=0,
                recently_closed=0,
                draft=0,
                needs_attention=0,
                open_age_business_day_sum=9,
                open_age_denominator=3,
            )
        }
    )
    overview = SERVICE.read_portfolio_overview(
        repository,  # type: ignore[arg-type]
        principal_id=PRINCIPAL,
        project_ids=(PROJECT_TOKYO, PROJECT_EAST),
        now=NOW,
    )
    assert [entry.project_id for entry in overview.projects] == [PROJECT_EAST, PROJECT_TOKYO]
    east, tokyo = overview.projects
    assert (east.project_today, east.project_timezone) == (EAST_TODAY, ZONE_EAST)
    assert (tokyo.project_today, tokyo.project_timezone) == (TOKYO_TODAY, ZONE_TOKYO)
    assert east.total_open == 3
    assert east.average_open_age_business_days == 3.0


def test_a_project_the_aggregate_returned_no_group_for_is_counted_as_zero_not_dropped() -> None:
    """ "No Constraints" is a count. It is never an absence from the result."""
    repository = _both_projects(facts={})
    overview = SERVICE.read_portfolio_overview(
        repository,  # type: ignore[arg-type]
        principal_id=PRINCIPAL,
        project_ids=(PROJECT_EAST, PROJECT_TOKYO),
        now=NOW,
    )
    assert len(overview.projects) == 2
    assert all(entry.total_open == 0 for entry in overview.projects)
    assert all(entry.average_open_age_business_days is None for entry in overview.projects)


# --- Principal isolation and the Project set ---------------------------------


def test_every_statement_is_issued_under_the_authenticated_principal() -> None:
    repository = _both_projects(records=(_record("cst_portfolioa1", PROJECT_EAST),))
    _page(repository)
    assert repository.principals
    assert set(repository.principals) == {PRINCIPAL}


def _two_principal_world() -> _PortfolioRepository:
    """One configured Project each, and a row in each, under two Principals.

    Both Projects are configured and both hold rows, so neither answer below can
    come from an empty arrangement. What separates them is who is asking.
    """
    return _PortfolioRepository(
        settings={
            (PRINCIPAL, PROJECT_EAST): _settings(PROJECT_EAST, ZONE_EAST),
            (OTHER_PRINCIPAL, PROJECT_OTHER): _settings(
                PROJECT_OTHER, ZONE_TOKYO, principal_id=OTHER_PRINCIPAL
            ),
        },
        records=(
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfoliod4", PROJECT_OTHER, principal_id=OTHER_PRINCIPAL),
        ),
    )


def test_the_other_principals_project_is_reachable_by_its_own_owner() -> None:
    """The control that makes the next test mean what its name says.

    Without this, an empty answer for `PROJECT_OTHER` would be consistent with
    there being nothing to find. Read under the Principal that owns it, the same
    fake returns the same Project's row — so the emptiness below is isolation
    and not absence.
    """
    page = _page(
        _two_principal_world(),
        project_ids=(PROJECT_OTHER,),
        principal_id=OTHER_PRINCIPAL,
    )
    assert [entry.project_id for entry in page.entries] == [PROJECT_OTHER]


def test_another_principals_project_identifier_yields_nothing_rather_than_an_error() -> None:
    """A foreign Project is unconfigured *to this Principal*, so it is absent.

    The settings read is partition-scoped, so a Project this Principal does not
    own has no calendar here and contributes no rows and no counts — the same
    answer an owned Project with no Constraint settings gives. Nothing about the
    result distinguishes the two, which is the nondisclosure posture the plane
    requires (decision PC-CM-D02).

    The violation is representable: the fake's row read is scoped by the spec's
    Project set alone, so a service that stopped narrowing the requested set to
    the settings this Principal owns would put `PROJECT_OTHER` in the spec and
    return its row. Both assertions would fail.
    """
    repository = _two_principal_world()
    page = _page(repository, project_ids=(PROJECT_EAST, PROJECT_OTHER))
    assert [entry.project_id for entry in page.entries] == [PROJECT_EAST]
    (spec,) = repository.specs
    assert spec.project_ids == (PROJECT_EAST,)


def test_another_principals_project_is_absent_from_the_portfolio_overview_too() -> None:
    """The same boundary on the read that reports a position rather than rows."""
    repository = _two_principal_world()
    overview = SERVICE.read_portfolio_overview(
        repository,  # type: ignore[arg-type]
        principal_id=PRINCIPAL,
        project_ids=(PROJECT_EAST, PROJECT_OTHER),
        now=NOW,
    )
    assert [entry.project_id for entry in overview.projects] == [PROJECT_EAST]


def test_the_service_narrows_the_project_set_and_never_widens_it() -> None:
    repository = _both_projects(records=(_record("cst_portfolioa1", PROJECT_EAST),))
    _page(repository, project_ids=(PROJECT_EAST,))
    (requested,) = repository.settings_requests
    assert requested == (PROJECT_EAST,)
    (spec,) = repository.specs
    assert spec.project_ids == (PROJECT_EAST,)
    assert repository.category_requests == [(PROJECT_EAST,)]
    assert repository.sync_requests[0][0] == (PROJECT_EAST,)


def test_a_repeated_project_identifier_is_read_once() -> None:
    repository = _both_projects()
    _page(repository, project_ids=(PROJECT_EAST, PROJECT_EAST, PROJECT_TOKYO))
    assert repository.settings_requests == [(PROJECT_EAST, PROJECT_TOKYO)]


def test_an_empty_portfolio_returns_an_empty_page_and_asks_the_repository_nothing() -> None:
    repository = _both_projects()
    page = _page(repository, project_ids=())
    assert page.entries == ()
    assert page.is_truncated is False
    assert page.next_cursor is None
    assert repository.principals == []


def test_an_empty_portfolio_overview_is_empty_and_asks_the_repository_nothing() -> None:
    repository = _both_projects()
    overview = SERVICE.read_portfolio_overview(
        repository,  # type: ignore[arg-type]
        principal_id=PRINCIPAL,
        project_ids=(),
        now=NOW,
    )
    assert overview.projects == ()
    assert overview.as_of == NOW
    assert repository.principals == []


# --- The unconfigured Project ------------------------------------------------


def test_a_project_with_no_constraint_calendar_contributes_nothing_and_does_not_fail_the_read() -> (
    None
):
    """The WP06 answer to a genuine silence in the plan.

    An exact-Project read of an unconfigured Project fails closed, because the
    caller named that Project and configuring it is the action they can take. A
    portfolio read names every Project the Principal owns, and refusing the
    whole surface because one of them was never enrolled would make the surface
    unusable for exactly the Principals it exists for — while naming no Project,
    so it would not even say which one to fix. An unconfigured Project therefore
    has no defensible Overdue boundary, yields no rows and no counts, and is
    silently absent.
    """
    repository = _PortfolioRepository(
        settings={
            (PRINCIPAL, PROJECT_EAST): _settings(PROJECT_EAST, ZONE_EAST),
            (PRINCIPAL, PROJECT_TOKYO): _settings(PROJECT_TOKYO, ZONE_TOKYO),
        },
        records=(
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfolioc3", PROJECT_UNSET),
        ),
    )
    page = _page(repository, project_ids=(PROJECT_EAST, PROJECT_TOKYO, PROJECT_UNSET))
    assert [entry.project_id for entry in page.entries] == [PROJECT_EAST]
    (spec,) = repository.specs
    assert PROJECT_UNSET not in spec.project_ids


def test_a_portfolio_of_only_unconfigured_projects_is_an_empty_page_and_not_a_refusal() -> None:
    repository = _PortfolioRepository(settings={})
    page = _page(repository, project_ids=(PROJECT_EAST, PROJECT_TOKYO))
    assert page.entries == ()
    assert page.next_cursor is None
    assert repository.specs == []


def test_a_configured_project_whose_stored_timezone_is_unknown_still_fails_the_read_closed() -> (
    None
):
    """Unconfigured and misconfigured are different, and only one of them relaxes.

    A Project with a stored zone name `zoneinfo` does not know *is* enrolled;
    its calendar is broken rather than absent, and substituting one would count
    Overdue against a day nobody chose. It stays the same `UnavailableError` the
    exact-Project read gives, reachable by the same fix.
    """
    repository = _PortfolioRepository(
        settings={(PRINCIPAL, PROJECT_EAST): _settings(PROJECT_EAST, "Mars/Olympus_Mons")}
    )
    with pytest.raises(UnavailableError):
        _page(repository, project_ids=(PROJECT_EAST,))
    assert repository.specs == []


# --- Paging, sorting and grouping across Projects ----------------------------


def test_a_portfolio_page_is_bounded_by_the_requested_limit_and_fetches_exactly_one_more() -> None:
    repository = _both_projects(
        records=tuple(
            _record(f"cst_portfolio{ordinal:02d}", PROJECT_EAST) for ordinal in range(10, 30)
        )
    )
    page = _page(repository, query=ConstraintListQuery(limit=5))
    (spec,) = repository.specs
    assert spec.fetch_limit == 6
    assert len(page.entries) == 5
    assert page.is_truncated is True
    assert page.next_cursor is not None


def test_a_page_that_fits_is_not_truncated_and_issues_no_cursor() -> None:
    repository = _both_projects(records=(_record("cst_portfolioa1", PROJECT_EAST),))
    page = _page(repository, query=ConstraintListQuery(limit=5))
    assert page.is_truncated is False
    assert page.next_cursor is None


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_a_portfolio_page_limit_outside_its_bounds_is_refused_where_the_request_is_built(
    limit: int,
) -> None:
    with pytest.raises(ConstraintQueryError):
        ConstraintListQuery(limit=limit)


def test_the_page_keeps_the_order_the_single_statement_returned_across_projects() -> None:
    """Ordering is the statement's. The service never re-sorts a fetched list."""
    repository = _both_projects(
        records=(
            _record("cst_portfoliob2", PROJECT_TOKYO),
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfolioc3", PROJECT_TOKYO),
        )
    )
    page = _page(repository)
    assert [entry.constraint_id for entry in page.entries] == [
        "cst_portfoliob2",
        "cst_portfolioa1",
        "cst_portfolioc3",
    ]


def test_group_keys_are_assigned_from_each_rows_own_projects_categories() -> None:
    """A Category grouping spans Projects without a Category leaking between them."""
    repository = _both_projects(
        records=(
            _record("cst_portfolioa1", PROJECT_EAST, category_id=CATEGORY_EAST),
            _record("cst_portfoliob2", PROJECT_TOKYO, category_id=CATEGORY_TOKYO),
        ),
        categories=(
            _category(CATEGORY_EAST, PROJECT_EAST, "AAA"),
            _category(CATEGORY_TOKYO, PROJECT_TOKYO, "BBB"),
        ),
    )
    page = _page(repository, query=ConstraintListQuery(grouping=ConstraintGrouping.CATEGORY))
    by_project = {entry.project_id: entry for entry in page.entries}
    assert by_project[PROJECT_EAST].group_keys == (CATEGORY_EAST,)
    assert by_project[PROJECT_TOKYO].group_keys == (CATEGORY_TOKYO,)
    assert by_project[PROJECT_EAST].category is not None
    assert by_project[PROJECT_EAST].category.prefix == "AAA"
    assert by_project[PROJECT_TOKYO].category is not None
    assert by_project[PROJECT_TOKYO].category.prefix == "BBB"


def test_the_pages_parties_sync_facts_and_categories_are_each_asked_for_once() -> None:
    """One bulk question per family for the whole page, whatever it spans."""
    repository = _both_projects(
        records=(
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfoliob2", PROJECT_TOKYO),
        )
    )
    _page(repository)
    assert len(repository.sync_requests) == 1
    assert len(repository.category_requests) == 1
    assert len(repository.settings_requests) == 1
    projects, constraints = repository.sync_requests[0]
    assert projects == (PROJECT_EAST, PROJECT_TOKYO)
    assert constraints == ("cst_portfolioa1", "cst_portfoliob2")


# --- Cursor binding ----------------------------------------------------------


def _issued_cursor(repository: _PortfolioRepository) -> str:
    page = _page(repository, query=ConstraintListQuery(limit=1))
    assert page.next_cursor is not None
    return page.next_cursor


def _two_rows() -> _PortfolioRepository:
    return _both_projects(
        records=(
            _record("cst_portfolioa1", PROJECT_EAST),
            _record("cst_portfoliob2", PROJECT_TOKYO),
        )
    )


def test_a_portfolio_cursor_is_bound_to_the_project_set_it_was_issued_over() -> None:
    token = _issued_cursor(_two_rows())
    decoded = ConstraintListCursor.decode(token)
    expected = ConstraintListQuery(limit=1).portfolio_binding(
        principal_id=PRINCIPAL, project_ids=(PROJECT_EAST, PROJECT_TOKYO)
    )
    assert decoded.binding == expected


def test_a_portfolio_cursor_cannot_be_replayed_against_a_different_project_set() -> None:
    token = _issued_cursor(_two_rows())
    with pytest.raises(ConflictError):
        _page(
            _two_rows(),
            project_ids=(PROJECT_EAST,),
            query=ConstraintListQuery(limit=1, cursor=token),
        )


def test_a_portfolio_cursor_cannot_be_replayed_against_an_exact_project_request() -> None:
    """The two scopes bind differently, so neither token validates as the other."""
    token = _issued_cursor(_two_rows())
    decoded = ConstraintListCursor.decode(token)
    exact = ConstraintListQuery(limit=1).binding(principal_id=PRINCIPAL, project_id=PROJECT_EAST)
    assert decoded.binding != exact
    single = ConstraintListQuery(limit=1).binding(principal_id=PRINCIPAL, project_id=PROJECT_TOKYO)
    assert decoded.binding != single


def test_an_exact_project_cursor_cannot_be_replayed_against_a_portfolio_request() -> None:
    foreign = ConstraintListCursor(
        binding=ConstraintListQuery(limit=1).binding(
            principal_id=PRINCIPAL, project_id=PROJECT_EAST
        ),
        sort_key=(),
        constraint_id="cst_portfolioa1",
    ).encode()
    with pytest.raises(ConflictError):
        _page(_two_rows(), query=ConstraintListQuery(limit=1, cursor=foreign))


def test_a_portfolio_cursor_cannot_be_replayed_under_another_principal() -> None:
    token = _issued_cursor(_two_rows())
    repository = _two_rows()
    with pytest.raises(ConflictError):
        SERVICE.list_portfolio_constraints(
            repository,  # type: ignore[arg-type]
            principal_id=OTHER_PRINCIPAL,
            project_ids=(PROJECT_EAST, PROJECT_TOKYO),
            query=ConstraintListQuery(limit=1, cursor=token),
            now=NOW,
        )


def test_a_portfolio_cursor_cannot_be_replayed_after_the_search_term_changes() -> None:
    token = _issued_cursor(_two_rows())
    with pytest.raises(ConflictError):
        _page(
            _two_rows(),
            query=ConstraintListQuery(limit=1, cursor=token, search_text="switchgear"),
        )


def test_the_project_set_is_the_only_thing_that_moves_between_two_otherwise_equal_bindings() -> (
    None
):
    """A digest is a function of the set's members, not of how they were listed."""
    query = ConstraintListQuery()
    one = query.portfolio_binding(principal_id=PRINCIPAL, project_ids=(PROJECT_TOKYO, PROJECT_EAST))
    two = query.portfolio_binding(
        principal_id=PRINCIPAL, project_ids=(PROJECT_EAST, PROJECT_TOKYO, PROJECT_EAST)
    )
    assert one == two
    three = query.portfolio_binding(principal_id=PRINCIPAL, project_ids=(PROJECT_EAST,))
    assert one != three


def test_an_unreadable_portfolio_cursor_is_an_invalid_request_and_not_a_silent_restart() -> None:
    repository = _two_rows()
    with pytest.raises(InvalidRequestError):
        _page(repository, query=ConstraintListQuery(cursor="!!!not base64!!!"))
    assert repository.specs == []


def test_a_rejected_portfolio_cursor_is_refused_before_any_row_is_read() -> None:
    """A refusal costs no statement, so a bad token cannot be used to probe cost."""
    token = _issued_cursor(_two_rows())
    repository = _two_rows()
    with pytest.raises(ConflictError):
        _page(
            repository,
            project_ids=(PROJECT_EAST,),
            query=ConstraintListQuery(limit=1, cursor=token),
        )
    assert repository.specs == []
    assert repository.settings_requests == []


def test_an_over_length_portfolio_cursor_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(ConstraintCursorError):
        ConstraintListQuery(cursor="a" * 4096)
