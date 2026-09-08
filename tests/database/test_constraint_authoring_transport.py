"""The authoring plane end to end, against a live PostgreSQL server (PC-CM-IMP-WP07).

`T07-07`, `T07-09` and `T07-10`. What the FAST tier proves about shapes, this
proves about behaviour through the canonical entry point — `ApplicationService.
invoke`, the same one every transport calls — on a disposable head-migrated
clone. Every identifier, prefix, label, code and date here is synthetic; nothing
here touches a persistent database.

Three claims:

**Authorization precedes every side effect (`T07-07`).** A request denied on
purpose or capability leaves no Constraint row, no revision, no receipt and no
advanced allocator sequence. A denial that wrote a Draft first and refused
afterwards would satisfy every assertion about the *answer*, so what is measured
is the tables.

**Result fidelity (`T07-09`).** `APPLIED`, `NO_OP` and `REPLAYED` reach a caller
as WP06 decided them; the record and receipt in the envelope are the ones the
ledger holds; `close_follow_up` returns both receipts, the successor and the
relationship id in one answer; `reorder` returns the whole final ordering.
Nothing about any of those is reconstructed by the dispatcher.

**Foreign identifiers are nondisclosing (`T07-10`).** On all twelve, a record in
another Principal's partition answers exactly as one that does not exist.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.sql import FromClause

from my_pa.application.commands import (
    CloseConstraint,
    CloseConstraintWithFollowUp,
    Command,
    ConstraintUpdateField,
    CreateConstraintCategory,
    CreateConstraintDraft,
    DeactivateConstraintCategory,
    PublishConstraint,
    ReopenConstraint,
    ReorderConstraintCategories,
    TransitionConstraint,
    UpdateConstraint,
    UpdateConstraintCategory,
    VoidConstraint,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_category_history,
    project_constraint_history,
    project_constraint_relationships,
    project_constraint_revisions,
    project_constraints,
    projects,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS

pytestmark = [pytest.mark.database, pytest.mark.database_clone]

PRINCIPAL_A: Final = "prn_wp07aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_wp07bbbb0002bbbb0002"
PROJECT_A: Final = "prj_wp07aaaa0001aaaa"
PROJECT_B: Final = "prj_wp07bbbb0002bbbb"
ZONE: Final = "America/Chicago"
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
PRINCIPAL_PARTY: Final = PartyRef(kind=PartyKind.PRINCIPAL)

ACTING: Final = Principal(principal_id=PRINCIPAL_A, kind=PrincipalKind.GATEWAY, authenticated=True)


def _service(engine: Engine) -> ApplicationService:
    """The one entry point, composed with the real Constraint transaction."""
    # The audit sink takes its own engine, exactly as `test_continuity_authoring`
    # composes it: the audit row for a denial has to survive the rollback of the
    # transaction that was denied.
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        clock=lambda: T0,
        limits=DEFAULT_LIMITS,
        constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
    )


def _invoke(
    engine: Engine,
    command: Command,
    *,
    purpose: Purpose = Purpose.CONSTRAINT_AUTHORING,
    principal: Principal = ACTING,
) -> ResponseEnvelope:
    metadata = RequestMetadata(
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        capability=command.capability,
        purpose=purpose,
        principal_id=principal.principal_id,
        requested_at=T0,
    )
    return _service(engine).invoke(metadata, command, principal=principal)


@pytest.fixture
def staged(migrated_engine: Engine) -> Iterator[Engine]:
    """Two Principals, two Projects, one calendar each, and one Category apiece."""
    with migrated_engine.begin() as connection:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
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
    with SqlAlchemyConstraintManagementUnitOfWork(migrated_engine) as uow:
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
    yield migrated_engine


def _count(engine: Engine, table: FromClause) -> int:
    with engine.begin() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _counts(engine: Engine) -> dict[str, int]:
    return {
        "constraints": _count(engine, project_constraints),
        "revisions": _count(engine, project_constraint_revisions),
        "history": _count(engine, project_constraint_history),
        "categories": _count(engine, constraint_categories),
        "category_history": _count(engine, constraint_category_history),
        "relationships": _count(engine, project_constraint_relationships),
    }


def _allocator(engine: Engine, category_id: str) -> tuple[int, int]:
    with engine.begin() as connection:
        row = connection.execute(
            select(
                constraint_categories.c.next_sequence, constraint_categories.c.issued_count
            ).where(constraint_categories.c.category_id == category_id)
        ).one()
    return int(row[0]), int(row[1])


def _category(
    engine: Engine, *, principal: Principal = ACTING, project: str = PROJECT_A, prefix: str = "DES"
) -> str:
    envelope = _invoke(
        engine,
        CreateConstraintCategory(
            project_id=project, code_segment=prefix, title=f"{prefix} category"
        ),
        principal=principal,
    )
    assert envelope.error is None, envelope.error
    category: str = envelope.result["category"]["category_id"]
    return category


def _draft(engine: Engine, category_id: str, *, principal: Principal = ACTING) -> dict[str, Any]:
    envelope = _invoke(
        engine,
        CreateConstraintDraft(
            project_id=PROJECT_A if principal is ACTING else PROJECT_B,
            category_id=category_id,
            description="The permit set is not stamped.",
            date_identified=date(2026, 9, 2),
            due_date=date(2026, 9, 30),
            bic=(PRINCIPAL_PARTY,),
            responsible=(PRINCIPAL_PARTY,),
        ),
        principal=principal,
    )
    assert envelope.error is None, envelope.error
    record: dict[str, Any] = envelope.result["constraint"]
    return record


def _published(
    engine: Engine, category_id: str, *, principal: Principal = ACTING
) -> dict[str, Any]:
    draft = _draft(engine, category_id, principal=principal)
    envelope = _invoke(
        engine,
        PublishConstraint(constraint_id=draft["constraint_id"], expected_version=draft["version"]),
        principal=principal,
    )
    assert envelope.error is None, envelope.error
    record: dict[str, Any] = envelope.result["constraint"]
    return record


# ---- T07-07: authorization precedes every side effect ------------------------


def test_a_denied_purpose_writes_nothing(staged: Engine) -> None:
    """`constraint_read` does not reach a mutation, and the refusal reaches no table."""
    category = _category(staged)
    before = _counts(staged)
    sequence_before = _allocator(staged, category)

    envelope = _invoke(
        staged,
        CreateConstraintDraft(
            project_id=PROJECT_A, category_id=category, description="Never written."
        ),
        purpose=Purpose.CONSTRAINT_READ,
    )

    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert _counts(staged) == before
    assert _allocator(staged, category) == sequence_before


def test_a_denied_publish_advances_no_allocator_sequence(staged: Engine) -> None:
    """The allocator is the one side effect a refusal could leave behind."""
    category = _category(staged)
    draft = _draft(staged, category)
    before = _counts(staged)
    sequence_before = _allocator(staged, category)

    envelope = _invoke(
        staged,
        PublishConstraint(constraint_id=draft["constraint_id"], expected_version=draft["version"]),
        purpose=Purpose.CONSTRAINT_READ,
    )

    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert _counts(staged) == before
    assert _allocator(staged, category) == sequence_before


def test_an_unauthenticated_principal_writes_nothing(staged: Engine) -> None:
    category = _category(staged)
    before = _counts(staged)
    stranger = Principal(principal_id=PRINCIPAL_B, kind=PrincipalKind.GATEWAY)

    envelope = _invoke(
        staged,
        CreateConstraintDraft(project_id=PROJECT_B, category_id=category, description="No."),
        principal=stranger,
    )

    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert _counts(staged) == before


# ---- T07-09: result fidelity -------------------------------------------------


def test_an_applied_mutation_returns_wp06s_own_record_and_receipt(staged: Engine) -> None:
    category = _category(staged)
    published = _published(staged, category)

    envelope = _invoke(
        staged,
        UpdateConstraint(
            constraint_id=published["constraint_id"],
            expected_version=published["version"],
            current_update="Awaiting the stamped set.",
        ),
    )

    assert envelope.error is None
    result = envelope.result
    assert result["disposition"] == "applied"
    assert result["constraint"]["current_update"] == "Awaiting the stamped set."
    assert result["constraint"]["version"] == published["version"] + 1
    assert result["receipt"]["before_version"] == published["version"]
    assert result["receipt"]["after_version"] == published["version"] + 1
    assert result["receipt"]["principal_id"] == PRINCIPAL_A
    with staged.begin() as connection:
        stored = connection.execute(
            select(project_constraint_history.c.history_id).where(
                project_constraint_history.c.history_id == result["receipt"]["history_id"]
            )
        ).one_or_none()
    assert stored is not None, "the receipt in the envelope is not the ledger's row"


def test_a_no_op_update_is_reported_as_a_no_op(staged: Engine) -> None:
    """A patch that changes nothing writes a receipt and does not advance the version."""
    category = _category(staged)
    published = _published(staged, category)

    envelope = _invoke(
        staged,
        UpdateConstraint(
            constraint_id=published["constraint_id"],
            expected_version=published["version"],
            description=published["description"],
        ),
    )

    assert envelope.error is None
    assert envelope.result["disposition"] == "no_op"
    assert envelope.result["constraint"]["version"] == published["version"]


def test_a_replayed_mutation_is_reported_as_a_replay(staged: Engine) -> None:
    category = _category(staged)
    published = _published(staged, category)
    command = UpdateConstraint(
        constraint_id=published["constraint_id"],
        expected_version=published["version"],
        reference="RFI-0001",
        idempotency_key="wp07-replay-0001",
    )

    first = _invoke(staged, command)
    second = _invoke(staged, command)

    assert first.error is None and second.error is None
    assert first.result["disposition"] == "applied"
    assert second.result["disposition"] == "replayed"
    assert second.result["receipt"]["history_id"] == first.result["receipt"]["history_id"]
    assert second.result["constraint"]["version"] == first.result["constraint"]["version"]


def test_a_version_conflict_is_a_conflict_and_not_a_silent_overwrite(staged: Engine) -> None:
    category = _category(staged)
    published = _published(staged, category)

    envelope = _invoke(
        staged,
        CloseConstraint(
            constraint_id=published["constraint_id"],
            expected_version=published["version"] + 7,
            completion_date=date(2026, 9, 3),
        ),
    )

    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT


def test_close_with_follow_up_returns_both_receipts_the_successor_and_the_edge(
    staged: Engine,
) -> None:
    """One operation, one answer: never two mutations a caller could half-apply."""
    category = _category(staged)
    published = _published(staged, category)

    envelope = _invoke(
        staged,
        CloseConstraintWithFollowUp(
            constraint_id=published["constraint_id"],
            expected_version=published["version"],
            successor_description="The stamped set is still outstanding.",
            completion_date=date(2026, 9, 3),
            successor_due_date=date(2026, 10, 15),
            successor_bic=(PRINCIPAL_PARTY,),
            successor_responsible=(PRINCIPAL_PARTY,),
        ),
    )

    assert envelope.error is None
    result = envelope.result
    assert result["disposition"] == "applied"
    assert result["predecessor"]["lifecycle_state"] == ConstraintLifecycleState.CLOSED.value
    assert result["successor"]["constraint_id"] != result["predecessor"]["constraint_id"]
    assert result["successor"]["constraint_code"], "the successor was published with a code"
    assert result["predecessor_receipt"]["history_id"]
    assert result["successor_receipt"]["history_id"]
    assert result["relationship_id"]
    with staged.begin() as connection:
        edge = connection.execute(
            select(
                project_constraint_relationships.c.source_constraint_id,
                project_constraint_relationships.c.target_constraint_id,
            ).where(project_constraint_relationships.c.relationship_id == result["relationship_id"])
        ).one()
    assert edge[0] == result["successor"]["constraint_id"]
    assert edge[1] == result["predecessor"]["constraint_id"]


def test_a_reorder_returns_the_whole_final_ordering(staged: Engine) -> None:
    first = _category(staged, prefix="DES")
    second = _category(staged, prefix="SIT")
    third = _category(staged, prefix="MEP")

    envelope = _invoke(
        staged,
        ReorderConstraintCategories(
            project_id=PROJECT_A,
            ordered_category_ids=(third, first, second),
            expected_versions=(1, 1, 1),
        ),
    )

    assert envelope.error is None
    result = envelope.result
    assert result["disposition"] == "applied"
    assert [record["category_id"] for record in result["categories"]] == [third, first, second]
    assert len(result["receipts"]) == 3


def test_a_transition_and_a_void_report_their_own_dispositions(staged: Engine) -> None:
    category = _category(staged)
    published = _published(staged, category)

    moved = _invoke(
        staged,
        TransitionConstraint(
            constraint_id=published["constraint_id"],
            to_state=ConstraintLifecycleState.IN_PROGRESS,
            expected_version=published["version"],
        ),
    )
    assert moved.error is None
    assert moved.result["constraint"]["lifecycle_state"] == "in_progress"

    voided = _invoke(
        staged,
        VoidConstraint(
            constraint_id=published["constraint_id"],
            expected_version=moved.result["constraint"]["version"],
            void_reason="Raised in error.",
            voided_date=date(2026, 9, 4),
        ),
    )
    assert voided.error is None
    assert voided.result["constraint"]["lifecycle_state"] == "void"

    reopened = _invoke(
        staged,
        ReopenConstraint(
            constraint_id=published["constraint_id"],
            to_state=ConstraintLifecycleState.IDENTIFIED,
            expected_version=voided.result["constraint"]["version"],
            reason="The scope came back.",
        ),
    )
    assert reopened.error is None
    assert reopened.result["constraint"]["lifecycle_state"] == "identified"


def test_a_category_update_and_deactivation_report_their_receipts(staged: Engine) -> None:
    category = _category(staged)

    revised = _invoke(
        staged,
        UpdateConstraintCategory(
            category_id=category, expected_version=1, title="Design coordination"
        ),
    )
    assert revised.error is None
    assert revised.result["category"]["title"] == "Design coordination"
    assert revised.result["receipt"]["category_id"] == category

    retired = _invoke(
        staged,
        DeactivateConstraintCategory(
            # The Category aggregate carries no `version`; the row does, and the
            # receipt is where WP06 publishes it. `after_version` is the
            # authoritative next expected version, and reading it here is the
            # same optimistic-concurrency handshake a real client performs.
            category_id=category,
            expected_version=revised.result["receipt"]["after_version"],
        ),
    )
    assert retired.error is None
    assert retired.result["category"]["state"] == "inactive"


def test_an_update_clears_only_the_fields_it_names(staged: Engine) -> None:
    category = _category(staged)
    published = _published(staged, category)
    referenced = _invoke(
        staged,
        UpdateConstraint(
            constraint_id=published["constraint_id"],
            expected_version=published["version"],
            reference="RFI-0002",
        ),
    )
    assert referenced.error is None

    cleared = _invoke(
        staged,
        UpdateConstraint(
            constraint_id=published["constraint_id"],
            expected_version=referenced.result["constraint"]["version"],
            clear_fields=(ConstraintUpdateField.REFERENCE,),
        ),
    )
    assert cleared.error is None
    assert cleared.result["constraint"]["reference"] is None
    assert cleared.result["constraint"]["description"] == published["description"]


# ---- T07-10: foreign identifiers are nondisclosing ---------------------------


def _foreign_commands(constraint_id: str, category_id: str, project_id: str) -> list[Command]:
    """One command per authoring capability, each naming another Principal's record."""
    return [
        CreateConstraintDraft(project_id=project_id, description="Not mine."),
        PublishConstraint(constraint_id=constraint_id, expected_version=1),
        UpdateConstraint(
            constraint_id=constraint_id, expected_version=1, current_update="Not mine."
        ),
        TransitionConstraint(
            constraint_id=constraint_id,
            to_state=ConstraintLifecycleState.PENDING,
            expected_version=1,
        ),
        CloseConstraint(constraint_id=constraint_id, expected_version=1),
        CloseConstraintWithFollowUp(
            constraint_id=constraint_id, expected_version=1, successor_description="Not mine."
        ),
        VoidConstraint(constraint_id=constraint_id, expected_version=1, void_reason="Not mine."),
        ReopenConstraint(
            constraint_id=constraint_id,
            to_state=ConstraintLifecycleState.IDENTIFIED,
            expected_version=1,
        ),
        CreateConstraintCategory(project_id=project_id, code_segment="XXX", title="Not mine"),
        UpdateConstraintCategory(category_id=category_id, expected_version=1, title="Not mine"),
        DeactivateConstraintCategory(category_id=category_id, expected_version=1),
        ReorderConstraintCategories(
            project_id=project_id,
            ordered_category_ids=(category_id,),
            expected_versions=(1,),
        ),
    ]


def test_every_authoring_capability_answers_a_foreign_record_as_an_absent_one(
    staged: Engine,
) -> None:
    """`CM-BE-AC-078`, one row per capability, compared pair by pair.

    The two requests differ only in whether the identifier they name exists in
    another Principal's partition. Every part of the refusal a caller can see —
    the code, the message and the safe details — must be identical, or the shape
    of the answer discloses that the record exists.
    """
    theirs = Principal(principal_id=PRINCIPAL_B, kind=PrincipalKind.GATEWAY, authenticated=True)
    their_category = _category(staged, principal=theirs, project=PROJECT_B, prefix="THR")
    their_constraint = _published(staged, their_category, principal=theirs)

    foreign = _foreign_commands(their_constraint["constraint_id"], their_category, PROJECT_B)
    absent = _foreign_commands(
        issue_identifier(IdKind.PROJECT_CONSTRAINT),
        issue_identifier(IdKind.CONSTRAINT_CATEGORY),
        issue_identifier(IdKind.PROJECT),
    )
    assert len(foreign) == len(absent) == 12

    for reaching, missing in zip(foreign, absent, strict=True):
        reached = _invoke(staged, reaching)
        unknown = _invoke(staged, missing)
        assert reached.error is not None, f"{reaching.capability.value} answered a foreign record"
        assert unknown.error is not None
        assert reached.error.code is unknown.error.code
        assert reached.error.message == unknown.error.message
        assert reached.error.safe_details == unknown.error.safe_details


def test_a_foreign_record_is_untouched_by_the_attempt(staged: Engine) -> None:
    """Nondisclosing and inert: the refusal changes nothing in the other partition."""
    theirs = Principal(principal_id=PRINCIPAL_B, kind=PrincipalKind.GATEWAY, authenticated=True)
    their_category = _category(staged, principal=theirs, project=PROJECT_B, prefix="THR")
    their_constraint = _published(staged, their_category, principal=theirs)
    before = _counts(staged)

    envelope = _invoke(
        staged,
        CloseConstraint(
            constraint_id=their_constraint["constraint_id"],
            expected_version=their_constraint["version"],
            completion_date=date(2026, 9, 5),
        ),
    )

    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.NOT_FOUND
    assert _counts(staged) == before


def test_the_acting_principal_and_not_the_envelope_owns_every_receipt(staged: Engine) -> None:
    """`CM-BE-AC-083` against the database: the ledger's owner is the authenticated one."""
    category = _category(staged)
    published = _published(staged, category)
    metadata = RequestMetadata(
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        capability=Capability.CONSTRAINTS_CLOSE,
        purpose=Purpose.CONSTRAINT_AUTHORING,
        # The envelope names the *other* Principal. It is correlation input.
        principal_id=PRINCIPAL_B,
        requested_at=T0,
    )
    envelope = _service(staged).invoke(
        metadata,
        CloseConstraint(
            constraint_id=published["constraint_id"],
            expected_version=published["version"],
            completion_date=date(2026, 9, 6),
        ),
        principal=ACTING,
    )

    assert envelope.error is None
    assert envelope.result["receipt"]["principal_id"] == PRINCIPAL_A
    with staged.begin() as connection:
        owners = set(
            connection.execute(select(project_constraint_history.c.principal_id)).scalars()
        )
    assert owners == {PRINCIPAL_A}
