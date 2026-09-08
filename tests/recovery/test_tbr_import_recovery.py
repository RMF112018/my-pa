"""PC-CM-IMP-WP13 T13-14: an import that fails part-way through leaves nothing.

The claim is that one import batch is one transaction, and a claim of that shape
is only worth what an injected failure proves about it. So each test here fails
the batch at a different point — before the first write, after the Categories
have been seeded, after a record and its receipt are already in the transaction,
and inside the revision write that closes the cycle — and then checks the whole
affected world rather than only the table the failure was injected in.

The atomicity is the unit of work's, not something this module compensates for:
`ConstraintLegacyImportService` performs every write on the unit of work it
opened, so leaving that block by exception rolls all of them back. What these
tests establish is that the claim is true of *this* write sequence — that the
Category seed is not committed separately from the records it seeded for, that a
half-written batch leaves no allocator state behind, and that a fresh attempt
after a rollback is a first attempt rather than a replay of one that never
happened.

The recovery boundary this build does **not** implement is stated rather than
tested: a database success followed by a later external write failure is WP11's
export-pending protocol. Canonical history is never rewritten here, and nothing
in this module claims otherwise.

Every identifier, prefix, label, code and date here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.sql import FromClause

from my_pa.application.constraint_legacy_import import ConstraintLegacyImportService
from my_pa.domain.project_controls.category import ConstraintCategory
from my_pa.domain.project_controls.constraint import ProjectConstraint
from my_pa.domain.project_controls.history import ConstraintHistoryEntry
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    project_constraint_history,
    project_constraint_parties,
    project_constraint_revisions,
    project_constraints,
    projects,
)
from tests.fixtures.tbr_workbook import SHEET_NAME, write_register

pytestmark = pytest.mark.recovery

PRINCIPAL: Final = "prn_recaaaa0001aaaa0001aa"
PROJECT: Final = "prj_recaaaa0001aaaa"
REGISTER: Final = "synthetic-register-01"
ZONE: Final = "America/Chicago"
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

#: Every table one import writes. All of them are checked after every failure,
#: because the point of atomicity is that a failure in the last write undoes the
#: first — a check that looked only where the exception came from would pass on
#: an import that had committed half of itself.
WRITTEN_TABLES: Final = (
    project_constraints,
    project_constraint_revisions,
    project_constraint_history,
    project_constraint_parties,
    constraint_categories,
)


class InjectedFailureError(RuntimeError):
    """Raised from a wrapped write, to fail one batch part-way through."""


class _FailsAtTheCategorySeed(SqlConstraintManagementRepository):
    """Fails on the very first write the batch performs."""

    def insert_category(
        self,
        principal_id: str,
        category: ConstraintCategory,
        *,
        next_sequence: int = 1,
        issued_count: int = 0,
        version: int = 1,
    ) -> None:
        raise InjectedFailureError("the category seed could not be written")


class _FailsAtTheSecondConstraint(SqlConstraintManagementRepository):
    """Fails after the Categories and the first record are already in the transaction."""

    seen = 0

    def insert_constraint(
        self,
        principal_id: str,
        constraint: ProjectConstraint,
        *,
        current_revision_id: str | None = None,
    ) -> None:
        type(self).seen += 1
        if type(self).seen > 1:
            raise InjectedFailureError("a constraint row could not be written")
        super().insert_constraint(principal_id, constraint, current_revision_id=current_revision_id)


class _FailsAtTheReceipt(SqlConstraintManagementRepository):
    """Fails after a record and its parties are already written."""

    def insert_history(self, principal_id: str, entry: ConstraintHistoryEntry) -> None:
        raise InjectedFailureError("the receipt could not be written")


class _FailsAtTheRevision(SqlConstraintManagementRepository):
    """Fails at the last write of the cycle, once everything else is in."""

    def insert_revision(self, principal_id: str, revision: ConstraintRevision) -> None:
        raise InjectedFailureError("the revision could not be written")


class _Broken(SqlAlchemyConstraintManagementUnitOfWork):
    """A unit of work whose repository is one of the failing subclasses.

    The transaction is the real one — only the repository is swapped, so what
    rolls back is the same boundary the product path uses.
    """

    def __init__(self, engine: Engine, repository: type[SqlConstraintManagementRepository]) -> None:
        super().__init__(engine)
        self._repository = repository

    @property
    def constraints(self) -> SqlConstraintManagementRepository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return self._repository(connection)


def seed(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(projects).values(
                project_id=PROJECT,
                principal_id=PRINCIPAL,
                name="A Synthetic Project",
                state="active",
                participants=[],
                opened_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
    with SqlAlchemyConstraintManagementUnitOfWork(engine) as uow:
        uow.constraints.insert_project_settings(
            PRINCIPAL,
            ConstraintProjectSettings(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name=ZONE,
                version=1,
                created_at=T0,
                updated_at=T0,
            ),
        )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return write_register(tmp_path / "register.xlsm", with_vba=True)


def _reader(source: Path) -> OoxmlWorkbookSource:
    return OoxmlWorkbookSource(source, sheet_name=SHEET_NAME)


def _service(
    engine: Engine,
    repository: type[SqlConstraintManagementRepository] = SqlConstraintManagementRepository,
) -> ConstraintLegacyImportService:
    return ConstraintLegacyImportService(
        unit_of_work=lambda: _Broken(engine, repository), clock=lambda: T0
    )


def _count(engine: Engine, table: FromClause) -> int:
    with engine.begin() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _assert_nothing_happened(engine: Engine) -> None:
    """Every table an import touches, back exactly as it stood: empty."""
    for table in WRITTEN_TABLES:
        assert _count(engine, table) == 0, table.name


def _apply(engine: Engine, source: Path, repository: type) -> None:
    _service(engine, repository).apply_disposable(
        principal_id=PRINCIPAL,
        project_id=PROJECT,
        register_id=REGISTER,
        reader=_reader(source),
    )


@pytest.mark.parametrize(
    "repository",
    (
        _FailsAtTheCategorySeed,
        _FailsAtTheSecondConstraint,
        _FailsAtTheReceipt,
        _FailsAtTheRevision,
    ),
    ids=lambda value: str(value.__name__),
)
def test_a_failure_at_any_point_in_the_batch_leaves_nothing_behind(
    staged: Engine, source: Path, repository: type
) -> None:
    """T13-14. Four injection points, one transaction, no partial state anywhere."""
    _FailsAtTheSecondConstraint.seen = 0
    with pytest.raises(InjectedFailureError):
        _apply(staged, source, repository)
    _assert_nothing_happened(staged)


def test_a_failure_before_the_first_write_writes_nothing(staged: Engine, source: Path) -> None:
    """T13-14. The seam fires inside the transaction and before any record write."""
    service = ConstraintLegacyImportService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(staged),
        clock=lambda: T0,
    )

    def explode() -> None:
        raise InjectedFailureError("the operator interrupted the batch")

    with pytest.raises(InjectedFailureError):
        service.apply_disposable(
            principal_id=PRINCIPAL,
            project_id=PROJECT,
            register_id=REGISTER,
            reader=_reader(source),
            before_write=explode,
        )
    _assert_nothing_happened(staged)


def test_a_fresh_attempt_after_a_rollback_is_a_first_attempt(staged: Engine, source: Path) -> None:
    """T13-14. The rolled-back attempt consumed no import identity and no sequence."""
    _FailsAtTheSecondConstraint.seen = 0
    with pytest.raises(InjectedFailureError):
        _apply(staged, source, _FailsAtTheRevision)
    _assert_nothing_happened(staged)

    service = ConstraintLegacyImportService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(staged),
        clock=lambda: T0,
    )
    outcome = service.apply_disposable(
        principal_id=PRINCIPAL,
        project_id=PROJECT,
        register_id=REGISTER,
        reader=_reader(source),
    )
    assert outcome.report.applied > 0
    assert outcome.report.replayed == 0
    assert _count(staged, project_constraints) == outcome.report.applied
    assert _count(staged, project_constraint_revisions) == outcome.report.applied
    assert _count(staged, project_constraint_history) == outcome.report.applied
    assert _count(staged, constraint_categories) == 2
