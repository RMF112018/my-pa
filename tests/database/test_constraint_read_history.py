"""PC-CM-IMP-WP03 §L T19: the mutation ledger, read as a bounded page and nothing more.

Receipts are ordered newest first by `(occurred_at, history_id)`, which is total
because two receipts can share an instant but never an identifier — the fixture
below deliberately gives two of them the same instant so the tie-break is
exercised rather than assumed. The page is bounded in SQL and continued by a
keyset on that same pair.

The other half is what the projection does **not** carry. A receipt stores an
idempotency key, a request digest, a client context and a correlation
identifier; none of the four is selected, so the page cannot leak one and a
field added later would have to be added deliberately. The fixture writes real
values into all four and the tests then assert they are nowhere in what comes
back.

A Constraint that is absent, or another Principal's, has no receipts — which is
the same page an untouched Constraint returns. Every value here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.application.errors import ConflictError, InvalidRequestError, SafeDetail
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_hstaaaa01"
PRINCIPAL_B: Final = "prn_hstbbbb02"
PROJECT_A: Final = "prj_hstaaaa01"
PROJECT_B: Final = "prj_hstbbbb02"
CATEGORY_A: Final = "ccat_hstaaaa01"
CATEGORY_B: Final = "ccat_hstbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_hst{ordinal:06d}"


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


def _category(
    category_id: str, principal: str, project: str, prefix: str, display_order: int
) -> ConstraintCategory:
    return ConstraintCategory(
        category_id=category_id,
        principal_id=principal,
        project_id=project,
        prefix=prefix,
        title=f"Category {prefix}",
        state=ConstraintCategoryState.ACTIVE,
        created_at=T0,
        updated_at=T0,
        display_order=display_order,
    )


def _settings(principal: str, project: str, zone: str = ZONE_EAST) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal,
        project_id=project,
        timezone_name=zone,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _constraint(**overrides: object) -> ProjectConstraint:
    """One published, active Constraint. Every value in it is synthetic."""
    values: dict[str, Any] = {
        "constraint_id": _id("cst", 1),
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "project_id": PROJECT_A,
        "category_id": CATEGORY_A,
        "constraint_code": "1.01",
        "description": "Switchgear submittal outstanding",
        "date_identified": date(2026, 9, 1),
        "due_date": date(2026, 9, 30),
        "bic": (PartyRef(kind=PartyKind.PRINCIPAL),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _world(connection: Connection, *, zone: str = ZONE_EAST) -> SqlConstraintManagementRepository:
    """Both Principals, both Projects, one Category each. Nothing is shared."""
    _seed_project(connection, PRINCIPAL_A, PROJECT_A)
    _seed_project(connection, PRINCIPAL_B, PROJECT_B)
    repository = SqlConstraintManagementRepository(connection)
    repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_A, zone))
    repository.insert_project_settings(PRINCIPAL_B, _settings(PRINCIPAL_B, PROJECT_B, zone))
    repository.insert_category(PRINCIPAL_A, _category(CATEGORY_A, PRINCIPAL_A, PROJECT_A, "AAA", 1))
    repository.insert_category(PRINCIPAL_B, _category(CATEGORY_B, PRINCIPAL_B, PROJECT_B, "BBB", 1))
    return repository


CONSTRAINT: Final = _id("cst", 1)
OTHER: Final = _id("cst", 2)
FOREIGN: Final = _id("cst", 3)
REVISION_ONE: Final = _id("crev", 1)
REVISION_TWO: Final = _id("crev", 2)
CREATED: Final = _id("chst", 1)
PUBLISHED: Final = _id("chst", 2)
UNCHANGED: Final = _id("chst", 3)
REFUSED: Final = _id("chst", 4)

#: Two receipts share this instant, so the identifier is what orders them.
SHARED_INSTANT: Final = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

#: Written into the ledger precisely so the projection can be shown not to carry
#: them. None of the four is a column this read selects.
IDEMPOTENCY_KEY: Final = "synthetic-history-key-01"
REQUEST_DIGEST: Final = "a" * 64
CLIENT_CONTEXT: Final = "synthetic-client-context"
CORRELATION_ID: Final = "corr_synthetic0001aaaa"


def _receipt(**overrides: object) -> ConstraintHistoryEntry:
    values: dict[str, Any] = {
        "history_id": CREATED,
        "principal_id": PRINCIPAL_A,
        "constraint_id": CONSTRAINT,
        "project_id": PROJECT_A,
        "operation": ConstraintMutationOperation.CREATE,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "outcome": ConstraintMutationOutcome.NO_OP,
        "before_version": 1,
        "after_version": 1,
        "occurred_at": T0,
        "recorded_at": T0,
    }
    values.update(overrides)
    return ConstraintHistoryEntry(**values)


def _ledger(connection: Connection) -> SqlConstraintManagementRepository:
    """Four receipts against one Constraint, two of them applied and two not."""
    repository = _world(connection)
    subject = _constraint(constraint_id=CONSTRAINT, version=2)
    repository.insert_constraint(PRINCIPAL_A, subject)
    repository.insert_constraint(
        PRINCIPAL_A, _constraint(constraint_id=OTHER, constraint_code="1.02")
    )
    repository.insert_constraint(
        PRINCIPAL_B,
        _constraint(
            constraint_id=FOREIGN,
            principal_id=PRINCIPAL_B,
            project_id=PROJECT_B,
            category_id=CATEGORY_B,
            constraint_code="9.01",
        ),
    )
    repository.insert_history(
        PRINCIPAL_A,
        _receipt(
            history_id=CREATED,
            operation=ConstraintMutationOperation.CREATE,
            outcome=ConstraintMutationOutcome.APPLIED,
            before_version=0,
            after_version=1,
            occurred_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
            revision_id=REVISION_ONE,
            idempotency_key=IDEMPOTENCY_KEY,
            request_digest=REQUEST_DIGEST,
            client_context=CLIENT_CONTEXT,
            correlation_id=CORRELATION_ID,
        ),
    )
    repository.insert_history(
        PRINCIPAL_A,
        _receipt(
            history_id=PUBLISHED,
            operation=ConstraintMutationOperation.PUBLISH,
            outcome=ConstraintMutationOutcome.APPLIED,
            before_version=1,
            after_version=2,
            occurred_at=SHARED_INSTANT,
            revision_id=REVISION_TWO,
        ),
    )
    repository.insert_history(
        PRINCIPAL_A,
        _receipt(
            history_id=UNCHANGED,
            operation=ConstraintMutationOperation.UPDATE,
            outcome=ConstraintMutationOutcome.NO_OP,
            before_version=2,
            after_version=2,
            occurred_at=SHARED_INSTANT,
        ),
    )
    repository.insert_history(
        PRINCIPAL_A,
        _receipt(
            history_id=REFUSED,
            operation=ConstraintMutationOperation.UPDATE,
            actor=ConstraintMutationActor.ASSISTANT,
            outcome=ConstraintMutationOutcome.REJECTED,
            before_version=2,
            after_version=2,
            occurred_at=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
            safe_failure_reason="version_conflict",
        ),
    )
    for revision_id, history_id, version in (
        (REVISION_ONE, CREATED, 1),
        (REVISION_TWO, PUBLISHED, 2),
    ):
        repository.insert_revision(
            PRINCIPAL_A,
            ConstraintRevision.from_constraint(
                _constraint(constraint_id=CONSTRAINT, version=version),
                revision_id=revision_id,
                history_id=history_id,
                recorded_at=T0,
            ),
        )
    return repository


def test_receipts_come_back_newest_first_and_break_ties_on_the_identifier(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        page = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT)
        assert [entry.history_id for entry in page.entries] == [
            REFUSED,
            UNCHANGED,
            PUBLISHED,
            CREATED,
        ]
        assert page.is_truncated is False
        assert page.next_cursor is None


def test_a_receipt_projects_its_operation_actor_outcome_and_versions(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        page = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT)
        refused = page.entries[0]
        assert refused.operation is ConstraintMutationOperation.UPDATE
        assert refused.actor is ConstraintMutationActor.ASSISTANT
        assert refused.outcome is ConstraintMutationOutcome.REJECTED
        assert (refused.before_version, refused.after_version) == (2, 2)
        assert refused.safe_failure_reason == "version_conflict"
        assert refused.revision_id is None


def test_an_applied_receipt_names_the_revision_a_reader_can_then_fetch(
    migrated_engine: Engine,
) -> None:
    """The linkage is what makes the ledger navigable rather than merely present."""
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        page = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT)
        applied = {entry.history_id: entry.revision_id for entry in page.entries}
        assert applied[CREATED] == REVISION_ONE
        assert applied[PUBLISHED] == REVISION_TWO
        assert applied[UNCHANGED] is None
        revision = repository.get_revision(PRINCIPAL_A, CONSTRAINT, 2)
        assert revision is not None
        assert revision.revision_id == REVISION_TWO
        assert revision.bic == (PartyRef(kind=PartyKind.PRINCIPAL),)


def test_the_projection_carries_none_of_the_four_withheld_columns(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        page = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT)
        rendered = repr(page)
        for withheld in (IDEMPOTENCY_KEY, REQUEST_DIGEST, CLIENT_CONTEXT, CORRELATION_ID):
            assert withheld not in rendered
        fields = set(type(page.entries[0]).__slots__)
        assert fields.isdisjoint(
            {"idempotency_key", "request_digest", "client_context", "correlation_id"}
        )
        rows = repository.list_history(PRINCIPAL_A, CONSTRAINT, limit=10)
        assert set(type(rows[0]).__slots__).isdisjoint(
            {"idempotency_key", "request_digest", "client_context", "correlation_id"}
        )


def test_a_history_page_is_bounded_and_continues_without_repeating(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        first = SERVICE.read_history(
            repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT, page_size=2
        )
        assert [entry.history_id for entry in first.entries] == [REFUSED, UNCHANGED]
        assert first.is_truncated is True
        assert first.next_cursor is not None
        second = SERVICE.read_history(
            repository,
            principal_id=PRINCIPAL_A,
            constraint_id=CONSTRAINT,
            page_size=2,
            cursor=first.next_cursor,
        )
        assert [entry.history_id for entry in second.entries] == [PUBLISHED, CREATED]
        assert second.is_truncated is False


def test_a_page_size_outside_its_bounds_is_refused(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        for page_size in (0, -1, 101):
            with pytest.raises(InvalidRequestError) as error:
                SERVICE.read_history(
                    repository,
                    principal_id=PRINCIPAL_A,
                    constraint_id=CONSTRAINT,
                    page_size=page_size,
                )
            assert error.value.safe_details == (SafeDetail.PAGE_SIZE,)


def test_a_history_cursor_belongs_to_one_ledger_and_one_page_size(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        first = SERVICE.read_history(
            repository, principal_id=PRINCIPAL_A, constraint_id=CONSTRAINT, page_size=2
        )
        assert first.next_cursor is not None
        with pytest.raises(ConflictError):
            SERVICE.read_history(
                repository,
                principal_id=PRINCIPAL_A,
                constraint_id=OTHER,
                page_size=2,
                cursor=first.next_cursor,
            )
        with pytest.raises(ConflictError):
            SERVICE.read_history(
                repository,
                principal_id=PRINCIPAL_A,
                constraint_id=CONSTRAINT,
                page_size=3,
                cursor=first.next_cursor,
            )
        with pytest.raises(InvalidRequestError):
            SERVICE.read_history(
                repository,
                principal_id=PRINCIPAL_A,
                constraint_id=CONSTRAINT,
                page_size=2,
                cursor="not-a-cursor",
            )


def test_a_foreign_or_absent_constraint_has_the_same_empty_ledger(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _ledger(connection)
        foreign = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=FOREIGN)
        untouched = SERVICE.read_history(repository, principal_id=PRINCIPAL_A, constraint_id=OTHER)
        absent = SERVICE.read_history(
            repository, principal_id=PRINCIPAL_A, constraint_id=_id("cst", 99)
        )
        assert foreign == untouched == absent
        assert foreign.entries == ()
        assert repository.list_history(PRINCIPAL_B, CONSTRAINT, limit=10) == ()
