"""P6 XER S7-4a: the 7 P6 capabilities and the format-aware S5 reads, end to end.

Schedule XER import contract (`docs/architecture/schedule-xer-import-contract.md`)
sections 7.1-7.7, 10.1-10.7 and the S7-4 acceptance D1-D4, D7 and D8 (D5 delta
and D6 scenario snapshot are S7-4b). Every request goes through
`ApplicationService.invoke`, composed as `bootstrap/gateway.py` composes it
(the Schedule plane, the P6 switch, the P6 unit of work, the section 7.7
limits and a real `FilesystemFileWorkspaceStore` under `tmp_path`); each
admitted export is parsed by the real `schedule` worker in the contained child.

`database` tier (`database_clone`). Every export is synthetic
(`tests/fixtures/schedule_p6_xer.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.commands import (
    Command,
    ImportScheduleP6Publication,
    ListScheduleActivities,
    ListScheduleChanges,
    ListScheduleP6Activities,
    ListScheduleP6AvailableFields,
    ListScheduleP6Calendars,
    ListScheduleP6FieldValues,
    ListScheduleP6Relationships,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
    ReadSchedulePublication,
    SetScheduleP6CapturedFields,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.schedule.p6_import import P6AdmissionLimits
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, claim_job
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_p6 import SqlAlchemyScheduleP6UnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.schedule_capability_harness import LIMITS
from tests.fixtures import schedule_p6_xer as xer

pytestmark = pytest.mark.database

P: Final = "prn_sp6caps0001"
Q: Final = "prn_sp6caps0002"
PROJECT: Final = "prj_sp6caps0001"
FOREIGN_PROJECT: Final = "prj_sp6caps0002"
WORKSPACE: Final = "syn"
OWNER: Final = "p6-capabilities-worker"
CLIENT_A: Final = "synthetic-p6-client-a"
CLIENT_B: Final = "synthetic-p6-client-b"
P6_BASIS: Final = ["p6_xer_v1", "p6-field-catalogue-v1"]
P6_NAMES: Final = frozenset(
    {
        Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6,
        Capability.SCHEDULE_P6_FIELDS_AVAILABLE,
        Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED,
        Capability.SCHEDULE_P6_ACTIVITIES_LIST,
        Capability.SCHEDULE_P6_RELATIONSHIPS_LIST,
        Capability.SCHEDULE_P6_CALENDARS_LIST,
        Capability.SCHEDULE_P6_FIELD_VALUES_LIST,
    }
)
EXTRA_KEY: Final = "xer:TASK.syn_extra_field"
LIMITS_7_7: Final = P6AdmissionLimits(
    snapshot_quota_bytes=8 * 1024**3, imports_per_hour=60, imports_per_day=500
)
_KEYS: list[int] = [0]


def _key(tag: str) -> str:
    _KEYS[0] += 1
    return f"p6cap-{tag}-{_KEYS[0]:06d}"


def _project(engine: Engine, principal: str, project: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                "now())"
            ),
            {"j": project, "p": principal},
        )


@dataclass
class World:
    """`ApplicationService` composed with the P6 plane, as the gateway composes it."""

    engine: Engine
    root: Path
    enabled: bool = True
    limits: P6AdmissionLimits = LIMITS_7_7
    services: dict[tuple[bool, P6AdmissionLimits], ApplicationService] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.store = FilesystemFileWorkspaceStore(self.root)
        self.audit = SqlAlchemyAuditSink(self.engine)

    def service(self) -> ApplicationService:
        known = self.services.get((self.enabled, self.limits))
        if known is not None:
            return known

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=self.audit, schedule_enabled=True)

        built = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            schedule_enabled=True,
            schedule_unit_of_work=lambda: SqlAlchemyScheduleUnitOfWork(self.engine),
            schedule_p6_enabled=self.enabled,
            schedule_p6_unit_of_work=lambda: SqlAlchemyScheduleP6UnitOfWork(self.engine),
            schedule_p6_limits=self.limits,
            file_workspace=FileWorkspaceApplication(store=self.store, workspace_id=WORKSPACE),
        )
        self.services[(self.enabled, self.limits)] = built
        return built

    # ---- invoke ---------------------------------------------------------------------

    def invoke(
        self,
        command: Command,
        *,
        principal_id: str = P,
        remote_client: str | None = None,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
    ) -> ResponseEnvelope:
        capability = command.capability
        purpose = sorted(permitted_purposes(capability))[0]
        remote = remote_client is not None
        if remote and grants is None:
            grants = frozenset({(capability, purpose)})
        return self.service().invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=purpose,
                principal_id=principal_id,
                requested_at=datetime.now(UTC),
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.REMOTE_CLIENT if remote else CaptureTransport.LOCAL,
            capability_grants=grants,
            authenticated_client_id=remote_client,
        )

    def ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()
        result = dumped["result"]
        assert isinstance(result, dict)
        return {**result, "__disclosure__": dumped["disclosure"]}

    def refused(self, command: Command, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return str(error["code"]), list(error.get("safe_details") or [])

    # ---- import and parse -------------------------------------------------------------

    def put(self, path: str, data: bytes) -> dict[str, Any]:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {
            "workspace_id": WORKSPACE,
            "path": path,
            "expected_version": self.store.stat(path).version,
            "expected_sha256": hashlib.sha256(data).hexdigest(),
            "format": "p6_xer",
        }

    def import_command(
        self,
        data: bytes,
        *,
        path: str = "exports/schedule.xer",
        **extra: Any,  # noqa: ANN401
    ) -> ImportScheduleP6Publication:
        fields: dict[str, Any] = {
            "project_id": PROJECT,
            "series_name": "Master Schedule",
            "idempotency_key": _key("import"),
            **self.put(path, data),
        }
        fields.update(extra)
        return ImportScheduleP6Publication(**fields)

    def work(self, principal: str = P) -> None:
        with self.engine.begin() as c:
            job = claim_job(
                c, owner=OWNER, lease_seconds=300, principal_id=principal, plane=SCHEDULE_JOBS
            )
        assert job is not None
        process_schedule_publication(self.engine, job, OWNER, p6_enabled=True)

    def publish(self, data: bytes, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
        admitted = self.ok(self.import_command(data, **extra))
        self.work()
        return admitted

    def count(self, table: str) -> int:
        with self.engine.connect() as c:
            return int(c.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one())  # noqa: S608


@pytest.fixture
def w(db_engine: Engine, tmp_path: Path) -> World:
    _project(db_engine, P, PROJECT)
    _project(db_engine, Q, FOREIGN_PROJECT)
    root = tmp_path / "workspace"
    root.mkdir()
    return World(db_engine, root)


def _bytes(model: xer.Model) -> bytes:
    return xer.encode(xer.layout(model).lines)


def _unknown_field_model(note: str = "Synthetic extra") -> xer.Model:
    model = xer.base_model("standard")
    task = model.table("TASK")
    task.fields.append("syn_extra_field")
    for index, row in enumerate(task.rows):
        row["syn_extra_field"] = f"{note} {index}"
    return model


def _udf_bytes() -> bytes:
    return xer.build("udf_all_types").data


def _flat(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


# ---- D1 / 10.2: the switch -----------------------------------------------------------


def test_switch_off_withholds_the_seven_names_and_each_handler_answers_unsupported(
    w: World,
) -> None:
    on = w.service().available_capabilities
    assert on >= P6_NAMES
    w.enabled = False
    off = w.service().available_capabilities
    assert not off & P6_NAMES
    assert on - off == P6_NAMES
    series = "sser_sp6caps0000"
    publication = "spub_sp6caps0000"
    for command in (
        w.import_command(xer.build("minimal_valid").data),
        ListScheduleP6AvailableFields(series_id=series),
        SetScheduleP6CapturedFields(
            series_id=series, field_keys=(), expected_sequence=0, idempotency_key=_key("s")
        ),
        ListScheduleP6Activities(publication_id=publication),
        ListScheduleP6Relationships(publication_id=publication),
        ListScheduleP6Calendars(publication_id=publication),
        ListScheduleP6FieldValues(publication_id=publication),
    ):
        assert w.refused(command) == ("unsupported", []), command.capability
    assert w.count("schedule_publications") == 0


# ---- D8: the S5 reads serve a P6 publication ------------------------------------------


def test_the_s5_reads_serve_a_complete_p6_publication(w: World) -> None:
    admitted = w.publish(xer.build("full_valid").data, path="secret/dir/schedule.xer")
    publication = str(admitted["publication_id"])
    series = str(admitted["series_id"])
    assert admitted["status"] == "queued"
    assert admitted["document"]["size_bytes"] > 0
    read = w.ok(ReadSchedulePublication(publication_id=publication))
    assert read["status"] == "complete"
    assert read["enrollment_id"] is None
    # The publication mapping (D8): the project's data date, the ERMHDR export
    # date, the project name as the title (at most 300 characters).
    assert read["data_date"] == "2030-01-07"
    assert read["run_date"] == "2030-01-08"
    assert read["published_schedule_title"]
    assert read["p6"]["data_date"].startswith("2030-01-07")
    assert read["p6"]["project"]["short_name"] == "SYN-PRJ"
    assert read["p6"]["counts"]["activity"] == read["counts"]["activity"] > 0
    assert read["p6"]["export_version"]
    assert read["__disclosure__"]["trust"]["basis"] == P6_BASIS
    assert read["__disclosure__"]["scope"] == {"source_ids": [], "enrollment_ids": []}
    listed = w.ok(ListSchedulePublications(series_id=series))
    assert [row["publication_id"] for row in listed["publications"]] == [publication]
    series_list = w.ok(ListScheduleSeries(project_id=PROJECT))
    assert series_list["series"][0]["latest_update"]["publication_id"] == publication
    activities = w.ok(ListScheduleActivities(publication_id=publication, page_size=2))
    assert len(activities["activities"]) == 2
    row = activities["activities"][0]
    assert row["source_format"] == "p6_xer"
    assert row["provenance"] == {"record_line": row["row_ordinal"]}
    nxt = activities["__disclosure__"]["truncation"]["next_cursor"]
    second = w.ok(ListScheduleActivities(publication_id=publication, page_size=2, cursor=nxt))
    assert second["activities"][0]["published_activity_id"] != row["published_activity_id"]
    history = w.ok(ReadScheduleActivityHistory(schedule_activity_id=row["schedule_activity_id"]))
    assert [item["publication_id"] for item in history["observations"]] == [publication]
    # D5 is S7-4b: the P6 delta is refused, never computed with the PDF algorithm.
    assert w.refused(
        ListScheduleChanges(from_publication_id=publication, to_publication_id=publication)
    ) == ("unsupported", ["source_format"])
    for answer in (admitted, read, listed, series_list, activities, history):
        flat = _flat(answer)
        # Never served (10.4): the workspace path, the ERMHDR user fields, and a
        # personal field nobody selected.
        assert "secret/dir" not in flat
        assert "SYNUSER" not in flat
        assert "Synthetic User" not in flat
        assert "Synthetic Person" not in flat


def test_a_p6_read_of_another_principals_publication_is_not_found(w: World) -> None:
    publication = str(w.publish(xer.build("minimal_valid").data)["publication_id"])
    for command in (
        ReadSchedulePublication(publication_id=publication),
        ListScheduleP6Activities(publication_id=publication),
        ListScheduleP6Relationships(publication_id=publication),
        ListScheduleP6Calendars(publication_id=publication),
        ListScheduleP6FieldValues(publication_id=publication),
    ):
        code, details = w.refused(command, principal_id=Q)
        assert code == "not_found", command.capability
        assert details == ["publication_id"]


# ---- the 10.5 read shapes ---------------------------------------------------------------


def test_the_p6_row_reads_have_the_contract_shapes(w: World) -> None:
    publication = str(w.publish(xer.build("full_valid").data)["publication_id"])
    activities = w.ok(ListScheduleP6Activities(publication_id=publication, page_size=100))
    first = activities["activities"][0]
    assert set(first) >= {
        "schedule_activity_id",
        "activity_id",
        "name",
        "kind",
        "task_type",
        "status",
        "wbs_path",
        "constraint",
        "constraint2",
        "total_float_hours",
        "fields",
    }
    assert [row["activity_id"] for row in activities["activities"]] == sorted(
        row["activity_id"] for row in activities["activities"]
    )
    assert activities["__disclosure__"]["trust"] == {
        "level": "source_bound_derived",
        "basis": P6_BASIS,
    }
    relationships = w.ok(ListScheduleP6Relationships(publication_id=publication))
    assert relationships["relationships"]
    assert {row["type"] for row in relationships["relationships"]} <= {"FS", "SS", "FF", "SF"}
    calendars = w.ok(ListScheduleP6Calendars(publication_id=publication))
    calendar = calendars["calendars"][0]
    assert len(calendar["week"]) == 7
    assert any(day == [["08:00", "12:00"], ["13:00", "17:00"]] for day in calendar["week"])
    assert all(set(item) == {"date", "intervals"} for item in calendar["exceptions"])
    one = w.ok(
        ListScheduleP6Calendars(
            publication_id=publication, calendar_id=calendar["calendar_id"], page_size=1
        )
    )
    assert len(one["calendars"]) == 1
    assert len(one["calendars"][0]["exceptions"]) <= 1
    flat = _flat(calendars)
    assert "clndr_data" not in flat
    assert w.refused(ListScheduleP6Calendars(publication_id=publication, calendar_id=999_999)) == (
        "not_found",
        ["calendar_id"],
    )


def test_a_read_of_an_unfinished_publication_is_a_status_conflict(w: World) -> None:
    admitted = w.ok(w.import_command(xer.build("minimal_valid").data))
    assert w.refused(ListScheduleP6Activities(publication_id=str(admitted["publication_id"]))) == (
        "conflict",
        ["status"],
    )


def test_a_review_required_publication_is_a_status_conflict_for_every_p6_read(w: World) -> None:
    # Independent review S7-4a: a publication whose run was parsed but whose
    # project identity changed is `review_required`, never served by a P6 read.
    w.publish(xer.build("full_valid").data, path="exports/first.xer")
    model = xer.base_model("full")
    model.table("PROJECT").rows[0].update(
        proj_short_name="SYN-OTHER", guid=xer.guid("SynOtherProject")
    )
    second = str(w.publish(_bytes(model), path="exports/other.xer")["publication_id"])
    assert w.ok(ReadSchedulePublication(publication_id=second))["status"] == "review_required"
    for command in (
        ListScheduleP6Activities(publication_id=second),
        ListScheduleP6Relationships(publication_id=second),
        ListScheduleP6Calendars(publication_id=second),
        ListScheduleP6FieldValues(publication_id=second),
    ):
        assert w.refused(command) == ("conflict", ["status"]), command.capability


def test_a_p6_cursor_continues_only_its_own_request(w: World) -> None:
    # Independent review S7-4a: the offset cursor is bound to the capability,
    # the Principal and every request field but the cursor itself.
    publication = str(w.publish(xer.build("full_valid").data)["publication_id"])
    first = w.ok(ListScheduleP6Activities(publication_id=publication, page_size=1))
    cursor = first["__disclosure__"]["truncation"]["next_cursor"]
    assert cursor is not None
    assert w.ok(ListScheduleP6Activities(publication_id=publication, page_size=1, cursor=cursor))
    for other in (
        ListScheduleP6Activities(
            publication_id=publication, page_size=1, cursor=cursor, fields=("xer:TASK.est_wt",)
        ),
        ListScheduleP6Activities(
            publication_id=publication,
            page_size=1,
            cursor=cursor,
            sort={"field": "xer:TASK.est_wt", "direction": "desc"},
        ),
        ListScheduleP6Activities(publication_id=publication, page_size=2, cursor=cursor),
        ListScheduleP6Relationships(publication_id=publication, page_size=1, cursor=cursor),
    ):
        assert w.refused(other) == ("conflict", ["cursor"]), other
    assert w.refused(
        ListScheduleP6Activities(publication_id=publication, page_size=1, cursor=cursor),
        principal_id=Q,
    ) == ("conflict", ["cursor"])


def test_a_named_calendar_pages_its_exceptions_and_says_when_more_exist(w: World) -> None:
    publication = str(w.publish(xer.build("full_valid").data)["publication_id"])
    listed = w.ok(ListScheduleP6Calendars(publication_id=publication))["calendars"]
    for calendar in listed:
        assert calendar["exceptions_truncated"] is (
            len(calendar["exceptions"]) < calendar["exception_count"]
        )
    (calendar,) = [item for item in listed if item["exception_count"] >= 2]
    seen: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = w.ok(
            ListScheduleP6Calendars(
                publication_id=publication,
                calendar_id=calendar["calendar_id"],
                page_size=1,
                cursor=cursor,
            )
        )
        (one,) = page["calendars"]
        seen.extend(one["exceptions"])
        cursor = page["__disclosure__"]["truncation"]["next_cursor"]
        assert one["exceptions_truncated"] is (cursor is not None)
        if cursor is None:
            break
    assert seen == calendar["exceptions"]
    assert len(seen) == calendar["exception_count"]


def test_a_cross_version_value_read_of_another_principals_activity_is_not_found(
    w: World,
) -> None:
    publication = str(w.publish(xer.build("full_valid").data)["publication_id"])
    activity = w.ok(ListScheduleP6Activities(publication_id=publication, page_size=1))[
        "activities"
    ][0]["schedule_activity_id"]
    assert w.ok(ListScheduleP6FieldValues(schedule_activity_id=activity))
    assert w.refused(ListScheduleP6FieldValues(schedule_activity_id=activity), principal_id=Q) == (
        "not_found",
        ["schedule_activity_id"],
    )


def test_a_remote_call_without_the_names_grant_is_unsupported(w: World) -> None:
    # Independent review S7-4a: `invoke` does not consult the grant set, so each
    # P6 handler re-checks the remote grant on its own name (defence in depth).
    admitted = w.publish(_bytes(_unknown_field_model()))
    publication = str(admitted["publication_id"])
    series = str(admitted["series_id"])
    unrelated = frozenset({(Capability.SCHEDULE_PUBLICATIONS_LIST, Purpose.SCHEDULE_READ)})
    for command in (
        w.import_command(xer.build("minimal_valid").data, path="exports/remote.xer"),
        ListScheduleP6AvailableFields(series_id=series),
        SetScheduleP6CapturedFields(
            series_id=series,
            field_keys=(EXTRA_KEY,),
            expected_sequence=0,
            idempotency_key=_key("g"),
        ),
        ListScheduleP6Activities(publication_id=publication),
        ListScheduleP6Relationships(publication_id=publication),
        ListScheduleP6Calendars(publication_id=publication),
        ListScheduleP6FieldValues(publication_id=publication),
    ):
        assert w.refused(command, remote_client=CLIENT_A, grants=unrelated) == (
            "unsupported",
            [],
        ), command.capability
    assert w.count("schedule_p6_capture_events") == 0
    assert w.count("schedule_publications") == 1


# ---- D2 / D3: the selection chain and the next import ---------------------------------


def test_an_observed_uncatalogued_field_selected_is_captured_from_the_next_import(
    w: World,
) -> None:
    first = w.publish(_bytes(_unknown_field_model()), path="exports/v1.xer")
    series = str(first["series_id"])
    available = w.ok(ListScheduleP6AvailableFields(series_id=series, page_size=100))
    by_key: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    while True:
        page = w.ok(ListScheduleP6AvailableFields(series_id=series, page_size=100, cursor=cursor))
        by_key.update({row["field_key"]: row for row in page["fields"]})
        cursor = page["__disclosure__"]["truncation"]["next_cursor"]
        if cursor is None:
            break
    assert available["selection"] == {
        "sequence": 0,
        "event_id": None,
        "include_personal": False,
        "defaults": True,
    }
    extra = by_key[EXTRA_KEY]
    assert extra["catalogued"] is False
    assert extra["captured"] is False
    assert extra["observed"]["imports_seen"] == 1
    assert extra["observed"]["last_seen_publication_id"] == first["publication_id"]
    assert extra["observed"]["nonempty_ratio"] == "1.000"
    assert "Synthetic extra" not in _flat(by_key)
    selected = w.ok(
        SetScheduleP6CapturedFields(
            series_id=series,
            field_keys=(EXTRA_KEY,),
            expected_sequence=0,
            idempotency_key=_key("select"),
        )
    )
    assert selected["created"] is True
    assert selected["sequence"] == 1
    assert selected["field_key_count"] == 1
    # The earlier import is unchanged: the selection applies from the next import.
    assert not w.ok(
        ListScheduleP6FieldValues(publication_id=str(first["publication_id"]), fields=(EXTRA_KEY,))
    )["values"]
    second = w.publish(_bytes(_unknown_field_model("Second export")), path="exports/v2.xer")
    values = w.ok(
        ListScheduleP6FieldValues(
            publication_id=str(second["publication_id"]), fields=(EXTRA_KEY,), page_size=100
        )
    )["values"]
    assert values
    assert {value["value_type"] for value in values} == {"text"}
    assert all(str(value["value"]).startswith("Second export") for value in values)
    shown = w.ok(
        ListScheduleP6Activities(
            publication_id=str(second["publication_id"]),
            fields=(EXTRA_KEY,),
            filter=({"field": EXTRA_KEY, "op": "prefix", "value": "Second export 1"},),
        )
    )["activities"]
    assert len(shown) == 1
    assert shown[0]["fields"][EXTRA_KEY] == "Second export 1"
    after = w.ok(ListScheduleP6AvailableFields(series_id=series, page_size=1))
    assert after["selection"]["sequence"] == 1


def test_set_captured_is_a_compare_and_swap_with_a_replay(w: World) -> None:
    series = str(w.publish(_bytes(_unknown_field_model()))["series_id"])
    key = _key("cas")
    command = SetScheduleP6CapturedFields(
        series_id=series, field_keys=(EXTRA_KEY,), expected_sequence=0, idempotency_key=key
    )
    first = w.ok(command)
    again = w.ok(command)
    assert again["created"] is False
    assert again["event_id"] == first["event_id"]
    assert w.count("schedule_p6_capture_events") == 1
    stale = SetScheduleP6CapturedFields(
        series_id=series, field_keys=(), expected_sequence=0, idempotency_key=_key("cas")
    )
    assert w.refused(stale) == ("conflict", ["sequence"])
    ahead = SetScheduleP6CapturedFields(
        series_id=series, field_keys=(), expected_sequence=5, idempotency_key=_key("cas")
    )
    assert w.refused(ahead) == ("conflict", ["sequence"])
    nxt = w.ok(
        SetScheduleP6CapturedFields(
            series_id=series, field_keys=(), expected_sequence=1, idempotency_key=_key("cas")
        )
    )
    assert nxt["sequence"] == 2
    assert w.count("schedule_p6_capture_events") == 2


def test_set_captured_refusals(w: World) -> None:
    series = str(w.publish(xer.build("minimal_valid").data)["series_id"])

    def select(keys: tuple[str, ...], principal_id: str = P) -> tuple[str, list[str]]:
        return w.refused(
            SetScheduleP6CapturedFields(
                series_id=series,
                field_keys=keys,
                expected_sequence=0,
                idempotency_key=_key("refuse"),
            ),
            principal_id=principal_id,
        )

    # Not available: an R field, an unobserved uncatalogued field.
    assert select(("xer:TASK.task_code",)) == ("invalid_request", ["field_key"])
    assert select(("xer:TASK.never_seen",)) == ("invalid_request", ["field_key"])
    # A personal field needs the explicit opt-in.
    assert select(("xer:TASK.create_user",)) == ("invalid_request", ["include_personal"])
    assert select(("xer:TASK.create_user",), principal_id=Q) == (
        "invalid_request",
        ["include_personal"],
    )
    # Another Principal's Series reads as absent.
    assert w.refused(
        SetScheduleP6CapturedFields(
            series_id=series, field_keys=(), expected_sequence=0, idempotency_key=_key("q")
        ),
        principal_id=Q,
    ) == ("not_found", ["series_id"])
    assert w.count("schedule_p6_capture_events") == 0


# ---- 10.4: personal fields ----------------------------------------------------------------


def test_a_personal_field_is_served_only_to_the_field_values_grant_and_when_selected(
    w: World,
) -> None:
    first = w.publish(xer.build("full_valid").data, path="exports/full1.xer")
    series = str(first["series_id"])
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=series,
            field_keys=("xer:TASK.create_user", "xer:TASK.est_wt"),
            include_personal=True,
            expected_sequence=0,
            idempotency_key=_key("personal"),
        )
    )
    model = xer.base_model("full")
    model.table("TASK").rows[0]["task_name"] = "Synthetic renamed activity"
    second = str(w.publish(_bytes(model), path="exports/full2.xer")["publication_id"])
    personal = ListScheduleP6FieldValues(
        publication_id=second, fields=("xer:TASK.create_user",), page_size=100
    )
    local = w.ok(personal)["values"]
    assert local
    granted = frozenset(
        {
            (Capability.SCHEDULE_P6_FIELD_VALUES_LIST, Purpose.SCHEDULE_READ),
            (Capability.SCHEDULE_P6_ACTIVITIES_LIST, Purpose.SCHEDULE_READ),
        }
    )
    assert w.ok(personal, remote_client=CLIENT_A, grants=granted)["values"] == local
    activities_only = frozenset({(Capability.SCHEDULE_P6_ACTIVITIES_LIST, Purpose.SCHEDULE_READ)})
    assert w.refused(
        ListScheduleP6Activities(publication_id=second, fields=("xer:TASK.create_user",)),
        remote_client=CLIENT_A,
        grants=activities_only,
    ) == ("invalid_request", ["field_key"])
    # The earlier publication's selection carried no personal opt-in.
    assert w.refused(
        ListScheduleP6FieldValues(
            publication_id=str(first["publication_id"]), fields=("xer:TASK.create_user",)
        )
    ) == ("invalid_request", ["field_key"])


def test_a_cross_version_value_read_withholds_personal_values_unless_every_version_opted_in(
    w: World,
) -> None:
    # Independent review S7-4a: across a Stable Activity's versions a personal
    # value is served only when every version's selection carried the opt-in.
    first = w.publish(xer.build("full_valid").data, path="exports/full1.xer")
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=str(first["series_id"]),
            field_keys=("xer:TASK.create_user", "xer:TASK.est_wt"),
            include_personal=True,
            expected_sequence=0,
            idempotency_key=_key("personal"),
        )
    )
    model = xer.base_model("full")
    model.table("TASK").rows[0]["task_name"] = "Synthetic renamed activity"
    second = str(w.publish(_bytes(model), path="exports/full2.xer")["publication_id"])
    in_second = w.ok(
        ListScheduleP6FieldValues(publication_id=second, entity_kind="activity", page_size=100)
    )["values"]
    assert any(row["field_key"] == "xer:TASK.create_user" for row in in_second)
    activity = w.ok(ListScheduleP6Activities(publication_id=second, page_size=1))["activities"][0]
    across = w.ok(
        ListScheduleP6FieldValues(
            schedule_activity_id=activity["schedule_activity_id"], page_size=100
        )
    )["values"]
    assert across
    assert all(row["field_key"] != "xer:TASK.create_user" for row in across)


# ---- D4: filters and sort over captured fields --------------------------------------------


def test_each_filter_operator_and_the_sort_over_captured_values(w: World) -> None:
    publication = str(w.publish(_udf_bytes())["publication_id"])
    count = "udf:TASK:Synthetic Count"
    note = "udf:TASK:Synthetic Note"
    ratio = "udf:TASK:Synthetic Ratio"

    def ids(*predicates: dict[str, Any], **extra: Any) -> list[str]:  # noqa: ANN401
        answer = w.ok(
            ListScheduleP6Activities(
                publication_id=publication, filter=predicates or None, page_size=100, **extra
            )
        )
        return [row["activity_id"] for row in answer["activities"]]

    every = ids()
    assert len(every) >= 3
    assert len(ids({"field": count, "op": "eq", "value": 12})) == 1
    assert len(ids({"field": count, "op": "in", "value": [12, 13]})) == 1
    assert len(ids({"field": count, "op": "gt", "value": 11})) == 1
    assert ids({"field": count, "op": "gt", "value": 12}) == []
    assert len(ids({"field": count, "op": "ge", "value": 12})) == 1
    assert ids({"field": count, "op": "lt", "value": 12}) == []
    assert len(ids({"field": count, "op": "le", "value": 12})) == 1
    assert len(ids({"field": note, "op": "prefix", "value": "Synthetic"})) == 1
    assert len(ids({"field": note, "op": "eq", "value": "Synthetic remark"})) == 1
    assert ids({"field": note, "op": "eq", "value": "Synthetic"}) == []
    # Predicates combine by AND.
    assert (
        ids({"field": count, "op": "eq", "value": 12}, {"field": ratio, "op": "gt", "value": 0})
        == []
    )
    (twelve,) = ids({"field": count, "op": "eq", "value": 12})
    # One key sorts; an entity without the value sorts last in either direction.
    for direction in ("asc", "desc"):
        ordered = ids(sort={"field": count, "direction": direction})
        assert ordered[0] == twelve
        assert set(ordered) == set(every)
    values = w.ok(
        ListScheduleP6FieldValues(
            publication_id=publication,
            entity_kind="activity",
            sort={"field": count, "direction": "asc"},
            page_size=100,
        )
    )["values"]
    assert values
    assert {value["entity_kind"] for value in values} == {"activity"}
    typed = {value["field_key"]: value["value_type"] for value in values}
    assert typed[count] == "number"
    assert typed[note] == "text"
    assert typed["udf:TASK:Synthetic Start"] == "ts"


def test_the_sort_direction_orders_the_captured_values(w: World) -> None:
    # Independent review S7-4a: `desc` reverses `asc` over a key every activity has.
    series = str(w.publish(_bytes(_unknown_field_model()), path="exports/v1.xer")["series_id"])
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=series,
            field_keys=(EXTRA_KEY,),
            expected_sequence=0,
            idempotency_key=_key("sort"),
        )
    )
    publication = str(
        w.publish(_bytes(_unknown_field_model("Second export")), path="exports/v2.xer")[
            "publication_id"
        ]
    )

    def ordered(direction: str) -> list[str]:
        rows = w.ok(
            ListScheduleP6Activities(
                publication_id=publication,
                fields=(EXTRA_KEY,),
                sort={"field": EXTRA_KEY, "direction": direction},
                page_size=100,
            )
        )["activities"]
        return [str(row["fields"][EXTRA_KEY]) for row in rows]

    ascending = ordered("asc")
    assert len(set(ascending)) >= 3
    assert ascending == sorted(ascending)
    assert ordered("desc") == list(reversed(ascending))


@pytest.mark.parametrize(
    "payload",
    [
        {"filter": [{"field": EXTRA_KEY, "op": "regex", "value": "x"}]},
        {"filter": [{"field": EXTRA_KEY, "op": "eq", "value": "x"}] * 4},
        {"filter": [{"field": EXTRA_KEY, "op": "in", "value": [str(i) for i in range(51)]}]},
        {"filter": [{"field": EXTRA_KEY, "op": "prefix", "value": "p" * 101}]},
        {"sort": {"field": EXTRA_KEY, "direction": "random"}},
        {"page_size": 101},
        {"page_size": 0},
        {"fields": [f"code:x{i}" for i in range(51)]},
    ],
)
def test_a_read_outside_the_grammar_is_refused_before_any_read(
    w: World, payload: dict[str, Any]
) -> None:
    document = {
        "contract_version": "v1",
        "request_id": issue_identifier(IdKind.CORRELATION),
        "requested_at": "2026-11-25T00:00:00Z",
        "principal_id": P,
        "purpose": "schedule_read",
        "scope": {"source_ids": [], "enrollment_ids": []},
        "payload": {"publication_id": "spub_sp6caps0000", **payload},
    }
    with pytest.raises(InvalidRequestError):
        normalize("schedule_p6_activities.list", document)
    assert w.count("audit_events") == 0


# ---- 7.7: quota and import budgets ---------------------------------------------------------


def test_the_snapshot_quota_refuses_a_new_snapshot_and_counts_held_bytes_once(w: World) -> None:
    data = xer.build("minimal_valid").data
    w.limits = P6AdmissionLimits(
        snapshot_quota_bytes=len(data) + 10, imports_per_hour=60, imports_per_day=500
    )
    first = w.ok(w.import_command(data, path="exports/a.xer"))
    other = _bytes(_unknown_field_model())
    assert w.refused(w.import_command(other, path="exports/b.xer")) == (
        "rate_limited",
        ["storage_quota"],
    )
    assert w.count("schedule_p6_snapshots") == 1
    # The same bytes into another Series are held already and fit.
    same = w.ok(w.import_command(data, path="exports/c.xer", series_name="Second Series"))
    assert same["publication_id"] != first["publication_id"]
    assert w.count("schedule_p6_snapshots") == 1


def test_the_hourly_import_budget(w: World) -> None:
    w.limits = P6AdmissionLimits(
        snapshot_quota_bytes=8 * 1024**3, imports_per_hour=1, imports_per_day=500
    )
    command = w.import_command(xer.build("minimal_valid").data, path="exports/a.xer")
    w.ok(command)
    # A replay of the same key writes nothing and spends nothing.
    assert w.ok(command)["outcome"] == "replayed"
    assert w.refused(w.import_command(_bytes(_unknown_field_model()), path="exports/b.xer")) == (
        "rate_limited",
        [],
    )
    assert w.count("schedule_publications") == 1


# ---- D7: remote, idempotent and client-bound -------------------------------------------------


def test_a_remote_import_is_client_bound(w: World) -> None:
    data = xer.build("minimal_valid").data
    named = {
        "project_id": PROJECT,
        "series_name": "Master Schedule",
        **w.put("exports/r.xer", data),
    }
    principal = Principal(principal_id=P, kind=PrincipalKind.OPERATOR, authenticated=True)
    grants = frozenset({(Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6, Purpose.SCHEDULE_P6_IMPORT)})

    def composed(client: str) -> ImportScheduleP6Publication:
        document = compose_remote_arguments(
            capability_name="schedule_publications.import_p6",
            arguments={"payload": dict(named)},
            principal=principal,
            grants=grants,
            authenticated_client_id=client,
        )
        return ImportScheduleP6Publication(**document["payload"])

    a = composed(CLIENT_A)
    assert a.idempotency_key == composed(CLIENT_A).idempotency_key
    assert a.idempotency_key != composed(CLIENT_B).idempotency_key
    first = w.ok(a, remote_client=CLIENT_A, grants=grants)
    assert w.ok(a, remote_client=CLIENT_A, grants=grants)["outcome"] == "replayed"
    other = w.ok(composed(CLIENT_B), remote_client=CLIENT_B, grants=grants)
    assert other["outcome"] == "already_present"
    assert other["publication_id"] == first["publication_id"]


def test_a_remote_selection_replays_for_its_own_client_only(w: World) -> None:
    series = str(w.publish(_bytes(_unknown_field_model()))["series_id"])
    grants = frozenset(
        {(Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED, Purpose.SCHEDULE_P6_CONFIGURATION)}
    )
    command = SetScheduleP6CapturedFields(
        series_id=series, field_keys=(EXTRA_KEY,), expected_sequence=0, idempotency_key=_key("r")
    )
    first = w.ok(command, remote_client=CLIENT_A, grants=grants)
    assert w.ok(command, remote_client=CLIENT_A, grants=grants)["created"] is False
    assert w.refused(command, remote_client=CLIENT_B, grants=grants) == ("conflict", ["sequence"])
    assert first["sequence"] == 1
