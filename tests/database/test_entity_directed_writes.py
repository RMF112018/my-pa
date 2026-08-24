"""The directed-relationship write path against a real PostgreSQL server.

`tests/unit/test_entity_directed_writes.py` drives the in-memory double and
proves the *contract*. This drives the SQL and proves the contract holds where it
has to: against real statements, two real partial unique indexes, a real
composite foreign key, and a version guard that is either in the WHERE clause or
is not.

**The claim that carries the package is that the application's folding rule and
the index's folding rule are the same rule.** `descriptor_key` restates
`COALESCE(lower(trim(x)), '')` in Python so the plane can decide replay before
the insert, and a rule stated twice and compared once is one rule while a rule
stated twice and never compared is two that drift. The null-safe and case-folded
pairs below are that comparison: each is asserted against the *server*, so the
Python copy is measured rather than trusted.

**Two of these tests need the seven `entities.assignments.*` and
`entities.relationships.*` names, and the `entity_authoring` purpose, admitted to
`knowledge.audit_events`; Phase A's Alembic revision is not this package's to
write.** They are the two that go through `ApplicationService.invoke` rather than
through the repository, because that is where an audit row is written -- and
committed, on its own connection -- before the handler runs. Measured at this
head: `capability_is_known` and `purpose_is_known` name neither, so the audit
insert is a `CheckViolation`, the exception leaves `_run`, and `invoke` renders
`internal_error`. Both tests therefore fail on `envelope.error is None` rather
than on anything they are about. Every other test in this module reaches the
repository directly and passes at this head.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.commands import CreateEntityAssignment, CreateEntityRelationship
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import (
    AssignmentWriteRequest,
    DirectedReceipt,
    RelationshipWriteRequest,
    UnknownScopeError,
)
from my_pa.contracts.ports import UnitOfWork as UnitOfWorkPort
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.relationship.entity import (
    AssignmentState,
    AssignmentType,
    DirectedWriteError,
    DirectedWriteOperation,
    DuplicateDirectedFactError,
    Entity,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    MergedEndpointError,
    RelationshipState,
    StaleDirectedVersionError,
    descriptor_key,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    MutationAuthority,
    MutationRecordFamily,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database
#: another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_directed_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

ALICE: Final = "ent_aaaa0001aaaa0001"
ACME: Final = "ent_bbbb0002bbbb0002"
TOWER: Final = "ent_cccc0003cccc0003"
BOB: Final = "ent_dddd0004dddd0004"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"
WHEN: Final = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _entity(entity_id: str, principal_id: str, name: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=kind,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """Alice, Acme and Tower belong to A; Bob belongs to B, as every read's decoy."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(ALICE, PRINCIPAL_A, "Alice", EntityType.PERSON))
        repository.create(PRINCIPAL_A, _entity(ACME, PRINCIPAL_A, "Acme", EntityType.ORGANIZATION))
        repository.create(PRINCIPAL_A, _entity(TOWER, PRINCIPAL_A, "Tower", EntityType.PROJECT))
        repository.create(PRINCIPAL_B, _entity(BOB, PRINCIPAL_B, "Bob", EntityType.PERSON))
    return migrated_engine


def _assignment(**overrides: object) -> AssignmentWriteRequest:
    values: dict[str, Any] = {
        "operation": DirectedWriteOperation.CREATE,
        "assignment_id": None,
        "principal_id": PRINCIPAL_A,
        "entity_id": ALICE,
        "expected_entity_version": 1,
        "assignment_type": AssignmentType.PROJECT_ASSIGNMENT,
        "scope_entity_id": TOWER,
        "expected_scope_version": 1,
        "expected_version": None,
        "role": None,
        "discipline": None,
        "responsibility_class": None,
        "effective_from": None,
        "effective_to": None,
        "cleared": (),
        "evidence_refs": (),
        "reason": None,
        "idempotency_key": "db-assignment-0001",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return AssignmentWriteRequest(**values)


def _edge(**overrides: object) -> RelationshipWriteRequest:
    values: dict[str, Any] = {
        "operation": DirectedWriteOperation.CREATE,
        "relationship_id": None,
        "principal_id": PRINCIPAL_A,
        "from_entity_id": ALICE,
        "expected_from_version": 1,
        "relationship_type": EntityRelationshipType.WORKS_FOR,
        "to_entity_id": ACME,
        "expected_to_version": 1,
        "scope_entity_id": None,
        "expected_scope_version": None,
        "expected_version": None,
        "effective_from": None,
        "effective_to": None,
        "cleared": (),
        "evidence_refs": (),
        "reason": None,
        "idempotency_key": "db-relationship-0001",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return RelationshipWriteRequest(**values)


def _rows(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )


def _write(engine: Engine, call: str, request: object) -> DirectedReceipt:
    with engine.begin() as connection:
        return getattr(SqlEntityRepository(connection), call)(request)  # type: ignore[no-any-return]


# --- the active semantic key, as the server actually folds it ---------------


@pytest.mark.parametrize(
    ("first_role", "second_role"),
    [
        (None, ""),
        (None, "   "),
        ("", "   "),
        ("Lead", "lead"),
        ("lead", " LEAD "),
        ("Project Manager", "project manager "),
    ],
    ids=[
        "null and empty are one role",
        "null and whitespace are one role",
        "empty and whitespace are one role",
        "case does not make two roles",
        "case and padding do not make two roles",
        "a padded lowercase spelling is the same role",
    ],
)
def test_the_index_folds_these_two_roles_together_and_so_does_the_application(
    staged: Engine, first_role: str | None, second_role: str
) -> None:
    """The one comparison that makes `descriptor_key` a copy rather than a claim.

    Both halves are asserted in one test on purpose. Asserting the Python fold
    in `tests/unit` and the SQL fold here, separately, is what lets the two
    drift: each would keep passing while they disagreed, and the disagreement is
    the defect -- a create the application admits and the index refuses is an
    `IntegrityError` out of a port, and one the application refuses and the index
    would have admitted is a write silently lost.
    """
    assert descriptor_key(first_role) == descriptor_key(second_role)
    _write(staged, "create_assignment", _assignment(role=first_role))
    with pytest.raises(DuplicateDirectedFactError):
        _write(
            staged,
            "create_assignment",
            _assignment(role=second_role, idempotency_key="db-assignment-0002"),
        )
    assert _rows(staged, "entity_assignments") == 1


def test_a_scope_set_and_a_scope_absent_are_two_assignments(staged: Engine) -> None:
    """`COALESCE(scope_entity_id, '')` folds NULL to empty and to nothing else."""
    _write(staged, "create_assignment", _assignment(role="Lead"))
    _write(
        staged,
        "create_assignment",
        _assignment(
            role="Lead",
            scope_entity_id=None,
            expected_scope_version=None,
            idempotency_key="db-assignment-0002",
        ),
    )
    assert _rows(staged, "entity_assignments") == 2


def test_a_different_discipline_is_a_different_assignment(staged: Engine) -> None:
    _write(staged, "create_assignment", _assignment(role="Lead", discipline="Structural"))
    _write(
        staged,
        "create_assignment",
        _assignment(role="Lead", discipline="Mechanical", idempotency_key="db-assignment-0002"),
    )
    assert _rows(staged, "entity_assignments") == 2


def test_ending_an_assignment_frees_the_key_for_its_replacement(staged: Engine) -> None:
    """The partial index is over the *active* row, which is what makes this work."""
    created = _write(staged, "create_assignment", _assignment(role="Lead"))
    _write(
        staged,
        "end_assignment",
        _assignment(
            operation=DirectedWriteOperation.END,
            assignment_id=created.record_id,
            expected_version=1,
            entity_id=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_entity_version=None,
            expected_scope_version=None,
            effective_to=WHEN,
            reason="the role was recorded against the wrong scope",
            idempotency_key="db-assignment-end",
        ),
    )
    replacement = _write(
        staged,
        "create_assignment",
        _assignment(role="Lead", idempotency_key="db-assignment-replacement"),
    )
    assert replacement.record_id != created.record_id
    assert _rows(staged, "entity_assignments") == 2


def test_a_duplicate_active_edge_is_refused_and_the_inverse_is_admitted(
    staged: Engine,
) -> None:
    """`(from, type, to, scope)`, so direction is what a directed model says it is."""
    _write(staged, "create_relationship", _edge())
    with pytest.raises(DuplicateDirectedFactError):
        _write(staged, "create_relationship", _edge(idempotency_key="db-relationship-0002"))
    inverse = _write(
        staged,
        "create_relationship",
        _edge(
            from_entity_id=ACME,
            to_entity_id=ALICE,
            idempotency_key="db-relationship-0003",
        ),
    )
    assert inverse.version == 1
    assert _rows(staged, "entity_relationships") == 2


def test_a_different_type_between_the_same_pair_is_a_different_edge(staged: Engine) -> None:
    _write(staged, "create_relationship", _edge())
    _write(
        staged,
        "create_relationship",
        _edge(
            relationship_type=EntityRelationshipType.CONSULTANT_TO,
            idempotency_key="db-relationship-0002",
        ),
    )
    assert _rows(staged, "entity_relationships") == 2


# --- the partition is structural, not a filter ------------------------------


def test_a_write_naming_another_principals_entity_is_refused_before_it_is_written(
    staged: Engine,
) -> None:
    """The composite `(entity_id, principal_id)` foreign key would refuse it too.

    Asserted through the repository rather than through raw SQL because the two
    refusals mean different things to a caller: the repository's is
    `UnknownScopeError`, which the application renders as `not_found` and which is
    indistinguishable from an absent entity, and the schema's is an
    `IntegrityError` naming a constraint. A plane that let the second one out
    would be telling a caller that the identifier names something.
    """
    with pytest.raises(UnknownScopeError):
        _write(staged, "create_assignment", _assignment(entity_id=BOB))
    assert _rows(staged, "entity_assignments") == 0


def test_a_write_naming_another_principals_scope_is_refused(staged: Engine) -> None:
    with pytest.raises(UnknownScopeError):
        _write(
            staged,
            "create_assignment",
            _assignment(scope_entity_id=BOB, expected_scope_version=1),
        )
    assert _rows(staged, "entity_assignments") == 0


def test_an_edge_to_another_principals_entity_is_refused(staged: Engine) -> None:
    with pytest.raises(UnknownScopeError):
        _write(staged, "create_relationship", _edge(to_entity_id=BOB))
    assert _rows(staged, "entity_relationships") == 0


def test_one_principals_active_key_does_not_block_anothers(staged: Engine) -> None:
    """The index leads with `principal_id`, so the key is per Principal."""
    _write(staged, "create_assignment", _assignment(role="Lead"))
    with staged.begin() as connection:
        SqlEntityRepository(connection).create(
            PRINCIPAL_B, _entity("ent_eeee0005eeee0005", PRINCIPAL_B, "Bob Two", EntityType.PROJECT)
        )
    _write(
        staged,
        "create_assignment",
        _assignment(
            principal_id=PRINCIPAL_B,
            entity_id=BOB,
            scope_entity_id="ent_eeee0005eeee0005",
            role="Lead",
            idempotency_key="db-assignment-0001",
        ),
    )
    assert _rows(staged, "entity_assignments") == 2


# --- the version guard ------------------------------------------------------


def test_a_stale_revise_writes_no_row_no_ledger_entry_and_leaves_prior_state(
    staged: Engine,
) -> None:
    created = _write(staged, "create_assignment", _assignment(role="Lead"))
    ledger = _rows(staged, "entity_mutation_events")
    with pytest.raises(StaleDirectedVersionError):
        _write(
            staged,
            "revise_assignment",
            _assignment(
                operation=DirectedWriteOperation.REVISE,
                assignment_id=created.record_id,
                expected_version=9,
                entity_id=None,
                assignment_type=None,
                scope_entity_id=None,
                expected_entity_version=None,
                expected_scope_version=None,
                role="Deputy Lead",
                idempotency_key="db-assignment-revise",
            ),
        )
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).assignment(PRINCIPAL_A, created.record_id)
    assert held is not None
    assert held.role == "Lead"
    assert held.version == 1
    assert held.state is AssignmentState.ACTIVE
    assert _rows(staged, "entity_mutation_events") == ledger


def test_a_stale_endpoint_version_refuses_the_create(staged: Engine) -> None:
    with pytest.raises(StaleDirectedVersionError):
        _write(staged, "create_assignment", _assignment(expected_entity_version=4))
    assert _rows(staged, "entity_assignments") == 0


def test_a_merged_away_endpoint_is_refused_rather_than_followed(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).redirect_entity(PRINCIPAL_A, ALICE, ACME)
    with pytest.raises(MergedEndpointError):
        _write(staged, "create_assignment", _assignment(expected_entity_version=2))
    assert _rows(staged, "entity_assignments") == 0


def test_a_revise_keeps_what_it_omits_and_removes_what_it_names(staged: Engine) -> None:
    created = _write(staged, "create_assignment", _assignment(role="Lead", discipline="Structural"))
    _write(
        staged,
        "revise_assignment",
        _assignment(
            operation=DirectedWriteOperation.REVISE,
            assignment_id=created.record_id,
            expected_version=1,
            entity_id=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_entity_version=None,
            expected_scope_version=None,
            role="Deputy Lead",
            cleared=("discipline",),
            idempotency_key="db-assignment-revise",
        ),
    )
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).assignment(PRINCIPAL_A, created.record_id)
    assert held is not None
    assert held.role == "Deputy Lead"
    assert held.discipline is None
    assert held.version == 2


def test_an_end_keeps_the_row_and_records_when_it_left_service(staged: Engine) -> None:
    created = _write(staged, "create_relationship", _edge())
    _write(
        staged,
        "end_relationship",
        _edge(
            operation=DirectedWriteOperation.END,
            relationship_id=created.record_id,
            expected_version=1,
            from_entity_id=None,
            to_entity_id=None,
            relationship_type=None,
            expected_from_version=None,
            expected_to_version=None,
            effective_to=WHEN,
            reason="the engagement ended",
            idempotency_key="db-relationship-end",
        ),
    )
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).relationship(PRINCIPAL_A, created.record_id)
    assert held is not None
    assert held.state is RelationshipState.ENDED
    assert held.ended_at == WHEN
    assert _rows(staged, "entity_relationships") == 1


# --- the ledger, which is this plane's receipt ------------------------------


def test_the_ledger_row_records_the_act_and_both_sides_of_the_change(
    staged: Engine,
) -> None:
    created = _write(staged, "create_assignment", _assignment(role="Lead"))
    _write(
        staged,
        "revise_assignment",
        _assignment(
            operation=DirectedWriteOperation.REVISE,
            assignment_id=created.record_id,
            expected_version=1,
            entity_id=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_entity_version=None,
            expected_scope_version=None,
            role="Deputy Lead",
            idempotency_key="db-assignment-revise",
        ),
    )
    with staged.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT * FROM {SCHEMA}.entity_mutation_events "  # noqa: S608
                "WHERE capability = 'entities.assignments.revise'"
            )
        ).one()
    assert row.record_family == MutationRecordFamily.ASSIGNMENT.value
    assert row.record_id == created.record_id
    assert row.prior_version == 1
    assert row.new_version == 2
    assert row.authority == MutationAuthority.USER_CONFIRMED_ASSERTION.value
    assert row.actor_class == ActorClass.USER.value
    assert row.before_state["role"] == "Lead"
    assert row.after_state["role"] == "Deputy Lead"
    assert row.audit_id == AUDIT
    assert row.receipt_id is None


def test_the_ledger_is_append_only_by_trigger(staged: Engine) -> None:
    """So a mutation record cannot be edited after the fact by anything at all."""
    _write(staged, "create_assignment", _assignment(role="Lead"))
    with pytest.raises(Exception, match=r"append.only"), staged.begin() as connection:
        connection.execute(
            text(f"UPDATE {SCHEMA}.entity_mutation_events SET reason = 'edited'")  # noqa: S608
        )


def test_one_key_is_unique_per_principal_and_capability(staged: Engine) -> None:
    """The idempotency store, arbitrated by the constraint rather than by a read."""
    request = _assignment(role="Lead")
    _write(staged, "create_assignment", request)
    with staged.connect() as connection:
        replayed = SqlEntityRepository(connection).directed_replay(
            "entities.assignments.create",
            request.idempotency_key,
            request.payload_digest,
            principal_id=PRINCIPAL_A,
        )
        free_under_another_capability = SqlEntityRepository(connection).directed_replay(
            "entities.assignments.revise",
            request.idempotency_key,
            request.payload_digest,
            principal_id=PRINCIPAL_A,
        )
        free_for_another_principal = SqlEntityRepository(connection).directed_replay(
            "entities.assignments.create",
            request.idempotency_key,
            request.payload_digest,
            principal_id=PRINCIPAL_B,
        )
    assert replayed is not None
    assert replayed.replayed is True
    assert free_under_another_capability is None
    assert free_for_another_principal is None


def test_the_same_key_with_a_different_request_is_refused(staged: Engine) -> None:
    _write(staged, "create_assignment", _assignment(role="Lead"))
    conflicting = _assignment(role="Deputy Lead")
    with staged.connect() as connection, pytest.raises(DirectedWriteError):
        SqlEntityRepository(connection).directed_replay(
            "entities.assignments.create",
            conflicting.idempotency_key,
            conflicting.payload_digest,
            principal_id=PRINCIPAL_A,
        )


# --- concurrency ------------------------------------------------------------


def test_two_sessions_racing_one_semantic_assignment_produce_one_row(
    staged: Engine,
) -> None:
    """Both pre-reads find nothing; the index decides, and the loser is classified.

    The pre-read in `_refuse_duplicate_assignment` cannot see an uncommitted
    sibling under READ COMMITTED, which is exactly why the refusal has to be
    catchable at the constraint: without that handler the loser leaves as a
    driver exception across a port whose vocabulary is `PortError` and
    `DirectedWriteError`.
    """
    first = staged.connect()
    second = staged.connect()
    try:
        first_transaction = first.begin()
        second_transaction = second.begin()
        SqlEntityRepository(first).create_assignment(_assignment(role="Lead"))
        # The second session's pre-read runs while the first is uncommitted, so
        # it finds no active duplicate and proceeds to the insert.
        second_repository = SqlEntityRepository(second)
        first_transaction.commit()
        with pytest.raises(DuplicateDirectedFactError):
            second_repository.create_assignment(
                _assignment(role="Lead", idempotency_key="db-assignment-0002")
            )
        second_transaction.rollback()
    finally:
        first.close()
        second.close()
    assert _rows(staged, "entity_assignments") == 1


def test_two_sessions_racing_one_semantic_edge_produce_one_row(staged: Engine) -> None:
    first = staged.connect()
    second = staged.connect()
    try:
        first_transaction = first.begin()
        second_transaction = second.begin()
        SqlEntityRepository(first).create_relationship(_edge())
        second_repository = SqlEntityRepository(second)
        first_transaction.commit()
        with pytest.raises(DuplicateDirectedFactError):
            second_repository.create_relationship(_edge(idempotency_key="db-relationship-0002"))
        second_transaction.rollback()
    finally:
        first.close()
        second.close()
    assert _rows(staged, "entity_relationships") == 1


def test_two_sessions_revising_one_assignment_leave_one_winner(staged: Engine) -> None:
    """The guarded `UPDATE` decides, and the loser's rowcount is zero.

    Both sessions read version one and both attempt the same guarded update. The
    second commits after the first, so its predicate matches nothing and it
    refuses -- rather than overwriting a change it never saw.
    """
    created = _write(staged, "create_assignment", _assignment(role="Lead"))

    def revise(role: str, key: str) -> AssignmentWriteRequest:
        return _assignment(
            operation=DirectedWriteOperation.REVISE,
            assignment_id=created.record_id,
            expected_version=1,
            entity_id=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_entity_version=None,
            expected_scope_version=None,
            role=role,
            idempotency_key=key,
        )

    first = staged.connect()
    second = staged.connect()
    try:
        first_transaction = first.begin()
        SqlEntityRepository(first).revise_assignment(revise("Deputy Lead", "db-revise-a"))
        first_transaction.commit()
        second_transaction = second.begin()
        with pytest.raises(StaleDirectedVersionError):
            SqlEntityRepository(second).revise_assignment(revise("Acting Lead", "db-revise-b"))
        second_transaction.rollback()
    finally:
        first.close()
        second.close()
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).assignment(PRINCIPAL_A, created.record_id)
    assert held is not None
    assert held.role == "Deputy Lead"
    assert held.version == 2


# --- the paged read ---------------------------------------------------------


def test_the_page_is_keyset_continued_and_refuses_an_unreachable_cursor(
    staged: Engine,
) -> None:
    first = _write(staged, "create_assignment", _assignment(role="Lead"))
    second = _write(
        staged,
        "create_assignment",
        _assignment(role="Deputy Lead", idempotency_key="db-assignment-0002"),
    )
    ordered = sorted([first.record_id, second.record_id])
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        page = repository.assignments_page(PRINCIPAL_A, ALICE, active_only=True, limit=1)
        continued = repository.assignments_page(
            PRINCIPAL_A,
            ALICE,
            active_only=True,
            limit=10,
            after_assignment_id=ordered[0],
        )
        with pytest.raises(UnknownScopeError):
            repository.assignments_page(
                PRINCIPAL_A,
                ALICE,
                active_only=False,
                limit=10,
                after_assignment_id="asn_absent0001absent1",
            )
    assert [held.assignment_id for held in page] == [ordered[0]]
    assert [held.assignment_id for held in continued] == [ordered[1]]


def test_the_page_cannot_reach_another_principals_assignment(staged: Engine) -> None:
    _write(staged, "create_assignment", _assignment(role="Lead"))
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.assignments_page(PRINCIPAL_A, ALICE, active_only=False, limit=10)
        theirs = repository.assignments_page(PRINCIPAL_B, ALICE, active_only=False, limit=10)
        foreign = repository.assignment(PRINCIPAL_B, mine[0].assignment_id)
        absent = repository.assignment(PRINCIPAL_B, "asn_absent0001absent1")
    assert len(mine) == 1
    assert theirs == []
    assert foreign is None
    assert foreign == absent


# --- the two tests that drive the plane through its own front door ----------
#
# **These are the only two here that go through `ApplicationService.invoke`**,
# and until Phase A's Alembic revision landed they were the two this package
# could not make pass. `authorize` commits an audit row *before* the handler
# runs, and `knowledge.audit_events` carries a stored `capability_is_known`
# CHECK naming the capability vocabulary as of the last revision to freeze it.
# What WP-RI-A-03 declared was not in it, so the audit insert raised a
# `CheckViolation` and the request rendered `internal_error`.
#
# `823e23b6cc63` restates both CHECKs with the full alphabetised list --
# `entity_authoring` on `purpose_is_known` included -- and both tests pass at
# head. They were written rather than deferred because the end-to-end path is
# the one a reviewer has to be able to see, and a package that omitted it would
# be reporting a plane it never drove through its own front door.

LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


class _Runtime:
    """One composed build with the entity plane on, over the real engine.

    Two engines, because that is the composition an operator gets:
    `SqlAlchemyAuditSink` takes its own connection so an audit row survives a
    rollback of the work it authorized, which is `persistence.audit`'s whole
    argument -- and it is also why the refusal below is an `IntegrityError` from
    the audit sink rather than a rolled-back handler.
    """

    def __init__(self, url: str) -> None:
        self.work_engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWorkPort:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            relationship_intelligence_enabled=True,
            # And the write half, which is a second switch: the plane flag
            # alone serves the reads and refuses these six with
            # `unsupported` before a handler runs.
            relationship_intelligence_writes_enabled=True,
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def invoke(self, capability: Capability, command: object) -> ResponseEnvelope:
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=PRINCIPAL_A,
                requested_at=WHEN,
            ),
            command,  # type: ignore[arg-type]
            principal=Principal(
                principal_id=PRINCIPAL_A, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )


@pytest.fixture
def composed(staged: Engine, disposable_database: str) -> Iterator[_Runtime]:
    runtime = _Runtime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()


def test_a_create_through_the_capability_writes_the_record_the_ledger_and_the_audit(
    composed: _Runtime, staged: Engine
) -> None:
    """The whole path: command, handler, record, ledger row, audit row.

    Needs Phase A's Alembic revision to admit the capability name -- see the
    block above for what a missing one does to a request that never reaches its
    handler.
    """
    envelope = composed.invoke(
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            scope_entity_id=TOWER,
            expected_scope_version=1,
            role="Lead",
            idempotency_key="e2e-assignment-0001",
        ),
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    assert envelope.result["state"] == AssignmentState.ACTIVE.value
    assert envelope.result["version"] == 1
    assert _rows(staged, "entity_assignments") == 1
    assert _rows(staged, "entity_mutation_events") == 1
    with staged.connect() as connection:
        audited = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.audit_events "  # noqa: S608
                "WHERE capability = 'entities.assignments.create'"
            )
        ).scalar_one()
    assert audited == 1


def test_a_replay_through_the_capability_writes_no_second_row(
    composed: _Runtime, staged: Engine
) -> None:
    """A retry through the capability finds its own earlier row.

    Needs Phase A's Alembic revision, for the reason the test above does.
    """
    command = CreateEntityRelationship(
        from_entity_id=ALICE,
        expected_from_version=1,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        expected_to_version=1,
        idempotency_key="e2e-relationship-0001",
    )
    first = composed.invoke(Capability.ENTITIES_RELATIONSHIPS_CREATE, command)
    second = composed.invoke(Capability.ENTITIES_RELATIONSHIPS_CREATE, command)
    assert first.error is None, first.error
    assert second.error is None, second.error
    assert first.result is not None
    assert second.result is not None
    assert second.result["record_id"] == first.result["record_id"]
    assert second.result["replayed"] is True
    assert _rows(staged, "entity_relationships") == 1
    assert _rows(staged, "entity_mutation_events") == 1
