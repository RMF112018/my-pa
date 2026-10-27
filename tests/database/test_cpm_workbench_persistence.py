"""The S5b-1 Schedule repository and unit of work (foundation contract 5.4-5.7, 8.2).

Every test drives `SqlAlchemyScheduleUnitOfWork` against a synthetic head
database: admission and its R2 section 23 idempotency outcomes, the section 24
worker transactions under a real `SCHEDULE_JOBS` lease, the Principal
partition, and the lifecycle the revision's triggers re-verify. There is no
worker process: a lease is taken with `claim_job` in a committed transaction
and expired by moving `lease_expires_at` into the past (contract 5.5).

`database` tier (`database_clone` by default): each test gets its own clone of
the head template. Every value is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import (
    ScheduleAdmissionRejectedError,
    ScheduleIntegrityError,
    ScheduleLeaseLostError,
    ScheduleRepository,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ROW_CELL_FIELDS,
    ParsedScheduleRow,
    ScheduleAdmission,
    ScheduleAdmissionOutcome,
    ScheduleAdmissionRefusal,
    ScheduleBaselineKind,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleFinalization,
    ScheduleImportRequest,
    ScheduleIssueCode,
    ScheduleLease,
    ScheduleParseCounts,
    ScheduleParseIssue,
    ScheduleParserIdentity,
    ScheduleParserRunStatus,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    ScheduleRowBoundsError,
    ScheduleRowType,
    normalize_series_name,
    schedule_import_request_digest,
)
from my_pa.infrastructure.persistence.jobs import (
    SCHEDULE_JOBS,
    claim_job,
    complete_job,
    job_for,
    release_job,
)
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.tables import JobState

pytestmark = pytest.mark.database

P: Final = "prn_cpmpers0001"
Q: Final = "prn_cpmpers0002"
DOC: Final = "a" * 64
RESULT: Final = "b" * 64
OWNER: Final = "cpm-worker-a"
CPM_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)
IDENTITY: Final = ScheduleParserIdentity(
    parser_name="cpm-workbench-full-parser",
    parser_version="1",
    profile_id="p6_full_v1",
    profile_version=1,
    pypdfium2_version="5.13.0",
    pdfium_version="153.0.7999.0",
)
LIVE_DATE: Final = date(2026, 5, 4)


# ---- the world ------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """One Principal's Projects, enrollments and source versions (all synthetic)."""

    principal: str
    tag: str
    project: str
    other_project: str
    enrollment: str
    text_only_enrollment: str
    source_object: str
    v1: str
    v2: str
    v3: str
    text_version: str
    large_version: str
    unenrolled_object: str
    unenrolled_version: str


def _world(engine: Engine, principal: str, tag: str) -> World:
    world = World(
        principal=principal,
        tag=tag,
        project=f"prj_{tag}0001",
        other_project=f"prj_{tag}0002",
        enrollment=f"enr_{tag}0001",
        text_only_enrollment=f"enr_{tag}0002",
        source_object=f"obj_{tag}0001",
        v1=f"ver_{tag}0001",
        v2=f"ver_{tag}0002",
        v3=f"ver_{tag}0003",
        text_version=f"ver_{tag}0007",
        large_version=f"ver_{tag}0008",
        unenrolled_object=f"obj_{tag}0009",
        unenrolled_version=f"ver_{tag}0009",
    )
    source = f"src_{tag}0001"
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.sources (source_id, provider_kind, label, classification, "
                "native_root) VALUES (:s, 'fixture', 'Synthetic', 'synthetic_test', :root)"
            ),
            {"s": source, "root": f"/synthetic/cpm/{tag}"},
        )
        for obj in (world.source_object, world.unenrolled_object):
            c.execute(
                text(
                    "INSERT INTO knowledge.source_objects (source_object_id, source_id, kind, "
                    "native_locator) VALUES (:o, :s, 'file', :locator)"
                ),
                {"o": obj, "s": source, "locator": f"/synthetic/cpm/{tag}/{obj}.pdf"},
            )
        for version, obj, media_type, size in (
            (world.v1, world.source_object, "application/pdf", 1024),
            (world.v2, world.source_object, "application/pdf", 2048),
            (world.v3, world.source_object, "application/pdf", None),
            (world.text_version, world.source_object, "text/plain", 64),
            (world.large_version, world.source_object, "application/pdf", 16_777_217),
            (world.unenrolled_version, world.unenrolled_object, "application/pdf", 1024),
        ):
            c.execute(
                text(
                    "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                    "fingerprint, media_type, size_bytes, modified_at) VALUES (:v, :o, :v, :m, "
                    ":size, now())"
                ),
                {"v": version, "o": obj, "m": media_type, "size": size},
            )
        for enrollment, media_types, key in (
            (world.enrollment, ["application/pdf"], f"{tag}-pdf"),
            (world.text_only_enrollment, ["text/plain"], f"{tag}-text"),
        ):
            c.execute(
                text(
                    "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                    "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                    "depth, media_types, max_items, max_bytes) VALUES (:e, :s, :p, "
                    "'schedule_import', 'policy-v1', :key, 'synthetic', ARRAY[:o], 0, :media, 10, "
                    "1048576)"
                ),
                {
                    "e": enrollment,
                    "s": source,
                    "p": principal,
                    "key": key,
                    "o": world.source_object,
                    "media": media_types,
                },
            )
            c.execute(
                text(
                    "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                    "VALUES (:e, :o)"
                ),
                {"e": enrollment, "o": world.source_object},
            )
        for project in (world.project, world.other_project):
            c.execute(
                text(
                    "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                    "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                    "now())"
                ),
                {"j": project, "p": principal},
            )
    return world


@pytest.fixture
def w(db_engine: Engine) -> World:
    return _world(db_engine, P, "cpmpa")


@pytest.fixture
def other(db_engine: Engine) -> World:
    return _world(db_engine, Q, "cpmpb")


# ---- requests, leases and records -------------------------------------------------


def _request(
    w: World,
    key: str = "cpm-key-0001",
    *,
    series: str | None = "Master Schedule",
    series_id: str | None = None,
    project: str | None = None,
    enrollment: str | None = None,
    source_object: str | None = None,
    version: str | None = None,
    role: SchedulePublicationRole = SchedulePublicationRole.UPDATE,
    baseline: ScheduleBaselineKind | None = None,
    expected: date | None = None,
    supersedes: str | None = None,
) -> ScheduleImportRequest:
    return ScheduleImportRequest(
        project_id=project or w.project,
        series_id=series_id,
        series_name=None if series_id is not None else normalize_series_name(str(series)),
        enrollment_id=enrollment or w.enrollment,
        source_object_id=source_object or w.source_object,
        source_version_id=version or w.v1,
        publication_role=role,
        baseline_kind=baseline,
        expected_data_date=expected,
        supersedes_publication_id=supersedes,
        idempotency_key=key,
    )


def _uow(engine: Engine) -> SqlAlchemyScheduleUnitOfWork:
    return SqlAlchemyScheduleUnitOfWork(engine)


def _do[T](engine: Engine, action: Callable[[ScheduleRepository], T]) -> T:
    """Run `action` in one Schedule unit of work and commit it."""
    with _uow(engine) as uow:
        return action(uow.schedules)


def _admit(engine: Engine, principal: str, request: ScheduleImportRequest) -> ScheduleAdmission:
    digest = schedule_import_request_digest(principal, request)
    return _do(engine, lambda r: r.admit_publication(principal, request, digest))


def _refusal(
    engine: Engine, principal: str, request: ScheduleImportRequest
) -> ScheduleAdmissionRefusal:
    with pytest.raises(ScheduleAdmissionRejectedError) as refused:
        _admit(engine, principal, request)
    return refused.value.reason


def _lease(engine: Engine, principal: str, publication_id: str) -> ScheduleLease:
    """Claim the Principal's next `schedule` job; it must be this publication's."""
    with engine.begin() as c:
        leased = claim_job(
            c, owner=OWNER, lease_seconds=300, principal_id=principal, plane=SCHEDULE_JOBS
        )
    assert leased is not None
    assert leased.subject_id == publication_id
    return ScheduleLease(operation_id=leased.operation_id, owner=OWNER, attempt=leased.attempt)


def _expire(engine: Engine, lease: ScheduleLease) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_jobs SET lease_expires_at = now() - interval "
                "'1 second' WHERE operation_id = :op"
            ),
            {"op": lease.operation_id},
        )


def _exhaust(engine: Engine, principal: str, publication_id: str) -> None:
    """Spend every attempt of the publication's job; it ends `failed`."""
    for _ in range(3):
        lease = _lease(engine, principal, publication_id)
        with engine.begin() as c:
            release_job(
                c,
                lease.operation_id,
                owner=OWNER,
                error_code=ErrorCode.UNAVAILABLE,
                plane=SCHEDULE_JOBS,
            )


def _cell(field: ScheduleFieldCode, value: str | None) -> ScheduleCellEvidence:
    if value is None:
        return ScheduleCellEvidence(field, ScheduleCellState.PUBLISHED_BLANK, None, ())
    fragment = ScheduleCellFragment(
        raw=value,
        box=ScheduleBox(10_000, 20_000, 30_500, 27_250),
        font_base_name="SyntheticSans",
        font_size_mpt=7_000,
    )
    return ScheduleCellEvidence(field, ScheduleCellState.PUBLISHED_VALUE, value, (fragment,))


def _prow(
    ordinal: int,
    *,
    kind: ScheduleRowType = ScheduleRowType.ACTIVITY,
    activity: str | None = None,
    parent: int | None = None,
    hierarchy: tuple[str, ...] | None = ("Synthetic WBS",),
    warnings: tuple[ScheduleIssueCode, ...] = (),
) -> ParsedScheduleRow:
    published: str | None = None
    name: str | None = None
    if kind in (ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE):
        published, name = activity or f"A-{ordinal:04d}", f"Synthetic activity {ordinal}"
    elif kind in (ScheduleRowType.PROJECT_SUMMARY, ScheduleRowType.WBS_SUMMARY):
        name = f"Synthetic summary {ordinal}"
    texts = {ScheduleFieldCode.ACTIVITY_ID: published, ScheduleFieldCode.ACTIVITY_NAME: name}
    return ParsedScheduleRow(
        row_ordinal=ordinal,
        page_number=1,
        physical_line_ordinal=ordinal,
        row_type=kind,
        indent_level=1,
        parent_row_ordinal=parent,
        hierarchy_path=hierarchy,
        published_activity_id=published,
        activity_name=name,
        original_duration=ScheduleDurationCell(
            ScheduleCellState.PUBLISHED_VALUE, Decimal("10.000")
        ),
        remaining_duration=ScheduleDurationCell(ScheduleCellState.PUBLISHED_BLANK, None),
        start=ScheduleDateCell(ScheduleCellState.PUBLISHED_VALUE, LIVE_DATE, None),
        finish=ScheduleDateCell(ScheduleCellState.PUBLISHED_VALUE, date(2026, 5, 15), "*"),
        box=ScheduleBox(1_000, 1_000 + ordinal, 2_000, 2_000 + ordinal),
        page_width_mpt=1_224_000,
        page_height_mpt=792_000,
        cells=tuple(_cell(field, texts.get(field)) for field in ROW_CELL_FIELDS),
        warning_codes=warnings,
    )


def _issue(code: ScheduleIssueCode, *, row_ordinal: int | None = None) -> ScheduleParseIssue:
    return ScheduleParseIssue(
        code=code,
        severity=ISSUE_SEVERITY[code],
        page_number=1,
        row_ordinal=row_ordinal,
        field=None,
    )


def _counts(rows: int, issues: Sequence[ScheduleParseIssue] = ()) -> ScheduleParseCounts:
    warnings = sum(1 for issue in issues if issue.severity.value == "warning")
    return ScheduleParseCounts(
        pages=1,
        rows=rows,
        project_summaries=0,
        wbs_summaries=0,
        activities=0,
        milestones=0,
        ambiguous=0,
        chart_objects_excluded=0,
        watermark_objects_excluded=0,
        suppressed_objects=0,
        duplicate_objects_collapsed=0,
        non_embedded_font_objects=0,
        issues=len(issues),
        warnings=warnings,
    )


# ---- the attempt, step by step ----------------------------------------------------


def _process(engine: Engine, principal: str, publication: str, lease: ScheduleLease) -> None:
    _do(engine, lambda r: r.begin_processing(principal, publication, lease))
    _do(engine, lambda r: r.pin_document(principal, publication, lease, DOC, 1024))


def _start(
    engine: Engine,
    principal: str,
    publication: str,
    lease: ScheduleLease,
    identity: ScheduleParserIdentity = IDENTITY,
) -> str:
    started = _do(engine, lambda r: r.start_parser_run(principal, publication, lease, identity))
    return started.run.parser_run_id


def _parse(
    engine: Engine,
    principal: str,
    publication: str,
    lease: ScheduleLease,
    *,
    rows: Sequence[ParsedScheduleRow] = (),
    issues: Sequence[ScheduleParseIssue] = (),
    finish: bool = True,
    identity: ScheduleParserIdentity = IDENTITY,
) -> str:
    """Process, pin, start a run, store `rows` then `issues`, and (by default) parse it."""
    _process(engine, principal, publication, lease)
    run = _start(engine, principal, publication, lease, identity)
    if rows:
        _do(engine, lambda r: r.insert_rows(principal, run, lease, rows))
    if issues:
        _do(engine, lambda r: r.insert_issues(principal, publication, lease, run, issues))
    if finish:
        _do(
            engine,
            lambda r: r.finish_parser_run(
                principal,
                run,
                lease,
                parsed=_counts(len(rows), issues),
                parse_result_sha256=RESULT,
                failure_code=None,
            ),
        )
    return run


def _canonicalize(
    engine: Engine, principal: str, run: str, lease: ScheduleLease, limit: int = 1000
) -> tuple[int, int, int]:
    progress = _do(engine, lambda r: r.canonicalize_batch(principal, run, lease, limit))
    return progress.linked, progress.created, progress.remaining


def _finalize(
    engine: Engine, principal: str, publication: str, run: str, lease: ScheduleLease
) -> SchedulePublicationStatus:
    finalization = ScheduleFinalization(
        accepted_parser_run_id=run,
        published_schedule_title="Synthetic Project Schedule",
        data_date=LIVE_DATE,
        run_date=date(2026, 5, 11),
    )
    return _do(
        engine, lambda r: r.finalize_publication(principal, publication, lease, finalization)
    ).status


def _complete(
    engine: Engine, w: World, request: ScheduleImportRequest
) -> tuple[ScheduleAdmission, ScheduleLease, str]:
    """A `complete` publication of one linked activity."""
    admission = _admit(engine, w.principal, request)
    publication = admission.publication.publication_id
    lease = _lease(engine, w.principal, publication)
    run = _parse(engine, w.principal, publication, lease, rows=[_prow(1)])
    _canonicalize(engine, w.principal, run, lease)
    assert _finalize(engine, w.principal, publication, run, lease) is (
        SchedulePublicationStatus.COMPLETE
    )
    return admission, lease, run


# ---- direct reads (assertions only) ----------------------------------------------


def _scalar(engine: Engine, statement: str, **values: object) -> object:
    with engine.connect() as c:
        return c.execute(text(statement), values).scalar_one()


def _count(engine: Engine, table: str, where: str = "true", **values: object) -> int:
    statement = f"SELECT count(*) FROM knowledge.{table} WHERE {where}"  # noqa: S608
    return int(str(_scalar(engine, statement, **values)))


def _snapshot(engine: Engine) -> dict[str, str]:
    """Every CPM row, digested, so "nothing was written" is checked exactly."""
    digest = (
        "SELECT count(*)::text || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY "
        "x::text)), '') FROM knowledge.{} x"
    )
    with engine.connect() as c:
        return {
            table: str(c.execute(text(digest.format(table))).scalar_one()) for table in CPM_TABLES
        }


def _waits_on_a_lock(engine: Engine, deadline_seconds: float = 20.0) -> None:
    """Block until some session in this database is waiting on a lock."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        waiting = _scalar(
            engine,
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND wait_event_type = 'Lock'",
        )
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("the concurrent admission never waited on the first one")


def _concurrently(
    engine: Engine, principal: str, first: ScheduleImportRequest, second: ScheduleImportRequest
) -> tuple[ScheduleAdmission, ScheduleAdmission | BaseException]:
    """Admit `first` uncommitted, admit `second` beside it, then commit `first`."""
    outcome: list[ScheduleAdmission | BaseException] = []

    def run_second() -> None:
        try:
            outcome.append(_admit(engine, principal, second))
        except BaseException as error:  # handed back to the test thread
            outcome.append(error)

    uow = _uow(engine)
    uow.__enter__()
    try:
        digest = schedule_import_request_digest(principal, first)
        admitted = uow.schedules.admit_publication(principal, first, digest)
        racer = threading.Thread(target=run_second)
        racer.start()
        _waits_on_a_lock(engine)
    except BaseException as error:
        uow.__exit__(type(error), error, error.__traceback__)
        raise
    uow.__exit__(None, None, None)
    racer.join(timeout=30)
    assert not racer.is_alive()
    return admitted, outcome[0]


# ---- admission: bindings -------------------------------------------------------------


_BINDINGS: Final[dict[str, tuple[Callable[[World], ScheduleImportRequest], str]]] = {
    "project": (lambda w: _request(w, project="prj_cpmpaabsent"), "PROJECT_NOT_FOUND"),
    "series": (lambda w: _request(w, series_id="sser_cpmpaabsent"), "SERIES_NOT_FOUND"),
    "enrollment": (lambda w: _request(w, enrollment="enr_cpmpaabsent"), "ENROLLMENT_NOT_FOUND"),
    "object": (
        lambda w: _request(w, source_object=w.unenrolled_object, version=w.unenrolled_version),
        "SOURCE_OBJECT_NOT_ENROLLED",
    ),
    "version": (lambda w: _request(w, version=w.unenrolled_version), "SOURCE_VERSION_NOT_FOUND"),
    "media": (lambda w: _request(w, version=w.text_version), "UNSUPPORTED_MEDIA_TYPE"),
    "enrolled_media": (
        lambda w: _request(w, enrollment=w.text_only_enrollment),
        "MEDIA_TYPE_NOT_ENROLLED",
    ),
    "size": (lambda w: _request(w, version=w.large_version), "SOURCE_TOO_LARGE"),
}


@pytest.mark.parametrize("binding", sorted(_BINDINGS))
def test_admission_refuses_each_unproven_binding(db_engine: Engine, w: World, binding: str) -> None:
    build, reason = _BINDINGS[binding]
    before = _snapshot(db_engine)
    assert _refusal(db_engine, P, build(w)) is ScheduleAdmissionRefusal[reason]
    assert _snapshot(db_engine) == before


def test_a_version_of_unknown_size_is_admitted(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w, version=w.v3))
    assert admission.outcome is ScheduleAdmissionOutcome.CREATED


def test_cross_principal_bindings_are_not_found(db_engine: Engine, w: World, other: World) -> None:
    theirs = _admit(db_engine, Q, _request(other, "cpm-key-theirs"))
    their_series = theirs.series.series_id
    their_publication = theirs.publication.publication_id
    cases = {
        ScheduleAdmissionRefusal.PROJECT_NOT_FOUND: _request(w, project=other.project),
        ScheduleAdmissionRefusal.ENROLLMENT_NOT_FOUND: _request(w, enrollment=other.enrollment),
        ScheduleAdmissionRefusal.SERIES_NOT_FOUND: _request(w, series_id=their_series),
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND: _request(
            w, version=w.v2, supersedes=their_publication
        ),
    }
    before = _snapshot(db_engine)
    for reason, request in cases.items():
        assert _refusal(db_engine, P, request) is reason
    assert _snapshot(db_engine) == before


# ---- admission: idempotency (R2 section 23) -------------------------------------------


def test_same_key_same_request_replays(db_engine: Engine, w: World) -> None:
    first = _admit(db_engine, P, _request(w))
    second = _admit(db_engine, P, _request(w))
    assert first.outcome is ScheduleAdmissionOutcome.CREATED and first.series_created
    assert second.outcome is ScheduleAdmissionOutcome.REPLAYED and not second.series_created
    assert second.publication == first.publication
    assert second.operation_id == first.operation_id
    assert second.series == first.series
    assert _count(db_engine, "schedule_publications") == 1
    assert _count(db_engine, "schedule_jobs") == 1


def test_a_key_equivalent_series_name_replays(db_engine: Engine, w: World) -> None:
    first = _admit(db_engine, P, _request(w, series="Master  Schedule"))
    second = _admit(db_engine, P, _request(w, series="MASTER schedule"))
    assert second.outcome is ScheduleAdmissionOutcome.REPLAYED
    assert second.publication.publication_id == first.publication.publication_id
    assert _count(db_engine, "schedule_series") == 1


def test_same_key_different_request_conflicts(db_engine: Engine, w: World) -> None:
    _admit(db_engine, P, _request(w))
    before = _snapshot(db_engine)
    different = _request(w, expected=LIVE_DATE)
    assert _refusal(db_engine, P, different) is ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT
    assert _snapshot(db_engine) == before


def test_same_version_same_series_replays_when_metadata_agrees(db_engine: Engine, w: World) -> None:
    first = _admit(db_engine, P, _request(w, "cpm-key-0001", expected=LIVE_DATE))
    second = _admit(db_engine, P, _request(w, "cpm-key-0002", expected=LIVE_DATE))
    assert second.outcome is ScheduleAdmissionOutcome.REPLAYED
    assert second.publication.publication_id == first.publication.publication_id
    assert second.publication.idempotency_key == "cpm-key-0001"
    assert second.operation_id == first.operation_id
    assert _count(db_engine, "schedule_publications") == 1


_METADATA: Final[dict[str, tuple[dict[str, object], dict[str, object]]]] = {
    "expected_data_date": ({"expected": LIVE_DATE}, {"expected": date(2026, 5, 11)}),
    "publication_role": ({}, {"role": SchedulePublicationRole.REFERENCE}),
    "baseline_kind": (
        {"role": SchedulePublicationRole.BASELINE, "baseline": ScheduleBaselineKind.WORKING},
        {"role": SchedulePublicationRole.BASELINE, "baseline": ScheduleBaselineKind.CONTRACT},
    ),
}


@pytest.mark.parametrize("field", sorted(_METADATA))
def test_same_version_same_series_conflicts_when_metadata_differs(
    db_engine: Engine, w: World, field: str
) -> None:
    original, changed = _METADATA[field]
    _admit(db_engine, P, _request(w, "cpm-key-0001", **original))  # type: ignore[arg-type]
    before = _snapshot(db_engine)
    request = _request(w, "cpm-key-0002", **changed)  # type: ignore[arg-type]
    assert _refusal(db_engine, P, request) is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT
    assert _snapshot(db_engine) == before


def test_same_version_conflicts_when_only_the_supersession_differs(
    db_engine: Engine, w: World
) -> None:
    predecessor, _, _ = _complete(db_engine, w, _request(w, "cpm-key-0001"))
    _admit(db_engine, P, _request(w, "cpm-key-0002", version=w.v2))
    superseding = _request(
        w, "cpm-key-0003", version=w.v2, supersedes=predecessor.publication.publication_id
    )
    assert _refusal(db_engine, P, superseding) is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT


def test_same_version_other_series_is_a_new_publication(db_engine: Engine, w: World) -> None:
    first = _admit(db_engine, P, _request(w, "cpm-key-0001", series="Series A"))
    second = _admit(db_engine, P, _request(w, "cpm-key-0002", series="Series B"))
    assert second.outcome is ScheduleAdmissionOutcome.CREATED and second.series_created
    assert second.series.series_id != first.series.series_id
    assert second.publication.publication_id != first.publication.publication_id
    assert second.operation_id != first.operation_id
    assert _count(db_engine, "schedule_jobs") == 2


def test_rejected_admission_writes_nothing(db_engine: Engine, w: World) -> None:
    # A refusal before the writes ...
    before = _snapshot(db_engine)
    refused = _request(w, version=w.v2, supersedes="spub_cpmpaabsent")
    assert _refusal(db_engine, P, refused) is (
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND
    )
    assert _snapshot(db_engine) == before
    # ... and one after this transaction created its Series (D-16): a racing
    # admission of the same key wins, and the Series row rolls back with the
    # refused publication.
    first = _request(w, "cpm-key-race", series="Series A")
    second = _request(w, "cpm-key-race", series="Series B")
    admitted, raced = _concurrently(db_engine, P, first, second)
    assert isinstance(raced, ScheduleAdmissionRejectedError), raced
    assert raced.reason is ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT
    assert _count(db_engine, "schedule_series") == 1
    assert _count(db_engine, "schedule_publications") == 1
    assert admitted.outcome is ScheduleAdmissionOutcome.CREATED


def test_concurrent_admission_of_one_key_replays(db_engine: Engine, w: World) -> None:
    admitted, raced = _concurrently(db_engine, P, _request(w), _request(w))
    assert isinstance(raced, ScheduleAdmission), raced
    assert raced.outcome is ScheduleAdmissionOutcome.REPLAYED and not raced.series_created
    assert raced.publication.publication_id == admitted.publication.publication_id
    assert raced.operation_id == admitted.operation_id
    assert _count(db_engine, "schedule_series") == 1
    assert _count(db_engine, "schedule_publications") == 1
    assert _count(db_engine, "schedule_jobs") == 1


def test_concurrent_admission_of_one_version_classifies_by_metadata(
    db_engine: Engine, w: World
) -> None:
    first = _request(w, "cpm-key-0001")
    second = _request(w, "cpm-key-0002", expected=LIVE_DATE)
    _, raced = _concurrently(db_engine, P, first, second)
    assert isinstance(raced, ScheduleAdmissionRejectedError), raced
    assert raced.reason is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT
    assert _count(db_engine, "schedule_publications") == 1


def _fail_it(engine: Engine, w: World, publication: str) -> None:
    lease = _lease(engine, P, publication)
    _process(engine, P, publication, lease)
    _do(
        engine,
        lambda r: r.fail_publication(P, publication, lease, ScheduleIssueCode.CORRUPT_PDF, None),
    )


def _review_it(engine: Engine, w: World, publication: str) -> None:
    lease = _lease(engine, P, publication)
    run = _parse(engine, P, publication, lease, rows=[_prow(1, kind=ScheduleRowType.AMBIGUOUS)])
    assert _finalize(engine, P, publication, run, lease) is (
        SchedulePublicationStatus.REVIEW_REQUIRED
    )


_ENDINGS: Final[dict[str, Callable[[Engine, World, str], None]]] = {
    "failed": _fail_it,
    "effective_failed": lambda engine, w, publication: _exhaust(engine, P, publication),
    "review_required": _review_it,
}


@pytest.mark.parametrize("ending", sorted(_ENDINGS))
def test_failed_version_cannot_be_reimported_into_its_series(
    db_engine: Engine, w: World, ending: str
) -> None:
    """U-09: an ended publication of V in S makes V in S replay or conflict for good."""
    first = _admit(db_engine, P, _request(w, "cpm-key-0001"))
    publication = first.publication.publication_id
    _ENDINGS[ending](db_engine, w, publication)
    status = _do(db_engine, lambda r: r.get_effective_status(P, publication))
    assert status in (SchedulePublicationStatus.FAILED, SchedulePublicationStatus.REVIEW_REQUIRED)
    again = _admit(db_engine, P, _request(w, "cpm-key-0002"))
    assert again.outcome is ScheduleAdmissionOutcome.REPLAYED
    assert again.publication.publication_id == publication
    changed = _request(w, "cpm-key-0003", expected=LIVE_DATE)
    assert _refusal(db_engine, P, changed) is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT
    assert _count(db_engine, "schedule_publications") == 1


# ---- admission: supersession (R2 section 10.4) ---------------------------------------


def test_supersession_rules(db_engine: Engine, w: World) -> None:
    pending = _admit(db_engine, P, _request(w, "cpm-key-0001", series="Series A"))
    not_terminal = _request(
        w,
        "cpm-key-0002",
        series="Series A",
        version=w.v2,
        supersedes=pending.publication.publication_id,
    )
    assert _refusal(db_engine, P, not_terminal) is (
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL
    )
    # An exhausted job is terminal by effective status (D-17).
    _exhaust(db_engine, P, pending.publication.publication_id)
    successor = _admit(db_engine, P, not_terminal)
    assert successor.outcome is ScheduleAdmissionOutcome.CREATED
    assert successor.publication.supersedes_publication_id == pending.publication.publication_id
    second_successor = _request(
        w,
        "cpm-key-0003",
        series="Series A",
        version=w.v3,
        supersedes=pending.publication.publication_id,
    )
    assert _refusal(db_engine, P, second_successor) is (
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR
    )
    other_series = _request(
        w,
        "cpm-key-0004",
        series="Series B",
        version=w.v3,
        supersedes=pending.publication.publication_id,
    )
    assert _refusal(db_engine, P, other_series) is (
        ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND
    )
    # Same version: step (5) answers first, because U2 makes a same-version
    # successor in one Series impossible (the step (6) check is defensive).
    same_version = _request(
        w,
        "cpm-key-0005",
        series="Series A",
        version=w.v1,
        supersedes=pending.publication.publication_id,
    )
    assert _refusal(db_engine, P, same_version) is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT


def test_concurrent_successors_of_one_predecessor_admit_one(db_engine: Engine, w: World) -> None:
    predecessor, _, _ = _complete(db_engine, w, _request(w, "cpm-key-0001"))
    pid = predecessor.publication.publication_id
    first = _request(w, "cpm-key-0002", version=w.v2, supersedes=pid)
    second = _request(w, "cpm-key-0003", version=w.v3, supersedes=pid)
    admitted, raced = _concurrently(db_engine, P, first, second)
    assert admitted.outcome is ScheduleAdmissionOutcome.CREATED
    assert isinstance(raced, ScheduleAdmissionRejectedError), raced
    assert raced.reason is ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR


# ---- one job per publication (R2 section 25) -----------------------------------------


def test_admission_enqueues_exactly_one_schedule_job(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    _admit(db_engine, P, _request(w))
    assert _count(db_engine, "schedule_jobs", "publication_id = :p", p=publication) == 1
    with db_engine.connect() as c:
        job = job_for(c, admission.operation_id, principal_id=P, plane=SCHEDULE_JOBS)
    assert job is not None
    assert job.subject_id == publication and job.state is JobState.QUEUED
    assert admission.publication.status is SchedulePublicationStatus.QUEUED


# ---- the Principal partition (R2 section 35) -------------------------------------


def test_other_principal_reads_none_and_writes_nothing(
    db_engine: Engine, w: World, other: World
) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    run = _parse(db_engine, P, publication, lease, rows=[_prow(1)], finish=False)
    assert _do(db_engine, lambda r: r.get_publication(Q, publication)) is None
    assert _do(db_engine, lambda r: r.get_series(Q, admission.series.series_id)) is None
    assert _do(db_engine, lambda r: r.get_effective_status(Q, publication)) is None
    assert _do(db_engine, lambda r: r.get_parser_runs(Q, publication)) == ()
    assert _do(db_engine, lambda r: r.get_publication(P, publication)) is not None
    before = _snapshot(db_engine)
    writes: dict[str, Callable[[ScheduleRepository], object]] = {
        "begin_processing": lambda r: r.begin_processing(Q, publication, lease),
        "insert_rows": lambda r: r.insert_rows(Q, run, lease, [_prow(2)]),
        "fail_publication": lambda r: r.fail_publication(
            Q, publication, lease, ScheduleIssueCode.CORRUPT_PDF, None
        ),
    }
    for name, write in writes.items():
        with pytest.raises((ScheduleLeaseLostError, ScheduleIntegrityError)):
            _do(db_engine, write)
        assert _snapshot(db_engine) == before, name


def test_schedule_jobs_are_partitioned(db_engine: Engine, w: World, other: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    with db_engine.begin() as c:
        assert (
            claim_job(c, owner=OWNER, lease_seconds=300, principal_id=Q, plane=SCHEDULE_JOBS)
            is None
        )
        assert job_for(c, admission.operation_id, principal_id=Q, plane=SCHEDULE_JOBS) is None
        assert job_for(c, admission.operation_id, principal_id=P, plane=SCHEDULE_JOBS) is not None
    lease = _lease(db_engine, P, admission.publication.publication_id)
    assert lease.attempt == 1


# ---- the lease (R2 section 24, AC-030) ----------------------------------------------


@dataclass(frozen=True)
class Staged:
    publication: str
    lease: ScheduleLease
    run: str | None


def _stage(engine: Engine, w: World, stage: str) -> Staged:
    """One publication leased and driven to `stage`, where the next call would succeed."""
    admission = _admit(engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(engine, P, publication)
    run: str | None = None
    if stage == "queued":
        return Staged(publication, lease, run)
    _do(engine, lambda r: r.begin_processing(P, publication, lease))
    if stage == "processing":
        return Staged(publication, lease, run)
    _do(engine, lambda r: r.pin_document(P, publication, lease, DOC, 1024))
    if stage == "pinned":
        return Staged(publication, lease, run)
    run = _start(engine, P, publication, lease)
    if stage == "running":
        return Staged(publication, lease, run)
    started = run
    _do(engine, lambda r: r.insert_rows(P, started, lease, [_prow(1)]))
    if stage == "running_with_rows":
        return Staged(publication, lease, run)
    _do(
        engine,
        lambda r: r.finish_parser_run(
            P, started, lease, parsed=_counts(1), parse_result_sha256=RESULT, failure_code=None
        ),
    )
    if stage == "parsed":
        return Staged(publication, lease, run)
    _canonicalize(engine, P, started, lease)
    return Staged(publication, lease, run)


def _final(run: str | None) -> ScheduleFinalization:
    assert run is not None
    return ScheduleFinalization(
        accepted_parser_run_id=run, published_schedule_title=None, data_date=None, run_date=None
    )


_WORKER_METHODS: Final[dict[str, tuple[str, Callable[[ScheduleRepository, Staged], object]]]] = {
    "begin_processing": ("queued", lambda r, s: r.begin_processing(P, s.publication, s.lease)),
    "pin_document": (
        "processing",
        lambda r, s: r.pin_document(P, s.publication, s.lease, DOC, 1024),
    ),
    "start_parser_run": (
        "pinned",
        lambda r, s: r.start_parser_run(P, s.publication, s.lease, IDENTITY),
    ),
    "insert_rows": ("running", lambda r, s: r.insert_rows(P, str(s.run), s.lease, [_prow(1)])),
    "insert_issues": (
        "running",
        lambda r, s: r.insert_issues(
            P, s.publication, s.lease, s.run, [_issue(ScheduleIssueCode.INVALID_DATE)]
        ),
    ),
    "finish_parser_run": (
        "running_with_rows",
        lambda r, s: r.finish_parser_run(
            P,
            str(s.run),
            s.lease,
            parsed=_counts(1),
            parse_result_sha256=RESULT,
            failure_code=None,
        ),
    ),
    "canonicalize_batch": (
        "parsed",
        lambda r, s: r.canonicalize_batch(P, str(s.run), s.lease, 1000),
    ),
    "finalize_publication": (
        "canonicalized",
        lambda r, s: r.finalize_publication(P, s.publication, s.lease, _final(s.run)),
    ),
    "fail_publication": (
        "running",
        lambda r, s: r.fail_publication(
            P, s.publication, s.lease, ScheduleIssueCode.CORRUPT_PDF, s.run
        ),
    ),
}


@pytest.mark.parametrize("method", sorted(_WORKER_METHODS))
def test_every_worker_write_refuses_after_lease_loss(
    db_engine: Engine, w: World, method: str
) -> None:
    stage, call = _WORKER_METHODS[method]
    staged = _stage(db_engine, w, stage)
    _expire(db_engine, staged.lease)
    before = _snapshot(db_engine)
    with pytest.raises(ScheduleLeaseLostError):
        _do(db_engine, lambda r: call(r, staged))
    assert _snapshot(db_engine) == before


@pytest.mark.parametrize("method", sorted(_WORKER_METHODS))
def test_every_worker_write_succeeds_under_a_live_lease(
    db_engine: Engine, w: World, method: str
) -> None:
    """The positive control of the lease-loss test: the same call, lease held."""
    stage, call = _WORKER_METHODS[method]
    staged = _stage(db_engine, w, stage)
    _do(db_engine, lambda r: call(r, staged))


def test_a_lease_of_another_attempt_or_publication_is_lost(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "processing")
    stale = replace(staged.lease, attempt=staged.lease.attempt + 1)
    with pytest.raises(ScheduleLeaseLostError):
        _do(db_engine, lambda r: r.pin_document(P, staged.publication, stale, DOC, 1024))
    second = _admit(db_engine, P, _request(w, "cpm-key-0002", series="Series B"))
    with pytest.raises(ScheduleLeaseLostError):
        _do(
            db_engine,
            lambda r: r.begin_processing(P, second.publication.publication_id, staged.lease),
        )


# ---- worker transactions -----------------------------------------------------------


def test_begin_processing_on_a_terminal_publication_returns_a_terminal_plan(
    db_engine: Engine, w: World
) -> None:
    admission, lease, _ = _complete(db_engine, w, _request(w))
    publication = admission.publication.publication_id
    _expire(db_engine, lease)
    reclaimed = _lease(db_engine, P, publication)
    assert reclaimed.attempt == lease.attempt + 1
    before = _snapshot(db_engine)
    plan = _do(db_engine, lambda r: r.begin_processing(P, publication, reclaimed))
    assert plan.terminal and plan.max_fetch_bytes is None
    assert plan.publication.status is SchedulePublicationStatus.COMPLETE
    assert _snapshot(db_engine) == before
    with db_engine.begin() as c:
        assert complete_job(c, reclaimed.operation_id, owner=OWNER, plane=SCHEDULE_JOBS)


def test_begin_processing_plans_the_enrollment_byte_bound(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    plan = _do(db_engine, lambda r: r.begin_processing(P, publication, lease))
    assert not plan.terminal and plan.max_fetch_bytes == 1_048_576
    assert plan.publication.status is SchedulePublicationStatus.PROCESSING
    again = _do(db_engine, lambda r: r.begin_processing(P, publication, lease))
    assert again.publication.processing_started_at == plan.publication.processing_started_at


def test_pin_document_is_set_once_through_the_repository(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "pinned")
    _do(db_engine, lambda r: r.pin_document(P, staged.publication, staged.lease, DOC, 1024))
    with pytest.raises(ScheduleIntegrityError) as changed:
        _do(
            db_engine,
            lambda r: r.pin_document(P, staged.publication, staged.lease, "c" * 64, 1024),
        )
    assert changed.value.code == "document_changed"


def test_start_parser_run_reuses_one_run_per_attempt_and_closes_earlier_ones(
    db_engine: Engine, w: World
) -> None:
    staged = _stage(db_engine, w, "running")
    first = _do(
        db_engine, lambda r: r.start_parser_run(P, staged.publication, staged.lease, IDENTITY)
    )
    assert first.reused and first.run.parser_run_id == staged.run
    _expire(db_engine, staged.lease)
    second_lease = _lease(db_engine, P, staged.publication)
    second = _do(
        db_engine, lambda r: r.start_parser_run(P, staged.publication, second_lease, IDENTITY)
    )
    assert not second.reused and second.run.attempt_number == 2
    runs = _do(db_engine, lambda r: r.get_parser_runs(P, staged.publication))
    assert [(run.attempt_number, run.status, run.failure_code) for run in runs] == [
        (1, ScheduleParserRunStatus.FAILED, None),
        (2, ScheduleParserRunStatus.RUNNING, None),
    ]


def test_an_exact_parsed_run_is_reused_by_a_later_attempt(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "parsed")
    _expire(db_engine, staged.lease)
    lease = _lease(db_engine, P, staged.publication)
    reused = _do(db_engine, lambda r: r.start_parser_run(P, staged.publication, lease, IDENTITY))
    assert reused.reused and reused.run.parser_run_id == staged.run
    assert reused.run.status is ScheduleParserRunStatus.PARSED
    assert _count(db_engine, "schedule_parser_runs") == 1


def test_row_batch_is_at_most_one_thousand(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "running")
    run = str(staged.run)
    for size in (0, 1001):
        rows = [_prow(n) for n in range(1, size + 1)]
        with pytest.raises(ValueError, match="1 to 1000 rows"):
            _do(db_engine, lambda r, rows=rows: r.insert_rows(P, run, staged.lease, rows))
    with pytest.raises(ValueError, match="1 to 1000 issues"):
        _do(
            db_engine,
            lambda r: r.insert_issues(
                P,
                staged.publication,
                staged.lease,
                run,
                [_issue(ScheduleIssueCode.INVALID_DATE)] * 1001,
            ),
        )
    with pytest.raises(ValueError, match="1 to 1000 rows"):
        _do(db_engine, lambda r: r.canonicalize_batch(P, run, staged.lease, 1001))
    stored = _do(
        db_engine,
        lambda r: r.insert_rows(P, run, staged.lease, [_prow(n) for n in range(1, 1001)]),
    )
    assert stored == 1000 == _count(db_engine, "schedule_rows")


def test_row_ordinals_are_stored_verbatim_and_gaps_refused(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "running")
    run = str(staged.run)
    _do(db_engine, lambda r: r.insert_rows(P, run, staged.lease, [_prow(1), _prow(2)]))
    for batch in ([_prow(4)], [_prow(3), _prow(5)], [_prow(2)]):
        before = _snapshot(db_engine)
        with pytest.raises(ScheduleIntegrityError) as gap:
            _do(db_engine, lambda r, batch=batch: r.insert_rows(P, run, staged.lease, batch))
        assert gap.value.code == "row_ordinal_gap"
        assert _snapshot(db_engine) == before
    _do(db_engine, lambda r: r.insert_rows(P, run, staged.lease, [_prow(3, parent=1)]))
    with db_engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT w.row_ordinal, p.row_ordinal AS parent FROM knowledge.schedule_rows w "
                "LEFT JOIN knowledge.schedule_rows p ON p.row_id = w.parent_row_id "
                "ORDER BY w.row_ordinal"
            )
        ).all()
    assert [tuple(row) for row in stored] == [(1, None), (2, None), (3, 1)]


def _millipoints(value: str) -> int:
    return int(Decimal(value) * 1000)


def _cells(evidence: dict[str, object]) -> tuple[ScheduleCellEvidence, ...]:
    cells = evidence["cells"]
    assert isinstance(cells, dict)
    built = []
    for field in ROW_CELL_FIELDS:
        cell = cells[field.value]
        built.append(
            ScheduleCellEvidence(
                field=field,
                state=ScheduleCellState(cell["state"]),
                text=cell["text"],
                fragments=tuple(
                    ScheduleCellFragment(
                        raw=fragment["raw"],
                        box=ScheduleBox(*(_millipoints(v) for v in fragment["bbox"])),
                        font_base_name=fragment["font"],
                        font_size_mpt=_millipoints(fragment["font_size"]),
                    )
                    for fragment in cell["fragments"]
                ),
            )
        )
    return tuple(built)


def _stored_rows(engine: Engine, run: str) -> list[ParsedScheduleRow]:
    with engine.connect() as c:
        rows = (
            c.execute(
                text(
                    "SELECT w.*, p.row_ordinal AS parent_ordinal FROM knowledge.schedule_rows w "
                    "LEFT JOIN knowledge.schedule_rows p ON p.row_id = w.parent_row_id "
                    "WHERE w.parser_run_id = :r ORDER BY w.row_ordinal"
                ),
                {"r": run},
            )
            .mappings()
            .all()
        )
    return [
        ParsedScheduleRow(
            row_ordinal=row["row_ordinal"],
            page_number=row["page_number"],
            physical_line_ordinal=row["physical_line_ordinal"],
            row_type=ScheduleRowType(row["row_type"]),
            indent_level=row["indent_level"],
            parent_row_ordinal=row["parent_ordinal"],
            hierarchy_path=None if row["hierarchy_path"] is None else tuple(row["hierarchy_path"]),
            published_activity_id=row["published_activity_id"],
            activity_name=row["activity_name"],
            original_duration=ScheduleDurationCell(
                ScheduleCellState(row["od_state"]), row["od_value"]
            ),
            remaining_duration=ScheduleDurationCell(
                ScheduleCellState(row["rd_state"]), row["rd_value"]
            ),
            start=ScheduleDateCell(
                ScheduleCellState(row["start_state"]), row["start_date"], row["start_marker"]
            ),
            finish=ScheduleDateCell(
                ScheduleCellState(row["finish_state"]), row["finish_date"], row["finish_marker"]
            ),
            box=ScheduleBox(
                row["bbox_x0_mpt"], row["bbox_y0_mpt"], row["bbox_x1_mpt"], row["bbox_y1_mpt"]
            ),
            page_width_mpt=row["page_width_mpt"],
            page_height_mpt=row["page_height_mpt"],
            cells=_cells(row["cell_evidence"]),
            warning_codes=tuple(ScheduleIssueCode(code) for code in row["warning_codes"]),
        )
        for row in rows
    ]


def test_row_round_trips_the_parsed_record_field_for_field(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "running")
    run = str(staged.run)
    rows = [
        _prow(1, kind=ScheduleRowType.PROJECT_SUMMARY, hierarchy=None),
        _prow(2, kind=ScheduleRowType.WBS_SUMMARY, parent=1, hierarchy=("Phase 1",)),
        _prow(3, parent=2, hierarchy=("Phase 1", "Ünïcode Wörk"), activity="A-1000"),
        _prow(
            4,
            kind=ScheduleRowType.MILESTONE,
            parent=2,
            warnings=(
                ScheduleIssueCode.HEADER_OD_OCCLUDED,
                ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED,
            ),
        ),
        _prow(5, kind=ScheduleRowType.AMBIGUOUS, hierarchy=()),
    ]
    _do(db_engine, lambda r: r.insert_rows(P, run, staged.lease, rows[:2]))
    _do(db_engine, lambda r: r.insert_rows(P, run, staged.lease, rows[2:]))
    assert _stored_rows(db_engine, run) == rows


# ---- parse, canonicalize, finalize ---------------------------------------------------


def test_finish_parser_run_verifies_counts_and_ends_once(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "running_with_rows")
    run = str(staged.run)
    with pytest.raises(ScheduleIntegrityError) as mismatch:
        _do(
            db_engine,
            lambda r: r.finish_parser_run(
                P,
                run,
                staged.lease,
                parsed=_counts(2),
                parse_result_sha256=RESULT,
                failure_code=None,
            ),
        )
    assert mismatch.value.code == "count_mismatch"
    with pytest.raises(ValueError, match="not both"):
        _do(
            db_engine,
            lambda r: r.finish_parser_run(
                P,
                run,
                staged.lease,
                parsed=_counts(1),
                parse_result_sha256=RESULT,
                failure_code=ScheduleIssueCode.CORRUPT_PDF,
            ),
        )
    failed = _do(
        db_engine,
        lambda r: r.finish_parser_run(
            P,
            run,
            staged.lease,
            parsed=None,
            parse_result_sha256=None,
            failure_code=ScheduleIssueCode.PARSER_EXCEPTION,
        ),
    )
    assert failed.status is ScheduleParserRunStatus.FAILED
    assert failed.failure_code is ScheduleIssueCode.PARSER_EXCEPTION
    with pytest.raises(ScheduleIntegrityError) as again:
        _do(
            db_engine,
            lambda r: r.finish_parser_run(
                P,
                run,
                staged.lease,
                parsed=_counts(1),
                parse_result_sha256=RESULT,
                failure_code=None,
            ),
        )
    assert again.value.code == "parser_run_not_running"


def test_a_failed_ladder_code_cannot_finish_parsed(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "running")
    run = str(staged.run)
    issues = [_issue(ScheduleIssueCode.CORRUPT_PDF)]
    _do(db_engine, lambda r: r.insert_issues(P, staged.publication, staged.lease, run, issues))
    with pytest.raises(ScheduleIntegrityError) as failed:
        _do(
            db_engine,
            lambda r: r.finish_parser_run(
                P,
                run,
                staged.lease,
                parsed=_counts(0, issues),
                parse_result_sha256=RESULT,
                failure_code=None,
            ),
        )
    assert failed.value.code == "failed_outcome"


_OUTCOMES: Final[
    dict[str, tuple[list[ParsedScheduleRow], list[ScheduleParseIssue], SchedulePublicationStatus]]
] = {
    "complete_with_warning": (
        [_prow(1)],
        [_issue(ScheduleIssueCode.HEADER_OD_OCCLUDED)],
        SchedulePublicationStatus.COMPLETE,
    ),
    "partial": (
        [_prow(1), _prow(2)],
        [_issue(ScheduleIssueCode.INVALID_DATE, row_ordinal=2)],
        SchedulePublicationStatus.PARTIAL,
    ),
    "review_by_code": (
        [_prow(1)],
        [_issue(ScheduleIssueCode.PAGE_METADATA_MISMATCH)],
        SchedulePublicationStatus.REVIEW_REQUIRED,
    ),
    "review_by_ambiguous_row": (
        [_prow(1), _prow(2, kind=ScheduleRowType.AMBIGUOUS)],
        [],
        SchedulePublicationStatus.REVIEW_REQUIRED,
    ),
}


@pytest.mark.parametrize("case", sorted(_OUTCOMES))
def test_finalize_derives_the_status(db_engine: Engine, w: World, case: str) -> None:
    rows, issues, expected = _OUTCOMES[case]
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    run = _parse(db_engine, P, publication, lease, rows=rows, issues=issues)
    if expected is not SchedulePublicationStatus.REVIEW_REQUIRED:
        _canonicalize(db_engine, P, run, lease)
    assert _finalize(db_engine, P, publication, run, lease) is expected
    stored = _do(db_engine, lambda r: r.get_publication(P, publication))
    assert stored is not None
    assert (stored.status, stored.accepted_parser_run_id) == (expected, run)
    assert (stored.row_count, stored.issue_count, stored.page_count) == (
        len(rows),
        len(issues),
        1,
    )
    assert stored.activity_count == sum(
        1 for row in rows if row.row_type is not ScheduleRowType.AMBIGUOUS
    )
    assert stored.ambiguous_row_count == len(rows) - stored.activity_count


_GATED: Final[dict[str, tuple[list[ParsedScheduleRow], list[ScheduleParseIssue]]]] = {
    "review_code": ([_prow(1)], [_issue(ScheduleIssueCode.ROW_WRAP_UNSUPPORTED)]),
    "ambiguous_row": ([_prow(1), _prow(2, kind=ScheduleRowType.AMBIGUOUS)], []),
    "duplicate_ids": ([_prow(1, activity="A-1"), _prow(2, activity="A-1")], []),
}


@pytest.mark.parametrize("case", sorted(_GATED))
def test_canonicalize_refuses_a_review_or_failed_outcome(
    db_engine: Engine, w: World, case: str
) -> None:
    """A `failed` outcome never reaches here: F6 refuses to parse a failed-ladder run."""
    rows, issues = _GATED[case]
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    run = _parse(db_engine, P, publication, lease, rows=rows, issues=issues)
    before = _snapshot(db_engine)
    with pytest.raises(ScheduleIntegrityError) as gated:
        _canonicalize(db_engine, P, run, lease)
    assert gated.value.code == "identity_gate"
    assert _snapshot(db_engine) == before


def test_review_required_publication_links_nothing(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    rows = [_prow(1), _prow(2, kind=ScheduleRowType.AMBIGUOUS)]
    run = _parse(db_engine, P, publication, lease, rows=rows)
    assert _finalize(db_engine, P, publication, run, lease) is (
        SchedulePublicationStatus.REVIEW_REQUIRED
    )
    assert _count(db_engine, "schedule_activities") == 0
    assert _count(db_engine, "schedule_rows", "schedule_activity_id IS NOT NULL") == 0


def test_finalization_verifies_completeness(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    rows = [_prow(1, kind=ScheduleRowType.WBS_SUMMARY), _prow(2, parent=1), _prow(3, parent=1)]
    run = _parse(db_engine, P, publication, lease, rows=rows)
    assert _canonicalize(db_engine, P, run, lease, limit=1) == (1, 1, 1)
    with pytest.raises(ScheduleIntegrityError) as incomplete:
        _finalize(db_engine, P, publication, run, lease)
    assert incomplete.value.code == "incomplete_canonicalization"
    assert _canonicalize(db_engine, P, run, lease) == (1, 1, 0)
    assert _canonicalize(db_engine, P, run, lease) == (0, 0, 0)
    assert _finalize(db_engine, P, publication, run, lease) is SchedulePublicationStatus.COMPLETE
    stored = _do(db_engine, lambda r: r.get_publication(P, publication))
    assert stored is not None
    assert (stored.row_count, stored.activity_count, stored.ambiguous_row_count) == (3, 2, 0)
    assert stored.published_schedule_title == "Synthetic Project Schedule"
    assert stored.document_sha256 == DOC


def test_canonicalization_is_resumable_after_lease_loss(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    run = _parse(db_engine, P, publication, lease, rows=[_prow(n) for n in (1, 2, 3)])
    assert _canonicalize(db_engine, P, run, lease, limit=2) == (2, 2, 1)
    _expire(db_engine, lease)
    with pytest.raises(ScheduleLeaseLostError):
        _canonicalize(db_engine, P, run, lease)
    resumed = _lease(db_engine, P, publication)
    assert _canonicalize(db_engine, P, run, resumed) == (1, 1, 0)
    assert _count(db_engine, "schedule_activities") == 3
    assert _finalize(db_engine, P, publication, run, resumed) is (
        SchedulePublicationStatus.COMPLETE
    )


def test_orphan_stable_activity_is_reused_not_duplicated(db_engine: Engine, w: World) -> None:
    """Ruling (d): a Stable Activity outlives a publication that never finalized."""
    first = _admit(db_engine, P, _request(w, "cpm-key-0001"))
    first_publication = first.publication.publication_id
    lease = _lease(db_engine, P, first_publication)
    run = _parse(db_engine, P, first_publication, lease, rows=[_prow(1, activity="A-1")])
    _canonicalize(db_engine, P, run, lease)
    _do(
        db_engine,
        lambda r: r.fail_publication(
            P, first_publication, lease, ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED, None
        ),
    )
    orphan = _scalar(db_engine, "SELECT schedule_activity_id FROM knowledge.schedule_activities")
    second = _admit(db_engine, P, _request(w, "cpm-key-0002", version=w.v2))
    second_publication = second.publication.publication_id
    second_lease = _lease(db_engine, P, second_publication)
    second_run = _parse(
        db_engine, P, second_publication, second_lease, rows=[_prow(1, activity="A-1")]
    )
    assert _canonicalize(db_engine, P, second_run, second_lease) == (1, 0, 0)
    assert _count(db_engine, "schedule_activities") == 1
    linked = _scalar(
        db_engine,
        "SELECT schedule_activity_id FROM knowledge.schedule_rows WHERE parser_run_id = :r",
        r=second_run,
    )
    assert linked == orphan


def test_stable_activities_are_inserted_in_published_id_order(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    published = ["C-300", "A-100", "D-400", "B-200"]
    rows = [_prow(n, activity=pid) for n, pid in enumerate(published, start=1)]
    run = _parse(db_engine, P, publication, lease, rows=rows)
    _canonicalize(db_engine, P, run, lease)
    with db_engine.connect() as c:
        physical = (
            c.execute(
                text(
                    "SELECT published_activity_id FROM knowledge.schedule_activities ORDER BY ctid"
                )
            )
            .scalars()
            .all()
        )
    assert physical == sorted(published)


def test_finalize_closes_other_running_runs(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    accepted = _parse(db_engine, P, publication, lease)
    _expire(db_engine, lease)
    later = _lease(db_engine, P, publication)
    other_identity = replace(IDENTITY, parser_version="2")
    straggler = _start(db_engine, P, publication, later, other_identity)
    assert straggler != accepted
    assert _finalize(db_engine, P, publication, accepted, later) is (
        SchedulePublicationStatus.COMPLETE
    )
    runs = {
        run.parser_run_id: run
        for run in _do(db_engine, lambda r: r.get_parser_runs(P, publication))
    }
    assert runs[straggler].status is ScheduleParserRunStatus.FAILED
    assert runs[straggler].failure_code is None
    assert runs[accepted].status is ScheduleParserRunStatus.PARSED


def test_fail_publication_closes_running_runs(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    lease = _lease(db_engine, P, publication)
    abandoned = _parse(db_engine, P, publication, lease, finish=False)
    _expire(db_engine, lease)
    later = _lease(db_engine, P, publication)
    failed = _do(
        db_engine,
        lambda r: r.fail_publication(
            P, publication, later, ScheduleIssueCode.SOURCE_VERSION_CHANGED, None
        ),
    )
    assert failed.status is SchedulePublicationStatus.FAILED and failed.issue_count == 1
    (run,) = _do(db_engine, lambda r: r.get_parser_runs(P, publication))
    assert run.parser_run_id == abandoned
    assert run.status is ScheduleParserRunStatus.FAILED and run.failure_code is None


def test_fail_publication_records_a_safe_issue_and_terminalizes(
    db_engine: Engine, w: World
) -> None:
    staged = _stage(db_engine, w, "running")
    with pytest.raises(ValueError, match="error code"):
        _do(
            db_engine,
            lambda r: r.fail_publication(
                P, staged.publication, staged.lease, ScheduleIssueCode.HEADER_OD_OCCLUDED, None
            ),
        )
    failed = _do(
        db_engine,
        lambda r: r.fail_publication(
            P, staged.publication, staged.lease, ScheduleIssueCode.CORRUPT_PDF, staged.run
        ),
    )
    assert failed.status is SchedulePublicationStatus.FAILED
    assert failed.issue_count == 1 and failed.completed_at is not None
    assert failed.accepted_parser_run_id is None
    with db_engine.connect() as c:
        issue = (
            c.execute(
                text(
                    "SELECT parser_run_id, severity, code, page_number, row_ordinal, field "
                    "FROM knowledge.schedule_import_issues"
                )
            )
            .mappings()
            .one()
        )
    assert dict(issue) == {
        "parser_run_id": staged.run,
        "severity": "error",
        "code": "corrupt_pdf",
        "page_number": None,
        "row_ordinal": None,
        "field": None,
    }
    (run,) = _do(db_engine, lambda r: r.get_parser_runs(P, staged.publication))
    assert run.status is ScheduleParserRunStatus.FAILED
    assert run.failure_code is ScheduleIssueCode.CORRUPT_PDF


def test_run_less_failure_issue_is_recorded_once(db_engine: Engine, w: World) -> None:
    staged = _stage(db_engine, w, "processing")
    issue = [_issue(ScheduleIssueCode.SOURCE_VERSION_CHANGED)]
    _do(db_engine, lambda r: r.insert_issues(P, staged.publication, staged.lease, None, issue))
    failed = _do(
        db_engine,
        lambda r: r.fail_publication(
            P, staged.publication, staged.lease, ScheduleIssueCode.SOURCE_VERSION_CHANGED, None
        ),
    )
    assert failed.issue_count == 1
    assert _count(db_engine, "schedule_import_issues") == 1


def test_row_bounds_violation_fails_the_publication(db_engine: Engine, w: World) -> None:
    """Ruling (c): an oversized row writes nothing, then fails the publication."""
    staged = _stage(db_engine, w, "running")
    run = str(staged.run)
    oversized = _prow(1, hierarchy=("x" * 2001,))  # the per-label bound is domain-only
    before = _snapshot(db_engine)
    with pytest.raises(ScheduleRowBoundsError):
        _do(db_engine, lambda r: r.insert_rows(P, run, staged.lease, [oversized]))
    assert _snapshot(db_engine) == before
    failed = _do(
        db_engine,
        lambda r: r.fail_publication(
            P, staged.publication, staged.lease, ScheduleIssueCode.BOUNDS_EXCEEDED, run
        ),
    )
    assert failed.status is SchedulePublicationStatus.FAILED
    (stored,) = _do(db_engine, lambda r: r.get_parser_runs(P, staged.publication))
    assert stored.failure_code is ScheduleIssueCode.BOUNDS_EXCEEDED


def test_terminal_publication_refuses_every_worker_write(db_engine: Engine, w: World) -> None:
    admission, lease, run = _complete(db_engine, w, _request(w))
    publication = admission.publication.publication_id
    before = _snapshot(db_engine)
    writes: dict[str, Callable[[ScheduleRepository], object]] = {
        "pin_document": lambda r: r.pin_document(P, publication, lease, DOC, 1024),
        "start_parser_run": lambda r: r.start_parser_run(P, publication, lease, IDENTITY),
        "insert_issues": lambda r: r.insert_issues(
            P, publication, lease, None, [_issue(ScheduleIssueCode.SOURCE_VERSION_CHANGED)]
        ),
        "canonicalize_batch": lambda r: r.canonicalize_batch(P, run, lease, 1000),
        "finalize_publication": lambda r: r.finalize_publication(
            P, publication, lease, _final(run)
        ),
        "fail_publication": lambda r: r.fail_publication(
            P, publication, lease, ScheduleIssueCode.CORRUPT_PDF, None
        ),
    }
    for name, write in writes.items():
        with pytest.raises(ScheduleIntegrityError) as refused:
            _do(db_engine, write)
        assert refused.value.code == "publication_not_processing", name
    assert _snapshot(db_engine) == before


def test_exhausted_job_reads_effective_failed_without_writing(db_engine: Engine, w: World) -> None:
    admission = _admit(db_engine, P, _request(w))
    publication = admission.publication.publication_id
    _exhaust(db_engine, P, publication)
    before = _snapshot(db_engine)
    assert _do(db_engine, lambda r: r.get_effective_status(P, publication)) is (
        SchedulePublicationStatus.FAILED
    )
    stored = _do(db_engine, lambda r: r.get_publication(P, publication))
    assert stored is not None and stored.status is SchedulePublicationStatus.QUEUED
    assert _snapshot(db_engine) == before


# ---- the unit of work ---------------------------------------------------------------


def test_unit_of_work_commits_rolls_back_and_refuses_reentry(db_engine: Engine, w: World) -> None:
    uow = _uow(db_engine)
    with pytest.raises(RuntimeError, match="not inside a transaction"):
        _ = uow.schedules
    with uow, pytest.raises(RuntimeError, match="already inside"):
        uow.__enter__()
    request = _request(w)
    digest = schedule_import_request_digest(P, request)
    with pytest.raises(LookupError), _uow(db_engine) as rolled_back:
        rolled_back.schedules.admit_publication(P, request, digest)
        raise LookupError("abandon the transaction")
    assert _count(db_engine, "schedule_publications") == 0
    with pytest.raises(ValueError, match="digest"):
        _do(db_engine, lambda r: r.admit_publication(P, request, "0" * 64))
