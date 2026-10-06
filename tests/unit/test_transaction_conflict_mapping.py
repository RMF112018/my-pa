"""SQLSTATE 40P01 / 40001 surface as `conflict` (KLP-WP-04, R6 section 8.4, KLP-AC-122).

FAST, unit half (the real-deadlock concurrency half is slice C's
`tests/concurrency/test_knowledge_review_lock_order.py`). A fake SQLAlchemy
`OperationalError` whose `.orig` carries `sqlstate` stands in for the driver:

* every raise site -- `unit_of_work._read`, `record_events.flush_record_events`
  and the feed reader's `_translated` -- raises `TransactionConflictError` before
  the `OperationalError` branch, and keeps the other classifications;
* `_port_failure` maps it to `ConflictError`, whose contract-fixed guidance is
  `after_refresh`, with no detail token (no contract change);
* `ApplicationService.invoke`'s terminal catch walks `__cause__`/`__context__`:
  an unwrapped port, the COMMIT itself and a port error re-raised `from None`
  over a deadlock all answer `conflict`; a non-conflict failure still answers
  `internal_error`;
* no driver text -- statement, parameter or message -- reaches the port error,
  its `__context__` or the rendered envelope; and nothing retries.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Final, cast

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from my_pa.application.commands import GetCapabilities
from my_pa.application.errors import ConflictError, problem_detail
from my_pa.application.service import _port_failure
from my_pa.contracts.ports import (
    AuditSink,
    EvidenceUnavailableError,
    RepositoryFailureError,
    TransactionConflictError,
    is_transaction_conflict,
    transaction_conflict_in_chain,
)
from my_pa.contracts.v1.errors import ErrorCode, RetryGuidance
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence import record_events as record_events_module
from my_pa.infrastructure.persistence.record_events import flush_record_events
from my_pa.infrastructure.persistence.unit_of_work import _read
from tests.conftest import (
    FakeProviders,
    FakeUnitOfWork,
    Scene,
    World,
    build_service,
    metadata_for,
)

SECRET: Final = "synthetic-driver-secret-7f3a"  # noqa: S105 - a planted marker, not a credential
CONFLICT_STATES: Final = ("40P01", "40001")


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"driver message {SECRET}")
        self.sqlstate = sqlstate


def _operational(sqlstate: str) -> OperationalError:
    return OperationalError(f"SELECT '{SECRET}'", {"value": SECRET}, _DriverError(sqlstate))


def _raising(error: BaseException) -> Callable[[], object]:
    def statement() -> object:
        raise error

    return statement


def _no_driver_text(error: BaseException) -> None:
    assert SECRET not in str(error)
    assert SECRET not in repr(error)
    assert error.__context__ is None
    assert error.__cause__ is None


# ---- the predicate -------------------------------------------------------------------


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_the_conflict_states_are_recognised_on_the_wrapper_and_the_driver(sqlstate: str) -> None:
    assert is_transaction_conflict(_operational(sqlstate))
    assert is_transaction_conflict(_DriverError(sqlstate))


@pytest.mark.parametrize("sqlstate", ["08006", "57014", "23505", "40002"])
def test_other_states_are_not_conflicts(sqlstate: str) -> None:
    assert not is_transaction_conflict(_operational(sqlstate))


# ---- the three raise sites -------------------------------------------------------------


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_read_raises_transaction_conflict_first(sqlstate: str) -> None:
    with pytest.raises(TransactionConflictError) as raised:
        _read(_raising(_operational(sqlstate)))
    _no_driver_text(raised.value)


def test_read_keeps_its_other_classifications() -> None:
    with pytest.raises(EvidenceUnavailableError):
        _read(_raising(_operational("08006")))
    with pytest.raises(RepositoryFailureError):
        _read(_raising(IntegrityError("INSERT", {}, _DriverError("23505"))))


class _Writer:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def allocate(self, principal_id: str, count: int) -> int:
        raise self._error

    def insert(self, first_sequence_number: int, drafts: object) -> None:
        raise AssertionError("unreachable")


class _Draft:
    principal_id = "prn_klpwp04conflict01"


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_flush_record_events_raises_transaction_conflict_first(sqlstate: str) -> None:
    with pytest.raises(TransactionConflictError) as raised:
        flush_record_events(_Writer(_operational(sqlstate)), [_Draft()])  # type: ignore[arg-type, list-item]
    _no_driver_text(raised.value)


def test_flush_record_events_keeps_its_other_classifications() -> None:
    with pytest.raises(EvidenceUnavailableError):
        flush_record_events(_Writer(_operational("08006")), [_Draft()])  # type: ignore[arg-type, list-item]


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_the_feed_readers_translation_raises_transaction_conflict_first(sqlstate: str) -> None:
    with pytest.raises(TransactionConflictError) as raised:
        record_events_module._translated(_raising(_operational(sqlstate)))
    _no_driver_text(raised.value)
    with pytest.raises(EvidenceUnavailableError):
        record_events_module._translated(_raising(_operational("08006")))


# ---- the public mapping ----------------------------------------------------------------


def test_port_failure_maps_it_to_conflict_after_refresh_without_a_detail() -> None:
    public = _port_failure(TransactionConflictError("the transaction lost a race"))
    assert isinstance(public, ConflictError)
    assert public.safe_details == ()
    problem = problem_detail(public, correlation_id="corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert problem.code is ErrorCode.CONFLICT
    assert problem.retry is RetryGuidance.AFTER_REFRESH


def test_the_chain_walk_finds_a_conflict_kept_in_context_and_is_cycle_safe() -> None:
    try:
        try:
            raise _operational("40P01")
        except OperationalError:
            raise RepositoryFailureError("wrapped") from None
    except RepositoryFailureError as wrapped:
        assert transaction_conflict_in_chain(wrapped)
    looped = RuntimeError("a")
    looped.__context__ = RuntimeError("b")
    looped.__context__.__context__ = looped
    assert not transaction_conflict_in_chain(looped)


# ---- the invoke terminal catch -----------------------------------------------------------


class _Calls:
    def __init__(self) -> None:
        self.count = 0


def _service(scene: Scene, world: World, factory: Callable[[], FakeUnitOfWork]) -> object:
    service = build_service(world, scene.providers)
    service._unit_of_work = factory  # type: ignore[attr-defined]
    return service


class _CommitFails(FakeUnitOfWork):
    """The COMMIT raises the raw driver error, as `context.__exit__` would."""

    def __init__(self, world: World, error: BaseException, calls: _Calls) -> None:
        super().__init__(world)
        self._error = error
        self._calls = calls

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        self._calls.count += 1
        if exc is None:
            raise self._error


class _AuditFails(FakeUnitOfWork):
    """An unwrapped port: the shared authorization path's audit write raises raw."""

    def __init__(self, world: World, error: Callable[[], None], calls: _Calls) -> None:
        super().__init__(world)
        self._raise = error
        self._calls = calls

    @property
    def audit(self) -> AuditSink:
        outer = self

        class _Sink:
            def record(self, event: object) -> None:
                outer._calls.count += 1
                outer._raise()

        return cast(AuditSink, _Sink())


def _invoke(service: object, scene: Scene) -> tuple[ErrorCode | None, str]:
    metadata = metadata_for(
        Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal
    )

    envelope = service.invoke(metadata, GetCapabilities(), principal=scene.principal)  # type: ignore[attr-defined]
    rendered = envelope.to_canonical_json()
    assert SECRET not in rendered
    code = None if envelope.error is None else envelope.error.code
    return code, rendered


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_a_conflict_at_commit_answers_conflict_once(
    scene: Scene, world: World, sqlstate: str
) -> None:
    calls = _Calls()
    service = _service(scene, world, lambda: _CommitFails(world, _operational(sqlstate), calls))
    code, rendered = _invoke(service, scene)
    assert code is ErrorCode.CONFLICT
    assert '"after_refresh"' in rendered
    assert calls.count == 1, "no retry loop"


@pytest.mark.parametrize("sqlstate", CONFLICT_STATES)
def test_a_conflict_from_an_unwrapped_port_answers_conflict(
    scene: Scene, world: World, sqlstate: str
) -> None:
    calls = _Calls()

    def fail() -> None:
        raise _operational(sqlstate)

    service = _service(scene, world, lambda: _AuditFails(world, fail, calls))
    code, _ = _invoke(service, scene)
    assert code is ErrorCode.CONFLICT
    assert calls.count == 1


def test_a_port_error_raised_over_a_conflict_answers_conflict(scene: Scene, world: World) -> None:
    calls = _Calls()

    def fail() -> None:
        try:
            raise _operational("40001")
        except OperationalError:
            raise RepositoryFailureError("wrapped") from None

    service = _service(scene, world, lambda: _AuditFails(world, fail, calls))
    code, _ = _invoke(service, scene)
    assert code is ErrorCode.CONFLICT


def test_a_non_conflict_driver_failure_still_answers_internal_error(
    scene: Scene, world: World
) -> None:
    calls = _Calls()
    service = _service(scene, world, lambda: _CommitFails(world, _operational("08006"), calls))
    code, _ = _invoke(service, scene)
    assert code is ErrorCode.INTERNAL_ERROR


def test_the_control_an_unfailing_unit_of_work_succeeds(scene: Scene, world: World) -> None:
    service = build_service(world, FakeProviders({}))
    code, _ = _invoke(service, scene)
    assert code is None
