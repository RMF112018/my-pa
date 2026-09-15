"""PC-CM-RUN01-WP05: the settings lock, the receipt ledger, and the shared connection.

The `database` tier, on a disposable head-migrated clone. What
`tests/unit/test_project_controls_settings_history.py` proves about the receipt
*shape*, this module proves about the stored table: that `FOR UPDATE` really
takes a row lock, that every column round-trips through
`_to_settings_history` unchanged, that the unique
`(principal_id, idempotency_key)` race arrives as
`ConstraintProjectSettingsHistoryKeyConflictError` rather than as a raw
`IntegrityError`, that the same-Principal Project foreign key refuses a foreign
Project and does **not** get translated, and that
`SqlAlchemyConstraintManagementUnitOfWork.projects` is on the unit of work's own
connection — which is the only reason a `lock_project` taken there means
anything by the time the settings row is written.

The lock proofs follow `tests/database/test_constraint_numbering_concurrency.py`
in both of its shapes, because a sequential readback cannot tell
`with_for_update()` from a plain select and a build that dropped the lock would
pass every other test here. The controls ask for the same row `FOR UPDATE
NOWAIT` from a second session and require a refusal — and, for the plain read,
require *no* refusal. The two races then run overlapping transactions with the
second in a thread under a `lock_timeout`, so a build holding no lock reports
instead of hanging the tier. Marked `database` and nothing else: this repository
declares no `concurrency` mark, and `tests/concurrency/` is not a directory the
CI classifier matches.

Every identifier, key, digest, label and date here is synthetic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, delete, event, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.project_controls.history import (
    ConstraintMutationActor,
    ConstraintProjectSettingsHistoryEntry,
    ConstraintProjectSettingsHistoryKeyConflictError,
    ConstraintProjectSettingsOutcome,
    issue_settings_history_id,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_project_settings_history,
    projects,
)

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_wp05aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_wp05bbbb0002bbbb0002"
PROJECT_A: Final = "prj_wp05aaaa0001aaaa"
PROJECT_B: Final = "prj_wp05bbbb0002bbbb"
#: A Project of `PRINCIPAL_A` that nobody has configured, so an absent settings
#: row can be told apart from a foreign one.
PROJECT_BARE: Final = "prj_wp05cccc0003cccc"
CORRELATION: Final = "corr_wp05aaaa0001aaaa"

ZONE: Final = "America/Chicago"
OTHER_ZONE: Final = "Europe/London"
DIGEST: Final = "a" * 64
OTHER_DIGEST: Final = "b" * 64

T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

#: Long enough that a loaded host does not turn a pass into a failure, short
#: enough that a build holding no lock reports instead of hanging the tier.
LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0


def seed(engine: Engine) -> None:
    """Two Principals, three Projects, and one configured Project each."""
    with engine.begin() as connection:
        for principal, project in (
            (PRINCIPAL_A, PROJECT_A),
            (PRINCIPAL_B, PROJECT_B),
            (PRINCIPAL_A, PROJECT_BARE),
        ):
            connection.execute(
                insert(projects).values(
                    project_id=project,
                    principal_id=principal,
                    name="A Synthetic Project",
                    state="active",
                    participants=[],
                    opened_at=T0,
                    created_at=T0,
                    updated_at=T0,
                )
            )
    with SqlAlchemyConstraintManagementUnitOfWork(engine) as uow:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
            uow.constraints.insert_project_settings(
                principal,
                ConstraintProjectSettings(
                    principal_id=principal,
                    project_id=project,
                    timezone_name=ZONE,
                    version=1,
                    created_at=T0,
                    updated_at=T0,
                ),
            )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """A head-migrated clone with the synthetic world already in it."""
    seed(migrated_engine)
    return migrated_engine


def _entry(
    *,
    principal_id: str = PRINCIPAL_A,
    project_id: str = PROJECT_A,
    idempotency_key: str = "wp05-settings-key-0001",
    request_digest: str = DIGEST,
    **overrides: object,
) -> ConstraintProjectSettingsHistoryEntry:
    """An applied first-configure receipt carrying every optional column."""
    fields: dict[str, object] = {
        "history_id": issue_settings_history_id(),
        "principal_id": principal_id,
        "project_id": project_id,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "outcome": ConstraintProjectSettingsOutcome.APPLIED,
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "occurred_at": T0,
        "recorded_at": T0 + timedelta(milliseconds=5),
        "before_settings_version": None,
        "after_settings_version": 1,
        "resulting_timezone_name": ZONE,
        "resulting_settings_updated_at": T0,
        "client_context": "browser",
        "correlation_id": CORRELATION,
    }
    fields.update(overrides)
    return ConstraintProjectSettingsHistoryEntry(**fields)  # type: ignore[arg-type]


def _impatient(engine: Engine) -> Engine:
    """The same database, on connections that refuse to wait forever for a lock."""

    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    return engine


# --- get_project_settings_for_update --------------------------------------


def test_the_locking_read_returns_the_same_row_the_plain_read_does(staged: Engine) -> None:
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        plain = uow.constraints.get_project_settings(PRINCIPAL_A, PROJECT_A)
        locked = uow.constraints.get_project_settings_for_update(PRINCIPAL_A, PROJECT_A)

    assert locked == plain
    assert locked is not None
    assert (locked.timezone_name, locked.version) == (ZONE, 1)
    assert locked.created_at == T0


def test_an_unconfigured_project_of_mine_locks_to_none(staged: Engine) -> None:
    """`None` is "no settings row", not "not your Project" — the Project is real."""
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        assert uow.constraints.get_project_settings_for_update(PRINCIPAL_A, PROJECT_BARE) is None
        assert uow.projects.lock_project(PRINCIPAL_A, PROJECT_BARE) is not None


def test_another_principals_configured_project_locks_to_none(staged: Engine) -> None:
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        assert uow.constraints.get_project_settings_for_update(PRINCIPAL_A, PROJECT_B) is None
        assert uow.projects.lock_project(PRINCIPAL_A, PROJECT_B) is None


def test_the_locking_read_actually_locks_the_settings_row(staged: Engine) -> None:
    """The lock proof, as a control rather than as a race.

    `FOR UPDATE NOWAIT` from a second session must be refused while this one
    holds the row. A sequential readback cannot tell `with_for_update()` from a
    plain select; this can, and reddens here if the lock is ever dropped.
    """
    holder = staged.connect()
    other = staged.connect()
    try:
        transaction = holder.begin()
        assert (
            SqlConstraintManagementRepository(holder).get_project_settings_for_update(
                PRINCIPAL_A, PROJECT_A
            )
            is not None
        )
        with pytest.raises(DBAPIError) as caught:
            other.execute(
                text(
                    "SELECT 1 FROM knowledge.constraint_project_settings "
                    "WHERE project_id = :identity FOR UPDATE NOWAIT"
                ),
                {"identity": PROJECT_A},
            )
        assert "lock" in str(caught.value).lower()
        transaction.rollback()
    finally:
        holder.close()
        other.close()


def test_the_plain_read_takes_no_lock(staged: Engine) -> None:
    """The other half of the control: `get_project_settings` must stay lock-free."""
    holder = staged.connect()
    other = staged.connect()
    try:
        transaction = holder.begin()
        assert (
            SqlConstraintManagementRepository(holder).get_project_settings(PRINCIPAL_A, PROJECT_A)
            is not None
        )
        other.execute(
            text(
                "SELECT 1 FROM knowledge.constraint_project_settings "
                "WHERE project_id = :identity FOR UPDATE NOWAIT"
            ),
            {"identity": PROJECT_A},
        )
        transaction.rollback()
    finally:
        holder.close()
        other.close()


def test_a_second_locking_read_sees_the_committed_version_rather_than_the_one_it_raced(
    staged: Engine,
) -> None:
    """Two overlapping configures: the waiter re-reads after the holder commits."""
    waiting = _impatient(staged)
    observed: list[int] = []

    def _second() -> None:
        with SqlAlchemyConstraintManagementUnitOfWork(waiting) as uow:
            row = uow.constraints.get_project_settings_for_update(PRINCIPAL_A, PROJECT_A)
            assert row is not None
            observed.append(row.version)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqlAlchemyConstraintManagementUnitOfWork(staged) as holder:
            first = holder.constraints.get_project_settings_for_update(PRINCIPAL_A, PROJECT_A)
            assert first is not None
            waiter = pool.submit(_second)
            holder.constraints.update_project_settings(
                PRINCIPAL_A,
                ConstraintProjectSettings(
                    principal_id=PRINCIPAL_A,
                    project_id=PROJECT_A,
                    timezone_name=OTHER_ZONE,
                    version=first.version + 1,
                    created_at=T0,
                    updated_at=T0 + timedelta(minutes=1),
                ),
            )
        waiter.result(timeout=JOIN_TIMEOUT_SECONDS)

    assert observed == [2]


# --- insert_project_settings_history and its readback ----------------------


def test_every_receipt_column_round_trips_unchanged(staged: Engine) -> None:
    entry = _entry()

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, entry)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        stored = uow.constraints.get_project_settings_history_by_idempotency_key(
            PRINCIPAL_A, entry.idempotency_key
        )

    assert stored == entry


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {
                "outcome": ConstraintProjectSettingsOutcome.APPLIED,
                "before_settings_version": 1,
                "after_settings_version": 2,
                "resulting_timezone_name": OTHER_ZONE,
            },
            id="applied-reconfigure",
        ),
        pytest.param(
            {
                "outcome": ConstraintProjectSettingsOutcome.NO_OP,
                "before_settings_version": 1,
                "after_settings_version": 1,
            },
            id="no-op",
        ),
        pytest.param(
            {
                "outcome": ConstraintProjectSettingsOutcome.REJECTED,
                "before_settings_version": 1,
                "after_settings_version": 1,
                "resulting_timezone_name": None,
                "resulting_settings_updated_at": None,
                "failure_code": "settings_version_stale",
                "failure_detail": "the expected settings version is not the current one",
            },
            id="rejected-against-a-row",
        ),
        pytest.param(
            {
                "outcome": ConstraintProjectSettingsOutcome.REJECTED,
                "before_settings_version": None,
                "after_settings_version": None,
                "resulting_timezone_name": None,
                "resulting_settings_updated_at": None,
                "failure_code": "project_timezone_invalid",
            },
            id="rejected-without-a-row",
        ),
        pytest.param(
            {"client_context": None, "correlation_id": None},
            id="applied-with-no-client-metadata",
        ),
        pytest.param(
            {"actor": ConstraintMutationActor.ASSISTANT},
            id="assistant-actor",
        ),
        pytest.param(
            {"actor": ConstraintMutationActor.SYSTEM},
            id="system-actor",
        ),
    ],
)
def test_every_stored_outcome_and_actor_the_checks_admit_persists(
    staged: Engine, overrides: dict[str, object]
) -> None:
    entry = _entry(idempotency_key="wp05-settings-key-0002", **overrides)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, entry)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        assert (
            uow.constraints.get_project_settings_history_by_idempotency_key(
                PRINCIPAL_A, entry.idempotency_key
            )
            == entry
        )


def test_the_receipt_is_stamped_with_the_authenticated_principal(staged: Engine) -> None:
    """`_bound` stamps the caller, so a receipt cannot re-home itself by being written."""
    entry = _entry()

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, entry)

    with staged.begin() as connection:
        stored = connection.execute(
            select(constraint_project_settings_history.c.principal_id).where(
                constraint_project_settings_history.c.history_id == entry.history_id
            )
        ).scalar_one()

    assert stored == PRINCIPAL_A


def test_an_unknown_key_reads_back_as_none(staged: Engine) -> None:
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        assert (
            uow.constraints.get_project_settings_history_by_idempotency_key(
                PRINCIPAL_A, "wp05-never-used-key-01"
            )
            is None
        )


def test_another_principals_receipt_is_answered_as_an_absent_one(staged: Engine) -> None:
    shared_key = "wp05-shared-key-000001"
    theirs = _entry(principal_id=PRINCIPAL_B, project_id=PROJECT_B, idempotency_key=shared_key)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_B, theirs)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        assert (
            uow.constraints.get_project_settings_history_by_idempotency_key(PRINCIPAL_A, shared_key)
            is None
        )


def test_the_same_key_is_free_in_another_principals_partition(staged: Engine) -> None:
    """The unique constraint is `(principal_id, idempotency_key)`, not the key alone."""
    shared_key = "wp05-shared-key-000002"

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_A, _entry(idempotency_key=shared_key)
        )
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_B,
            _entry(principal_id=PRINCIPAL_B, project_id=PROJECT_B, idempotency_key=shared_key),
        )

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        mine = uow.constraints.get_project_settings_history_by_idempotency_key(
            PRINCIPAL_A, shared_key
        )
        theirs = uow.constraints.get_project_settings_history_by_idempotency_key(
            PRINCIPAL_B, shared_key
        )

    assert mine is not None
    assert theirs is not None
    assert mine.project_id == PROJECT_A
    assert theirs.project_id == PROJECT_B


# --- The translated key conflict ------------------------------------------


@pytest.mark.parametrize("digest", [DIGEST, OTHER_DIGEST], ids=["same-digest", "other-digest"])
def test_a_reused_key_raises_the_typed_conflict_and_never_an_integrity_error(
    staged: Engine, digest: str
) -> None:
    """Replay and conflict both arrive here as the same typed refusal.

    Which one it *was* is the stored digest's answer, read back afterwards;
    this method makes no judgement, and the caller never sees SQLAlchemy.
    """
    key = "wp05-settings-key-0003"

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, _entry(idempotency_key=key))

    with (
        pytest.raises(ConstraintProjectSettingsHistoryKeyConflictError) as raised,
        SqlAlchemyConstraintManagementUnitOfWork(staged) as uow,
    ):
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_A, _entry(idempotency_key=key, request_digest=digest)
        )

    assert raised.value.code == "constraint_settings_history_idempotency_key_taken"
    assert not isinstance(raised.value, IntegrityError)

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        stored = uow.constraints.get_project_settings_history_by_idempotency_key(PRINCIPAL_A, key)
    assert stored is not None
    assert stored.request_digest == DIGEST


def test_the_conflict_leaves_exactly_one_receipt_behind(staged: Engine) -> None:
    key = "wp05-settings-key-0004"

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, _entry(idempotency_key=key))
    with (
        pytest.raises(ConstraintProjectSettingsHistoryKeyConflictError),
        SqlAlchemyConstraintManagementUnitOfWork(staged) as uow,
    ):
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_A, _entry(idempotency_key=key, request_digest=OTHER_DIGEST)
        )

    with staged.begin() as connection:
        rows = connection.execute(
            select(constraint_project_settings_history.c.history_id).where(
                constraint_project_settings_history.c.idempotency_key == key
            )
        ).all()

    assert len(rows) == 1


def test_two_transactions_racing_one_key_leave_one_winner_and_one_typed_conflict(
    staged: Engine,
) -> None:
    """The race the unique constraint exists for, overlapping rather than sequential."""
    waiting = _impatient(staged)
    key = "wp05-settings-key-0005"
    outcome: list[str] = []

    def _second() -> None:
        try:
            with SqlAlchemyConstraintManagementUnitOfWork(waiting) as uow:
                uow.constraints.insert_project_settings_history(
                    PRINCIPAL_A, _entry(idempotency_key=key, request_digest=OTHER_DIGEST)
                )
        except ConstraintProjectSettingsHistoryKeyConflictError:
            outcome.append("conflict")
        else:
            outcome.append("applied")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqlAlchemyConstraintManagementUnitOfWork(staged) as holder:
            holder.constraints.insert_project_settings_history(
                PRINCIPAL_A, _entry(idempotency_key=key)
            )
            waiter = pool.submit(_second)
        waiter.result(timeout=JOIN_TIMEOUT_SECONDS)

    assert outcome == ["conflict"]


# --- What is deliberately *not* translated ---------------------------------


def test_a_foreign_project_is_refused_by_the_composite_foreign_key(staged: Engine) -> None:
    """`PRINCIPAL_A` cannot file a receipt against `PRINCIPAL_B`'s Project.

    And the refusal arrives as the `IntegrityError` it is: translating it would
    tell the caller to change its idempotency key over an ownership failure.
    """
    with (
        pytest.raises(IntegrityError) as raised,
        SqlAlchemyConstraintManagementUnitOfWork(staged) as uow,
    ):
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_A, _entry(project_id=PROJECT_B, idempotency_key="wp05-foreign-key-0001")
        )

    assert not isinstance(raised.value, ConstraintProjectSettingsHistoryKeyConflictError)


def test_an_unknown_project_is_refused_by_the_same_foreign_key(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError),
        SqlAlchemyConstraintManagementUnitOfWork(staged) as uow,
    ):
        uow.constraints.insert_project_settings_history(
            PRINCIPAL_A,
            _entry(project_id="prj_wp05zzzz9999zzzz", idempotency_key="wp05-absent-key-0001"),
        )


def test_a_duplicate_history_identifier_is_not_reported_as_a_key_conflict(
    staged: Engine,
) -> None:
    """The primary key is a unique violation too, and must not borrow the translation."""
    entry = _entry(idempotency_key="wp05-settings-key-0006")

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, entry)

    clash = _entry(idempotency_key="wp05-settings-key-0007")
    object.__setattr__(clash, "history_id", entry.history_id)

    with (
        pytest.raises(IntegrityError) as raised,
        SqlAlchemyConstraintManagementUnitOfWork(staged) as uow,
    ):
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, clash)

    assert not isinstance(raised.value, ConstraintProjectSettingsHistoryKeyConflictError)


# --- Immutability ----------------------------------------------------------


def test_a_stored_receipt_cannot_be_updated_or_deleted(staged: Engine) -> None:
    entry = _entry(idempotency_key="wp05-settings-key-0008")

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        uow.constraints.insert_project_settings_history(PRINCIPAL_A, entry)

    with (
        pytest.raises(DBAPIError, match="append only"),
        staged.begin() as connection,
    ):
        connection.execute(
            update(constraint_project_settings_history)
            .where(constraint_project_settings_history.c.history_id == entry.history_id)
            .values(outcome="no_op")
        )

    with (
        pytest.raises(DBAPIError, match="append only"),
        staged.begin() as connection,
    ):
        connection.execute(
            delete(constraint_project_settings_history).where(
                constraint_project_settings_history.c.history_id == entry.history_id
            )
        )


# --- The shared connection -------------------------------------------------


def test_the_unit_of_work_hands_out_projects_on_its_own_connection(staged: Engine) -> None:
    """A Project created but uncommitted in this transaction is visible to `projects`.

    Which is the whole claim: a repository on any other connection would not
    see it, and a `lock_project` taken there would not serialise this one. The
    Project is created through the port's own `add_project` rather than through
    a hand-written statement, so what is proved is the shared transaction and
    not this module's ability to reach a private attribute.
    """
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        created = uow.projects.add_project(
            principal_id=PRINCIPAL_A,
            name="A Synthetic Project",
            description=None,
            participants=(),
        )
        locked = uow.projects.lock_project(PRINCIPAL_A, created.project_id)

        assert locked is not None
        assert locked.project_id == created.project_id
        assert uow.projects.get_project(PRINCIPAL_A, created.project_id) is not None

    with staged.begin() as connection:
        committed = connection.execute(
            select(projects.c.project_id).where(projects.c.project_id == created.project_id)
        ).scalar_one()
    assert committed == created.project_id


def test_a_project_lock_taken_through_the_unit_of_work_is_a_real_row_lock(
    staged: Engine,
) -> None:
    """`uow.projects.lock_project` holds the Project row for this transaction.

    Which is what makes it usable as the ownership-and-serialisation proof a
    configure takes before it touches settings at all.
    """
    other = staged.connect()
    try:
        with SqlAlchemyConstraintManagementUnitOfWork(staged) as holder:
            assert holder.projects.lock_project(PRINCIPAL_A, PROJECT_A) is not None
            with pytest.raises(DBAPIError) as caught:
                other.execute(
                    text(
                        "SELECT 1 FROM knowledge.projects "
                        "WHERE project_id = :identity FOR UPDATE NOWAIT"
                    ),
                    {"identity": PROJECT_A},
                )
            assert "lock" in str(caught.value).lower()
    finally:
        other.close()


def test_the_unit_of_work_refuses_to_hand_out_projects_outside_a_transaction(
    staged: Engine,
) -> None:
    uow = SqlAlchemyConstraintManagementUnitOfWork(staged)

    with pytest.raises(RuntimeError):
        _ = uow.projects


def test_no_index_was_added_to_the_receipt_ledger(staged: Engine) -> None:
    """WP03 deliberately left this table unindexed; nothing here changes that."""
    with staged.begin() as connection:
        names = set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'knowledge' "
                    "AND tablename = 'constraint_project_settings_history'"
                )
            ).scalars()
        )

    assert "constraint_project_settings_history_by_project_time" not in names
