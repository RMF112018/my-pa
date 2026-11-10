"""WP04 catalog domain: plane, filters, bound keyset cursor, search-text projection."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from my_pa.domain.reports.catalog import (
    DEFAULT_LIFECYCLE_STATES,
    LIST_ORDER,
    MAX_CATALOG_CURSOR_CHARACTERS,
    SEARCH_ORDER,
    AssociationFilter,
    CatalogCursor,
    CatalogCursorError,
    CatalogFilters,
    CatalogOperation,
    ReportPlane,
    binding_digest,
    extract_search_text,
    validate_catalog_page_size,
)
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    MAX_SEARCH_TEXT_CHARACTERS,
    AssociationTargetKind,
    LifecycleState,
)
from my_pa.domain.search.query import SearchQuery

PRINCIPAL = "prn_abcdefgh1234"
OTHER_PRINCIPAL = "prn_zyxwvuts9876"
REPORT = "grpt_abcdefgh1234"
LEGACY = "rpt_abcdefgh1234"
WHEN = datetime(2026, 11, 5, 12, 30, 15, 123456, tzinfo=UTC)
CREATOR = "gcrt_" + "0123456789abcdef" * 2 + "01234567"


def test_plane_and_order_vocabulary() -> None:
    assert [plane.value for plane in ReportPlane] == ["intelligence", "standalone", "all"]
    assert [op.value for op in CatalogOperation] == ["list", "search"]
    assert LIST_ORDER == "sort_time_desc_then_report_id_desc"
    assert SEARCH_ORDER == "rank_desc_then_sort_time_desc_then_report_id_desc"
    assert MAX_SEARCH_TEXT_CHARACTERS == 65536


# ---- filters ---------------------------------------------------------------------


def test_default_filters_are_active_only_and_canonical() -> None:
    filters = CatalogFilters()
    assert filters.lifecycle_states == DEFAULT_LIFECYCLE_STATES == {LifecycleState.ACTIVE}
    assert filters.canonical() == {
        "type": None,
        "topics": None,
        "tags": None,
        "associated_with": None,
        "lifecycle_states": ["active"],
        "created_from": None,
        "created_to": None,
        "report_date_from": None,
        "report_date_to": None,
        "created_by": None,
    }


def test_filters_normalize_and_sort_for_the_binding() -> None:
    filters = CatalogFilters(
        report_type="weekly_brief",
        topics=("zeta", "Cafe\u0301"),
        tags=("b", "a"),
        associated_with=AssociationFilter("project", "prj_abcdefgh1234"),  # type: ignore[arg-type]
        lifecycle_states=["trashed", "active"],  # type: ignore[arg-type]
        created_from=datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=2))),
        created_to=datetime(2026, 2, 1, tzinfo=UTC),
        report_date_from=date(2026, 1, 1),
        report_date_to=date(2026, 1, 1),
        created_by=CREATOR,
    )
    assert filters.topics == ("zeta", "Café")
    assert filters.associated_with is not None
    assert filters.associated_with.target_kind is AssociationTargetKind.PROJECT
    assert filters.canonical() == {
        "type": "weekly_brief",
        "topics": ["Café", "zeta"],
        "tags": ["a", "b"],
        "associated_with": {"target_kind": "project", "target_ref": "prj_abcdefgh1234"},
        "lifecycle_states": ["active", "trashed"],
        "created_from": "2026-01-01T07:00:00.000000Z",
        "created_to": "2026-02-01T00:00:00.000000Z",
        "report_date_from": "2026-01-01",
        "report_date_to": "2026-01-01",
        "created_by": CREATOR,
    }


@pytest.mark.parametrize(
    ("kwargs", "field", "code"),
    [
        ({"report_type": "Bad"}, "type", "pattern"),
        ({"report_type": "my_pa_internal"}, "type", "reserved"),
        ({"report_type": 3}, "type", "type"),
        ({"topics": []}, "topics", "too_short"),
        ({"topics": "one"}, "topics", "type"),
        ({"topics": ["a", "A"]}, "topics", "duplicate"),
        ({"topics": [str(n) for n in range(25)]}, "topics", "too_many"),
        ({"topics": ["x" * 65]}, "topics", "too_long"),
        ({"tags": []}, "tags", "too_short"),
        ({"tags": ["a\tb"]}, "tags", "control_character"),
        ({"associated_with": {"target_kind": "project"}}, "associated_with", "type"),
        ({"lifecycle_states": []}, "lifecycle_states", "too_short"),
        ({"lifecycle_states": "active"}, "lifecycle_states", "type"),
        ({"lifecycle_states": ["active", "active"]}, "lifecycle_states", "duplicate"),
        ({"lifecycle_states": ["gone"]}, "lifecycle_states", "unknown"),
        ({"lifecycle_states": [1]}, "lifecycle_states", "type"),
        ({"created_from": datetime(2026, 1, 1)}, "created_from", "naive"),
        ({"created_to": "2026-01-01T00:00:00Z"}, "created_to", "type"),
        ({"created_from": WHEN, "created_to": WHEN}, "created_range", "order"),
        ({"report_date_from": WHEN}, "report_date_from", "type"),
        ({"report_date_to": "2026-01-01"}, "report_date_to", "type"),
        (
            {"report_date_from": date(2026, 1, 2), "report_date_to": date(2026, 1, 1)},
            "report_date_range",
            "order",
        ),
        # WP05 A5: a creator pseudonym, exactly.
        ({"created_by": 7}, "created_by", "type"),
        ({"created_by": ""}, "created_by", "pattern"),
        ({"created_by": "gcrt_" + "A" * 40}, "created_by", "pattern"),
        ({"created_by": "gcrt_" + "a" * 39}, "created_by", "pattern"),
        ({"created_by": "gcrt_" + "a" * 40 + "\n"}, "created_by", "pattern"),
        ({"created_by": "prn_" + "a" * 40}, "created_by", "pattern"),
    ],
)
def test_filter_refusals_name_the_field_and_rule(
    kwargs: dict[str, Any], field: str, code: str
) -> None:
    with pytest.raises(ReportValidationError) as raised:
        CatalogFilters(**kwargs)
    assert (raised.value.field, raised.value.code) == (field, code)


@pytest.mark.parametrize(
    ("kind", "ref", "code"),
    [
        ("planet", "x", "target_kind"),
        (7, "x", "type"),
        ("project", "", "too_short"),
        ("project", "x" * 513, "too_long"),
        ("entity", "a\nb", "control_character"),
        ("entity", 5, "type"),
    ],
)
def test_association_filter_uses_the_publish_ref_shape(
    kind: object, ref: object, code: str
) -> None:
    with pytest.raises(ReportValidationError) as raised:
        AssociationFilter(kind, ref)  # type: ignore[arg-type]
    assert (raised.value.field, raised.value.code) == ("associated_with", code)


def test_page_size_is_refused_not_clamped() -> None:
    assert validate_catalog_page_size(1) == 1
    assert validate_catalog_page_size(100) == 100
    for bad, code in ((0, "out_of_range"), (101, "out_of_range"), (True, "type"), ("5", "type")):
        with pytest.raises(ReportValidationError) as raised:
            validate_catalog_page_size(bad)
        assert (raised.value.field, raised.value.code) == ("page_size", code)


# ---- binding ---------------------------------------------------------------------


def _binding(**overrides: object) -> str:
    arguments: dict[str, Any] = {
        "operation": CatalogOperation.SEARCH,
        "principal_id": PRINCIPAL,
        "plane": ReportPlane.STANDALONE,
        "filters": CatalogFilters(),
        "query": SearchQuery("quarterly risk"),
        "page_size": 20,
    }
    arguments.update(overrides)
    return binding_digest(**arguments)


def test_binding_is_deterministic_and_canonical_over_filter_order() -> None:
    assert _binding() == _binding()
    one = CatalogFilters(topics=("a", "b"), lifecycle_states=["archived", "active"])  # type: ignore[arg-type]
    two = CatalogFilters(topics=("b", "a"), lifecycle_states=["active", "archived"])  # type: ignore[arg-type]
    assert _binding(filters=one) == _binding(filters=two)
    # The query enters as its fingerprint: whitespace-equal queries bind alike.
    assert _binding(query=SearchQuery("quarterly   risk")) == _binding()


@pytest.mark.parametrize(
    "override",
    [
        {"principal_id": OTHER_PRINCIPAL},
        {"plane": ReportPlane.ALL},
        {"page_size": 21},
        {"query": SearchQuery("quarterly risks")},
        {"operation": CatalogOperation.LIST, "query": None},
        {"filters": CatalogFilters(report_type="brief")},
        {"filters": CatalogFilters(topics=("a",))},
        {"filters": CatalogFilters(tags=("a",))},
        {"filters": CatalogFilters(associated_with=AssociationFilter("entity", "x"))},  # type: ignore[arg-type]
        {"filters": CatalogFilters(lifecycle_states=["active", "archived"])},  # type: ignore[arg-type]
        {"filters": CatalogFilters(created_from=WHEN)},
        {"filters": CatalogFilters(created_to=WHEN)},
        {"filters": CatalogFilters(report_date_from=date(2026, 1, 1))},
        {"filters": CatalogFilters(report_date_to=date(2026, 1, 1))},
        {"filters": CatalogFilters(created_by=CREATOR)},
    ],
)
def test_binding_changes_with_each_bound_input(override: dict[str, Any]) -> None:
    assert _binding(**override) != _binding()


def test_binding_refuses_a_mismatched_operation_and_query() -> None:
    with pytest.raises(ReportValidationError):
        _binding(query=None)
    with pytest.raises(ReportValidationError):
        _binding(operation=CatalogOperation.LIST)
    with pytest.raises(ReportValidationError):
        _binding(page_size=0)
    with pytest.raises(ValueError, match="prefix"):
        _binding(principal_id="usr_abcdefgh1234")


# ---- the cursor ------------------------------------------------------------------


def _decode(token: object, **overrides: object) -> CatalogCursor:
    arguments: dict[str, Any] = {
        "operation": CatalogOperation.SEARCH,
        "plane": ReportPlane.STANDALONE,
        "binding": _binding(),
    }
    arguments.update(overrides)
    return CatalogCursor.decode(token, **arguments)


def _token(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_search_and_list_cursors_round_trip() -> None:
    search = CatalogCursor(binding=_binding(), sort_time=WHEN, report_id=REPORT, rank=4321)
    token = search.encode()
    assert "=" not in token and len(token) <= MAX_CATALOG_CURSOR_CHARACTERS
    assert json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) == {
        "b": _binding(),
        "i": REPORT,
        "r": 4321,
        "t": "2026-11-05T12:30:15.123456Z",
    }
    assert _decode(token) == search
    assert search.operation is CatalogOperation.SEARCH

    binding = _binding(operation=CatalogOperation.LIST, query=None, plane=ReportPlane.ALL)
    listed = CatalogCursor(binding=binding, sort_time=WHEN, report_id=LEGACY)
    decoded = _decode(
        listed.encode(), operation=CatalogOperation.LIST, plane=ReportPlane.ALL, binding=binding
    )
    assert decoded == listed and decoded.rank is None
    assert decoded.operation is CatalogOperation.LIST


def test_a_non_utc_sort_time_is_kept_as_its_utc_instant() -> None:
    local = WHEN.astimezone(timezone(timedelta(hours=-5)))
    cursor = CatalogCursor(binding=_binding(), sort_time=local, report_id=REPORT, rank=0)
    assert cursor.sort_time == WHEN and cursor.sort_time.tzinfo is UTC
    assert _decode(cursor.encode()) == cursor


def _good() -> dict[str, object]:
    return {"b": _binding(), "i": REPORT, "r": 7, "t": "2026-11-05T12:30:15.123456Z"}


_MALFORMED_PAYLOADS: list[tuple[str, object]] = [
    ("not an object", [1, 2]),
    ("missing rank on search", {k: v for k, v in _good().items() if k != "r"}),
    ("extra key", {**_good(), "x": 1}),
    ("binding not a digest", {**_good(), "b": "ab" * 31}),
    ("binding upper case", {**_good(), "b": _binding().upper()}),
    ("binding not a string", {**_good(), "b": 5}),
    ("time without micros", {**_good(), "t": "2026-11-05T12:30:15Z"}),
    ("time with offset", {**_good(), "t": "2026-11-05T12:30:15.123456+00:00"}),
    ("time impossible", {**_good(), "t": "2026-13-05T12:30:15.123456Z"}),
    ("time not a string", {**_good(), "t": 1700000000}),
    ("id of another kind", {**_good(), "i": "grver_abcdefgh1234"}),
    ("legacy id outside all", {**_good(), "i": LEGACY}),
    ("id malformed", {**_good(), "i": "grpt_x"}),
    ("id not a string", {**_good(), "i": 12}),
    ("rank negative", {**_good(), "r": -1}),
    ("rank float", {**_good(), "r": 1.0}),
    ("rank bool", {**_good(), "r": True}),
    ("rank string", {**_good(), "r": "7"}),
    ("rank beyond bigint", {**_good(), "r": 2**63}),
]


@pytest.mark.parametrize(
    ("label", "payload"), _MALFORMED_PAYLOADS, ids=[x[0] for x in _MALFORMED_PAYLOADS]
)
def test_every_malformed_payload_is_one_refusal(label: str, payload: object) -> None:
    del label
    with pytest.raises(CatalogCursorError) as raised:
        _decode(_token(payload))
    assert (raised.value.field, raised.value.code) == ("cursor", "invalid")


def test_a_list_cursor_with_a_rank_is_refused() -> None:
    binding = _binding(operation=CatalogOperation.LIST, query=None)
    with pytest.raises(CatalogCursorError):
        _decode(_token({**_good(), "b": binding}), operation=CatalogOperation.LIST, binding=binding)


def test_the_good_payload_decodes() -> None:
    assert _decode(_token(_good())).rank == 7


@pytest.mark.parametrize(
    "token",
    [
        None,
        42,
        "",
        "a" * (MAX_CATALOG_CURSOR_CHARACTERS + 1),
        "abc=",
        "ab+c",
        "ab c",
        "éabc",
        "a",  # not a whole base64 group
        base64.urlsafe_b64encode(b"\xff\xfe").decode().rstrip("="),  # not UTF-8
        base64.urlsafe_b64encode(b"{not json").decode().rstrip("="),
    ],
)
def test_every_unreadable_token_is_one_refusal(token: object) -> None:
    with pytest.raises(CatalogCursorError) as raised:
        _decode(token)
    assert str(raised.value) == "cursor: invalid"
    assert raised.value.__context__ is None


def test_non_canonical_spellings_of_a_valid_position_are_refused() -> None:
    good = CatalogCursor(binding=_binding(), sort_time=WHEN, report_id=REPORT, rank=7)
    token = good.encode()
    payload = json.dumps(_good(), sort_keys=True, separators=(",", ":"))
    spaced = json.dumps(_good(), sort_keys=True)
    unsorted = json.dumps(dict(reversed(list(_good().items()))), separators=(",", ":"))
    duplicated = payload[:-1] + ',"r":7}'
    for raw in (spaced, unsorted, duplicated):
        variant = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        assert variant != token
        with pytest.raises(CatalogCursorError):
            _decode(variant)
    # Padding kept.
    with pytest.raises(CatalogCursorError):
        _decode(base64.urlsafe_b64encode(payload.encode()).decode())
    # Non-zero trailing bits in the last group (same bytes, other spelling).
    if len(token) % 4:
        last = token[-1]
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        bumped = alphabet[alphabet.index(last) ^ 1]  # flips a padding bit only
        with pytest.raises(CatalogCursorError):
            _decode(token[:-1] + bumped)


def test_a_cursor_from_another_request_is_refused() -> None:
    token = CatalogCursor(binding=_binding(), sort_time=WHEN, report_id=REPORT, rank=1).encode()
    for binding in (
        _binding(principal_id=OTHER_PRINCIPAL),
        _binding(plane=ReportPlane.ALL),
        _binding(page_size=50),
        _binding(filters=CatalogFilters(tags=("x",))),
    ):
        with pytest.raises(CatalogCursorError):
            _decode(token, binding=binding)
    # A search token presented to a list request fails on its key set.
    with pytest.raises(CatalogCursorError):
        _decode(token, operation=CatalogOperation.LIST)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"binding": "nope"},
        {"sort_time": datetime(2026, 1, 1)},
        {"sort_time": "2026-01-01"},
        {"report_id": "grver_abcdefgh1234"},
        {"rank": -1},
        {"rank": 1.5},
        {"rank": True},
    ],
)
def test_constructing_a_bad_cursor_is_refused(kwargs: dict[str, Any]) -> None:
    good = CatalogCursor(binding=_binding(), sort_time=WHEN, report_id=REPORT, rank=1)
    with pytest.raises(CatalogCursorError):
        replace(good, **kwargs)


# ---- the search projection --------------------------------------------------------


def test_textual_content_projects_its_body() -> None:
    for content_format in ("markdown", "text"):
        content = validate_content({"format": content_format, "body": "# Title\n\nbody text"})
        assert extract_search_text(content) == "# Title\n\nbody text"


def test_json_projects_string_values_only_in_sorted_key_depth_first_order() -> None:
    content = validate_content(
        {
            "format": "json",
            "data": {
                "zulu": "last",
                "alpha": ["first", 1, 2.5, True, None, {"secret_key": "nested"}],
                "mike": {"b": "bee", "a": "ay", "n": 99},
                "keyonly": None,
            },
        }
    )
    assert extract_search_text(content) == "first\nnested\nay\nbee\nlast"
    text = extract_search_text(content)
    for excluded in ("zulu", "alpha", "mike", "secret_key", "keyonly", "99", "2.5", "true", "null"):
        assert excluded not in text.split("\n"), excluded
    assert "secret_key" not in text and "zulu" not in text


def test_json_without_strings_projects_nothing() -> None:
    assert extract_search_text(validate_content({"format": "json", "data": [1, 2, False]})) == ""
    assert extract_search_text(validate_content({"format": "json", "data": "solo"})) == "solo"


def test_mixed_projects_body_then_data_strings() -> None:
    content = validate_content(
        {"format": "mixed", "body": "Body line", "data": {"k2": "two", "k1": ["one", 3]}}
    )
    assert extract_search_text(content) == "Body line\none\ntwo"
    empty = validate_content({"format": "mixed", "body": "Only", "data": {}})
    assert extract_search_text(empty) == "Only\n"


def test_projection_is_cut_at_the_bound_in_code_points() -> None:
    # A 4-byte code point: the cut counts code points, never bytes.
    body = "\U0001f600" * (MAX_SEARCH_TEXT_CHARACTERS + 10)
    text = extract_search_text(validate_content({"format": "text", "body": body}))
    assert len(text) == MAX_SEARCH_TEXT_CHARACTERS
    exact = "a" * MAX_SEARCH_TEXT_CHARACTERS
    assert extract_search_text(validate_content({"format": "text", "body": exact})) == exact
    data = ["x" * 40000, "y" * 40000]
    cut = extract_search_text(validate_content({"format": "json", "data": data}))
    assert cut == ("x" * 40000 + "\n" + "y" * 40000)[:MAX_SEARCH_TEXT_CHARACTERS]


def test_projection_never_reads_the_encoded_or_original_bytes() -> None:
    content = validate_content({"format": "markdown", "body": "plain words here"})
    encoded = base64.b64encode(content.decoded).decode()
    poisoned = replace(content, decoded=encoded.encode())
    assert extract_search_text(poisoned) == "plain words here"
    assert encoded not in extract_search_text(content)


def test_projection_refuses_a_non_content() -> None:
    with pytest.raises(ReportValidationError) as raised:
        extract_search_text({"format": "text", "body": "x"})  # type: ignore[arg-type]
    assert (raised.value.field, raised.value.code) == ("content", "type")
