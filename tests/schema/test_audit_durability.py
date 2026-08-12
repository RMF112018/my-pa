"""The audit outlives the work it describes, and a lost audit refuses the request.

This is the asymmetry `D-34` names, proved against a real PostgreSQL transaction
rather than against a fake that cannot roll anything back. That distinction is
the reason this file is in the `database` tier and not beside the application
contract tests: `tests/conftest.py`'s `FakeUnitOfWork` counts commits and
rollbacks but its audit list is an ordinary Python list, so an event "survives" a
rollback there whatever the design is. Only a second connection can be shown to
survive the first one's rollback, and only a server can show it.

Three claims.

**An allowed request whose handler fails still leaves an audit record.** The
enrollment path is used because it is the one that writes: it inserts an
enrollment and a job, and the failure is induced *after* both, so the rollback
has real work to discard. The audit row is then still there, and the enrollment
and the job are not.

**A failure to persist an audit event fails the request closed.** The sink is
pointed at a server that is not there. The caller gets an error, no enrollment
was written, and no audit row exists — which is the whole point: the request did
not succeed while its audit was lost.

**Every audit outcome reaches the durable store.** All three members of
`AuditOutcome`, driven through the real service, plus the structural claim that
`service.py`'s enumeration is still a derivation — that `AuditSink.record` has
exactly the two call sites the docstring derives from.

Everything is synthetic: the source root is an invented path that is never
opened, the fixture tree is pytest's `tmp_path`, and no live source is reached.
"""

from __future__ import annotations

import ast
import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.conftest import DEFAULT_LIMITS

from my_pa.application.commands import EnrollSource, GetCapabilities, ListSources
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import (
    AuditSink,
    CaptureRepository,
    EnrollmentRepository,
    EvidenceUnavailableError,
    KnowledgeRecord,
    KnowledgeRepository,
    OperationQueue,
    ProjectRepository,
    PulseRepository,
    ReviewRepository,
    SearchOutcome,
    SituationRepository,
    SourceProviders,
    SourceRepository,
    UnitOfWork,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import SearchRequest
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[2]

APPLICATION = ROOT / "src" / "my_pa" / "application"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE = "my_pa_audit_durability_test"

WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/audit/corpus"

#: A URL that resolves and refuses, so the sink fails at connect time rather than
#: hanging. Port 1 on loopback has nothing listening on it.
UNREACHABLE_URL: Final = "postgresql+psycopg://nobody@127.0.0.1:1/nothing"


def _administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        with built.begin() as connection:
            # Each test starts from an empty audit trail, so a count is a
            # statement about what this test did.
            connection.execute(
                text(
                    "TRUNCATE knowledge.native_simulation_receipts, "
                    "knowledge.native_checkpoints, "
                    "knowledge.native_admission_authorities, knowledge.audit_events"
                )
            )
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
        yield built
    finally:
        built.dispose()


class _FailingKnowledge(KnowledgeRepository):
    """The real knowledge port, except that `limitations` refuses.

    `limitations` is chosen because `sources.enroll` calls it *after* it has
    accepted the enrollment and enqueued the job. The failure therefore lands
    with real uncommitted work on the connection, which is what makes the
    rollback in this test discard something rather than nothing.
    """

    def __init__(self, inner: KnowledgeRepository) -> None:
        self._inner = inner

    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        eligible: int | None,
        queued: int = 0,
    ) -> CoverageCounts:
        return self._inner.coverage(
            enrollment_id, observed_at=observed_at, eligible=eligible, queued=queued
        )

    def limitations(self, enrollment_id: str) -> tuple[AggregateLimitation, ...]:
        raise EvidenceUnavailableError("the limitation read was made to fail by this test")

    def outcome_for_object(
        self, *, enrollment_id: str, source_object_id: str
    ) -> ExtractionStatus | None:
        return self._inner.outcome_for_object(
            enrollment_id=enrollment_id, source_object_id=source_object_id
        )

    def search(self, request: SearchRequest, *, now: datetime) -> SearchOutcome:
        return self._inner.search(request, now=now)

    def read(self, knowledge_id: str, *, enrollment_id: str) -> KnowledgeRecord | None:
        return self._inner.read(knowledge_id, enrollment_id=enrollment_id)


class _FailsAfterTheWork(UnitOfWork):
    """A real unit of work whose knowledge port fails once the work is written.

    A wrapper rather than a fake: the transaction, the connection, the writers,
    and the audit sink are all the production ones, and exactly one method is
    replaced. Anything less real would not prove the claim, because the claim is
    about what a PostgreSQL rollback does.
    """

    def __init__(self, inner: UnitOfWork) -> None:
        self._inner = inner

    def __enter__(self) -> UnitOfWork:
        self._inner.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._inner.__exit__(exc_type, exc, traceback)

    @property
    def providers(self) -> SourceProviders:
        return self._inner.providers

    @property
    def sources(self) -> SourceRepository:
        return self._inner.sources

    @property
    def enrollments(self) -> EnrollmentRepository:
        return self._inner.enrollments

    @property
    def operations(self) -> OperationQueue:
        return self._inner.operations

    @property
    def knowledge(self) -> KnowledgeRepository:
        return _FailingKnowledge(self._inner.knowledge)

    @property
    def captures(self) -> CaptureRepository:
        return self._inner.captures

    @property
    def reviews(self) -> ReviewRepository:
        return self._inner.reviews

    @property
    def situations(self) -> SituationRepository:
        return self._inner.situations

    @property
    def projects(self) -> ProjectRepository:
        return self._inner.projects

    @property
    def pulse(self) -> PulseRepository:
        return self._inner.pulse

    @property
    def audit(self) -> AuditSink:
        return self._inner.audit


def _operator() -> Principal:
    return Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def _metadata(capability: Capability, purpose: Purpose, principal: Principal) -> RequestMetadata:
    return RequestMetadata(
        request_id=f"req-{capability.value}",
        capability=capability,
        purpose=purpose,
        principal_id=principal.principal_id,
        requested_at=WHEN,
    )


def _register(engine: Engine, key: str) -> tuple[str, str]:
    """One configured source and one observed object under it."""
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=f"{NATIVE_ROOT}/{key}",
        )
        observed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/{key}/note.md",
            kind=ObjectKind.FILE,
            fingerprint=f"fingerprint-{key}",
            modified_at=WHEN,
            media_type="text/markdown",
            size_bytes=32,
        )
    return source.source_id, observed.source_object_id


def _service(
    engine: Engine, *, audit_engine: Engine | None = None, failing: bool = False
) -> ApplicationService:
    """The real service over the real store, with the real durable sink."""
    sink = SqlAlchemyAuditSink(engine if audit_engine is None else audit_engine)

    def unit_of_work() -> UnitOfWork:
        real = SqlAlchemyUnitOfWork(engine, audit=sink)
        return _FailsAfterTheWork(real) if failing else real

    return ApplicationService(
        unit_of_work=unit_of_work,
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


#: One statement per counted table, written out rather than interpolated. A
#: table name cannot be a bound parameter, and building the statement from a
#: variable is the shape that becomes an injection the day the variable stops
#: being a literal in this file.
_COUNTS = text(
    "SELECT (SELECT count(*) FROM knowledge.audit_events), "
    " (SELECT count(*) FROM knowledge.enrollments), "
    " (SELECT count(*) FROM knowledge.jobs)"
)


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        audit, enrollments, jobs = connection.execute(_COUNTS).one()
    return {"audit_events": int(audit), "enrollments": int(enrollments), "jobs": int(jobs)}


def _outcomes(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT outcome FROM knowledge.audit_events ORDER BY audit_id")
            ).scalars()
        )


def _enroll(
    service: ApplicationService,
    principal: Principal,
    source_id: str,
    object_id: str,
    key: str,
) -> ResponseEnvelope:
    enroll = EnrollSource(
        source_id=source_id,
        object_ids=(object_id,),
        root_object_id=None,
        depth=0,
        media_types=("text/markdown",),
        idempotency_key=key,
    )
    return service.invoke(
        _metadata(Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT, principal),
        enroll,
        principal=principal,
    )


@pytest.mark.database
def test_an_allowed_request_whose_handler_fails_still_leaves_an_audit_record(
    engine: Engine,
) -> None:
    """The asymmetry, closed. Recorded as allowed, and it survives the rollback.

    Before `D-34` this row did not exist: the audit was written on the same
    connection as the work, so the rollback that discarded the half-written
    enrollment discarded the record of the authorization with it, and a failed
    security-relevant action left no trace at all.
    """
    source_id, object_id = _register(engine, "handler-fails")
    principal = _operator()
    service = _service(engine, failing=True)

    envelope = _enroll(service, principal, source_id, object_id, "enroll-handler-fails")

    assert envelope.error is not None
    counts = _counts(engine)
    # The work is gone: no enrollment, no queued job.
    assert (counts["enrollments"], counts["jobs"]) == (0, 0)
    # The decision is not.
    assert counts["audit_events"] == 1
    assert _outcomes(engine) == [AuditOutcome.ALLOWED.value]

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT capability, purpose, principal_id, denial_reason "
                "FROM knowledge.audit_events"
            )
        ).one()
    assert row[0] == Capability.SOURCES_ENROLL.value
    assert row[1] == Purpose.BOUNDED_ENROLLMENT.value
    assert row[2] == principal.principal_id
    assert row[3] is None
    assert object_id.startswith("obj_")


@pytest.mark.database
def test_a_failure_to_persist_an_audit_event_fails_the_request_closed(engine: Engine) -> None:
    """`module-boundaries.md` section 5.6: fail closed when the audit will not write.

    The sink is aimed at a server that is not there, so `record` raises before
    any handler runs. The caller is told the request failed, nothing was
    enrolled, nothing was queued, and no audit row exists — the request did not
    succeed while its audit was lost.
    """
    source_id, object_id = _register(engine, "audit-fails")
    principal = _operator()
    unreachable = create_database_engine(UNREACHABLE_URL)
    try:
        service = _service(engine, audit_engine=unreachable)
        envelope = _enroll(service, principal, source_id, object_id, "enroll-audit-fails")
    finally:
        unreachable.dispose()

    error = envelope.error
    assert error is not None
    # Classified rather than crashing: the sink translates into the port's
    # vocabulary and the service maps that to a public code.
    assert error.code.value == "unavailable"
    assert _counts(engine) == {"audit_events": 0, "enrollments": 0, "jobs": 0}


@pytest.mark.database
def test_a_successful_request_commits_its_work_beside_its_audit(engine: Engine) -> None:
    """The control for the two tests above.

    Without it, "no enrollment was written" would be evidence of nothing: a
    service that never enrolled anything would pass both of them.
    """
    source_id, object_id = _register(engine, "succeeds")
    principal = _operator()

    envelope = _enroll(_service(engine), principal, source_id, object_id, "enroll-succeeds")

    assert envelope.error is None
    assert _counts(engine) == {"audit_events": 1, "enrollments": 1, "jobs": 1}
    assert _outcomes(engine) == [AuditOutcome.ALLOWED.value]


@pytest.mark.database
def test_every_audit_outcome_reaches_the_durable_store(engine: Engine) -> None:
    """All three members of `AuditOutcome`, through the real service and sink.

    One request per outcome, and the assertion is against the enum rather than
    against a list written here, so a fourth outcome added to the domain without
    a path to the store fails this rather than being quietly untested.
    """
    source_id, _ = _register(engine, "outcomes")
    service = _service(engine)

    # `allowed`: capabilities.get needs no scope and no enrollment.
    reader = _operator()
    allowed = service.invoke(
        _metadata(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, reader),
        GetCapabilities(),
        principal=reader,
    )

    # `denied`: a principal holding no enrollment asks to list a source.
    stranger = _operator()
    denied = service.invoke(
        _metadata(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, stranger),
        ListSources(source_id=source_id, parent_object_id=None),
        principal=stranger,
    )

    # `failed`: the declared capability and the payload's capability disagree.
    confused = _operator()
    mismatched = service.invoke(
        _metadata(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, confused),
        GetCapabilities(),
        principal=confused,
    )

    assert allowed.error is None
    assert denied.error is not None
    assert mismatched.error is not None

    assert set(_outcomes(engine)) == {member.value for member in AuditOutcome}
    assert len(_outcomes(engine)) == 3

    with engine.connect() as connection:
        reasons = dict(
            connection.execute(
                text("SELECT outcome, denial_reason FROM knowledge.audit_events")
            ).all()
        )
    # A denial names its reason; the other two have none to name.
    assert reasons[AuditOutcome.DENIED.value] == "scope_not_authorized"
    assert reasons[AuditOutcome.ALLOWED.value] is None
    assert reasons[AuditOutcome.FAILED.value] is None


def _record_call_sites() -> list[str]:
    """Every `<something>.audit.record(...)` call in the application layer.

    Matched on the attribute chain rather than on the text, so a rename or a
    reformat does not change the answer and an alias does not hide one.
    """
    found: list[str] = []
    for path in sorted(APPLICATION.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "record":
                continue
            owner = function.value
            if isinstance(owner, ast.Attribute) and owner.attr == "audit":
                found.append(f"{path.name}:{node.lineno}")
    return found


def test_the_service_enumeration_is_still_a_derivation() -> None:
    """`service.py`'s outcome list is derived from two facts, and this is one.

    The docstring says `AuditSink.record` has exactly two call sites in this
    layer — `authorization.authorize` and the mismatch branch of `_run` — and
    derives its closed list of outcomes from that. A third call site would make
    the enumeration a survey again, silently. This is what turns that into a
    failure.
    """
    sites = _record_call_sites()
    assert len(sites) == 2, f"audit.record now has {len(sites)} call sites: {sites}"
    assert {site.split(":")[0] for site in sites} == {"authorization.py", "service.py"}


def test_the_call_site_scan_is_not_vacuous(tmp_path: Path) -> None:
    """Guard the scan: one that matched nothing would report two as zero."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def go(unit_of_work: object, event: object) -> None:\n"
        "    unit_of_work.audit.record(event)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"), filename=str(planted))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "record"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "audit"
    ]
    assert len(matches) == 1
