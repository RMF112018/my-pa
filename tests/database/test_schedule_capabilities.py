"""CPM Workbench S5b-2: the 7 Schedule capabilities against a synthetic head database.

Worker and capabilities contract sections 3.1 and 3.5-3.11 (R2 sections 9, 10,
22, 23, 29, 30, 31, 32): the switch, import admission (attested-local only,
remote refusal E-10, the caller's own enrollment on a shared source, the 14
admission refusals, idempotency replay and conflict), the six reads (U-03,
RR1-I01, eligibility, ordering, filters, cross-Principal answers), the cursor
(section 3.7 incl. R7-F10), the disclosure (section 3.8 incl. the empty
reference set) and the delta and baseline rules end to end. Publications are
written by the real handler through
`tests/database/schedule_capability_harness.py`.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.adapters.mcp.server import published_tools
from my_pa.application import schedules as schedules_module
from my_pa.application.commands import (
    Command,
    GetCapabilities,
    ImportSchedulePublication,
    ListScheduleActivities,
    ListScheduleChanges,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
    ReadSchedulePublication,
)
from my_pa.contracts.ports import ScheduleAdmissionRejectedError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.schedule import (
    ScheduleAdmissionRefusal,
    ScheduleFinalization,
    ScheduleIssueCode,
    ScheduleLease,
    ScheduleParserIdentity,
    SchedulePublicationStatus,
    ScheduleRowType,
    parse_result_sha256,
)
from my_pa.domain.schedule.cursor import (
    ScheduleCursorOrder,
    encode_schedule_cursor,
    schedule_cursor_binding,
)
from my_pa.infrastructure.persistence import schedule as persistence_module
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, LeasedJob, claim_job
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from tests.database.schedule_capability_harness import (
    OTHER_PRINCIPAL,
    OWNER,
    PRINCIPAL,
    REMOTE_CLIENT,
    SIXTEEN_MIB,
    Activity,
    ScheduleRuntime,
    World,
    build_result,
    cpm_snapshot,
)
from tests.transports import cli_transport, http_transport, mcp_transport

pytestmark = pytest.mark.database

D1: Final = date(2026, 5, 4)
D2: Final = date(2026, 6, 1)
D3: Final = date(2026, 7, 6)
IMPORT: Final = Capability.SCHEDULE_PUBLICATIONS_IMPORT
READS: Final = (
    Capability.SCHEDULE_SERIES_LIST,
    Capability.SCHEDULE_PUBLICATIONS_LIST,
    Capability.SCHEDULE_PUBLICATIONS_READ,
    Capability.SCHEDULE_ACTIVITIES_LIST,
    Capability.SCHEDULE_ACTIVITIES_HISTORY,
    Capability.SCHEDULE_CHANGES_LIST,
)
SEVEN: Final = (IMPORT, *READS)
_ABSENT: Final = {
    "project": "prj_absentroot0001",
    "series": "sser_absentroot0001",
    "publication": "spub_absentroot0001",
    "activity": "sact_absentroot0001",
}


@pytest.fixture
def rt(disposable_database: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.fixture
def w(rt: ScheduleRuntime) -> World:
    return rt.world(PRINCIPAL, "schedcapa")


@pytest.fixture
def q(rt: ScheduleRuntime, w: World) -> World:
    """The other Principal, enrolled on the **same** source (R7-F06, Q14)."""
    return rt.world(OTHER_PRINCIPAL, "schedcapb", source=w.source)


def _activities(*published: str) -> list[Activity]:
    return [Activity(pid) for pid in published]


class Scene:
    """Two complete updates of one Series, the second renaming, dropping and adding."""

    def __init__(self, rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch) -> None:
        self.first = rt.publish(monkeypatch, w, _activities("A-1", "B-2"), data_date=D1)
        (series,) = rt.ok(ListScheduleSeries(project_id=w.project), principal_id=w.principal)[
            "series"
        ]
        self.series = str(series["series_id"])
        self.second = rt.publish(
            monkeypatch,
            w,
            [Activity("A-1", name="Renamed"), Activity("C-3")],
            data_date=D2,
            series_id=self.series,
        )
        listed = rt.ok(ListScheduleActivities(publication_id=self.first), principal_id=w.principal)[
            "activities"
        ]
        self.activity = str(listed[0]["schedule_activity_id"])
        self.project = w.project


@pytest.fixture
def scene(rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(rt, w, monkeypatch)


def _read_commands(scene: Scene) -> dict[Capability, Command]:
    return {
        Capability.SCHEDULE_SERIES_LIST: ListScheduleSeries(project_id=scene.project),
        Capability.SCHEDULE_PUBLICATIONS_LIST: ListSchedulePublications(series_id=scene.series),
        Capability.SCHEDULE_PUBLICATIONS_READ: ReadSchedulePublication(publication_id=scene.first),
        Capability.SCHEDULE_ACTIVITIES_LIST: ListScheduleActivities(publication_id=scene.first),
        Capability.SCHEDULE_ACTIVITIES_HISTORY: ReadScheduleActivityHistory(
            schedule_activity_id=scene.activity
        ),
        Capability.SCHEDULE_CHANGES_LIST: ListScheduleChanges(
            from_publication_id=scene.first, to_publication_id=scene.second
        ),
    }


def _import_command(w: World, object_id: str, version_id: str, **overrides: Any) -> Command:  # noqa: ANN401
    fields_: dict[str, Any] = {
        "project_id": w.project,
        "series_name": "Master Schedule",
        "enrollment_id": w.enrollment,
        "source_object_id": object_id,
        "source_version_id": version_id,
        "publication_role": "update",
        "idempotency_key": f"schedule-cap-{object_id[-10:]}",
    }
    fields_.update(overrides)
    return ImportSchedulePublication(**fields_)


def _disclosure(answer: Mapping[str, Any]) -> dict[str, Any]:
    disclosure = answer["__disclosure__"]
    assert isinstance(disclosure, dict)
    return disclosure


def _manifest_rows(rt: ScheduleRuntime, service: Any = None) -> dict[str, Any]:  # noqa: ANN401
    answer = rt.ok(
        GetCapabilities(), purpose=Purpose.STATUS_OBSERVATION, service=service or rt.service
    )
    return {row["name"]: row for row in answer["manifest"]["capabilities"]}


# ---- the switch (section 3.1) ------------------------------------------------------------


@pytest.mark.parametrize("capability", SEVEN, ids=lambda capability: capability.value)
def test_switch_off_withholds_and_refuses_every_schedule_capability(
    rt: ScheduleRuntime, scene: Scene, w: World, capability: Capability
) -> None:
    """Off, with the factory composed: only the switch stands between a caller and the plane.

    The Schedule factory is present, the roots exist and the import names an
    enrolled PDF from the attested CLI surface, so a handler that skipped
    `_schedule_plane()` would serve the read or admit the publication. The
    authorization audit row `invoke` writes before any handler is the one row
    the call writes (R7-F09).
    """
    off = ScheduleRuntime(rt.url, enabled=False)
    try:
        object_id, version_id = rt.source_object(w)
        commands: dict[Capability, Command] = {
            IMPORT: _import_command(w, object_id, version_id),
            **_read_commands(scene),
        }
        assert capability not in off.service.available_capabilities
        assert capability in rt.service.available_capabilities
        assert _manifest_rows(off, off.service)[capability.value]["availability"] == (
            "not_implemented"
        )
        assert capability.value not in {
            tool.name for tool in published_tools(off.service, authenticated_client_present=True)
        }
        before = cpm_snapshot(rt.engine)
        audited = off.audit_count(capability)
        code, details = off.refused(
            commands[capability],
            surface=OperatorSurface.CLI if capability is IMPORT else None,
        )
        assert (code, details) == ("unsupported", [])
        assert off.audit_count(capability) == audited + 1
        assert cpm_snapshot(rt.engine) == before
    finally:
        off.close()


def test_capabilities_get_reports_the_schedule_plane_only_when_enabled(
    rt: ScheduleRuntime,
) -> None:
    def planes(runtime: ScheduleRuntime) -> list[str]:
        answer = runtime.ok(GetCapabilities(), purpose=Purpose.STATUS_OBSERVATION)
        return [plane["plane"] for plane in answer["worker_planes"]]

    assert planes(rt) == ["capture", "enrollment", "schedule"]
    off = ScheduleRuntime(rt.url, enabled=False)
    uncomposed = ScheduleRuntime(rt.url, composed=False)
    try:
        assert planes(off) == ["capture", "enrollment"]
        assert planes(uncomposed) == ["capture", "enrollment"]
        assert not set(SEVEN) & set(uncomposed.service.available_capabilities)
    finally:
        off.close()
        uncomposed.close()


# ---- import admission (section 3.6) ------------------------------------------------------


def test_import_creates_one_job(rt: ScheduleRuntime, w: World) -> None:
    object_id, version_id = rt.source_object(w)
    answer = rt.import_(w, object_id, version_id)
    assert (answer["status"], answer["created"]) == ("queued", True)
    assert answer["operation_id"].startswith("op_")
    publication = answer["publication_id"]
    assert (
        rt.scalar(
            "SELECT count(*) FROM knowledge.schedule_jobs WHERE publication_id = :p", p=publication
        )
        == 1
    )
    assert (
        rt.scalar(
            "SELECT state FROM knowledge.schedule_jobs WHERE publication_id = :p", p=publication
        )
        == "queued"
    )
    disclosure = _disclosure(answer)
    assert disclosure["coverage"] == {
        "state": "queued",
        "eligible": 1,
        "processed": 0,
        "quarantined": 0,
        "unsupported": 0,
    }
    assert disclosure["trust"] == {"level": "source_bound_derived", "basis": ["schedule_admission"]}
    assert disclosure["scope"] == {"source_ids": [w.source], "enrollment_ids": [w.enrollment]}
    assert disclosure["source_references"] == [
        {"source_id": w.source, "source_object_id": object_id, "version_id": version_id}
    ]
    assert disclosure["partial_result"] is False


def test_import_replays_and_conflicts_per_section_23(rt: ScheduleRuntime, w: World) -> None:
    object_id, version_id = rt.source_object(w)
    first = rt.import_(w, object_id, version_id, key="schedule-replay-0001")
    again = rt.import_(w, object_id, version_id, key="schedule-replay-0001")
    assert (again["status"], again["created"]) == ("replayed", False)
    assert {k: again[k] for k in ("series_id", "publication_id", "operation_id")} == {
        k: first[k] for k in ("series_id", "publication_id", "operation_id")
    }
    # The same version under a new key, every field equal: the version replays.
    by_version = rt.import_(w, object_id, version_id, key="schedule-replay-0002")
    assert (by_version["publication_id"], by_version["created"]) == (
        first["publication_id"],
        False,
    )
    # The same key naming something else, or the same version stated differently.
    other_object, other_version = rt.source_object(w)
    before = cpm_snapshot(rt.engine)
    assert rt.refused(
        _import_command(w, other_object, other_version, idempotency_key="schedule-replay-0001"),
        surface=OperatorSurface.CLI,
    ) == ("conflict", ["idempotency_key"])
    assert rt.refused(
        _import_command(
            w,
            object_id,
            version_id,
            publication_role="reference",
            idempotency_key="schedule-replay-0003",
        ),
        surface=OperatorSurface.CLI,
    ) == ("conflict", ["source_version_id"])
    assert cpm_snapshot(rt.engine) == before


def test_import_with_another_principals_enrollment_is_denied_and_writes_nothing(
    rt: ScheduleRuntime, w: World, q: World
) -> None:
    """Both Principals hold an enrollment on one shared source (R7-F06).

    The requested scope is the source of the caller's **own** enrollment named
    by `enrollment_id`; Q's enrollment is not P's, so the scope is empty and
    authorization denies, audited. A scope read off the enrollment row itself
    would resolve to the shared source P is also authorized for, admit the
    request and leave the admission's `not_found` as the only refusal.
    """
    object_id, version_id = rt.source_object(q)
    assert q.source == w.source
    before = cpm_snapshot(rt.engine)
    audited = rt.audit_count(IMPORT)
    refused = rt.refused(
        _import_command(w, object_id, version_id, enrollment_id=q.enrollment),
        surface=OperatorSurface.CLI,
    )
    assert refused == ("denied", [])
    assert rt.audit_count(IMPORT) == audited + 1
    audit = rt.last_audit()
    assert (audit["capability"], audit["principal_id"], audit["outcome"]) == (
        IMPORT.value,
        PRINCIPAL,
        "denied",
    )
    assert cpm_snapshot(rt.engine) == before
    # Non-vacuous: Q importing through its own enrollment is admitted.
    admitted = rt.import_(q, object_id, version_id)
    assert admitted["created"] is True


def _second_enrollment(rt: ScheduleRuntime, w: World, media: str) -> str:
    enrollment = f"enr_{w.tag}second"
    rt.execute(
        "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, purpose, "
        "policy_version, idempotency_key, request_fingerprint, object_ids, depth, media_types, "
        "max_items, max_bytes) VALUES (:e, :s, :p, 'schedule_import', 'policy-v1', :k, "
        "'synthetic', ARRAY[:root], 0, ARRAY[:m], 100, :max)",
        e=enrollment,
        s=w.source,
        p=w.principal,
        k=f"{w.tag}-second",
        root=f"obj_{w.tag}secondroot",
        m=media,
        max=SIXTEEN_MIB,
    )
    return enrollment


def _failed_publication(
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    **options: Any,  # noqa: ANN401
) -> tuple[str, str, str, dict[str, Any]]:
    """A terminal `failed` publication: the provider serves bytes that are not a PDF."""
    object_id, version_id = rt.source_object(w)
    rt.objects[object_id] = (version_id, b"not a pdf at all")
    admitted = rt.import_(w, object_id, version_id, **options)
    rt.serve(monkeypatch, w)
    assert rt.run_worker(w.principal).completed == 1
    return str(admitted["publication_id"]), object_id, version_id, admitted


def _unreachable(reason: ScheduleAdmissionRefusal) -> Callable[..., Any]:
    def admit(*_args: object, **_kwargs: object) -> Any:  # noqa: ANN401
        raise ScheduleAdmissionRejectedError(reason)

    return admit


#: Section 3.5.3: each refusal and its public answer.
_REFUSAL_ANSWERS: Final = {
    ScheduleAdmissionRefusal.PROJECT_NOT_FOUND: ("not_found", ["project_id"]),
    ScheduleAdmissionRefusal.SERIES_NOT_FOUND: ("not_found", ["series_id"]),
    ScheduleAdmissionRefusal.ENROLLMENT_NOT_FOUND: ("not_found", ["enrollment_id"]),
    ScheduleAdmissionRefusal.SOURCE_OBJECT_NOT_ENROLLED: ("not_found", ["source_object_id"]),
    ScheduleAdmissionRefusal.SOURCE_VERSION_NOT_FOUND: ("not_found", ["source_version_id"]),
    ScheduleAdmissionRefusal.UNSUPPORTED_MEDIA_TYPE: ("unsupported", ["source_version_id"]),
    ScheduleAdmissionRefusal.MEDIA_TYPE_NOT_ENROLLED: ("denied", []),
    ScheduleAdmissionRefusal.SOURCE_TOO_LARGE: ("unsupported", ["max_bytes"]),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND: (
        "not_found",
        ["supersedes_publication_id"],
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL: (
        "conflict",
        ["supersedes_publication_id"],
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION: (
        "invalid_request",
        ["supersedes_publication_id"],
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR: (
        "conflict",
        ["supersedes_publication_id"],
    ),
    ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT: ("conflict", ["idempotency_key"]),
    ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT: ("conflict", ["source_version_id"]),
}

#: Refusals the capability path cannot reach, so the mapping is proved by a
#: repository that answers them: `ENROLLMENT_NOT_FOUND` is pre-empted by
#: authorization (a foreign or absent enrollment is an empty scope, `denied`),
#: and `SAME_SOURCE_VERSION` by the S5b-1 version replay (one publication per
#: version per Series: a predecessor with the same version *is* the version's
#: publication, so the request is a `SOURCE_VERSION_CONFLICT` first).
_BACKSTOPS: Final = frozenset(
    {
        ScheduleAdmissionRefusal.ENROLLMENT_NOT_FOUND,
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION,
    }
)


@pytest.mark.parametrize("reason", list(ScheduleAdmissionRefusal), ids=lambda reason: reason.value)
def test_import_admission_refusals_map_to_safe_errors(
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    reason: ScheduleAdmissionRefusal,
) -> None:
    assert set(_REFUSAL_ANSWERS) == set(ScheduleAdmissionRefusal)
    object_id, version_id = rt.source_object(w)
    command: Command
    if reason is ScheduleAdmissionRefusal.PROJECT_NOT_FOUND:
        command = _import_command(w, object_id, version_id, project_id=_ABSENT["project"])
    elif reason is ScheduleAdmissionRefusal.SERIES_NOT_FOUND:
        command = _import_command(
            w, object_id, version_id, series_name=None, series_id=_ABSENT["series"]
        )
    elif reason is ScheduleAdmissionRefusal.SOURCE_OBJECT_NOT_ENROLLED:
        loose_object, loose_version = rt.source_object(w, enrolled=False)
        command = _import_command(w, loose_object, loose_version)
    elif reason is ScheduleAdmissionRefusal.SOURCE_VERSION_NOT_FOUND:
        command = _import_command(w, object_id, "ver_absentroot0001")
    elif reason is ScheduleAdmissionRefusal.UNSUPPORTED_MEDIA_TYPE:
        text_object, text_version = rt.source_object(w, media_type="text/plain")
        command = _import_command(w, text_object, text_version)
    elif reason is ScheduleAdmissionRefusal.MEDIA_TYPE_NOT_ENROLLED:
        enrollment = _second_enrollment(rt, w, "text/plain")
        other_object, other_version = rt.source_object(w, enrollment=enrollment)
        command = _import_command(w, other_object, other_version, enrollment_id=enrollment)
    elif reason is ScheduleAdmissionRefusal.SOURCE_TOO_LARGE:
        large_object, large_version = rt.source_object(w, size=SIXTEEN_MIB + 1)
        command = _import_command(w, large_object, large_version)
    elif reason is ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND:
        command = _import_command(
            w, object_id, version_id, supersedes_publication_id=_ABSENT["publication"]
        )
    elif reason is ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL:
        queued_object, queued_version = rt.source_object(w)
        queued = rt.import_(w, queued_object, queued_version)["publication_id"]
        command = _import_command(w, object_id, version_id, supersedes_publication_id=queued)
    elif reason is ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR:
        failed, *_ = _failed_publication(rt, w, monkeypatch)
        successor_object, successor_version = rt.source_object(w)
        rt.import_(w, successor_object, successor_version, supersedes=failed)
        command = _import_command(w, object_id, version_id, supersedes_publication_id=failed)
    elif reason is ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT:
        rt.import_(w, object_id, version_id, key="schedule-conflict-0001")
        other_object, other_version = rt.source_object(w)
        command = _import_command(
            w, other_object, other_version, idempotency_key="schedule-conflict-0001"
        )
    elif reason is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT:
        rt.import_(w, object_id, version_id)
        command = _import_command(
            w,
            object_id,
            version_id,
            publication_role="reference",
            idempotency_key="schedule-conflict-0002",
        )
    else:
        assert reason in _BACKSTOPS
        monkeypatch.setattr(
            persistence_module.SqlScheduleRepository, "admit_publication", _unreachable(reason)
        )
        command = _import_command(w, object_id, version_id)
    before = cpm_snapshot(rt.engine)
    assert rt.refused(command, surface=OperatorSurface.CLI) == _REFUSAL_ANSWERS[reason]
    # The admission transaction rolled back -- a Series it created included.
    assert cpm_snapshot(rt.engine) == before


def test_failed_version_reimport_is_a_source_version_conflict(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S5b-1 U-09 surfaced: a failed version stays the version's publication in its Series."""
    failed, object_id, version_id, admitted = _failed_publication(rt, w, monkeypatch)
    read = rt.ok(ReadSchedulePublication(publication_id=failed))
    assert read["status"] == "failed"
    # Stated identically under a new key: the failed publication answers.
    again = rt.import_(w, object_id, version_id, key="schedule-u09-0002")
    assert (again["publication_id"], again["status"], again["created"]) == (
        failed,
        "replayed",
        False,
    )
    assert _disclosure(again)["coverage"]["state"] == "unsupported"
    # Any re-statement -- superseding the failure with the same bytes -- is a conflict.
    assert rt.refused(
        _import_command(
            w,
            object_id,
            version_id,
            series_name=None,
            series_id=admitted["series_id"],
            supersedes_publication_id=failed,
            idempotency_key="schedule-u09-0003",
        ),
        surface=OperatorSurface.CLI,
    ) == ("conflict", ["source_version_id"])


def _document(rt: ScheduleRuntime, w: World, object_id: str, version_id: str) -> dict[str, Any]:
    return {
        "request_id": f"req-{object_id[-12:]}",
        "purpose": "schedule_import",
        "principal_id": w.principal,
        "requested_at": datetime.now(UTC).isoformat(),
        "payload": {
            "project_id": w.project,
            "series_name": "Transport Schedule",
            "enrollment_id": w.enrollment,
            "source_object_id": object_id,
            "source_version_id": version_id,
            "publication_role": "update",
            "idempotency_key": f"transport-{object_id[-12:]}",
        },
    }


def _operator(principal: str = PRINCIPAL) -> Principal:
    return Principal(principal_id=principal, kind=PrincipalKind.OPERATOR, authenticated=True)


def test_import_over_stdio_mcp_is_denied_and_writes_nothing(rt: ScheduleRuntime, w: World) -> None:
    """The local stdio MCP composition stamps no operator surface (E-12)."""
    object_id, version_id = rt.source_object(w)
    before = cpm_snapshot(rt.engine)
    with mcp_transport(rt.service, _operator()) as mcp:
        answer = mcp.send(IMPORT.value, _document(rt, w, object_id, version_id))
    assert answer.failed
    error = answer.document.get("error", answer.document)
    assert error["code"] == "denied"
    assert cpm_snapshot(rt.engine) == before


def test_import_without_an_attested_surface_is_denied(rt: ScheduleRuntime, w: World) -> None:
    object_id, version_id = rt.source_object(w)
    before = cpm_snapshot(rt.engine)
    audited = rt.audit_count(IMPORT)
    assert rt.refused(_import_command(w, object_id, version_id)) == ("denied", [])
    # Authorization allowed it (the audit row says so); the handler refused it.
    assert rt.audit_count(IMPORT) == audited + 1
    assert rt.last_audit()["outcome"] == "allowed"
    assert cpm_snapshot(rt.engine) == before


def test_import_from_cli_and_http_gateway_is_admitted(rt: ScheduleRuntime, w: World) -> None:
    cli_object, cli_version = rt.source_object(w)
    with cli_transport(rt.service, _operator()) as cli:
        answer = cli.send(IMPORT.value, _document(rt, w, cli_object, cli_version))
    assert not answer.failed, answer.rendered
    assert answer.document["result"]["status"] == "queued"
    http_object, http_version = rt.source_object(w)
    with http_transport(rt.service, _operator()) as http:
        answer = http.send(IMPORT.value, _document(rt, w, http_object, http_version))
    assert not answer.failed, answer.rendered
    assert answer.document["result"]["created"] is True
    assert (
        rt.scalar(
            "SELECT count(*) FROM knowledge.schedule_publications WHERE principal_id = :p",
            p=PRINCIPAL,
        )
        == 2
    )


def test_remote_import_is_unsupported_even_for_an_operator_principal(
    rt: ScheduleRuntime, w: World
) -> None:
    """E-10: every remote OAuth client is an operator, so policy alone admits the call.

    Invoked on the service directly with a grant on the import: the publication
    layer (which never lists the import remotely) would mask the handler's own
    refusal.
    """
    object_id, version_id = rt.source_object(w)
    before = cpm_snapshot(rt.engine)
    audited = rt.audit_count(IMPORT)
    refused = rt.refused(
        _import_command(w, object_id, version_id),
        remote_client=REMOTE_CLIENT,
        grants=frozenset({(IMPORT, Purpose.SCHEDULE_IMPORT)}),
    )
    assert refused == ("unsupported", [])
    assert rt.audit_count(IMPORT) == audited + 1
    assert rt.last_audit()["outcome"] == "allowed"
    assert cpm_snapshot(rt.engine) == before


# ---- reads: the remote grant re-check, cross-Principal answers --------------------------


@pytest.mark.parametrize("capability", READS, ids=lambda capability: capability.value)
def test_remote_read_without_grant_is_unsupported(
    rt: ScheduleRuntime, scene: Scene, capability: Capability
) -> None:
    command = _read_commands(scene)[capability]
    ungranted = frozenset({(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION)})
    assert rt.refused(command, remote_client=REMOTE_CLIENT, grants=ungranted) == (
        "unsupported",
        [],
    )
    # A grant for a purpose the read does not permit admits nothing either.
    assert rt.refused(
        command,
        remote_client=REMOTE_CLIENT,
        grants=frozenset({(capability, Purpose.SCHEDULE_IMPORT)}),
    ) == ("unsupported", [])
    # Non-vacuous: the same remote caller with the grant is served.
    assert rt.ok(command, remote_client=REMOTE_CLIENT)


def _foreign_and_absent(
    capability: Capability, mine: Scene, theirs: Scene
) -> tuple[Command, Command]:
    match capability:
        case Capability.SCHEDULE_SERIES_LIST:
            return (
                ListScheduleSeries(project_id=theirs.project),
                ListScheduleSeries(project_id=_ABSENT["project"]),
            )
        case Capability.SCHEDULE_PUBLICATIONS_LIST:
            return (
                ListSchedulePublications(series_id=theirs.series),
                ListSchedulePublications(series_id=_ABSENT["series"]),
            )
        case Capability.SCHEDULE_PUBLICATIONS_READ:
            return (
                ReadSchedulePublication(publication_id=theirs.first),
                ReadSchedulePublication(publication_id=_ABSENT["publication"]),
            )
        case Capability.SCHEDULE_ACTIVITIES_LIST:
            return (
                ListScheduleActivities(publication_id=theirs.first),
                ListScheduleActivities(publication_id=_ABSENT["publication"]),
            )
        case Capability.SCHEDULE_ACTIVITIES_HISTORY:
            return (
                ReadScheduleActivityHistory(schedule_activity_id=theirs.activity),
                ReadScheduleActivityHistory(schedule_activity_id=_ABSENT["activity"]),
            )
        case _:
            return (
                ListScheduleChanges(
                    from_publication_id=mine.first, to_publication_id=theirs.second
                ),
                ListScheduleChanges(
                    from_publication_id=mine.first, to_publication_id=_ABSENT["publication"]
                ),
            )


@pytest.mark.parametrize("capability", READS, ids=lambda capability: capability.value)
def test_cross_principal_roots_are_not_found_identically(
    rt: ScheduleRuntime,
    w: World,
    q: World,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
) -> None:
    mine = Scene(rt, w, monkeypatch)
    theirs = Scene(rt, q, monkeypatch)
    foreign, absent = _foreign_and_absent(capability, mine, theirs)
    refused = rt.refused(foreign)
    assert refused[0] == "not_found"
    assert refused == rt.refused(absent)
    # The other Principal reads its own root.
    assert rt.ok(
        foreign
        if capability is not Capability.SCHEDULE_CHANGES_LIST
        else ListScheduleChanges(from_publication_id=theirs.first, to_publication_id=theirs.second),
        principal_id=OTHER_PRINCIPAL,
    )
    if capability is Capability.SCHEDULE_CHANGES_LIST:
        from_foreign = rt.refused(
            ListScheduleChanges(from_publication_id=theirs.first, to_publication_id=mine.second)
        )
        assert from_foreign == ("not_found", ["from_publication_id"])
        assert from_foreign == rt.refused(
            ListScheduleChanges(
                from_publication_id=_ABSENT["publication"], to_publication_id=mine.second
            )
        )


# ---- U-03 and RR1-I01 ----------------------------------------------------------------------


def _claim(rt: ScheduleRuntime, principal: str = PRINCIPAL) -> LeasedJob:
    with rt.engine.begin() as c:
        job = claim_job(
            c, owner=OWNER, lease_seconds=300, principal_id=principal, plane=SCHEDULE_JOBS
        )
    assert job is not None
    return job


def _expire(rt: ScheduleRuntime, operation_id: str) -> None:
    rt.execute(
        "UPDATE knowledge.schedule_jobs SET lease_expires_at = now() - interval '1 second' "
        "WHERE operation_id = :o",
        o=operation_id,
    )


def _repository(rt: ScheduleRuntime, work: Callable[[Any], Any]) -> Any:  # noqa: ANN401
    with SqlAlchemyScheduleUnitOfWork(rt.engine) as uow:
        return work(uow.schedules)


def _staged(
    rt: ScheduleRuntime, w: World, activities: list[Activity], *, outcome: SchedulePublicationStatus
) -> tuple[str, Any, Any]:
    """Admit and claim one publication; returns its id, its lease and the result."""
    object_id, version_id = rt.source_object(w)
    data = rt.objects[object_id][1]
    result = build_result(data, activities, data_date=D1, outcome=outcome)
    publication = str(rt.import_(w, object_id, version_id)["publication_id"])
    job = _claim(rt, w.principal)
    lease = ScheduleLease(job.operation_id, OWNER, job.attempt)
    _repository(rt, lambda r: r.begin_processing(w.principal, publication, lease))
    _repository(
        rt,
        lambda r: r.pin_document(
            w.principal, publication, lease, result.document_sha256, result.document_size_bytes
        ),
    )
    return publication, lease, result


def test_orphan_stable_activity_is_not_found_like_absent(rt: ScheduleRuntime, w: World) -> None:
    """U-03: a Stable Activity linked only from a publication that then failed.

    Canonicalization links a parsed run's rows and the attempt then fails
    (here: its budget, after H7). The Stable Activity row exists, but no
    complete or partial publication's accepted run links it, so it is answered
    exactly as an absent one -- and never with its `created_at`.
    """
    publication, lease, result = _staged(
        rt, w, _activities("ORPHAN-1"), outcome=SchedulePublicationStatus.COMPLETE
    )
    p = w.principal
    run = _repository(
        rt,
        lambda r: (
            r.start_parser_run(
                p, publication, lease, ScheduleParserIdentity.from_parse_result(result)
            ).run
        ),
    )
    _repository(rt, lambda r: r.insert_rows(p, run.parser_run_id, lease, result.rows))
    _repository(
        rt,
        lambda r: r.finish_parser_run(
            p,
            run.parser_run_id,
            lease,
            parsed=result.counts,
            parse_result_sha256=parse_result_sha256(result),
            failure_code=None,
        ),
    )
    _repository(rt, lambda r: r.canonicalize_batch(p, run.parser_run_id, lease))
    _repository(
        rt,
        lambda r: r.fail_publication(
            p, publication, lease, ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED, None
        ),
    )
    orphan = rt.scalar(
        "SELECT schedule_activity_id FROM knowledge.schedule_activities WHERE "
        "published_activity_id = 'ORPHAN-1'"
    )
    assert orphan is not None
    refused = rt.refused(ReadScheduleActivityHistory(schedule_activity_id=orphan))
    assert refused == ("not_found", ["schedule_activity_id"])
    assert refused == rt.refused(
        ReadScheduleActivityHistory(schedule_activity_id=_ABSENT["activity"])
    )


def test_history_never_reports_created_at(rt: ScheduleRuntime, scene: Scene) -> None:
    answer = rt.ok(ReadScheduleActivityHistory(schedule_activity_id=scene.activity))
    payload = {k: v for k, v in answer.items() if k != "__disclosure__"}
    rendered = json.dumps(payload)
    assert "created_at" not in rendered
    assert "first_seen" not in rendered
    assert set(payload) == {
        "schedule_activity_id",
        "series_id",
        "published_activity_id",
        "observations",
        "page_size",
    }
    assert [o["data_date"] for o in payload["observations"]] == [D1.isoformat(), D2.isoformat()]
    assert [o["activity_name"] for o in payload["observations"]] == [
        "Synthetic activity",
        "Renamed",
    ]


def test_history_lists_a_superseded_predecessor_and_its_successor(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7-F11: both are actual observations, by `(data_date, admitted_at, publication_id)`."""
    first = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1)
    series = rt.ok(ReadSchedulePublication(publication_id=first))["series_id"]
    successor = rt.publish(
        monkeypatch,
        w,
        [Activity("A-1", name="Corrected")],
        data_date=D1,
        series_id=series,
        supersedes=first,
    )
    activity = rt.ok(ListScheduleActivities(publication_id=first))["activities"][0]
    history = rt.ok(
        ReadScheduleActivityHistory(schedule_activity_id=activity["schedule_activity_id"])
    )
    assert [o["publication_id"] for o in history["observations"]] == [first, successor]


def test_issue_counts_are_limited_to_the_accepted_run(rt: ScheduleRuntime, w: World) -> None:
    """RR1-I01: a partial publication whose first attempt stored issues, then lost its lease."""
    publication, lease, result = _staged(
        rt, w, _activities("P-1", "P-2"), outcome=SchedulePublicationStatus.PARTIAL
    )
    p = w.principal
    identity = ScheduleParserIdentity.from_parse_result(result)
    first = _repository(rt, lambda r: r.start_parser_run(p, publication, lease, identity).run)
    _repository(rt, lambda r: r.insert_rows(p, first.parser_run_id, lease, result.rows))
    _repository(
        rt, lambda r: r.insert_issues(p, publication, lease, first.parser_run_id, result.issues)
    )
    _expire(rt, lease.operation_id)
    job = _claim(rt, p)
    retry = ScheduleLease(job.operation_id, OWNER, job.attempt)
    assert retry.attempt == 2
    _repository(rt, lambda r: r.begin_processing(p, publication, retry))
    _repository(
        rt,
        lambda r: r.pin_document(
            p, publication, retry, result.document_sha256, result.document_size_bytes
        ),
    )
    second = _repository(rt, lambda r: r.start_parser_run(p, publication, retry, identity).run)
    assert second.parser_run_id != first.parser_run_id
    _repository(rt, lambda r: r.insert_rows(p, second.parser_run_id, retry, result.rows))
    _repository(
        rt, lambda r: r.insert_issues(p, publication, retry, second.parser_run_id, result.issues)
    )
    _repository(
        rt,
        lambda r: r.finish_parser_run(
            p,
            second.parser_run_id,
            retry,
            parsed=result.counts,
            parse_result_sha256=parse_result_sha256(result),
            failure_code=None,
        ),
    )
    _repository(rt, lambda r: r.canonicalize_batch(p, second.parser_run_id, retry))
    _repository(
        rt,
        lambda r: r.finalize_publication(
            p,
            publication,
            retry,
            ScheduleFinalization(second.parser_run_id, "Synthetic Schedule", D1, D1),
        ),
    )
    assert (
        rt.scalar(
            "SELECT count(*) FROM knowledge.schedule_import_issues WHERE publication_id = :p",
            p=publication,
        )
        == 2
    )
    read = rt.ok(ReadSchedulePublication(publication_id=publication))
    assert read["status"] == "partial"
    assert read["accepted_parser_run_id"] == second.parser_run_id
    assert read["issue_counts"] == {"invalid_date": 1}
    assert read["counts"]["issue"] == 1
    assert [run["status"] for run in read["parser_runs"]] == ["failed", "parsed"]


def test_a_failed_publication_counts_every_issue(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed, *_ = _failed_publication(rt, w, monkeypatch)
    read = rt.ok(ReadSchedulePublication(publication_id=failed))
    assert read["issue_counts"] == {"unsupported_media_type": 1}
    assert read["counts"]["issue"] == 1
    assert read["accepted_parser_run_id"] is None
    assert read["job"]["state"] == "succeeded"


def test_exhausted_job_reads_effective_failed_without_writing(
    rt: ScheduleRuntime, w: World
) -> None:
    """R2 section 10.6: the job abandoned its last attempt; reads derive `failed`, write nothing."""
    object_id, version_id = rt.source_object(w)
    admitted = rt.import_(w, object_id, version_id)
    publication = admitted["publication_id"]
    for attempt in (1, 2, 3):
        job = _claim(rt)
        assert job.attempt == attempt
        _expire(rt, job.operation_id)
    before = cpm_snapshot(rt.engine)
    read = rt.ok(ReadSchedulePublication(publication_id=publication))
    assert (read["status"], read["persisted_status"]) == ("failed", "queued")
    assert read["job"]["state"] == "failed"
    assert read["job"]["attempt_count"] == read["job"]["max_attempts"] == 3
    assert _disclosure(read)["coverage"]["state"] == "unsupported"
    listed = rt.ok(ListSchedulePublications(series_id=admitted["series_id"], status="failed"))
    assert [p["publication_id"] for p in listed["publications"]] == [publication]
    assert listed["publications"][0]["persisted_status"] == "queued"
    assert not rt.ok(ListSchedulePublications(series_id=admitted["series_id"], status="queued"))[
        "publications"
    ]
    assert cpm_snapshot(rt.engine) == before


# ---- reads: payloads, eligibility, ordering ------------------------------------------------


def test_publication_read_payload(rt: ScheduleRuntime, scene: Scene, w: World) -> None:
    read = rt.ok(ReadSchedulePublication(publication_id=scene.first))
    assert read["series_id"] == scene.series
    assert (read["project_id"], read["enrollment_id"]) == (w.project, w.enrollment)
    assert (read["status"], read["persisted_status"]) == ("complete", "complete")
    assert read["counts"] == {"page": 1, "row": 2, "activity": 2, "ambiguous_row": 0, "issue": 0}
    assert read["issue_counts"] == {}
    assert read["data_date"] == D1.isoformat()
    assert read["job"]["state"] == "succeeded"
    (run,) = read["parser_runs"]
    assert (run["status"], run["parser_name"], run["profile_id"]) == (
        "parsed",
        "cpm-workbench-full-parser",
        "p6_full_v1",
    )
    assert run["parser_run_id"] == read["accepted_parser_run_id"]
    assert len(read["document_sha256"]) == 64
    rendered = json.dumps({k: v for k, v in read.items() if k != "__disclosure__"})
    for absent in ("native_locator", "locator", "/synthetic/", "created_at", "request_digest"):
        assert absent not in rendered


def test_activities_list_serves_the_accepted_run_in_schedule_order(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    activities = [
        Activity("Z-9", path=("Phase 1",), start=D1, finish=D2),
        Activity(
            "A-1",
            row_type=ScheduleRowType.MILESTONE,
            path=("Phase 1", "Sub"),
            od="0",
            rd="0",
            start=D2,
            finish=D2,
        ),
        Activity("M-5", path=("Phase 2",), start=None, finish=D3),
    ]
    publication = rt.publish(monkeypatch, w, activities, data_date=D1)
    answer = rt.ok(ListScheduleActivities(publication_id=publication))
    rows = answer["activities"]
    # Published schedule order (row ordinal), not ID order.
    assert [row["published_activity_id"] for row in rows] == ["Z-9", "A-1", "M-5"]
    assert [row["row_ordinal"] for row in rows] == [1, 2, 3]
    assert rows[1]["row_type"] == "milestone"
    assert rows[0]["original_duration"] == {"state": "published_value", "value": "10.000"}
    assert rows[2]["start"] == {"state": "published_blank", "value": None, "marker": None}
    assert rows[0]["provenance"]["page_number"] == 1
    assert len(rows[0]["provenance"]["bbox_normalized"]) == 4

    def ids(**filters: Any) -> list[str]:  # noqa: ANN401
        found = rt.ok(ListScheduleActivities(publication_id=publication, **filters))
        return [row["published_activity_id"] for row in found["activities"]]

    assert ids(row_type="milestone") == ["A-1"]
    assert ids(row_type="activity") == ["Z-9", "M-5"]
    assert ids(hierarchy_prefix=("Phase 1",)) == ["Z-9", "A-1"]
    assert ids(hierarchy_prefix=("Phase 1", "Sub")) == ["A-1"]
    assert ids(hierarchy_prefix=("Phase",)) == []
    # A date bound matches only a published value: M-5's blank Start never does.
    assert ids(start_from=D1.isoformat()) == ["Z-9", "A-1"]
    assert ids(start_to=D1.isoformat()) == ["Z-9"]
    assert ids(finish_from=D3.isoformat(), finish_to=D3.isoformat()) == ["M-5"]


def test_activities_and_changes_need_a_complete_or_partial_publication(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = rt.publish(
        monkeypatch,
        w,
        _activities("R-1"),
        data_date=D1,
        outcome=SchedulePublicationStatus.REVIEW_REQUIRED,
    )
    series = rt.ok(ReadSchedulePublication(publication_id=review))["series_id"]
    partial = rt.publish(
        monkeypatch,
        w,
        _activities("R-1"),
        data_date=D2,
        outcome=SchedulePublicationStatus.PARTIAL,
        series_id=series,
    )
    assert rt.refused(ListScheduleActivities(publication_id=review)) == ("conflict", ["status"])
    assert rt.refused(
        ListScheduleChanges(from_publication_id=review, to_publication_id=partial)
    ) == ("conflict", ["status"])
    served = rt.ok(ListScheduleActivities(publication_id=partial))
    assert [row["published_activity_id"] for row in served["activities"]] == ["R-1"]
    disclosure = _disclosure(served)
    assert disclosure["coverage"]["state"] == "partially_processed"
    assert disclosure["partial_result"] is True


def test_changes_eligibility_refusals(
    rt: ScheduleRuntime, scene: Scene, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_series = rt.publish(
        monkeypatch, w, _activities("A-1"), data_date=D3, series_name="Other Series"
    )
    pair = {"from_publication_id": scene.first, "to_publication_id": scene.second}
    assert rt.ok(ListScheduleChanges(**pair))["algorithm_version"] == (
        "cpm-workbench-full-delta-v1"
    )
    for refused_pair in (
        {"from_publication_id": scene.second, "to_publication_id": scene.first},  # reversed
        {"from_publication_id": scene.first, "to_publication_id": scene.first},  # equal
        {"from_publication_id": scene.first, "to_publication_id": other_series},  # series
    ):
        assert rt.refused(ListScheduleChanges(**refused_pair)) == (
            "invalid_request",
            ["to_publication_id"],
        )
    assert rt.refused(
        ListScheduleChanges(
            from_publication_id=_ABSENT["publication"], to_publication_id=scene.second
        )
    ) == ("not_found", ["from_publication_id"])


def test_changes_report_every_kind_with_reintroduced(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = rt.publish(monkeypatch, w, _activities("X-1", "Y-2"), data_date=D1)
    series = rt.ok(ReadSchedulePublication(publication_id=first))["series_id"]
    second = rt.publish(monkeypatch, w, _activities("Y-2"), data_date=D2, series_id=series)
    third = rt.publish(
        monkeypatch,
        w,
        [
            Activity("X-1"),
            Activity("Y-2", od="12.500", start=date(2026, 5, 1), path=("Other WBS",), rd=None),
            Activity("Z-3"),
        ],
        data_date=D3,
        series_id=series,
    )
    answer = rt.ok(ListScheduleChanges(from_publication_id=second, to_publication_id=third))
    kinds = [(c["published_activity_id"], c["change_kind"], c["field"]) for c in answer["changes"]]
    assert kinds == [
        ("X-1", "reintroduced", None),
        ("Y-2", "original_duration_changed", "original_duration"),
        ("Y-2", "start_changed", "start"),
        ("Y-2", "hierarchy_changed", "hierarchy"),
        ("Y-2", "field_state_changed", "remaining_duration"),
        ("Z-3", "added", None),
    ]
    by_kind = {c["change_kind"]: c for c in answer["changes"]}
    assert by_kind["original_duration_changed"]["delta_source_units"] == "2.500"
    assert by_kind["start_changed"]["delta_calendar_days"] == -3
    assert by_kind["field_state_changed"]["before"] == {
        "state": "published_value",
        "value": "5.000",
    }
    assert by_kind["field_state_changed"]["after"] == {"state": "published_blank", "value": None}
    assert by_kind["field_state_changed"]["delta_source_units"] is None
    assert by_kind["reintroduced"]["after"] == {
        "activity_name": "Synthetic activity",
        "row_type": "activity",
    }
    assert set(answer["counts_by_kind"]) == {
        "added",
        "removed",
        "reintroduced",
        "renamed",
        "row_type_changed",
        "original_duration_changed",
        "remaining_duration_changed",
        "start_changed",
        "finish_changed",
        "hierarchy_changed",
        "field_state_changed",
    }
    assert answer["from"] == {
        "publication_id": second,
        "publication_role": "update",
        "baseline_kind": None,
        "data_date": D2.isoformat(),
    }
    disclosure = _disclosure(answer)
    assert disclosure["trust"]["basis"] == [
        "cpm-workbench-full-parser",
        "p6_full_v1",
        "cpm-workbench-full-delta-v1",
    ]
    assert len(disclosure["source_references"]) == 2


def test_changes_pagination_is_stable_across_pages(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = [Activity(f"K-{n:03d}") for n in range(20)]
    after = [
        Activity(f"K-{n:03d}", name="Renamed", finish=date(2026, 5, 20)) for n in range(0, 20, 2)
    ] + [Activity(f"N-{n:03d}") for n in range(5)]
    first = rt.publish(monkeypatch, w, before, data_date=D1)
    series = rt.ok(ReadSchedulePublication(publication_id=first))["series_id"]
    second = rt.publish(monkeypatch, w, after, data_date=D2, series_id=series)
    pair = {"from_publication_id": first, "to_publication_id": second}
    full = rt.ok(ListScheduleChanges(**pair, page_size=100))
    assert len(full["changes"]) == 10 * 2 + 10 + 5
    for kind in (None, "renamed"):
        expected = [c for c in full["changes"] if kind is None or c["change_kind"] == kind]
        pages: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = rt.ok(ListScheduleChanges(**pair, page_size=7, change_kind=kind, cursor=cursor))
            assert page["counts_by_kind"] == full["counts_by_kind"]
            pages.extend(page["changes"])
            truncation = _disclosure(page)["truncation"]
            cursor = truncation["next_cursor"]
            if cursor is None:
                assert truncation["is_truncated"] is False
                break
            assert truncation == {
                "is_truncated": True,
                "reason": "page_size_reached",
                "next_cursor": cursor,
            }
        assert pages == expected


def _publish_rows(
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    **options: Any,  # noqa: ANN401
) -> str:
    return rt.publish(
        monkeypatch, w, [Activity(f"R-{n:04d}") for n in range(count)], data_date=D1, **options
    )


def test_page_of_100_and_101_rows(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    exact = _publish_rows(rt, w, monkeypatch, 100)
    series = rt.ok(ReadSchedulePublication(publication_id=exact))["series_id"]
    one_more = rt.publish(
        monkeypatch,
        w,
        [Activity(f"R-{n:04d}") for n in range(101)],
        data_date=D2,
        series_id=series,
    )
    page = rt.ok(ListScheduleActivities(publication_id=exact, page_size=100))
    assert len(page["activities"]) == 100
    assert _disclosure(page)["truncation"] == {
        "is_truncated": False,
        "reason": None,
        "next_cursor": None,
    }
    first = rt.ok(ListScheduleActivities(publication_id=one_more, page_size=100))
    assert len(first["activities"]) == 100
    truncation = _disclosure(first)["truncation"]
    assert truncation["is_truncated"] is True
    assert _disclosure(first)["partial_result"] is True
    rest = rt.ok(
        ListScheduleActivities(
            publication_id=one_more, page_size=100, cursor=truncation["next_cursor"]
        )
    )
    assert [row["row_ordinal"] for row in rest["activities"]] == [101]
    assert _disclosure(rest)["truncation"]["next_cursor"] is None
    # The default page is 25.
    assert rt.ok(ListScheduleActivities(publication_id=one_more))["page_size"] == 25


def _binding(principal: str, command: Any, order: ScheduleCursorOrder, page_size: int) -> str:  # noqa: ANN401
    return schedule_cursor_binding(
        capability=command.capability.value,
        principal_id=principal,
        purpose="schedule_read",
        request=schedules_module._request_of(command),
        page_size=page_size,
        order=order,
    )


@pytest.mark.parametrize(
    "case", ["malformed", "rebound", "expired", "future", "offset_out_of_range"]
)
def test_cursor_conflicts(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    publication = _publish_rows(rt, w, monkeypatch, 5)
    series = rt.ok(ReadSchedulePublication(publication_id=publication))["series_id"]
    later = rt.publish(
        monkeypatch, w, [Activity("R-0000", name="Renamed")], data_date=D2, series_id=series
    )
    issued = datetime.now(UTC)
    rt.now = issued
    first = rt.ok(ListScheduleActivities(publication_id=publication, page_size=2))
    cursor = _disclosure(first)["truncation"]["next_cursor"]
    assert cursor is not None
    command: Command = ListScheduleActivities(
        publication_id=publication, page_size=2, cursor=cursor
    )
    if case == "malformed":
        command = ListScheduleActivities(
            publication_id=publication, page_size=2, cursor="!" + cursor[1:]
        )
    elif case == "rebound":
        command = ListScheduleActivities(
            publication_id=publication, page_size=2, row_type="activity", cursor=cursor
        )
    elif case == "expired":
        rt.now = issued + timedelta(seconds=301)
    elif case == "future":
        rt.now = issued - timedelta(seconds=6)
    else:
        changes = ListScheduleChanges(
            from_publication_id=publication, to_publication_id=later, page_size=2
        )
        forged = encode_schedule_cursor(
            binding=_binding(PRINCIPAL, changes, ScheduleCursorOrder.CHANGES, 2),
            order=ScheduleCursorOrder.CHANGES,
            position=(7,),
            issued_at=issued,
        )
        in_range = encode_schedule_cursor(
            binding=_binding(PRINCIPAL, changes, ScheduleCursorOrder.CHANGES, 2),
            order=ScheduleCursorOrder.CHANGES,
            position=(5,),
            issued_at=issued,
        )
        # 5 changes (1 rename, 4 removals): offset 5 is the end, 7 is beyond it.
        assert (
            rt.ok(
                ListScheduleChanges(
                    from_publication_id=publication,
                    to_publication_id=later,
                    page_size=2,
                    cursor=in_range,
                )
            )["changes"]
            == []
        )
        command = ListScheduleChanges(
            from_publication_id=publication, to_publication_id=later, page_size=2, cursor=forged
        )
    assert rt.refused(command) == ("conflict", ["cursor"])
    # Non-vacuous: the untouched cursor continues at the issuing instant.
    rt.now = issued
    assert rt.ok(ListScheduleActivities(publication_id=publication, page_size=2, cursor=cursor))


def test_a_bad_cursor_is_refused_before_the_root_is_read(rt: ScheduleRuntime, w: World) -> None:
    """R7-F10: the cursor is decoded first, so an absent root and a bad cursor answer `cursor`."""
    for command in (
        ListScheduleSeries(project_id=_ABSENT["project"], cursor="bad"),
        ListSchedulePublications(series_id=_ABSENT["series"], cursor="bad"),
        ListScheduleActivities(publication_id=_ABSENT["publication"], cursor="bad"),
        ReadScheduleActivityHistory(schedule_activity_id=_ABSENT["activity"], cursor="bad"),
        ListScheduleChanges(
            from_publication_id=_ABSENT["publication"],
            to_publication_id="spub_absentroot0002",
            cursor="bad",
        ),
    ):
        assert rt.refused(command) == ("conflict", ["cursor"])


def test_forged_cursor_position_stays_inside_the_callers_partition(
    rt: ScheduleRuntime, w: World, q: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forged position under the caller's own binding skips only among its own rows."""
    mine = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1)
    rt.publish(monkeypatch, q, _activities("B-1"), data_date=D1)
    series = rt.ok(ReadSchedulePublication(publication_id=mine))["series_id"]
    command = ListSchedulePublications(series_id=series)
    forged = encode_schedule_cursor(
        binding=_binding(PRINCIPAL, command, ScheduleCursorOrder.PUBLICATIONS, 25),
        order=ScheduleCursorOrder.PUBLICATIONS,
        position=(datetime(2099, 1, 1, tzinfo=UTC), "spub_zzzzzzzz9999"),
        issued_at=datetime.now(UTC),
    )
    answer = rt.ok(ListSchedulePublications(series_id=series, cursor=forged))
    assert [p["publication_id"] for p in answer["publications"]] == [mine]
    series_forged = encode_schedule_cursor(
        binding=_binding(
            PRINCIPAL, ListScheduleSeries(project_id=w.project), ScheduleCursorOrder.SERIES, 25
        ),
        order=ScheduleCursorOrder.SERIES,
        position=(datetime(2099, 1, 1, tzinfo=UTC), "sser_zzzzzzzz9999"),
        issued_at=datetime.now(UTC),
    )
    listed = rt.ok(ListScheduleSeries(project_id=w.project, cursor=series_forged))
    assert [s["series_id"] for s in listed["series"]] == [series]


# ---- baselines (section 3.11) ---------------------------------------------------------------


def test_series_latest_update_ignores_baselines_and_references(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1)
    series = rt.ok(ReadSchedulePublication(publication_id=update))["series_id"]
    baseline = rt.publish(
        monkeypatch,
        w,
        _activities("A-1"),
        data_date=D2,
        series_id=series,
        role="baseline",
        baseline_kind="working",
    )
    rt.publish(monkeypatch, w, _activities("A-1"), data_date=D3, series_id=series, role="reference")
    (row,) = rt.ok(ListScheduleSeries(project_id=w.project))["series"]
    assert row["publication_count"] == 3
    assert row["latest_update"] == {"publication_id": update, "data_date": D1.isoformat()}
    roles = {
        p["publication_id"]: (p["publication_role"], p["baseline_kind"])
        for p in rt.ok(ListSchedulePublications(series_id=series))["publications"]
    }
    assert roles[baseline] == ("baseline", "working")
    assert {p for p, (role, _) in roles.items() if role == "baseline"} == {baseline}
    only_baselines = rt.ok(ListSchedulePublications(series_id=series, publication_role="baseline"))
    assert [p["publication_id"] for p in only_baselines["publications"]] == [baseline]
    # The caller chooses any pair of roles; an update against its baseline works.
    assert rt.ok(ListScheduleChanges(from_publication_id=update, to_publication_id=baseline))


def test_first_publication_is_not_a_baseline(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D2)
    series = rt.ok(ReadSchedulePublication(publication_id=first))["series_id"]
    read = rt.ok(ReadSchedulePublication(publication_id=first))
    assert (read["publication_role"], read["baseline_kind"]) == ("update", None)
    # A later update with an older Data Date does not make the first a baseline,
    # and "previous update" names nothing either: a pair is always explicit.
    older = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1, series_id=series)
    listed = rt.ok(ListSchedulePublications(series_id=series))["publications"]
    assert {p["publication_role"] for p in listed} == {"update"}
    (row,) = rt.ok(ListScheduleSeries(project_id=w.project))["series"]
    assert row["latest_update"]["publication_id"] == first
    assert rt.ok(ListScheduleChanges(from_publication_id=older, to_publication_id=first))


def test_publications_list_orders_newest_admission_first_and_filters_effective_status(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D2)
    series = rt.ok(ReadSchedulePublication(publication_id=first))["series_id"]
    second = rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1, series_id=series)
    failed, *_ = _failed_publication(rt, w, monkeypatch, series_id=series, series_name=None)
    listed = rt.ok(ListSchedulePublications(series_id=series))["publications"]
    assert [p["publication_id"] for p in listed] == [failed, second, first]
    assert [p["status"] for p in listed] == ["failed", "complete", "complete"]
    assert listed[1]["parser_name"] == "cpm-workbench-full-parser"
    assert listed[0]["parser_name"] is None
    complete = rt.ok(ListSchedulePublications(series_id=series, status="complete"))
    assert [p["publication_id"] for p in complete["publications"]] == [second, first]
    paged = rt.ok(ListSchedulePublications(series_id=series, page_size=1))
    cursor = _disclosure(paged)["truncation"]["next_cursor"]
    following = rt.ok(ListSchedulePublications(series_id=series, page_size=1, cursor=cursor))
    assert [p["publication_id"] for p in following["publications"]] == [second]


# ---- disclosure (section 3.8) -----------------------------------------------------------------


def test_disclosure_per_read(
    rt: ScheduleRuntime, scene: Scene, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reference(publication: str) -> dict[str, str]:
        read = rt.ok(ReadSchedulePublication(publication_id=publication))
        return {
            "source_id": w.source,
            "source_object_id": read["source_object_id"],
            "version_id": read["source_version_id"],
        }

    processed = {
        "state": "processed",
        "eligible": 1,
        "processed": 1,
        "quarantined": 0,
        "unsupported": 0,
    }
    both = {**processed, "eligible": 2, "processed": 2}
    expected: dict[Capability, tuple[dict[str, Any], list[str]]] = {
        Capability.SCHEDULE_SERIES_LIST: (processed, [scene.second]),
        Capability.SCHEDULE_PUBLICATIONS_LIST: (both, [scene.first, scene.second]),
        Capability.SCHEDULE_PUBLICATIONS_READ: (processed, [scene.first]),
        Capability.SCHEDULE_ACTIVITIES_LIST: (processed, [scene.first]),
        Capability.SCHEDULE_ACTIVITIES_HISTORY: (both, [scene.first, scene.second]),
        Capability.SCHEDULE_CHANGES_LIST: (both, [scene.first, scene.second]),
    }
    for capability, command in _read_commands(scene).items():
        coverage, publications = expected[capability]
        disclosure = _disclosure(rt.ok(command))
        assert disclosure["coverage"] == coverage, capability
        assert disclosure["scope"] == {"source_ids": [w.source], "enrollment_ids": [w.enrollment]}
        assert disclosure["trust"]["level"] == "source_bound_derived"
        assert disclosure["trust"]["basis"][:2] == ["cpm-workbench-full-parser", "p6_full_v1"]
        assert disclosure["freshness"]["state"] == "current_for_observed_version"
        assert disclosure["source_references"] == sorted(
            (reference(p) for p in publications),
            key=lambda ref: (ref["source_id"], ref["source_object_id"], ref["version_id"]),
        ), capability
        assert disclosure["truncation"]["is_truncated"] is False
        assert disclosure["partial_result"] is False
        assert disclosure["classification"] == "private_local"
        assert disclosure["cloud_eligible"] is False
    # The empty reference set is an ordinary answer: `eligible`, every count 0,
    # never `not_enrolled` (R7-F08) -- a Project with no Series, a filter that
    # matches no publication, an activity filter on an eligible publication.
    rt.execute(
        "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, created_at, "
        "updated_at) VALUES ('prj_emptyproject01', :p, 'Empty', now(), now(), now())",
        p=PRINCIPAL,
    )
    empty = {"state": "eligible", "eligible": 0, "processed": 0, "quarantined": 0, "unsupported": 0}
    for command in (
        ListScheduleSeries(project_id="prj_emptyproject01"),
        ListSchedulePublications(series_id=scene.series, status="review_required"),
    ):
        disclosure = _disclosure(rt.ok(command))
        assert disclosure["coverage"] == empty
        assert disclosure["scope"] == {"source_ids": [], "enrollment_ids": []}
        assert disclosure["source_references"] == []
        assert disclosure["partial_result"] is False
    # A filtered-empty activity page still references its one publication.
    filtered = rt.ok(ListScheduleActivities(publication_id=scene.first, row_type="milestone"))
    assert filtered["activities"] == []
    assert _disclosure(filtered)["coverage"] == processed
    # A Series whose only publication is a baseline has no latest update: empty set.
    rt.publish(
        monkeypatch,
        w,
        _activities("A-1"),
        data_date=D1,
        series_name="Baseline Only",
        role="baseline",
        baseline_kind="contract",
    )
    listed = rt.ok(ListScheduleSeries(project_id=w.project))
    assert [s["latest_update"] is None for s in listed["series"]] == [True, False]
    assert _disclosure(listed)["coverage"] == processed


def test_series_list_orders_newest_first_with_counts(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ["Series One", "Series Two", "Series Three"]
    for name in names:
        rt.publish(monkeypatch, w, _activities("A-1"), data_date=D1, series_name=name)
    listed = rt.ok(ListScheduleSeries(project_id=w.project, page_size=2))
    assert [s["name"] for s in listed["series"]] == ["Series Three", "Series Two"]
    cursor = _disclosure(listed)["truncation"]["next_cursor"]
    rest = rt.ok(ListScheduleSeries(project_id=w.project, page_size=2, cursor=cursor))
    assert [s["name"] for s in rest["series"]] == ["Series One"]
    assert all(s["publication_count"] == 1 for s in listed["series"] + rest["series"])
