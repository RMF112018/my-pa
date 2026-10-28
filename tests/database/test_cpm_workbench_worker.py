"""The S5b-2 schedule import handler against a synthetic head database.

Worker contract (`docs/architecture/cpm-workbench-worker-capabilities-contract.md`)
sections 3.3 and 3.4, R2 sections 9.4, 10.6, 22, 24 and 25. Every test admits a
synthetic publication through the S5b-1 repository, claims its `schedule_jobs`
row with a real lease, and drives `process_schedule_publication` -- directly, or
under `run_worker(..., plane=SCHEDULE_JOBS)` with no heartbeat. Bytes come from
a fake `SourceProvider` behind the handler's `_provider_for` seam; the parse runs
in the real contained child unless a test replaces `run_isolated_parse` to
force an outcome. A lease is expired by moving `lease_expires_at` into the past.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import ScheduleRepository
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ScheduleAdmission,
    ScheduleImportRequest,
    ScheduleIssueCode,
    ScheduleLease,
    ScheduleParseIssue,
    ScheduleParseResult,
    ScheduleParserIdentity,
    ScheduleParserRunStatus,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    normalize_series_name,
    parse_result_sha256,
    schedule_import_request_digest,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    ProviderError,
    SourceObject,
    SourceObjectContent,
    SourceProvider,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.infrastructure.jobs import schedule as handler_module
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.jobs.schedule_parser_process import (
    DeterministicFailure,
    IsolatedParse,
    ParsedResult,
    TransientFailure,
)
from my_pa.infrastructure.jobs.worker import (
    JobExecutionError,
    LeaseLostError,
    WorkerRun,
    run_worker,
)
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, LeasedJob, claim_job, job_for
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.tables import JobState
from my_pa.infrastructure.schedule import parse_full_schedule
from tests.fixtures import schedule_full_pdf as gen

pytestmark = pytest.mark.database

P: Final = "prn_cpmwork0001"
Q: Final = "prn_cpmwork0002"
OWNER: Final = "cpm-worker-a"
LEASE_SECONDS: Final = 300
SIXTEEN_MIB: Final = 16_777_216
CPM_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)


# ---- the world ------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    principal: str
    source: str
    project: str
    enrollment: str
    source_object: str
    version: str


def _world(engine: Engine, principal: str, tag: str) -> World:
    world = World(
        principal=principal,
        source=f"src_{tag}0001",
        project=f"prj_{tag}0001",
        enrollment=f"enr_{tag}0001",
        source_object=f"obj_{tag}0001",
        version=f"ver_{tag}0001",
    )
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.sources (source_id, provider_kind, label, classification, "
                "native_root) VALUES (:s, 'fixture', 'Synthetic', 'synthetic_test', :root)"
            ),
            {"s": world.source, "root": f"/synthetic/cpm/{tag}"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_objects (source_object_id, source_id, kind, "
                "native_locator) VALUES (:o, :s, 'file', :locator)"
            ),
            {"o": world.source_object, "s": world.source, "locator": f"/synthetic/{tag}.pdf"},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                "fingerprint, media_type, size_bytes, modified_at) VALUES (:v, :o, :v, "
                "'application/pdf', NULL, now())"
            ),
            {"v": world.version, "o": world.source_object},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                "depth, media_types, max_items, max_bytes) VALUES (:e, :s, :p, "
                "'schedule_import', 'policy-v1', :key, 'synthetic', ARRAY[:o], 0, "
                "ARRAY['application/pdf'], 10, :max)"
            ),
            {
                "e": world.enrollment,
                "s": world.source,
                "p": principal,
                "key": f"{tag}-pdf",
                "o": world.source_object,
                "max": SIXTEEN_MIB,
            },
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                "VALUES (:e, :o)"
            ),
            {"e": world.enrollment, "o": world.source_object},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                "now())"
            ),
            {"j": world.project, "p": principal},
        )
    return world


@pytest.fixture
def w(db_engine: Engine) -> World:
    return _world(db_engine, P, "cpmwa")


def _admit(engine: Engine, w: World, *, expected: date | None = None) -> ScheduleAdmission:
    request = ScheduleImportRequest(
        project_id=w.project,
        series_id=None,
        series_name=normalize_series_name("Master Schedule"),
        enrollment_id=w.enrollment,
        source_object_id=w.source_object,
        source_version_id=w.version,
        publication_role=SchedulePublicationRole.UPDATE,
        baseline_kind=None,
        expected_data_date=expected,
        supersedes_publication_id=None,
        idempotency_key="cpm-work-0001",
    )
    with SqlAlchemyScheduleUnitOfWork(engine) as uow:
        return uow.schedules.admit_publication(
            w.principal, request, schedule_import_request_digest(w.principal, request)
        )


def _claim(engine: Engine, principal: str = P) -> LeasedJob:
    with engine.begin() as c:
        job = claim_job(
            c,
            owner=OWNER,
            lease_seconds=LEASE_SECONDS,
            principal_id=principal,
            plane=SCHEDULE_JOBS,
        )
    assert job is not None
    return job


def _expire(engine: Engine, operation_id: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE operation_id = :o"
            ),
            {"o": operation_id},
        )


def _read[T](engine: Engine, work: Callable[[ScheduleRepository], T]) -> T:
    with SqlAlchemyScheduleUnitOfWork(engine) as uow:
        return work(uow.schedules)


def _job_state(engine: Engine, operation_id: str) -> JobState:
    with engine.connect() as c:
        record = job_for(c, operation_id, principal_id=P, plane=SCHEDULE_JOBS)
    assert record is not None
    return record.state


def _issues(engine: Engine, publication_id: str) -> list[tuple[str, str | None]]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT code, parser_run_id FROM knowledge.schedule_import_issues "
                "WHERE publication_id = :p ORDER BY code, parser_run_id"
            ),
            {"p": publication_id},
        ).all()
    return [(str(code), run) for code, run in rows]


def _snapshot(engine: Engine) -> dict[str, Any]:
    """Every CPM row this database holds, as comparable text."""
    found: dict[str, Any] = {}
    with engine.connect() as c:
        for table in CPM_TABLES:
            rows = c.execute(text(f"SELECT * FROM knowledge.{table}")).all()  # noqa: S608
            found[table] = sorted(repr(tuple(row)) for row in rows)
    # The lease columns move with every claim and expiry; the job's state and
    # attempt are what a write would change.
    with engine.connect() as c:
        found["schedule_jobs"] = [
            repr(tuple(row))
            for row in c.execute(
                text(
                    "SELECT operation_id, state, attempt_count, last_error_code "
                    "FROM knowledge.schedule_jobs ORDER BY operation_id"
                )
            ).all()
        ]
    return found


# ---- the fake provider and seams --------------------------------------------------------


class FakeProvider(SourceProvider):
    """Serves one synthetic object; every deviation is a constructor argument."""

    def __init__(
        self,
        w: World,
        data: bytes,
        *,
        media_type: str | None = "application/pdf",
        size: int | None = None,
        metadata_version: str | None = None,
        fetch_version: str | None = None,
        truncated: bool = False,
        metadata_error: Exception | None = None,
        fetch_error: Exception | None = None,
        overrun: bool = False,
        on_fetch: Callable[[], None] | None = None,
    ) -> None:
        self._w = w
        self._data = data
        self._media_type = media_type
        self._size = len(data) if size is None else size
        self._metadata_version = metadata_version or w.version
        self._fetch_version = fetch_version or w.version
        self._truncated = truncated
        self._metadata_error = metadata_error
        self._fetch_error = fetch_error
        self._overrun = overrun
        self._on_fetch = on_fetch
        self.fetched_max_bytes: int | None = None

    @property
    def source_id(self) -> str:
        return self._w.source

    def list_children(self, parent_object_id: str | None = None) -> Iterator[SourceObject]:
        del parent_object_id
        return iter(())

    def metadata(self, source_object_id: str) -> SourceObject:
        if self._metadata_error is not None:
            raise self._metadata_error
        return SourceObject(
            source_id=self._w.source,
            source_object_id=source_object_id,
            version_id=self._metadata_version,
            kind=ObjectKind.FILE,
            media_type=self._media_type,
            size_bytes=self._size,
            modified_at=datetime(2026, 5, 4, tzinfo=UTC),
        )

    def fetch(self, source_object_id: str, *, max_bytes: int) -> SourceObjectContent:
        self.fetched_max_bytes = max_bytes
        if self._on_fetch is not None:
            self._on_fetch()
        if self._fetch_error is not None:
            raise self._fetch_error
        if self._overrun:
            # A misbehaving adapter: more than `max_bytes`, not reported truncated.
            content, truncated = self._data, self._truncated
        else:
            content = self._data[:max_bytes]
            truncated = self._truncated or len(self._data) > max_bytes
        return SourceObjectContent(
            source_object_id=source_object_id,
            version_id=self._fetch_version,
            media_type=self._media_type,
            content=content,
            is_truncated=truncated,
        )


def _serve(monkeypatch: pytest.MonkeyPatch, provider: SourceProvider | None) -> None:
    monkeypatch.setattr(handler_module, "_provider_for", lambda _connection, _source: provider)


def _no_parse(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Replace the child with a recorder that must not be reached."""
    calls: list[bytes] = []

    def refuse(data: bytes, **_kwargs: object) -> IsolatedParse:
        calls.append(data)
        raise AssertionError("the parse was spawned")

    monkeypatch.setattr(handler_module, "run_isolated_parse", refuse)
    return calls


def _parse_returns(monkeypatch: pytest.MonkeyPatch, outcome: IsolatedParse) -> None:
    monkeypatch.setattr(handler_module, "run_isolated_parse", lambda _data, **_kwargs: outcome)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _at_checkpoint(
    monkeypatch: pytest.MonkeyPatch, target: str, action: Callable[[], None]
) -> list[str]:
    """Run `action` the first time the handler reaches checkpoint `target`."""
    original = handler_module._checkpoint
    seen: list[str] = []

    def checkpoint(budget: handler_module.ScheduleBudget, label: str) -> bool:
        seen.append(label)
        if label == target and seen.count(label) == 1:
            action()
        return original(budget, label)

    monkeypatch.setattr(handler_module, "_checkpoint", checkpoint)
    return seen


def _small() -> gen.FixtureCase:
    return gen.build("full_valid_2p", "base")


def _run_worker(engine: Engine) -> WorkerRun:
    return run_worker(
        engine,
        owner=OWNER,
        handler=process_schedule_publication,
        stop=threading.Event(),
        principal_id=P,
        plane=SCHEDULE_JOBS,
        max_iterations=1,
        lease_seconds=LEASE_SECONDS,
    )


def _publication(engine: Engine, publication_id: str) -> Any:  # noqa: ANN401 - a test read
    found = _read(engine, lambda r: r.get_publication(P, publication_id))
    assert found is not None
    return found


# ---- end to end under run_worker ----------------------------------------------------------


def test_worker_imports_a_complete_publication_end_to_end(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _small()
    expected = parse_full_schedule(case.pdf)
    assert expected.outcome is SchedulePublicationStatus.COMPLETE
    admission = _admit(db_engine, w)
    provider = FakeProvider(w, case.pdf)
    _serve(monkeypatch, provider)
    outcome = _run_worker(db_engine)
    assert (outcome.claimed, outcome.completed, outcome.released, outcome.lost) == (1, 1, 0, 0)
    assert provider.fetched_max_bytes == SIXTEEN_MIB
    publication = _publication(db_engine, admission.publication.publication_id)
    assert publication.status is SchedulePublicationStatus.COMPLETE
    assert publication.document_sha256 == hashlib.sha256(case.pdf).hexdigest()
    assert publication.row_count == len(expected.rows)
    assert publication.data_date == expected.data_date
    assert publication.published_schedule_title == expected.published_schedule_title
    (run,) = _read(db_engine, lambda r: r.get_parser_runs(P, publication.publication_id))
    assert run.status is ScheduleParserRunStatus.PARSED
    assert run.parse_result_sha256 == parse_result_sha256(expected)
    assert publication.accepted_parser_run_id == run.parser_run_id
    assert _job_state(db_engine, admission.operation_id) is JobState.SUCCEEDED
    with db_engine.connect() as c:
        unlinked = c.execute(
            text(
                "SELECT count(*) FROM knowledge.schedule_rows WHERE parser_run_id = :r AND "
                "row_type IN ('activity', 'milestone') AND schedule_activity_id IS NULL"
            ),
            {"r": run.parser_run_id},
        ).scalar_one()
    assert unlinked == 0


@pytest.mark.parametrize(
    ("family", "variant", "status"),
    [
        ("full_invalid_date", "base", SchedulePublicationStatus.PARTIAL),
        ("full_duplicate_activity_id", "base", SchedulePublicationStatus.REVIEW_REQUIRED),
    ],
)
def test_worker_imports_partial_and_review_required_outcomes(
    db_engine: Engine,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    variant: str,
    status: SchedulePublicationStatus,
) -> None:
    case = gen.build(family, variant)
    assert parse_full_schedule(case.pdf).outcome is status
    admission = _admit(db_engine, w)
    _serve(monkeypatch, FakeProvider(w, case.pdf))
    assert _run_worker(db_engine).completed == 1
    assert _publication(db_engine, admission.publication.publication_id).status is status


# ---- the provider read (R2 9.4) ------------------------------------------------------------


def _fails_run_less(engine: Engine, admission: ScheduleAdmission, code: ScheduleIssueCode) -> None:
    publication_id = admission.publication.publication_id
    assert _publication(engine, publication_id).status is SchedulePublicationStatus.FAILED
    assert _issues(engine, publication_id) == [(code.value, None)]


@pytest.mark.parametrize("how", ["raises", "differs"])
def test_version_change_at_metadata_fails_before_parsing(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    admission = _admit(db_engine, w)
    provider = (
        FakeProvider(w, _small().pdf, metadata_error=VersionChangedError("synthetic"))
        if how == "raises"
        else FakeProvider(w, _small().pdf, metadata_version="ver_cpmwa0099")
    )
    _serve(monkeypatch, provider)
    spawned = _no_parse(monkeypatch)
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert spawned == []
    assert provider.fetched_max_bytes is None
    _fails_run_less(db_engine, admission, ScheduleIssueCode.SOURCE_VERSION_CHANGED)
    assert (
        _read(db_engine, lambda r: r.get_parser_runs(P, admission.publication.publication_id)) == ()
    )


@pytest.mark.parametrize("how", ["raises", "differs"])
def test_version_change_at_fetch_fails_before_parsing(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    admission = _admit(db_engine, w)
    provider = (
        FakeProvider(w, _small().pdf, fetch_error=VersionChangedError("synthetic"))
        if how == "raises"
        else FakeProvider(w, _small().pdf, fetch_version="ver_cpmwa0099")
    )
    _serve(monkeypatch, provider)
    spawned = _no_parse(monkeypatch)
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert spawned == []
    _fails_run_less(db_engine, admission, ScheduleIssueCode.SOURCE_VERSION_CHANGED)
    publication = _publication(db_engine, admission.publication.publication_id)
    assert publication.document_sha256 is None


def test_truncated_fetch_is_source_too_large(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = _admit(db_engine, w)
    _serve(monkeypatch, FakeProvider(w, _small().pdf, size=None, truncated=True))
    spawned = _no_parse(monkeypatch)
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert spawned == []
    _fails_run_less(db_engine, admission, ScheduleIssueCode.SOURCE_TOO_LARGE)


@pytest.mark.parametrize(
    "how", ["no_provider", "adapter_refuses_root", "traversal_denied", "provider_error"]
)
def test_provider_unavailable_is_transient_and_exhausts_to_effective_failed(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    admission = _admit(db_engine, w)
    if how == "no_provider":
        _serve(monkeypatch, None)
    elif how == "adapter_refuses_root":

        def refuse(_connection: object, _source: str) -> SourceProvider:
            raise ValueError("root not there")

        monkeypatch.setattr(handler_module, "_provider_for", refuse)
    else:
        error = TraversalDeniedError("x") if how == "traversal_denied" else ProviderError("x")
        _serve(monkeypatch, FakeProvider(w, _small().pdf, metadata_error=error))
    spawned = _no_parse(monkeypatch)
    for attempt in range(1, 4):
        outcome = _run_worker(db_engine)
        assert (outcome.claimed, outcome.released, outcome.completed) == (1, 1, 0), attempt
    assert spawned == []
    publication_id = admission.publication.publication_id
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.PROCESSING
    assert _job_state(db_engine, admission.operation_id) is JobState.FAILED
    with db_engine.connect() as c:
        last = c.execute(
            text("SELECT last_error_code FROM knowledge.schedule_jobs WHERE operation_id = :o"),
            {"o": admission.operation_id},
        ).scalar_one()
    assert last == ErrorCode.UNAVAILABLE.value
    effective = _read(db_engine, lambda r: r.get_effective_status(P, publication_id))
    assert effective is SchedulePublicationStatus.FAILED
    assert _issues(db_engine, publication_id) == []


def test_provider_read_holds_no_transaction(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = _admit(db_engine, w)
    observed: list[tuple[int, bool]] = []

    def inspect() -> None:
        with db_engine.connect() as c:
            open_transactions = c.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                )
            ).scalar_one()
        with db_engine.begin() as c:
            c.execute(text("SET LOCAL lock_timeout = '1s'"))
            locked = c.execute(
                text(
                    "SELECT 1 FROM knowledge.schedule_jobs WHERE operation_id = :o "
                    "FOR UPDATE NOWAIT"
                ),
                {"o": admission.operation_id},
            ).scalar_one_or_none()
        observed.append((int(open_transactions), locked == 1))

    _serve(monkeypatch, FakeProvider(w, _small().pdf, on_fetch=inspect))
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert observed == [(0, True)]
    status = _publication(db_engine, admission.publication.publication_id).status
    assert status is SchedulePublicationStatus.COMPLETE


# ---- deterministic and transient classes (3.3.2) ------------------------------------------


def _long_id_result() -> ScheduleParseResult:
    """A valid parse whose first activity ID exceeds the 256-character persistence bound."""
    result = parse_full_schedule(_small().pdf)
    index = next(i for i, row in enumerate(result.rows) if row.published_activity_id is not None)
    rows = list(result.rows)
    rows[index] = replace(rows[index], published_activity_id="A" * 300)
    return replace(result, rows=tuple(rows))


def _prepin_other_document(engine: Engine, job: LeasedJob) -> None:
    lease = ScheduleLease(job.operation_id, OWNER, job.attempt)

    def prepin(r: ScheduleRepository) -> None:
        r.begin_processing(P, job.subject_id, lease)
        r.pin_document(P, job.subject_id, lease, "c" * 64, 10)

    _read(engine, prepin)


@dataclass(frozen=True)
class Deterministic:
    name: str
    code: ScheduleIssueCode
    run_scoped: bool
    provider: Callable[[World], SourceProvider] | None = None
    parse: Callable[[], IsolatedParse] | None = None
    prepin: bool = False
    budget_at: str | None = None


def _corrupt() -> bytes:
    pdf = gen.build("corrupt_pdf", "garbage").pdf
    return pdf if pdf.startswith(b"%PDF-") else b"%PDF-1.7\n" + pdf


DETERMINISTIC: Final = (
    Deterministic(
        "metadata_raises_version_changed",
        ScheduleIssueCode.SOURCE_VERSION_CHANGED,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, metadata_error=VersionChangedError("x")),
    ),
    Deterministic(
        "metadata_version_differs",
        ScheduleIssueCode.SOURCE_VERSION_CHANGED,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, metadata_version="ver_cpmwa0099"),
    ),
    Deterministic(
        "fetch_version_differs",
        ScheduleIssueCode.SOURCE_VERSION_CHANGED,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, fetch_version="ver_cpmwa0099"),
    ),
    Deterministic(
        "metadata_media_type_other",
        ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, media_type="text/plain"),
    ),
    Deterministic(
        "metadata_size_over_the_plan",
        ScheduleIssueCode.SOURCE_TOO_LARGE,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, size=SIXTEEN_MIB + 1),
    ),
    Deterministic(
        "fetch_truncated",
        ScheduleIssueCode.SOURCE_TOO_LARGE,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf, truncated=True),
    ),
    Deterministic(
        "fetch_over_sixteen_mib",
        ScheduleIssueCode.SOURCE_TOO_LARGE,
        False,
        provider=lambda w: FakeProvider(w, b"%PDF-" + bytes(SIXTEEN_MIB), size=1024, overrun=True),
    ),
    Deterministic(
        "bytes_not_pdf",
        ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        False,
        provider=lambda w: FakeProvider(w, b"GIF89a synthetic", media_type=None),
    ),
    Deterministic(
        "document_changed_on_retry",
        ScheduleIssueCode.SOURCE_VERSION_CHANGED,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf),
        prepin=True,
    ),
    Deterministic(
        "child_result_failed",
        ScheduleIssueCode.CORRUPT_PDF,
        True,
        provider=lambda w: FakeProvider(w, _corrupt()),
    ),
    Deterministic(
        "child_outcome_deterministic",
        ScheduleIssueCode.PARSER_EXCEPTION,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf),
        parse=lambda: DeterministicFailure(ScheduleIssueCode.PARSER_EXCEPTION),
    ),
    Deterministic(
        "row_bounds",
        ScheduleIssueCode.BOUNDS_EXCEEDED,
        True,
        provider=lambda w: FakeProvider(w, _small().pdf),
        parse=lambda: ParsedResult(_long_id_result()),
    ),
    Deterministic(
        "budget",
        ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED,
        False,
        provider=lambda w: FakeProvider(w, _small().pdf),
        budget_at="C1",
    ),
)


@pytest.mark.parametrize("row", DETERMINISTIC, ids=[row.name for row in DETERMINISTIC])
def test_deterministic_failure_completes_the_job_and_fails_the_publication(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, row: Deterministic
) -> None:
    admission = _admit(db_engine, w)
    assert row.provider is not None
    _serve(monkeypatch, row.provider(w))
    if row.parse is not None:
        _parse_returns(monkeypatch, row.parse())
    if row.budget_at is not None:
        clock = Clock()
        monkeypatch.setattr(handler_module, "_clock", clock)
        _at_checkpoint(monkeypatch, row.budget_at, lambda: setattr(clock, "now", 1e6))
    if row.prepin:
        job = _claim(db_engine)
        _prepin_other_document(db_engine, job)
        _expire(db_engine, job.operation_id)
    outcome = _run_worker(db_engine)
    assert (outcome.completed, outcome.released, outcome.lost) == (1, 0, 0)
    assert _job_state(db_engine, admission.operation_id) is JobState.SUCCEEDED
    publication_id = admission.publication.publication_id
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.FAILED
    runs = _read(db_engine, lambda r: r.get_parser_runs(P, publication_id))
    issues = _issues(db_engine, publication_id)
    if row.run_scoped:
        (run,) = runs
        assert run.status is ScheduleParserRunStatus.FAILED
        assert run.failure_code is row.code
        assert issues == [(row.code.value, run.parser_run_id)]
    else:
        assert all(run.status is not ScheduleParserRunStatus.RUNNING for run in runs)
        assert issues == [(row.code.value, None)]
    assert ISSUE_SEVERITY[row.code].value == "error"


@pytest.mark.parametrize("error_code", [ErrorCode.INTERNAL_ERROR, ErrorCode.UNAVAILABLE])
def test_transient_failure_releases_and_retries(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, error_code: ErrorCode
) -> None:
    admission = _admit(db_engine, w)
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    _parse_returns(monkeypatch, TransientFailure(error_code))
    first = _run_worker(db_engine)
    assert (first.released, first.completed) == (1, 0)
    assert _job_state(db_engine, admission.operation_id) is JobState.QUEUED
    publication_id = admission.publication.publication_id
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.PROCESSING
    assert _issues(db_engine, publication_id) == []
    assert _read(db_engine, lambda r: r.get_parser_runs(P, publication_id)) == ()
    monkeypatch.undo()
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    second = _run_worker(db_engine)
    assert second.completed == 1
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.COMPLETE


# ---- the lease (R2 24, AC-030) -------------------------------------------------------------


PHASES: Final = ("H1", "H3", "H5", "H6", "H7", "H8")


def _arm_expiry(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, w: World, job: LeasedJob, phase: str
) -> dict[str, Any]:
    """Expire the lease just before `phase`; the returned dict receives the snapshot."""
    held: dict[str, Any] = {}

    def expire() -> None:
        _expire(engine, job.operation_id)
        held["snapshot"] = _snapshot(engine)

    provider_hook = expire if phase == "H3" else None
    _serve(monkeypatch, FakeProvider(w, _small().pdf, on_fetch=provider_hook))
    if phase == "H1":
        expire()
    elif phase == "H5":
        original = handler_module.run_isolated_parse

        def parse_then_expire(data: bytes, **kwargs: Any) -> IsolatedParse:  # noqa: ANN401
            outcome = original(data, **kwargs)
            expire()
            return outcome

        monkeypatch.setattr(handler_module, "run_isolated_parse", parse_then_expire)
    elif phase in ("H6", "H7", "H8"):
        _at_checkpoint(monkeypatch, phase, expire)
    return held


@pytest.mark.parametrize("phase", PHASES)
def test_every_phase_refuses_after_lease_loss(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    _admit(db_engine, w)
    job = _claim(db_engine)
    held = _arm_expiry(db_engine, monkeypatch, w, job, phase)
    with pytest.raises(LeaseLostError):
        process_schedule_publication(db_engine, job, OWNER)
    assert _snapshot(db_engine) == held["snapshot"], phase


def test_no_write_after_lease_loss(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lost at the first row batch: no row, no issue, the run still running, nothing failed."""
    admission = _admit(db_engine, w)
    job = _claim(db_engine)
    held = _arm_expiry(db_engine, monkeypatch, w, job, "H6")
    with pytest.raises(LeaseLostError):
        process_schedule_publication(db_engine, job, OWNER)
    assert _snapshot(db_engine) == held["snapshot"]
    publication_id = admission.publication.publication_id
    (run,) = _read(db_engine, lambda r: r.get_parser_runs(P, publication_id))
    assert run.status is ScheduleParserRunStatus.RUNNING
    assert _read(db_engine, lambda r: r.count_parser_run_contents(P, run.parser_run_id)) == (0, 0)
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.PROCESSING


def test_lease_loss_is_counted_lost_not_released(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = _admit(db_engine, w)
    original = handler_module.run_isolated_parse

    def parse_then_expire(data: bytes, **kwargs: Any) -> IsolatedParse:  # noqa: ANN401
        outcome = original(data, **kwargs)
        _expire(db_engine, admission.operation_id)
        return outcome

    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    monkeypatch.setattr(handler_module, "run_isolated_parse", parse_then_expire)
    outcome = _run_worker(db_engine)
    assert (outcome.claimed, outcome.lost, outcome.released, outcome.completed) == (1, 1, 0, 0)
    with db_engine.connect() as c:
        last = c.execute(
            text("SELECT last_error_code FROM knowledge.schedule_jobs WHERE operation_id = :o"),
            {"o": admission.operation_id},
        ).scalar_one()
    assert last is None


# ---- re-claims (R6-F05, R7-N1, R7-N2) ------------------------------------------------------


def _parsed_then_lost(engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch) -> str:
    """Attempt 1 stores and finishes its run, then loses the lease before canonicalization."""
    admission = _admit(engine, w)
    job = _claim(engine)
    _arm_expiry(engine, monkeypatch, w, job, "H7")
    with pytest.raises(LeaseLostError):
        process_schedule_publication(engine, job, OWNER)
    monkeypatch.undo()
    (run,) = _read(engine, lambda r: r.get_parser_runs(P, admission.publication.publication_id))
    assert run.status is ScheduleParserRunStatus.PARSED
    return admission.publication.publication_id


def test_reclaimed_attempt_reuses_the_parsed_run(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _parsed_then_lost(db_engine, w, monkeypatch)
    (first,) = _read(db_engine, lambda r: r.get_parser_runs(P, publication_id))
    rows_before = _read(db_engine, lambda r: r.count_parser_run_contents(P, first.parser_run_id))
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    job = _claim(db_engine)
    assert job.attempt == 2
    process_schedule_publication(db_engine, job, OWNER)
    (run,) = _read(db_engine, lambda r: r.get_parser_runs(P, publication_id))
    assert run.parser_run_id == first.parser_run_id
    assert _read(db_engine, lambda r: r.count_parser_run_contents(P, run.parser_run_id)) == (
        rows_before
    )
    publication = _publication(db_engine, publication_id)
    assert publication.status is SchedulePublicationStatus.COMPLETE
    assert publication.accepted_parser_run_id == first.parser_run_id


def test_reclaimed_reparse_digest_must_equal_the_reused_run(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-parse that disagrees with the stored `parsed` run writes nothing (R7-N1, Q61)."""
    publication_id = _parsed_then_lost(db_engine, w, monkeypatch)
    before = _snapshot(db_engine)
    drifted = replace(parse_full_schedule(_small().pdf), published_schedule_title="Drifted Title")
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    _parse_returns(monkeypatch, ParsedResult(drifted))
    job = _claim(db_engine)
    with pytest.raises(JobExecutionError) as raised:
        process_schedule_publication(db_engine, job, OWNER)
    assert raised.value.code is ErrorCode.INTERNAL_ERROR
    after = _snapshot(db_engine)
    # Only the claim itself moved the job row (attempt 2).
    assert {k: v for k, v in after.items() if k != "schedule_jobs"} == {
        k: v for k, v in before.items() if k != "schedule_jobs"
    }
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.PROCESSING


@pytest.mark.parametrize("stored", ["rows", "issues"])
def test_running_run_of_this_attempt_with_stored_rows_is_an_invariant_breach(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    """This attempt's own `running` run already holds a row or an issue: no resumption.

    The `rows` case is also refused by S5b-1's `row_ordinal_gap`; the `issues`
    case is held only by the explicit count read (R7-N3), because
    `insert_issues` has no ordinal guard.
    """
    case = _small()
    expected = parse_full_schedule(case.pdf)
    admission = _admit(db_engine, w)
    publication_id = admission.publication.publication_id
    job = _claim(db_engine)
    lease = ScheduleLease(job.operation_id, OWNER, job.attempt)

    def stage(r: ScheduleRepository) -> str:
        r.begin_processing(P, publication_id, lease)
        r.pin_document(
            P, publication_id, lease, hashlib.sha256(case.pdf).hexdigest(), len(case.pdf)
        )
        run = r.start_parser_run(
            P, publication_id, lease, ScheduleParserIdentity.from_parse_result(expected)
        ).run
        if stored == "rows":
            r.insert_rows(P, run.parser_run_id, lease, expected.rows[:1])
        else:
            issue = ScheduleParseIssue(
                ScheduleIssueCode.INVALID_DATE,
                ISSUE_SEVERITY[ScheduleIssueCode.INVALID_DATE],
                1,
                None,
                None,
            )
            r.insert_issues(P, publication_id, lease, run.parser_run_id, [issue])
        return run.parser_run_id

    run_id = _read(db_engine, stage)
    counts = _read(db_engine, lambda r: r.count_parser_run_contents(P, run_id))
    before = _snapshot(db_engine)
    _serve(monkeypatch, FakeProvider(w, case.pdf))
    with pytest.raises(JobExecutionError) as raised:
        process_schedule_publication(db_engine, job, OWNER)
    assert raised.value.code is ErrorCode.INTERNAL_ERROR
    assert _snapshot(db_engine) == before
    assert _read(db_engine, lambda r: r.count_parser_run_contents(P, run_id)) == counts


def test_reclaimed_attempt_after_terminal_completes_without_writing(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = _admit(db_engine, w)
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    first = _claim(db_engine)
    process_schedule_publication(db_engine, first, OWNER)  # the job itself is not completed
    _expire(db_engine, first.operation_id)
    before = _snapshot(db_engine)
    spawned = _no_parse(monkeypatch)
    outcome = _run_worker(db_engine)
    assert outcome.completed == 1
    assert spawned == []
    after = _snapshot(db_engine)
    assert {k: v for k, v in after.items() if k != "schedule_jobs"} == {
        k: v for k, v in before.items() if k != "schedule_jobs"
    }
    assert _job_state(db_engine, admission.operation_id) is JobState.SUCCEEDED


# ---- the budget (R2 25) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("checkpoint", "run_scoped"),
    [
        ("C1", False),
        ("C2", False),
        ("C3", False),
        ("C4", False),
        ("H6", True),
        ("H7", False),
        ("H8", False),
    ],
)
def test_budget_checkpoints_fail_with_processing_budget_exceeded(
    db_engine: Engine,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
    run_scoped: bool,
) -> None:
    admission = _admit(db_engine, w)
    clock = Clock()
    monkeypatch.setattr(handler_module, "_clock", clock)
    seen = _at_checkpoint(monkeypatch, checkpoint, lambda: setattr(clock, "now", 1e6))
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert seen[-1] == checkpoint
    publication_id = admission.publication.publication_id
    assert _publication(db_engine, publication_id).status is SchedulePublicationStatus.FAILED
    runs = _read(db_engine, lambda r: r.get_parser_runs(P, publication_id))
    code = ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED.value
    if run_scoped:
        (run,) = runs
        assert run.failure_code is ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED
        assert _issues(db_engine, publication_id) == [(code, run.parser_run_id)]
    else:
        assert _issues(db_engine, publication_id) == [(code, None)]


def test_parse_is_not_spawned_with_less_than_the_minimum_wall(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At C3 70 s remain: the wall would be 10 s (< 15 s), so the child never starts."""
    admission = _admit(db_engine, w)
    clock = Clock()
    monkeypatch.setattr(handler_module, "_clock", clock)
    _at_checkpoint(monkeypatch, "C3", lambda: setattr(clock, "now", 170.0))
    _serve(monkeypatch, FakeProvider(w, _small().pdf))
    spawned = _no_parse(monkeypatch)
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    assert spawned == []
    _fails_run_less(db_engine, admission, ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)


# ---- the N3 count read ------------------------------------------------------------------------


def test_count_parser_run_contents_is_partitioned(
    db_engine: Engine, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission = _admit(db_engine, w)
    _serve(monkeypatch, FakeProvider(w, gen.build("full_invalid_date", "base").pdf))
    process_schedule_publication(db_engine, _claim(db_engine), OWNER)
    (run,) = _read(db_engine, lambda r: r.get_parser_runs(P, admission.publication.publication_id))
    counts = _read(db_engine, lambda r: r.count_parser_run_contents(P, run.parser_run_id))
    assert counts == (run.row_count, run.issue_count)
    assert counts[0] > 0 and counts[1] > 0
    assert _read(db_engine, lambda r: r.count_parser_run_contents(Q, run.parser_run_id)) == (0, 0)
