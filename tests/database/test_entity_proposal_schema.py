"""The widened proposal record and its evidence table, against a real server.

The unit suite proves `EntityProposal` and `EntityProposalPayload` refuse. This
proves the *server* refuses, which is the half that survives a writer who did not
go through the record: a migration, a backfill, a hand-run statement, a future
repository method somebody adds in a hurry.

Two constraints carry most of the weight.
`an_open_equivalent_proposal_is_raised_once` is the whole of open-equivalent
dedupe -- without it a producer puts the same candidate in front of a reviewer on
every run, and the reviewer's queue becomes noise nobody reads.
`a_model_proposal_names_its_model` is the anti-laundering half: a model
conclusion recorded as `deterministic` is a model conclusion a configured
threshold would accept with no person involved, which is the promotion section
21.4 forbids.

Every statement here goes in through SQL rather than the repository, deliberately.
A test that could only reach the column through the record would prove the record
and say nothing about the column.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposalEvidenceLink,
    EntityProposalKind,
    EntityProposalMethod,
    EvidenceRole,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import ProposalPayloadError
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entity_proposal_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"
BOB: Final = "ent_cccc0003cccc0003"
OBSERVATION_A: Final = "eobs_aaaa0001aaaa0001"
OBSERVATION_B: Final = "eobs_bbbb0002bbbb0002"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)

#: A digest of the right shape. Any 64 lowercase hexadecimal characters: what is
#: under test here is the column's rule, not the derivation, which
#: `test_entity_proposal_payload` covers.
DIGEST: Final = "a" * 64
OTHER_DIGEST: Final = "b" * 64

_INSERT: Final = text(
    f"""
    INSERT INTO {SCHEMA}.entity_proposals (
      proposal_id, principal_id, kind, state, payload, observation_ids,
      proposed_at, proposed_by, method, method_version, dedupe_sha256,
      model_id, model_version, expected_target_version, review_case_id,
      accepted_record_type, accepted_record_id, accepted_record_version,
      invalidated_reason, superseded_at, decided_by, decided_at, decision_reason
    ) VALUES (
      :proposal_id, :principal_id, :kind, :state, CAST(:payload AS jsonb), CAST('[]' AS jsonb),
      :proposed_at, 'resolver', :method, :method_version, :dedupe_sha256,
      :model_id, :model_version, :expected_target_version, :review_case_id,
      :accepted_record_type, :accepted_record_id, :accepted_record_version,
      :invalidated_reason, :superseded_at, :decided_by, :decided_at, NULL
    )
    """  # noqa: S608
)

_INSERT_EVIDENCE: Final = text(
    f"""
    INSERT INTO {SCHEMA}.entity_proposal_evidence_links (
      proposal_id, sequence, principal_id, role,
      entity_observation_id, capture_span_id, knowledge_id, created_at
    ) VALUES (
      :proposal_id, :sequence, :principal_id, :role,
      :entity_observation_id, :capture_span_id, :knowledge_id, :created_at
    )
    """  # noqa: S608
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


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


@pytest.fixture
def staged(disposable_database: str) -> Iterator[Engine]:
    """A migrated database holding two Principals, their entities and observations."""
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            repository = SqlEntityRepository(connection)
            repository.create(PRINCIPAL_A, _entity(ALICE))
            repository.create(PRINCIPAL_A, _entity(ALICE_TWO))
            repository.create(PRINCIPAL_B, _entity(BOB, PRINCIPAL_B, "Bob Chen"))
            repository.record_observation(PRINCIPAL_A, _observation(OBSERVATION_A))
            repository.record_observation(PRINCIPAL_B, _observation(OBSERVATION_B, PRINCIPAL_B))
        yield engine
    finally:
        engine.dispose()


def _proposal(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "proposal_id": "eprp_aaaa0001aaaa0001",
        "principal_id": PRINCIPAL_A,
        "kind": "record_alias",
        "state": "proposed",
        "payload": '{"entity_id": "ent_aaaa0001aaaa0001"}',
        "proposed_at": WHEN,
        "method": "deterministic",
        "method_version": "1",
        "dedupe_sha256": DIGEST,
        "model_id": None,
        "model_version": None,
        "expected_target_version": None,
        "review_case_id": None,
        "accepted_record_type": None,
        "accepted_record_id": None,
        "accepted_record_version": None,
        "invalidated_reason": None,
        "superseded_at": None,
        "decided_by": None,
        "decided_at": None,
    }
    values.update(overrides)
    return values


def _write(connection: Connection, **overrides: object) -> None:
    connection.execute(_INSERT, _proposal(**overrides))


def test_semantically_invalid_payload_writes_neither_proposal_nor_evidence(staged: Engine) -> None:
    with staged.begin() as connection:
        with pytest.raises(ProposalPayloadError, match="known namespace"):
            EntityGovernanceService(SqlEntityRepository(connection)).propose(
                PRINCIPAL_A,
                kind=EntityProposalKind.BIND_IDENTIFIER,
                payload={
                    "entity_id": ALICE,
                    "namespace": "invented",
                    "display_value": "alice@example.invalid",
                },
                observation_ids=(OBSERVATION_A,),
                proposed_by="resolver",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
            )
        for table in ("entity_proposals", "entity_proposal_evidence_links"):
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608
                ).scalar_one()
                == 0
            )


# --- the widened vocabularies -----------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "update_entity",
        "retire_identifier",
        "supersede_identifier",
        "retire_alias",
        "supersede_alias",
        "revise_assignment",
        "end_assignment",
        "revise_relationship",
        "end_relationship",
        "resolve_mention",
        "split_identity",
    ],
)
def test_the_server_admits_each_kind_this_revision_added(staged: Engine, kind: str) -> None:
    """Eleven kinds the four-column record could not name. Each, against the CHECK."""
    with staged.begin() as connection:
        _write(connection, kind=kind)


@pytest.mark.parametrize("state", ["needs_review", "corrected_accepted", "deferred", "invalidated"])
def test_the_server_admits_each_state_this_revision_added(staged: Engine, state: str) -> None:
    decided = state != "needs_review"
    with staged.begin() as connection:
        _write(
            connection,
            state=state,
            decided_by="a reviewer" if decided else None,
            decided_at=WHEN if decided else None,
            invalidated_reason="evidence no longer holds" if state == "invalidated" else None,
        )


def test_the_server_refuses_a_kind_nothing_declares(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="a_proposal_kind_is_known"),
        staged.begin() as c,
    ):
        _write(c, kind="promote_entity")


def test_the_server_refuses_a_state_nothing_declares(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="a_proposal_state_is_known"),
        staged.begin() as c,
    ):
        _write(c, state="applied")


@pytest.mark.parametrize("method", ["cloud_model", "hybrid"])
def test_the_server_refuses_a_method_nothing_declares(staged: Engine, method: str) -> None:
    """The two this vocabulary is deliberately closed against.

    Written with no model named, so the refusal is the method vocabulary rather
    than `a_model_proposal_names_its_model` firing first -- a row that named a
    model would be refused for the wrong reason and this test would pass without
    the method CHECK existing at all.
    """
    with (
        pytest.raises(IntegrityError, match="a_proposal_method_is_known"),
        staged.begin() as c,
    ):
        _write(c, method=method)


# --- method and model identity -----------------------------------------------


def test_the_server_refuses_a_model_named_on_a_deterministic_proposal(staged: Engine) -> None:
    """A row claiming a model ran when the method says none did."""
    with (
        pytest.raises(IntegrityError, match="a_model_proposal_names_its_model"),
        staged.begin() as c,
    ):
        _write(c, model_id="localnamer", model_version="1")


def test_the_server_refuses_a_model_proposal_that_names_no_model(staged: Engine) -> None:
    """The laundering direction: a model conclusion filed under no model identity."""
    with (
        pytest.raises(IntegrityError, match="a_model_proposal_names_its_model"),
        staged.begin() as c,
    ):
        _write(c, method="local_model")


def test_the_server_refuses_a_model_with_no_version(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="states_its_version"),
        staged.begin() as c,
    ):
        _write(c, method="local_model", model_id="localnamer", model_version=None)


def test_the_server_refuses_a_dedupe_value_that_is_not_a_digest(staged: Engine) -> None:
    """Otherwise uniqueness is over whatever token a producer chose to write."""
    with (
        pytest.raises(IntegrityError, match="is_a_sha256_digest"),
        staged.begin() as c,
    ):
        _write(c, dedupe_sha256="not-a-digest")


# --- open-equivalent dedupe ---------------------------------------------------


@pytest.mark.parametrize("second_state", ["proposed", "needs_review", "deferred"])
def test_one_open_equivalent_proposal_per_digest(staged: Engine, second_state: str) -> None:
    """The reviewer sees a candidate once, whichever undisposed state it is in.

    `deferred` is the member that matters: a producer that could re-file an
    identical proposal would clear a reviewer's deferral by repeating itself.
    """
    with staged.begin() as connection:
        _write(connection)
    with (
        pytest.raises(IntegrityError, match="an_open_equivalent_proposal_is_raised_once"),
        staged.begin() as connection,
    ):
        _write(
            connection,
            proposal_id="eprp_bbbb0002bbbb0002",
            state=second_state,
            decided_by="a reviewer" if second_state == "deferred" else None,
            decided_at=WHEN if second_state == "deferred" else None,
        )


@pytest.mark.parametrize("final_state", ["rejected", "invalidated"])
def test_a_finally_disposed_proposal_does_not_block_a_new_one(
    staged: Engine, final_state: str
) -> None:
    """Section 15.2 requires a refused candidate to be raisable again on new evidence.

    A total unique would make that impossible, which is why the index is partial.
    """
    with staged.begin() as connection:
        _write(
            connection,
            state=final_state,
            decided_by="a reviewer",
            decided_at=WHEN,
            invalidated_reason="basis withdrawn" if final_state == "invalidated" else None,
        )
        _write(connection, proposal_id="eprp_bbbb0002bbbb0002")


def test_two_principals_may_raise_the_same_proposal(staged: Engine) -> None:
    """The unique is scoped by Principal; one person's candidate is not another's."""
    with staged.begin() as connection:
        _write(connection)
        _write(connection, proposal_id="eprp_bbbb0002bbbb0002", principal_id=PRINCIPAL_B)


def test_a_different_digest_is_a_different_candidate(staged: Engine) -> None:
    with staged.begin() as connection:
        _write(connection)
        _write(connection, proposal_id="eprp_bbbb0002bbbb0002", dedupe_sha256=OTHER_DIGEST)


# --- decision, supersession and result ---------------------------------------


def test_the_server_refuses_a_decided_proposal_with_no_actor(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="decided_exactly_when"),
        staged.begin() as c,
    ):
        _write(c, state="deferred")


def test_the_server_refuses_an_actor_on_a_needs_review_proposal(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="decided_exactly_when"),
        staged.begin() as c,
    ):
        _write(c, state="needs_review", decided_by="a reviewer", decided_at=WHEN)


def test_the_server_refuses_a_superseded_proposal_with_no_moment(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="a_superseded_proposal_records_when"),
        staged.begin() as c,
    ):
        _write(c, state="superseded")


def test_the_server_refuses_a_superseded_moment_on_any_other_state(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="a_superseded_proposal_records_when"),
        staged.begin() as c,
    ):
        _write(c, superseded_at=WHEN)


def test_a_superseded_proposal_names_no_decider(staged: Engine) -> None:
    """Nobody disposed of an overtaken proposal, so the decision columns stay NULL."""
    with staged.begin() as connection:
        _write(connection, state="superseded", superseded_at=WHEN)


def test_the_server_refuses_an_invalidation_with_no_reason(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="an_invalidated_proposal_records_why"),
        staged.begin() as c,
    ):
        _write(c, state="invalidated", decided_by="a reviewer", decided_at=WHEN)


def test_the_server_refuses_an_accepted_record_on_an_undecided_proposal(staged: Engine) -> None:
    """A promotion with no acceptance behind it."""
    with (
        pytest.raises(IntegrityError, match="only_when_accepted"),
        staged.begin() as c,
    ):
        _write(
            c,
            accepted_record_type="alias",
            accepted_record_id="eals_aaaa0001aaaa0001",
            accepted_record_version=1,
        )


def test_the_server_refuses_a_half_named_accepted_record(staged: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="named_in_full"),
        staged.begin() as c,
    ):
        _write(
            c,
            state="accepted",
            decided_by="a reviewer",
            decided_at=WHEN,
            accepted_record_id="eals_aaaa0001aaaa0001",
        )


def test_the_server_refuses_an_accepted_merge_that_names_a_record(staged: Engine) -> None:
    """Section 15, at the server. Accepting a merge proposal changes no identity.

    A row naming a canonical record for an accepted `merge_entities` proposal
    would present a reviewer's acceptance as an executed identity join -- which
    is the exact thing `entities.merge` exists to keep operator-only.
    """
    with (
        pytest.raises(IntegrityError, match="identity_correction_names_no_record"),
        staged.begin() as c,
    ):
        _write(
            c,
            kind="merge_entities",
            state="accepted",
            decided_by="the operator",
            decided_at=WHEN,
            accepted_record_type="entity",
            accepted_record_id=ALICE,
            accepted_record_version=2,
        )


def test_an_accepted_merge_proposal_naming_no_record_is_admitted(staged: Engine) -> None:
    with staged.begin() as connection:
        _write(
            connection,
            kind="merge_entities",
            state="accepted",
            decided_by="the operator",
            decided_at=WHEN,
        )


# --- proposal evidence links --------------------------------------------------


def _stage_proposal(engine: Engine) -> None:
    with engine.begin() as connection:
        # Evidence writers now hydrate and revalidate their open parent before
        # appending. Stage a domain-valid RECORD_ALIAS rather than the minimal
        # JSON used by the constraint-only cases above, so evidence ownership —
        # not payload parsing — remains the behavior these tests exercise.
        _write(
            connection,
            payload=(
                f'{{"alias_type": "nickname", "display_value": "Ali", "entity_id": "{ALICE}"}}'
            ),
        )


def _stage_knowledge(connection: Connection, principal_id: str, suffix: str) -> str:
    source = f"src_{suffix}0001{suffix}0001"
    object_id = f"obj_{suffix}0001{suffix}0001"
    version = f"ver_{suffix}0001{suffix}0001"
    enrollment = f"enr_{suffix}0001{suffix}0001"
    knowledge = f"kn_{suffix}0001{suffix}0001"
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.sources "  # noqa: S608
            "(source_id, provider_kind, label, classification, native_root) "
            "VALUES (:id, 'fixture', :label, 'synthetic_test', :root)"
        ),
        {"id": source, "label": f"Fixture {suffix}", "root": f"fixture-{suffix}"},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.source_objects "  # noqa: S608
            "(source_object_id, source_id, kind, native_locator) "
            "VALUES (:object, :source, 'file', :locator)"
        ),
        {"object": object_id, "source": source, "locator": f"object-{suffix}"},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.source_object_versions "  # noqa: S608
            "(version_id, source_object_id, fingerprint, modified_at) "
            "VALUES (:version, :object, :fingerprint, :at)"
        ),
        {"version": version, "object": object_id, "fingerprint": suffix * 8, "at": WHEN},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.enrollments "  # noqa: S608
            "(enrollment_id, source_id, principal_id, purpose, policy_version, "
            "idempotency_key, request_fingerprint, object_ids, depth, media_types, "
            "max_items, max_bytes) VALUES (:enrollment, :source, :principal, "
            "'bounded_enrollment', 'mcv-1', :key, :fingerprint, ARRAY[:object], 0, "
            "ARRAY['text/plain'], 10, 1024)"
        ),
        {
            "enrollment": enrollment,
            "source": source,
            "principal": principal_id,
            "key": f"evidence-{suffix}",
            "fingerprint": f"evidence-{suffix}",
            "object": object_id,
        },
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.extractions "  # noqa: S608
            "(extraction_id, enrollment_id, source_object_id, version_id, status, "
            "media_type, extractor, extractor_version, text, observed_at) VALUES "
            "(:knowledge, :enrollment, :object, :version, 'extracted', 'text/plain', "
            "'test', '1', 'text', :at)"
        ),
        {
            "knowledge": knowledge,
            "enrollment": enrollment,
            "object": object_id,
            "version": version,
            "at": WHEN,
        },
    )
    return knowledge


def test_knowledge_evidence_is_scoped_through_its_enrollment(staged: Engine) -> None:
    _stage_proposal(staged)
    with staged.begin() as connection:
        own = _stage_knowledge(connection, PRINCIPAL_A, "aaaa")
        foreign = _stage_knowledge(connection, PRINCIPAL_B, "bbbb")
        SqlEntityRepository(connection).record_proposal_evidence_link(
            PRINCIPAL_A,
            EntityProposalEvidenceLink(
                proposal_id="eprp_aaaa0001aaaa0001",
                principal_id=PRINCIPAL_A,
                sequence=1,
                role=EvidenceRole.SUPPORTING,
                created_at=WHEN,
                knowledge_id=own,
            ),
        )

    for sequence, knowledge in ((2, foreign), (3, issue_identifier(IdKind.KNOWLEDGE))):
        with (
            pytest.raises(UnknownScopeError, match="outside this scope"),
            staged.begin() as connection,
        ):
            SqlEntityRepository(connection).record_proposal_evidence_link(
                PRINCIPAL_A,
                EntityProposalEvidenceLink(
                    proposal_id="eprp_aaaa0001aaaa0001",
                    principal_id=PRINCIPAL_A,
                    sequence=sequence,
                    role=EvidenceRole.SUPPORTING,
                    created_at=WHEN,
                    knowledge_id=knowledge,
                ),
            )
    with staged.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_proposal_evidence_links")  # noqa: S608
            ).scalar_one()
            == 1
        )


def test_proposal_evidence_names_exactly_one_record(staged: Engine) -> None:
    """Three evidence columns, one of which is filled. Zero and two are both refused."""
    _stage_proposal(staged)
    for observation, span in ((None, None), (OBSERVATION_A, "span_aaaa0001aaaa0001")):
        with (
            pytest.raises(IntegrityError, match="names_exactly_one_record"),
            staged.begin() as connection,
        ):
            connection.execute(
                _INSERT_EVIDENCE,
                {
                    "proposal_id": "eprp_aaaa0001aaaa0001",
                    "sequence": 1,
                    "principal_id": PRINCIPAL_A,
                    "role": "direct",
                    "entity_observation_id": observation,
                    "capture_span_id": span,
                    "knowledge_id": None,
                    "created_at": WHEN,
                },
            )


def test_proposal_evidence_records_a_counterevidence_role(staged: Engine) -> None:
    """The member that matters: a link table holding only support proves nothing."""
    _stage_proposal(staged)
    with staged.begin() as connection:
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 1,
                "principal_id": PRINCIPAL_A,
                "role": "counterevidence",
                "entity_observation_id": OBSERVATION_A,
                "capture_span_id": None,
                "knowledge_id": None,
                "created_at": WHEN,
            },
        )


def test_proposal_evidence_refuses_a_role_nothing_declares(staged: Engine) -> None:
    _stage_proposal(staged)
    with (
        pytest.raises(IntegrityError, match="a_proposal_evidence_role_is_known"),
        staged.begin() as connection,
    ):
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 1,
                "principal_id": PRINCIPAL_A,
                "role": "corroborating",
                "entity_observation_id": OBSERVATION_A,
                "capture_span_id": None,
                "knowledge_id": None,
                "created_at": WHEN,
            },
        )


def test_proposal_evidence_cites_an_observation_of_its_own_principal(staged: Engine) -> None:
    """The composite foreign key, and the failure it closes.

    A single-column reference would accept my proposal citing another
    Principal's observation: the observation exists, the proposal is mine, and
    only the pairing crosses. That row would present somebody else's evidence as
    the basis for my candidate.
    """
    _stage_proposal(staged)
    with (
        pytest.raises(IntegrityError, match="cites_an_observation_of_its_principal"),
        staged.begin() as connection,
    ):
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 1,
                "principal_id": PRINCIPAL_A,
                "role": "direct",
                "entity_observation_id": OBSERVATION_B,
                "capture_span_id": None,
                "knowledge_id": None,
                "created_at": WHEN,
            },
        )


def test_proposal_evidence_names_a_proposal_of_its_own_principal(staged: Engine) -> None:
    _stage_proposal(staged)
    with (
        pytest.raises(IntegrityError, match="names_a_proposal_of_its_principal"),
        staged.begin() as connection,
    ):
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 1,
                "principal_id": PRINCIPAL_B,
                "role": "direct",
                "entity_observation_id": None,
                "capture_span_id": None,
                "knowledge_id": "kn_aaaa0001aaaa0001",
                "created_at": WHEN,
            },
        )


def test_one_piece_of_proposal_evidence_per_sequence(staged: Engine) -> None:
    """`(proposal_id, sequence)` orders the evidence and is the record's identity."""
    _stage_proposal(staged)
    with staged.begin() as connection:
        for sequence, knowledge in ((1, "kn_aaaa0001aaaa0001"), (2, "kn_bbbb0002bbbb0002")):
            connection.execute(
                _INSERT_EVIDENCE,
                {
                    "proposal_id": "eprp_aaaa0001aaaa0001",
                    "sequence": sequence,
                    "principal_id": PRINCIPAL_A,
                    "role": "supporting",
                    "entity_observation_id": None,
                    "capture_span_id": None,
                    "knowledge_id": knowledge,
                    "created_at": WHEN,
                },
            )
    with (
        pytest.raises(IntegrityError, match="entity_proposal_evidence_links_pkey"),
        staged.begin() as connection,
    ):
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 1,
                "principal_id": PRINCIPAL_A,
                "role": "supporting",
                "entity_observation_id": None,
                "capture_span_id": None,
                "knowledge_id": "kn_cccc0003cccc0003",
                "created_at": WHEN,
            },
        )


def test_proposal_evidence_is_numbered_from_one(staged: Engine) -> None:
    _stage_proposal(staged)
    with (
        pytest.raises(IntegrityError, match="numbered_from_one"),
        staged.begin() as connection,
    ):
        connection.execute(
            _INSERT_EVIDENCE,
            {
                "proposal_id": "eprp_aaaa0001aaaa0001",
                "sequence": 0,
                "principal_id": PRINCIPAL_A,
                "role": "direct",
                "entity_observation_id": OBSERVATION_A,
                "capture_span_id": None,
                "knowledge_id": None,
                "created_at": WHEN,
            },
        )
