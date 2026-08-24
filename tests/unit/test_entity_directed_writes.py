"""The directed-relationship write path without persistence (WP-RI-A-03).

Three layers, and the split is deliberate.

**The domain** decides what a descriptor is, what a reason is, and how the
active semantic key folds free text. Those are rules the schema also encodes, so
`descriptor_key` is checked here for what it *says* and in
`tests/database/test_entity_directed_writes.py` for whether it agrees with the
index that actually decides.

**The commands** decide what a caller may send. Every refusal here is a refusal
of a request, and every one of them names a field and never a value.

**The port requests** decide what the server may add. The two write requests are
where "immutable semantic identity" stops being a sentence and becomes a
constructor that refuses: a revise carrying an entity, a type or a scope is
refused before any repository sees it, because there is no reading of that
request which is a correction rather than a rewrite.

The in-memory double carries the rest -- duplicate refusal, the version guard,
directionality -- and it is the same double `tests/database` measures the SQL
repository against, which is what stops these from proving something only the
fake does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.commands import (
    CreateEntityAssignment,
    CreateEntityRelationship,
    EndEntityAssignment,
    EndEntityRelationship,
    ListEntityAssignments,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.ports import (
    AssignmentWriteRequest,
    RelationshipWriteRequest,
    UnknownScopeError,
)
from my_pa.domain.relationship.entity import (
    MAX_DIRECTED_REASON_CHARACTERS,
    MAX_DIRECTED_TEXT_CHARACTERS,
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
    validate_directed_reason,
    validate_directed_text,
)
from my_pa.domain.relationship.governance import MutationRecordFamily
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
ACME: Final = "ent_bbbb0002bbbb0002"
TOWER: Final = "ent_cccc0003cccc0003"
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"
WHEN: Final = datetime(2026, 8, 23, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 9, 23, 12, tzinfo=UTC)


def _entity(entity_id: str, name: str, entity_type: EntityType, principal: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def world() -> World:
    """Alice, Acme and Tower for one Principal; nothing else."""
    world = World()
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(
            PRINCIPAL, _entity(ALICE, "Alice", EntityType.PERSON, PRINCIPAL)
        )
        unit_of_work.entities.create(
            PRINCIPAL, _entity(ACME, "Acme", EntityType.ORGANIZATION, PRINCIPAL)
        )
        unit_of_work.entities.create(
            PRINCIPAL, _entity(TOWER, "Tower", EntityType.PROJECT, PRINCIPAL)
        )
    return world


def _assignment_request(**overrides: object) -> AssignmentWriteRequest:
    values: dict[str, object] = {
        "operation": DirectedWriteOperation.CREATE,
        "assignment_id": None,
        "principal_id": PRINCIPAL,
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
        "idempotency_key": "unit-assignment-0001",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return AssignmentWriteRequest(**values)  # type: ignore[arg-type]


def _relationship_request(**overrides: object) -> RelationshipWriteRequest:
    values: dict[str, object] = {
        "operation": DirectedWriteOperation.CREATE,
        "relationship_id": None,
        "principal_id": PRINCIPAL,
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
        "idempotency_key": "unit-relationship-0001",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "server_received_at": WHEN,
    }
    values.update(overrides)
    return RelationshipWriteRequest(**values)  # type: ignore[arg-type]


# --- the domain vocabulary --------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (None, ""),
        ("", "   "),
        ("Lead", "lead"),
        ("lead", " LEAD "),
        ("Project Manager", "project manager "),
    ],
)
def test_the_descriptor_fold_treats_these_pairs_as_one_value(left: str | None, right: str) -> None:
    """The application's copy of `COALESCE(lower(trim(x)), '')`.

    Checked against the index that actually decides in
    `tests/database/test_entity_directed_writes.py`: a folding rule stated twice
    and compared once is one rule, and stated twice and never compared it is two
    that drift.
    """
    assert descriptor_key(left) == descriptor_key(right)


def test_the_descriptor_fold_keeps_two_different_roles_apart() -> None:
    assert descriptor_key("Lead") != descriptor_key("Deputy Lead")


def test_a_blank_descriptor_normalizes_to_absent_rather_than_to_the_empty_string() -> None:
    """So the application agrees with the index rather than storing a distinction."""
    assert validate_directed_text("   ", field="role") is None
    assert validate_directed_text("  Lead  ", field="role") == "Lead"


def test_a_descriptor_past_the_ceiling_is_refused() -> None:
    with pytest.raises(DirectedWriteError):
        validate_directed_text("x" * (MAX_DIRECTED_TEXT_CHARACTERS + 1), field="role")


def test_a_reason_is_required_and_bounded() -> None:
    assert validate_directed_reason("  they left the programme  ") == "they left the programme"
    with pytest.raises(DirectedWriteError):
        validate_directed_reason("   ")
    with pytest.raises(DirectedWriteError):
        validate_directed_reason("x" * (MAX_DIRECTED_REASON_CHARACTERS + 1))


# --- what a command may say -------------------------------------------------


def test_a_create_refuses_a_scope_version_without_a_scope() -> None:
    """A version of nothing, and its mirror: an unguarded reference to a record."""
    with pytest.raises(InvalidRequestError):
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            idempotency_key="unit-0001",
            expected_scope_version=1,
        )
    with pytest.raises(InvalidRequestError):
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            idempotency_key="unit-0001",
            scope_entity_id=TOWER,
        )


def test_a_create_refuses_a_window_that_closes_before_it_opens() -> None:
    with pytest.raises(InvalidRequestError):
        CreateEntityAssignment(
            entity_id=ALICE,
            expected_entity_version=1,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            idempotency_key="unit-0001",
            effective_from=LATER,
            effective_to=WHEN,
        )


def test_an_edge_refuses_to_connect_an_entity_to_itself() -> None:
    with pytest.raises(InvalidRequestError):
        CreateEntityRelationship(
            from_entity_id=ALICE,
            expected_from_version=1,
            relationship_type=EntityRelationshipType.WORKS_FOR,
            to_entity_id=ALICE,
            expected_to_version=1,
            idempotency_key="unit-0001",
        )


def test_an_end_names_a_date_or_says_now_and_never_both_or_neither() -> None:
    """Two facts, and guessing which was meant is how a wrong date is recorded."""
    with pytest.raises(InvalidRequestError):
        EndEntityAssignment(
            assignment_id="asn_unit0001unit0001",
            expected_version=1,
            reason="they left",
            idempotency_key="unit-0001",
        )
    with pytest.raises(InvalidRequestError):
        EndEntityAssignment(
            assignment_id="asn_unit0001unit0001",
            expected_version=1,
            reason="they left",
            idempotency_key="unit-0001",
            effective_end=WHEN,
            end_now=True,
        )


def test_an_end_refuses_a_blank_reason() -> None:
    with pytest.raises(InvalidRequestError):
        EndEntityAssignment(
            assignment_id="asn_unit0001unit0001",
            expected_version=1,
            reason="   ",
            idempotency_key="unit-0001",
            end_now=True,
        )


def test_a_revise_refuses_a_field_it_both_states_and_clears() -> None:
    """The contradiction is refused rather than resolved in the caller's favour."""
    with pytest.raises(InvalidRequestError):
        ReviseEntityAssignment(
            assignment_id="asn_unit0001unit0001",
            expected_version=1,
            idempotency_key="unit-0001",
            role="Lead",
            clear=("role",),
        )


def test_a_revise_refuses_a_field_the_family_cannot_clear() -> None:
    """An edge has no descriptors, so `clear=("role",)` names nothing it holds."""
    with pytest.raises(InvalidRequestError):
        ReviseEntityRelationship(
            relationship_id="erel_unit0001unit001",
            expected_version=1,
            idempotency_key="unit-0001",
            clear=("role",),
        )


def test_a_listing_refuses_a_cursor_that_is_not_an_assignment_identifier() -> None:
    with pytest.raises(InvalidRequestError):
        ListEntityAssignments(entity_id=ALICE, after="not-an-identifier")


def test_no_write_command_carries_a_server_owned_field() -> None:
    """The mechanism is absence: there is no field for a caller to supply.

    Asserted over the whole family rather than one command, because the property
    is what stops a payload from claiming an authority, a lifecycle state or a
    version the server owns -- and a single-command version of this test would
    have gone green while the other five carried one.
    """
    forbidden = {
        "principal_id",
        "authority",
        "actor_class",
        "state",
        "version",
        "recorded_at",
        "updated_at",
        "ended_at",
        "superseded_by_assignment_id",
        "superseded_by_relationship_id",
        "assignment_id_override",
    }
    for command in (
        CreateEntityAssignment,
        ReviseEntityAssignment,
        EndEntityAssignment,
        CreateEntityRelationship,
        ReviseEntityRelationship,
        EndEntityRelationship,
        ListEntityAssignments,
    ):
        assert not forbidden & set(command.__dataclass_fields__)


# --- what a write request may say -------------------------------------------


def test_a_revise_request_cannot_carry_a_semantic_identity() -> None:
    """Immutability is a constructor refusal, not a field the repository ignores."""
    with pytest.raises(ValueError, match="only an assignment creation"):
        _assignment_request(
            operation=DirectedWriteOperation.REVISE,
            assignment_id="asn_unit0001unit0001",
            expected_version=1,
            entity_id=ALICE,
            assignment_type=None,
            scope_entity_id=None,
            expected_entity_version=None,
            expected_scope_version=None,
        )
    with pytest.raises(ValueError, match="only an edge creation"):
        _relationship_request(
            operation=DirectedWriteOperation.REVISE,
            relationship_id="erel_unit0001unit001",
            expected_version=1,
            from_entity_id=None,
            to_entity_id=ACME,
            relationship_type=None,
            expected_from_version=None,
            expected_to_version=None,
        )


def test_only_an_end_carries_a_reason() -> None:
    with pytest.raises(ValueError, match="carries a reason"):
        _assignment_request(reason="a reason a create may not give")


def test_the_payload_digest_excludes_what_differs_on_every_attempt() -> None:
    """Two attempts at one request hash the same; a changed field does not."""
    first = _assignment_request()
    second = _assignment_request(
        correlation_id="corr_bbbb0002bbbb0002",
        audit_id="audit_bbbb0002bbbb02",
        server_received_at=LATER,
    )
    assert first.payload_digest == second.payload_digest
    assert first.payload_digest != _assignment_request(role="Lead").payload_digest


def test_the_payload_digest_reads_the_cleared_set() -> None:
    """Otherwise "keep the role" and "remove the role" would be one request."""
    keep = _assignment_request(
        operation=DirectedWriteOperation.REVISE,
        assignment_id="asn_unit0001unit0001",
        expected_version=1,
        entity_id=None,
        assignment_type=None,
        scope_entity_id=None,
        expected_entity_version=None,
        expected_scope_version=None,
    )
    clear = _assignment_request(
        operation=DirectedWriteOperation.REVISE,
        assignment_id="asn_unit0001unit0001",
        expected_version=1,
        entity_id=None,
        assignment_type=None,
        scope_entity_id=None,
        expected_entity_version=None,
        expected_scope_version=None,
        cleared=("role",),
    )
    assert keep.payload_digest != clear.payload_digest


# --- the plane's behaviour, over the double ---------------------------------


def test_a_created_assignment_is_active_at_version_one(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        receipt = unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        held = unit_of_work.entities.assignment(PRINCIPAL, receipt.record_id)
    assert receipt.record_family is MutationRecordFamily.ASSIGNMENT
    assert receipt.prior_version is None
    assert receipt.version == 1
    assert receipt.state == AssignmentState.ACTIVE.value
    assert receipt.replayed is False
    assert held is not None
    assert held.state is AssignmentState.ACTIVE
    assert held.role == "Lead"


def test_a_duplicate_active_assignment_is_refused_case_and_space_insensitively(
    world: World,
) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        with pytest.raises(DuplicateDirectedFactError):
            unit_of_work.entities.create_assignment(
                _assignment_request(role=" LEAD ", idempotency_key="unit-assignment-0002")
            )


def test_a_scope_set_is_a_different_assignment_from_a_scope_absent(world: World) -> None:
    """`COALESCE(scope_entity_id, '')` folds NULL to empty, not to any scope."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        second = unit_of_work.entities.create_assignment(
            _assignment_request(
                role="Lead",
                scope_entity_id=None,
                expected_scope_version=None,
                idempotency_key="unit-assignment-0002",
            )
        )
    assert second.version == 1


def test_an_ended_assignment_frees_the_semantic_key(world: World) -> None:
    """Which is what makes end-and-replace the correction path it is meant to be."""
    with FakeUnitOfWork(world) as unit_of_work:
        first = unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        unit_of_work.entities.end_assignment(
            _assignment_request(
                operation=DirectedWriteOperation.END,
                assignment_id=first.record_id,
                expected_version=1,
                entity_id=None,
                assignment_type=None,
                scope_entity_id=None,
                expected_entity_version=None,
                expected_scope_version=None,
                effective_to=WHEN,
                reason="the role was recorded against the wrong scope",
                idempotency_key="unit-assignment-end",
            )
        )
        replacement = unit_of_work.entities.create_assignment(
            _assignment_request(role="Lead", idempotency_key="unit-assignment-replacement")
        )
        ended = unit_of_work.entities.assignment(PRINCIPAL, first.record_id)
    assert ended is not None
    assert ended.state is AssignmentState.ENDED
    assert ended.ended_at == WHEN
    assert ended.version == 2
    assert replacement.record_id != first.record_id
    assert replacement.version == 1


def test_a_stale_revise_writes_nothing_and_leaves_the_prior_state(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        created = unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        before = len(world.entity_mutation_events)
        with pytest.raises(StaleDirectedVersionError):
            unit_of_work.entities.revise_assignment(
                _assignment_request(
                    operation=DirectedWriteOperation.REVISE,
                    assignment_id=created.record_id,
                    expected_version=9,
                    entity_id=None,
                    assignment_type=None,
                    scope_entity_id=None,
                    expected_entity_version=None,
                    expected_scope_version=None,
                    role="Deputy Lead",
                    idempotency_key="unit-assignment-revise",
                )
            )
        held = unit_of_work.entities.assignment(PRINCIPAL, created.record_id)
    assert held is not None
    assert held.role == "Lead"
    assert held.version == 1
    assert len(world.entity_mutation_events) == before


def test_a_revise_keeps_what_it_does_not_mention_and_clears_what_it_names(
    world: World,
) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        created = unit_of_work.entities.create_assignment(
            _assignment_request(role="Lead", discipline="Structural")
        )
        unit_of_work.entities.revise_assignment(
            _assignment_request(
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
                idempotency_key="unit-assignment-revise",
            )
        )
        held = unit_of_work.entities.assignment(PRINCIPAL, created.record_id)
    assert held is not None
    assert held.role == "Deputy Lead"
    assert held.discipline is None
    assert held.version == 2
    assert held.state is AssignmentState.ACTIVE


def test_the_opposite_direction_of_the_same_pair_is_a_different_edge(world: World) -> None:
    """What a directed model is for, asserted rather than assumed."""
    with FakeUnitOfWork(world) as unit_of_work:
        forward = unit_of_work.entities.create_relationship(_relationship_request())
        backward = unit_of_work.entities.create_relationship(
            _relationship_request(
                from_entity_id=ACME,
                to_entity_id=ALICE,
                idempotency_key="unit-relationship-0002",
            )
        )
    assert forward.record_id != backward.record_id
    assert backward.version == 1


def test_no_reciprocal_edge_is_generated(world: World) -> None:
    """One assertion in, one edge out. The inverse is the user's to state."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create_relationship(_relationship_request())
        edges = unit_of_work.entities.relationships(PRINCIPAL, ALICE)
    assert len(edges) == 1
    assert edges[0].from_entity_id == ALICE
    assert edges[0].to_entity_id == ACME


def test_a_duplicate_active_edge_is_refused(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create_relationship(_relationship_request())
        with pytest.raises(DuplicateDirectedFactError):
            unit_of_work.entities.create_relationship(
                _relationship_request(idempotency_key="unit-relationship-0002")
            )


def test_a_different_type_between_the_same_pair_is_a_different_edge(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create_relationship(_relationship_request())
        second = unit_of_work.entities.create_relationship(
            _relationship_request(
                relationship_type=EntityRelationshipType.CONSULTANT_TO,
                idempotency_key="unit-relationship-0002",
            )
        )
    assert second.version == 1


def test_ending_one_edge_leaves_its_inverse_untouched(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        forward = unit_of_work.entities.create_relationship(_relationship_request())
        backward = unit_of_work.entities.create_relationship(
            _relationship_request(
                from_entity_id=ACME,
                to_entity_id=ALICE,
                idempotency_key="unit-relationship-0002",
            )
        )
        unit_of_work.entities.end_relationship(
            _relationship_request(
                operation=DirectedWriteOperation.END,
                relationship_id=forward.record_id,
                expected_version=1,
                from_entity_id=None,
                to_entity_id=None,
                relationship_type=None,
                expected_from_version=None,
                expected_to_version=None,
                effective_to=WHEN,
                reason="the engagement ended",
                idempotency_key="unit-relationship-end",
            )
        )
        ended = unit_of_work.entities.relationship(PRINCIPAL, forward.record_id)
        untouched = unit_of_work.entities.relationship(PRINCIPAL, backward.record_id)
    assert ended is not None
    assert ended.state is RelationshipState.ENDED
    assert untouched is not None
    assert untouched.state is RelationshipState.ACTIVE
    assert untouched.version == 1


def test_a_write_refuses_an_entity_at_a_version_the_caller_did_not_read(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work, pytest.raises(StaleDirectedVersionError):
        unit_of_work.entities.create_assignment(_assignment_request(expected_entity_version=4))


def test_a_write_refuses_a_scope_at_a_version_the_caller_did_not_read(world: World) -> None:
    """The scope is guarded too: a create binds a new row to *two* entities."""
    with FakeUnitOfWork(world) as unit_of_work, pytest.raises(StaleDirectedVersionError):
        unit_of_work.entities.create_assignment(_assignment_request(expected_scope_version=4))


def test_a_write_refuses_a_merged_away_endpoint_rather_than_following_it(world: World) -> None:
    """Following the redirect would record a fact about an identity nobody chose."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.redirect_entity(PRINCIPAL, ALICE, ACME)
        with pytest.raises(MergedEndpointError):
            unit_of_work.entities.create_assignment(_assignment_request())


def test_a_write_naming_another_principals_entity_is_refused_as_absent(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(
            OTHER_PRINCIPAL,
            _entity("ent_dddd0004dddd0004", "Foreign", EntityType.PERSON, OTHER_PRINCIPAL),
        )
        with pytest.raises(UnknownScopeError):
            unit_of_work.entities.create_assignment(
                _assignment_request(entity_id="ent_dddd0004dddd0004")
            )


# --- idempotency ------------------------------------------------------------


def test_an_exact_replay_returns_the_original_receipt_and_writes_nothing(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        request = _assignment_request(role="Lead")
        created = unit_of_work.entities.create_assignment(request)
        rows = len(world.entity_assignments)
        replayed = unit_of_work.entities.directed_replay(
            "entities.assignments.create",
            request.idempotency_key,
            request.payload_digest,
            principal_id=PRINCIPAL,
        )
    assert replayed is not None
    assert replayed.record_id == created.record_id
    assert replayed.version == created.version
    assert replayed.replayed is True
    assert len(world.entity_assignments) == rows


def test_the_same_key_with_a_different_request_is_a_conflict(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        request = _assignment_request(role="Lead")
        unit_of_work.entities.create_assignment(request)
        conflicting = _assignment_request(role="Deputy Lead")
        with pytest.raises(DirectedWriteError):
            unit_of_work.entities.directed_replay(
                "entities.assignments.create",
                conflicting.idempotency_key,
                conflicting.payload_digest,
                principal_id=PRINCIPAL,
            )


def test_one_key_is_free_under_a_different_capability(world: World) -> None:
    """The ledger's unique is `(principal, capability, key)`, and that is honest.

    A caller that reuses one key across `create` and `revise` is making two
    writes, not one: they are different acts on different state.
    """
    with FakeUnitOfWork(world) as unit_of_work:
        request = _assignment_request(role="Lead")
        unit_of_work.entities.create_assignment(request)
        assert (
            unit_of_work.entities.directed_replay(
                "entities.assignments.revise",
                request.idempotency_key,
                request.payload_digest,
                principal_id=PRINCIPAL,
            )
            is None
        )


def test_one_key_held_by_another_principal_is_not_this_principals_replay(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        request = _assignment_request(role="Lead")
        unit_of_work.entities.create_assignment(request)
        assert (
            unit_of_work.entities.directed_replay(
                "entities.assignments.create",
                request.idempotency_key,
                request.payload_digest,
                principal_id=OTHER_PRINCIPAL,
            )
            is None
        )


# --- the paged read ---------------------------------------------------------


def test_the_assignment_page_is_keyset_continued_and_defaults_to_the_live_set(
    world: World,
) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        first = unit_of_work.entities.create_assignment(_assignment_request(role="Lead"))
        second = unit_of_work.entities.create_assignment(
            _assignment_request(role="Deputy Lead", idempotency_key="unit-assignment-0002")
        )
        unit_of_work.entities.end_assignment(
            _assignment_request(
                operation=DirectedWriteOperation.END,
                assignment_id=first.record_id,
                expected_version=1,
                entity_id=None,
                assignment_type=None,
                scope_entity_id=None,
                expected_entity_version=None,
                expected_scope_version=None,
                effective_to=WHEN,
                reason="the role ended",
                idempotency_key="unit-assignment-end",
            )
        )
        live = unit_of_work.entities.assignments_page(PRINCIPAL, ALICE, active_only=True, limit=10)
        historical = unit_of_work.entities.assignments_page(
            PRINCIPAL, ALICE, active_only=False, limit=10
        )
        continued = unit_of_work.entities.assignments_page(
            PRINCIPAL,
            ALICE,
            active_only=False,
            limit=10,
            after_assignment_id=min(first.record_id, second.record_id),
        )
    assert [held.assignment_id for held in live] == [second.record_id]
    assert len(historical) == 2
    assert len(continued) == 1
    assert continued[0].assignment_id == max(first.record_id, second.record_id)


def test_a_cursor_naming_an_unreachable_assignment_is_refused_rather_than_emptied(
    world: World,
) -> None:
    with FakeUnitOfWork(world) as unit_of_work, pytest.raises(UnknownScopeError):
        unit_of_work.entities.assignments_page(
            PRINCIPAL,
            ALICE,
            active_only=False,
            limit=10,
            after_assignment_id="asn_absent0001absent1",
        )
