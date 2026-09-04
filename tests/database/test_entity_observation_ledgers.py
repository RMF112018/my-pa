"""The three WP-RI-A-01 ledgers, written for the first time, against a real server.

`tests/unit/test_entity_observation_ingest.py` and its sibling drive the
in-memory fake and prove the *contract*. This drives the SQL and proves the
contract holds where it has to: against the append-only triggers, the unique
key that makes a replay a replay, the six CHECKs that make an evidence link name
one fact and one record, the composite foreign keys that make same-Principal
structural, and a guarded `UPDATE` whose rowcount is the only thing standing
between two reviewers and one silently overwritten decision.

**What this file proves and what it does not.** Nothing here goes through
`ApplicationService`, so nothing here writes an audit row: this is the
repository half, and the end-to-end half is somebody else's file. That division
was originally forced — `knowledge.audit_events` constrains `capability` and
`purpose` to closed sets, and no revision admitted `entities.observe`,
`entities.observations.list`, `entities.unresolved_mentions.resolve`,
`entity_observation_ingest` or `entity_authoring`, because Phase A takes exactly
one such revision and three branches restating one frozen constraint would have
produced three heads. `823e23b6cc63` admits all five at head. The division
stands anyway, because it was the right one: what this file is about is the
partition predicate, the unique key and the guarded version, and driving a
transport through them would prove those with a great deal more machinery.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    NEGATIVE_IDENTITY_EVIDENCE_ROLE,
    ActorClass,
    EntityFactEvidenceLink,
    EntityMutationConflictError,
    EntityMutationEvent,
    EntityObservation,
    EntityResolutionDecision,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationKind,
    ObservationState,
    ResolutionDisposition,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database
#: another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_ledgers_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

ALICE: Final = "ent_aaaa0001aaaa0001"
FOREIGN: Final = "ent_ffff0009ffff0009"
MENTION: Final = "eobs_aaaa0001aaaa01"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"
CAPABILITY: Final = "entities.observe"

WHEN: Final = datetime(2026, 8, 17, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def an_entity(entity_id: str, principal_id: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name("Alice Synthetic"),
        display_name="Alice Synthetic",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def a_mention(observation_id: str, principal_id: str) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Synthetic",
        normalized_value=normalize_name("Alice Synthetic"),
        mention_display_name="Alice Synthetic",
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
    )


def an_event(event_id: str, *, key: str, digest: str = DIGEST) -> EntityMutationEvent:
    return EntityMutationEvent(
        event_id=event_id,
        principal_id=PRINCIPAL_A,
        capability=CAPABILITY,
        record_family=MutationRecordFamily.OBSERVATION,
        record_id=MENTION,
        new_version=1,
        authority=MutationAuthority.SYSTEM_DETERMINISTIC,
        actor_class=ActorClass.SYSTEM_DETERMINISTIC,
        idempotency_key=key,
        request_digest=digest,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        recorded_at=WHEN,
        after_state={"observation_id": MENTION},
    )


def a_decision(
    decision_id: str,
    *,
    sequence: int = 1,
    expected: int = 0,
    disposition: ResolutionDisposition = ResolutionDisposition.DEFER,
    entity_id: str | None = None,
) -> EntityResolutionDecision:
    return EntityResolutionDecision(
        decision_id=decision_id,
        principal_id=PRINCIPAL_A,
        observation_id=MENTION,
        sequence=sequence,
        expected_resolution_version=expected,
        disposition=disposition,
        decided_by=PRINCIPAL_A,
        actor_class=ActorClass.USER,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        decided_at=WHEN,
        entity_id=entity_id,
        reason="there is not enough identity evidence yet",
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Iterator[Engine]:
    """One entity and one unplaced mention, committed."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, an_entity(ALICE, PRINCIPAL_A))
        repository.create(PRINCIPAL_B, an_entity(FOREIGN, PRINCIPAL_B))
        repository.record_observation(PRINCIPAL_A, a_mention(MENTION, PRINCIPAL_A))
    yield migrated_engine


# --- the mutation ledger, which is also the idempotency store -----------------


def test_one_key_and_one_capability_admit_exactly_one_row(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_mutation_event(PRINCIPAL_A, an_event("emut_aaaa0001aaaa01", key="k"))
        repository.record_mutation_event(PRINCIPAL_A, an_event("emut_bbbb0002bbbb02", key="k"))
        held = repository.mutation_event(PRINCIPAL_A, capability=CAPABILITY, idempotency_key="k")
    assert held is not None
    assert held.event_id == "emut_aaaa0001aaaa01"


def test_one_key_bound_to_a_different_digest_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_mutation_event(PRINCIPAL_A, an_event("emut_aaaa0001aaaa01", key="k"))
        with pytest.raises(EntityMutationConflictError):
            repository.record_mutation_event(
                PRINCIPAL_A, an_event("emut_bbbb0002bbbb02", key="k", digest=OTHER_DIGEST)
            )


def test_the_same_key_under_a_different_capability_is_a_different_request(
    staged: Engine,
) -> None:
    """`capability` is part of the key rather than assumed.

    One key replayed against a *different* capability is a different request,
    and answering it from the first row would be answering the wrong question.
    """
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_mutation_event(PRINCIPAL_A, an_event("emut_aaaa0001aaaa01", key="k"))
        other = an_event("emut_bbbb0002bbbb02", key="k")
        repository.record_mutation_event(
            PRINCIPAL_A,
            EntityMutationEvent(
                **{
                    **{
                        field: getattr(other, field)
                        for field in (
                            "event_id",
                            "principal_id",
                            "record_family",
                            "record_id",
                            "new_version",
                            "authority",
                            "actor_class",
                            "idempotency_key",
                            "request_digest",
                            "correlation_id",
                            "audit_id",
                            "recorded_at",
                        )
                    },
                    "capability": "entities.unresolved_mentions.resolve",
                }
            ),
        )
    with staged.connect() as connection:
        rows = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_mutation_events")  # noqa: S608
        ).scalar_one()
    assert rows == 2


def test_the_mutation_ledger_is_append_only_at_the_server(staged: Engine) -> None:
    """The trigger, not the repository. This statement goes around the port."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_mutation_event(
            PRINCIPAL_A, an_event("emut_aaaa0001aaaa01", key="k")
        )
    for statement in (
        f"UPDATE {SCHEMA}.entity_mutation_events SET reason = 'rewritten'",  # noqa: S608
        f"DELETE FROM {SCHEMA}.entity_mutation_events",  # noqa: S608
    ):
        with pytest.raises(DBAPIError), staged.begin() as connection:
            connection.execute(text(statement))


# --- the resolution decisions ---------------------------------------------------


def test_a_decision_is_appended_and_read_back_in_sequence(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_resolution_decision(PRINCIPAL_A, a_decision("erdc_aaaa0001aaaa01"))
        repository.record_resolution_decision(
            PRINCIPAL_A, a_decision("erdc_bbbb0002bbbb02", sequence=2, expected=1)
        )
        held = repository.resolution_decisions(PRINCIPAL_A, MENTION)
    assert [row.sequence for row in held] == [1, 2]
    assert [row.disposition for row in held] == [
        ResolutionDisposition.DEFER,
        ResolutionDisposition.DEFER,
    ]


def test_two_decisions_cannot_take_one_sequence(staged: Engine) -> None:
    """The uniqueness that refuses a second writer past the version check."""
    with pytest.raises(IntegrityError), staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_resolution_decision(PRINCIPAL_A, a_decision("erdc_aaaa0001aaaa01"))
        repository.record_resolution_decision(PRINCIPAL_A, a_decision("erdc_bbbb0002bbbb02"))


def test_the_decision_ledger_is_append_only_at_the_server(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_resolution_decision(
            PRINCIPAL_A, a_decision("erdc_aaaa0001aaaa01")
        )
    for statement in (
        f"UPDATE {SCHEMA}.entity_resolution_decisions SET reason = 'rewritten'",  # noqa: S608
        f"DELETE FROM {SCHEMA}.entity_resolution_decisions",  # noqa: S608
    ):
        with pytest.raises(DBAPIError), staged.begin() as connection:
            connection.execute(text(statement))


def test_a_decision_binds_an_entity_of_its_own_principal(staged: Engine) -> None:
    """Same-Principal is structural here, and the repository refuses first."""
    with pytest.raises(Exception, match=r"scope|principal"), staged.begin() as connection:
        SqlEntityRepository(connection).record_resolution_decision(
            PRINCIPAL_A,
            a_decision(
                "erdc_aaaa0001aaaa01",
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=FOREIGN,
            ),
        )


def test_a_refusal_may_not_name_the_entity_it_refused(staged: Engine) -> None:
    """The CHECK that makes the evidence link necessary.

    `entity_id` is reserved for the two dispositions that *bind* one, so a
    rejection has nowhere on this table to name the other half of the pairing —
    which is exactly why the refused pairing is preserved on
    `entity_fact_evidence_links` instead.
    """
    with pytest.raises(ValueError, match="binds one"):
        a_decision(
            "erdc_aaaa0001aaaa01",
            disposition=ResolutionDisposition.REJECT,
            entity_id=ALICE,
        )


# --- the evidence links -----------------------------------------------------------


def _link(link_id: str, **overrides: object) -> EntityFactEvidenceLink:
    fields: dict[str, object] = {
        "link_id": link_id,
        "principal_id": PRINCIPAL_A,
        "role": NEGATIVE_IDENTITY_EVIDENCE_ROLE,
        "authority": MutationAuthority.USER_CONFIRMED_ASSERTION,
        "created_at": WHEN,
        "entity_id": ALICE,
        "entity_observation_id": MENTION,
    }
    fields.update(overrides)
    return EntityFactEvidenceLink(**fields)  # type: ignore[arg-type]


def test_a_negative_identity_link_is_written_and_read_back_by_role(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_fact_evidence_link(PRINCIPAL_A, _link("efev_aaaa0001aaaa01"))
        repository.record_fact_evidence_link(
            PRINCIPAL_A, _link("efev_bbbb0002bbbb02", role=EvidenceRole.SUPPORTING)
        )
        refused = repository.fact_evidence_links(
            PRINCIPAL_A,
            entity_observation_id=MENTION,
            role=EvidenceRole.COUNTEREVIDENCE,
        )
    assert [row.link_id for row in refused] == ["efev_aaaa0001aaaa01"]
    assert refused[0].entity_id == ALICE
    assert refused[0].is_negative_identity_evidence


def test_an_evidence_link_names_exactly_one_fact(staged: Engine) -> None:
    """Refused by the record before the CHECK, and by the CHECK if it were not."""
    with pytest.raises(ValueError, match="exactly one fact"):
        _link("efev_aaaa0001aaaa01", alias_id="eals_aaaa0001aaaa01")
    with pytest.raises(ValueError, match="exactly one fact"):
        _link("efev_aaaa0001aaaa01", entity_id=None)


def test_an_evidence_link_names_exactly_one_record(staged: Engine) -> None:
    with pytest.raises(ValueError, match="exactly one record"):
        _link("efev_aaaa0001aaaa01", knowledge_id="kn_aaaa0001aaaa0001")
    with pytest.raises(ValueError, match="exactly one record"):
        _link("efev_aaaa0001aaaa01", entity_observation_id=None)


def test_an_evidence_link_cites_a_fact_of_its_own_principal(staged: Engine) -> None:
    with pytest.raises(Exception, match=r"scope|principal"), staged.begin() as connection:
        SqlEntityRepository(connection).record_fact_evidence_link(
            PRINCIPAL_A, _link("efev_aaaa0001aaaa01", entity_id=FOREIGN)
        )


def test_an_evidence_link_is_deleted_with_the_fact_it_cites(staged: Engine) -> None:
    """Not trigger-protected, and cascading — which is the table's own property.

    A link to a fact that no longer exists is not evidence of anything. What
    survives is the *decision* that cited it, on a table that is append-only.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_fact_evidence_link(
            PRINCIPAL_A, _link("efev_aaaa0001aaaa01")
        )
    with staged.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :id"),  # noqa: S608
            {"id": ALICE},
        )
    with staged.connect() as connection:
        remaining = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_fact_evidence_links")  # noqa: S608
        ).scalar_one()
    assert remaining == 0


# --- the guarded update -------------------------------------------------------------


def test_a_stale_expected_resolution_version_writes_nothing(staged: Engine) -> None:
    """One `UPDATE`, and its rowcount is the whole decision."""
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.decide_observation(
            PRINCIPAL_A, MENTION, expected_resolution_version=0, entity_id=ALICE
        )
        assert not repository.decide_observation(
            PRINCIPAL_A,
            MENTION,
            expected_resolution_version=0,
            state=ObservationState.QUARANTINED,
            state_reason="a second reviewer",
        )
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        held = repository.observation(PRINCIPAL_A, MENTION)
    assert held is not None
    assert held.resolution_version == 1
    assert held.entity_id == ALICE
    # Nothing the losing write asked for was applied.
    assert held.state is ObservationState.CURRENT
    assert held.state_reason is None


def test_a_foreign_observation_is_answered_exactly_as_an_absent_one(
    staged: Engine,
) -> None:
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.observation(PRINCIPAL_B, MENTION) is None
        assert repository.observation(PRINCIPAL_A, "eobs_ffff0009ffff09") is None


def test_a_decision_on_a_foreign_observation_writes_nothing(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        assert not repository.decide_observation(
            PRINCIPAL_B, MENTION, expected_resolution_version=0
        )
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).observation(PRINCIPAL_A, MENTION)
    assert held is not None
    assert held.resolution_version == 0
