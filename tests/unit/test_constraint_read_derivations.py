"""Unit tests for the PC-CM-IMP-WP03 Constraint read-plane derivations.

Pure and fast: no database, no adapter, no clock. Every date-dependent case
fixes the UTC instant and the Project timezone explicitly, because the whole
point of the read plane's calendar rule is that nothing about a derived answer
depends on where or when the server happens to be running.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from my_pa.application.constraints import (
    ConstraintReadService,
    _sort_key,
)
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    UnavailableError,
)
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.business_time import (
    business_days_elapsed,
    due_soon_through,
    is_due_soon,
    is_overdue,
    project_today,
)
from my_pa.domain.project_controls.category import ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintFieldKey,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    in_my_court,
)
from my_pa.domain.project_controls.party import PartyKind
from my_pa.domain.project_controls.read_models import (
    MAX_CURSOR_CHARACTERS,
    MAX_LIST_LIMIT,
    MAX_SEARCH_CHARACTERS,
    MIN_SEARCH_CHARACTERS,
    ConstraintCategoryRow,
    ConstraintCursorError,
    ConstraintListCursor,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintPartyRow,
    ConstraintQueryError,
    ConstraintSort,
    ConstraintSyncStateView,
    PersistedConstraintRecord,
    attention_for,
    legacy_missing_fields,
    party_refs_of,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings

S = ConstraintLifecycleState

PRINCIPAL = "prn_readplane01"
PROJECT = "prj_readplane01"
CONSTRAINT = "cst_readplane01"
OTHER_CONSTRAINT = "cst_readplane02"
ENTITY = "ent_readplane01"

# 2026-09-07 is a Monday.
MON = date(2026, 9, 7)
TUE = MON + timedelta(days=1)
FRI = MON + timedelta(days=4)
SAT = MON + timedelta(days=5)
PREVIOUS_FRIDAY = MON - timedelta(days=3)
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _record(
    *,
    lifecycle_state: ConstraintLifecycleState = S.IDENTIFIED,
    record_quality: ConstraintRecordQuality = ConstraintRecordQuality.NORMAL,
    origin: ConstraintOrigin = ConstraintOrigin.PRODUCT,
    **overrides: object,
) -> PersistedConstraintRecord:
    """A persisted read record with the partition columns already filled in."""
    fields: dict[str, object] = {
        "constraint_id": CONSTRAINT,
        "principal_id": PRINCIPAL,
        "lifecycle_state": lifecycle_state,
        "record_quality": record_quality,
        "origin": origin,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        "project_id": PROJECT,
    }
    fields.update(overrides)
    return PersistedConstraintRecord(**fields)  # type: ignore[arg-type]


def _party(
    kind: PartyKind,
    *,
    role: str = "bic",
    ordinal: int = 0,
    entity_id: str | None = None,
    display_label: str | None = None,
    original_label: str | None = None,
) -> ConstraintPartyRow:
    return ConstraintPartyRow(
        constraint_id=CONSTRAINT,
        role=role,
        ordinal=ordinal,
        party_kind=kind,
        entity_id=entity_id,
        display_label=display_label,
        original_label=original_label,
    )


# --- T7: In My Court ---------------------------------------------------------


def test_an_active_constraint_whose_bic_is_the_principal_is_in_my_court() -> None:
    bic = party_refs_of((_party(PartyKind.PRINCIPAL),), "bic")
    assert in_my_court(S.IDENTIFIED, bic, principal_bound_entity_ids=frozenset()) is True


@pytest.mark.parametrize("state", [S.CLOSED, S.VOID, S.DRAFT])
def test_a_terminal_or_draft_constraint_is_never_in_my_court_even_with_a_principal_bic(
    state: ConstraintLifecycleState,
) -> None:
    bic = party_refs_of((_party(PartyKind.PRINCIPAL),), "bic")
    assert in_my_court(state, bic, principal_bound_entity_ids=frozenset()) is False


def test_an_unresolved_party_never_establishes_in_my_court_however_it_is_worded() -> None:
    bic = party_refs_of(
        (_party(PartyKind.UNRESOLVED, display_label="Me, the owning principal"),), "bic"
    )
    assert in_my_court(S.IDENTIFIED, bic, principal_bound_entity_ids=frozenset()) is False


def test_an_entity_party_is_not_in_my_court_without_a_proven_principal_binding() -> None:
    bic = party_refs_of((_party(PartyKind.ENTITY, entity_id=ENTITY, display_label="Bobby"),), "bic")
    assert in_my_court(S.IDENTIFIED, bic, principal_bound_entity_ids=frozenset()) is False


def test_the_read_plane_passes_an_empty_bound_entity_set_because_no_binding_exists() -> None:
    bic = party_refs_of((_party(PartyKind.ENTITY, entity_id=ENTITY),), "bic")
    proven = in_my_court(S.IDENTIFIED, bic, principal_bound_entity_ids=frozenset({ENTITY}))
    unproven = in_my_court(S.IDENTIFIED, bic, principal_bound_entity_ids=frozenset())
    assert proven is True
    assert unproven is False


def test_party_projection_drops_a_principal_partys_stored_label() -> None:
    refs = party_refs_of((_party(PartyKind.PRINCIPAL, display_label="Bobby"),), "bic")
    assert refs[0].kind is PartyKind.PRINCIPAL
    assert refs[0].label is None


def test_party_projection_keeps_stored_ordinal_order_and_separates_the_two_roles() -> None:
    rows = (
        _party(PartyKind.UNRESOLVED, role="responsible", ordinal=0, display_label="Trade"),
        _party(PartyKind.ENTITY, ordinal=1, entity_id=ENTITY, display_label="Second"),
        _party(PartyKind.PRINCIPAL, ordinal=0),
    )
    bic = party_refs_of(rows, "bic")
    responsible = party_refs_of(rows, "responsible")
    assert [ref.kind for ref in bic] == [PartyKind.PRINCIPAL, PartyKind.ENTITY]
    assert [ref.kind for ref in responsible] == [PartyKind.UNRESOLVED]


# --- T8: project_today across zones ------------------------------------------


def test_project_today_is_the_projects_calendar_date_and_not_the_servers() -> None:
    # 03:30 UTC is still the previous day in New York and already the same day
    # in Sydney, so one instant is two Project dates.
    instant = datetime(2026, 9, 8, 3, 30, tzinfo=UTC)
    assert project_today(instant, "America/New_York") == date(2026, 9, 7)
    assert project_today(instant, "Australia/Sydney") == date(2026, 9, 8)


def test_project_today_crosses_at_local_midnight_and_not_at_utc_midnight() -> None:
    just_before = datetime(2026, 9, 8, 3, 59, tzinfo=UTC)
    just_after = datetime(2026, 9, 8, 4, 1, tzinfo=UTC)
    assert project_today(just_before, "America/New_York") == date(2026, 9, 7)
    assert project_today(just_after, "America/New_York") == date(2026, 9, 8)


# --- T9: the calendar fails closed -------------------------------------------


class _SettingsOnlyRepository:
    """Enough of the read port to resolve — or fail to resolve — a Project calendar."""

    def __init__(self, settings: ConstraintProjectSettings | None) -> None:
        self._settings = settings
        self.overview_calls = 0

    def get_project_settings(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        return self._settings

    def overview_facts(self, *args: object, **kwargs: object) -> object:
        self.overview_calls += 1
        raise AssertionError("the overview must not be counted without a project calendar")


def _settings(timezone_name: str) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=PRINCIPAL,
        project_id=PROJECT,
        timezone_name=timezone_name,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_an_unconfigured_project_timezone_makes_the_overview_unavailable_not_empty() -> None:
    repository = _SettingsOnlyRepository(None)
    with pytest.raises(UnavailableError):
        ConstraintReadService().read_overview(
            repository,  # type: ignore[arg-type]
            principal_id=PRINCIPAL,
            project_id=PROJECT,
            now=NOW,
        )
    assert repository.overview_calls == 0


def test_an_unknown_iana_timezone_makes_the_overview_unavailable_not_empty() -> None:
    repository = _SettingsOnlyRepository(_settings("Mars/Olympus_Mons"))
    with pytest.raises(UnavailableError):
        ConstraintReadService().read_overview(
            repository,  # type: ignore[arg-type]
            principal_id=PRINCIPAL,
            project_id=PROJECT,
            now=NOW,
        )
    assert repository.overview_calls == 0


def test_no_read_method_accepts_a_caller_supplied_timezone() -> None:
    import inspect

    service = ConstraintReadService()
    for name in (
        "list_categories",
        "read_category",
        "list_constraints",
        "read_constraint",
        "read_history",
        "read_overview",
    ):
        parameters = inspect.signature(getattr(service, name)).parameters
        assert not any("time" in parameter and "zone" in parameter for parameter in parameters)


# --- T10: business-day arithmetic --------------------------------------------


def test_business_days_elapsed_counts_both_ends_of_a_working_week() -> None:
    assert business_days_elapsed(MON, FRI) == 5


def test_business_days_elapsed_skips_the_weekend_between_two_weekdays() -> None:
    assert business_days_elapsed(FRI, MON + timedelta(days=7)) == 2


def test_a_real_weekday_holiday_is_still_counted_because_v1_has_no_calendar() -> None:
    # 2026-12-25 is a Friday and a public holiday in most of the world.
    christmas = date(2026, 12, 25)
    assert christmas.weekday() == 4
    assert business_days_elapsed(christmas, christmas) == 1


def test_days_elapsed_is_unavailable_when_a_legacy_row_has_no_date_identified() -> None:
    record = _record(
        record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
        origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
        date_identified=None,
    )
    assert record.date_identified is None
    assert ConstraintFieldKey.DATE_IDENTIFIED in legacy_missing_fields(record)


# --- T11: Overdue and Due Soon -----------------------------------------------


def test_a_due_date_of_yesterday_is_overdue_and_not_due_soon() -> None:
    yesterday = MON - timedelta(days=1)
    assert is_overdue(S.IDENTIFIED, yesterday, MON) is True
    assert is_due_soon(S.IDENTIFIED, yesterday, MON) is False


def test_a_due_date_of_today_is_due_soon_and_not_overdue() -> None:
    assert is_due_soon(S.IDENTIFIED, MON, MON) is True
    assert is_overdue(S.IDENTIFIED, MON, MON) is False


def test_a_due_date_of_the_next_business_day_is_due_soon() -> None:
    assert is_due_soon(S.IDENTIFIED, TUE, MON) is True


def test_a_due_date_on_the_exact_seventh_business_day_is_still_due_soon() -> None:
    boundary = due_soon_through(MON)
    assert boundary == date(2026, 9, 16)
    assert is_due_soon(S.IDENTIFIED, boundary, MON) is True


def test_a_due_date_one_day_past_the_boundary_is_not_due_soon() -> None:
    beyond = due_soon_through(MON) + timedelta(days=1)
    assert is_due_soon(S.IDENTIFIED, beyond, MON) is False
    assert is_overdue(S.IDENTIFIED, beyond, MON) is False


def test_a_weekend_due_date_inside_the_window_is_due_soon_because_the_window_is_dates() -> None:
    assert is_due_soon(S.IDENTIFIED, SAT, MON) is True


def test_a_due_date_of_the_previous_friday_is_overdue_and_never_due_soon() -> None:
    assert is_overdue(S.IDENTIFIED, PREVIOUS_FRIDAY, MON) is True
    assert is_due_soon(S.IDENTIFIED, PREVIOUS_FRIDAY, MON) is False


@pytest.mark.parametrize("state", [S.CLOSED, S.VOID, S.DRAFT])
def test_a_terminal_or_draft_constraint_is_neither_overdue_nor_due_soon(
    state: ConstraintLifecycleState,
) -> None:
    past = MON - timedelta(days=30)
    assert is_overdue(state, past, MON) is False
    assert is_due_soon(state, MON, MON) is False


def test_a_constraint_with_no_due_date_is_neither_overdue_nor_due_soon() -> None:
    assert is_overdue(S.IDENTIFIED, None, MON) is False
    assert is_due_soon(S.IDENTIFIED, None, MON) is False


@pytest.mark.parametrize("offset", list(range(-10, 15)))
def test_overdue_and_due_soon_are_mutually_exclusive_on_every_nearby_date(offset: int) -> None:
    due = MON + timedelta(days=offset)
    assert not (is_overdue(S.IDENTIFIED, due, MON) and is_due_soon(S.IDENTIFIED, due, MON))


# --- Attention and missing fields --------------------------------------------


def test_a_normal_record_reports_no_missing_fields_however_incomplete_the_draft_is() -> None:
    draft = _record(lifecycle_state=S.DRAFT, project_id=None, description=None)
    attention = attention_for(draft, has_open_conflict=False)
    assert attention.missing_fields == ()
    assert attention.reasons == ()
    assert attention.needs_attention is False


def test_a_legacy_incomplete_record_names_exactly_the_columns_that_are_null() -> None:
    record = _record(
        lifecycle_state=S.CLOSED,
        record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
        origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
        category_id=None,
        constraint_code=None,
        description="a workbook row",
        date_identified=None,
        due_date=None,
    )
    attention = attention_for(record, has_open_conflict=False)
    assert attention.missing_fields == (
        ConstraintFieldKey.CATEGORY_ID,
        ConstraintFieldKey.CONSTRAINT_CODE,
        ConstraintFieldKey.DATE_IDENTIFIED,
        ConstraintFieldKey.DUE_DATE,
        ConstraintFieldKey.BIC,
    )
    assert attention.needs_attention is True


def test_an_open_sync_conflict_needs_attention_on_a_record_missing_nothing() -> None:
    attention = attention_for(_record(), has_open_conflict=True)
    assert attention.missing_fields == ()
    assert attention.needs_attention is True


def test_a_data_quality_exception_is_never_emitted() -> None:
    reasons = attention_for(_record(), has_open_conflict=True).reasons
    assert all(reason.value != "data_quality_exception" for reason in reasons)


def test_the_sync_state_vocabulary_is_exactly_the_four_derivable_names() -> None:
    assert {state.value for state in ConstraintSyncStateView} == {
        "never_synced",
        "in_sync",
        "db_export_pending",
        "conflict",
    }


# --- The list cursor ----------------------------------------------------------


def _binding() -> str:
    return ConstraintListQuery().binding(principal_id=PRINCIPAL, project_id=PROJECT)


def test_a_list_cursor_round_trips_through_its_opaque_token() -> None:
    cursor = ConstraintListCursor(
        binding=_binding(), sort_key=(3, "007", None), constraint_id=CONSTRAINT
    )
    decoded = ConstraintListCursor.decode(cursor.encode())
    assert decoded == cursor


def test_an_encoded_cursor_carries_no_padding_and_is_url_safe() -> None:
    token = ConstraintListCursor(
        binding=_binding(), sort_key=("2026-09-07",), constraint_id=CONSTRAINT
    ).encode()
    assert "=" not in token
    assert "+" not in token and "/" not in token


@pytest.mark.parametrize(
    "token",
    [
        "",
        "!!!not base64!!!",
        "bm90IGpzb24",
        "WyJhIiwiYiJd",
        "eyJiIjoxfQ",
        "x" * (MAX_CURSOR_CHARACTERS + 1),
    ],
)
def test_every_unreadable_cursor_fails_with_the_same_flat_message(token: str) -> None:
    with pytest.raises(ConstraintCursorError) as raised:
        ConstraintListCursor.decode(token)
    assert str(raised.value) == "the cursor is not readable"
    assert raised.value.code == "constraint_cursor_unreadable"


def test_a_cursor_decode_failure_leaves_no_rejected_value_in_the_exception_context() -> None:
    with pytest.raises(ConstraintCursorError) as raised:
        ConstraintListCursor.decode("!!!not base64!!!")
    assert raised.value.__context__ is None


def test_a_cursor_naming_something_that_is_not_a_constraint_is_refused() -> None:
    # Constructed directly, the identifier check speaks for itself; reached
    # through `decode` the same rejection becomes the one flat cursor message.
    with pytest.raises(InvalidIdentifierError):
        ConstraintListCursor(binding=_binding(), sort_key=(), constraint_id="prj_readplane01")
    token = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"b": _binding(), "i": "prj_readplane01", "k": [], "v": 1},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(ConstraintCursorError) as raised:
        ConstraintListCursor.decode(token)
    assert str(raised.value) == "the cursor is not readable"


def test_a_cursor_binding_must_be_a_sha256_digest() -> None:
    with pytest.raises(ConstraintCursorError):
        ConstraintListCursor(binding="not-a-digest", sort_key=(), constraint_id=CONSTRAINT)


def test_a_cursor_is_bound_to_the_request_that_issued_it() -> None:
    cursor = ConstraintListCursor(binding=_binding(), sort_key=(), constraint_id=CONSTRAINT)
    other = ConstraintListQuery(sort=ConstraintSort.DUE_DATE).binding(
        principal_id=PRINCIPAL, project_id=PROJECT
    )
    assert cursor.is_bound_to(_binding()) is True
    assert cursor.is_bound_to(other) is False


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"principal_id": PRINCIPAL}, {"principal_id": "prn_readplane02"}),
        ({"project_id": PROJECT}, {"project_id": "prj_readplane02"}),
    ],
)
def test_a_binding_changes_with_the_partition_the_page_was_read_under(
    first: dict[str, str], second: dict[str, str]
) -> None:
    query = ConstraintListQuery()
    arguments = {"principal_id": PRINCIPAL, "project_id": PROJECT}
    assert query.binding(**{**arguments, **first}) != query.binding(**{**arguments, **second})


@pytest.mark.parametrize(
    "query",
    [
        ConstraintListQuery(scope=ConstraintListScope.CLOSED),
        ConstraintListQuery(sort=ConstraintSort.UPDATED_AT),
        ConstraintListQuery(limit=25),
        ConstraintListQuery(overdue=True),
        ConstraintListQuery(search_text="anchor bolt"),
        ConstraintListQuery(category_ids=frozenset({"ccat_readplane01"})),
    ],
)
def test_a_binding_changes_with_anything_that_gives_the_page_meaning(
    query: ConstraintListQuery,
) -> None:
    baseline = ConstraintListQuery().binding(principal_id=PRINCIPAL, project_id=PROJECT)
    assert query.binding(principal_id=PRINCIPAL, project_id=PROJECT) != baseline


def test_a_binding_carries_the_search_fingerprint_and_never_the_search_text() -> None:
    query = ConstraintListQuery(search_text="anchor bolt")
    binding = query.binding(principal_id=PRINCIPAL, project_id=PROJECT)
    assert "anchor" not in binding
    assert query.search_fingerprint != ""
    assert ConstraintListQuery().search_fingerprint == ""


# --- The list request ---------------------------------------------------------


def test_a_list_query_defaults_to_the_open_register_grouped_by_category() -> None:
    query = ConstraintListQuery()
    assert query.scope is ConstraintListScope.OPEN
    assert query.sort is ConstraintSort.CODE
    assert query.direction.value == "asc"
    assert query.grouping.value == "category"
    assert query.limit == 50


@pytest.mark.parametrize("limit", [0, -1, MAX_LIST_LIMIT + 1])
def test_a_page_limit_outside_its_bounds_is_refused(limit: int) -> None:
    with pytest.raises(ConstraintQueryError) as raised:
        ConstraintListQuery(limit=limit)
    assert raised.value.code == "constraint_list_limit_out_of_range"


def test_a_one_character_search_term_is_refused_rather_than_served() -> None:
    with pytest.raises(ConstraintQueryError) as raised:
        ConstraintListQuery(search_text="a")
    assert raised.value.code == "constraint_search_too_short"
    assert MIN_SEARCH_CHARACTERS == 2


def test_a_search_term_past_its_ceiling_is_refused() -> None:
    with pytest.raises(ConstraintQueryError) as raised:
        ConstraintListQuery(search_text="a" * (MAX_SEARCH_CHARACTERS + 1))
    assert raised.value.code == "constraint_search_too_long"


def test_a_blank_search_term_is_no_search_rather_than_an_error() -> None:
    assert ConstraintListQuery(search_text="   ").search_text is None


def test_a_search_term_is_stored_normalised_and_never_echoed_in_the_refusal() -> None:
    assert ConstraintListQuery(search_text="  anchor bolt  ").search_text == "anchor bolt"
    with pytest.raises(ConstraintQueryError) as raised:
        ConstraintListQuery(search_text="secret")
    assert "secret" not in str(raised.value)


def test_a_party_reference_that_is_neither_closed_token_nor_entity_identity_is_refused() -> None:
    with pytest.raises(ConstraintQueryError) as raised:
        ConstraintListQuery(bic_party_refs=frozenset({"Bobby Fetting"}))
    assert raised.value.code == "constraint_party_ref_unknown"
    assert "Bobby" not in str(raised.value)


def test_the_two_closed_party_tokens_and_an_entity_identity_are_accepted() -> None:
    query = ConstraintListQuery(
        bic_party_refs=frozenset({"principal", "unresolved", ENTITY}),
        responsible_party_refs=frozenset({"principal"}),
    )
    assert query.bic_party_refs == frozenset({"principal", "unresolved", ENTITY})


def test_an_over_length_cursor_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(ConstraintCursorError):
        ConstraintListQuery(cursor="x" * (MAX_CURSOR_CHARACTERS + 1))


# --- Service-level cursor handling -------------------------------------------


class _ListRepository(_SettingsOnlyRepository):
    """A calendar plus an empty Register, enough to reach the cursor decision."""

    def list_constraints(self, *args: object, **kwargs: object) -> tuple[object, ...]:
        raise AssertionError("a rejected cursor must not reach the statement")


def test_an_unreadable_cursor_is_an_invalid_request_and_not_a_silent_restart() -> None:
    repository = _ListRepository(_settings("America/New_York"))
    with pytest.raises(InvalidRequestError):
        ConstraintReadService().list_constraints(
            repository,  # type: ignore[arg-type]
            principal_id=PRINCIPAL,
            project_id=PROJECT,
            query=ConstraintListQuery(cursor="!!!not base64!!!"),
            now=NOW,
        )


def test_a_cursor_issued_for_another_request_is_a_conflict_and_not_a_silent_restart() -> None:
    repository = _ListRepository(_settings("America/New_York"))
    foreign = ConstraintListCursor(
        binding=ConstraintListQuery().binding(principal_id="prn_readplane02", project_id=PROJECT),
        sort_key=(),
        constraint_id=OTHER_CONSTRAINT,
    ).encode()
    with pytest.raises(ConflictError):
        ConstraintReadService().list_constraints(
            repository,  # type: ignore[arg-type]
            principal_id=PRINCIPAL,
            project_id=PROJECT,
            query=ConstraintListQuery(cursor=foreign),
            now=NOW,
        )


# --- Keyset anchors ----------------------------------------------------------

CATEGORY_A = "ccat_readplane01"
CATEGORY_B = "ccat_readplane02"


def _category(category_id: str, *, prefix: str, display_order: int) -> ConstraintCategoryRow:
    return ConstraintCategoryRow(
        category_id=category_id,
        project_id=PROJECT,
        prefix=prefix,
        title=prefix + " works",
        description=None,
        display_order=display_order,
        state=ConstraintCategoryState.ACTIVE,
        next_sequence=1,
        issued_count=0,
        version=1,
        prefix_locked_at=None,
    )


CATEGORIES = {
    CATEGORY_A: _category(CATEGORY_A, prefix="2", display_order=0),
    CATEGORY_B: _category(CATEGORY_B, prefix="7", display_order=1),
}


def test_the_code_anchor_carries_the_whole_ordering_key_and_not_just_the_sequence() -> None:
    record = _record(category_id=CATEGORY_A, constraint_code="2.09")
    anchor = _sort_key(record, ConstraintListQuery(sort=ConstraintSort.CODE), CATEGORIES)
    assert anchor == (0, 0, "2", 2, "09")


def test_two_categories_sharing_a_sequence_number_produce_different_code_anchors() -> None:
    query = ConstraintListQuery(sort=ConstraintSort.CODE)
    first = _sort_key(_record(category_id=CATEGORY_A, constraint_code="2.03"), query, CATEGORIES)
    second = _sort_key(_record(category_id=CATEGORY_B, constraint_code="7.03"), query, CATEGORIES)
    assert first != second
    assert first[3:] == second[3:]  # the sequence half alone would have collided


def test_the_code_anchor_orders_sequences_by_length_then_text_and_never_as_a_decimal() -> None:
    query = ConstraintListQuery(sort=ConstraintSort.CODE)
    anchors = [
        _sort_key(_record(category_id=CATEGORY_A, constraint_code=code), query, CATEGORIES)
        for code in ("2.01", "2.09", "2.10", "2.100")
    ]
    assert anchors == sorted(anchors)


def test_a_row_with_no_code_or_no_category_anchors_as_an_absent_key_sorting_last() -> None:
    query = ConstraintListQuery(sort=ConstraintSort.CODE)
    draft = _sort_key(_record(category_id=None, constraint_code=None), query, CATEGORIES)
    orphan = _sort_key(
        _record(category_id="ccat_readplane99", constraint_code="9.01"), query, CATEGORIES
    )
    present = _sort_key(_record(category_id=CATEGORY_A, constraint_code="2.01"), query, CATEGORIES)
    assert draft == orphan == (1, None, None, None, None)
    assert present < draft


def test_the_absent_key_discriminator_cannot_be_collided_with_by_real_data() -> None:
    query = ConstraintListQuery(sort=ConstraintSort.CODE)
    absent = _sort_key(_record(category_id=None, constraint_code=None), query, CATEGORIES)
    present = _sort_key(_record(category_id=CATEGORY_A, constraint_code="2.01"), query, CATEGORIES)
    assert absent[0] != present[0]


@pytest.mark.parametrize(
    ("sort", "overrides"),
    [
        (ConstraintSort.DATE_IDENTIFIED, {"date_identified": MON}),
        (ConstraintSort.DAYS_ELAPSED, {"date_identified": MON}),
        (ConstraintSort.DUE_DATE, {"due_date": FRI}),
        (ConstraintSort.UPDATED_AT, {}),
    ],
)
def test_every_other_sort_anchors_on_its_own_key_with_a_null_discriminator(
    sort: ConstraintSort, overrides: dict[str, object]
) -> None:
    anchor = _sort_key(_record(**overrides), ConstraintListQuery(sort=sort), CATEGORIES)
    assert len(anchor) == 2
    assert anchor[0] == 0
    assert anchor[1] is not None


@pytest.mark.parametrize(
    "sort", [ConstraintSort.DATE_IDENTIFIED, ConstraintSort.DAYS_ELAPSED, ConstraintSort.DUE_DATE]
)
def test_a_missing_nullable_sort_key_anchors_as_absent_and_sorts_last(
    sort: ConstraintSort,
) -> None:
    query = ConstraintListQuery(sort=sort)
    absent = _sort_key(_record(date_identified=None, due_date=None), query, CATEGORIES)
    present = _sort_key(_record(date_identified=MON, due_date=FRI), query, CATEGORIES)
    assert absent == (1, None)
    assert present < absent


@pytest.mark.parametrize(
    "sort",
    [
        ConstraintSort.CODE,
        ConstraintSort.DATE_IDENTIFIED,
        ConstraintSort.DAYS_ELAPSED,
        ConstraintSort.DUE_DATE,
        ConstraintSort.UPDATED_AT,
    ],
)
def test_every_sorts_anchor_round_trips_through_the_cursor_unchanged(
    sort: ConstraintSort,
) -> None:
    query = ConstraintListQuery(sort=sort)
    record = _record(
        category_id=CATEGORY_A, constraint_code="2.100", date_identified=MON, due_date=FRI
    )
    anchor = _sort_key(record, query, CATEGORIES)
    cursor = ConstraintListCursor(
        binding=query.binding(principal_id=PRINCIPAL, project_id=PROJECT),
        sort_key=anchor,
        constraint_id=record.constraint_id,
    )
    decoded = ConstraintListCursor.decode(cursor.encode())
    assert decoded.sort_key == anchor
    assert decoded.constraint_id == CONSTRAINT
