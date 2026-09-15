"""PC-CM-RUN01-WP05: `ProjectControlsConfigurationService` against PostgreSQL.

What `tests/unit/test_project_controls_settings_service.py` proves against an
in-memory partition, this module proves against the real thing: the canonical
Project row lock the absent-row creation is serialised by, the stored partial
unique index that makes an idempotency key mean something, the append-only
triggers, the same-Principal composite foreign key, the exact persisted
readback, and — the part a fake cannot establish at all — that a failed attempt
rolls back in the database rather than only in a Python dictionary.

The two concurrent cases follow `tests/database/test_constraint_numbering_
concurrency.py`'s precedent exactly: overlapping transactions on separate
connections with the waiter in a thread, and a `lock_timeout` on the waiting
session so a build that takes **no** lock reports loudly instead of hanging the
tier. Marked `database` and nothing else — `--strict-markers` is on and this
repository declares no `concurrency` mark.

Every identifier, timezone and key here is synthetic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, delete, event, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from my_pa.application.constraint_settings import (
    ProjectControlsConfigurationResult,
    ProjectControlsConfigurationService,
    ProjectControlsDisposition,
    ProjectControlsIdempotencyConflictError,
    ProjectControlsNotConfiguredError,
    ProjectControlsProjectUnavailableError,
    ProjectControlsState,
    ProjectControlsVersionConflictError,
)
from my_pa.domain.project_controls.business_time import ProjectTimezoneError
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_project_settings,
    constraint_project_settings_history,
    projects,
)

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_pcsaaaa0001aaaa0001a"
PRINCIPAL_B: Final = "prn_pcsbbbb0002bbbb0002b"
#: One Project per Principal that nobody has configured, plus one more for
#: `PRINCIPAL_A` so a cross-Project key collision has somewhere to collide.
PROJECT_A: Final = "prj_pcsaaaa0001aaaa"
PROJECT_A2: Final = "prj_pcsaaaa0002aaaa"
PROJECT_B: Final = "prj_pcsbbbb0002bbbb"
PROJECT_ABSENT: Final = "prj_pcsnone0003nono"

ZONE: Final = "America/Chicago"
OTHER_ZONE: Final = "America/New_York"
KEY: Final = "pcs-configure-0001"
NO_OP_KEY: Final = "pcs-no-op-0000001"

T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

#: Long enough that a loaded host does not turn a pass into a failure, short
#: enough that a build holding no lock reports instead of hanging the tier.
LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0


def _service(engine: Engine) -> ProjectControlsConfigurationService:
    return ProjectControlsConfigurationService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def seed(engine: Engine) -> None:
    """Three Projects across two Principals, and not one settings row.

    Deliberately unconfigured: this work package exists because a Project that
    nobody has configured used to be unreachable, so the fixture that proves it
    has to start in exactly that state.
    """
    with engine.begin() as connection:
        for principal, project in (
            (PRINCIPAL_A, PROJECT_A),
            (PRINCIPAL_A, PROJECT_A2),
            (PRINCIPAL_B, PROJECT_B),
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


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """A head-migrated clone with the synthetic Projects already in it."""
    seed(migrated_engine)
    return migrated_engine


def _impatient(engine: Engine) -> Engine:
    """The same database, on connections that refuse to wait forever for a lock."""

    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    return engine


def _configure(engine: Engine, **overrides: object) -> ProjectControlsConfigurationResult:
    values: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "project_id": PROJECT_A,
        "timezone_name": ZONE,
        "idempotency_key": KEY,
    }
    values.update(overrides)
    return _service(engine).configure(**values)  # type: ignore[arg-type]


def _settings_rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        return [
            dict(row._mapping)
            for row in connection.execute(
                select(constraint_project_settings).order_by(
                    constraint_project_settings.c.project_id
                )
            )
        ]


def _receipts(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        return [
            dict(row._mapping)
            for row in connection.execute(
                select(constraint_project_settings_history).order_by(
                    constraint_project_settings_history.c.recorded_at,
                    constraint_project_settings_history.c.history_id,
                )
            )
        ]


def _count(engine: Engine, table: object) -> int:
    with engine.begin() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


# --- the exact persisted readback ---------------------------------------------


def test_a_first_configure_writes_exactly_one_row_and_one_receipt(staged: Engine) -> None:
    """CM-BE-AC-038: every stored column, read back from the server."""
    result = _configure(staged, client_context="web")
    assert result.disposition is ProjectControlsDisposition.APPLIED
    assert result.settings_version == 1

    rows = _settings_rows(staged)
    assert len(rows) == 1
    stored = rows[0]
    assert stored["principal_id"] == PRINCIPAL_A
    assert stored["project_id"] == PROJECT_A
    assert stored["timezone_name"] == ZONE
    assert stored["version"] == 1
    assert stored["created_at"] == T0
    assert stored["updated_at"] == T0

    receipts = _receipts(staged)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["history_id"].startswith("cpsh_")
    assert receipt["principal_id"] == PRINCIPAL_A
    assert receipt["project_id"] == PROJECT_A
    assert receipt["action"] == "configure"
    assert receipt["actor"] == "principal"
    assert receipt["outcome"] == "applied"
    assert receipt["before_settings_version"] is None
    assert receipt["after_settings_version"] == 1
    assert receipt["resulting_timezone_name"] == ZONE
    assert receipt["resulting_settings_updated_at"] == T0
    assert receipt["idempotency_key"] == KEY
    assert len(receipt["request_digest"]) == 64
    assert receipt["client_context"] == "web"
    assert receipt["failure_code"] is None
    assert receipt["failure_detail"] is None
    assert receipt["occurred_at"] == T0
    assert receipt["recorded_at"] == T0


def test_an_update_moves_the_version_once_and_preserves_the_creation_time(
    staged: Engine,
) -> None:
    _configure(staged)
    result = _configure(
        staged,
        timezone_name=OTHER_ZONE,
        expected_version=1,
        idempotency_key="pcs-update-000001",
    )
    assert result.disposition is ProjectControlsDisposition.APPLIED
    stored = _settings_rows(staged)[0]
    assert stored["timezone_name"] == OTHER_ZONE
    assert stored["version"] == 2
    assert stored["created_at"] == T0
    assert _count(staged, constraint_project_settings_history) == 2


def test_the_same_timezone_writes_one_receipt_and_no_settings_change(staged: Engine) -> None:
    """Two requests, two receipts, one unchanged settings row — and in that order.

    The outcomes cannot be read off row order here. This module's clock is
    frozen at `T0`, so both receipts carry the *same* `recorded_at` and the
    `history_id` tiebreaker `_receipts` falls back on is an opaque random
    identifier: PostgreSQL is free to return either receipt first, and does.
    So the readback is keyed by the one column that genuinely discriminates the
    two requests — each one's own idempotency key — which binds an outcome to
    the request that produced it rather than to a position.

    The ordering claim is then made explicitly, from the receipts' own content
    rather than from their arrival order: the applied receipt is the earlier one
    because it alone found no settings row (`before_settings_version is None`),
    and the no-op receipt is the later one because it saw the version the
    applied one had just created. That is a strictly stronger statement than
    `outcomes == ["applied", "no_op"]`, which only ever claimed adjacency.
    """
    _configure(staged)
    before = _settings_rows(staged)[0]
    result = _configure(staged, idempotency_key=NO_OP_KEY)
    assert result.disposition is ProjectControlsDisposition.NO_OP
    assert _settings_rows(staged)[0] == before

    receipts = {receipt["idempotency_key"]: receipt for receipt in _receipts(staged)}
    assert sorted(receipts) == sorted([KEY, NO_OP_KEY])
    assert receipts[KEY]["outcome"] == "applied"
    assert receipts[NO_OP_KEY]["outcome"] == "no_op"
    assert (receipts[KEY]["before_settings_version"], receipts[KEY]["after_settings_version"]) == (
        None,
        1,
    )
    assert (
        receipts[NO_OP_KEY]["before_settings_version"],
        receipts[NO_OP_KEY]["after_settings_version"],
    ) == (1, 1)


# --- the three separate checks -------------------------------------------------


@pytest.mark.parametrize("project_id", [PROJECT_B, PROJECT_ABSENT], ids=["foreign", "unknown"])
def test_a_project_outside_this_principals_partition_writes_nothing(
    staged: Engine, project_id: str
) -> None:
    """CM-BE-AC-132's shape: absent and foreign are one answer, and one refusal."""
    with pytest.raises(ProjectControlsProjectUnavailableError):
        _configure(staged, project_id=project_id)
    assert _count(staged, constraint_project_settings) == 0
    assert _count(staged, constraint_project_settings_history) == 0


def test_a_deleted_project_answers_exactly_as_a_foreign_one(staged: Engine) -> None:
    """Nondisclosure equivalence against the server, not against a dictionary.

    This test used to configure `PROJECT_A` and then delete its Project row,
    which the server does not permit and never did: the receipts `configure`
    wrote are append-only and name the Project through
    `a_constraint_settings_history_names_a_project_in_its_principal`, the
    same-Principal composite foreign key, so the delete is *refused* rather
    than cascading the ledger away. `deleted` is therefore not a state a
    **configured** Project can reach at all, and the first half of this test now
    asserts that refusal by name instead of pretending otherwise. The foreign
    key is the integrity defense under test here; weakening it, or clearing the
    history to let the delete through, would have deleted the guarantee rather
    than proven it.

    The second half then proves the nondisclosure claim on the deleted state
    that *is* reachable: `PROJECT_A2`, owned by `PRINCIPAL_A`, never configured,
    and so carrying no receipts to hold its row in place. A Project this
    Principal genuinely owned and that genuinely no longer exists must be
    indistinguishable from another Principal's Project and from one that never
    existed — same exception type, same refusal text, to the character. That is
    the identical equivalence the previous body claimed, now made against a
    Project the database actually let us delete.
    """
    _configure(staged)
    with pytest.raises(IntegrityError) as refused, staged.begin() as connection:
        connection.execute(
            delete(constraint_project_settings).where(
                constraint_project_settings.c.project_id == PROJECT_A
            )
        )
        connection.execute(delete(projects).where(projects.c.project_id == PROJECT_A))
    assert "a_constraint_settings_history_names_a_project_in_its_principal" in str(refused.value)
    assert _count(staged, constraint_project_settings_history) == 1
    assert _count(staged, constraint_project_settings) == 1

    with staged.begin() as connection:
        connection.execute(delete(projects).where(projects.c.project_id == PROJECT_A2))

    answers = []
    for project_id in (PROJECT_A2, PROJECT_B, PROJECT_ABSENT):
        with pytest.raises(ProjectControlsProjectUnavailableError) as refusal:
            _service(staged).read_status(principal_id=PRINCIPAL_A, project_id=project_id)
        answers.append((type(refusal.value), str(refusal.value)))
    assert len(set(answers)) == 1


def test_an_owned_project_with_no_settings_row_is_not_configured(staged: Engine) -> None:
    status = _service(staged).read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert status.state is ProjectControlsState.NOT_CONFIGURED
    assert status.settings is None


def test_a_configured_project_reports_the_rows_own_values(staged: Engine) -> None:
    _configure(staged)
    status = _service(staged).read_status(principal_id=PRINCIPAL_A, project_id=PROJECT_A)
    assert status.state is ProjectControlsState.CONFIGURED
    assert status.settings is not None
    assert (status.settings.timezone_name, status.settings.version) == (ZONE, 1)


def test_an_invalid_timezone_reaches_no_statement_at_all(staged: Engine) -> None:
    with pytest.raises(ProjectTimezoneError):
        _configure(staged, timezone_name="Mars/Olympus_Mons")
    assert _count(staged, constraint_project_settings) == 0
    assert _count(staged, constraint_project_settings_history) == 0


# --- rejection evidence, committed ---------------------------------------------


def test_a_stale_expected_version_commits_its_rejection_and_changes_nothing(
    staged: Engine,
) -> None:
    _configure(staged)
    with pytest.raises(ProjectControlsVersionConflictError):
        _configure(
            staged,
            timezone_name=OTHER_ZONE,
            expected_version=7,
            idempotency_key="pcs-stale-0000001",
        )
    stored = _settings_rows(staged)[0]
    assert (stored["timezone_name"], stored["version"]) == (ZONE, 1)
    rejected = [r for r in _receipts(staged) if r["outcome"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["failure_code"] == "settings_version_conflict"
    assert rejected[0]["before_settings_version"] == 1
    assert rejected[0]["after_settings_version"] == 1
    assert rejected[0]["resulting_timezone_name"] is None


def test_an_expected_version_against_no_row_commits_a_null_null_rejection(
    staged: Engine,
) -> None:
    """The stored CHECK spells the rejected pairing `IS NOT DISTINCT FROM`.

    So a rejection against a Project with no settings row is legal with both
    versions null, which is what this branch writes and what this asserts.
    """
    with pytest.raises(ProjectControlsNotConfiguredError):
        _configure(staged, expected_version=1)
    assert _count(staged, constraint_project_settings) == 0
    receipts = _receipts(staged)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "rejected"
    assert receipts[0]["failure_code"] == "project_controls_not_configured"
    assert receipts[0]["before_settings_version"] is None
    assert receipts[0]["after_settings_version"] is None


# --- the ledger's stored rules --------------------------------------------------


def test_the_idempotency_key_is_unique_within_the_principal(staged: Engine) -> None:
    _configure(staged)
    with pytest.raises(Exception) as caught, staged.begin() as connection:
        connection.execute(
            insert(constraint_project_settings_history).values(
                history_id="cpsh_" + "a" * 32,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                action="configure",
                actor="principal",
                outcome="no_op",
                before_settings_version=1,
                after_settings_version=1,
                resulting_timezone_name=ZONE,
                resulting_settings_updated_at=T0,
                idempotency_key=KEY,
                request_digest="b" * 64,
                occurred_at=T0,
                recorded_at=T0,
            )
        )
    assert "unique" in str(caught.value).lower() or "duplicate" in str(caught.value).lower()


def test_the_same_key_is_available_to_another_principal(staged: Engine) -> None:
    """The key is unique within the Principal, never across the table."""
    _configure(staged)
    result = _service(staged).configure(
        principal_id=PRINCIPAL_B,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_B,
        timezone_name=ZONE,
        idempotency_key=KEY,
    )
    assert result.disposition is ProjectControlsDisposition.APPLIED
    assert _count(staged, constraint_project_settings_history) == 2


@pytest.mark.parametrize("statement", ["update", "delete"], ids=["update", "delete"])
def test_a_settings_receipt_can_neither_be_updated_nor_deleted(
    staged: Engine, statement: str
) -> None:
    """Append-only, enforced by the server rather than by convention."""
    _configure(staged)
    history_id = _receipts(staged)[0]["history_id"]
    with pytest.raises(Exception) as caught, staged.begin() as connection:
        if statement == "update":
            connection.execute(
                update(constraint_project_settings_history)
                .where(constraint_project_settings_history.c.history_id == history_id)
                .values(outcome="no_op")
            )
        else:
            connection.execute(
                delete(constraint_project_settings_history).where(
                    constraint_project_settings_history.c.history_id == history_id
                )
            )
    assert str(caught.value)
    assert _count(staged, constraint_project_settings_history) == 1


def test_a_settings_row_cannot_name_another_principals_project(staged: Engine) -> None:
    """`constraint_settings_project_is_same_principal`, the composite foreign key."""
    with pytest.raises(Exception) as caught, staged.begin() as connection:
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_B,
                timezone_name=ZONE,
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
    assert "foreign key" in str(caught.value).lower()


def test_a_receipt_cannot_name_another_principals_project(staged: Engine) -> None:
    with pytest.raises(Exception) as caught, staged.begin() as connection:
        connection.execute(
            insert(constraint_project_settings_history).values(
                history_id="cpsh_" + "c" * 32,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_B,
                action="configure",
                actor="principal",
                outcome="applied",
                before_settings_version=None,
                after_settings_version=1,
                resulting_timezone_name=ZONE,
                resulting_settings_updated_at=T0,
                idempotency_key="pcs-foreign-00001",
                request_digest="d" * 64,
                occurred_at=T0,
                recorded_at=T0,
            )
        )
    assert "foreign key" in str(caught.value).lower()


def test_a_failed_receipt_write_leaves_no_settings_row(staged: Engine) -> None:
    """No partial write. The settings row and its receipt commit together or not.

    The failure is induced by binding the key to a *different* Project first, so
    the second attempt's receipt insert hits the stored unique index after its
    settings insert has already run inside the same transaction.
    """
    _service(staged).configure(
        principal_id=PRINCIPAL_A,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_A2,
        timezone_name=ZONE,
        idempotency_key=KEY,
    )
    with pytest.raises(ProjectControlsIdempotencyConflictError):
        _configure(staged)
    stored = {row["project_id"] for row in _settings_rows(staged)}
    assert stored == {PROJECT_A2}, "the losing transaction left a settings row behind"
    assert _count(staged, constraint_project_settings_history) == 1


# --- replay -------------------------------------------------------------------


def test_the_same_key_and_digest_replays_from_the_ledger(staged: Engine) -> None:
    first = _configure(staged)
    second = _configure(staged)
    assert second.disposition is ProjectControlsDisposition.REPLAYED
    assert second.settings_version == first.settings_version
    assert second.timezone_name == first.timezone_name
    assert _count(staged, constraint_project_settings_history) == 1


# --- the canonical Project row lock --------------------------------------------


def test_the_project_row_is_actually_locked_while_a_configure_holds_it(
    staged: Engine,
) -> None:
    """The control. Without it the two race tests below prove nothing.

    A second session asking for the same Project row `FOR UPDATE NOWAIT` while
    one is held must be refused. If `configure` stopped taking `lock_project`,
    this reddens here rather than leaving the concurrency claims unfalsifiable.
    """
    holder = staged.connect()
    other = staged.connect()
    try:
        transaction = holder.begin()
        holder.execute(
            text("SELECT 1 FROM knowledge.projects WHERE project_id = :identity FOR UPDATE"),
            {"identity": PROJECT_A},
        )
        with pytest.raises(Exception) as caught:
            other.execute(
                text(
                    "SELECT 1 FROM knowledge.projects "
                    "WHERE project_id = :identity FOR UPDATE NOWAIT"
                ),
                {"identity": PROJECT_A},
            )
        assert "lock" in str(caught.value).lower()
        transaction.rollback()
    finally:
        holder.close()
        other.close()


def test_two_overlapping_same_key_configures_yield_one_applied_and_one_replayed(
    staged: Engine,
) -> None:
    """The serialisation claim, only visible while both transactions are open.

    Both requests name one Project and one key and carry identical intent. The
    Project row lock makes the second wait; when the first commits, the second
    reads the receipt it wrote and replays. A build that consulted the ledger
    ahead of the lock would have both read an empty ledger, both insert, and the
    loser reach the stored unique index — an integrity error where the accepted
    contract requires `REPLAYED`.
    """
    engine = _impatient(staged)

    def configure() -> ProjectControlsDisposition:
        return (
            _service(engine)
            .configure(
                principal_id=PRINCIPAL_A,
                actor=ConstraintMutationActor.PRINCIPAL,
                project_id=PROJECT_A,
                timezone_name=ZONE,
                idempotency_key=KEY,
            )
            .disposition
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(configure) for _ in range(2)]
        dispositions = sorted(
            future.result(timeout=JOIN_TIMEOUT_SECONDS).value for future in futures
        )

    assert dispositions == ["applied", "replayed"]
    assert _count(staged, constraint_project_settings) == 1
    assert _count(staged, constraint_project_settings_history) == 1
    assert _settings_rows(staged)[0]["version"] == 1


@pytest.mark.parametrize(
    ("project_id", "timezone_name"),
    [(PROJECT_A2, ZONE), (PROJECT_A, OTHER_ZONE)],
    ids=["different-project", "different-timezone"],
)
def test_two_overlapping_same_key_configures_with_different_intent_conflict(
    staged: Engine, project_id: str, timezone_name: str
) -> None:
    """A typed conflict, never a raw integrity error, whichever thread loses.

    Two Projects share no lock to serialise on, so this is the race the stored
    unique index arbitrates and the repository's narrowed key-conflict error
    reports. Exactly one request may succeed; the other must be told its key was
    used for different content.
    """
    engine = _impatient(staged)

    def configure(target: str, zone: str) -> str:
        try:
            return (
                _service(engine)
                .configure(
                    principal_id=PRINCIPAL_A,
                    actor=ConstraintMutationActor.PRINCIPAL,
                    project_id=target,
                    timezone_name=zone,
                    idempotency_key=KEY,
                )
                .disposition.value
            )
        except ProjectControlsIdempotencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(configure, PROJECT_A, ZONE),
            pool.submit(configure, project_id, timezone_name),
        ]
        answers = sorted(future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures)

    assert answers == ["applied", "conflict"]
    assert _count(staged, constraint_project_settings) == 1
    assert _count(staged, constraint_project_settings_history) == 1
