"""P6 XER S7-3: admission from a files workspace and the `schedule` worker's P6 path.

Schedule XER import contract (`docs/architecture/schedule-xer-import-contract.md`)
sections 9.1, 9.3, 10.2, 11.1-11.3 and the S7-3 acceptance C1-C5. Every test
admits synthetic XER bytes (`tests/fixtures/schedule_p6_xer.py`) written into
a real `FilesystemFileWorkspaceStore` under `tmp_path`, through
`ScheduleP6Application.import_p6`, then claims the `schedule_jobs` row with a
real lease and drives `process_schedule_publication`. The parse runs in the
real contained child unless a test replaces the `_parse_p6` seam.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.application.schedule_p6 import ScheduleP6Application
from my_pa.contracts.ports import FileWorkspaceReader, FileWorkspaceStore
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ScheduleImportRequest,
    SchedulePublicationRole,
    normalize_series_name,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.p6.frame import frame_object
from my_pa.domain.schedule.p6.model import P6Issue, P6IssueCode, P6Severity
from my_pa.domain.schedule.p6_import import P6RenumberCandidate, match_p6_activities
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.jobs import schedule_p6 as p6_handler
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.jobs.schedule_parser_child import P6_FRAME_MAGIC
from my_pa.infrastructure.jobs.schedule_parser_process import (
    ChildExchange,
    IsolatedP6Parse,
    ParsedP6Result,
    classify_p6_exchange,
    run_isolated_p6_parse,
)
from my_pa.infrastructure.jobs.worker import JobExecutionError, run_worker
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, LeasedJob, claim_job
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_p6 import SqlAlchemyScheduleP6UnitOfWork
from tests.fixtures import schedule_p6_xer as xer

pytestmark = pytest.mark.database

P: Final = "prn_sp6work0001"
Q: Final = "prn_sp6work0002"
PROJECT: Final = "prj_sp6work0001"
FOREIGN_PROJECT: Final = "prj_sp6work0002"
OWNER: Final = "p6-worker-a"
LEASE_SECONDS: Final = 300
WORKSPACE: Final = "syn"
SIXTEEN_MIB: Final = 16_777_216
P6_TABLES: Final = (
    "schedule_p6_snapshots",
    "schedule_p6_projects",
    "schedule_p6_wbs",
    "schedule_p6_activities",
    "schedule_p6_relationships",
    "schedule_p6_calendars",
    "schedule_p6_field_values",
    "schedule_p6_observed_fields",
    "schedule_publications",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_import_issues",
    "schedule_activities",
    "schedule_series",
)


# ---- the world ----------------------------------------------------------------------


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
    engine: Engine
    root: Path
    store: FilesystemFileWorkspaceStore
    enabled: bool = True

    def application(self, store: FileWorkspaceStore | None = None) -> ScheduleP6Application:
        spaces: Mapping[str, FileWorkspaceStore] = {WORKSPACE: store or self.store}
        return ScheduleP6Application(
            lambda: SqlAlchemyScheduleP6UnitOfWork(self.engine),
            spaces.get,
            enabled=lambda: self.enabled,
        )

    def put(self, path: str, data: bytes) -> dict[str, object]:
        """Write `path` and return the request fields that name its current bytes."""
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


@pytest.fixture
def w(db_engine: Engine, tmp_path: Path) -> World:
    _project(db_engine, P, PROJECT)
    _project(db_engine, Q, FOREIGN_PROJECT)
    root = tmp_path / "workspace"
    root.mkdir()
    return World(db_engine, root, FilesystemFileWorkspaceStore(root))


def _request(
    named: Mapping[str, object], key: str = "p6-import-0001", **extra: object
) -> dict[str, object]:
    request: dict[str, object] = {
        "project_id": PROJECT,
        "series_name": "Master Schedule",
        "idempotency_key": key,
        **named,
    }
    request.update(extra)
    return request


def _import(
    w: World,
    data: bytes,
    *,
    path: str = "exports/schedule.xer",
    key: str = "p6-import-0001",
    principal: str = P,
    **extra: object,
) -> dict[str, Any]:
    return w.application().import_p6(principal, _request(w.put(path, data), key, **extra))


def _claim(engine: Engine, principal: str = P) -> LeasedJob:
    with engine.begin() as c:
        job = claim_job(
            c, owner=OWNER, lease_seconds=LEASE_SECONDS, principal_id=principal, plane=SCHEDULE_JOBS
        )
    assert job is not None
    return job


def _work(engine: Engine, *, enabled: bool = True, principal: str = P) -> None:
    process_schedule_publication(engine, _claim(engine, principal), OWNER, p6_enabled=enabled)


def _one(engine: Engine, sql: str, **params: object) -> Any:  # noqa: ANN401 - a test read
    with engine.connect() as c:
        return c.execute(text(sql), params).one()


def _all(engine: Engine, sql: str, **params: object) -> list[Any]:
    with engine.connect() as c:
        return list(c.execute(text(sql), params).all())


def _status(engine: Engine, publication_id: str) -> str:
    return str(
        _one(
            engine,
            "SELECT status FROM knowledge.schedule_publications WHERE publication_id = :p",
            p=publication_id,
        )[0]
    )


def _snapshot(engine: Engine) -> dict[str, list[str]]:
    """Every row of the P6 and S5 tables, as comparable text (leases excluded)."""
    found: dict[str, list[str]] = {}
    with engine.connect() as c:
        for table in P6_TABLES:
            rows = c.execute(text(f"SELECT * FROM knowledge.{table}")).all()  # noqa: S608
            found[table] = sorted(repr(tuple(row)) for row in rows)
        found["schedule_jobs"] = [
            repr(tuple(row))
            for row in c.execute(
                text(
                    "SELECT operation_id, state, attempt_count FROM knowledge.schedule_jobs "
                    "ORDER BY operation_id"
                )
            ).all()
        ]
    return found


def _refused(
    call: Callable[[], object], error: type[ApplicationError], *details: SafeDetail
) -> None:
    with pytest.raises(error) as raised:
        call()
    assert raised.value.safe_details == details


def _full() -> bytes:
    return xer.build("full_valid").data


def _model_bytes(model: xer.Model) -> bytes:
    return xer.encode(xer.layout(model).lines)


# ---- C1: admission refusals, replay, already_present ----------------------------------


def test_admission_refuses_a_moved_version(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    (w.root / "exports/schedule.xer").write_bytes(_full() + b"\r\n")
    before = _snapshot(w.engine)
    _refused(
        lambda: w.application().import_p6(P, _request(named)),
        ConflictError,
        SafeDetail.EXPECTED_VERSION,
    )
    assert _snapshot(w.engine) == before


class _MovingReader(FileWorkspaceReader):
    """A real held file whose bytes change on disk right after they are read."""

    def __init__(self, inner: FileWorkspaceReader, target: Path) -> None:
        self._inner, self._target = inner, target
        self.size, self.version = inner.size, inner.version

    def read_range(self, start: int, length: int) -> Iterator[bytes]:
        chunks = list(self._inner.read_range(start, length))
        if length:
            with self._target.open("ab") as handle:
                handle.write(b"\r\n")
        return iter(chunks)

    def sha256(self) -> str:
        return self._inner.sha256()

    def close(self) -> None:
        self._inner.close()


class _MovingStore(FilesystemFileWorkspaceStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._root_path = root

    def open_download(self, path: str, *, expected_version: str) -> FileWorkspaceReader:
        inner = super().open_download(path, expected_version=expected_version)
        return _MovingReader(inner, self._root_path / path)


def test_admission_rereads_the_fingerprint_after_the_bytes(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    before = _snapshot(w.engine)
    _refused(
        lambda: w.application(_MovingStore(w.root)).import_p6(P, _request(named)),
        ConflictError,
        SafeDetail.EXPECTED_VERSION,
    )
    assert _snapshot(w.engine) == before


def test_admission_refuses_a_sha256_mismatch(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    named["expected_sha256"] = hashlib.sha256(b"other bytes").hexdigest()
    before = _snapshot(w.engine)
    _refused(
        lambda: w.application().import_p6(P, _request(named)),
        ConflictError,
        SafeDetail.EXPECTED_SHA256,
    )
    assert _snapshot(w.engine) == before


class _NoReadStore(FilesystemFileWorkspaceStore):
    """Counts bytes read; the too-large refusal must come before any."""

    read_bytes = 0

    def open_download(self, path: str, *, expected_version: str) -> FileWorkspaceReader:
        inner = super().open_download(path, expected_version=expected_version)
        outer = self

        class Counting(FileWorkspaceReader):
            size, version = inner.size, inner.version

            def read_range(self, start: int, length: int) -> Iterator[bytes]:
                outer.read_bytes += length
                return inner.read_range(start, length)

            def sha256(self) -> str:
                return inner.sha256()

            def close(self) -> None:
                inner.close()

        return Counting()


def test_admission_refuses_a_file_too_large_before_reading_it(w: World) -> None:
    data = _full()
    big = data[:-4] + b"\r\n" * ((SIXTEEN_MIB + 1 - len(data)) // 2 + 1) + b"%E\r\n"
    assert len(big) > SIXTEEN_MIB
    named = w.put("exports/big.xer", big)
    store = _NoReadStore(w.root)
    _refused(
        lambda: w.application(store).import_p6(P, _request(named)),
        UnsupportedError,
        SafeDetail.MAX_BYTES,
    )
    assert store.read_bytes == 0


def test_admission_sniffs_the_bytes_and_ignores_the_extension(w: World) -> None:
    pdf = b"%PDF-1.7\n%synthetic\n%%EOF\n"
    _refused(
        lambda: _import(w, pdf, path="exports/schedule.xer"),
        UnsupportedError,
        SafeDetail.SOURCE_FORMAT,
    )
    # No `%E` at the end is not an XER either, whatever the name says.
    _refused(
        lambda: _import(w, _full().replace(b"%E\r\n", b""), path="exports/cut.xer"),
        UnsupportedError,
        SafeDetail.SOURCE_FORMAT,
    )
    answer = _import(w, _full(), path="exports/schedule.pdf")
    assert answer["outcome"] == "created"


def test_admission_refuses_xml_until_its_slice(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    named["format"] = "p6_xml"
    _refused(
        lambda: w.application().import_p6(P, _request(named)), UnsupportedError, SafeDetail.FORMAT
    )


def test_admission_inputs_are_strict(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "role": "baseline"}),
        InvalidRequestError,
    )
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "series_id": "sser_x0000001"}),
        InvalidRequestError,
        SafeDetail.SERIES_ID,
    )
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "expected_sha256": "ABC"}),
        InvalidRequestError,
        SafeDetail.EXPECTED_SHA256,
    )
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "workspace_id": "other"}),
        NotFoundError,
        SafeDetail.WORKSPACE_ID,
    )
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "path": "exports/absent.xer"}),
        NotFoundError,
        SafeDetail.PATH,
    )


def _pdf_series(engine: Engine) -> str:
    """A Series holding one PDF publication (admitted through the S5 path)."""
    tag = "sp6pdf"
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.sources (source_id, provider_kind, label, classification, "
                "native_root) VALUES (:s, 'fixture', 'Synthetic', 'synthetic_test', :root)"
            ),
            {"s": f"src_{tag}0001", "root": f"/synthetic/p6/{tag}"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_objects (source_object_id, source_id, kind, "
                "native_locator) VALUES (:o, :s, 'file', '/synthetic/pdf.pdf')"
            ),
            {"o": f"obj_{tag}0001", "s": f"src_{tag}0001"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                "fingerprint, media_type, size_bytes, modified_at) VALUES (:v, :o, :v, "
                "'application/pdf', NULL, now())"
            ),
            {"v": f"ver_{tag}0001", "o": f"obj_{tag}0001"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                "depth, media_types, max_items, max_bytes) VALUES (:e, :s, :p, "
                "'schedule_import', 'policy-v1', 'sp6-pdf', 'synthetic', ARRAY[:o], 0, "
                "ARRAY['application/pdf'], 10, 16777216)"
            ),
            {"e": f"enr_{tag}0001", "s": f"src_{tag}0001", "p": P, "o": f"obj_{tag}0001"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                "VALUES (:e, :o)"
            ),
            {"e": f"enr_{tag}0001", "o": f"obj_{tag}0001"},
        )
    request = ScheduleImportRequest(
        project_id=PROJECT,
        series_id=None,
        series_name=normalize_series_name("PDF Schedule"),
        enrollment_id=f"enr_{tag}0001",
        source_object_id=f"obj_{tag}0001",
        source_version_id=f"ver_{tag}0001",
        publication_role=SchedulePublicationRole.UPDATE,
        baseline_kind=None,
        expected_data_date=None,
        supersedes_publication_id=None,
        idempotency_key="sp6-pdf-0001",
    )
    with SqlAlchemyScheduleUnitOfWork(engine) as uow:
        admission = uow.schedules.admit_publication(
            P, request, schedule_import_request_digest(P, request)
        )
    return admission.series.series_id


def test_admission_refuses_a_series_holding_a_pdf_publication(w: World) -> None:
    series_id = _pdf_series(w.engine)
    named = w.put("exports/schedule.xer", _full())
    request = {**_request(named), "series_id": series_id}
    del request["series_name"]
    before = _snapshot(w.engine)
    _refused(lambda: w.application().import_p6(P, request), ConflictError, SafeDetail.SERIES_FORMAT)
    assert _snapshot(w.engine) == before


def test_admission_refuses_another_principals_project(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    _refused(
        lambda: w.application().import_p6(P, {**_request(named), "project_id": FOREIGN_PROJECT}),
        NotFoundError,
        SafeDetail.PROJECT_ID,
    )


def test_admission_replays_a_key_and_refuses_it_for_another_request(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    first = w.application().import_p6(P, _request(named))
    again = w.application().import_p6(P, _request(named))
    assert again["outcome"] == "replayed"
    assert again["publication_id"] == first["publication_id"]
    assert again["operation_id"] == first["operation_id"]
    before = _snapshot(w.engine)
    _refused(
        lambda: w.application().import_p6(P, _request(named, series_name="Another Schedule")),
        ConflictError,
        SafeDetail.IDEMPOTENCY_KEY,
    )
    assert _snapshot(w.engine) == before


def test_identical_bytes_are_already_present_and_write_nothing(w: World) -> None:
    first = _import(w, _full())
    before = _snapshot(w.engine)
    again = _import(w, _full(), path="exports/copy.xer", key="p6-import-0002")
    assert again["outcome"] == "already_present"
    assert again["already_present"] is True
    assert again["publication_id"] == first["publication_id"]
    assert _snapshot(w.engine) == before


# ---- C2: snapshot dedup per Principal; the path is stored and never served --------------


def test_the_snapshot_is_stored_once_per_principal(w: World) -> None:
    _import(w, _full())
    _import(w, _full(), key="p6-import-0002", series_name="Second Schedule")
    rows = _all(w.engine, "SELECT principal_id FROM knowledge.schedule_p6_snapshots")
    assert [row[0] for row in rows] == [P]
    publications = _all(
        w.engine,
        "SELECT p6_snapshot_id FROM knowledge.schedule_publications WHERE source_format = 'p6_xer'",
    )
    assert len(publications) == 2 and len({row[0] for row in publications}) == 1
    _import(w, _full(), key="p6-import-0003", principal=Q, project_id=FOREIGN_PROJECT)
    owners = _all(w.engine, "SELECT principal_id FROM knowledge.schedule_p6_snapshots ORDER BY 1")
    assert [row[0] for row in owners] == [P, Q]


def test_the_workspace_path_is_stored_and_never_served(w: World) -> None:
    path = "exports/synthetic-sp6-path-marker.xer"
    named = w.put(path, _full())
    answer = w.application().import_p6(P, _request(named))
    assert "synthetic-sp6-path-marker" not in repr(answer)
    assert "path" not in {key.lower() for key in answer}
    stored = _one(
        w.engine,
        "SELECT p6_workspace_id, p6_workspace_path, p6_workspace_version, source_format, "
        "publication_role FROM knowledge.schedule_publications WHERE publication_id = :p",
        p=answer["publication_id"],
    )
    assert tuple(stored)[:2] == (WORKSPACE, path)
    assert stored[2].startswith("fv1_") and tuple(stored)[3:] == ("p6_xer", "update")
    replay = w.application().import_p6(P, _request(named))
    assert replay["outcome"] == "replayed"
    assert "synthetic-sp6-path-marker" not in repr(replay)


# ---- C3: the worker --------------------------------------------------------------------


def test_a_valid_export_completes_and_links_stable_activities(w: World) -> None:
    answer = _import(w, _full())
    _work(w.engine)
    publication_id = answer["publication_id"]
    assert _status(w.engine, publication_id) == "complete"
    published = _one(
        w.engine,
        "SELECT row_count, activity_count, page_count, ambiguous_row_count, data_date, "
        "document_sha256 FROM knowledge.schedule_publications WHERE publication_id = :p",
        p=publication_id,
    )
    assert tuple(published)[:4] == (4, 4, 0, 0)
    assert published[4] is not None and published[5] == answer["document"]["sha256"]
    linked = _all(
        w.engine,
        "SELECT a.activity_id, s.published_activity_id FROM knowledge.schedule_p6_activities a "
        "JOIN knowledge.schedule_activities s ON s.schedule_activity_id = a.schedule_activity_id "
        "ORDER BY 1",
    )
    assert [row[0] for row in linked] == ["SYN-1000", "SYN-1010", "SYN-1020", "SYN-1030"]
    assert all(row[0] == row[1] for row in linked)
    run = _one(
        w.engine,
        "SELECT profile_id, parser_version, pypdfium2_version, status, row_count "
        "FROM knowledge.schedule_parser_runs WHERE publication_id = :p",
        p=publication_id,
    )
    assert tuple(run) == ("p6_xer_v1", "p6-field-catalogue-v1", None, "parsed", 4)
    counts = {
        table: _one(w.engine, f"SELECT count(*) FROM knowledge.{table}")[0]  # noqa: S608
        for table in (
            "schedule_p6_projects",
            "schedule_p6_wbs",
            "schedule_p6_relationships",
            "schedule_p6_calendars",
            "schedule_p6_observed_fields",
        )
    }
    assert counts["schedule_p6_projects"] == 1
    assert counts["schedule_p6_wbs"] == 4 and counts["schedule_p6_relationships"] == 3
    assert counts["schedule_p6_calendars"] >= 1 and counts["schedule_p6_observed_fields"] > 0
    activity_values = _all(
        w.engine,
        "SELECT activity_id, schedule_activity_id FROM knowledge.schedule_p6_field_values "
        "WHERE entity_kind = 'activity'",
    )
    assert activity_values and all(row[1] is not None for row in activity_values)


def test_a_fatal_export_fails_with_its_positioned_issue(w: World) -> None:
    case = xer.build("missing_required_field")
    answer = _import(w, case.data)
    _work(w.engine)
    publication_id = answer["publication_id"]
    assert _status(w.engine, publication_id) == "failed"
    issues = _all(
        w.engine,
        "SELECT code, severity, source_table, record_line, field FROM "
        "knowledge.schedule_import_issues WHERE publication_id = :p AND severity = 'error'",
        p=publication_id,
    )
    expected = [issue for issue in case.truth.issues if issue[1] == xer.FATAL]
    assert [(row[0], row[2], row[3], row[4]) for row in issues] == [
        (code, table, line, field) for code, _severity, table, line, field in expected
    ]
    run = _one(
        w.engine,
        "SELECT status, failure_code FROM knowledge.schedule_parser_runs WHERE publication_id = :p",
        p=publication_id,
    )
    assert tuple(run) == ("failed", expected[0][0])
    assert (
        _one(
            w.engine,
            "SELECT count(*) FROM knowledge.schedule_p6_activities a JOIN "
            "knowledge.schedule_parser_runs r ON r.parser_run_id = a.parser_run_id "
            "WHERE r.publication_id = :p",
            p=publication_id,
        )[0]
        == 0
    )


def _renamed_project(*, short_name: str, guid: str) -> bytes:
    model = xer.base_model("full")
    model.table("PROJECT").rows[0].update(proj_short_name=short_name, guid=guid)
    return _model_bytes(model)


def test_a_changed_project_identity_is_review_required_and_links_nothing(w: World) -> None:
    first = _import(w, _full())
    _work(w.engine)
    assert _status(w.engine, first["publication_id"]) == "complete"
    other = _renamed_project(short_name="SYN-OTHER", guid=xer.guid("SynOtherProject"))
    second = _import(w, other, path="exports/other.xer", key="p6-import-0002")
    _work(w.engine)
    publication_id = second["publication_id"]
    assert _status(w.engine, publication_id) == "review_required"
    codes = _all(
        w.engine,
        "SELECT code, source_table, field FROM knowledge.schedule_import_issues "
        "WHERE publication_id = :p AND code = 'p6_project_identity_changed'",
        p=publication_id,
    )
    assert [tuple(row) for row in codes] == [
        ("p6_project_identity_changed", "PROJECT", "proj_short_name")
    ]
    unlinked = _one(
        w.engine,
        "SELECT count(*), count(a.schedule_activity_id) FROM knowledge.schedule_p6_activities a "
        "JOIN knowledge.schedule_parser_runs r ON r.parser_run_id = a.parser_run_id "
        "WHERE r.publication_id = :p",
        p=publication_id,
    )
    assert tuple(unlinked) == (4, 0)
    # The same file, the change accepted: `complete`, nothing to review.
    accepted = _import(
        w,
        other + b"\r\n",
        path="exports/accepted.xer",
        key="p6-import-0003",
        accept_project_identity_change=True,
    )
    _work(w.engine)
    assert _status(w.engine, accepted["publication_id"]) == "complete"


def test_a_renamed_project_keeping_its_guid_keeps_the_series(w: World) -> None:
    _import(w, _full())
    _work(w.engine)
    renamed = _renamed_project(short_name="SYN-RENAMED", guid=xer.guid("SynProject"))
    second = _import(w, renamed, path="exports/renamed.xer", key="p6-import-0002")
    _work(w.engine)
    assert _status(w.engine, second["publication_id"]) == "complete"


def test_a_renumbered_activity_is_removed_added_and_a_renumber_candidate(w: World) -> None:
    first = _import(w, _full())
    _work(w.engine)
    model = xer.base_model("full")
    model.table("TASK").rows[2]["task_code"] = "SYN-1025"
    second = _import(w, _model_bytes(model), path="exports/renumbered.xer", key="p6-import-0002")
    _work(w.engine)
    assert _status(w.engine, second["publication_id"]) == "complete"
    with SqlAlchemyScheduleP6UnitOfWork(w.engine) as uow:
        before = uow.p6.p6_activity_identities(P, first["publication_id"])
        after = uow.p6.p6_activity_identities(P, second["publication_id"])
    matching = match_p6_activities(before, after)
    assert matching.removed == ("SYN-1020",)
    assert matching.added == ("SYN-1025",)
    assert matching.renumber_candidates == (P6RenumberCandidate("SYN-1020", "SYN-1025"),)
    stable = _all(
        w.engine,
        "SELECT published_activity_id, count(*) FROM knowledge.schedule_activities s "
        "JOIN knowledge.schedule_p6_activities a ON a.schedule_activity_id = "
        "s.schedule_activity_id GROUP BY 1 ORDER BY 1",
    )
    # Same code, same Stable Activity across both publications; the renumbered
    # code is a new one (never merged).
    assert [tuple(row) for row in stable] == [
        ("SYN-1000", 2),
        ("SYN-1010", 2),
        ("SYN-1020", 1),
        ("SYN-1025", 1),
        ("SYN-1030", 2),
    ]


def test_unknown_names_are_stored_only_when_they_match_the_pattern(w: World) -> None:
    model = xer.base_model("full")
    model.insert_after("TASKPRED", xer.Table("Synextra", ["syn_key"], [{"syn_key": "1"}]))
    model.insert_after(
        "TASKPRED", xer.Table("9synbadtable", ["9synbadfield"], [{"9synbadfield": "1"}])
    )
    answer = _import(w, _model_bytes(model))
    _work(w.engine)
    publication_id = answer["publication_id"]
    assert _status(w.engine, publication_id) == "complete"
    tables = _all(
        w.engine,
        "SELECT source_table FROM knowledge.schedule_import_issues WHERE publication_id = :p "
        "AND code = 'p6_unknown_table' ORDER BY source_table NULLS LAST",
        p=publication_id,
    )
    assert [row[0] for row in tables] == ["Synextra", None]
    observed = _all(
        w.engine,
        "SELECT source_table, field_name FROM knowledge.schedule_p6_observed_fields "
        "WHERE catalogued = false AND (source_table IS NULL OR source_table = 'Synextra') "
        "ORDER BY source_table NULLS LAST",
    )
    assert [tuple(row) for row in observed] == [("Synextra", "syn_key"), (None, None)]
    # Every stored row but the retained snapshot itself (the bytes, section 7.6).
    rows = _snapshot(w.engine)
    stored = repr({k: v for k, v in rows.items() if k != "schedule_p6_snapshots"})
    assert "9synbad" not in stored


def test_the_worker_stores_a_name_outside_the_pattern_as_null(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defence in depth behind the parser's own `safe_name`: the worker re-checks 5.2."""
    original = p6_handler._parse_p6

    def with_bad_names(data: bytes, capture: object, wall: float) -> IsolatedP6Parse:
        parsed = original(data, capture, wall)  # type: ignore[arg-type]
        assert isinstance(parsed, ParsedP6Result)
        planted = P6Issue(
            P6IssueCode.UNKNOWN_FIELD,
            P6Severity.WARNING,
            table="9synbadtable",
            line=1,
            field="9synbadfield",
        )
        result = replace(parsed.result, issues=(*parsed.result.issues, planted))
        return ParsedP6Result(result=result, frame_sha256=parsed.frame_sha256)

    monkeypatch.setattr(p6_handler, "_parse_p6", with_bad_names)
    answer = _import(w, _full())
    _work(w.engine)
    assert _status(w.engine, answer["publication_id"]) == "complete"
    stored = _all(
        w.engine,
        "SELECT source_table, field FROM knowledge.schedule_import_issues "
        "WHERE publication_id = :p AND code = 'p6_unknown_field' AND record_line = 1",
        p=answer["publication_id"],
    )
    assert [tuple(row) for row in stored] == [(None, None)]


def test_the_issue_list_is_capped_at_ten_thousand(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from my_pa.domain.schedule.p6.model import MAX_LISTED_ISSUES

    assert MAX_LISTED_ISSUES == 10_000
    monkeypatch.setattr(p6_handler, "MAX_LISTED_ISSUES", 3)
    model = xer.base_model("full")
    for index in range(5):
        model.insert_after("TASKPRED", xer.Table(f"SYNX{index}", ["syn_key"], [{"syn_key": "1"}]))
    answer = _import(w, _model_bytes(model))
    _work(w.engine)
    publication_id = answer["publication_id"]
    assert _status(w.engine, publication_id) == "complete"
    count = _one(
        w.engine,
        "SELECT issue_count FROM knowledge.schedule_publications WHERE publication_id = :p",
        p=publication_id,
    )[0]
    assert count == 3


# ---- C4 (database half): the child is the one that parsed ----------------------------------


def _forged_output(other: bytes) -> bytes:
    """A real child frame for `other`, offered for different bytes."""
    parsed = run_isolated_p6_parse(other, capture=None, wall_seconds=30)
    assert isinstance(parsed, ParsedP6Result)
    envelope = {
        "document_sha256": hashlib.sha256(other).hexdigest(),
        "document_size_bytes": len(other),
        "frame": frame_object(parsed.result),
    }
    return P6_FRAME_MAGIC + json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def test_a_frame_forged_for_another_digest_is_refused_transient(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _forged_output(xer.build("minimal_valid").data)

    def forged(data: bytes, capture: object, wall: float) -> IsolatedP6Parse:
        del capture, wall
        return classify_p6_exchange(ChildExchange(0, output, False, False, 1), data)

    monkeypatch.setattr(p6_handler, "_parse_p6", forged)
    answer = _import(w, _full())
    with pytest.raises(JobExecutionError) as raised:
        _work(w.engine)
    assert raised.value.code is ErrorCode.INTERNAL_ERROR
    assert _status(w.engine, answer["publication_id"]) == "processing"
    assert _one(w.engine, "SELECT count(*) FROM knowledge.schedule_parser_runs")[0] == 0


# ---- C5: the switch ------------------------------------------------------------------------


def test_switch_off_the_admission_reads_nothing(w: World) -> None:
    named = w.put("exports/schedule.xer", _full())
    store = _NoReadStore(w.root)
    w.enabled = False
    before = _snapshot(w.engine)
    _refused(lambda: w.application(store).import_p6(P, _request(named)), UnsupportedError)
    assert store.read_bytes == 0 and _snapshot(w.engine) == before


def test_switch_off_the_job_fails_closed_transient_and_nothing_parses(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = _import(w, _full())
    calls: list[bytes] = []

    def refuse(data: bytes, capture: object, wall: float) -> IsolatedP6Parse:
        calls.append(data)
        raise AssertionError("the parse was spawned")

    monkeypatch.setattr(p6_handler, "_parse_p6", refuse)
    before = _snapshot(w.engine)
    with pytest.raises(JobExecutionError) as raised:
        _work(w.engine, enabled=False)
    assert raised.value.code is ErrorCode.UNAVAILABLE
    assert calls == []
    assert _status(w.engine, answer["publication_id"]) == "queued"
    after = _snapshot(w.engine)
    assert {k: v for k, v in after.items() if k != "schedule_jobs"} == {
        k: v for k, v in before.items() if k != "schedule_jobs"
    }
    # Under the worker loop (the lease expired) the attempt is released, never completed.
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_jobs SET lease_expires_at = now() - interval '1 second'"
            )
        )
    run = run_worker(
        w.engine,
        owner=OWNER,
        handler=process_schedule_publication,
        stop=threading.Event(),
        principal_id=P,
        plane=SCHEDULE_JOBS,
        max_iterations=1,
        lease_seconds=LEASE_SECONDS,
    )
    assert run.completed == 0 and run.released == 1
    assert calls == [] and _status(w.engine, answer["publication_id"]) == "queued"
    job = _one(w.engine, "SELECT last_error_code FROM knowledge.schedule_jobs")
    assert job[0] == "unavailable"


# ---- the bounds-maximal synthetic measurement (section 9.3 budget item) --------------------


def _bounds_maximal() -> bytes:
    """25,000 activities, 100,000 relationships, 25,000 WBS rows, R fields, under 16 MiB."""
    model = xer.base_model("minimal")
    wbs = model.table("PROJWBS").rows
    template_wbs = dict(wbs[1])
    while len(wbs) < 25_000:
        number = str(100_000 + len(wbs))
        wbs.append(
            dict(template_wbs, wbs_id=number, parent_wbs_id="2001", wbs_short_name=f"W{number}")
        )
    tasks = model.table("TASK").rows
    template = dict(tasks[1])
    while len(tasks) < 25_000:
        number = str(200_000 + len(tasks))
        wbs_id = wbs[len(tasks) % len(wbs)]["wbs_id"]
        tasks.append(dict(template, task_id=number, task_code=f"SYN-{number}", wbs_id=wbs_id))
    ids = [row["task_id"] for row in tasks]
    preds = model.table("TASKPRED").rows
    step = 1
    while len(preds) < 100_000:
        for index in range(len(ids) - step):
            if len(preds) >= 100_000:
                break
            preds.append(xer.pred_row(str(500_000 + len(preds)), ids[index], ids[index + step]))
        step += 1
    return _model_bytes(model)


@pytest.mark.slow
def test_a_bounds_maximal_export_completes_within_the_handler_budget(w: World) -> None:
    data = _bounds_maximal()
    assert len(data) <= SIXTEEN_MIB
    answer = _import(w, data)
    started = time.monotonic()
    _work(w.engine)
    elapsed = time.monotonic() - started
    assert _status(w.engine, answer["publication_id"]) == "complete"
    counts = _one(
        w.engine,
        "SELECT (SELECT count(*) FROM knowledge.schedule_p6_activities), "
        "(SELECT count(*) FROM knowledge.schedule_p6_relationships), "
        "(SELECT count(*) FROM knowledge.schedule_p6_wbs)",
    )
    assert tuple(counts) == (25_000, 100_000, 25_000)
    assert elapsed < 240, elapsed
