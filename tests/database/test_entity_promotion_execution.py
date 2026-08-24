"""Promotion against a real server: what it writes, and what it refuses to write.

The unit suite proves the promotion path routes and executes. This proves the
half a fake cannot: the authority the mutation ledger actually stores, the
evidence links the proposal plane's own table accepts and refuses, the successor
pointer's foreign key, and — the property most worth a real transaction — that a
refused promotion leaves nothing behind at all.

Five subjects:

1. **The ledger row an accepted proposal produces.** Section 14's last
   paragraph is about a stored value: `authority` is `review_accepted` and
   `actor_class` is `review_promotion`, because a promoted source or
   local-model conclusion recorded as the user's own assertion is a false
   record. A fake that does not write `entity_mutation_events` cannot say this.
2. **A stale target version prevents promotion, and prevents everything.** The
   decision is claimed before the write, so a refusal must take the decision
   with it — an acceptance with no record and no way to retry would be worse
   than either outcome.
3. **`entity_proposal_evidence_links` has a writer, and the writer is
   partitioned.** Same-Principal on the proposal and the observation, the
   capture span walked to the capture that owns it, and the exclusivity CHECK.
4. **`superseded_by_proposal_id`** — the column `reprocess` will need, its two
   CHECKs and its composite foreign key.
5. **A proposal a person has to look at is stored `needs_review`**, and is
   still decidable, which is the pair `initial_state_for` and the widened
   `UPDATE` predicate have to satisfy together.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    PromotionContext,
    ProposedEvidence,
)
from my_pa.application.entity_promotion import StaleTargetVersionError
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import AliasState, Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposalEvidenceLink,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    EvidenceRole,
    MutationRecordFamily,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entity_promotion_execution_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
BOB: Final = "ent_cccc0003cccc0003"
OBSERVATION_A: Final = "eobs_aaaa0001aaaa0001"
OBSERVATION_B: Final = "eobs_bbbb0002bbbb0002"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

ALIAS_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "alias_type": "nickname",
    "display_value": "Ali",
}


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


def _entity(entity_id: str, principal_id: str = PRINCIPAL_A, name: str = "Alice Chen") -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _observation(observation_id: str, principal_id: str = PRINCIPAL_A) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@example.invalid>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
    )


def _stage_span(connection: Connection, principal_id: str, suffix: str) -> str:
    """One capture, one version and one span this Principal owns.

    `capture_spans` carries no principal partition, so the ownership of a cited
    span is only provable through the capture behind it — which is the walk the
    writer performs and the thing these rows exist to make real.
    """
    capture_id = f"cap_stage{suffix}stage{suffix}"
    version_id = f"capver_stage{suffix}stage{suffix}"
    span_id = f"span_stage{suffix}stage{suffix}"
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.captures (capture_id, owner_principal_id, created_at) "  # noqa: S608
            "VALUES (:capture_id, :principal_id, now())"
        ),
        {"capture_id": capture_id, "principal_id": principal_id},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_versions (version_id, capture_id, version_number, "  # noqa: S608
            "content, content_sha256, owner_principal_id, classification, processing_policy, "
            "idempotency_key, correlation_id, audit_id, server_received_at, accepted_at, "
            "recorded_at) VALUES (:version_id, :capture_id, 1, 'a synthetic note', "
            ":digest, :principal_id, 'synthetic_test', 'local_only', :key, :correlation, "
            ":audit, now(), now(), now())"
        ),
        {
            "version_id": version_id,
            "capture_id": capture_id,
            "digest": "0" * 64,
            "principal_id": principal_id,
            "key": f"stage-{suffix}",
            "correlation": f"corr_stage{suffix}stage{suffix}",
            "audit": f"audit_stage{suffix}stage{suffix}",
        },
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, "  # noqa: S608
            "end_offset, offset_basis, line_start, column_start, line_end, column_end, "
            "quoted_text_sha256, span_role) VALUES (:span_id, :version_id, 0, 4, "
            "'unicode_code_point_v1', 1, 1, 1, 5, :digest, 'direct')"
        ),
        {"span_id": span_id, "version_id": version_id, "digest": "1" * 64},
    )
    return span_id


@pytest.fixture
def staged(disposable_database: str) -> Iterator[Engine]:
    """A migrated database holding two Principals, their entities and observations."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            repository = SqlEntityRepository(connection)
            repository.create(PRINCIPAL_A, _entity(ALICE))
            repository.create(PRINCIPAL_B, _entity(BOB, PRINCIPAL_B, "Bob Chen"))
            repository.record_observation(PRINCIPAL_A, _observation(OBSERVATION_A))
            repository.record_observation(PRINCIPAL_B, _observation(OBSERVATION_B, PRINCIPAL_B))
        yield engine
    finally:
        engine.dispose()


def _context(key: str = "idem-promote-1") -> PromotionContext:
    return PromotionContext(
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        idempotency_key=key,
        at=LATER,
    )


def _propose(
    connection: Connection,
    *,
    principal_id: str = PRINCIPAL_A,
    kind: EntityProposalKind = EntityProposalKind.RECORD_ALIAS,
    payload: dict[str, str | bool] | None = None,
    observation_ids: tuple[str, ...] = (),
    evidence: tuple[ProposedEvidence, ...] = (),
    expected_target_version: int | None = None,
) -> str:
    return (
        EntityGovernanceService(SqlEntityRepository(connection))
        .propose(
            principal_id,
            kind=kind,
            payload=ALIAS_PAYLOAD if payload is None else payload,
            observation_ids=observation_ids,
            proposed_by="resolver",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="1",
            at=WHEN,
            evidence=evidence,
            expected_target_version=expected_target_version,
        )
        .proposal_id
    )


def _counts(engine: Engine) -> dict[str, int]:
    tables = ("entity_aliases", "entity_mutation_events", "entity_fact_evidence_links")
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608
                ).scalar_one()
            )
            for table in tables
        }


# --- 1. the ledger row an accepted proposal produces --------------------------


def test_a_promoted_alias_is_recorded_as_review_accepted(staged: Engine) -> None:
    """Section 14, as a stored value rather than as an argument passed in memory."""
    with staged.begin() as connection:
        proposal_id = _propose(connection)
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            proposal_id,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context(),
        )

    with staged.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT capability, record_family, authority, actor_class "  # noqa: S608
                f"FROM {SCHEMA}.entity_mutation_events ORDER BY recorded_at"
            )
        ).all()
        alias = SqlEntityRepository(connection).aliases(PRINCIPAL_A, ALICE)
    assert [tuple(row) for row in rows] == [
        ("entities.aliases.add", "alias", "review_accepted", "review_promotion")
    ]
    assert [row.display_value for row in alias] == ["Ali"]
    assert alias[0].state is AliasState.ACTIVE


def test_the_promoted_proposal_names_the_record_and_its_evidence_follows(
    staged: Engine,
) -> None:
    """`accepted_record_*` on the proposal, and the cited observation on the fact."""
    with staged.begin() as connection:
        proposal_id = _propose(connection, observation_ids=(OBSERVATION_A,))
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            proposal_id,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context(),
        )

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        stored = repository.proposal(PRINCIPAL_A, proposal_id)
        alias = repository.aliases(PRINCIPAL_A, ALICE)[0]
        links = repository.fact_evidence_links(PRINCIPAL_A, entity_observation_id=OBSERVATION_A)
    assert stored is not None
    assert stored.accepted_record_type is MutationRecordFamily.ALIAS
    assert stored.accepted_record_id == alias.alias_id
    assert stored.accepted_record_version == alias.version
    promoted = [link for link in links if link.alias_id == alias.alias_id]
    assert len(promoted) == 1
    assert promoted[0].role is EvidenceRole.SUPPORTING
    assert promoted[0].authority.value == "review_accepted"


def test_a_promoted_assignment_goes_through_the_directed_plane(staged: Engine) -> None:
    """The second write plane, whose expected version is the record's own.

    On the authoring plane `expected_version` is the entity's, because the entity
    is the aggregate; on this one it is the assignment's. The promotion path
    reads which from the record family rather than from a per-kind table.
    """
    with staged.begin() as connection:
        proposal_id = _propose(
            connection,
            kind=EntityProposalKind.RECORD_ASSIGNMENT,
            payload={"entity_id": ALICE, "assignment_type": "project_assignment", "role": "PM"},
        )
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            proposal_id,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context(),
        )

    with staged.connect() as connection:
        assignments = SqlEntityRepository(connection).assignments(PRINCIPAL_A, ALICE)
        authority = connection.execute(
            text(
                f"SELECT authority, actor_class FROM {SCHEMA}.entity_mutation_events "  # noqa: S608
                "WHERE record_family = 'assignment'"
            )
        ).all()
    assert [assignment.role for assignment in assignments] == ["PM"]
    assert [tuple(row) for row in authority] == [("review_accepted", "review_promotion")]


# --- 2. a stale target version prevents promotion, and prevents everything -----


def test_a_stale_target_version_leaves_no_trace_of_the_acceptance(staged: Engine) -> None:
    """Section 27, and the transaction that makes the refusal total.

    The decision is claimed before the canonical write, so a refused promotion
    has to take the decision back with it. An acceptance recorded against a
    proposal whose promotion failed would be an acceptance nobody could retry
    and nobody could act on.
    """
    with staged.begin() as connection:
        first = _propose(connection)
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            first,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context(),
        )
    with staged.connect() as connection:
        alias = SqlEntityRepository(connection).aliases(PRINCIPAL_A, ALICE)[0]
    with staged.begin() as connection:
        retire = _propose(
            connection,
            kind=EntityProposalKind.RETIRE_ALIAS,
            payload={"entity_id": ALICE, "alias_id": alias.alias_id, "reason": "wrong person"},
            expected_target_version=alias.version + 1,
        )
    before = _counts(staged)

    with pytest.raises(StaleTargetVersionError), staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            retire,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context("idem-promote-2"),
        )

    assert _counts(staged) == before
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).proposal(PRINCIPAL_A, retire)
    assert stored is not None
    assert stored.state is EntityProposalState.NEEDS_REVIEW
    assert stored.decided_by is None


# --- 3. the proposal evidence table, and the partition around it --------------


def test_a_proposal_may_cite_an_observation_a_span_and_a_knowledge_record(
    staged: Engine,
) -> None:
    """Section 17's three evidence kinds, none of which the JSONB array can carry."""
    with staged.begin() as connection:
        span_id = _stage_span(connection, PRINCIPAL_A, "aaaa")
        proposal_id = _propose(
            connection,
            observation_ids=(OBSERVATION_A,),
            evidence=(
                ProposedEvidence(role=EvidenceRole.SUPPORTING, capture_span_id=span_id),
                ProposedEvidence(
                    role=EvidenceRole.COUNTEREVIDENCE,
                    knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
                ),
            ),
        )

    with staged.connect() as connection:
        links = SqlEntityRepository(connection).proposal_evidence_links(PRINCIPAL_A, proposal_id)
    assert [link.sequence for link in links] == [1, 2, 3]
    assert links[0].entity_observation_id == OBSERVATION_A
    assert links[0].role is EvidenceRole.DIRECT
    assert links[1].capture_span_id == span_id
    assert links[2].knowledge_id is not None
    assert links[2].role is EvidenceRole.COUNTEREVIDENCE


def test_proposal_evidence_may_not_cite_another_principals_observation(
    staged: Engine,
) -> None:
    """A foreign observation and an absent one answer alike."""
    with staged.begin() as connection:
        proposal_id = _propose(connection)
    with pytest.raises(UnknownScopeError), staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal_evidence_link(
            PRINCIPAL_A,
            EntityProposalEvidenceLink(
                proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                sequence=9,
                role=EvidenceRole.SUPPORTING,
                created_at=LATER,
                entity_observation_id=OBSERVATION_B,
            ),
        )


def test_proposal_evidence_may_not_cite_another_principals_span(staged: Engine) -> None:
    """`capture_spans` has no partition, so the join to the owning capture is the check."""
    with staged.begin() as connection:
        span_id = _stage_span(connection, PRINCIPAL_B, "bbbb")
        proposal_id = _propose(connection)
    with pytest.raises(UnknownScopeError), staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal_evidence_link(
            PRINCIPAL_A,
            EntityProposalEvidenceLink(
                proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                sequence=9,
                role=EvidenceRole.SUPPORTING,
                created_at=LATER,
                capture_span_id=span_id,
            ),
        )


def test_proposal_evidence_may_not_cite_another_principals_proposal(staged: Engine) -> None:
    with staged.begin() as connection:
        foreign = _propose(
            connection,
            principal_id=PRINCIPAL_B,
            payload={"entity_id": BOB, "alias_type": "nickname", "display_value": "Bo"},
        )
    with pytest.raises(UnknownScopeError), staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal_evidence_link(
            PRINCIPAL_A,
            EntityProposalEvidenceLink(
                proposal_id=foreign,
                principal_id=PRINCIPAL_A,
                sequence=1,
                role=EvidenceRole.SUPPORTING,
                created_at=LATER,
                entity_observation_id=OBSERVATION_A,
            ),
        )


def test_the_server_refuses_proposal_evidence_naming_two_records(staged: Engine) -> None:
    """The exclusivity CHECK, reached through SQL because the record refuses first.

    `EntityProposalEvidenceLink.__post_init__` will not build a link naming two
    targets, so the column's own rule is only observable from a writer that did
    not go through the record — a migration, a backfill, a hand-run statement.
    """
    with staged.begin() as connection:
        proposal_id = _propose(connection)
    with (
        pytest.raises(IntegrityError, match="proposal_evidence_names_exactly_one_record"),
        staged.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_proposal_evidence_links ("  # noqa: S608
                "proposal_id, sequence, principal_id, role, entity_observation_id, "
                "capture_span_id, knowledge_id, created_at) VALUES (:proposal_id, 7, "
                ":principal_id, 'supporting', :observation_id, :span_id, NULL, now())"
            ),
            {
                "proposal_id": proposal_id,
                "principal_id": PRINCIPAL_A,
                "observation_id": OBSERVATION_A,
                "span_id": "span_cccc0003cccc0003",
            },
        )


# --- 4. the successor pointer -------------------------------------------------


def test_superseding_a_proposal_names_its_successor(staged: Engine) -> None:
    """The predecessor half of section 13's `reprocess`, which is all this worker writes."""
    with staged.begin() as connection:
        predecessor = _propose(connection)
        successor = _propose(
            connection,
            payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Alicia"},
        )
    with staged.begin() as connection:
        moved = SqlEntityRepository(connection).supersede_proposal(
            PRINCIPAL_A, predecessor, successor_proposal_id=successor, at=LATER
        )
    assert moved is True

    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).proposal(PRINCIPAL_A, predecessor)
    assert stored is not None
    assert stored.state is EntityProposalState.SUPERSEDED
    assert stored.superseded_by_proposal_id == successor
    assert stored.superseded_at is not None


def test_a_decided_proposal_is_not_superseded(staged: Engine) -> None:
    """A stale reprocess creates nothing rather than overwriting a decision (section 27)."""
    with staged.begin() as connection:
        predecessor = _propose(connection)
        successor = _propose(
            connection,
            payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Alicia"},
        )
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).reject(
            PRINCIPAL_A, predecessor, decided_by="reviewer", decided_at=LATER, reason="no"
        )
    with staged.begin() as connection:
        moved = SqlEntityRepository(connection).supersede_proposal(
            PRINCIPAL_A, predecessor, successor_proposal_id=successor, at=LATER
        )
    assert moved is False

    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).proposal(PRINCIPAL_A, predecessor)
    assert stored is not None
    assert stored.state is EntityProposalState.REJECTED
    assert stored.superseded_by_proposal_id is None


def test_the_server_refuses_a_successor_in_another_principals_partition(
    staged: Engine,
) -> None:
    """The composite foreign key: lineage that crossed a partition would read as authority."""
    with staged.begin() as connection:
        predecessor = _propose(connection)
        foreign = _propose(
            connection,
            principal_id=PRINCIPAL_B,
            payload={"entity_id": BOB, "alias_type": "nickname", "display_value": "Bo"},
        )
    with (
        pytest.raises(IntegrityError, match="a_proposal_is_superseded_within_its_principal"),
        staged.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals SET state = 'superseded', "  # noqa: S608
                "superseded_at = now(), superseded_by_proposal_id = :successor "
                "WHERE proposal_id = :proposal_id"
            ),
            {"successor": foreign, "proposal_id": predecessor},
        )


def test_the_server_refuses_a_successor_on_a_live_proposal(staged: Engine) -> None:
    """A proposal still awaiting a decision cannot claim to have been replaced."""
    with staged.begin() as connection:
        predecessor = _propose(connection)
        successor = _propose(
            connection,
            payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Alicia"},
        )
    with (
        pytest.raises(IntegrityError, match="only_a_superseded_proposal_names_its_successor"),
        staged.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET superseded_by_proposal_id = :successor WHERE proposal_id = :proposal_id"
            ),
            {"successor": successor, "proposal_id": predecessor},
        )


# --- 5. the state a proposal a person has to look at is written in -------------


def test_a_proposal_a_person_must_look_at_is_stored_needs_review_and_stays_decidable(
    staged: Engine,
) -> None:
    """`initial_state_for` and the widened `UPDATE` predicate, proved together.

    Either half alone is a defect: the state without the predicate makes every
    `needs_review` proposal undecidable, and the predicate without the state
    widens a guard nothing exercises.
    """
    with staged.begin() as connection:
        proposal_id = _propose(
            connection,
            kind=EntityProposalKind.BIND_IDENTIFIER,
            payload={
                "entity_id": ALICE,
                "namespace": "email",
                "display_value": "a.chen@example.invalid",
            },
        )
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
    assert stored is not None
    assert stored.state is EntityProposalState.NEEDS_REVIEW
    assert stored.is_open is True

    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            proposal_id,
            decided_by="reviewer",
            decided_at=LATER,
            reason="looks right",
            promotion=_context(),
        )

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        decided = repository.proposal(PRINCIPAL_A, proposal_id)
        bound = repository.external_identifiers(PRINCIPAL_A, ALICE)
    assert decided is not None
    assert decided.state is EntityProposalState.ACCEPTED
    assert [identifier.display_value for identifier in bound] == ["a.chen@example.invalid"]


def test_a_proposal_a_threshold_may_accept_is_stored_proposed(staged: Engine) -> None:
    """The control: the derivation distinguishes, rather than writing one state twice."""
    with staged.begin() as connection:
        proposal_id = _propose(connection)
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
    assert stored is not None
    assert stored.state is EntityProposalState.PROPOSED
