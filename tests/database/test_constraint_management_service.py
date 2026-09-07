"""PC-CM-IMP-WP06: the mutation plane against a live PostgreSQL server.

The `database` tier, on a disposable head-migrated clone. What
`tests/unit/test_constraint_management_service.py` proves against an in-memory
partition, this module proves against the real thing: the stored CHECKs and
unique indexes, the deferred revision/receipt cycle, the row locks the
optimistic version check depends on, and — the part a fake cannot establish at
all — that a failed operation rolls back in the database rather than only in a
Python dictionary.

Every identifier, prefix, label, code and date here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.sql import ColumnElement, FromClause

from my_pa.application.constraint_management import (
    ConstraintIdempotencyConflictError,
    ConstraintManagementService,
    ConstraintMutationDisposition,
    ConstraintNotFoundError,
    ConstraintOperationError,
    ConstraintPartyError,
    ConstraintProjectUnavailableError,
    ConstraintVersionConflictError,
)
from my_pa.domain.project_controls.category import ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleError,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintPublishError,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_category_history,
    entities,
    project_constraint_history,
    project_constraint_relationships,
    project_constraint_revisions,
    project_constraints,
    projects,
)

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_svcaaaa0001aaaa0001aa"
PRINCIPAL_B: Final = "prn_svcbbbb0002bbbb0002bb"
PROJECT_A: Final = "prj_svcaaaa0001aaaa"
PROJECT_B: Final = "prj_svcbbbb0002bbbb"
ENTITY_MINE: Final = "ent_svcaaaa0001aaaa"
ENTITY_THEIRS: Final = "ent_svcbbbb0002bbbb"
ZONE: Final = "America/Chicago"

#: 15:00 UTC on Wednesday 2 September 2026 — still 2 September in Chicago.
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

PRINCIPAL_PARTY: Final = PartyRef(kind=PartyKind.PRINCIPAL)
ENTITY_PARTY: Final = PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_MINE)
UNRESOLVED_PARTY: Final = PartyRef(kind=PartyKind.UNRESOLVED, label="whoever signs the RFI")


def _service(engine: Engine) -> ConstraintManagementService:
    return ConstraintManagementService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def seed(engine: Engine) -> None:
    """Two Principals, two Projects, two Entities, and one calendar each."""
    with engine.begin() as connection:
        for principal, project, entity in (
            (PRINCIPAL_A, PROJECT_A, ENTITY_MINE),
            (PRINCIPAL_B, PROJECT_B, ENTITY_THEIRS),
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
            connection.execute(
                insert(entities).values(
                    entity_id=entity,
                    principal_id=principal,
                    entity_type="organization",
                    canonical_name="a synthetic vendor",
                    display_name="A Synthetic Vendor",
                    status="active",
                    created_at=T0,
                    updated_at=T0,
                    version=1,
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


def _category(engine: Engine, *, prefix: str = "DES", principal: str = PRINCIPAL_A) -> str:
    project = PROJECT_A if principal == PRINCIPAL_A else PROJECT_B
    return (
        _service(engine)
        .create_category(
            principal_id=principal,
            project_id=project,
            prefix=prefix,
            title=f"{prefix} category",
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record.category_id
    )


def _draft(engine: Engine, category_id: str, **overrides: object) -> ProjectConstraint:
    values: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "project_id": PROJECT_A,
        "category_id": category_id,
        "description": "The permit set is not stamped.",
        "date_identified": date(2026, 9, 2),
        "bic": (PRINCIPAL_PARTY,),
    }
    values.update(overrides)
    return _service(engine).create_draft(**values).record


def _published(engine: Engine, category_id: str, **overrides: object) -> ProjectConstraint:
    draft = _draft(engine, category_id, **overrides)
    return (
        _service(engine)
        .publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record
    )


def _count(engine: Engine, table: FromClause, *where: ColumnElement[bool]) -> int:
    """How many rows the named table holds, optionally narrowed."""
    with engine.begin() as connection:
        return int(
            connection.execute(select(func.count()).select_from(table).where(*where)).scalar_one()
        )


# --- Draft and Publish -------------------------------------------------------


def test_a_draft_is_stored_with_no_public_code_and_the_allocator_untouched(
    staged: Engine,
) -> None:
    """CM-BE-AC-005/026, against the stored CHECKs that restate them."""
    category_id = _category(staged)
    draft = _draft(staged, category_id)
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == draft.constraint_id
            )
        ).one()
        allocator = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
    assert row._mapping["constraint_code"] is None
    assert row._mapping["published_at"] is None
    assert row._mapping["version"] == 1
    assert row._mapping["principal_id"] == PRINCIPAL_A
    assert row._mapping["record_quality"] == ConstraintRecordQuality.NORMAL.value
    assert row._mapping["origin"] == ConstraintOrigin.PRODUCT.value
    assert (allocator._mapping["next_sequence"], allocator._mapping["issued_count"]) == (1, 0)
    assert allocator._mapping["prefix_locked_at"] is None


def test_publish_writes_the_record_its_revision_and_its_receipt_together(
    staged: Engine,
) -> None:
    """CM-BE-AC-024/062/063/064, with the deferred revision cycle satisfied."""
    category_id = _category(staged)
    draft = _draft(
        staged, category_id, bic=(PRINCIPAL_PARTY, ENTITY_PARTY), responsible=(UNRESOLVED_PARTY,)
    )
    result = _service(staged).publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert result.record.constraint_code == "DES.01"
    assert result.record.version == 2
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == draft.constraint_id
            )
        ).one()
        allocator = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
    assert row._mapping["constraint_code"] == "DES.01"
    assert row._mapping["current_revision_id"] == result.receipt.revision_id
    assert (allocator._mapping["next_sequence"], allocator._mapping["issued_count"]) == (2, 1)
    assert allocator._mapping["prefix_locked_at"] is not None

    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        revision = uow.constraints.get_revision(PRINCIPAL_A, draft.constraint_id, 2)
    assert revision is not None
    assert revision.constraint_code == "DES.01"
    assert revision.bic == (PRINCIPAL_PARTY, ENTITY_PARTY)
    assert revision.responsible == (UNRESOLVED_PARTY,)
    assert revision.history_id == result.receipt.history_id


def test_publish_defaults_both_project_dates_from_the_project_calendar(
    staged: Engine,
) -> None:
    """CM-BE-AC-044 consumed: `projectToday` and `+10` business days."""
    category_id = _category(staged)
    draft = _draft(staged, category_id, date_identified=None)
    published = (
        _service(staged)
        .publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record
    )
    assert published.date_identified == date(2026, 9, 2)
    assert published.due_date == date(2026, 9, 16)


def test_a_refused_publish_leaves_no_trace_in_the_database(staged: Engine) -> None:
    """Atomicity: the transaction rolls back, so the allocator never advanced."""
    category_id = _category(staged)
    draft = _draft(staged, category_id, bic=())
    with pytest.raises(ConstraintPublishError):
        _service(staged).publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    with staged.begin() as connection:
        allocator = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == draft.constraint_id
            )
        ).one()
    assert (allocator._mapping["next_sequence"], allocator._mapping["issued_count"]) == (1, 0)
    assert row._mapping["version"] == 1
    assert row._mapping["constraint_code"] is None
    assert _count(staged, project_constraint_revisions) == 1


def test_publish_refuses_a_category_from_another_project_and_another_principal(
    staged: Engine,
) -> None:
    """CM-BE-AC-132 consumed: the foreign Category is answered as an absent one."""
    theirs = _category(staged, prefix="THR", principal=PRINCIPAL_B)
    with pytest.raises(Exception) as caught:
        _draft(staged, theirs)
    assert "category" in str(caught.value).lower()
    assert _count(staged, project_constraints) == 0


# --- Numbering ---------------------------------------------------------------


def test_the_public_code_is_exact_text_at_every_width(staged: Engine) -> None:
    """CM-BE-AC-027/028, read back out of a `text` column."""
    category_id = _category(staged, prefix="2")
    codes = [_published(staged, category_id).constraint_code for _ in range(10)]
    assert codes[0] == "2.01"
    assert codes[8] == "2.09"
    assert codes[9] == "2.10"
    with staged.begin() as connection:
        stored = sorted(
            connection.execute(
                select(project_constraints.c.constraint_code).where(
                    project_constraints.c.constraint_code.is_not(None)
                )
            )
            .scalars()
            .all()
        )
    assert "2.10" in stored
    assert "2.1" not in stored


def test_two_categories_number_independently(staged: Engine) -> None:
    first = _category(staged, prefix="DES")
    second = _category(staged, prefix="PRO")
    assert _published(staged, first).constraint_code == "DES.01"
    assert _published(staged, second).constraint_code == "PRO.01"
    assert _published(staged, first).constraint_code == "DES.02"


# --- Version and idempotency -------------------------------------------------


def test_a_stale_version_commits_its_rejection_and_nothing_else(staged: Engine) -> None:
    """CM-BE-AC-059/060/061: the REJECTED receipt survives the refusal."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    with pytest.raises(ConstraintVersionConflictError) as caught:
        _service(staged).update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version - 1,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "RFI-014"},
        )
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == published.constraint_id
            )
        ).one()
        receipt = connection.execute(
            select(project_constraint_history).where(
                project_constraint_history.c.history_id == caught.value.receipt.history_id
            )
        ).one()
    assert row._mapping["version"] == published.version
    assert row._mapping["reference"] is None
    assert receipt._mapping["outcome"] == ConstraintMutationOutcome.REJECTED.value
    assert receipt._mapping["safe_failure_reason"] == "version_conflict"
    assert receipt._mapping["revision_id"] is None


def test_a_no_op_writes_a_receipt_and_no_revision(staged: Engine) -> None:
    """CM-BE-AC-059, second half."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    before = _count(staged, project_constraint_revisions)
    same = _service(staged).transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        target_state=published.lifecycle_state,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert same.disposition is ConstraintMutationDisposition.NO_OP
    assert _count(staged, project_constraint_revisions) == before
    assert (
        _count(
            staged,
            project_constraint_history,
            project_constraint_history.c.outcome == ConstraintMutationOutcome.NO_OP.value,
        )
        == 1
    )


def test_a_replay_returns_the_original_and_writes_no_second_row(staged: Engine) -> None:
    """CM-BE-AC-065, with the stored partial unique index underneath it."""
    category_id = _category(staged)
    draft = _draft(staged, category_id)
    first = _service(staged).publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-db-publish-key-01",
    )
    again = _service(staged).publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-db-publish-key-01",
    )
    assert again.disposition is ConstraintMutationDisposition.REPLAYED
    assert again.receipt.history_id == first.receipt.history_id
    assert again.record.constraint_code == first.record.constraint_code
    assert _count(staged, project_constraint_revisions) == 2
    with staged.begin() as connection:
        allocator = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
    assert (allocator._mapping["next_sequence"], allocator._mapping["issued_count"]) == (2, 1)


def test_a_reused_key_with_different_content_conflicts_and_changes_nothing(
    staged: Engine,
) -> None:
    """CM-BE-AC-066."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    _service(staged).update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-014"},
        idempotency_key="wp06-db-conflict-key-1",
    )
    with pytest.raises(ConstraintIdempotencyConflictError):
        _service(staged).update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "RFI-999"},
            idempotency_key="wp06-db-conflict-key-1",
        )
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == published.constraint_id
            )
        ).one()
    assert row._mapping["reference"] == "RFI-014"


# --- Close, Void, Reopen -----------------------------------------------------


def test_close_and_void_store_disjoint_terminal_fields(staged: Engine) -> None:
    """CM-BE-AC-014/015/016, enforced twice: by the aggregate and by the CHECKs."""
    category_id = _category(staged)
    closed = _published(staged, category_id)
    voided = _published(staged, category_id)
    _service(staged).close(
        principal_id=PRINCIPAL_A,
        constraint_id=closed.constraint_id,
        expected_version=closed.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        closure_commentary="Stamped set issued.",
    )
    _service(staged).void(
        principal_id=PRINCIPAL_A,
        constraint_id=voided.constraint_id,
        expected_version=voided.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        void_reason="Scope removed by owner.",
    )
    with staged.begin() as connection:
        rows = {
            row._mapping["constraint_id"]: row._mapping
            for row in connection.execute(select(project_constraints)).all()
        }
    ended = rows[closed.constraint_id]
    assert ended["lifecycle_state"] == ConstraintLifecycleState.CLOSED.value
    assert ended["completion_date"] == date(2026, 9, 2)
    assert ended["voided_date"] is None and ended["void_reason"] is None
    cancelled = rows[voided.constraint_id]
    assert cancelled["lifecycle_state"] == ConstraintLifecycleState.VOID.value
    assert cancelled["voided_date"] == date(2026, 9, 2)
    assert cancelled["completion_date"] is None


def test_reopen_clears_the_current_row_and_leaves_the_terminal_revision_intact(
    staged: Engine,
) -> None:
    """CM-BE-AC-013/017. The revision table refuses UPDATE; this proves it is not asked."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    closed = (
        _service(staged)
        .close(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            closure_commentary="Stamped set issued.",
        )
        .record
    )
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        terminal = uow.constraints.get_revision(
            PRINCIPAL_A, published.constraint_id, closed.version
        )
    reopened = (
        _service(staged)
        .reopen(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            target_state=ConstraintLifecycleState.IN_PROGRESS,
            expected_version=closed.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            reason="The owner reinstated the scope.",
        )
        .record
    )
    assert reopened.lifecycle_state is ConstraintLifecycleState.IN_PROGRESS
    assert reopened.completion_date is None
    assert reopened.closure_commentary is None
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        still = uow.constraints.get_revision(PRINCIPAL_A, published.constraint_id, closed.version)
    assert still == terminal
    assert still is not None
    assert still.completion_date == date(2026, 9, 2)


def test_a_terminal_record_cannot_return_active_through_a_transition(staged: Engine) -> None:
    """CM-BE-AC-013: only REOPEN crosses back."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    closed = (
        _service(staged)
        .close(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        .record
    )
    with pytest.raises(ConstraintLifecycleError):
        _service(staged).transition_active(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            target_state=ConstraintLifecycleState.PENDING,
            expected_version=closed.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )


# --- Close + Follow-up -------------------------------------------------------


def test_close_with_follow_up_commits_both_records_and_the_edge(staged: Engine) -> None:
    """CM-BE-AC-018, with the relationship's own composite foreign keys satisfied."""
    category_id = _category(staged)
    published = _published(
        staged, category_id, bic=(PRINCIPAL_PARTY,), responsible=(UNRESOLVED_PARTY,)
    )
    result = _service(staged).close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
    )
    assert result.predecessor.lifecycle_state is ConstraintLifecycleState.CLOSED
    assert result.successor.constraint_code == "DES.02"
    assert result.successor.bic == published.bic
    assert result.successor.responsible == published.responsible
    assert result.successor.date_identified == date(2026, 9, 2)
    assert result.successor.due_date == date(2026, 9, 16)
    with staged.begin() as connection:
        edge = connection.execute(select(project_constraint_relationships)).one()
    assert edge._mapping["source_constraint_id"] == result.successor.constraint_id
    assert edge._mapping["target_constraint_id"] == published.constraint_id
    assert edge._mapping["relationship_type"] == "follow_up_of"
    assert edge._mapping["created_by_history_id"] == result.successor_receipt.history_id
    assert edge._mapping["principal_id"] == PRINCIPAL_A


@pytest.mark.parametrize(
    ("name", "make"),
    [
        (
            "stale predecessor version",
            lambda published: {"expected_version": published.version - 1},
        ),
        ("blank successor description", lambda published: {"successor_description": "   "}),
        (
            "successor category from another principal",
            lambda published: {"successor_category_id": "ccat_neverissuedaaaa01"},
        ),
    ],
)
def test_an_induced_failure_in_close_with_follow_up_leaves_zero_partial_state(
    staged: Engine, name: str, make: Callable[[ProjectConstraint], dict[str, Any]]
) -> None:
    """Any failure: no closure, no successor, no consumed number, no edge.

    The three cases do not all exercise the same mechanism, and saying so is
    part of the measurement. The blank successor description is refused by the
    argument check at the top of the method, before the unit of work is ever
    opened, so that case proves the refusal happens and nothing more. The other
    two do open the transaction and fail inside it — one on the predecessor's
    version comparison, before any successor exists, and one after the
    predecessor has already been closed within the transaction — and those two
    are what measure the rollback. All three are asserted against the same zero
    state, including the two ledgers, which is why the case that never opens a
    transaction is kept rather than deleted.
    """
    category_id = _category(staged)
    published = _published(staged, category_id, bic=(PRINCIPAL_PARTY,))
    request: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "constraint_id": published.constraint_id,
        "expected_version": published.version,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "successor_description": "Re-issue the stamped set.",
    }
    request.update(make(published))
    with pytest.raises(Exception):  # noqa: B017 - each case raises its own type
        _service(staged).close_with_follow_up(**request)
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == published.constraint_id
            )
        ).one()
        allocator = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
    assert row._mapping["lifecycle_state"] == ConstraintLifecycleState.IDENTIFIED.value
    assert row._mapping["version"] == published.version
    assert _count(staged, project_constraints) == 1
    assert _count(staged, project_constraint_relationships) == 0
    assert (allocator._mapping["next_sequence"], allocator._mapping["issued_count"]) == (2, 1)
    # The two ledgers, as `test_a_refused_publish_leaves_no_trace_in_the_database`
    # measures them: the staging Draft and its Publish, and nothing this refused
    # request wrote. Without these the rollback claim covers the record tables
    # only, and a receipt or a revision surviving a refusal would go unseen.
    assert _count(staged, project_constraint_history) == 2
    assert _count(staged, project_constraint_revisions) == 2


def test_close_with_follow_up_replays_without_a_second_successor(staged: Engine) -> None:
    category_id = _category(staged)
    published = _published(staged, category_id, bic=(PRINCIPAL_PARTY,))
    first = _service(staged).close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
        idempotency_key="wp06-db-followup-key-1",
    )
    again = _service(staged).close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
        idempotency_key="wp06-db-followup-key-1",
    )
    assert again.disposition is ConstraintMutationDisposition.REPLAYED
    assert again.successor.constraint_id == first.successor.constraint_id
    assert again.relationship_id == first.relationship_id
    assert _count(staged, project_constraints) == 2
    assert _count(staged, project_constraint_relationships) == 1


# --- Categories --------------------------------------------------------------


def test_a_category_is_created_deactivated_and_never_deleted(staged: Engine) -> None:
    """CM-BE-AC-019/023."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    result = _service(staged).deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=category_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert result.record.state is ConstraintCategoryState.INACTIVE
    assert _count(staged, constraint_categories) == 1
    assert _count(staged, project_constraints) == 1
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == published.constraint_id
            )
        ).one()
    assert row._mapping["category_id"] == category_id
    assert (
        _count(
            staged,
            constraint_category_history,
            constraint_category_history.c.category_id == category_id,
        )
        == 2
    )


def test_a_project_unique_prefix_is_refused_by_the_stored_index(staged: Engine) -> None:
    """CM-BE-AC-020: the rule is the database's, and the service does not bypass it."""
    _category(staged, prefix="DES")
    with pytest.raises(Exception) as caught:
        _category(staged, prefix="DES")
    assert "unique" in str(caught.value).lower() or "duplicate" in str(caught.value).lower()
    assert _count(staged, constraint_categories) == 1


def test_a_reorder_writes_one_atomic_new_order(staged: Engine) -> None:
    """CM-BE-AC-022: one operation, not a loop of independent updates."""
    ids = [_category(staged, prefix=prefix) for prefix in ("DES", "PRO", "PER")]
    order = list(reversed(ids))
    result = _service(staged).reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=order,
        expected_versions=dict.fromkeys(ids, 1),
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert [record.category_id for record in result.records] == order
    with staged.begin() as connection:
        stored = {
            row._mapping["category_id"]: (row._mapping["display_order"], row._mapping["version"])
            for row in connection.execute(select(constraint_categories)).all()
        }
    assert [stored[category_id][0] for category_id in order] == [0, 1, 2]
    assert all(version == 2 for _, version in stored.values())


def test_a_prefix_is_immutable_once_a_code_has_been_issued_under_it(staged: Engine) -> None:
    """CM-BE-AC-021/022, with the stored issue-count/lock pairing underneath."""
    category_id = _category(staged)
    _published(staged, category_id)
    with staged.begin() as connection:
        row = connection.execute(
            select(constraint_categories).where(constraint_categories.c.category_id == category_id)
        ).one()
    assert row._mapping["issued_count"] == 1
    assert row._mapping["prefix_locked_at"] is not None
    with pytest.raises(Exception) as caught:
        _service(staged).update_category(
            principal_id=PRINCIPAL_A,
            category_id=category_id,
            expected_version=row._mapping["version"],
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"prefix": "XYZ"},
        )
    assert "prefix" in str(caught.value)
    renamed = _service(staged).update_category(
        principal_id=PRINCIPAL_A,
        category_id=category_id,
        expected_version=row._mapping["version"],
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"title": "Design and Engineering"},
    )
    assert renamed.record.title == "Design and Engineering"


# --- Security ----------------------------------------------------------------


def test_one_principal_cannot_mutate_another_principals_constraint(staged: Engine) -> None:
    """CM-BE-AC-132 consumed. Foreign and absent are the same refusal."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    for constraint_id in (published.constraint_id, "cst_neverissuedaaaa0001"):
        with pytest.raises(ConstraintNotFoundError):
            _service(staged).close(
                principal_id=PRINCIPAL_B,
                constraint_id=constraint_id,
                expected_version=published.version,
                actor=ConstraintMutationActor.PRINCIPAL,
            )
    with staged.begin() as connection:
        row = connection.execute(
            select(project_constraints).where(
                project_constraints.c.constraint_id == published.constraint_id
            )
        ).one()
    assert row._mapping["lifecycle_state"] == ConstraintLifecycleState.IDENTIFIED.value
    assert row._mapping["principal_id"] == PRINCIPAL_A


def test_a_party_cannot_name_another_principals_entity(staged: Engine) -> None:
    """CM-BE-AC-035. The foreign Entity is never named back to the caller either."""
    category_id = _category(staged)
    foreign = PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_THEIRS)
    with pytest.raises(ConstraintPartyError) as caught:
        _draft(staged, category_id, bic=(foreign,))
    assert ENTITY_THEIRS not in str(caught.value)
    assert _count(staged, project_constraints) == 0


def test_a_caller_cannot_supply_the_principal_a_record_is_written_under(
    staged: Engine,
) -> None:
    """The partition is the authenticated argument, never a payload field."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    with pytest.raises(ConstraintOperationError) as caught:
        _service(staged).update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"principal_id": PRINCIPAL_B},
        )
    assert caught.value.code == "constraint_update_field_unknown"
    with staged.begin() as connection:
        owners = set(connection.execute(select(project_constraints.c.principal_id)).scalars().all())
    assert owners == {PRINCIPAL_A}


def test_a_project_this_principal_has_no_settings_for_is_unavailable(staged: Engine) -> None:
    with pytest.raises(ConstraintProjectUnavailableError):
        _service(staged).create_category(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_B,
            prefix="NOPE",
            title="Not mine",
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert _count(staged, constraint_categories) == 0


# --- The ledger --------------------------------------------------------------


def test_the_receipt_ledger_records_before_and_after_for_every_attempt(
    staged: Engine,
) -> None:
    """CM-BE-AC-064/067."""
    category_id = _category(staged)
    published = _published(staged, category_id)
    _service(staged).update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"current_update": "x" * 4000},
        client_context="browser",
    )
    with staged.begin() as connection:
        rows = connection.execute(
            select(project_constraint_history)
            .where(project_constraint_history.c.constraint_id == published.constraint_id)
            .order_by(project_constraint_history.c.after_version)
        ).all()
    assert [
        (row._mapping["operation"], row._mapping["before_version"], row._mapping["after_version"])
        for row in rows
    ] == [
        (ConstraintMutationOperation.CREATE.value, 0, 1),
        (ConstraintMutationOperation.PUBLISH.value, 1, 2),
        (ConstraintMutationOperation.UPDATE.value, 2, 3),
    ]
    for row in rows:
        assert len(row._mapping["request_digest"]) == 64
        assert row._mapping["client_context"] in {None, "browser"}
    assert set(project_constraint_history.c.keys()).isdisjoint({"payload", "prompt", "request"})
