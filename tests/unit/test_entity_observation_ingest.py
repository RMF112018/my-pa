"""Recording what a source said, and the one thing that must never get in.

`entities.observe` exists so evidence has somewhere to live that is not a
person. Every test here names a route by which recording evidence could become
*asserting an identity* — or by which a model's conclusion could be recorded as
something a source said — and asserts it is closed.

**The authority rule is the sharp end.** `ObservationAuthority` is three
members and none of them names a model, which is a shape rather than a
convention: a conclusion drawn by a model has no member to claim. What a caller
*could* still do is claim `source_observation` for something no source produced,
so the claim is checked against the origin rather than believed — a
product-owned capture may not carry it at all, and a configured source must name
a source object this product has actually read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    ObserveCommand,
    ResolutionNotPermittedError,
    UnknownEntityError,
)
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityMutationConflictError,
    MutationAuthority,
    MutationRecordFamily,
    ObservationAuthority,
    ObservationAuthorityError,
    ObservationKind,
    ObservationOrigin,
    ObservationState,
    capture_origin_triple,
    origin_of,
)
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"
ALICE = "ent_aaaa0001aaaa0001"

SOURCE = "src_aaaa0001aaaa0001"
OBJECT = "obj_aaaa0001aaaa0001"
VERSION = "ver_aaaa0001aaaa0001"
CAPTURE = "cap_aaaa0001aaaa0001"
CAPTURE_VERSION = "capver_aaaa0001aaaa01"

CORRELATION = "corr_aaaa0001aaaa0001"
AUDIT = "audit_aaaa0001aaaa01"

WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)

#: A name with a mail envelope around it. The point of the value: `normalize_name`
#: removes no content, so the normalized form still carries the local part and
#: the domain — which is why no read on this plane publishes either.
ENVELOPE = "Alice Chen <a.chen@northwind.test>"


@pytest.fixture
def staged(world: World) -> World:
    """One source object this product has read, and one entity."""
    world.objects[OBJECT] = SOURCE
    FakeUnitOfWork(world).entities.create(
        PRINCIPAL,
        Entity(
            entity_id=ALICE,
            principal_id=PRINCIPAL,
            entity_type=EntityType.PERSON,
            canonical_name=normalize_name("Alice Chen"),
            display_name="Alice Chen",
            status=EntityStatus.ACTIVE,
            created_at=WHEN,
            updated_at=WHEN,
            version=1,
        ),
    )
    return world


def _service(world: World) -> EntityGovernanceService:
    return EntityGovernanceService(FakeUnitOfWork(world).entities)


def _sources(world: World):  # noqa: ANN202
    return FakeUnitOfWork(world).sources


def a_command(**overrides: object) -> ObserveCommand:
    """One source-backed observation, with every field a caller may state."""
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "kind": ObservationKind.MESSAGE_PARTICIPANT,
        "authority": ObservationAuthority.SOURCE_OBSERVATION,
        "observed_value": ENVELOPE,
        "observed_at": WHEN,
        "idempotency_key": "observe-0001",
        "source_id": SOURCE,
        "source_object_id": OBJECT,
        "source_version_id": VERSION,
    }
    fields.update(overrides)
    return ObserveCommand(**fields)  # type: ignore[arg-type]


def _ingest(world: World, command: ObserveCommand, *, at: datetime = WHEN):  # noqa: ANN202
    return _service(world).ingest(
        command, sources=_sources(world), at=at, correlation_id=CORRELATION, audit_id=AUDIT
    )


# --- the authority vocabulary -----------------------------------------------


def test_the_authority_vocabulary_is_three_and_none_of_them_is_a_model() -> None:
    """The structural half of the rule: there is no member to claim.

    A model conclusion belongs in proposal state, and the way that is made true
    is that this vocabulary has nowhere to put one. Asserted over the members
    themselves rather than over a list, so widening the enum reddens here.
    """
    assert {member.value for member in ObservationAuthority} == {
        "source_observation",
        "user_authored_statement",
        "system_deterministic_observation",
    }
    for member in ObservationAuthority:
        assert "model" not in member.value
        assert "inferred" not in member.value


def test_a_product_owned_capture_may_not_claim_source_authority(staged: World) -> None:
    """The behavioural half, and the one a model could actually reach.

    A model writing through this capability has no source object version to
    name; what it has, at best, is a capture. So the capture origin is refused
    `source_observation` outright rather than being trusted to declare itself.
    """
    with pytest.raises(ObservationAuthorityError):
        _ingest(
            staged,
            a_command(
                source_id=None,
                source_object_id=None,
                source_version_id=None,
                capture_id=CAPTURE,
                capture_version_id=CAPTURE_VERSION,
            ),
        )


def test_source_authority_requires_a_source_object_this_product_has_read(world: World) -> None:
    """A triple naming nothing is not provenance. Nothing is staged here."""
    with pytest.raises(ObservationAuthorityError):
        _ingest(world, a_command())


def test_source_authority_refuses_an_object_belonging_to_a_different_source(
    staged: World,
) -> None:
    """The object exists and the pairing is false, which is its own claim."""
    staged.objects[OBJECT] = "src_ffff0009ffff0009"
    with pytest.raises(ObservationAuthorityError):
        _ingest(staged, a_command())


def test_a_user_authored_statement_is_not_quoting_a_configured_source(staged: World) -> None:
    """The mirror image, and it protects the authority a source cannot falsify."""
    with pytest.raises(ObservationAuthorityError):
        _ingest(
            staged,
            a_command(
                kind=ObservationKind.USER_STATEMENT,
                authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
            ),
        )


def test_a_user_authored_statement_is_recorded_as_a_user_statement(staged: World) -> None:
    """The kind and the authority have to agree about what happened."""
    with pytest.raises(ObservationAuthorityError):
        _ingest(
            staged,
            a_command(
                kind=ObservationKind.CONTACT_RECORD,
                authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
                source_id=None,
                source_object_id=None,
                source_version_id=None,
                capture_id=CAPTURE,
                capture_version_id=CAPTURE_VERSION,
            ),
        )


def test_a_user_authored_statement_over_a_capture_is_admitted(staged: World) -> None:
    admitted = _ingest(
        staged,
        a_command(
            kind=ObservationKind.USER_STATEMENT,
            authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
            source_id=None,
            source_object_id=None,
            source_version_id=None,
            capture_id=CAPTURE,
            capture_version_id=CAPTURE_VERSION,
        ),
    )
    assert admitted.origin is ObservationOrigin.PRODUCT_OWNED_CAPTURE
    assert admitted.authority is ObservationAuthority.USER_AUTHORED_STATEMENT


# --- the origin ---------------------------------------------------------------


def test_an_observation_names_one_origin_and_not_two(staged: World) -> None:
    with pytest.raises(ObservationAuthorityError):
        _ingest(staged, a_command(capture_id=CAPTURE, capture_version_id=CAPTURE_VERSION))


def test_an_observation_names_one_origin_and_not_none(staged: World) -> None:
    with pytest.raises(ObservationAuthorityError):
        _ingest(staged, a_command(source_id=None, source_object_id=None, source_version_id=None))


def test_a_capture_origin_maps_onto_the_triple_the_table_requires(staged: World) -> None:
    """The columns stay `NOT NULL` and the capture identity fits them.

    Deterministic, and that is a requirement rather than a nicety: the triple is
    part of what a replay compares, so a mapping that minted fresh identifiers
    would make every retry a conflict.
    """
    triple = capture_origin_triple(CAPTURE, CAPTURE_VERSION)
    assert triple == capture_origin_triple(CAPTURE, CAPTURE_VERSION)
    assert origin_of(triple[0]) is ObservationOrigin.PRODUCT_OWNED_CAPTURE
    _ingest(
        staged,
        a_command(
            kind=ObservationKind.USER_STATEMENT,
            authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
            source_id=None,
            source_object_id=None,
            source_version_id=None,
            capture_id=CAPTURE,
            capture_version_id=CAPTURE_VERSION,
        ),
    )
    held = staged.entity_observations[0]
    assert (held.source_id, held.source_object_id, held.source_version_id) == triple


# --- what recording evidence does, and does not, do ---------------------------


def test_recording_an_observation_creates_no_entity(staged: World) -> None:
    """Section 12.2, asserted as a count rather than as an intention."""
    before = len(staged.entities)
    admitted = _ingest(staged, a_command())
    assert len(staged.entities) == before
    assert admitted.entity_id is None
    assert admitted.state is ObservationState.CURRENT
    assert admitted.resolution_version == 0


def test_an_admitted_observation_is_unresolved_until_something_decides_it(
    staged: World,
) -> None:
    admitted = _ingest(staged, a_command())
    queue = FakeUnitOfWork(staged).entities.observations(PRINCIPAL, unresolved_only=True)
    assert [item.observation_id for item in queue] == [admitted.observation_id]


def test_the_receipt_carries_neither_value_the_source_produced(staged: World) -> None:
    """A receipt acknowledges durability. It is not a way to read the text back."""
    admitted = _ingest(staged, a_command())
    rendered = repr(admitted)
    assert ENVELOPE not in rendered
    assert normalize_name(ENVELOPE) not in rendered
    assert not hasattr(admitted, "observed_value")
    assert not hasattr(admitted, "normalized_value")


def test_the_normalized_value_is_derived_and_not_supplied(staged: World) -> None:
    """The command has no field for it, so a caller cannot plant one."""
    assert not hasattr(a_command(), "normalized_value")
    _ingest(staged, a_command())
    assert staged.entity_observations[0].normalized_value == normalize_name(ENVELOPE)


def test_the_mutation_ledger_photograph_carries_no_observed_text(staged: World) -> None:
    """The ledger is read by operators, exported, and rendered in failures."""
    _ingest(staged, a_command())
    event = staged.entity_mutation_events[0]
    rendered = repr(dict(event.after_state or {}))
    assert ENVELOPE not in rendered
    assert normalize_name(ENVELOPE) not in rendered
    assert event.record_family is MutationRecordFamily.OBSERVATION
    assert event.new_version == 1
    assert event.prior_version is None
    assert event.authority is MutationAuthority.SYSTEM_DETERMINISTIC


# --- binding an entity, where that is already justified -----------------------


def test_a_binding_names_the_entity_version_it_expects(staged: World) -> None:
    admitted = _ingest(staged, a_command(entity_id=ALICE, expected_entity_version=1))
    assert admitted.entity_id == ALICE


def test_a_binding_refuses_a_stale_entity_version(staged: World) -> None:
    with pytest.raises(ResolutionNotPermittedError) as refused:
        _ingest(staged, a_command(entity_id=ALICE, expected_entity_version=2))
    assert refused.value.detail == "stale_version"


def test_a_binding_refuses_an_entity_of_another_principal(staged: World) -> None:
    """Foreign is answered exactly as absent, which is the partition rule.

    `UnknownEntityError` rather than `UnknownObservationError`: the two name
    different fields, and a caller told the wrong one refreshes the wrong
    record. The two arrangements below are the same refusal, which is the point.
    """
    staged.objects[OBJECT] = SOURCE
    for principal_id, entity_id in ((OTHER, ALICE), (PRINCIPAL, "ent_ffff0009ffff0009")):
        with pytest.raises(UnknownEntityError):
            _ingest(
                staged,
                a_command(
                    principal_id=principal_id,
                    entity_id=entity_id,
                    expected_entity_version=1,
                ),
            )


def test_a_configured_source_origin_is_proved_under_every_authority(staged: World) -> None:
    """A triple naming nothing is fabricated provenance whatever it claimed.

    Checking only `source_observation` would leave
    `system_deterministic_observation` as the way around the rule, on a plane
    where the difference between the two is not observable from the row.
    """
    staged.objects.clear()
    with pytest.raises(ObservationAuthorityError):
        _ingest(
            staged,
            a_command(authority=ObservationAuthority.SYSTEM_DETERMINISTIC_OBSERVATION),
        )


# --- idempotency --------------------------------------------------------------


def test_an_exact_replay_returns_the_first_observation_and_writes_nothing(
    staged: World,
) -> None:
    first = _ingest(staged, a_command())
    second = _ingest(staged, a_command(), at=LATER)
    assert second.observation_id == first.observation_id
    assert second.created is False
    assert first.created is True
    assert len(staged.entity_observations) == 1
    assert len(staged.entity_mutation_events) == 1


def test_one_key_bound_to_a_different_request_is_a_conflict(staged: World) -> None:
    _ingest(staged, a_command())
    with pytest.raises(EntityMutationConflictError):
        _ingest(staged, a_command(observed_value="Someone Else"))
    assert len(staged.entity_observations) == 1


def test_the_replay_digest_excludes_what_differs_on_every_attempt(staged: World) -> None:
    """Minted identifiers, the correlation identifier and the receipt time.

    Asserted by replaying at a different moment through a different correlation
    identifier: including any of the three would make an ordinary retry a
    conflict, which is the failure this exclusion exists to prevent.
    """
    first = _ingest(staged, a_command())
    replayed = _service(staged).ingest(
        a_command(),
        sources=_sources(staged),
        at=LATER,
        correlation_id="corr_ffff0009ffff0009",
        audit_id="audit_ffff0009ffff09",
    )
    assert replayed.observation_id == first.observation_id
    assert replayed.created is False
