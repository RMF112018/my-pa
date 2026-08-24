"""What a governed entity write decides, and what it refuses to decide.

`tests/database/test_entity_authoring.py` drives the same use cases against a
real server and proves the constraints hold. This drives them against the
in-memory double and proves the *contract*: which field a caller may supply,
which refusal each failure is, and what a request that was refused left behind.

Three claims carry this file.

**A caller cannot state what the server owns.** Every command below is
constructed directly, so a field that does not exist is a `TypeError` at the
constructor rather than a rule somewhere downstream. The Principal, the version,
the canonical name, the authority and every identifier are supplied by
`EntityAuthoringService`, and the tests that matter here are the ones that show a
caller reaching for one and finding nothing to hold.

**A refusal is typed, and the type is the answer.** `bind_identifier` answered a
permanent conflict and a retryable race with one `ValueError` until
`WP-RI-A-02`; the tests below assert the two classes and the two public codes,
because a caller told `conflict` for the second abandons a write that would have
succeeded.

**A replay is not a second write.** The idempotency key is asserted in all three
of its states: the same key with the same payload answers with the original
receipt and writes nothing, the same key with a different payload is refused,
and a different key writes again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.entity_authoring import EntityAuthoringService, NamedValue
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import (
    EntityWriteRequest,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.authoring import (
    CALLER_SETTABLE_STATUSES,
    AmbiguousEntityError,
    CallerNamespace,
    ConflictedIdentifierError,
    DuplicateEntityFactError,
    EntityIdempotencyConflictError,
    EntityWriteOperation,
    HistoricalEntityError,
    StaleEntityVersionError,
    UnsettledBindingError,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityStatus,
    EntityType,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, World

WHEN: Final = datetime(2026, 8, 20, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 21, 12, tzinfo=UTC)

MINE: Final = "prn_aaaa0001aaaa0001aaaa0001"
THEIRS: Final = "prn_bbbb0002bbbb0002bbbb0002"


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def service() -> EntityAuthoringService:
    return EntityAuthoringService()


def repository(world: World) -> object:
    return FakeUnitOfWork(world).entities


def an_entity(
    world: World,
    *,
    principal_id: str = MINE,
    display_name: str = "Sarah Chen",
    status: EntityStatus = EntityStatus.ACTIVE,
    entity_type: EntityType = EntityType.PERSON,
    version: int = 1,
    superseded_by: str | None = None,
    archived_from: EntityStatus | None = None,
) -> Entity:
    """One entity written through the port, so it is a row a writer could produce."""
    return FakeUnitOfWork(world).entities.create(  # type: ignore[no-any-return]
        principal_id,
        Entity(
            entity_id=issue_identifier(IdKind.ENTITY),
            principal_id=principal_id,
            entity_type=entity_type,
            canonical_name=normalize_name(display_name),
            display_name=display_name,
            status=status,
            created_at=WHEN,
            updated_at=WHEN,
            version=version,
            superseded_by_entity_id=superseded_by,
            archived_from_status=archived_from,
        ),
    )


def context() -> dict[str, object]:
    """The three server-supplied values every call takes, in one place."""
    return {
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": LATER,
    }


# --- the request: what a caller may supply, and what it may never ------------


def a_request(**overrides: object) -> EntityWriteRequest:
    """One well-formed create request, with named fields replaced."""
    fields: dict[str, object] = {
        "operation": EntityWriteOperation.CREATE,
        "capability": "entities.create",
        "principal_id": MINE,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "idempotency_key": "key-0001",
        "server_received_at": WHEN,
        "event_id": issue_identifier(IdKind.ENTITY_MUTATION_EVENT),
        "entity_id": None,
        "expected_version": None,
        "minted_entity_id": issue_identifier(IdKind.ENTITY),
        "entity_type": EntityType.PERSON,
        "display_name": "Sarah Chen",
        "canonical_name": normalize_name("Sarah Chen"),
    }
    fields.update(overrides)
    return EntityWriteRequest(**fields)  # type: ignore[arg-type]


def test_the_digest_ignores_every_value_this_layer_minted() -> None:
    """Two attempts at one request are a replay, not a conflict.

    The identifiers, the correlation identifier, the audit identifier and the
    receipt time differ on every attempt by construction. A digest that read any
    of them would make every retry a fresh key -- which is to say, no idempotency
    at all.
    """
    first = a_request()
    second = a_request(
        minted_entity_id=issue_identifier(IdKind.ENTITY),
        event_id=issue_identifier(IdKind.ENTITY_MUTATION_EVENT),
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        server_received_at=LATER,
    )
    assert first.payload_digest == second.payload_digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", "Sara Chen"),
        ("canonical_name", normalize_name("Sara Chen")),
        ("entity_type", EntityType.ORGANIZATION),
        ("reason", "a different reason"),
        ("capability", "entities.update"),
        ("operation", EntityWriteOperation.CREATE),
    ],
)
def test_the_digest_reads_every_value_a_caller_supplied(field: str, value: object) -> None:
    """Per field, so a failure names the one that stopped being compared.

    `operation` is in the list and is the control: the value is the one the
    baseline already carries, so this row must *not* differ. A parameterization
    where every row differed would pass with a digest over a constant.
    """
    changed = a_request(**{field: value})
    baseline = a_request()
    if field == "operation":
        assert changed.payload_digest == baseline.payload_digest
        return
    assert changed.payload_digest != baseline.payload_digest


def test_the_digest_reads_the_evidence_a_request_cites() -> None:
    """Two requests citing different evidence are different requests.

    Answering the second from the first's receipt would report evidence as
    recorded that never was.
    """
    span = issue_identifier(IdKind.SPAN)
    cited = a_request(
        evidence=(span,),
        minted_evidence_link_ids=(issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),),
    )
    assert cited.payload_digest != a_request().payload_digest


def test_a_create_names_no_entity_and_every_other_operation_does() -> None:
    with pytest.raises(ValueError, match="creation names no entity"):
        a_request(entity_id=issue_identifier(IdKind.ENTITY))


def test_a_state_dependent_write_names_the_version_it_expects() -> None:
    with pytest.raises(ValueError, match="names the version it expects"):
        a_request(expected_version=1)


def test_a_child_transition_names_the_record_it_transitions() -> None:
    with pytest.raises(ValueError, match="names the record it transitions"):
        a_request(
            operation=EntityWriteOperation.RETIRE_ALIAS,
            capability="entities.aliases.retire",
            entity_id=issue_identifier(IdKind.ENTITY),
            expected_version=1,
            minted_entity_id=None,
            entity_type=None,
            display_name=None,
            canonical_name=None,
        )


def test_a_request_carries_a_bounded_number_of_evidence_records() -> None:
    spans = tuple(issue_identifier(IdKind.SPAN) for _ in range(9))
    links = tuple(issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK) for _ in spans)
    with pytest.raises(ValueError, match="bounded number of evidence"):
        a_request(evidence=spans, minted_evidence_link_ids=links)


def test_a_request_mints_one_link_identifier_per_evidence_record() -> None:
    with pytest.raises(ValueError, match="one link identifier per evidence"):
        a_request(evidence=(issue_identifier(IdKind.SPAN),))


def test_the_record_family_follows_the_operation() -> None:
    """What the ledger says one row is about, derived rather than passed in."""
    entity_id = issue_identifier(IdKind.ENTITY)
    common: dict[str, object] = {
        "entity_id": entity_id,
        "expected_version": 1,
        "minted_entity_id": None,
        "entity_type": None,
        "display_name": None,
        "canonical_name": None,
    }
    assert (
        a_request(
            operation=EntityWriteOperation.BIND_IDENTIFIER,
            capability="entities.identifiers.bind",
            minted_child_id=issue_identifier(IdKind.EXTERNAL_IDENTIFIER),
            **common,
        ).record_family.value
        == "identifier"
    )
    assert (
        a_request(
            operation=EntityWriteOperation.ADD_ALIAS,
            capability="entities.aliases.add",
            minted_child_id=issue_identifier(IdKind.ENTITY_ALIAS),
            **common,
        ).record_family.value
        == "alias"
    )
    assert (
        a_request(
            operation=EntityWriteOperation.ARCHIVE,
            capability="entities.archive",
            **common,
        ).record_family.value
        == "entity"
    )


# --- create: duplicate resolution refuses rather than choosing ---------------


def test_a_create_mints_the_identifier_the_version_and_the_status(
    world: World, service: EntityAuthoringService
) -> None:
    """Server-owned throughout, and there is no field a caller could have used."""
    admission = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(),
        identifiers=(),
        reason="A synthetic creation.",
        idempotency_key="create-0001",
        **context(),  # type: ignore[arg-type]
    )
    receipt = admission.receipt
    assert admission.created
    assert receipt.entity_version == 1
    assert receipt.entity_status is EntityStatus.ACTIVE
    stored = FakeUnitOfWork(world).entities.get(MINE, receipt.entity_id)
    assert stored is not None
    assert stored.canonical_name == normalize_name("Sarah Chen")
    assert stored.display_name == "Sarah Chen"


def test_a_create_refuses_an_address_another_entity_currently_holds(
    world: World, service: EntityAuthoringService
) -> None:
    """`conflicted_identifier`, and the existing entity is not returned.

    Linking to what it found would be a merge performed as a side effect of a
    create, which section 15.2 reserves from automatic action.
    """
    held = an_entity(world, display_name="Sarah Chen")
    _bind(world, held.entity_id, "sarah@example.invalid")
    before = len(world.entities)
    with pytest.raises(ConflictedIdentifierError):
        service.create(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_type=EntityType.PERSON,
            display_name="Sarah Q Chen",
            aliases=(),
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
            reason=None,
            idempotency_key="create-0002",
            **context(),  # type: ignore[arg-type]
        )
    assert len(world.entities) == before


def test_a_create_with_no_identity_refuses_a_name_that_already_exists(
    world: World, service: EntityAuthoringService
) -> None:
    """`ambiguous_identity`: a name alone decides nothing in either direction."""
    an_entity(world, display_name="Sarah Chen")
    with pytest.raises(AmbiguousEntityError):
        service.create(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_type=EntityType.PERSON,
            display_name="Sarah Chen",
            aliases=(),
            identifiers=(),
            reason=None,
            idempotency_key="create-0003",
            **context(),  # type: ignore[arg-type]
        )


def test_a_create_carrying_an_unheld_identity_admits_a_genuine_namesake(
    world: World, service: EntityAuthoringService
) -> None:
    """The other half of the rule, and the reason the plane is usable.

    Two real people share a name. A create that refused on name equality with no
    way past it would make the second Sarah Chen unrecordable and push a user
    into editing the first -- the false join this plane exists to avoid, reached
    by refusing to admit a true fact. An exact identifier nobody holds is section
    15.2's "strong evidence" that this is somebody else.
    """
    first = an_entity(world, display_name="Sarah Chen")
    admission = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(),
        identifiers=(NamedValue("email", "s.chen@other.invalid"),),
        reason="A second person of the same name.",
        idempotency_key="create-0004",
        **context(),  # type: ignore[arg-type]
    )
    assert admission.receipt.entity_id != first.entity_id


def test_a_create_of_a_name_another_type_carries_is_not_ambiguous(
    world: World, service: EntityAuthoringService
) -> None:
    """A project and a person may share a name; neither is evidence about the other."""
    an_entity(world, display_name="Northwind", entity_type=EntityType.ORGANIZATION)
    admission = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PROJECT,
        display_name="Northwind",
        aliases=(),
        identifiers=(),
        reason=None,
        idempotency_key="create-0005",
        **context(),  # type: ignore[arg-type]
    )
    assert admission.created


def test_a_create_records_the_aliases_and_identities_it_was_given(
    world: World, service: EntityAuthoringService
) -> None:
    admission = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(NamedValue("nickname", "Sar"),),
        identifiers=(NamedValue("email", "Sarah.Chen@Example.Invalid"),),
        reason=None,
        idempotency_key="create-0006",
        **context(),  # type: ignore[arg-type]
    )
    entity_id = admission.receipt.entity_id
    alias = next(held for held in world.entity_aliases if held.entity_id == entity_id)
    identifier = next(held for held in world.entity_identifiers if held.entity_id == entity_id)
    assert alias.normalized_value == normalize_name("Sar")
    assert alias.display_value == "Sar"
    # The *server* normalized it, so the matched form is the algorithm's rather
    # than whatever casing the source happened to use.
    assert identifier.normalized_value == normalize_identifier(
        ExternalIdentifierNamespace.EMAIL, "Sarah.Chen@Example.Invalid"
    )
    assert identifier.display_value == "Sarah.Chen@Example.Invalid"


# --- idempotency: three states, told apart ----------------------------------


def test_a_replayed_key_answers_with_the_original_receipt_and_writes_nothing(
    world: World, service: EntityAuthoringService
) -> None:
    first = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(),
        identifiers=(),
        reason=None,
        idempotency_key="replay-0001",
        **context(),  # type: ignore[arg-type]
    )
    after_first = len(world.entities)
    second = service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(),
        identifiers=(),
        reason=None,
        idempotency_key="replay-0001",
        **context(),  # type: ignore[arg-type]
    )
    assert first.created
    assert not second.created
    assert second.receipt.entity_id == first.receipt.entity_id
    assert second.receipt.event_id == first.receipt.event_id
    assert not second.receipt.created
    assert len(world.entities) == after_first


def test_a_key_reused_with_a_different_payload_is_refused(
    world: World, service: EntityAuthoringService
) -> None:
    """Answering it with the original receipt would report a write that never happened."""
    service.create(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_type=EntityType.PERSON,
        display_name="Sarah Chen",
        aliases=(),
        identifiers=(),
        reason=None,
        idempotency_key="conflict-0001",
        **context(),  # type: ignore[arg-type]
    )
    with pytest.raises(EntityIdempotencyConflictError):
        service.create(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_type=EntityType.PERSON,
            display_name="Someone Else",
            aliases=(),
            identifiers=(),
            reason=None,
            idempotency_key="conflict-0001",
            **context(),  # type: ignore[arg-type]
        )


def test_one_key_spent_on_two_capabilities_is_two_writes(
    world: World, service: EntityAuthoringService
) -> None:
    """The unique is `(principal, capability, key)` and the test says why.

    A key replayed against a *different* capability is a different request, and
    answering it from the first row would hand a caller a receipt for a write it
    never asked for.
    """
    held = an_entity(world)
    service.add_alias(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Sar",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason=None,
        idempotency_key="shared-key",
        **context(),  # type: ignore[arg-type]
    )
    admission = service.archive(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=2,
        reason="A synthetic withdrawal.",
        idempotency_key="shared-key",
        **context(),  # type: ignore[arg-type]
    )
    assert admission.created


# --- optimistic concurrency: a stale write leaves nothing --------------------


def test_a_stale_expected_version_writes_nothing(
    world: World, service: EntityAuthoringService
) -> None:
    held = an_entity(world, version=3)
    with pytest.raises(StaleEntityVersionError):
        service.update(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=2,
            display_name="Sarah Q Chen",
            canonical_name=None,
            status=None,
            reason="A synthetic correction.",
            idempotency_key="stale-0001",
            **context(),  # type: ignore[arg-type]
        )
    stored = FakeUnitOfWork(world).entities.get(MINE, held.entity_id)
    assert stored is not None
    assert stored.display_name == "Sarah Chen"
    assert stored.version == 3
    assert world.entity_mutations == {}


def test_a_child_write_advances_the_entity_version(
    world: World, service: EntityAuthoringService
) -> None:
    """The entity is the aggregate, so binding an address moves its version.

    A caller that bound one address and then tried to bind a second using the
    version it read before the first is refused, which is the point.
    """
    held = an_entity(world)
    first = service.bind_identifier(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        namespace=CallerNamespace.EMAIL,
        display_value="sarah@example.invalid",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason=None,
        idempotency_key="bind-0001",
        **context(),  # type: ignore[arg-type]
    )
    assert first.receipt.entity_version == 2
    with pytest.raises(StaleEntityVersionError):
        service.bind_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=1,
            namespace=CallerNamespace.TEAMS_USER_ID,
            display_value="sarah-teams",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="bind-0002",
            **context(),  # type: ignore[arg-type]
        )


def test_a_stale_child_version_is_refused_even_when_the_entity_is_current(
    world: World, service: EntityAuthoringService
) -> None:
    """Two expectations, and either one being stale refuses the write."""
    held = an_entity(world)
    identifier = _bind(world, held.entity_id, "sarah@example.invalid")
    with pytest.raises(StaleEntityVersionError):
        service.retire_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=1,
            identifier_id=identifier,
            expected_identifier_version=2,
            reason="A synthetic retirement.",
            idempotency_key="retire-0001",
            **context(),  # type: ignore[arg-type]
        )


# --- lifecycle: archive records what restore returns to ----------------------


def test_an_archive_records_the_status_it_withdrew_from(
    world: World, service: EntityAuthoringService
) -> None:
    """An entity that was `historical` must not come back claiming to be current."""
    held = an_entity(world, status=EntityStatus.HISTORICAL)
    service.archive(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        reason="A synthetic withdrawal.",
        idempotency_key="archive-0001",
        **context(),  # type: ignore[arg-type]
    )
    withdrawn = FakeUnitOfWork(world).entities.get(MINE, held.entity_id)
    assert withdrawn is not None
    assert withdrawn.status is EntityStatus.ARCHIVED
    assert withdrawn.archived_from_status is EntityStatus.HISTORICAL
    restored = service.restore(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=2,
        reason="A synthetic restoration.",
        idempotency_key="restore-0001",
        **context(),  # type: ignore[arg-type]
    )
    assert restored.receipt.entity_status is EntityStatus.HISTORICAL


def test_an_entity_that_is_not_archived_cannot_be_restored(
    world: World, service: EntityAuthoringService
) -> None:
    held = an_entity(world)
    with pytest.raises(DuplicateEntityFactError):
        service.restore(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=1,
            reason="A synthetic restoration.",
            idempotency_key="restore-0002",
            **context(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("operation", ["archive", "restore", "update"])
def test_a_merged_redirect_refuses_every_lifecycle_write(
    world: World, service: EntityAuthoringService, operation: str
) -> None:
    """`historical_entity`, and the successor is what the caller should retarget to.

    Archiving a redirect would leave a pointer whose target is reachable and
    whose source is not, which is a state no reader could act on.
    """
    survivor = an_entity(world, display_name="Sarah Chen")
    merged = an_entity(
        world,
        display_name="Sarah Chenn",
        status=EntityStatus.MERGED_REDIRECT,
        superseded_by=survivor.entity_id,
    )
    calls = {
        "archive": lambda: service.archive(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=merged.entity_id,
            expected_version=1,
            reason="A synthetic withdrawal.",
            idempotency_key=f"merged-{operation}",
            **context(),  # type: ignore[arg-type]
        ),
        "restore": lambda: service.restore(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=merged.entity_id,
            expected_version=1,
            reason="A synthetic restoration.",
            idempotency_key=f"merged-{operation}",
            **context(),  # type: ignore[arg-type]
        ),
        "update": lambda: service.update(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=merged.entity_id,
            expected_version=1,
            display_name="Sarah Chen",
            canonical_name=None,
            status=None,
            reason="A synthetic correction.",
            idempotency_key=f"merged-{operation}",
            **context(),  # type: ignore[arg-type]
        ),
    }
    with pytest.raises(HistoricalEntityError) as refusal:
        calls[operation]()
    assert survivor.entity_id in str(refusal.value)


def test_a_caller_may_not_set_archived_or_merged_through_an_update() -> None:
    """Refused at the command, because each is written by the capability that owns it.

    `archived` travels with `archived_from_status`, which is what makes the
    withdrawal reversible; `merged_redirect` travels with a survivor, which is a
    governed merge rather than a field.
    """
    from my_pa.application.commands import UpdateEntity

    for status in (EntityStatus.ARCHIVED, EntityStatus.MERGED_REDIRECT):
        assert status not in CALLER_SETTABLE_STATUSES
        with pytest.raises(InvalidRequestError) as refusal:
            UpdateEntity(
                entity_id=issue_identifier(IdKind.ENTITY),
                expected_version=1,
                reason="A synthetic correction.",
                idempotency_key="update-0001",
                status=status,
            )
        assert refusal.value.safe_details == (SafeDetail.STATUS,)


def test_a_canonical_name_correction_preserves_the_prior_name_as_a_former_name(
    world: World, service: EntityAuthoringService
) -> None:
    """A reference written under the old name still has to resolve."""
    held = an_entity(world, display_name="Sarah Chenn")
    admission = service.update(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        display_name=None,
        canonical_name="Sarah Chen",
        status=None,
        reason="A misspelling.",
        idempotency_key="rename-0001",
        **context(),  # type: ignore[arg-type]
    )
    former = next(
        held for held in world.entity_aliases if held.entity_id == admission.receipt.entity_id
    )
    assert former.alias_type is AliasType.FORMER_NAME
    assert former.normalized_value == normalize_name("Sarah Chenn")
    assert former.display_value == "Sarah Chenn"
    assert admission.receipt.child_id == former.alias_id


def test_a_display_name_correction_leaves_the_matched_form_alone(
    world: World, service: EntityAuthoringService
) -> None:
    """Cosmetic, so it records no former name and re-points no lookup."""
    held = an_entity(world, display_name="Sarah Chen")
    service.update(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        display_name="Dr Sarah Chen",
        canonical_name=None,
        status=None,
        reason="A title.",
        idempotency_key="display-0001",
        **context(),  # type: ignore[arg-type]
    )
    stored = FakeUnitOfWork(world).entities.get(MINE, held.entity_id)
    assert stored is not None
    assert stored.display_name == "Dr Sarah Chen"
    assert stored.canonical_name == normalize_name("Sarah Chen")
    assert world.entity_aliases == []


# --- identifiers: one active claimant, never transferred ---------------------


def test_an_address_another_entity_holds_is_a_permanent_conflict(
    world: World, service: EntityAuthoringService
) -> None:
    """`ConflictedIdentifierError`, and never a silent transfer."""
    holder = an_entity(world, display_name="Sarah Chen")
    _bind(world, holder.entity_id, "sarah@example.invalid")
    other = an_entity(world, display_name="Sara Chen")
    with pytest.raises(ConflictedIdentifierError):
        service.bind_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=other.entity_id,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="sarah@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="conflict-bind",
            **context(),  # type: ignore[arg-type]
        )


def test_the_two_binding_refusals_are_different_classes() -> None:
    """The defect this typing exists to prevent, stated as a property.

    Both refusals still subclass `ValueError`, so every existing handler is
    unchanged; a handler that classified only `ValueError` reported the
    retryable race as the permanent conflict, telling a caller to stop when the
    address may already be free.
    """
    assert issubclass(ConflictedIdentifierError, ValueError)
    assert issubclass(UnsettledBindingError, ValueError)
    assert not issubclass(ConflictedIdentifierError, UnsettledBindingError)
    assert not issubclass(UnsettledBindingError, ConflictedIdentifierError)


def test_re_binding_an_address_this_entity_already_holds_is_a_duplicate(
    world: World, service: EntityAuthoringService
) -> None:
    """Refused rather than absorbed, and the difference from the port is deliberate.

    `EntitiesRepository.bind_identifier` treats a re-bind as a no-op, which is
    right for a resolution path that binds what it finds. A governed write that
    did the same would hand back a receipt for a binding it did not make.
    """
    held = an_entity(world)
    _bind(world, held.entity_id, "sarah@example.invalid")
    with pytest.raises(DuplicateEntityFactError):
        service.bind_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="sarah@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="duplicate-bind",
            **context(),  # type: ignore[arg-type]
        )


def test_a_supersede_writes_the_replacement_and_points_the_old_row_at_it(
    world: World, service: EntityAuthoringService
) -> None:
    """One step, because between a retire and a bind the entity has no address."""
    held = an_entity(world)
    identifier = _bind(world, held.entity_id, "sarah@example.invalid")
    admission = service.supersede_identifier(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        identifier_id=identifier,
        expected_identifier_version=1,
        namespace=CallerNamespace.EMAIL,
        display_value="s.chen@example.invalid",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason="The address changed.",
        idempotency_key="supersede-0001",
        **context(),  # type: ignore[arg-type]
    )
    old = next(held for held in world.entity_identifiers if held.identifier_id == identifier)
    assert old.state is IdentifierState.SUPERSEDED
    assert old.superseded_by_identifier_id == admission.receipt.child_id
    assert admission.receipt.superseded_ids == (identifier,)
    replacement = next(
        held
        for held in world.entity_identifiers
        if held.identifier_id == admission.receipt.child_id
    )
    assert replacement.state is IdentifierState.ACTIVE


def test_a_retired_binding_cannot_be_retired_twice(
    world: World, service: EntityAuthoringService
) -> None:
    """`duplicate_fact`, which is not `stale_version`: the transition is unavailable."""
    held = an_entity(world)
    identifier = _bind(world, held.entity_id, "sarah@example.invalid")
    service.retire_identifier(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        identifier_id=identifier,
        expected_identifier_version=1,
        reason="A synthetic retirement.",
        idempotency_key="retire-a",
        **context(),  # type: ignore[arg-type]
    )
    with pytest.raises(StaleEntityVersionError):
        service.retire_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=2,
            identifier_id=identifier,
            expected_identifier_version=1,
            reason="A synthetic retirement.",
            idempotency_key="retire-b",
            **context(),  # type: ignore[arg-type]
        )
    with pytest.raises(DuplicateEntityFactError):
        service.retire_identifier(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=2,
            identifier_id=identifier,
            expected_identifier_version=2,
            reason="A synthetic retirement.",
            idempotency_key="retire-c",
            **context(),  # type: ignore[arg-type]
        )


def test_an_address_retired_from_one_entity_may_be_bound_to_another(
    world: World, service: EntityAuthoringService
) -> None:
    """A reissued mailbox, which the partial unique exists to make recordable."""
    first = an_entity(world, display_name="Sarah Chen")
    identifier = _bind(world, first.entity_id, "shared@example.invalid")
    service.retire_identifier(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=first.entity_id,
        expected_version=1,
        identifier_id=identifier,
        expected_identifier_version=1,
        reason="They left.",
        idempotency_key="reissue-retire",
        **context(),  # type: ignore[arg-type]
    )
    second = an_entity(world, display_name="Sara Chen")
    admission = service.bind_identifier(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=second.entity_id,
        expected_version=1,
        namespace=CallerNamespace.EMAIL,
        display_value="shared@example.invalid",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason="The address was reissued.",
        idempotency_key="reissue-bind",
        **context(),  # type: ignore[arg-type]
    )
    assert admission.created
    # And the row that resolves a message sent before the reissue is still there.
    retired = next(held for held in world.entity_identifiers if held.identifier_id == identifier)
    assert retired.state is IdentifierState.RETIRED


# --- aliases: a shared name is a fact, not a collision -----------------------


def test_two_entities_may_carry_the_same_active_alias(
    world: World, service: EntityAuthoringService
) -> None:
    """Two real people share a name, and a schema that refused it would join them."""
    first = an_entity(world, display_name="Sarah Chen")
    second = an_entity(world, display_name="Sarah Chenh")
    for index, entity in enumerate((first, second)):
        admission = service.add_alias(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=entity.entity_id,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key=f"shared-alias-{index}",
            **context(),  # type: ignore[arg-type]
        )
        assert admission.created
    assert len(world.entity_aliases) == 2


def test_one_entity_may_not_carry_the_same_alias_twice_under_one_type(
    world: World, service: EntityAuthoringService
) -> None:
    held = an_entity(world)
    service.add_alias(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Sar",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason=None,
        idempotency_key="alias-a",
        **context(),  # type: ignore[arg-type]
    )
    with pytest.raises(DuplicateEntityFactError):
        service.add_alias(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=held.entity_id,
            expected_version=2,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="alias-b",
            **context(),  # type: ignore[arg-type]
        )


def test_an_alias_supersede_names_the_correction_that_replaced_it(
    world: World, service: EntityAuthoringService
) -> None:
    held = an_entity(world)
    added = service.add_alias(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Sarr",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason=None,
        idempotency_key="alias-c",
        **context(),  # type: ignore[arg-type]
    )
    corrected = service.supersede_alias(
        repository(world),  # type: ignore[arg-type]
        principal_id=MINE,
        entity_id=held.entity_id,
        expected_version=2,
        alias_id=str(added.receipt.child_id),
        expected_alias_version=1,
        alias_type=AliasType.NICKNAME,
        display_value="Sar",
        effective_from=None,
        effective_to=None,
        evidence=(),
        reason="A misspelling.",
        idempotency_key="alias-d",
        **context(),  # type: ignore[arg-type]
    )
    old = next(held for held in world.entity_aliases if held.alias_id == added.receipt.child_id)
    assert old.state is AliasState.SUPERSEDED
    assert old.superseded_by_alias_id == corrected.receipt.child_id
    assert corrected.receipt.superseded_ids == (added.receipt.child_id,)


# --- the partition ------------------------------------------------------------


def test_a_foreign_entity_is_refused_exactly_as_an_absent_one(
    world: World, service: EntityAuthoringService
) -> None:
    """A refusal that told the two apart would confirm a stranger's identifier."""
    theirs = an_entity(world, principal_id=THEIRS, display_name="Their Person")

    def archive(entity_id: str) -> None:
        service.archive(
            repository(world),  # type: ignore[arg-type]
            principal_id=MINE,
            entity_id=entity_id,
            expected_version=1,
            reason="A synthetic withdrawal.",
            idempotency_key=f"partition-{entity_id}",
            **context(),  # type: ignore[arg-type]
        )

    with pytest.raises(UnknownScopeError) as foreign:
        archive(theirs.entity_id)
    with pytest.raises(UnknownScopeError) as absent:
        archive(issue_identifier(IdKind.ENTITY))
    assert str(foreign.value) == str(absent.value)


def _bind(world: World, entity_id: str, address: str) -> str:
    """One active binding written through the port, and its identifier."""
    from my_pa.domain.relationship.entity import ExternalIdentifier

    identifier_id = issue_identifier(IdKind.EXTERNAL_IDENTIFIER)
    FakeUnitOfWork(world).entities.bind_identifier(
        MINE,
        entity_id,
        ExternalIdentifier(
            identifier_id=identifier_id,
            entity_id=entity_id,
            namespace=ExternalIdentifierNamespace.EMAIL,
            normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
            display_value=address,
            principal_id=MINE,
        ),
    )
    return identifier_id
