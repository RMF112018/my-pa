"""Schedule Scenarios S6-3: the 26 plane commands' strict inputs (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 15.5: every
command is a frozen dataclass built by `_BUILDERS` as `Command(**payload)`, so an
unknown or missing key is `invalid_request` with no detail; `__post_init__`
checks types, identifier kinds, lengths and closed sets only and refuses each
field with its own detail; the 3 heavy documents are checked for their JSON
type alone and stay opaque until the handler. Built through the generic adapter
builder, exactly as a transport would. Every value is synthetic.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import CreateScheduleScenarioVersion
from my_pa.application.errors import ApplicationError, InvalidRequestError, SafeDetail
from my_pa.domain.identity.operation import Capability
from tests.schedule_scenario_samples import (
    SCHEDULE_SCENARIO_COMMAND_TYPES,
    scenario_payloads,
)

_SAMPLES: Final = scenario_payloads("cmd")
_KEYED: Final = frozenset(
    capability for capability, payload in _SAMPLES.items() if "idempotency_key" in payload
)
_CLIENT_WRITES: Final = frozenset(
    {
        Capability.SCHEDULE_SCENARIOS_CREATE,
        Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
        Capability.SCHEDULE_CPM_RUNS_CREATE,
        Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD,
        Capability.SCHEDULE_BASELINES_PROPOSE,
        Capability.SCHEDULE_BASELINES_WITHDRAW,
    }
)
_PAGED: Final = tuple(
    capability
    for capability in SCHEDULE_SCENARIO_COMMAND_TYPES
    if "cursor" in SCHEDULE_SCENARIO_COMMAND_TYPES[capability].__dataclass_fields__
)


def _document(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": "req-s63-commands-0001",
        "purpose": "schedule_analysis_read",
        "principal_id": "prn_s63commands01",
        "requested_at": "2026-11-11T12:00:00Z",
        "payload": payload,
    }


def _build(capability: Capability, payload: dict[str, Any]) -> Any:  # noqa: ANN401
    return normalize(capability.value, _document(payload))[1]


def _refused(capability: Capability, payload: dict[str, Any]) -> ApplicationError:
    with pytest.raises(InvalidRequestError) as refused:
        _build(capability, payload)
    return refused.value


def _with(capability: Capability, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    payload = dict(_SAMPLES[capability])
    for name, value in changes.items():
        if value is ...:
            payload.pop(name, None)
        else:
            payload[name] = value
    return payload


@pytest.mark.parametrize("capability", sorted(_SAMPLES), ids=lambda c: c.value)
def test_every_sample_builds_its_command(capability: Capability) -> None:
    built = _build(capability, _SAMPLES[capability])
    assert type(built) is SCHEDULE_SCENARIO_COMMAND_TYPES[capability]
    assert built.capability is capability


@pytest.mark.parametrize("capability", sorted(_SAMPLES), ids=lambda c: c.value)
def test_unknown_key_is_invalid_request(capability: Capability) -> None:
    """Section 15.5: an unknown key is `invalid_request` with no detail (P3-07)."""
    refused = _refused(capability, {**_SAMPLES[capability], "principal_scope": "x"})
    assert refused.safe_details == ()


@pytest.mark.parametrize("capability", sorted(_KEYED), ids=lambda c: c.value)
def test_every_write_requires_a_well_formed_key(capability: Capability) -> None:
    assert _refused(capability, _with(capability, idempotency_key=...)).safe_details == ()
    for bad in ("short", "has space in it", 7, "x" * 129):
        refused = _refused(capability, _with(capability, idempotency_key=bad))
        assert refused.safe_details == (SafeDetail.IDEMPOTENCY_KEY,), bad


@pytest.mark.parametrize("capability", sorted(_CLIENT_WRITES), ids=lambda c: c.value)
def test_client_writes_take_an_intent_and_a_claim(capability: Capability) -> None:
    """S6-3-D16: `client_intent_id` (the Reports pattern) and the boolean claim."""
    built = _build(capability, _with(capability, client_intent_id="intent-1", user_directed=True))
    assert (built.client_intent_id, built.user_directed) == ("intent-1", True)
    for bad in ("-leading", "has space", 3):
        refused = _refused(capability, _with(capability, client_intent_id=bad))
        assert refused.safe_details == (SafeDetail.CLIENT_INTENT_ID,), bad
    refused = _refused(capability, _with(capability, user_directed="yes"))
    assert refused.safe_details == (SafeDetail.USER_DIRECTED,)


@pytest.mark.parametrize(
    "capability",
    sorted(set(_KEYED) - _CLIENT_WRITES),
    ids=lambda c: c.value,
)
def test_operator_writes_take_the_key_only(capability: Capability) -> None:
    fields = SCHEDULE_SCENARIO_COMMAND_TYPES[capability].__dataclass_fields__
    assert "client_intent_id" not in fields and "user_directed" not in fields
    assert _refused(capability, _with(capability, user_directed=False)).safe_details == ()


@pytest.mark.parametrize("capability", _PAGED, ids=lambda c: c.value)
def test_every_list_bounds_its_page_and_cursor(capability: Capability) -> None:
    assert _build(capability, _with(capability, page_size=100)).page_size == 100
    for size in (0, 101, True, "10"):
        refused = _refused(capability, _with(capability, page_size=size))
        assert refused.safe_details == (SafeDetail.PAGE_SIZE,), size
    for cursor in ("", "x" * 513, 5):
        refused = _refused(capability, _with(capability, cursor=cursor))
        assert refused.safe_details == (SafeDetail.CURSOR,), cursor


_CREATE: Final = Capability.SCHEDULE_SCENARIOS_CREATE


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"from_publication_id": ...}, SafeDetail.FROM_PUBLICATION_ID),
        ({"from_version_id": "sscv_cmdscen0001"}, SafeDetail.FROM_PUBLICATION_ID),
        ({"from_publication_id": "sbl_cmdscen0001"}, SafeDetail.FROM_PUBLICATION_ID),
        (
            {"from_publication_id": ..., "from_baseline_id": "spub_cmdscen0001"},
            SafeDetail.FROM_BASELINE_ID,
        ),
        (
            {"from_publication_id": ..., "from_version_id": "sscn_cmdscen0001"},
            SafeDetail.FROM_VERSION_ID,
        ),
        ({"name": " \t "}, SafeDetail.NAME),
        ({"name": "x" * 201}, SafeDetail.NAME),
        ({"name": 5}, SafeDetail.NAME),
        ({"description": "x" * 2001}, SafeDetail.DESCRIPTION),
        ({"label": "baseline"}, SafeDetail.LABEL),
        ({"note": ""}, SafeDetail.NOTE),
        ({"minutes_per_source_unit": ...}, SafeDetail.MINUTES_PER_SOURCE_UNIT),
        ({"minutes_per_source_unit": 0}, SafeDetail.MINUTES_PER_SOURCE_UNIT),
        ({"minutes_per_source_unit": 1441}, SafeDetail.MINUTES_PER_SOURCE_UNIT),
        ({"minutes_per_source_unit": 8.5}, SafeDetail.MINUTES_PER_SOURCE_UNIT),
        ({"calendars": ...}, SafeDetail.CALENDAR),
        ({"calendars": []}, SafeDetail.CALENDAR),
        ({"calendars": {"key": "std"}}, SafeDetail.CALENDAR),
        ({"calendars": [{}] * 33}, SafeDetail.CALENDAR),
        ({"default_calendar": ...}, SafeDetail.CALENDAR),
        ({"data_date_time": "24:00"}, SafeDetail.DATA_DATE_TIME),
        ({"data_date_time": "8:00"}, SafeDetail.DATA_DATE_TIME),
    ],
)
def test_scenario_create_refuses_each_field_with_its_own_detail(
    changes: dict[str, Any], detail: SafeDetail
) -> None:
    assert _refused(_CREATE, _with(_CREATE, **changes)).safe_details == (detail,)


def test_a_fork_takes_no_snapshot_field() -> None:
    fork = {
        "from_publication_id": ...,
        "from_version_id": "sscv_cmdscen0001",
        "minutes_per_source_unit": ...,
        "calendars": ...,
        "default_calendar": ...,
    }
    built = _build(_CREATE, _with(_CREATE, **fork))
    assert built.from_version_id == "sscv_cmdscen0001"
    for extra, detail in (
        ({"minutes_per_source_unit": 480}, SafeDetail.MINUTES_PER_SOURCE_UNIT),
        ({"calendars": [{}]}, SafeDetail.CALENDAR),
        ({"default_calendar": "std"}, SafeDetail.CALENDAR),
        ({"data_date_time": "08:00"}, SafeDetail.DATA_DATE_TIME),
    ):
        refused = _refused(_CREATE, _with(_CREATE, **{**fork, **extra}))
        assert refused.safe_details == (detail,), extra


def test_heavy_documents_stay_opaque_until_the_handler() -> None:
    """Section 15.10: the command checks the JSON type only, never the content."""
    calendars = [{"nothing": "a calendar would hold"}]
    built = _build(_CREATE, _with(_CREATE, calendars=calendars))
    assert built.calendars == calendars
    version = Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE
    ops = [{"op": "no.such.op"}, 7, "not an op"]
    appended = _build(version, _with(version, change_set=ops))
    assert isinstance(appended, CreateScheduleScenarioVersion)
    assert appended.change_set == ops
    output = Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD
    assert _build(output, _with(output, document={"anything": [1, 2]})).document == {
        "anything": [1, 2]
    }


@pytest.mark.parametrize(
    ("capability", "changes", "detail"),
    [
        (
            Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
            {"scenario_id": "sscv_cmdscen0001"},
            SafeDetail.SCENARIO_ID,
        ),
        (
            Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
            {"expected_head_version_no": 0},
            SafeDetail.EXPECTED_VERSION,
        ),
        (
            Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
            {"expected_head_version_no": 500},
            SafeDetail.EXPECTED_VERSION,
        ),
        (Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE, {"label": "x"}, SafeDetail.LABEL),
        (Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE, {"note": 3}, SafeDetail.NOTE),
        (
            Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
            {"change_set": {"op": "x"}},
            SafeDetail.CHANGE_SET,
        ),
        (
            Capability.SCHEDULE_CPM_RUNS_CREATE,
            {"version_id": "scpm_x0000001"},
            SafeDetail.VERSION_ID,
        ),
        (Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD, {"document": []}, SafeDetail.OUTPUT),
        (
            Capability.SCHEDULE_BASELINES_PROPOSE,
            {"publication_id": "sbl_cmdscen0001"},
            SafeDetail.PUBLICATION_ID,
        ),
        (Capability.SCHEDULE_BASELINES_PROPOSE, {"type": "working"}, SafeDetail.BASELINE_TYPE),
        (Capability.SCHEDULE_BASELINES_PROPOSE, {"reason": ""}, SafeDetail.REASON),
        (
            Capability.SCHEDULE_BASELINES_WITHDRAW,
            {"baseline_id": "sbev_cmdscen0001"},
            SafeDetail.BASELINE_ID,
        ),
        (Capability.SCHEDULE_BASELINES_WITHDRAW, {"reason": "x" * 2001}, SafeDetail.REASON),
        (
            Capability.SCHEDULE_BASELINES_APPROVE,
            {"baseline_id": "sbl_cmdscen0001"},
            SafeDetail.BASELINE_ID,
        ),
        (
            Capability.SCHEDULE_BASELINES_APPROVE,
            {"publication_id": ...},
            SafeDetail.BASELINE_ID,
        ),
        (Capability.SCHEDULE_BASELINES_APPROVE, {"type": ...}, SafeDetail.BASELINE_TYPE),
        (
            Capability.SCHEDULE_BASELINES_APPROVE,
            {"approval_reference": "x" * 501},
            SafeDetail.APPROVAL_REFERENCE,
        ),
        (
            Capability.SCHEDULE_BASELINES_APPROVE,
            {"effective_from": "05/04/2026"},
            SafeDetail.EFFECTIVE_FROM,
        ),
        (
            Capability.SCHEDULE_BASELINES_APPROVE,
            {"supersedes_baseline_id": "spub_cmdscen0001"},
            SafeDetail.SUPERSEDES_BASELINE_ID,
        ),
        (Capability.SCHEDULE_BASELINES_REJECT, {"reason": " "}, SafeDetail.REASON),
        (
            Capability.SCHEDULE_BASELINES_REVOKE,
            {"baseline_id": "spub_cmdscen0001"},
            SafeDetail.BASELINE_ID,
        ),
        (
            Capability.SCHEDULE_BASELINES_SET_GOVERNING,
            {"project_id": "sser_cmdscen0001"},
            SafeDetail.PROJECT_ID,
        ),
        (
            Capability.SCHEDULE_BASELINES_SET_GOVERNING,
            {"expected_governing_baseline_id": "spub_cmdscen0001"},
            SafeDetail.GOVERNING,
        ),
        (
            Capability.SCHEDULE_SCENARIOS_LIST,
            {"series_id": "spub_cmdscen0001"},
            SafeDetail.SERIES_ID,
        ),
        (Capability.SCHEDULE_SCENARIOS_READ, {"scenario_id": "x"}, SafeDetail.SCENARIO_ID),
        (Capability.SCHEDULE_CPM_RUNS_READ, {"cpm_run_id": "sscv_x0000001"}, SafeDetail.CPM_RUN_ID),
        (Capability.SCHEDULE_CPM_RUNS_ACTIVITIES, {"critical_only": 1}, SafeDetail.CRITICAL_ONLY),
        (
            Capability.SCHEDULE_SCENARIO_OUTPUTS_READ,
            {"output_id": "sscv_x0000001"},
            SafeDetail.OUTPUT_ID,
        ),
        (Capability.SCHEDULE_SERIES_CURRENT, {"series_id": "prj_x0000001"}, SafeDetail.SERIES_ID),
        (Capability.SCHEDULE_BASELINES_LIST, {"status": "pending"}, SafeDetail.STATUS),
        (Capability.SCHEDULE_BASELINES_GOVERNING, {"as_of": "2026-11-11"}, SafeDetail.AS_OF),
        (
            Capability.SCHEDULE_BASELINES_GOVERNING,
            {"as_of": "2026-11-11T12:00:00"},
            SafeDetail.AS_OF,
        ),
        (
            Capability.SCHEDULE_BASELINES_COMPARE,
            {"to_publication_id": "sbl_x0000001"},
            SafeDetail.TO_PUBLICATION_ID,
        ),
        (Capability.SCHEDULE_BASELINES_COMPARE, {"change_kind": "moved"}, SafeDetail.CHANGE_KIND),
    ],
)
def test_each_field_refusal_names_its_detail(
    capability: Capability, changes: dict[str, Any], detail: SafeDetail
) -> None:
    assert _refused(capability, _with(capability, **changes)).safe_details == (detail,)


def test_set_governing_requires_the_cas_key_even_when_null() -> None:
    governing = Capability.SCHEDULE_BASELINES_SET_GOVERNING
    built = _build(governing, _SAMPLES[governing])
    assert built.expected_governing_baseline_id is None
    assert (
        _refused(governing, _with(governing, expected_governing_baseline_id=...)).safe_details == ()
    )


def test_approve_by_baseline_takes_an_optional_type() -> None:
    approve = Capability.SCHEDULE_BASELINES_APPROVE
    by_id = _with(approve, publication_id=..., type=..., baseline_id="sbl_cmdscen0001")
    assert _build(approve, by_id).type is None
    both = _with(approve, baseline_id="sbl_cmdscen0001")
    assert _refused(approve, both).safe_details == (SafeDetail.BASELINE_ID,)


def test_governing_as_of_is_an_instant_with_an_offset() -> None:
    governing = Capability.SCHEDULE_BASELINES_GOVERNING
    built = _build(governing, _with(governing, as_of="2026-11-11T12:00:00+00:00"))
    assert built.as_of == "2026-11-11T12:00:00+00:00"


def test_the_26_commands_are_the_plane_capabilities() -> None:
    assert len(SCHEDULE_SCENARIO_COMMAND_TYPES) == 26
    assert {command.capability for command in SCHEDULE_SCENARIO_COMMAND_TYPES.values()} == set(
        SCHEDULE_SCENARIO_COMMAND_TYPES
    )
