"""Every S5b-1 CHECK, foreign key, unique and trigger, at head (foundation contract 4, 8).

Each test breaks exactly one rule and asserts the refusal names that rule: the
constraint name for a CHECK, unique or foreign key, the fixed trigger message
for a lifecycle guard. CHECK-only cases are seeded under
`session_replication_role = replica` (triggers and foreign keys silenced, CHECKs
still applied), so the CHECK is the only thing that can answer; every trigger
and foreign-key case runs in the default mode against a real, legal history
built step by step through the lifecycle the triggers allow.

`database` tier (`database_clone` by default): each test gets its own clone of
the head template. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

import pytest
from sqlalchemy import Engine, Table, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleIssueCode,
    ScheduleParseIssue,
    ScheduleRowType,
    derive_outcome,
)
from my_pa.domain.schedule import model as schedule_model
from my_pa.infrastructure.persistence.tables import (
    schedule_activities,
    schedule_import_issues,
    schedule_jobs,
    schedule_parser_runs,
    schedule_publications,
    schedule_rows,
    schedule_series,
)

pytestmark = pytest.mark.database

P: Final = "prn_cpmguard0001"
Q: Final = "prn_cpmguard0002"
DOC: Final = "a" * 64
OTHER_DOC: Final = "c" * 64
RESULT: Final = "b" * 64
CHECK_VIOLATION: Final = "23514"
FOREIGN_KEY_VIOLATION: Final = "23503"
UNIQUE_VIOLATION: Final = "23505"
RESTRICT_VIOLATION: Final = "23001"
CPM_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)
CELLS: Final[dict[str, object]] = {
    "schema": "cpm-full-cells-v1",
    "cells": {
        name: {"state": "published_blank", "text": None, "fragments": []}
        for name in (
            "activity_id",
            "activity_name",
            "original_duration",
            "remaining_duration",
            "start",
            "finish",
        )
    },
}


# ---- the world ------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """One Principal's Project and enrolled PDF, plus the near-misses FKs refuse."""

    principal: str
    tag: str
    project: str
    other_project: str
    enrollment: str
    source_object: str
    version: str
    second_version: str
    unenrolled_object: str
    unenrolled_version: str

    def series(self, n: int = 1) -> str:
        return f"sser_{self.tag}s{n:04d}"

    def publication(self, n: int) -> str:
        return f"spub_{self.tag}p{n:04d}"

    def job(self, n: int) -> str:
        return f"op_{self.tag}j{n:04d}"


def _world(engine: Engine, principal: str, tag: str) -> World:
    world = World(
        principal=principal,
        tag=tag,
        project=f"prj_{tag}0001",
        other_project=f"prj_{tag}0002",
        enrollment=f"enr_{tag}0001",
        source_object=f"obj_{tag}0001",
        version=f"ver_{tag}0001",
        second_version=f"ver_{tag}0002",
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
        for version, obj, fingerprint in (
            (world.version, world.source_object, "fp-1"),
            (world.second_version, world.source_object, "fp-2"),
            (world.unenrolled_version, world.unenrolled_object, "fp-9"),
        ):
            c.execute(
                text(
                    "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                    "fingerprint, media_type, size_bytes, modified_at) VALUES (:v, :o, :f, "
                    "'application/pdf', 1024, now())"
                ),
                {"v": version, "o": obj, "f": fingerprint},
            )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, depth, "
                "media_types, max_items, max_bytes) VALUES (:e, :s, :p, 'schedule_import', "
                "'policy-v1', :key, 'synthetic', ARRAY[:o], 0, ARRAY['application/pdf'], 10, "
                "1048576)"
            ),
            {
                "e": world.enrollment,
                "s": source,
                "p": principal,
                "key": tag,
                "o": world.source_object,
            },
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                "VALUES (:e, :o)"
            ),
            {"e": world.enrollment, "o": world.source_object},
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
    return _world(db_engine, P, "cpmga")


@pytest.fixture
def other(db_engine: Engine) -> World:
    return _world(db_engine, Q, "cpmgb")


# ---- lifecycle steps (each legal under every trigger) ----------------------------


def _series(c: Connection, w: World, n: int = 1, *, project: str | None = None) -> str:
    series = w.series(n)
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, name, "
            "name_key) VALUES (:s, :p, :j, :name, lower(:name)) ON CONFLICT DO NOTHING"
        ),
        {"s": series, "p": w.principal, "j": project or w.project, "name": f"Series {n}"},
    )
    return series


def _admit(
    c: Connection,
    w: World,
    n: int,
    *,
    series: int | None = None,
    version: str | None = None,
    supersedes: str | None = None,
    role: str = "update",
    baseline: str | None = None,
) -> str:
    """Admit publication `n` (in Series `n` unless told) with its one job."""
    publication = w.publication(n)
    series_id = _series(c, w, n if series is None else series)
    c.execute(
        insert(schedule_publications).values(
            publication_id=publication,
            principal_id=w.principal,
            project_id=w.project,
            series_id=series_id,
            enrollment_id=w.enrollment,
            source_object_id=w.source_object,
            source_version_id=version or w.version,
            idempotency_key=f"key-{w.tag}-{n:04d}",
            request_digest=DOC,
            publication_role=role,
            baseline_kind=baseline,
            supersedes_publication_id=supersedes,
        )
    )
    c.execute(
        insert(schedule_jobs).values(
            operation_id=w.job(n), publication_id=publication, principal_id=w.principal
        )
    )
    return publication


def _process(c: Connection, publication: str, *, pin: str | None = DOC) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_publications SET status = 'processing', "
            "processing_started_at = now(), updated_at = now() WHERE publication_id = :pub"
        ),
        {"pub": publication},
    )
    if pin is not None:
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET document_sha256 = :doc, "
                "document_size_bytes = 100 WHERE publication_id = :pub"
            ),
            {"pub": publication, "doc": pin},
        )


def _publication_row(c: Connection, publication: str) -> dict[str, object]:
    return dict(
        c.execute(
            text("SELECT * FROM knowledge.schedule_publications WHERE publication_id = :pub"),
            {"pub": publication},
        )
        .mappings()
        .one()
    )


def _job_of(c: Connection, publication: str) -> str:
    return str(
        c.execute(
            text("SELECT operation_id FROM knowledge.schedule_jobs WHERE publication_id = :pub"),
            {"pub": publication},
        ).scalar_one()
    )


def _run(
    c: Connection,
    publication: str,
    run: str,
    *,
    attempt: int = 1,
    doc: str = DOC,
    operation: str | None = None,
) -> str:
    pub = _publication_row(c, publication)
    c.execute(
        insert(schedule_parser_runs).values(
            parser_run_id=run,
            principal_id=pub["principal_id"],
            project_id=pub["project_id"],
            series_id=pub["series_id"],
            publication_id=publication,
            operation_id=operation or _job_of(c, publication),
            attempt_number=attempt,
            parser_name="cpm-workbench-full-parser",
            parser_version="1",
            profile_id="p6_full_v1",
            profile_version=1,
            pypdfium2_version="5.13.0",
            pdfium_version="153.0.7999.0",
            document_sha256=doc,
        )
    )
    return run


def _row_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "row_id": "srow_cpmgrow0001",
        "principal_id": P,
        "project_id": "prj_cpmga0001",
        "series_id": "sser_cpmgas0001",
        "publication_id": "spub_cpmgap0001",
        "parser_run_id": "sprun_cpmgr0001",
        "row_ordinal": 1,
        "page_number": 1,
        "physical_line_ordinal": 1,
        "row_type": "activity",
        "indent_level": 1,
        "parent_row_id": None,
        "hierarchy_path": ["Synthetic WBS"],
        "published_activity_id": "A-1000",
        "activity_name": "Synthetic activity",
        "od_state": "published_value",
        "od_value": Decimal("10.000"),
        "rd_state": "published_value",
        "rd_value": Decimal("5.000"),
        "start_state": "published_value",
        "start_date": date(2026, 5, 4),
        "start_marker": None,
        "finish_state": "published_value",
        "finish_date": date(2026, 5, 15),
        "finish_marker": "*",
        "bbox_x0_mpt": 1_000,
        "bbox_y0_mpt": 1_000,
        "bbox_x1_mpt": 2_000,
        "bbox_y1_mpt": 2_000,
        "page_width_mpt": 1_224_000,
        "page_height_mpt": 792_000,
        "cell_evidence": CELLS,
        "warning_codes": [],
    }
    values.update(overrides)
    return values


def _row(
    c: Connection,
    publication: str,
    run: str,
    ordinal: int,
    *,
    row_type: str = "activity",
    activity: str | None = None,
    parent: str | None = None,
    **overrides: object,
) -> str:
    pub = _publication_row(c, publication)
    row_id = f"srow_{run.removeprefix('sprun_')}o{ordinal:04d}"
    identity: dict[str, object] = {
        "published_activity_id": activity or f"A-{ordinal:04d}",
        "activity_name": f"Synthetic {ordinal}",
    }
    if row_type in ("project_summary", "wbs_summary"):
        identity = {"published_activity_id": None, "activity_name": f"Summary {ordinal}"}
    elif row_type == "ambiguous":
        identity = {"published_activity_id": None, "activity_name": None}
    c.execute(
        insert(schedule_rows).values(
            **_row_values(
                row_id=row_id,
                principal_id=pub["principal_id"],
                project_id=pub["project_id"],
                series_id=pub["series_id"],
                publication_id=publication,
                parser_run_id=run,
                row_ordinal=ordinal,
                physical_line_ordinal=ordinal,
                row_type=row_type,
                parent_row_id=parent,
                **identity,
                **overrides,
            )
        )
    )
    return row_id


def _issue(
    c: Connection,
    publication: str,
    run: str | None,
    n: int,
    code: ScheduleIssueCode,
    *,
    row_ordinal: int | None = None,
) -> str:
    pub = _publication_row(c, publication)
    issue = f"siss_{publication.removeprefix('spub_')}i{n:04d}"
    c.execute(
        insert(schedule_import_issues).values(
            issue_id=issue,
            principal_id=pub["principal_id"],
            project_id=pub["project_id"],
            series_id=pub["series_id"],
            publication_id=publication,
            parser_run_id=run,
            severity=ISSUE_SEVERITY[code].value,
            code=code.value,
            page_number=1,
            row_ordinal=row_ordinal,
        )
    )
    return issue


def _parse(c: Connection, run: str, **overrides: object) -> None:
    """`running -> parsed` with the counts the stored rows and issues imply."""
    counts = (
        c.execute(
            text(
                "SELECT (SELECT count(*) FROM knowledge.schedule_rows WHERE parser_run_id = :r) "
                "AS row_count, (SELECT count(*) FROM knowledge.schedule_import_issues WHERE "
                "parser_run_id = :r) AS issue_count, (SELECT count(*) FROM "
                "knowledge.schedule_import_issues WHERE parser_run_id = :r AND severity = "
                "'warning') AS warning_count"
            ),
            {"r": run},
        )
        .mappings()
        .one()
    )
    values = {
        "status": "parsed",
        "completed_at": text("now()"),
        "page_count": 1,
        "parse_result_sha256": RESULT,
        **counts,
        **overrides,
    }
    c.execute(
        schedule_parser_runs.update()
        .where(schedule_parser_runs.c.parser_run_id == run)
        .values(**values)
    )


def _fail_run(c: Connection, run: str, code: str | None = None) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_parser_runs SET status = 'failed', completed_at = now(), "
            "failure_code = :code WHERE parser_run_id = :r"
        ),
        {"r": run, "code": code},
    )


def _link(c: Connection, row_id: str) -> str:
    row = (
        c.execute(text("SELECT * FROM knowledge.schedule_rows WHERE row_id = :r"), {"r": row_id})
        .mappings()
        .one()
    )
    activity = f"sact_{row_id.removeprefix('srow_')}"
    c.execute(
        insert(schedule_activities).values(
            schedule_activity_id=activity,
            principal_id=row["principal_id"],
            project_id=row["project_id"],
            series_id=row["series_id"],
            published_activity_id=row["published_activity_id"],
        )
    )
    c.execute(
        text("UPDATE knowledge.schedule_rows SET schedule_activity_id = :a WHERE row_id = :r"),
        {"a": activity, "r": row_id},
    )
    return activity


def _derived_counts(c: Connection, run: str) -> dict[str, object]:
    return dict(
        c.execute(
            text(
                "SELECT r.page_count, r.row_count, (SELECT count(*) FROM knowledge.schedule_rows "
                "w WHERE w.parser_run_id = r.parser_run_id AND w.row_type IN ('activity', "
                "'milestone')) AS activity_count, (SELECT count(*) FROM knowledge.schedule_rows "
                "w WHERE w.parser_run_id = r.parser_run_id AND w.row_type = 'ambiguous') AS "
                "ambiguous_row_count, r.issue_count FROM knowledge.schedule_parser_runs r WHERE "
                "r.parser_run_id = :r"
            ),
            {"r": run},
        )
        .mappings()
        .one()
    )


def _finalize(c: Connection, publication: str, run: str, **overrides: object) -> None:
    status = c.execute(text("SELECT knowledge.schedule_run_outcome(:r)"), {"r": run}).scalar_one()
    values: dict[str, object] = {
        "status": status,
        "accepted_parser_run_id": run,
        "completed_at": text("now()"),
        "published_schedule_title": "Synthetic Project Schedule",
        "data_date": date(2026, 5, 4),
        "run_date": date(2026, 5, 11),
        **_derived_counts(c, run),
        **overrides,
    }
    c.execute(
        schedule_publications.update()
        .where(schedule_publications.c.publication_id == publication)
        .values(**values)
    )


def _fail(c: Connection, publication: str, **overrides: object) -> None:
    count = c.execute(
        text("SELECT count(*) FROM knowledge.schedule_import_issues WHERE publication_id = :pub"),
        {"pub": publication},
    ).scalar_one()
    values: dict[str, object] = {
        "status": "failed",
        "completed_at": text("now()"),
        "issue_count": count,
        **overrides,
    }
    c.execute(
        schedule_publications.update()
        .where(schedule_publications.c.publication_id == publication)
        .values(**values)
    )


def _complete(engine: Engine, w: World, n: int = 1, **admit: object) -> tuple[str, str, str]:
    """A `complete` publication: a summary and one linked activity. Returns ids."""
    with engine.begin() as c:
        publication = _admit(c, w, n, **admit)  # type: ignore[arg-type]
        _process(c, publication)
        run = _run(c, publication, f"sprun_{w.tag}r{n:04d}")
        summary = _row(c, publication, run, 1, row_type="wbs_summary")
        activity_row = _row(c, publication, run, 2, parent=summary)
        _parse(c, run)
        _link(c, activity_row)
        _finalize(c, publication, run)
    return publication, run, activity_row


def _parsed(engine: Engine, w: World, n: int = 1) -> tuple[str, str, str]:
    """A processing publication with one parsed run holding one unlinked activity."""
    with engine.begin() as c:
        publication = _admit(c, w, n)
        _process(c, publication)
        run = _run(c, publication, f"sprun_{w.tag}r{n:04d}")
        row = _row(c, publication, run, 1)
        _parse(c, run)
    return publication, run, row


def _running(engine: Engine, w: World, n: int = 1) -> tuple[str, str]:
    with engine.begin() as c:
        publication = _admit(c, w, n)
        _process(c, publication)
        run = _run(c, publication, f"sprun_{w.tag}r{n:04d}")
    return publication, run


# ---- assertions ----------------------------------------------------------------


def _refused(
    engine: Engine,
    write: Callable[[Connection], object],
    *,
    sqlstate: str,
    names: str,
    replica: bool = False,
) -> None:
    """`write` fails with `sqlstate`, and the failure names `names`."""
    with pytest.raises(DBAPIError) as refused, engine.begin() as c:
        if replica:
            c.execute(text("SET LOCAL session_replication_role = replica"))
        write(c)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate, str(refused.value)
    assert names in str(refused.value), str(refused.value)


def _accepted(
    engine: Engine, write: Callable[[Connection], object], *, replica: bool = False
) -> None:
    with engine.begin() as c:
        if replica:
            c.execute(text("SET LOCAL session_replication_role = replica"))
        write(c)


def _insert(table: Table, values: dict[str, object]) -> Callable[[Connection], object]:
    return lambda c: c.execute(insert(table).values(**values))


def _sql(statement: str, **values: object) -> Callable[[Connection], object]:
    return lambda c: c.execute(text(statement), values)


# ---- CHECKs (replica seeding; the CHECK alone answers) ----------------------------


def _series_values(**overrides: object) -> dict[str, object]:
    return {
        "series_id": "sser_cpmgcheck01",
        "principal_id": P,
        "project_id": "prj_cpmgcheck01",
        "name": "Master Schedule",
        "name_key": "master schedule",
        **overrides,
    }


def test_series_name_check_refuses_untrimmed_doubled_and_control(db_engine: Engine) -> None:
    name = "a_schedule_series_name_is_normalized"
    _accepted(db_engine, _insert(schedule_series, _series_values()), replica=True)
    for n, bad in enumerate((" Master", "Master ", "Master  Schedule", "Master\tX", "", "x" * 201)):
        _refused(
            db_engine,
            _insert(schedule_series, _series_values(series_id=f"sser_cpmgcheck9{n}", name=bad)),
            sqlstate=CHECK_VIOLATION,
            names=name,
            replica=True,
        )


def _publication_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "publication_id": "spub_cpmgcheck01",
        "principal_id": P,
        "project_id": "prj_cpmgcheck01",
        "series_id": "sser_cpmgcheck01",
        "enrollment_id": "enr_cpmgcheck01",
        "source_object_id": "obj_cpmgcheck01",
        "source_version_id": None,
        "idempotency_key": "check-key-0001",
        "request_digest": DOC,
        "publication_role": "update",
        "baseline_kind": None,
    }
    values.update(overrides)
    if values["source_version_id"] is None:
        values["source_version_id"] = f"ver_{str(values['publication_id']).removeprefix('spub_')}"
    return values


def test_baseline_kind_is_required_exactly_for_baseline(db_engine: Engine) -> None:
    name = "a_schedule_baseline_has_its_kind"
    for n, (role, kind) in enumerate(
        (("update", None), ("reference", None), ("baseline", "working"), ("baseline", "contract"))
    ):
        _accepted(
            db_engine,
            _insert(
                schedule_publications,
                _publication_values(
                    publication_id=f"spub_cpmgcheck1{n}",
                    idempotency_key=f"ok-key-{n:04d}",
                    publication_role=role,
                    baseline_kind=kind,
                ),
            ),
            replica=True,
        )
    for n, (role, kind) in enumerate(
        (("baseline", None), ("update", "working"), ("reference", "contract"))
    ):
        _refused(
            db_engine,
            _insert(
                schedule_publications,
                _publication_values(
                    publication_id=f"spub_cpmgcheck2{n}",
                    idempotency_key=f"bad-key-{n:04d}",
                    publication_role=role,
                    baseline_kind=kind,
                ),
            ),
            sqlstate=CHECK_VIOLATION,
            names=name,
            replica=True,
        )


def test_idempotency_key_has_the_precedent_shape(db_engine: Engine) -> None:
    name = "a_schedule_idempotency_key_is_bounded"
    for n, key in enumerate(("abcdefgh", "A" * 128, "key_with-dash_01")):
        _accepted(
            db_engine,
            _insert(
                schedule_publications,
                _publication_values(publication_id=f"spub_cpmgcheck3{n}", idempotency_key=key),
            ),
            replica=True,
        )
    for n, key in enumerate(("short", "k" * 129, "has space", "dot.key.0001", "slash/key/01")):
        _refused(
            db_engine,
            _insert(
                schedule_publications,
                _publication_values(publication_id=f"spub_cpmgcheck4{n}", idempotency_key=key),
            ),
            sqlstate=CHECK_VIOLATION,
            names=name,
            replica=True,
        )


#: A row legal under `a_schedule_publication_records_its_progress` for each
#: branch, and one change that breaks only that branch (R6 rulings, P67).
_ACCEPTED_TERMINAL: Final[dict[str, object]] = {
    "processing_started_at": text("now()"),
    "completed_at": text("now()"),
    "accepted_parser_run_id": "sprun_cpmgcheck01",
    "document_sha256": DOC,
    "document_size_bytes": 100,
    "page_count": 1,
    "row_count": 2,
    "activity_count": 1,
    "ambiguous_row_count": 0,
    "issue_count": 0,
}
_PROGRESS: Final[dict[str, tuple[dict[str, object], dict[str, object]]]] = {
    "queued": ({"status": "queued"}, {"row_count": 1}),
    "processing": (
        {"status": "processing", "processing_started_at": text("now()")},
        {"completed_at": text("now()")},
    ),
    "accepted_terminal": (
        {"status": "complete", **_ACCEPTED_TERMINAL},
        {"issue_count": None},
    ),
    "failed": (
        {
            "status": "failed",
            "processing_started_at": text("now()"),
            "completed_at": text("now()"),
            "issue_count": 1,
        },
        {"issue_count": 0},
    ),
}


@pytest.mark.parametrize("branch", sorted(_PROGRESS))
def test_publication_progress_columns_follow_status(db_engine: Engine, branch: str) -> None:
    legal, breaking = _PROGRESS[branch]
    _accepted(
        db_engine,
        _insert(schedule_publications, _publication_values(**legal)),
        replica=True,
    )
    _refused(
        db_engine,
        _insert(
            schedule_publications,
            _publication_values(
                publication_id="spub_cpmgcheck02",
                idempotency_key="check-key-0002",
                **{**legal, **breaking},
            ),
        ),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_publication_records_its_progress",
        replica=True,
    )


_ROW_IDENTITY: Final = "a_schedule_row_identity_matches_its_type"


def test_row_identity_matches_type(db_engine: Engine) -> None:
    legal = (
        ("activity", "A-1", "Name"),
        ("milestone", "M-1", "Name"),
        ("wbs_summary", None, "Label"),
        ("project_summary", None, "Label"),
        ("ambiguous", None, None),
    )
    for n, (row_type, activity, name) in enumerate(legal):
        _accepted(
            db_engine,
            _insert(
                schedule_rows,
                _row_values(
                    row_id=f"srow_cpmgcheck0{n}",
                    row_ordinal=n + 1,
                    row_type=row_type,
                    published_activity_id=activity,
                    activity_name=name,
                ),
            ),
            replica=True,
        )
    illegal = (
        ("activity", None, "Name"),
        ("milestone", "M-1", None),
        ("wbs_summary", "W-1", "Label"),
        ("project_summary", None, None),
        ("ambiguous", "X-1", None),
        ("ambiguous", None, "Name"),
    )
    for n, (row_type, activity, name) in enumerate(illegal):
        _refused(
            db_engine,
            _insert(
                schedule_rows,
                _row_values(
                    row_id=f"srow_cpmgcheck1{n}",
                    row_ordinal=10 + n,
                    row_type=row_type,
                    published_activity_id=activity,
                    activity_name=name,
                ),
            ),
            sqlstate=CHECK_VIOLATION,
            names=_ROW_IDENTITY,
            replica=True,
        )


def test_only_id_bearing_rows_link(db_engine: Engine) -> None:
    name = "a_schedule_row_links_only_an_activity_or_milestone"
    _accepted(
        db_engine,
        _insert(schedule_rows, _row_values(schedule_activity_id="sact_cpmgcheck01")),
        replica=True,
    )
    _refused(
        db_engine,
        _insert(
            schedule_rows,
            _row_values(
                row_id="srow_cpmgcheck02",
                row_ordinal=2,
                row_type="wbs_summary",
                published_activity_id=None,
                schedule_activity_id="sact_cpmgcheck01",
            ),
        ),
        sqlstate=CHECK_VIOLATION,
        names=name,
        replica=True,
    )


_CELL_COLUMNS: Final = {
    "od": ("od_state", "od_value", Decimal("1.000")),
    "rd": ("rd_state", "rd_value", Decimal("1.000")),
    "start": ("start_state", "start_date", date(2026, 5, 4)),
    "finish": ("finish_state", "finish_date", date(2026, 5, 4)),
}


@pytest.mark.parametrize("present", [True, False], ids=["value", "no_value"])
@pytest.mark.parametrize("state", [state.value for state in ScheduleCellState])
@pytest.mark.parametrize("cell", sorted(_CELL_COLUMNS))
def test_four_state_typed_value_matrix(
    db_engine: Engine, cell: str, state: str, present: bool
) -> None:
    """R2 section 17.2: a typed value exists exactly in the `published_value` state."""
    state_column, value_column, value = _CELL_COLUMNS[cell]
    values = _row_values(
        **{state_column: state, value_column: value if present else None},
        start_marker=None,
        finish_marker=None,
    )
    write = _insert(schedule_rows, values)
    if present == (state == "published_value"):
        _accepted(db_engine, write, replica=True)
    else:
        _refused(
            db_engine,
            write,
            sqlstate=CHECK_VIOLATION,
            names=f"a_schedule_row_{cell}_is_typed",
            replica=True,
        )


def test_negative_durations_and_stray_markers_are_refused(db_engine: Engine) -> None:
    _refused(
        db_engine,
        _insert(schedule_rows, _row_values(od_value=Decimal("-1.000"))),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_row_od_is_typed",
        replica=True,
    )
    _refused(
        db_engine,
        _insert(
            schedule_rows,
            _row_values(start_state="published_blank", start_date=None, start_marker="*"),
        ),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_row_start_marker_is_known",
        replica=True,
    )
    _refused(
        db_engine,
        _insert(schedule_rows, _row_values(finish_marker="+")),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_row_finish_marker_is_known",
        replica=True,
    )


_BOUNDS: Final[dict[str, tuple[dict[str, object], dict[str, object], str]]] = {
    "cell_evidence": (
        {"cell_evidence": {**CELLS, "padding": "x" * 30_000}},
        {"cell_evidence": {**CELLS, "padding": "x" * 33_000}},
        "a_schedule_row_cell_evidence_is_bounded",
    ),
    "cell_evidence_shape": (
        {"cell_evidence": CELLS},
        {"cell_evidence": {"schema": "cpm-full-cells-v1", "cells": {"activity_id": {}}}},
        "a_schedule_row_cell_evidence_is_bounded",
    ),
    "hierarchy": (
        {"hierarchy_path": ["L"] * 32},
        {"hierarchy_path": ["L"] * 33},
        "a_schedule_row_hierarchy_is_bounded",
    ),
    "warnings": (
        {"warning_codes": [ScheduleIssueCode.HEADER_OD_OCCLUDED.value] * 16},
        {"warning_codes": [ScheduleIssueCode.HEADER_OD_OCCLUDED.value] * 17},
        "a_schedule_row_warnings_are_bounded",
    ),
    "warning_codes": (
        {"warning_codes": [ScheduleIssueCode.INVALID_DATE.value]},
        {"warning_codes": ["not_a_code"]},
        "a_schedule_row_warning_codes_are_known",
    ),
}


@pytest.mark.parametrize("bound", sorted(_BOUNDS))
def test_cell_evidence_hierarchy_and_warning_bounds(db_engine: Engine, bound: str) -> None:
    legal, breaking, name = _BOUNDS[bound]
    _accepted(db_engine, _insert(schedule_rows, _row_values(**legal)), replica=True)
    _refused(
        db_engine,
        _insert(schedule_rows, _row_values(row_id="srow_cpmgcheck02", row_ordinal=2, **breaking)),
        sqlstate=CHECK_VIOLATION,
        names=name,
        replica=True,
    )


def _issue_values(**overrides: object) -> dict[str, object]:
    return {
        "issue_id": "siss_cpmgcheck01",
        "principal_id": P,
        "project_id": "prj_cpmgcheck01",
        "series_id": "sser_cpmgcheck01",
        "publication_id": "spub_cpmgcheck01",
        "parser_run_id": "sprun_cpmgcheck01",
        "severity": "error",
        "code": "invalid_date",
        **overrides,
    }


def test_issue_severity_matches_code(db_engine: Engine) -> None:
    name = "a_schedule_issue_severity_matches_its_code"
    for n, code in enumerate(ScheduleIssueCode):
        _accepted(
            db_engine,
            _insert(
                schedule_import_issues,
                _issue_values(
                    issue_id=f"siss_cpmgcheck{n:02d}",
                    code=code.value,
                    severity=ISSUE_SEVERITY[code],
                ),
            ),
            replica=True,
        )
    for n, (code, severity) in enumerate(
        (("header_od_occluded", "error"), ("invalid_date", "warning"))
    ):
        _refused(
            db_engine,
            _insert(
                schedule_import_issues,
                _issue_values(issue_id=f"siss_cpmgcheck9{n}", code=code, severity=severity),
            ),
            sqlstate=CHECK_VIOLATION,
            names=name,
            replica=True,
        )


def test_row_issue_needs_its_run(db_engine: Engine) -> None:
    name = "a_schedule_issue_row_has_its_run"
    _accepted(
        db_engine,
        _insert(schedule_import_issues, _issue_values(parser_run_id=None, row_ordinal=None)),
        replica=True,
    )
    _refused(
        db_engine,
        _insert(
            schedule_import_issues,
            _issue_values(issue_id="siss_cpmgcheck02", parser_run_id=None, row_ordinal=1),
        ),
        sqlstate=CHECK_VIOLATION,
        names=name,
        replica=True,
    )


def test_supersession_is_same_series_once_and_not_self(db_engine: Engine, w: World) -> None:
    """Not self (CHECK); same Series (FK); at most one successor (partial unique)."""
    _refused(
        db_engine,
        _insert(
            schedule_publications,
            _publication_values(supersedes_publication_id="spub_cpmgcheck01"),
        ),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_publication_does_not_supersede_itself",
        replica=True,
    )
    first, _, _ = _complete(db_engine, w, 1)

    def other_series(c: Connection) -> None:
        _admit(c, w, 2, series=2, version=w.second_version, supersedes=first)

    _refused(
        db_engine,
        other_series,
        sqlstate=FOREIGN_KEY_VIOLATION,
        names="a_schedule_publication_supersedes_within_its_series",
    )
    _accepted(
        db_engine, lambda c: _admit(c, w, 3, series=1, version=w.second_version, supersedes=first)
    )
    _refused(
        db_engine,
        lambda c: _admit(c, w, 4, series=1, version=w.unenrolled_version, supersedes=first),
        sqlstate=UNIQUE_VIOLATION,
        names="a_schedule_publication_is_superseded_once",
    )


# ---- foreign keys (default mode; the FK alone answers) -----------------------------------


def _fk_cases(
    w: World, other: World
) -> dict[str, Callable[[Engine], Callable[[Connection], object]]]:
    """For each section 4.8 foreign key, a write that only it refuses."""

    def series_project(_engine: Engine) -> Callable[[Connection], object]:
        return lambda c: _series(c, w, 5, project=other.project)

    def publication_series(_engine: Engine) -> Callable[[Connection], object]:
        def write(c: Connection) -> None:
            series = _series(c, w, 6, project=w.other_project)
            c.execute(
                insert(schedule_publications).values(
                    **_publication_values(
                        publication_id=w.publication(6),
                        principal_id=w.principal,
                        project_id=w.project,
                        series_id=series,
                        enrollment_id=w.enrollment,
                        source_object_id=w.source_object,
                        source_version_id=w.version,
                    )
                )
            )
            c.execute(
                insert(schedule_jobs).values(
                    operation_id=w.job(6), publication_id=w.publication(6), principal_id=P
                )
            )

        return write

    def binding(**changes: str) -> Callable[[Engine], Callable[[Connection], object]]:
        def case(_engine: Engine) -> Callable[[Connection], object]:
            def write(c: Connection) -> None:
                series = _series(c, w)
                c.execute(
                    insert(schedule_publications).values(
                        **_publication_values(
                            **{
                                "publication_id": w.publication(7),
                                "principal_id": w.principal,
                                "project_id": w.project,
                                "series_id": series,
                                "enrollment_id": w.enrollment,
                                "source_object_id": w.source_object,
                                "source_version_id": w.version,
                                **changes,
                            }
                        )
                    )
                )
                c.execute(
                    insert(schedule_jobs).values(
                        operation_id=w.job(7), publication_id=w.publication(7), principal_id=P
                    )
                )

            return write

        return case

    def accepted_run(engine: Engine) -> Callable[[Connection], object]:
        _, foreign_run, foreign_row = _parsed(engine, w, 8)
        publication, run, _ = _parsed(engine, w, 9)
        with engine.begin() as c:
            _link(c, foreign_row)

        def write(c: Connection) -> None:
            _finalize(c, publication, run, accepted_parser_run_id=foreign_run)

        return write

    def activity_series(_engine: Engine) -> Callable[[Connection], object]:
        def write(c: Connection) -> None:
            _series(c, w)
            c.execute(
                insert(schedule_activities).values(
                    schedule_activity_id="sact_cpmgfk0001",
                    principal_id=P,
                    project_id=w.other_project,
                    series_id=w.series(1),
                    published_activity_id="A-1",
                )
            )

        return write

    def job_publication(_engine: Engine) -> Callable[[Connection], object]:
        def write(c: Connection) -> None:
            series = _series(c, w, 10)
            c.execute(
                insert(schedule_publications).values(
                    **_publication_values(
                        publication_id=w.publication(10),
                        project_id=w.project,
                        series_id=series,
                        enrollment_id=w.enrollment,
                        source_object_id=w.source_object,
                        source_version_id=w.version,
                    )
                )
            )
            c.execute(
                insert(schedule_jobs).values(
                    operation_id=w.job(10), publication_id=w.publication(10), principal_id=Q
                )
            )

        return write

    def run_publication(engine: Engine) -> Callable[[Connection], object]:
        publication, _ = _running(engine, w, 11)

        def write(c: Connection) -> None:
            c.execute(
                insert(schedule_parser_runs).values(
                    parser_run_id="sprun_cpmgfk0011",
                    principal_id=P,
                    project_id=w.other_project,
                    series_id=w.series(1),
                    publication_id=publication,
                    operation_id=w.job(11),
                    attempt_number=2,
                    parser_name="p",
                    parser_version="1",
                    profile_id="x",
                    profile_version=1,
                    pypdfium2_version="1",
                    pdfium_version="1",
                    document_sha256=DOC,
                )
            )

        return write

    def run_job(engine: Engine) -> Callable[[Connection], object]:
        _running(engine, w, 12)
        publication, _ = _running(engine, w, 13)
        return lambda c: _run(c, publication, "sprun_cpmgfk0013", attempt=2, operation=w.job(12))

    def row_run(engine: Engine) -> Callable[[Connection], object]:
        _, foreign_run = _running(engine, w, 14)
        publication, _ = _running(engine, w, 15)
        return lambda c: _row(c, publication, foreign_run, 1)

    def row_publication(engine: Engine) -> Callable[[Connection], object]:
        publication, run = _running(engine, w, 16)

        def write(c: Connection) -> None:
            c.execute(
                insert(schedule_rows).values(
                    **_row_values(
                        row_id="srow_cpmgfk0016",
                        principal_id=P,
                        project_id=w.other_project,
                        series_id=w.series(1),
                        publication_id=publication,
                        parser_run_id=run,
                    )
                )
            )

        return write

    def row_parent(engine: Engine) -> Callable[[Connection], object]:
        publication, run = _running(engine, w, 17)
        _, foreign_run = _running(engine, w, 18)
        with engine.begin() as c:
            foreign_parent = _row(c, w.publication(18), foreign_run, 1)
        return lambda c: _row(c, publication, run, 2, parent=foreign_parent)

    def row_activity(engine: Engine) -> Callable[[Connection], object]:
        _, _, row = _parsed(engine, w, 19)
        with engine.begin() as c:
            c.execute(
                insert(schedule_activities).values(
                    schedule_activity_id="sact_cpmgfk0019",
                    principal_id=P,
                    project_id=w.project,
                    series_id=w.series(19),
                    published_activity_id="A-OTHER",
                )
            )
        return _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = 'sact_cpmgfk0019' "
            "WHERE row_id = :r",
            r=row,
        )

    def issue_publication(engine: Engine) -> Callable[[Connection], object]:
        publication, _ = _running(engine, w, 20)
        return _insert(
            schedule_import_issues,
            _issue_values(
                issue_id="siss_cpmgfk0020",
                project_id=w.other_project,
                series_id=w.series(1),
                publication_id=publication,
                parser_run_id=None,
            ),
        )

    def issue_run(engine: Engine) -> Callable[[Connection], object]:
        _, foreign_run = _running(engine, w, 21)
        publication, _ = _running(engine, w, 22)
        return lambda c: _issue(c, publication, foreign_run, 1, ScheduleIssueCode.INVALID_DATE)

    def issue_row(engine: Engine) -> Callable[[Connection], object]:
        publication, run = _running(engine, w, 23)
        return lambda c: _issue(
            c, publication, run, 1, ScheduleIssueCode.INVALID_DATE, row_ordinal=5
        )

    return {
        "a_schedule_series_names_a_project_of_its_principal": series_project,
        "a_schedule_publication_names_its_series": publication_series,
        "a_schedule_publication_names_an_enrollment_of_its_principal": binding(
            enrollment_id=other.enrollment,
            source_object_id=other.source_object,
            source_version_id=other.version,
        ),
        "a_schedule_publication_names_an_enrolled_object": binding(
            source_object_id=w.unenrolled_object, source_version_id=w.unenrolled_version
        ),
        "a_schedule_publication_names_a_version_of_its_object": binding(
            source_version_id=w.unenrolled_version
        ),
        "a_schedule_publication_accepts_one_of_its_runs": accepted_run,
        "a_schedule_activity_belongs_to_its_series": activity_series,
        "a_schedule_job_names_a_publication_of_its_principal": job_publication,
        "a_schedule_parser_run_names_its_publication": run_publication,
        "a_schedule_parser_run_names_its_job": run_job,
        "a_schedule_row_belongs_to_its_run": row_run,
        "a_schedule_row_belongs_to_its_publication": row_publication,
        "a_schedule_row_parent_is_in_its_run": row_parent,
        "a_schedule_row_links_its_exact_activity": row_activity,
        "a_schedule_issue_belongs_to_its_publication": issue_publication,
        "a_schedule_issue_belongs_to_its_run": issue_run,
        "a_schedule_issue_names_a_row_of_its_run": issue_row,
    }


_FOREIGN_KEYS: Final = (
    "a_schedule_series_names_a_project_of_its_principal",
    "a_schedule_publication_names_its_series",
    "a_schedule_publication_names_an_enrollment_of_its_principal",
    "a_schedule_publication_names_an_enrolled_object",
    "a_schedule_publication_names_a_version_of_its_object",
    "a_schedule_publication_accepts_one_of_its_runs",
    "a_schedule_activity_belongs_to_its_series",
    "a_schedule_job_names_a_publication_of_its_principal",
    "a_schedule_parser_run_names_its_publication",
    "a_schedule_parser_run_names_its_job",
    "a_schedule_row_belongs_to_its_run",
    "a_schedule_row_belongs_to_its_publication",
    "a_schedule_row_parent_is_in_its_run",
    "a_schedule_row_links_its_exact_activity",
    "a_schedule_issue_belongs_to_its_publication",
    "a_schedule_issue_belongs_to_its_run",
    "a_schedule_issue_names_a_row_of_its_run",
)


@pytest.mark.parametrize("foreign_key", _FOREIGN_KEYS)
def test_foreign_key_refuses_a_cross_binding(
    db_engine: Engine, w: World, other: World, foreign_key: str
) -> None:
    write = _fk_cases(w, other)[foreign_key](db_engine)
    _refused(db_engine, write, sqlstate=FOREIGN_KEY_VIOLATION, names=foreign_key)


def test_every_foreign_key_has_a_cross_binding_case(db_engine: Engine) -> None:
    with db_engine.connect() as c:
        declared = set(
            c.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con JOIN pg_class t "
                    "ON t.oid = con.conrelid WHERE con.contype = 'f' AND t.relname = ANY(:t)"
                ),
                {"t": list(CPM_TABLES)},
            ).scalars()
        )
    assert declared == set(_FOREIGN_KEYS) | {"a_schedule_publication_supersedes_within_its_series"}


def test_publication_cannot_cross_enrollment_object_or_version(
    db_engine: Engine, w: World, other: World
) -> None:
    """R2 sections 9.2-9.3: the three bindings, each refused by its own key."""
    cases = _fk_cases(w, other)
    for name in (
        "a_schedule_publication_names_an_enrollment_of_its_principal",
        "a_schedule_publication_names_an_enrolled_object",
        "a_schedule_publication_names_a_version_of_its_object",
    ):
        _refused(db_engine, cases[name](db_engine), sqlstate=FOREIGN_KEY_VIOLATION, names=name)


def test_issue_row_ordinal_names_a_row_of_its_run(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _row(c, publication, run, 1)
        _issue(c, publication, run, 1, ScheduleIssueCode.INVALID_DATE, row_ordinal=1)
    _refused(
        db_engine,
        lambda c: _issue(c, publication, run, 2, ScheduleIssueCode.INVALID_DATE, row_ordinal=2),
        sqlstate=FOREIGN_KEY_VIOLATION,
        names="a_schedule_issue_names_a_row_of_its_run",
    )


def test_link_binds_exact_id_and_series(db_engine: Engine, w: World) -> None:
    """The stable link proves Principal, Series and the exact published ID."""
    _, _, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        _series(c, w, 2)
        for activity, series, published in (
            ("sact_cpmglink01", w.series(1), "A-0001"),
            ("sact_cpmglink02", w.series(2), "A-0001"),
            ("sact_cpmglink03", w.series(1), "a-0001"),
        ):
            c.execute(
                insert(schedule_activities).values(
                    schedule_activity_id=activity,
                    principal_id=P,
                    project_id=w.project,
                    series_id=series,
                    published_activity_id=published,
                )
            )
    for activity in ("sact_cpmglink02", "sact_cpmglink03"):
        _refused(
            db_engine,
            _sql(
                "UPDATE knowledge.schedule_rows SET schedule_activity_id = :a WHERE row_id = :r",
                a=activity,
                r=row,
            ),
            sqlstate=FOREIGN_KEY_VIOLATION,
            names="a_schedule_row_links_its_exact_activity",
        )
    _accepted(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = 'sact_cpmglink01' "
            "WHERE row_id = :r",
            r=row,
        ),
    )


def test_source_delete_is_refused_while_a_publication_references_it(
    db_engine: Engine, w: World
) -> None:
    """U-10 (R6-F08): `RESTRICT` beneath cascading source deletes refuses the whole delete."""
    _running(db_engine, w)
    for statement in (
        "DELETE FROM knowledge.sources WHERE source_id = 'src_cpmga0001'",
        "DELETE FROM knowledge.source_objects WHERE source_object_id = 'obj_cpmga0001'",
    ):
        _refused(
            db_engine,
            _sql(statement),
            sqlstate=FOREIGN_KEY_VIOLATION,
            names="a_schedule_publication_names",
        )


# ---- uniques ---------------------------------------------------------------------


def test_series_name_key_is_unique_within_its_project(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        _series(c, w, 1)
    _refused(
        db_engine,
        _insert(
            schedule_series,
            {
                "series_id": "sser_cpmgdupl01",
                "principal_id": P,
                "project_id": w.project,
                "name": "SERIES 1",
                "name_key": "series 1",
            },
        ),
        sqlstate=UNIQUE_VIOLATION,
        names="a_schedule_series_name_is_unique_within_its_project",
    )
    _accepted(
        db_engine,
        _insert(
            schedule_series,
            {
                "series_id": "sser_cpmgdupl02",
                "principal_id": P,
                "project_id": w.other_project,
                "name": "Series 1",
                "name_key": "series 1",
            },
        ),
    )


def _unique_cases(w: World) -> dict[str, Callable[[Engine], Callable[[Connection], object]]]:
    def key_used_once(engine: Engine) -> Callable[[Connection], object]:
        _running(engine, w, 1)

        def write(c: Connection) -> None:
            c.execute(
                insert(schedule_publications).values(
                    **_publication_values(
                        publication_id=w.publication(2),
                        project_id=w.project,
                        series_id=w.series(1),
                        enrollment_id=w.enrollment,
                        source_object_id=w.source_object,
                        source_version_id=w.second_version,
                        idempotency_key=f"key-{w.tag}-0001",
                    )
                )
            )

        return write

    def version_once_per_series(engine: Engine) -> Callable[[Connection], object]:
        _running(engine, w, 1)
        return lambda c: _admit(c, w, 2, series=1)

    def superseded_once(engine: Engine) -> Callable[[Connection], object]:
        first, _, _ = _complete(engine, w, 1)
        with engine.begin() as c:
            _admit(c, w, 2, series=1, version=w.second_version, supersedes=first)
        return lambda c: _admit(c, w, 3, series=1, version=w.unenrolled_version, supersedes=first)

    def one_job(engine: Engine) -> Callable[[Connection], object]:
        publication, _ = _running(engine, w, 1)
        return _insert(
            schedule_jobs,
            {"operation_id": "op_cpmgdupl0001", "publication_id": publication, "principal_id": P},
        )

    def parse_accepted_once(engine: Engine) -> Callable[[Connection], object]:
        publication, _, _ = _parsed(engine, w, 1)

        def write(c: Connection) -> None:
            second = _run(c, publication, "sprun_cpmgdupl02", attempt=2)
            _row(c, publication, second, 1)
            _parse(c, second)

        return write

    def ordinal_unique(engine: Engine) -> Callable[[Connection], object]:
        publication, run = _running(engine, w, 1)
        with engine.begin() as c:
            _row(c, publication, run, 1)
        return _insert(
            schedule_rows,
            _row_values(
                row_id="srow_cpmgdupl0001",
                project_id=w.project,
                series_id=w.series(1),
                publication_id=publication,
                parser_run_id=run,
                row_ordinal=1,
            ),
        )

    def activity_id_unique(engine: Engine) -> Callable[[Connection], object]:
        with engine.begin() as c:
            _series(c, w)
            c.execute(
                insert(schedule_activities).values(
                    schedule_activity_id="sact_cpmgdupl01",
                    principal_id=P,
                    project_id=w.project,
                    series_id=w.series(1),
                    published_activity_id="A-1",
                )
            )
        return _insert(
            schedule_activities,
            {
                "schedule_activity_id": "sact_cpmgdupl02",
                "principal_id": P,
                "project_id": w.project,
                "series_id": w.series(1),
                "published_activity_id": "A-1",
            },
        )

    return {
        "a_schedule_publication_key_is_used_once": key_used_once,
        "a_schedule_source_version_is_published_once_per_series": version_once_per_series,
        "a_schedule_publication_is_superseded_once": superseded_once,
        "a_schedule_publication_has_one_job": one_job,
        "a_schedule_parse_is_accepted_once": parse_accepted_once,
        "a_schedule_row_ordinal_is_unique_within_its_run": ordinal_unique,
        "a_schedule_activity_id_is_unique_within_its_series": activity_id_unique,
    }


@pytest.mark.parametrize(
    "unique",
    [
        "a_schedule_publication_key_is_used_once",
        "a_schedule_source_version_is_published_once_per_series",
        "a_schedule_publication_is_superseded_once",
        "a_schedule_publication_has_one_job",
        "a_schedule_parse_is_accepted_once",
        "a_schedule_row_ordinal_is_unique_within_its_run",
        "a_schedule_activity_id_is_unique_within_its_series",
    ],
)
def test_unique_holds(db_engine: Engine, w: World, unique: str) -> None:
    write = _unique_cases(w)[unique](db_engine)
    _refused(db_engine, write, sqlstate=UNIQUE_VIOLATION, names=unique)


def test_one_parser_run_per_attempt(db_engine: Engine, w: World) -> None:
    publication, _ = _running(db_engine, w)
    _refused(
        db_engine,
        lambda c: _run(c, publication, "sprun_cpmgdupl03", attempt=1),
        sqlstate=UNIQUE_VIOLATION,
        names="a_schedule_attempt_starts_one_parser_run",
    )
    _accepted(db_engine, lambda c: _run(c, publication, "sprun_cpmgdupl04", attempt=2))


# ---- F3: the publication lifecycle -------------------------------------------------


def _update_publication(publication: str, **values: object) -> Callable[[Connection], object]:
    return lambda c: c.execute(
        schedule_publications.update()
        .where(schedule_publications.c.publication_id == publication)
        .values(**values)
    )


def test_publication_is_admitted_queued(db_engine: Engine, w: World) -> None:
    def write(c: Connection) -> None:
        _series(c, w)
        c.execute(
            insert(schedule_publications).values(
                **_publication_values(
                    publication_id=w.publication(1),
                    project_id=w.project,
                    series_id=w.series(1),
                    enrollment_id=w.enrollment,
                    source_object_id=w.source_object,
                    source_version_id=w.version,
                    status="processing",
                    processing_started_at=text("now()"),
                )
            )
        )

    _refused(
        db_engine,
        write,
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication is admitted queued",
    )


def test_publication_is_never_deleted(db_engine: Engine, w: World) -> None:
    publication, _ = _running(db_engine, w)
    _refused(
        db_engine,
        _sql(
            "DELETE FROM knowledge.schedule_publications WHERE publication_id = :p", p=publication
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication is never deleted",
    )


def test_terminal_publication_is_immutable(db_engine: Engine, w: World) -> None:
    publication, _, _ = _complete(db_engine, w)
    for change in (
        {"updated_at": text("now()")},
        {"published_schedule_title": "Changed"},
        {"status": "processing", "completed_at": None},
    ):
        _refused(
            db_engine,
            _update_publication(publication, **change),
            sqlstate=RESTRICT_VIOLATION,
            names="a terminal schedule publication is immutable",
        )


def test_publication_transitions_are_forward_only(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        queued = _admit(c, w, 1)
    _refused(
        db_engine,
        _update_publication(queued, updated_at=text("now()")),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication moves forward only",
    )
    _refused(
        db_engine,
        _update_publication(queued, status="complete", **_ACCEPTED_TERMINAL),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication moves forward only",
    )
    processing, _ = _running(db_engine, w, 2)
    _refused(
        db_engine,
        _update_publication(processing, status="queued", processing_started_at=None),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication moves forward only",
    )


_ADMISSION_CHANGES: Final[dict[str, object]] = {
    "publication_id": "spub_cpmgchanged",
    "principal_id": Q,
    "project_id": "prj_cpmga0002",
    "series_id": "sser_cpmgas0002",
    "enrollment_id": "enr_cpmgb0001",
    "source_object_id": "obj_cpmga0009",
    "source_version_id": "ver_cpmga0002",
    "idempotency_key": "changed-key-0001",
    "request_digest": OTHER_DOC,
    "publication_role": "reference",
    "baseline_kind": "working",
    "expected_data_date": date(2026, 1, 1),
    "supersedes_publication_id": "spub_cpmgap0009",
    "admitted_at": text("now() - interval '1 day'"),
}


@pytest.mark.parametrize("column", sorted(_ADMISSION_CHANGES))
def test_admission_columns_are_immutable(db_engine: Engine, w: World, column: str) -> None:
    publication, _ = _running(db_engine, w)
    _refused(
        db_engine,
        _update_publication(publication, **{column: _ADMISSION_CHANGES[column]}),
        sqlstate=RESTRICT_VIOLATION,
        names="schedule publication admission columns are immutable",
    )


def test_pinned_document_is_set_once(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
        _process(c, publication, pin=None)
    _accepted(
        db_engine, _update_publication(publication, document_sha256=DOC, document_size_bytes=100)
    )
    _accepted(db_engine, _update_publication(publication, updated_at=text("now()")))
    for change in (
        {"document_sha256": OTHER_DOC},
        {"document_size_bytes": 101},
        {"document_sha256": None, "document_size_bytes": None},
    ):
        _refused(
            db_engine,
            _update_publication(publication, **change),
            sqlstate=RESTRICT_VIOLATION,
            names="a pinned schedule document is set once",
        )


def test_processing_starts_without_a_document_and_once(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
    _refused(
        db_engine,
        _update_publication(
            publication,
            status="processing",
            processing_started_at=text("now()"),
            document_sha256=DOC,
            document_size_bytes=100,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication starts processing before its document",
    )
    processing, _ = _running(db_engine, w, 2)
    _refused(
        db_engine,
        _update_publication(processing, processing_started_at=text("now() + interval '1 hour'")),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication starts processing once",
    )


def test_supersession_needs_a_different_source_version(db_engine: Engine, w: World) -> None:
    first, _, _ = _complete(db_engine, w, 1)
    with db_engine.begin() as c:
        _series(c, w, 1)
    # The same version in the same Series would also meet U2; a second Series
    # carries the predecessor's version only through this trigger's check.

    def same_version(c: Connection) -> None:
        c.execute(
            insert(schedule_publications).values(
                **_publication_values(
                    publication_id=w.publication(2),
                    project_id=w.project,
                    series_id=w.series(1),
                    enrollment_id=w.enrollment,
                    source_object_id=w.source_object,
                    source_version_id=w.version,
                    idempotency_key="supersede-key-01",
                    supersedes_publication_id=first,
                )
            )
        )

    _refused(
        db_engine,
        same_version,
        sqlstate=RESTRICT_VIOLATION,
        names="a superseding schedule publication names another source version",
    )
    _accepted(
        db_engine, lambda c: _admit(c, w, 3, series=1, version=w.second_version, supersedes=first)
    )


def test_no_terminal_transition_while_a_run_is_running(db_engine: Engine, w: World) -> None:
    publication, run, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        _link(c, row)
        _run(c, publication, "sprun_cpmgrun002", attempt=2)
    _refused(
        db_engine,
        lambda c: _finalize(c, publication, run),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication ends with no parser run running",
    )
    with db_engine.begin() as c:
        _issue(c, publication, None, 1, ScheduleIssueCode.SOURCE_VERSION_CHANGED)
    _refused(
        db_engine,
        lambda c: _fail(c, publication),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication ends with no parser run running",
    )
    with db_engine.begin() as c:
        _fail_run(c, "sprun_cpmgrun002")
    _accepted(db_engine, lambda c: _finalize(c, publication, run))


def test_accepted_run_is_a_parsed_run_of_the_pinned_document(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _row(c, publication, run, 1)
        _fail_run(c, run)
    _refused(
        db_engine,
        lambda c: _finalize(
            c,
            publication,
            run,
            status="complete",
            page_count=1,
            row_count=1,
            activity_count=1,
            ambiguous_row_count=0,
            issue_count=0,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule publication accepts a parsed run of its document",
    )


def test_accepted_counts_equal_the_stored_run(db_engine: Engine, w: World) -> None:
    publication, run, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        _link(c, row)
    for change in (
        {"page_count": 2},
        {"row_count": 2},
        {"activity_count": 0},
        {"ambiguous_row_count": 1},
        {"issue_count": 1},
    ):
        _refused(
            db_engine,
            lambda c, change=change: _finalize(c, publication, run, **change),
            sqlstate=RESTRICT_VIOLATION,
            names="a schedule publication counts its accepted run",
        )
    _accepted(db_engine, lambda c: _finalize(c, publication, run))


def test_terminal_status_must_equal_the_derived_outcome(db_engine: Engine, w: World) -> None:
    """R6-F01: the status is the issue-derived outcome, never the caller's choice."""
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
        _issue(c, publication, run, 1, ScheduleIssueCode.INVALID_DATE)
        _parse(c, run)
        _link(c, row)
    for status in ("complete", "review_required"):
        _refused(
            db_engine,
            lambda c, status=status: _finalize(c, publication, run, status=status),
            sqlstate=RESTRICT_VIOLATION,
            names="a schedule publication status is its derived outcome",
        )
    _accepted(db_engine, lambda c: _finalize(c, publication, run, status="partial"))


def test_complete_requires_every_id_row_linked(db_engine: Engine, w: World) -> None:
    publication, run, _ = _parsed(db_engine, w)
    _refused(
        db_engine,
        lambda c: _finalize(c, publication, run),
        sqlstate=RESTRICT_VIOLATION,
        names="a complete or partial schedule publication links every activity",
    )


def test_review_required_rejects_any_link(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
        _row(c, publication, run, 2, row_type="ambiguous")
        _parse(c, run)
        _link(c, row)
    _refused(
        db_engine,
        lambda c: _finalize(c, publication, run),
        sqlstate=RESTRICT_VIOLATION,
        names="a review-required schedule publication links nothing",
    )


def test_failed_publication_counts_its_issues(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _issue(c, publication, run, 1, ScheduleIssueCode.CORRUPT_PDF)
        _issue(c, publication, None, 2, ScheduleIssueCode.SOURCE_VERSION_CHANGED)
        _fail_run(c, run, "corrupt_pdf")
    _refused(
        db_engine,
        lambda c: _fail(c, publication, issue_count=1),
        sqlstate=RESTRICT_VIOLATION,
        names="a failed schedule publication counts its issues",
    )
    _accepted(db_engine, lambda c: _fail(c, publication))


def test_failed_publication_needs_an_error_issue(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _issue(c, publication, run, 1, ScheduleIssueCode.HEADER_OD_OCCLUDED)
        _fail_run(c, run)
    _refused(
        db_engine,
        lambda c: _fail(c, publication),
        sqlstate=RESTRICT_VIOLATION,
        names="a failed schedule publication has an error issue",
    )


# ---- F4: every publication has its job, at commit ------------------------------------


def test_publication_without_job_fails_at_commit(db_engine: Engine, w: World) -> None:
    def write(c: Connection) -> None:
        _series(c, w)
        c.execute(
            insert(schedule_publications).values(
                **_publication_values(
                    publication_id=w.publication(1),
                    project_id=w.project,
                    series_id=w.series(1),
                    enrollment_id=w.enrollment,
                    source_object_id=w.source_object,
                    source_version_id=w.version,
                )
            )
        )

    _refused(db_engine, write, sqlstate=CHECK_VIOLATION, names="a schedule publication has its job")
    _accepted(db_engine, lambda c: _admit(c, w, 1))


# ---- F5: the job keeps its identity --------------------------------------------------


def test_job_is_inserted_queued_and_unleased(db_engine: Engine, w: World) -> None:
    for n, change in enumerate(
        (
            {"state": "running", "lease_owner": "w", "lease_expires_at": text("now()")},
            {"attempt_count": 1},
        )
    ):

        def write(c: Connection, n: int = n, change: dict[str, object] = change) -> None:
            _series(c, w)
            c.execute(
                insert(schedule_publications).values(
                    **_publication_values(
                        publication_id=w.publication(n + 1),
                        project_id=w.project,
                        series_id=w.series(1),
                        enrollment_id=w.enrollment,
                        source_object_id=w.source_object,
                        source_version_id=w.version if n == 0 else w.second_version,
                        idempotency_key=f"job-key-{n:04d}",
                    )
                )
            )
            c.execute(
                insert(schedule_jobs).values(
                    operation_id=w.job(n + 1),
                    publication_id=w.publication(n + 1),
                    principal_id=P,
                    **change,
                )
            )

        _refused(
            db_engine,
            write,
            sqlstate=RESTRICT_VIOLATION,
            names="a schedule job is inserted queued and unleased",
        )


def test_job_is_never_deleted(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
    _refused(
        db_engine,
        _sql("DELETE FROM knowledge.schedule_jobs WHERE publication_id = :p", p=publication),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule job is never deleted",
    )


_JOB_IDENTITY: Final[dict[str, object]] = {
    "operation_id": "op_cpmgchanged",
    "publication_id": "spub_cpmgap0002",
    "principal_id": Q,
    "max_attempts": 5,
    "created_at": text("now() - interval '1 day'"),
}


@pytest.mark.parametrize("column", sorted(_JOB_IDENTITY))
def test_job_identity_column_is_immutable(db_engine: Engine, w: World, column: str) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
        _admit(c, w, 2, version=w.second_version)
    _refused(
        db_engine,
        lambda c: c.execute(
            schedule_jobs.update()
            .where(schedule_jobs.c.publication_id == publication)
            .values(**{column: _JOB_IDENTITY[column]})
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule job keeps its identity",
    )


def test_job_lease_columns_move_and_terminal_job_is_immutable(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
    lease = (
        "UPDATE knowledge.schedule_jobs SET state = 'running', lease_owner = 'worker', "
        "lease_expires_at = now() + interval '1 minute', attempt_count = attempt_count + 1, "
        "updated_at = now() WHERE publication_id = :p"
    )
    _accepted(db_engine, _sql(lease, p=publication))
    _accepted(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_jobs SET lease_expires_at = now() - interval '1 second' "
            "WHERE publication_id = :p",
            p=publication,
        ),
    )
    _accepted(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_jobs SET state = 'succeeded', lease_owner = NULL, "
            "lease_expires_at = NULL, updated_at = now() WHERE publication_id = :p",
            p=publication,
        ),
    )


def test_terminal_job_is_immutable(db_engine: Engine, w: World) -> None:
    with db_engine.begin() as c:
        succeeded = _admit(c, w, 1)
        failed = _admit(c, w, 2, version=w.second_version)
        c.execute(
            text(
                "UPDATE knowledge.schedule_jobs SET state = 'succeeded' WHERE publication_id = :p"
            ),
            {"p": succeeded},
        )
        c.execute(
            text(
                "UPDATE knowledge.schedule_jobs SET state = 'failed', dead_lettered_at = now(), "
                "last_error_code = 'unavailable' WHERE publication_id = :p"
            ),
            {"p": failed},
        )
    for publication in (succeeded, failed):
        for change in (
            "state = 'queued', dead_lettered_at = NULL",
            "updated_at = now()",
            "next_attempt_at = now()",
        ):
            _refused(
                db_engine,
                _sql(
                    f"UPDATE knowledge.schedule_jobs SET {change} WHERE publication_id = :p",  # noqa: S608
                    p=publication,
                ),
                sqlstate=RESTRICT_VIOLATION,
                names="a terminal schedule job is immutable",
            )


# ---- F6: the parser run lifecycle -------------------------------------------------------


def test_parser_run_is_never_deleted_and_starts_running(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    _refused(
        db_engine,
        _sql("DELETE FROM knowledge.schedule_parser_runs WHERE parser_run_id = :r", r=run),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule parser run is never deleted",
    )

    def parsed_at_insert(c: Connection) -> None:
        pub = _publication_row(c, publication)
        c.execute(
            insert(schedule_parser_runs).values(
                parser_run_id="sprun_cpmgrun009",
                principal_id=P,
                project_id=pub["project_id"],
                series_id=pub["series_id"],
                publication_id=publication,
                operation_id=_job_of(c, publication),
                attempt_number=9,
                parser_name="p",
                parser_version="1",
                profile_id="x",
                profile_version=1,
                pypdfium2_version="1",
                pdfium_version="1",
                document_sha256=DOC,
                status="failed",
                completed_at=text("now()"),
            )
        )

    _refused(
        db_engine,
        parsed_at_insert,
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule parser run starts running",
    )


@pytest.mark.parametrize("case", ["not_processing", "other_document"])
def test_parser_run_starts_only_on_a_pinned_processing_publication(
    db_engine: Engine, w: World, case: str
) -> None:
    with db_engine.begin() as c:
        publication = _admit(c, w, 1)
        if case == "other_document":
            _process(c, publication)
    doc = DOC if case == "not_processing" else OTHER_DOC
    names = (
        "a schedule parser run starts on a processing publication"
        if case == "not_processing"
        else "a schedule parser run parses the pinned document"
    )

    def write(c: Connection) -> None:
        _run(c, publication, "sprun_cpmgrun001", doc=doc)

    _refused(db_engine, write, sqlstate=RESTRICT_VIOLATION, names=names)


def test_terminal_parser_run_is_immutable(db_engine: Engine, w: World) -> None:
    publication, run, _ = _parsed(db_engine, w)
    with db_engine.begin() as c:
        failed = _run(c, publication, "sprun_cpmgrun002", attempt=2)
        _fail_run(c, failed)
    for target, change in (
        (
            run,
            "status = 'failed', completed_at = now(), page_count = NULL, row_count = NULL, "
            "issue_count = NULL, warning_count = NULL, parse_result_sha256 = NULL",
        ),
        (run, "completed_at = now()"),
        (failed, "failure_code = 'corrupt_pdf'"),
    ):
        _refused(
            db_engine,
            _sql(
                f"UPDATE knowledge.schedule_parser_runs SET {change} WHERE parser_run_id = :r",  # noqa: S608
                r=target,
            ),
            sqlstate=RESTRICT_VIOLATION,
            names="a finished schedule parser run is immutable",
        )


def test_parser_run_finishes_once(db_engine: Engine, w: World) -> None:
    _, run = _running(db_engine, w)
    _refused(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_parser_runs SET status = 'running' WHERE parser_run_id = :r",
            r=run,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule parser run finishes once",
    )


def test_parser_run_cannot_change_under_a_terminal_publication(db_engine: Engine, w: World) -> None:
    """R6-F03: a run still `running` (forced in by replica) cannot finish once terminal."""
    publication, _, _ = _complete(db_engine, w)
    with db_engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _run(c, publication, "sprun_cpmgrun002", attempt=2)
    _refused(
        db_engine,
        lambda c: _fail_run(c, "sprun_cpmgrun002"),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule parser run changes only under a processing publication",
    )


_RUN_IDENTITY: Final[dict[str, object]] = {
    "attempt_number": 7,
    "parser_name": "other-parser",
    "parser_version": "2",
    "profile_id": "other",
    "profile_version": 2,
    "pypdfium2_version": "9",
    "pdfium_version": "9",
    "document_sha256": OTHER_DOC,
    "started_at": text("now() - interval '1 day'"),
}


@pytest.mark.parametrize("column", sorted(_RUN_IDENTITY))
def test_parser_run_identity_is_immutable(db_engine: Engine, w: World, column: str) -> None:
    _, run = _running(db_engine, w)
    _refused(
        db_engine,
        lambda c: c.execute(
            schedule_parser_runs.update()
            .where(schedule_parser_runs.c.parser_run_id == run)
            .values(status="failed", completed_at=text("now()"), **{column: _RUN_IDENTITY[column]})
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule parser run keeps its identity",
    )


def test_parsed_run_counts_match_rows(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _row(c, publication, run, 1)
    _refused(
        db_engine,
        lambda c: _parse(c, run, row_count=2),
        sqlstate=RESTRICT_VIOLATION,
        names="a parsed schedule run counts its rows",
    )


@pytest.mark.parametrize("count", ["issue_count", "warning_count"])
def test_parsed_run_counts_match_issues(db_engine: Engine, w: World, count: str) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _row(c, publication, run, 1)
        _issue(c, publication, run, 1, ScheduleIssueCode.HEADER_OD_OCCLUDED)
        _issue(c, publication, run, 2, ScheduleIssueCode.INVALID_DATE)
    wrong = {"issue_count": 3} if count == "issue_count" else {"warning_count": 2}
    _refused(
        db_engine,
        lambda c: _parse(c, run, **wrong),
        sqlstate=RESTRICT_VIOLATION,
        names=f"a parsed schedule run counts its {count.removesuffix('_count')}s",
    )


def test_parsed_run_refuses_a_failed_ladder_code(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _issue(c, publication, run, 1, ScheduleIssueCode.CORRUPT_PDF)
    _refused(
        db_engine,
        lambda c: _parse(c, run),
        sqlstate=RESTRICT_VIOLATION,
        names="a parsed schedule run carries no failed-ladder code",
    )


# ---- F7: rows change only by linking -----------------------------------------------------


def test_row_is_inserted_unlinked(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        _series(c, w)
        c.execute(
            insert(schedule_activities).values(
                schedule_activity_id="sact_cpmgrow001",
                principal_id=P,
                project_id=w.project,
                series_id=w.series(1),
                published_activity_id="A-0001",
            )
        )
    _refused(
        db_engine,
        lambda c: _row(c, publication, run, 1, schedule_activity_id="sact_cpmgrow001"),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is inserted unlinked",
    )


def test_row_is_stored_only_by_a_running_run_of_a_processing_publication(
    db_engine: Engine, w: World
) -> None:
    publication, run, _ = _parsed(db_engine, w)
    _refused(
        db_engine,
        lambda c: _row(c, publication, run, 2),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is stored by a running parser run",
    )
    with db_engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE knowledge.schedule_parser_runs SET status = 'running', completed_at = "
                "NULL, page_count = NULL, row_count = NULL, issue_count = NULL, warning_count = "
                "NULL, parse_result_sha256 = NULL WHERE parser_run_id = :r"
            ),
            {"r": run},
        )
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET status = 'queued', "
                "processing_started_at = NULL, document_sha256 = NULL, document_size_bytes = NULL "
                "WHERE publication_id = :p"
            ),
            {"p": publication},
        )
    _refused(
        db_engine,
        lambda c: _row(c, publication, run, 2),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is stored while its publication processes",
    )


def test_parent_row_precedes_its_child(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        first = _row(c, publication, run, 1, row_type="wbs_summary")
        _row(c, publication, run, 3, row_type="wbs_summary")
    later = f"srow_{run.removeprefix('sprun_')}o0003"
    _refused(
        db_engine,
        lambda c: _row(c, publication, run, 2, parent=later),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row parent precedes its child",
    )
    _accepted(db_engine, lambda c: _row(c, publication, run, 2, parent=first))


def test_row_is_never_deleted(db_engine: Engine, w: World) -> None:
    _, _, row = _parsed(db_engine, w)
    _refused(
        db_engine,
        _sql("DELETE FROM knowledge.schedule_rows WHERE row_id = :r", r=row),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is never deleted",
    )


_ROW_CONTENT: Final[dict[str, object]] = {
    "activity_name": "Changed",
    "row_ordinal": 9,
    "od_value": Decimal("11.000"),
    "finish_marker": None,
    "cell_evidence": {**CELLS, "changed": True},
    "warning_codes": ["invalid_date"],
    "created_at": text("now() - interval '1 day'"),
    "hierarchy_path": ["Other"],
}


@pytest.mark.parametrize("column", sorted(_ROW_CONTENT))
def test_row_content_is_immutable(db_engine: Engine, w: World, column: str) -> None:
    _, _, row = _parsed(db_engine, w)
    _refused(
        db_engine,
        lambda c: c.execute(
            schedule_rows.update()
            .where(schedule_rows.c.row_id == row)
            .values(**{column: _ROW_CONTENT[column]})
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="schedule row content is immutable",
    )


def test_row_link_is_set_once(db_engine: Engine, w: World) -> None:
    _, _, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        _link(c, row)
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_activities (schedule_activity_id, principal_id, "
                "project_id, series_id, published_activity_id) SELECT 'sact_cpmgother1', "
                "principal_id, project_id, series_id, published_activity_id || '-X' FROM "
                "knowledge.schedule_activities WHERE schedule_activity_id = :a"
            ),
            {"a": f"sact_{row.removeprefix('srow_')}"},
        )
    _refused(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = 'sact_cpmgother1' "
            "WHERE row_id = :r",
            r=row,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row link is set once",
    )


def test_row_link_cannot_be_cleared(db_engine: Engine, w: World) -> None:
    _, _, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        _link(c, row)
    _refused(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = NULL WHERE row_id = :r",
            r=row,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row link is never cleared",
    )


def test_row_link_cannot_be_reset(db_engine: Engine, w: World) -> None:
    _, _, row = _parsed(db_engine, w)
    with db_engine.begin() as c:
        activity = _link(c, row)
    _refused(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = :a WHERE row_id = :r",
            a=activity,
            r=row,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row link is never reset",
    )


def test_unlinked_row_cannot_be_rewritten_unlinked(db_engine: Engine, w: World) -> None:
    _, _, row = _parsed(db_engine, w)
    _refused(
        db_engine,
        _sql(
            "UPDATE knowledge.schedule_rows SET schedule_activity_id = NULL WHERE row_id = :r",
            r=row,
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row link is set once",
    )


def test_row_link_requires_a_parsed_run(db_engine: Engine, w: World) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
    _refused(
        db_engine,
        lambda c: _link(c, row),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is linked after its run is parsed",
    )


def test_row_link_requires_parsed_run_and_processing_publication(
    db_engine: Engine, w: World
) -> None:
    """No link once the publication is terminal (`review_required` here)."""
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
        _row(c, publication, run, 2, row_type="ambiguous")
        _parse(c, run)
        _finalize(c, publication, run)
    assert _status(db_engine, publication) == "review_required"
    _refused(
        db_engine,
        lambda c: _link(c, row),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule row is linked while its publication processes",
    )


def _status(engine: Engine, publication: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text(
                    "SELECT status FROM knowledge.schedule_publications WHERE publication_id = :p"
                ),
                {"p": publication},
            ).scalar_one()
        )


# ---- F8: issues only while processing --------------------------------------------------


def test_issue_is_refused_after_terminal(db_engine: Engine, w: World) -> None:
    publication, _, _ = _complete(db_engine, w)
    _refused(
        db_engine,
        lambda c: _issue(c, publication, None, 9, ScheduleIssueCode.SOURCE_VERSION_CHANGED),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule issue is recorded while its publication processes",
    )
    with db_engine.begin() as c:
        queued = _admit(c, w, 2, version=w.second_version)
    _refused(
        db_engine,
        lambda c: _issue(c, queued, None, 1, ScheduleIssueCode.SOURCE_VERSION_CHANGED),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule issue is recorded while its publication processes",
    )


def test_run_issue_requires_a_running_run(db_engine: Engine, w: World) -> None:
    publication, run, _ = _parsed(db_engine, w)
    _refused(
        db_engine,
        lambda c: _issue(c, publication, run, 1, ScheduleIssueCode.INVALID_DATE),
        sqlstate=RESTRICT_VIOLATION,
        names="a schedule run issue is recorded while its run is running",
    )
    _accepted(
        db_engine,
        lambda c: _issue(c, publication, None, 2, ScheduleIssueCode.SOURCE_VERSION_CHANGED),
    )


# ---- F1/F2: append-only and TRUNCATE ---------------------------------------------------


_APPEND_ONLY: Final = ("schedule_series", "schedule_activities", "schedule_import_issues")


@pytest.mark.parametrize("table", _APPEND_ONLY)
def test_is_append_only(db_engine: Engine, w: World, table: str) -> None:
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
        _issue(c, publication, run, 1, ScheduleIssueCode.INVALID_DATE)
        _parse(c, run)
        _link(c, row)
    for statement in (
        f"UPDATE knowledge.{table} SET created_at = created_at",  # noqa: S608
        f"DELETE FROM knowledge.{table}",  # noqa: S608
    ):
        _refused(
            db_engine,
            _sql(statement),
            sqlstate=RESTRICT_VIOLATION,
            names=f"{table} is append-only",
        )


@pytest.mark.parametrize("table", CPM_TABLES)
def test_refuses_truncate_when_it_holds_rows(db_engine: Engine, w: World, table: str) -> None:
    """Only `table`'s own refusal is live, so the refusal is that trigger's alone."""
    # An empty CPM table lets a fixture's cascading TRUNCATE through.
    _accepted(db_engine, _sql(f"TRUNCATE knowledge.{table} CASCADE"))
    publication, run = _running(db_engine, w)
    with db_engine.begin() as c:
        row = _row(c, publication, run, 1)
        _issue(c, publication, run, 1, ScheduleIssueCode.INVALID_DATE)
        _parse(c, run)
        _link(c, row)

    def truncate(c: Connection) -> None:
        for other_table in CPM_TABLES:
            if other_table != table:
                c.execute(
                    text(
                        f"ALTER TABLE knowledge.{other_table} DISABLE TRIGGER "
                        f"{other_table}_refuse_truncate"
                    )
                )
        c.execute(text(f"TRUNCATE knowledge.{table} CASCADE"))

    _refused(db_engine, truncate, sqlstate=RESTRICT_VIOLATION, names=f"{table} refuses TRUNCATE")


# ---- F9: the frozen outcome ladder equals S5a `derive_outcome` --------------------------


def _domain_row(row_type: ScheduleRowType) -> ParsedScheduleRow:
    blank = ScheduleCellState.PUBLISHED_BLANK
    cells = tuple(
        ScheduleCellEvidence(field, blank, None, ()) for field in schedule_model.ROW_CELL_FIELDS
    )
    identity: dict[str, str | None] = {"published_activity_id": "A-1", "activity_name": "N"}
    if row_type is ScheduleRowType.AMBIGUOUS:
        identity = {"published_activity_id": None, "activity_name": None}
    return ParsedScheduleRow(
        row_ordinal=1,
        page_number=1,
        physical_line_ordinal=1,
        row_type=row_type,
        indent_level=None,
        parent_row_ordinal=None,
        hierarchy_path=None,
        original_duration=ScheduleDurationCell(blank, None),
        remaining_duration=ScheduleDurationCell(blank, None),
        start=ScheduleDateCell(blank, None, None),
        finish=ScheduleDateCell(blank, None, None),
        box=ScheduleBox(0, 0, 1, 1),
        page_width_mpt=10,
        page_height_mpt=10,
        cells=cells,
        warning_codes=(),
        **identity,
    )


_LADDER_CASES: Final = (*(code.value for code in ScheduleIssueCode), "ambiguous_row", "no_issue")


@pytest.mark.parametrize("case", _LADDER_CASES)
def test_sql_outcome_ladder_equals_derive_outcome(db_engine: Engine, w: World, case: str) -> None:
    publication, run = _running(db_engine, w)
    rows = [_domain_row(ScheduleRowType.ACTIVITY)]
    issues: list[ScheduleParseIssue] = []
    with db_engine.begin() as c:
        if case == "ambiguous_row":
            _row(c, publication, run, 1, row_type="ambiguous")
            rows = [_domain_row(ScheduleRowType.AMBIGUOUS)]
        else:
            _row(c, publication, run, 1)
        if case not in ("ambiguous_row", "no_issue"):
            code = ScheduleIssueCode(case)
            _issue(c, publication, run, 1, code)
            issues = [ScheduleParseIssue(code, ISSUE_SEVERITY[code], 1, None, None)]
        stored = c.execute(
            text("SELECT knowledge.schedule_run_outcome(:r)"), {"r": run}
        ).scalar_one()
    if case == ScheduleIssueCode.SOURCE_VERSION_CHANGED.value:
        # Never a run issue (S5a raises); the frozen ladder gives it no rung.
        with pytest.raises(ValueError, match="not a parser issue"):
            derive_outcome(issues, rows)
        assert stored == "complete"
        return
    assert stored == derive_outcome(issues, rows).value, case


# ---- the record field-code vocabulary the tables hold ------------------------------


def test_issue_field_vocabulary_is_the_field_codes(db_engine: Engine) -> None:
    for n, field in enumerate(ScheduleFieldCode):
        _accepted(
            db_engine,
            _insert(
                schedule_import_issues,
                _issue_values(issue_id=f"siss_cpmgfield{n:02d}", field=field.value),
            ),
            replica=True,
        )
    _refused(
        db_engine,
        _insert(schedule_import_issues, _issue_values(issue_id="siss_cpmgfield99", field="nope")),
        sqlstate=CHECK_VIOLATION,
        names="a_schedule_issue_field_is_known",
        replica=True,
    )
