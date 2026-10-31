"""CPM Workbench S5b-2: the 7 Schedule commands' strict inputs (FAST).

Worker and capabilities contract sections 3.5.1 and 3.11 (R2 sections 9.1 and
30): the import names exactly the contract fields and nothing that could carry a
path, locator, filename, URL, body, Principal or scope; it requires exactly one
of a Series id and name, an exact source version and an explicit role, with a
baseline kind exactly on a baseline; and every list read bounds its page size,
cursor, filters and date ranges. Built through the generic adapter builder
(`adapters.normalization`), so an unknown key is `invalid_request` exactly as a
transport would answer it. Every value is synthetic.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    SCHEDULE_CHANGE_KIND_VALUES,
    ImportSchedulePublication,
    ListScheduleActivities,
    ListScheduleChanges,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
    ReadSchedulePublication,
)
from my_pa.application.errors import ApplicationError, InvalidRequestError, SafeDetail
from my_pa.domain.schedule import (
    ScheduleBaselineKind,
    SchedulePublicationRole,
)
from my_pa.domain.schedule.compare import ScheduleChangeKind

IMPORT: Final = "schedule_publications.import"

_IMPORT_FIELDS: Final = frozenset(
    {
        "project_id",
        "series_id",
        "series_name",
        "enrollment_id",
        "source_object_id",
        "source_version_id",
        "publication_role",
        "baseline_kind",
        "expected_data_date",
        "supersedes_publication_id",
        "idempotency_key",
    }
)


def _payload(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    payload: dict[str, Any] = {
        "project_id": "prj_commands0001",
        "series_name": "Synthetic Master Schedule",
        "enrollment_id": "enr_commands0001",
        "source_object_id": "obj_commands0001",
        "source_version_id": "ver_commands0001",
        "publication_role": "update",
        "idempotency_key": "synthetic-import-0001",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not ...}


def _document(payload: dict[str, Any], capability: str = IMPORT) -> dict[str, Any]:
    purpose = "schedule_import" if capability == IMPORT else "schedule_read"
    return {
        "request_id": "req-commands-0001",
        "purpose": purpose,
        "principal_id": "prn_commands0001",
        "requested_at": "2026-10-31T12:00:00Z",
        "payload": payload,
    }


def _build(payload: dict[str, Any], capability: str = IMPORT) -> Any:  # noqa: ANN401
    return normalize(capability, _document(payload, capability))[1]


def _refused(payload: dict[str, Any], capability: str = IMPORT) -> ApplicationError:
    with pytest.raises(InvalidRequestError) as refused:
        _build(payload, capability)
    return refused.value


def test_import_accepts_exactly_the_contract_fields() -> None:
    assert {item.name for item in fields(ImportSchedulePublication)} == _IMPORT_FIELDS
    command = _build(
        _payload(
            expected_data_date="2026-05-04",
            supersedes_publication_id="spub_commands0001",
        )
    )
    assert isinstance(command, ImportSchedulePublication)
    request = command.import_request()
    assert request.series_name is not None
    assert request.series_name.name == "Synthetic Master Schedule"
    assert request.publication_role is SchedulePublicationRole.UPDATE
    assert str(request.expected_data_date) == "2026-05-04"
    # A Series name is normalized (R2 section 10.1), never stored as typed.
    spaced = _build(_payload(series_name="  Synthetic   Master\tSchedule "))
    assert spaced.import_request().series_name.name == "Synthetic Master Schedule"


@pytest.mark.parametrize(
    "key",
    [
        "path",
        "file_path",
        "locator",
        "native_locator",
        "filename",
        "url",
        "uri",
        "bytes",
        "content",
        "body",
        "data",
        "principal_id",
        "scope",
        "source_id",
        "operation_id",
    ],
)
def test_import_refuses_path_locator_filename_and_body_fields(key: str) -> None:
    error = _refused(_payload(**{key: "synthetic"}))
    # The unknown key is refused by the builder itself, naming nothing.
    assert error.safe_details == ()


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"series_name": ...}, SafeDetail.SERIES_ID),
        ({"series_id": "sser_commands0001"}, SafeDetail.SERIES_ID),
        ({"series_name": "   "}, SafeDetail.SERIES_NAME),
        ({"series_name": "x" * 1_001}, SafeDetail.SERIES_NAME),
        ({"series_name": "Bad​Name"}, SafeDetail.SERIES_NAME),
        ({"series_name": ..., "series_id": "prj_commands0001"}, SafeDetail.SERIES_ID),
    ],
    ids=["neither", "both", "blank_name", "long_name", "format_character", "wrong_id_kind"],
)
def test_import_requires_exactly_one_of_series_id_and_name(
    overrides: dict[str, Any], detail: SafeDetail
) -> None:
    assert _refused(_payload(**overrides)).safe_details == (detail,)
    by_id = _build(_payload(series_name=..., series_id="sser_commands0001"))
    assert by_id.import_request().series_id == "sser_commands0001"


def test_import_requires_a_source_version() -> None:
    # Missing entirely: the constructor's own refusal (no default exists).
    assert _refused(_payload(source_version_id=...)).safe_details == ()
    required = {item.name for item in fields(ImportSchedulePublication) if item.default is MISSING}
    assert "source_version_id" in required
    for bad in (None, "", "obj_commands0001", "ver_x"):
        assert _refused(_payload(source_version_id=bad)).safe_details == (
            SafeDetail.SOURCE_VERSION_ID,
        )


def test_role_is_required_and_baseline_kind_follows_it() -> None:
    required = {item.name for item in fields(ImportSchedulePublication) if item.default is MISSING}
    # Section 3.11: no default role -- a missing role is refused, never `update`.
    assert "publication_role" in required
    assert _refused(_payload(publication_role=...)).safe_details == ()
    assert _refused(_payload(publication_role=None)).safe_details == (SafeDetail.PUBLICATION_ROLE,)
    refused = _refused(_payload(publication_role="current"))
    assert refused.safe_details == (SafeDetail.PUBLICATION_ROLE,)
    assert refused.allowed_values[SafeDetail.PUBLICATION_ROLE] == tuple(
        role.value for role in SchedulePublicationRole
    )
    # A baseline names its kind; nothing else may.
    assert _refused(_payload(publication_role="baseline")).safe_details == (
        SafeDetail.BASELINE_KIND,
    )
    assert _refused(_payload(baseline_kind="working")).safe_details == (SafeDetail.BASELINE_KIND,)
    assert _refused(
        _payload(publication_role="reference", baseline_kind="contract")
    ).safe_details == (SafeDetail.BASELINE_KIND,)
    for kind in ScheduleBaselineKind:
        command = _build(_payload(publication_role="baseline", baseline_kind=kind.value))
        assert command.import_request().baseline_kind is kind
    for role in ("update", "reference"):
        assert _build(_payload(publication_role=role)).import_request().baseline_kind is None


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"project_id": "sser_commands0001"}, SafeDetail.PROJECT_ID),
        ({"enrollment_id": "obj_commands0001"}, SafeDetail.ENROLLMENT_ID),
        ({"source_object_id": "ver_commands0001"}, SafeDetail.SOURCE_OBJECT_ID),
        ({"expected_data_date": "04-May-26"}, SafeDetail.EXPECTED_DATA_DATE),
        ({"supersedes_publication_id": "sser_commands0001"}, SafeDetail.SUPERSEDES_PUBLICATION_ID),
        ({"idempotency_key": "short"}, SafeDetail.IDEMPOTENCY_KEY),
        ({"idempotency_key": "has space in it"}, SafeDetail.IDEMPOTENCY_KEY),
    ],
)
def test_import_fields_refuse_with_their_own_detail(
    overrides: dict[str, Any], detail: SafeDetail
) -> None:
    assert _refused(_payload(**overrides)).safe_details == (detail,)


# ---- the 6 reads -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        ("schedule_series.list", {"project_id": "prj_commands0001"}),
        ("schedule_publications.list", {"series_id": "sser_commands0001"}),
        ("schedule_activities.list", {"publication_id": "spub_commands0001"}),
        ("schedule_activities.history", {"schedule_activity_id": "sact_commands0001"}),
        (
            "schedule_changes.list",
            {"from_publication_id": "spub_commands0001", "to_publication_id": "spub_commands0002"},
        ),
    ],
)
def test_list_reads_bound_page_size_and_cursor(capability: str, payload: dict[str, Any]) -> None:
    assert _build(payload, capability).page_size is None
    assert _build({**payload, "page_size": 100}, capability).page_size == 100
    for size in (0, 101, -1, True, "10", 2.0):
        refused = _refused({**payload, "page_size": size}, capability)
        assert refused.safe_details == (SafeDetail.PAGE_SIZE,)
    for cursor in ("", "x" * 513, 5):
        refused = _refused({**payload, "cursor": cursor}, capability)
        assert refused.safe_details == (SafeDetail.CURSOR,)
    assert _refused({**payload, "unknown": 1}, capability).safe_details == ()


def test_publication_read_takes_one_identifier() -> None:
    assert isinstance(
        _build({"publication_id": "spub_commands0001"}, "schedule_publications.read"),
        ReadSchedulePublication,
    )
    assert _refused(
        {"publication_id": "sser_commands0001"}, "schedule_publications.read"
    ).safe_details == (SafeDetail.PUBLICATION_ID,)
    assert {item.name for item in fields(ReadSchedulePublication)} == {"publication_id"}


def test_publication_list_filters_are_closed_vocabularies() -> None:
    capability = "schedule_publications.list"
    base = {"series_id": "sser_commands0001"}
    command = _build({**base, "publication_role": "baseline", "status": "failed"}, capability)
    assert isinstance(command, ListSchedulePublications)
    assert _refused({**base, "publication_role": "current"}, capability).safe_details == (
        SafeDetail.PUBLICATION_ROLE,
    )
    assert _refused({**base, "status": "done"}, capability).safe_details == (SafeDetail.STATUS,)


def test_activity_filters_are_bounded() -> None:
    capability = "schedule_activities.list"
    base = {"publication_id": "spub_commands0001"}
    command = _build(
        {
            **base,
            "row_type": "milestone",
            "hierarchy_prefix": ["Synthetic WBS", "Phase 1"],
            "start_from": "2026-05-01",
            "start_to": "2026-05-01",
            "finish_to": "2026-06-30",
        },
        capability,
    )
    assert isinstance(command, ListScheduleActivities)
    assert command.hierarchy_prefix == ("Synthetic WBS", "Phase 1")
    for row_type in ("project_summary", "wbs_summary", "ambiguous", "task"):
        assert _refused({**base, "row_type": row_type}, capability).safe_details == (
            SafeDetail.ROW_TYPE,
        )
    for prefix in ([], [""], ["x" * 2_001], ["a"] * 33, "Synthetic WBS", [1]):
        assert _refused({**base, "hierarchy_prefix": prefix}, capability).safe_details == (
            SafeDetail.HIERARCHY_PREFIX,
        )
    for dates in (
        {"start_from": "2026-05-02", "start_to": "2026-05-01"},
        {"finish_from": "01-May-26"},
        {"finish_to": "2026-02-30"},
    ):
        assert _refused({**base, **dates}, capability).safe_details == (SafeDetail.DATE_RANGE,)


def test_history_takes_one_stable_activity() -> None:
    capability = "schedule_activities.history"
    assert isinstance(
        _build({"schedule_activity_id": "sact_commands0001"}, capability),
        ReadScheduleActivityHistory,
    )
    assert _refused({"schedule_activity_id": "srow_commands0001"}, capability).safe_details == (
        SafeDetail.SCHEDULE_ACTIVITY_ID,
    )


def test_changes_name_both_publications_and_a_closed_kind() -> None:
    capability = "schedule_changes.list"
    pair = {"from_publication_id": "spub_commands0001", "to_publication_id": "spub_commands0002"}
    command = _build({**pair, "change_kind": "reintroduced"}, capability)
    assert isinstance(command, ListScheduleChanges)
    assert _refused({"from_publication_id": "spub_commands0001"}, capability).safe_details == ()
    assert _refused(
        {**pair, "to_publication_id": "sser_commands0002"}, capability
    ).safe_details == (SafeDetail.TO_PUBLICATION_ID,)
    assert _refused(
        {**pair, "from_publication_id": "sser_commands0002"}, capability
    ).safe_details == (SafeDetail.FROM_PUBLICATION_ID,)
    refused = _refused({**pair, "change_kind": "moved"}, capability)
    assert refused.safe_details == (SafeDetail.CHANGE_KIND,)
    assert refused.allowed_values[SafeDetail.CHANGE_KIND] == SCHEDULE_CHANGE_KIND_VALUES


def test_change_kind_values_are_the_delta_vocabulary() -> None:
    """The command's closed set is read off `ScheduleChangeKind`, never restated."""
    assert tuple(kind.value for kind in ScheduleChangeKind) == SCHEDULE_CHANGE_KIND_VALUES
    schema = ListScheduleChanges.mcp_payload_properties["change_kind"]
    assert schema == {"type": "string", "enum": list(SCHEDULE_CHANGE_KIND_VALUES)}


def test_series_list_takes_a_project() -> None:
    assert isinstance(
        _build({"project_id": "prj_commands0001"}, "schedule_series.list"), ListScheduleSeries
    )
    assert _refused({"project_id": "sser_commands0001"}, "schedule_series.list").safe_details == (
        SafeDetail.PROJECT_ID,
    )
