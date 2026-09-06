"""PC-CM-IMP-WP02 §H.5: the Constraint persistence adapter, against a live server.

The `database` tier, on a disposable head-migrated clone. What these tests are
for is the seam itself: that a record written through
`SqlConstraintManagementRepository` comes back as the same domain value, that a
second Principal's read of it is answered identically to absent, that the row
lock really locks, and that the unit of work owns the transaction.

Every identifier, code, and label here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError

from my_pa.contracts.ports import ConstraintManagementRepository
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintCategoryHistoryEntry,
    ConstraintCategoryMutationOperation,
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.tables import (
    project_constraint_parties,
    project_constraints,
    projects,
)

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_adapteraaaa0001aaaa01"
PRINCIPAL_B: Final = "prn_adapterbbbb0002bbbb02"
PROJECT_A: Final = "prj_adapteraaaa0001aaaa"
PROJECT_B: Final = "prj_adapterbbbb0002bbbb"
CATEGORY_A: Final = "ccat_adapteraaaa0001aaa"
CONSTRAINT_A: Final = "cst_adapteraaaa0001aaaa"
REVISION_A: Final = "crev_adapteraaaa0001aaa"
HISTORY_A: Final = "chst_adapteraaaa0001aaa"
CATEGORY_HISTORY_A: Final = "cchst_adapteraaaa0001a"
ENTITY_ONE: Final = "ent_adapteraaaa0001aaaa"
ENTITY_TWO: Final = "ent_adapterbbbb0002bbbb"
DIGEST: Final = "b" * 64
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T1: Final = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _seed_project(connection: Connection, principal: str, project: str) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name="Sample Project",
            state="active",
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )


def _category(**overrides: object) -> ConstraintCategory:
    values: dict[str, Any] = {
        "category_id": CATEGORY_A,
        "principal_id": PRINCIPAL_A,
        "project_id": PROJECT_A,
        "prefix": "DES",
        "title": "Design",
        "state": ConstraintCategoryState.ACTIVE,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return ConstraintCategory(**values)


def _settings(**overrides: object) -> ConstraintProjectSettings:
    values: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "project_id": PROJECT_A,
        "timezone_name": "America/New_York",
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return ConstraintProjectSettings(**values)


def _draft(**overrides: object) -> ProjectConstraint:
    values: dict[str, Any] = {
        "constraint_id": CONSTRAINT_A,
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.DRAFT,
        "origin": ConstraintOrigin.PRODUCT,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _published(**overrides: object) -> ProjectConstraint:
    values: dict[str, Any] = {
        "constraint_id": CONSTRAINT_A,
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "project_id": PROJECT_A,
        "category_id": CATEGORY_A,
        "constraint_code": "1.10",
        "description": "Long-lead switchgear submittal outstanding",
        "date_identified": date(2026, 8, 3),
        "due_date": date(2026, 9, 30),
        "reference": "RFI-114",
        "current_update": "Vendor confirmed a ship date",
        "bic": (
            PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_ONE, label="Sample Vendor"),
            PartyRef(kind=PartyKind.UNRESOLVED, label="the switchgear rep"),
        ),
        "responsible": (PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_TWO),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _history(**overrides: object) -> ConstraintHistoryEntry:
    values: dict[str, Any] = {
        "history_id": HISTORY_A,
        "principal_id": PRINCIPAL_A,
        "constraint_id": CONSTRAINT_A,
        "operation": ConstraintMutationOperation.PUBLISH,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "outcome": ConstraintMutationOutcome.NO_OP,
        "before_version": 1,
        "after_version": 1,
        "occurred_at": T0,
        "recorded_at": T0,
        "project_id": PROJECT_A,
    }
    values.update(overrides)
    return ConstraintHistoryEntry(**values)


def _repository(connection: Connection) -> ConstraintManagementRepository:
    return SqlConstraintManagementRepository(connection)


def _seed_all(connection: Connection) -> ConstraintManagementRepository:
    """Both Principals' Projects, plus A's Category and one receipt to hang rows on."""
    _seed_project(connection, PRINCIPAL_A, PROJECT_A)
    _seed_project(connection, PRINCIPAL_B, PROJECT_B)
    repository = _repository(connection)
    repository.insert_category(PRINCIPAL_A, _category())
    return repository


# --- Roundtrips --------------------------------------------------------------


def test_project_settings_roundtrip(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection, PRINCIPAL_A, PROJECT_A)
        repository = _repository(connection)
        repository.insert_project_settings(PRINCIPAL_A, _settings())
        assert repository.get_project_settings(PRINCIPAL_A, PROJECT_A) == _settings()
        repository.update_project_settings(
            PRINCIPAL_A, _settings(timezone_name="America/Chicago", version=2, updated_at=T1)
        )
        stored = repository.get_project_settings(PRINCIPAL_A, PROJECT_A)
        assert stored is not None
        assert stored.timezone_name == "America/Chicago"
        assert stored.version == 2
        assert stored.updated_at == T1


def test_category_roundtrip_keeps_its_allocator_columns(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection, PRINCIPAL_A, PROJECT_A)
        repository = _repository(connection)
        repository.insert_category(PRINCIPAL_A, _category())
        assert repository.get_category(PRINCIPAL_A, CATEGORY_A) == _category()
        repository.update_category(
            PRINCIPAL_A,
            _category(title="Design and Engineering", updated_at=T1, prefix_locked_at=T0),
            next_sequence=4,
            issued_count=3,
            version=2,
        )
        stored = repository.get_category(PRINCIPAL_A, CATEGORY_A)
        assert stored is not None
        assert stored.title == "Design and Engineering"
        assert stored.is_prefix_locked
        allocator = connection.execute(
            text(
                "SELECT next_sequence, issued_count, version FROM knowledge.constraint_categories"
                " WHERE category_id = :id"
            ),
            {"id": CATEGORY_A},
        ).one()
        assert tuple(allocator) == (4, 3, 2)


def test_a_draft_constraint_roundtrips_with_its_absences(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _draft())
        stored = repository.get(PRINCIPAL_A, CONSTRAINT_A)
        assert stored == _draft()
        assert stored is not None
        assert stored.project_id is None
        assert stored.constraint_code is None
        assert stored.bic == ()


def test_a_published_constraint_roundtrips_with_its_parties_in_order(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-028/063: `1.10` byte-exact, two BIC and one Responsible in order."""
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        stored = repository.get(PRINCIPAL_A, CONSTRAINT_A)
        assert stored == _published()
        assert stored is not None
        assert stored.constraint_code == "1.10"
        assert len(stored.bic) == 2
        assert stored.bic[0].entity_id == ENTITY_ONE
        assert stored.bic[1].kind is PartyKind.UNRESOLVED
        assert stored.bic[1].label == "the switchgear rep"
        assert stored.responsible == (PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_TWO),)


def test_updating_a_constraint_replaces_its_party_rows(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        revised = _published(
            version=3,
            updated_at=T1,
            bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
            responsible=(),
        )
        repository.update_constraint(PRINCIPAL_A, revised)
        stored = repository.get(PRINCIPAL_A, CONSTRAINT_A)
        assert stored == revised
        assert (
            len(connection.execute(select(project_constraint_parties.c.party_assignment_id)).all())
            == 1
        )


@pytest.mark.parametrize("state", ["closed", "void"])
def test_a_terminal_constraint_roundtrips(migrated_engine: Engine, state: str) -> None:
    terminal = (
        _published(
            version=3,
            lifecycle_state=ConstraintLifecycleState.CLOSED,
            completion_date=date(2026, 9, 20),
            closure_commentary="Submittal received",
        )
        if state == "closed"
        else _published(
            version=3,
            lifecycle_state=ConstraintLifecycleState.VOID,
            voided_date=date(2026, 9, 20),
            void_reason="Duplicated by 1.11",
        )
    )
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.update_constraint(PRINCIPAL_A, terminal)
        assert repository.get(PRINCIPAL_A, CONSTRAINT_A) == terminal


def test_a_revision_and_its_party_snapshot_roundtrip(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.insert_history(PRINCIPAL_A, _history())
        revision = ConstraintRevision.from_constraint(
            _published(), revision_id=REVISION_A, history_id=HISTORY_A, recorded_at=T1
        )
        repository.insert_revision(PRINCIPAL_A, revision)
        assert repository.get_revision(PRINCIPAL_A, CONSTRAINT_A, 2) == revision
        assert repository.get_revision(PRINCIPAL_A, CONSTRAINT_A, 99) is None


def test_the_current_revision_link_is_set_only_when_it_is_given(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.insert_history(PRINCIPAL_A, _history())
        repository.insert_revision(
            PRINCIPAL_A,
            ConstraintRevision.from_constraint(
                _published(), revision_id=REVISION_A, history_id=HISTORY_A, recorded_at=T1
            ),
        )
        repository.update_constraint(
            PRINCIPAL_A, _published(version=3, updated_at=T1), current_revision_id=REVISION_A
        )
        linked = connection.execute(
            select(project_constraints.c.current_revision_id).where(
                project_constraints.c.constraint_id == CONSTRAINT_A
            )
        ).scalar_one()
        assert linked == REVISION_A
        repository.update_constraint(PRINCIPAL_A, _published(version=4, updated_at=T1))
        assert (
            connection.execute(
                select(project_constraints.c.current_revision_id).where(
                    project_constraints.c.constraint_id == CONSTRAINT_A
                )
            ).scalar_one()
            == REVISION_A
        )


def test_a_receipt_roundtrips_every_safe_field(migrated_engine: Engine) -> None:
    entry = _history(
        outcome=ConstraintMutationOutcome.REJECTED,
        safe_failure_reason="version_conflict",
        idempotency_key="synthetic-adapter-key-01",
        request_digest=DIGEST,
        client_context="cli",
        correlation_id="corr_adapteraaaa0001aaa",
    )
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.insert_history(PRINCIPAL_A, entry)
        found = repository.find_history_by_idempotency_key(PRINCIPAL_A, "synthetic-adapter-key-01")
        assert found == entry
        assert repository.find_history_by_idempotency_key(PRINCIPAL_A, "no-such-key-0001") is None


def test_a_category_receipt_roundtrips(migrated_engine: Engine) -> None:
    entry = ConstraintCategoryHistoryEntry(
        history_id=CATEGORY_HISTORY_A,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        category_id=CATEGORY_A,
        operation=ConstraintCategoryMutationOperation.CREATE,
        actor=ConstraintMutationActor.ASSISTANT,
        outcome=ConstraintMutationOutcome.APPLIED,
        before_version=0,
        after_version=1,
        occurred_at=T0,
        recorded_at=T0,
        idempotency_key="synthetic-category-key-1",
    )
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_category_history(PRINCIPAL_A, entry)
        stored = connection.execute(
            text(
                "SELECT principal_id, operation, idempotency_key"
                " FROM knowledge.constraint_category_history WHERE history_id = :id"
            ),
            {"id": CATEGORY_HISTORY_A},
        ).one()
        assert stored.principal_id == PRINCIPAL_A
        assert stored.operation == "create"
        assert stored.idempotency_key == "synthetic-category-key-1"


# --- Partition isolation -----------------------------------------------------


def test_a_foreign_principal_is_answered_identically_to_absent(migrated_engine: Engine) -> None:
    """CM-BE-AC-132: `None`, never a refusal that discloses the record exists."""
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.insert_history(PRINCIPAL_A, _history(idempotency_key="synthetic-adapter-key-01"))
        repository.insert_project_settings(PRINCIPAL_A, _settings())
        repository.insert_revision(
            PRINCIPAL_A,
            ConstraintRevision.from_constraint(
                _published(), revision_id=REVISION_A, history_id=HISTORY_A, recorded_at=T1
            ),
        )

        assert repository.get(PRINCIPAL_A, CONSTRAINT_A) is not None
        assert repository.get(PRINCIPAL_B, CONSTRAINT_A) is None
        assert repository.get_for_update(PRINCIPAL_B, CONSTRAINT_A) is None
        assert repository.get_category(PRINCIPAL_B, CATEGORY_A) is None
        assert repository.get_category_for_update(PRINCIPAL_B, CATEGORY_A) is None
        assert repository.get_project_settings(PRINCIPAL_B, PROJECT_A) is None
        assert repository.get_revision(PRINCIPAL_B, CONSTRAINT_A, 2) is None
        assert (
            repository.find_history_by_idempotency_key(PRINCIPAL_B, "synthetic-adapter-key-01")
            is None
        )
        assert repository.get(PRINCIPAL_A, "cst_adapternever0001nev") is None


def test_a_constraint_cannot_borrow_another_principal_s_category(
    migrated_engine: Engine,
) -> None:
    """The composite same-Principal foreign key, reached through the seam."""
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            repository.insert_constraint(PRINCIPAL_B, _published(project_id=PROJECT_B))


def test_a_wrong_project_binding_is_not_silently_re_homed(migrated_engine: Engine) -> None:
    """A row naming another Principal's Project stays in the writer's own partition.

    `projects` carries no `(principal_id, project_id)` uniqueness for a composite
    foreign key to reach, so what holds here is the partition: the row is stamped
    with the authenticated Principal, keeps the `project_id` it was given rather
    than being re-pointed at one of theirs, and is invisible to the Project's own
    owner. Refusing the cross-Principal Project reference itself is the
    application boundary's (WP06), which resolves the Project before it writes.
    """
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_category(
            PRINCIPAL_B, _category(category_id="ccat_adapterbbbb0002bbb", project_id=PROJECT_B)
        )
        borrowed = _published(
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_A,
            category_id="ccat_adapterbbbb0002bbb",
        )
        repository.insert_constraint(PRINCIPAL_B, borrowed)
        assert repository.get(PRINCIPAL_A, CONSTRAINT_A) is None
        stored = repository.get(PRINCIPAL_B, CONSTRAINT_A)
        assert stored is not None
        assert stored.principal_id == PRINCIPAL_B
        assert stored.project_id == PROJECT_A


def test_a_write_is_stamped_with_the_authenticated_principal(migrated_engine: Engine) -> None:
    """The payload's own `principal_id` never chooses the partition it lands in."""
    with migrated_engine.begin() as connection:
        _seed_project(connection, PRINCIPAL_A, PROJECT_A)
        _seed_project(connection, PRINCIPAL_B, PROJECT_B)
        repository = _repository(connection)
        repository.insert_category(PRINCIPAL_B, _category(principal_id=PRINCIPAL_A))
        assert repository.get_category(PRINCIPAL_A, CATEGORY_A) is None
        stored = repository.get_category(PRINCIPAL_B, CATEGORY_A)
        assert stored is not None
        assert stored.principal_id == PRINCIPAL_B


# --- Locking, transactions, and integrity -----------------------------------


def test_get_for_update_blocks_a_second_lock_on_another_connection(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-060's substrate: the lock primitive really locks."""
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        _repository(connection).insert_constraint(PRINCIPAL_A, _published())

    holder = migrated_engine.connect()
    contender = migrated_engine.connect()
    try:
        holder.begin()
        assert _repository(holder).get_for_update(PRINCIPAL_A, CONSTRAINT_A) is not None
        contender.begin()
        with pytest.raises(OperationalError):
            contender.execute(
                text(
                    "SELECT constraint_id FROM knowledge.project_constraints"
                    " WHERE constraint_id = :id FOR UPDATE NOWAIT"
                ),
                {"id": CONSTRAINT_A},
            )
    finally:
        contender.close()
        holder.close()


def test_the_unit_of_work_rolls_back_and_leaves_nothing_behind(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)

    class _DeliberateError(RuntimeError):
        pass

    with (
        pytest.raises(_DeliberateError),
        SqlAlchemyConstraintManagementUnitOfWork(migrated_engine) as unit,
    ):
        unit.constraints.insert_constraint(PRINCIPAL_A, _published())
        unit.constraints.insert_history(PRINCIPAL_A, _history())
        raise _DeliberateError

    with migrated_engine.connect() as connection:
        assert connection.execute(select(project_constraints.c.constraint_id)).all() == []
        assert connection.execute(select(project_constraint_parties.c.role)).all() == []


def test_the_unit_of_work_commits_what_its_block_wrote(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_all(connection)
    with SqlAlchemyConstraintManagementUnitOfWork(migrated_engine) as unit:
        unit.constraints.insert_constraint(PRINCIPAL_A, _published())
    with SqlAlchemyConstraintManagementUnitOfWork(migrated_engine) as unit:
        assert unit.constraints.get(PRINCIPAL_A, CONSTRAINT_A) == _published()


def test_a_repository_outside_a_transaction_is_refused(migrated_engine: Engine) -> None:
    unit = SqlAlchemyConstraintManagementUnitOfWork(migrated_engine)
    with pytest.raises(RuntimeError):
        _ = unit.constraints


def test_a_duplicate_idempotency_key_raises_through_the_adapter(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-072: the partial unique index, reached through the seam."""
    with migrated_engine.begin() as connection:
        _seed_all(connection)
        repository = _repository(connection)
        repository.insert_constraint(PRINCIPAL_A, _published())
        repository.insert_history(PRINCIPAL_A, _history(idempotency_key="synthetic-adapter-key-01"))
        with pytest.raises(IntegrityError), connection.begin_nested():
            repository.insert_history(
                PRINCIPAL_A,
                _history(
                    history_id="chst_adapterbbbb0002bbb",
                    idempotency_key="synthetic-adapter-key-01",
                ),
            )
        repository.insert_history(PRINCIPAL_A, _history(history_id="chst_adapterbbbb0002bbb"))
