"""WP-9 schema governance, reversibility, exact evidence, and round trip."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, insert, select, text, update
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.identity import (
    DuplicateCandidateSet,
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    IdentityResolutionError,
    ResolutionAction,
    UnresolvedMention,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.relationships import SqlRelationshipRepository
from my_pa.infrastructure.persistence.tables import (
    relationship_affiliations,
    relationship_aliases,
    relationship_conversation_observations,
    relationship_conversation_participants,
    relationship_duplicate_members,
    relationship_duplicate_sets,
    relationship_evidence,
    relationship_evidence_observations,
    relationship_identity_observations,
    relationship_identity_resolutions,
    relationship_identity_review_cases,
    relationship_identity_review_decisions,
    relationship_observation_links,
    relationship_people,
    relationship_resolution_observations,
    relationship_unresolved_mentions,
)

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_relationship_test"
WHEN = datetime(2026, 8, 4, 12, tzinfo=UTC)


def _id(prefix: str, ordinal: int) -> str:
    return f"{prefix}_{ordinal:016d}"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def relationship_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(drop)
        connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    url = configured.set(database=DATABASE).render_as_string(hide_password=False)
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
    engine = create_database_engine(url)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(drop)
        maintenance.dispose()


def _observation(ordinal: int, domain: str) -> IdentityObservation:
    return IdentityObservation(
        observation_id=_id("iobs", ordinal),
        source_id=_id("src", 1),
        source_object_id=_id("obj", ordinal),
        source_version=_id("ver", ordinal),
        observed_at=WHEN,
        display_name=f"Synthetic Person {ordinal}",
    )


def _link_person(
    repository: SqlRelationshipRepository,
    *,
    person_ordinal: int,
    observations: tuple[IdentityObservation, ...],
) -> str:
    candidate = IdentityCandidateSet(
        candidate_set_id=_id("dups", person_ordinal),
        person_ids=(),
        observation_ids=tuple(row.observation_id for row in observations),
        created_at=WHEN,
    )
    review_id = repository.open_identity_review(candidate, ResolutionAction.LINK_OBSERVATION)
    decision_id = repository.decide_identity_review(
        review_id,
        disposition="accept",
        principal_id=_id("prn", 1),
        decided_at=WHEN,
    )
    person_id = _id("per", person_ordinal)
    repository.apply_resolution(
        IdentityResolution(
            resolution_id=_id("ires", person_ordinal),
            action=ResolutionAction.LINK_OBSERVATION,
            review_case_id=review_id,
            decision_id=decision_id,
            retained_person_id=person_id,
            prior_person_id=None,
            observation_ids=tuple(row.observation_id for row in observations),
            decided_at=WHEN,
        ),
        display_name=f"Synthetic Person {person_ordinal}",
    )
    return person_id


def _identity_evidence_snapshot(
    connection: Connection,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    tables = (
        relationship_identity_observations,
        relationship_unresolved_mentions,
        relationship_duplicate_sets,
        relationship_duplicate_members,
        relationship_identity_review_cases,
        relationship_identity_review_decisions,
        relationship_resolution_observations,
    )
    return {
        table.name: tuple(
            tuple(row)
            for row in connection.execute(select(table).order_by(*table.primary_key.columns))
        )
        for table in tables
    }


def _relationship_state_snapshot(
    connection: Connection,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    tables = (
        relationship_people,
        relationship_identity_resolutions,
        relationship_resolution_observations,
        relationship_observation_links,
        relationship_aliases,
        relationship_affiliations,
        relationship_evidence,
        relationship_evidence_observations,
        relationship_conversation_participants,
        relationship_conversation_observations,
    )
    return {
        table.name: tuple(
            tuple(row)
            for row in connection.execute(select(table).order_by(*table.primary_key.columns))
        )
        for table in tables
    }


def _create_conversation(connection: Connection, ordinal: int) -> str:
    ids = {
        "capture": _id("cap", ordinal),
        "version": _id("capver", ordinal),
        "conversation": _id("conv", ordinal),
        "principal": _id("prn", 1),
        "correlation": _id("corr", ordinal),
        "audit": _id("audit", ordinal),
    }
    connection.execute(
        text(
            "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
            "VALUES (:capture, :principal)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO knowledge.capture_versions "
            "(version_id, capture_id, version_number, content, content_sha256, "
            "owner_principal_id, classification, processing_policy, idempotency_key, "
            "correlation_id, audit_id, server_received_at, accepted_at, recorded_at) "
            "VALUES (:version, :capture, 1, 'x', "
            "'2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881', "
            ":principal, 'synthetic_test', 'local_only', :version, :correlation, :audit, "
            "now(), now(), now())"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO knowledge.capture_conversations "
            "(conversation_id, capture_id, version_id, event_state, channel, recorded_at) "
            "VALUES (:conversation, :capture, :version, 'skeletal', 'unknown', now())"
        ),
        ids,
    )
    return ids["conversation"]


def _accepted_correction(
    repository: SqlRelationshipRepository,
    *,
    ordinal: int,
    action: ResolutionAction,
    retained_person_id: str,
    prior_person_id: str,
    observation_ids: tuple[str, ...],
) -> IdentityResolution:
    candidates = DuplicateCandidateSet(
        candidate_set_id=_id("dups", ordinal),
        person_ids=(retained_person_id, prior_person_id),
        observation_ids=observation_ids,
        created_at=WHEN,
    )
    review_id = repository.open_identity_review(
        candidates,
        action,
        retained_person_id=retained_person_id,
        prior_person_id=prior_person_id,
    )
    decision_id = repository.decide_identity_review(
        review_id,
        disposition="accept",
        principal_id=_id("prn", 1),
        decided_at=WHEN,
    )
    return IdentityResolution(
        resolution_id=_id("ires", ordinal),
        action=action,
        review_case_id=review_id,
        decision_id=decision_id,
        retained_person_id=retained_person_id,
        prior_person_id=prior_person_id,
        observation_ids=observation_ids,
        decided_at=WHEN,
    )


@pytest.mark.database
def test_direct_merge_is_denied_before_any_write(relationship_engine: Engine) -> None:
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        before = connection.execute(
            select(func.count()).select_from(relationship_identity_resolutions)
        ).scalar_one()
        with pytest.raises(IdentityResolutionError, match="before persistence"):
            repository.direct_merge(_id("per", 1), _id("per", 2))
        after = connection.execute(
            select(func.count()).select_from(relationship_identity_resolutions)
        ).scalar_one()
    assert before == after == 0


@pytest.mark.database
def test_observed_source_version_cannot_be_silently_rebound(
    relationship_engine: Engine,
) -> None:
    original = _observation(70, "contacts")
    conflicting = IdentityObservation(
        observation_id=_id("iobs", 71),
        source_id=original.source_id,
        source_object_id=original.source_object_id,
        source_version=original.source_version,
        observed_at=WHEN,
        display_name="Conflicting Synthetic Person",
    )
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        assert repository.record_observations("contacts", (original,)) == 1
        assert repository.record_observations("contacts", (original,)) == 0
        before = connection.execute(select(relationship_identity_observations)).all()
        with pytest.raises(IdentityResolutionError, match="cannot be rebound"):
            repository.record_observations("contacts", (conflicting,))
        after = connection.execute(select(relationship_identity_observations)).all()
    assert before == after


@pytest.mark.database
def test_database_refuses_direct_canonical_person_insert_without_review(
    relationship_engine: Engine,
) -> None:
    with relationship_engine.connect() as connection:
        before = connection.execute(
            select(func.count()).select_from(relationship_people)
        ).scalar_one()
    with (
        pytest.raises(DBAPIError, match="canonical person requires a governed resolution"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_people).values(
                person_id=_id("per", 99), display_name="Synthetic Bypass", created_at=WHEN
            )
        )
    with relationship_engine.connect() as connection:
        after = connection.execute(
            select(func.count()).select_from(relationship_people)
        ).scalar_one()
    assert before == after == 0


@pytest.mark.database
def test_rejected_identity_review_cannot_persist_a_resolution(
    relationship_engine: Engine,
) -> None:
    observations = (_observation(1, "contacts"), _observation(2, "email"))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", (observations[0],))
        repository.record_observations("email", (observations[1],))
        first = _link_person(repository, person_ordinal=1, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=2, observations=(observations[1],))

    with (
        pytest.raises(DBAPIError, match="exact accepted review"),
        relationship_engine.begin() as connection,
    ):
        repository = SqlRelationshipRepository(connection)
        review_id = repository.open_identity_review(
            DuplicateCandidateSet(
                candidate_set_id=_id("dups", 22),
                person_ids=(first, second),
                observation_ids=(observations[0].observation_id,),
                created_at=WHEN,
            ),
            ResolutionAction.SPLIT_PERSON,
            retained_person_id=first,
            prior_person_id=second,
        )
        decision_id = repository.decide_identity_review(
            review_id,
            disposition="reject",
            principal_id=_id("prn", 1),
            decided_at=WHEN,
        )
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=_id("ires", 20),
                action="split_person",
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=first,
                prior_person_id=second,
                decided_at=WHEN,
            )
        )


@pytest.mark.database
def test_merge_review_requires_exact_distinct_candidate_people(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(73, 76))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        people = tuple(
            _link_person(repository, person_ordinal=index, observations=(observation,))
            for index, observation in zip(range(73, 76), observations, strict=True)
        )
        counts_before = (
            connection.execute(
                select(func.count()).select_from(relationship_duplicate_sets)
            ).scalar_one(),
            connection.execute(
                select(func.count()).select_from(relationship_identity_review_cases)
            ).scalar_one(),
        )
        with pytest.raises(IdentityResolutionError, match="exactly two reviewed people"):
            repository.open_identity_review(
                DuplicateCandidateSet(
                    candidate_set_id=_id("dups", 76),
                    person_ids=(people[0], people[2]),
                    observation_ids=(observations[1].observation_id,),
                    created_at=WHEN,
                ),
                ResolutionAction.MERGE_PERSON,
                retained_person_id=people[0],
                prior_person_id=people[1],
            )
        counts_after = (
            connection.execute(
                select(func.count()).select_from(relationship_duplicate_sets)
            ).scalar_one(),
            connection.execute(
                select(func.count()).select_from(relationship_identity_review_cases)
            ).scalar_one(),
        )
    assert counts_before == counts_after

    with (
        pytest.raises(DBAPIError, match="honest candidate set"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_duplicate_sets).values(
                duplicate_set_id=_id("dups", 77), candidate_kind="duplicate", created_at=WHEN
            )
        )
        for person_id in (people[0], people[2]):
            connection.execute(
                insert(relationship_duplicate_members).values(
                    duplicate_set_id=_id("dups", 77), person_id=person_id
                )
            )
        connection.execute(
            insert(relationship_identity_review_cases).values(
                review_case_id=_id("rvw", 77),
                duplicate_set_id=_id("dups", 77),
                requested_action="merge_person",
                retained_person_id=people[0],
                prior_person_id=people[1],
            )
        )
    with relationship_engine.connect() as connection:
        assert not connection.execute(
            select(relationship_duplicate_sets).where(
                relationship_duplicate_sets.c.duplicate_set_id == _id("dups", 77)
            )
        ).all()


@pytest.mark.database
def test_accepted_merge_and_split_receipts_cannot_commit_without_exact_final_state(
    relationship_engine: Engine,
) -> None:
    observations = (_observation(181, "contacts"), _observation(182, "contacts"))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=181, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=182, observations=(observations[1],))
        raw_merge = _accepted_correction(
            repository,
            ordinal=183,
            action=ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
            observation_ids=(observations[1].observation_id,),
        )
    with relationship_engine.connect() as connection:
        before_raw_merge = _relationship_state_snapshot(connection)

    with (
        pytest.raises(DBAPIError, match="exact final person state"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=raw_merge.resolution_id,
                action=raw_merge.action.value,
                review_case_id=raw_merge.review_case_id,
                decision_id=raw_merge.decision_id,
                retained_person_id=raw_merge.retained_person_id,
                prior_person_id=raw_merge.prior_person_id,
                decided_at=raw_merge.decided_at,
            )
        )
        connection.execute(
            insert(relationship_resolution_observations).values(
                resolution_id=raw_merge.resolution_id,
                observation_id=observations[1].observation_id,
            )
        )
        with pytest.raises(IdentityResolutionError, match="current canonical resolution state"):
            SqlRelationshipRepository(connection).profile(second, expected_domains=("contacts",))
    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before_raw_merge

    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.apply_resolution(raw_merge, display_name="unused")
        repository.apply_resolution(raw_merge, display_name="unused")
        assert repository.profile(first, expected_domains=("contacts",)) is not None
        raw_split = _accepted_correction(
            repository,
            ordinal=184,
            action=ResolutionAction.SPLIT_PERSON,
            retained_person_id=second,
            prior_person_id=first,
            observation_ids=(observations[1].observation_id,),
        )
    with relationship_engine.connect() as connection:
        before_raw_split = _relationship_state_snapshot(connection)

    with (
        pytest.raises(DBAPIError, match="exact final person state"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=raw_split.resolution_id,
                action=raw_split.action.value,
                review_case_id=raw_split.review_case_id,
                decision_id=raw_split.decision_id,
                retained_person_id=raw_split.retained_person_id,
                prior_person_id=raw_split.prior_person_id,
                decided_at=raw_split.decided_at,
            )
        )
        connection.execute(
            insert(relationship_resolution_observations).values(
                resolution_id=raw_split.resolution_id,
                observation_id=observations[1].observation_id,
            )
        )
    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before_raw_split

    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.apply_resolution(raw_split, display_name="unused")
        repository.apply_resolution(raw_split, display_name="unused")
        assert repository.profile(first, expected_domains=("contacts",)) is not None
        assert repository.profile(second, expected_domains=("contacts",)) is not None


@pytest.mark.database
@pytest.mark.parametrize("action", tuple(ResolutionAction), ids=lambda action: action.value)
def test_every_accepted_resolution_action_requires_complete_final_state_at_commit(
    relationship_engine: Engine,
    action: ResolutionAction,
) -> None:
    observations = (_observation(185, "contacts"), _observation(186, "contacts"))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        if action is ResolutionAction.LINK_OBSERVATION:
            candidate = IdentityCandidateSet(
                candidate_set_id=_id("dups", 185),
                person_ids=(),
                observation_ids=(observations[0].observation_id,),
                created_at=WHEN,
            )
            review_id = repository.open_identity_review(candidate, action)
            decision_id = repository.decide_identity_review(
                review_id,
                disposition="accept",
                principal_id=_id("prn", 1),
                decided_at=WHEN,
            )
            resolution = IdentityResolution(
                resolution_id=_id("ires", 185),
                action=action,
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=_id("per", 185),
                prior_person_id=None,
                observation_ids=(observations[0].observation_id,),
                decided_at=WHEN,
            )
        else:
            first = _link_person(repository, person_ordinal=185, observations=(observations[0],))
            second = _link_person(repository, person_ordinal=186, observations=(observations[1],))
            resolution = _accepted_correction(
                repository,
                ordinal=187,
                action=action,
                retained_person_id=first,
                prior_person_id=second,
                observation_ids=(observations[1].observation_id,),
            )
    with relationship_engine.connect() as connection:
        before = _relationship_state_snapshot(connection)

    with pytest.raises(DBAPIError), relationship_engine.begin() as connection:
        if action is ResolutionAction.LINK_OBSERVATION:
            connection.execute(
                insert(relationship_people).values(
                    person_id=resolution.retained_person_id,
                    display_name="Unapplied accepted identity",
                    created_at=WHEN,
                )
            )
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=resolution.resolution_id,
                action=resolution.action.value,
                review_case_id=resolution.review_case_id,
                decision_id=resolution.decision_id,
                retained_person_id=resolution.retained_person_id,
                prior_person_id=resolution.prior_person_id,
                decided_at=resolution.decided_at,
            )
        )
        connection.execute(
            insert(relationship_resolution_observations).values(
                resolution_id=resolution.resolution_id,
                observation_id=resolution.observation_ids[0],
            )
        )

    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before


@pytest.mark.database
@pytest.mark.parametrize(
    "omission",
    (
        "person_state",
        "observation_link",
        "evidence",
        "evidence_lineage",
        "alias",
        "wrong_receipt_owner",
    ),
)
def test_accepted_link_receipt_cannot_commit_with_incomplete_final_state(
    relationship_engine: Engine,
    omission: str,
) -> None:
    observation = _observation(188, "contacts")
    person_id = _id("per", 188)
    resolution_id = _id("ires", 188)
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", (observation,))
        candidate = IdentityCandidateSet(
            candidate_set_id=_id("dups", 188),
            person_ids=(),
            observation_ids=(observation.observation_id,),
            created_at=WHEN,
        )
        review_id = repository.open_identity_review(candidate, ResolutionAction.LINK_OBSERVATION)
        decision_id = repository.decide_identity_review(
            review_id,
            disposition="accept",
            principal_id=_id("prn", 1),
            decided_at=WHEN,
        )
        if omission == "wrong_receipt_owner":
            competing_candidate = IdentityCandidateSet(
                candidate_set_id=_id("dups", 190),
                person_ids=(),
                observation_ids=(observation.observation_id,),
                created_at=WHEN,
            )
            competing_review_id = repository.open_identity_review(
                competing_candidate, ResolutionAction.LINK_OBSERVATION
            )
            competing_decision_id = repository.decide_identity_review(
                competing_review_id,
                disposition="accept",
                principal_id=_id("prn", 1),
                decided_at=WHEN,
            )
    with relationship_engine.connect() as connection:
        before = _relationship_state_snapshot(connection)

    with pytest.raises(DBAPIError), relationship_engine.begin() as connection:
        connection.execute(
            insert(relationship_people).values(
                person_id=person_id,
                display_name="Incomplete accepted identity",
                created_at=WHEN,
            )
        )
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=resolution_id,
                action="link_observation",
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=person_id,
                prior_person_id=None,
                decided_at=WHEN,
            )
        )
        if omission != "person_state":
            connection.execute(
                update(relationship_people)
                .where(relationship_people.c.person_id == person_id)
                .values(state_resolution_id=resolution_id)
            )
        connection.execute(
            insert(relationship_resolution_observations).values(
                resolution_id=resolution_id,
                observation_id=observation.observation_id,
            )
        )
        if omission not in {"observation_link", "wrong_receipt_owner"}:
            connection.execute(
                insert(relationship_observation_links).values(
                    observation_id=observation.observation_id,
                    person_id=person_id,
                    resolution_id=resolution_id,
                )
            )
            if omission != "alias":
                connection.execute(
                    insert(relationship_aliases).values(
                        alias_id=_id("alias", 188),
                        person_id=person_id,
                        observation_id=observation.observation_id,
                        value=observation.display_name,
                    )
                )
        if omission not in {"evidence", "wrong_receipt_owner"}:
            evidence_id = f"source_{observation.observation_id}"
            connection.execute(
                insert(relationship_evidence).values(
                    evidence_id=evidence_id,
                    person_id=person_id,
                    authority="source_observation",
                    recorded_at=WHEN,
                )
            )
            if omission != "evidence_lineage":
                connection.execute(
                    insert(relationship_evidence_observations).values(
                        evidence_id=evidence_id,
                        observation_id=observation.observation_id,
                    )
                )
        if omission == "wrong_receipt_owner":
            competing_person_id = _id("per", 190)
            competing_resolution_id = _id("ires", 190)
            connection.execute(
                insert(relationship_people).values(
                    person_id=competing_person_id,
                    display_name="Competing accepted identity",
                    created_at=WHEN,
                )
            )
            connection.execute(
                insert(relationship_identity_resolutions).values(
                    resolution_id=competing_resolution_id,
                    action="link_observation",
                    review_case_id=competing_review_id,
                    decision_id=competing_decision_id,
                    retained_person_id=competing_person_id,
                    prior_person_id=None,
                    decided_at=WHEN,
                )
            )
            connection.execute(
                update(relationship_people)
                .where(relationship_people.c.person_id == competing_person_id)
                .values(state_resolution_id=competing_resolution_id)
            )
            connection.execute(
                insert(relationship_resolution_observations).values(
                    resolution_id=competing_resolution_id,
                    observation_id=observation.observation_id,
                )
            )
            connection.execute(
                insert(relationship_observation_links).values(
                    observation_id=observation.observation_id,
                    person_id=competing_person_id,
                    resolution_id=competing_resolution_id,
                )
            )
            connection.execute(
                insert(relationship_aliases).values(
                    alias_id=_id("alias", 190),
                    person_id=competing_person_id,
                    observation_id=observation.observation_id,
                    value=observation.display_name,
                )
            )
            evidence_id = f"source_{observation.observation_id}"
            connection.execute(
                insert(relationship_evidence).values(
                    evidence_id=evidence_id,
                    person_id=competing_person_id,
                    authority="source_observation",
                    recorded_at=WHEN,
                )
            )
            connection.execute(
                insert(relationship_evidence_observations).values(
                    evidence_id=evidence_id,
                    observation_id=observation.observation_id,
                )
            )

    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before


@pytest.mark.database
def test_governed_link_is_idempotent_and_profile_fails_closed_if_receipt_link_is_missing(
    relationship_engine: Engine,
) -> None:
    observation = _observation(189, "contacts")
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", (observation,))
        candidate = IdentityCandidateSet(
            candidate_set_id=_id("dups", 189),
            person_ids=(),
            observation_ids=(observation.observation_id,),
            created_at=WHEN,
        )
        review_id = repository.open_identity_review(candidate, ResolutionAction.LINK_OBSERVATION)
        decision_id = repository.decide_identity_review(
            review_id,
            disposition="accept",
            principal_id=_id("prn", 1),
            decided_at=WHEN,
        )
        resolution = IdentityResolution(
            resolution_id=_id("ires", 189),
            action=ResolutionAction.LINK_OBSERVATION,
            review_case_id=review_id,
            decision_id=decision_id,
            retained_person_id=_id("per", 189),
            prior_person_id=None,
            observation_ids=(observation.observation_id,),
            decided_at=WHEN,
        )
        repository.apply_resolution(resolution, display_name="Synthetic Person 189")
        before_retry = _relationship_state_snapshot(connection)
        repository.apply_resolution(resolution, display_name="Synthetic Person 189")
        assert _relationship_state_snapshot(connection) == before_retry
        assert repository.profile(resolution.retained_person_id, expected_domains=("contacts",))

    with relationship_engine.connect() as connection:
        before_delete = _relationship_state_snapshot(connection)
    with (
        pytest.raises(DBAPIError, match="current observation links cannot be deleted"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            relationship_observation_links.delete().where(
                relationship_observation_links.c.observation_id == observation.observation_id
            )
        )
    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before_delete

    # Exercise the read-side fail-closed guard without weakening committed
    # production state: the trigger change and stale plant are both rolled back.
    with relationship_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "ALTER TABLE knowledge.relationship_observation_links "
                    "DISABLE TRIGGER observation_link_requires_current_resolution"
                )
            )
            connection.execute(
                relationship_observation_links.delete().where(
                    relationship_observation_links.c.observation_id == observation.observation_id
                )
            )
            with pytest.raises(IdentityResolutionError, match="current canonical resolution state"):
                SqlRelationshipRepository(connection).profile(
                    resolution.retained_person_id, expected_domains=("contacts",)
                )
        finally:
            transaction.rollback()
    with relationship_engine.connect() as connection:
        assert _relationship_state_snapshot(connection) == before_delete


@pytest.mark.database
def test_merge_then_governed_split_restores_exact_links_and_keeps_lineage(
    relationship_engine: Engine,
) -> None:
    observations = tuple(
        _observation(index, "contacts" if index % 2 else "email") for index in range(1, 5)
    )
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        for index, observation in enumerate(observations, start=1):
            repository.record_observations("contacts" if index % 2 else "email", (observation,))
        first = _link_person(repository, person_ordinal=1, observations=observations[:2])
        second = _link_person(repository, person_ordinal=2, observations=observations[2:])
        initial_aliases = {
            str(row.observation_id): (str(row.person_id), str(row.value))
            for row in connection.execute(select(relationship_aliases))
        }
        assert initial_aliases == {
            observation.observation_id: (
                first if index < 2 else second,
                f"Synthetic Person {index + 1}",
            )
            for index, observation in enumerate(observations)
        }

    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        merge_set = DuplicateCandidateSet(
            candidate_set_id=_id("dups", 30),
            person_ids=(first, second),
            observation_ids=tuple(row.observation_id for row in observations[2:]),
            created_at=WHEN,
        )
        review_id = repository.open_identity_review(
            merge_set,
            ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
        )
        decision_id = repository.decide_identity_review(
            review_id, disposition="accept", principal_id=_id("prn", 1), decided_at=WHEN
        )
        repository.apply_resolution(
            IdentityResolution(
                resolution_id=_id("ires", 30),
                action=ResolutionAction.MERGE_PERSON,
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=first,
                prior_person_id=second,
                observation_ids=tuple(row.observation_id for row in observations[2:]),
                decided_at=WHEN,
            ),
            display_name="unused",
        )

    with relationship_engine.begin() as connection:
        merged = {
            str(row.observation_id): str(row.person_id)
            for row in connection.execute(select(relationship_observation_links))
        }
        assert set(merged.values()) == {first}
        assert {str(row.person_id) for row in connection.execute(select(relationship_aliases))} == {
            first
        }
        repository = SqlRelationshipRepository(connection)
        split_set = DuplicateCandidateSet(
            candidate_set_id=_id("dups", 31),
            person_ids=(first, second),
            observation_ids=tuple(row.observation_id for row in observations[2:]),
            created_at=WHEN,
        )
        split_review = repository.open_identity_review(
            split_set,
            ResolutionAction.SPLIT_PERSON,
            retained_person_id=second,
            prior_person_id=first,
        )
        split_decision = repository.decide_identity_review(
            split_review, disposition="accept", principal_id=_id("prn", 1), decided_at=WHEN
        )
        repository.apply_resolution(
            IdentityResolution(
                resolution_id=_id("ires", 31),
                action=ResolutionAction.SPLIT_PERSON,
                review_case_id=split_review,
                decision_id=split_decision,
                retained_person_id=second,
                prior_person_id=first,
                observation_ids=tuple(row.observation_id for row in observations[2:]),
                decided_at=WHEN,
            ),
            display_name="unused",
        )

    with relationship_engine.connect() as connection:
        links = {
            str(row.observation_id): str(row.person_id)
            for row in connection.execute(select(relationship_observation_links))
        }
        assert links == {
            observations[0].observation_id: first,
            observations[1].observation_id: first,
            observations[2].observation_id: second,
            observations[3].observation_id: second,
        }
        aliases_after_split = {
            str(row.observation_id): (str(row.person_id), str(row.value))
            for row in connection.execute(select(relationship_aliases))
        }
        assert aliases_after_split == initial_aliases
        alias_rows_before_plants = tuple(
            connection.execute(
                select(relationship_aliases).order_by(relationship_aliases.c.alias_id)
            )
        )
        assert (
            connection.execute(
                select(func.count()).select_from(relationship_identity_resolutions)
            ).scalar_one()
            == 4
        )
        assert (
            connection.execute(
                select(func.count()).select_from(relationship_identity_review_decisions)
            ).scalar_one()
            == 4
        )
        assert (
            connection.execute(
                select(func.count()).select_from(relationship_resolution_observations)
            ).scalar_one()
            == 8
        )

    for statement, parameters, message in (
        (
            "UPDATE knowledge.relationship_aliases SET value = 'invented alias' "
            "WHERE observation_id = :observation",
            {"observation": observations[2].observation_id},
            "alias provenance is immutable",
        ),
        (
            "UPDATE knowledge.relationship_aliases SET person_id = :person "
            "WHERE observation_id = :observation",
            {"person": first, "observation": observations[2].observation_id},
            "exact current observation",
        ),
        (
            "UPDATE knowledge.relationship_aliases SET alias_id = :alias "
            "WHERE observation_id = :observation",
            {"alias": _id("alias", 99), "observation": observations[2].observation_id},
            "alias provenance is immutable",
        ),
        (
            "DELETE FROM knowledge.relationship_aliases WHERE observation_id = :observation",
            {"observation": observations[2].observation_id},
            "source-bound aliases cannot be deleted",
        ),
    ):
        with (
            pytest.raises(DBAPIError, match=message),
            relationship_engine.begin() as connection,
        ):
            connection.execute(text(statement), parameters)
    with relationship_engine.connect() as connection:
        alias_rows_after_plants = tuple(
            connection.execute(
                select(relationship_aliases).order_by(relationship_aliases.c.alias_id)
            )
        )
    assert alias_rows_after_plants == alias_rows_before_plants

    with (
        pytest.raises(DBAPIError, match="governed resolution"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE knowledge.relationship_people "
                "SET superseded_by_person_id = :first, state_resolution_id = :old_merge "
                "WHERE person_id = :second"
            ),
            {"first": first, "second": second, "old_merge": _id("ires", 30)},
        )
    with (
        pytest.raises(DBAPIError, match="current exact resolution"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            relationship_observation_links.update()
            .where(
                relationship_observation_links.c.observation_id == observations[2].observation_id
            )
            .values(person_id=first, resolution_id=_id("ires", 30))
        )
    with relationship_engine.connect() as connection:
        unchanged = {
            str(row.observation_id): str(row.person_id)
            for row in connection.execute(select(relationship_observation_links))
        }
        assert unchanged[observations[2].observation_id] == second

    with relationship_engine.begin() as connection:
        SqlRelationshipRepository(connection).record_unresolved_mention(
            UnresolvedMention(
                unresolved_mention_id=_id("umen", 31),
                source_object_id=observations[0].source_object_id,
                source_version=observations[0].source_version,
                observed_at=WHEN,
            )
        )
    with relationship_engine.connect() as connection:
        evidence_before = _identity_evidence_snapshot(connection)
        people_before = tuple(
            tuple(row)
            for row in connection.execute(
                select(relationship_people).order_by(relationship_people.c.person_id)
            )
        )
        active_triggers = set(
            connection.execute(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid IN ("
                    "'knowledge.relationship_identity_observations'::regclass, "
                    "'knowledge.relationship_unresolved_mentions'::regclass, "
                    "'knowledge.relationship_duplicate_sets'::regclass, "
                    "'knowledge.relationship_duplicate_members'::regclass, "
                    "'knowledge.relationship_identity_review_cases'::regclass, "
                    "'knowledge.relationship_identity_review_decisions'::regclass, "
                    "'knowledge.relationship_identity_resolutions'::regclass, "
                    "'knowledge.relationship_resolution_observations'::regclass, "
                    "'knowledge.relationship_evidence'::regclass, "
                    "'knowledge.relationship_evidence_observations'::regclass, "
                    "'knowledge.relationship_affiliations'::regclass, "
                    "'knowledge.relationship_aliases'::regclass, "
                    "'knowledge.relationship_conversation_participants'::regclass, "
                    "'knowledge.relationship_conversation_observations'::regclass, "
                    "'knowledge.relationship_observation_links'::regclass) "
                    "AND NOT tgisinternal AND tgenabled <> 'D'"
                )
            ).scalars()
        )
        assert {
            "identity_observations_are_append_only",
            "unresolved_mentions_are_append_only",
            "identity_candidate_sets_are_append_only",
            "identity_candidate_members_are_append_only",
            "identity_review_cases_are_append_only",
            "identity_review_decisions_are_append_only",
            "identity_resolution_requires_review",
            "identity_resolution_requires_exact_observations",
            "identity_resolutions_are_append_only",
            "zz_identity_corrections_require_complete_final_state",
            "resolution_observations_are_append_only",
            "relationship_evidence_is_governed",
            "relationship_evidence_observations_are_append_only",
            "relationship_affiliations_match_observations",
            "relationship_aliases_match_observations",
            "conversation_participant_changes_are_governed",
            "conversation_support_matches_participant",
            "conversation_participants_remain_supported",
            "conversation_observations_remain_supported",
            "observation_link_keeps_participants_supported",
        } <= active_triggers

    evidence_plants = (
        (
            "UPDATE knowledge.relationship_identity_observations "
            "SET display_name = 'rewritten' WHERE observation_id = :id",
            {"id": observations[0].observation_id},
        ),
        (
            "DELETE FROM knowledge.relationship_unresolved_mentions "
            "WHERE unresolved_mention_id = :id",
            {"id": _id("umen", 31)},
        ),
        (
            "UPDATE knowledge.relationship_duplicate_sets "
            "SET created_at = created_at + interval '1 second' WHERE duplicate_set_id = :id",
            {"id": _id("dups", 30)},
        ),
        (
            "DELETE FROM knowledge.relationship_duplicate_members WHERE duplicate_set_id = :id",
            {"id": _id("dups", 30)},
        ),
        (
            "UPDATE knowledge.relationship_identity_review_cases "
            "SET requested_action = 'link_observation' WHERE review_case_id = :id",
            {"id": split_review},
        ),
        (
            "UPDATE knowledge.relationship_identity_review_decisions "
            "SET disposition = 'reject' WHERE decision_id = :id",
            {"id": split_decision},
        ),
        (
            "DELETE FROM knowledge.relationship_resolution_observations WHERE resolution_id = :id",
            {"id": _id("ires", 31)},
        ),
    )
    for statement, parameters in evidence_plants:
        with (
            pytest.raises(DBAPIError, match="identity evidence is append-only"),
            relationship_engine.begin() as connection,
        ):
            connection.execute(text(statement), parameters)

    person_plants = (
        (
            "UPDATE knowledge.relationship_people SET display_name = 'rewritten' "
            "WHERE person_id = :person",
            {"person": first},
            "identity fields are immutable",
        ),
        (
            "UPDATE knowledge.relationship_people "
            "SET created_at = created_at + interval '1 second' "
            "WHERE person_id = :person",
            {"person": first},
            "identity fields are immutable",
        ),
        (
            "UPDATE knowledge.relationship_people SET state_resolution_id = :resolution "
            "WHERE person_id = :person",
            {"person": second, "resolution": _id("ires", 2)},
            "governed resolution",
        ),
    )
    for statement, parameters, message in person_plants:
        with (
            pytest.raises(DBAPIError, match=message),
            relationship_engine.begin() as connection,
        ):
            connection.execute(text(statement), parameters)

    with relationship_engine.connect() as connection:
        assert _identity_evidence_snapshot(connection) == evidence_before
        people_after = tuple(
            tuple(row)
            for row in connection.execute(
                select(relationship_people).order_by(relationship_people.c.person_id)
            )
        )
    assert people_after == people_before

    # A byte-identical retry while its state is still current returns the same
    # receipt without appending lineage. The split is current here.
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        before = connection.execute(
            select(func.count()).select_from(relationship_identity_resolutions)
        ).scalar_one()
        aliases_before_retry = tuple(
            connection.execute(
                select(relationship_aliases).order_by(relationship_aliases.c.alias_id)
            )
        )
        repository.apply_resolution(
            IdentityResolution(
                resolution_id=_id("ires", 31),
                action=ResolutionAction.SPLIT_PERSON,
                review_case_id=split_review,
                decision_id=split_decision,
                retained_person_id=second,
                prior_person_id=first,
                observation_ids=tuple(row.observation_id for row in observations[2:]),
                decided_at=WHEN,
            ),
            display_name="unused",
        )
        after = connection.execute(
            select(func.count()).select_from(relationship_identity_resolutions)
        ).scalar_one()
        aliases_after_retry = tuple(
            connection.execute(
                select(relationship_aliases).order_by(relationship_aliases.c.alias_id)
            )
        )
        assert before == after == 4
        assert aliases_after_retry == aliases_before_retry


@pytest.mark.database
def test_merge_and_split_atomically_move_supported_participants_and_evidence(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(101, 105))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=101, observations=observations[:2])
        second = _link_person(repository, person_ordinal=102, observations=observations[2:])
        conversation_id = _create_conversation(connection, 101)
        participant_id = repository.attach_conversation_participant(
            conversation_id,
            person_id=second,
            observation_ids=(observations[2].observation_id,),
        )
        merge = _accepted_correction(
            repository,
            ordinal=103,
            action=ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
            observation_ids=tuple(row.observation_id for row in observations[2:]),
        )
        repository.apply_resolution(merge, display_name="unused")
        assert (
            connection.execute(
                select(relationship_conversation_participants.c.person_id).where(
                    relationship_conversation_participants.c.participant_id == participant_id
                )
            ).scalar_one()
            == first
        )
        assert set(
            connection.execute(
                select(relationship_evidence.c.person_id).where(
                    relationship_evidence.c.evidence_id.in_(
                        tuple(f"source_{row.observation_id}" for row in observations[2:])
                    )
                )
            ).scalars()
        ) == {first}

        split = _accepted_correction(
            repository,
            ordinal=104,
            action=ResolutionAction.SPLIT_PERSON,
            retained_person_id=second,
            prior_person_id=first,
            observation_ids=tuple(row.observation_id for row in observations[2:]),
        )
        repository.apply_resolution(split, display_name="unused")
        assert (
            connection.execute(
                select(relationship_conversation_participants.c.person_id).where(
                    relationship_conversation_participants.c.participant_id == participant_id
                )
            ).scalar_one()
            == second
        )
        assert set(
            connection.execute(
                select(relationship_evidence.c.person_id).where(
                    relationship_evidence.c.evidence_id.in_(
                        tuple(f"source_{row.observation_id}" for row in observations[2:])
                    )
                )
            ).scalars()
        ) == {second}
        assert tuple(
            connection.execute(
                select(relationship_conversation_observations.c.observation_id).where(
                    relationship_conversation_observations.c.participant_id == participant_id
                )
            ).scalars()
        ) == (observations[2].observation_id,)

    moved_evidence_ids = tuple(f"source_{row.observation_id}" for row in observations[2:])
    with relationship_engine.connect() as connection:
        evidence_after_split = tuple(
            connection.execute(
                select(relationship_evidence)
                .where(relationship_evidence.c.evidence_id.in_(moved_evidence_ids))
                .order_by(relationship_evidence.c.evidence_id)
            )
        )
    with (
        pytest.raises(DBAPIError, match="exact current resolution"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            update(relationship_evidence)
            .where(relationship_evidence.c.evidence_id.in_(moved_evidence_ids))
            .values(person_id=first)
        )
    with relationship_engine.connect() as connection:
        assert (
            tuple(
                connection.execute(
                    select(relationship_evidence)
                    .where(relationship_evidence.c.evidence_id.in_(moved_evidence_ids))
                    .order_by(relationship_evidence.c.evidence_id)
                )
            )
            == evidence_after_split
        )


@pytest.mark.database
def test_merge_denies_ambiguous_participant_support_without_writes(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(111, 114))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=111, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=112, observations=observations[1:])
        repository.attach_conversation_participant(
            _create_conversation(connection, 111),
            person_id=second,
            observation_ids=tuple(row.observation_id for row in observations[1:]),
        )
        merge = _accepted_correction(
            repository,
            ordinal=113,
            action=ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
            observation_ids=(observations[1].observation_id,),
        )
        before = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_evidence))),
        )
        with pytest.raises(IdentityResolutionError, match="ambiguous conversation support"):
            repository.apply_resolution(merge, display_name="unused")
        after = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_evidence))),
        )
        assert after == before


@pytest.mark.database
def test_merge_refuses_conversation_participant_collision_without_writes(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(115, 117))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=115, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=116, observations=(observations[1],))
        conversation_id = _create_conversation(connection, 115)
        repository.attach_conversation_participant(
            conversation_id,
            person_id=first,
            observation_ids=(observations[0].observation_id,),
        )
        repository.attach_conversation_participant(
            conversation_id,
            person_id=second,
            observation_ids=(observations[1].observation_id,),
        )
        merge = _accepted_correction(
            repository,
            ordinal=117,
            action=ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
            observation_ids=(observations[1].observation_id,),
        )
        before = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
        )
        with pytest.raises(IdentityResolutionError, match="collapse distinct"):
            repository.apply_resolution(merge, display_name="unused")
        after = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
        )
        assert after == before


@pytest.mark.database
def test_split_denies_ambiguous_participant_support_without_writes(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(121, 123))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=121, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=122, observations=(observations[1],))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.apply_resolution(
            _accepted_correction(
                repository,
                ordinal=123,
                action=ResolutionAction.MERGE_PERSON,
                retained_person_id=first,
                prior_person_id=second,
                observation_ids=(observations[1].observation_id,),
            ),
            display_name="unused",
        )
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.attach_conversation_participant(
            _create_conversation(connection, 121),
            person_id=first,
            observation_ids=tuple(row.observation_id for row in observations),
        )
        split = _accepted_correction(
            repository,
            ordinal=124,
            action=ResolutionAction.SPLIT_PERSON,
            retained_person_id=second,
            prior_person_id=first,
            observation_ids=(observations[1].observation_id,),
        )
        before = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_evidence))),
        )
        with pytest.raises(IdentityResolutionError, match="ambiguous conversation support"):
            repository.apply_resolution(split, display_name="unused")
        after = (
            tuple(connection.execute(select(relationship_identity_resolutions))),
            tuple(connection.execute(select(relationship_observation_links))),
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_evidence))),
        )
        assert after == before


@pytest.mark.database
def test_database_denies_stale_participant_and_evidence_rewrites_with_rollback(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(131, 133))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=131, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=132, observations=(observations[1],))
        conversation_id = _create_conversation(connection, 131)
        empty_support_conversation_id = _create_conversation(connection, 132)
        participant_id = repository.attach_conversation_participant(
            conversation_id,
            person_id=first,
            observation_ids=(observations[0].observation_id,),
        )
        with pytest.raises(IdentityResolutionError, match="requires exact support"):
            repository.attach_conversation_participant(conversation_id, person_id=first)
        evidence_id = f"source_{observations[0].observation_id}"

    def snapshot(connection: Connection) -> tuple[object, ...]:
        return (
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_conversation_observations))),
            tuple(connection.execute(select(relationship_evidence))),
            tuple(connection.execute(select(relationship_evidence_observations))),
        )

    with relationship_engine.connect() as connection:
        before = snapshot(connection)

    with (
        pytest.raises(DBAPIError, match="participant support is stale"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_conversation_participants).values(
                participant_id=_id("cpart", 132),
                conversation_id=empty_support_conversation_id,
                person_id=second,
                unresolved_mention_id=None,
            )
        )

    plants = (
        (
            "UPDATE knowledge.relationship_conversation_participants "
            "SET person_id = :second WHERE participant_id = :participant",
            {"second": second, "participant": participant_id},
            "exact current resolution",
        ),
        (
            "UPDATE knowledge.relationship_conversation_participants "
            "SET conversation_id = :conversation WHERE participant_id = :participant",
            {"conversation": empty_support_conversation_id, "participant": participant_id},
            "participant provenance is immutable",
        ),
        (
            "DELETE FROM knowledge.relationship_conversation_participants "
            "WHERE participant_id = :participant",
            {"participant": participant_id},
            "conversation participants cannot be deleted",
        ),
        (
            "UPDATE knowledge.relationship_conversation_observations "
            "SET observation_id = :other WHERE participant_id = :participant",
            {"other": observations[1].observation_id, "participant": participant_id},
            "participant support is append-only",
        ),
        (
            "DELETE FROM knowledge.relationship_conversation_observations "
            "WHERE participant_id = :participant",
            {"participant": participant_id},
            "participant support cannot be deleted",
        ),
        (
            "UPDATE knowledge.relationship_evidence SET authority = 'model_inference' "
            "WHERE evidence_id = :evidence",
            {"evidence": evidence_id},
            "provenance is immutable",
        ),
        (
            "UPDATE knowledge.relationship_evidence SET effective_at = now() "
            "WHERE evidence_id = :evidence",
            {"evidence": evidence_id},
            "provenance is immutable",
        ),
        (
            "UPDATE knowledge.relationship_evidence SET recorded_at = recorded_at + "
            "interval '1 second' WHERE evidence_id = :evidence",
            {"evidence": evidence_id},
            "provenance is immutable",
        ),
        (
            "UPDATE knowledge.relationship_evidence SET person_id = :second "
            "WHERE evidence_id = :evidence",
            {"second": second, "evidence": evidence_id},
            "exact current resolution",
        ),
        (
            "DELETE FROM knowledge.relationship_evidence WHERE evidence_id = :evidence",
            {"evidence": evidence_id},
            "evidence is append-only",
        ),
        (
            "UPDATE knowledge.relationship_evidence_observations SET observation_id = :other "
            "WHERE evidence_id = :evidence",
            {"other": observations[1].observation_id, "evidence": evidence_id},
            "identity evidence is append-only",
        ),
        (
            "DELETE FROM knowledge.relationship_evidence_observations "
            "WHERE evidence_id = :evidence",
            {"evidence": evidence_id},
            "identity evidence is append-only",
        ),
    )
    for statement, parameters, message in plants:
        with pytest.raises(DBAPIError, match=message), relationship_engine.begin() as connection:
            connection.execute(text(statement), parameters)

    with relationship_engine.connect() as connection:
        assert snapshot(connection) == before


@pytest.mark.database
def test_database_refuses_an_unreviewed_observation_planted_in_a_resolution(
    relationship_engine: Engine,
) -> None:
    observations = tuple(_observation(index, "contacts") for index in range(61, 64))
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", observations)
        first = _link_person(repository, person_ordinal=61, observations=(observations[0],))
        second = _link_person(repository, person_ordinal=62, observations=(observations[1],))
        reviewed = DuplicateCandidateSet(
            candidate_set_id=_id("dups", 63),
            person_ids=(first, second),
            observation_ids=(observations[1].observation_id,),
            created_at=WHEN,
        )
        review_id = repository.open_identity_review(
            reviewed,
            ResolutionAction.MERGE_PERSON,
            retained_person_id=first,
            prior_person_id=second,
        )
        decision_id = repository.decide_identity_review(
            review_id, disposition="accept", principal_id=_id("prn", 1), decided_at=WHEN
        )

    with (
        pytest.raises(DBAPIError, match="exact reviewed observation set"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            insert(relationship_identity_resolutions).values(
                resolution_id=_id("ires", 63),
                action="merge_person",
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=first,
                prior_person_id=second,
                decided_at=WHEN,
            )
        )
        connection.execute(
            insert(relationship_resolution_observations).values(
                resolution_id=_id("ires", 63),
                observation_id=observations[2].observation_id,
            )
        )


@pytest.mark.database
def test_timeline_uses_only_explicit_conversation_support(relationship_engine: Engine) -> None:
    observations = (
        _observation(41, "contacts"),
        _observation(42, "email"),
        _observation(43, "contacts"),
    )
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", (observations[0],))
        repository.record_observations("email", (observations[1],))
        repository.record_observations("contacts", (observations[2],))
        person_id = _link_person(repository, person_ordinal=40, observations=observations[:2])
        ids = {
            "capture": _id("cap", 40),
            "version": _id("capver", 40),
            "conversation": _id("conv", 40),
            "principal": _id("prn", 1),
            "correlation": _id("corr", 40),
            "audit": _id("audit", 40),
        }
        connection.execute(
            text(
                "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
                "VALUES (:capture, :principal)"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_versions "
                "(version_id, capture_id, version_number, content, content_sha256, "
                "owner_principal_id, classification, processing_policy, idempotency_key, "
                "correlation_id, audit_id, server_received_at, accepted_at, recorded_at) "
                "VALUES (:version, :capture, 1, 'x', "
                "'2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881', "
                ":principal, 'synthetic_test', 'local_only', :version, :correlation, :audit, "
                "now(), now(), now())"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_conversations "
                "(conversation_id, capture_id, version_id, event_state, channel, recorded_at) "
                "VALUES (:conversation, :capture, :version, 'skeletal', 'unknown', now())"
            ),
            ids,
        )
        person_participant_id = repository.attach_conversation_participant(
            ids["conversation"],
            person_id=person_id,
            observation_ids=(observations[1].observation_id,),
        )
        unresolved = UnresolvedMention(
            unresolved_mention_id=_id("umen", 40),
            source_object_id=observations[0].source_object_id,
            source_version=observations[0].source_version,
            observed_at=WHEN,
        )
        repository.record_unresolved_mention(unresolved)
        participant_state_before_app_mismatch = (
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_conversation_observations))),
        )
        with pytest.raises(IdentityResolutionError, match="resolved participant"):
            repository.attach_conversation_participant(
                ids["conversation"],
                person_id=person_id,
                observation_ids=(observations[2].observation_id,),
            )
        with pytest.raises(IdentityResolutionError, match="unresolved source identity"):
            repository.attach_conversation_participant(
                ids["conversation"],
                unresolved_mention_id=unresolved.unresolved_mention_id,
                observation_ids=(observations[1].observation_id,),
            )
        assert (
            tuple(connection.execute(select(relationship_conversation_participants))),
            tuple(connection.execute(select(relationship_conversation_observations))),
        ) == participant_state_before_app_mismatch
        unresolved_participant_id = repository.attach_conversation_participant(
            ids["conversation"],
            unresolved_mention_id=unresolved.unresolved_mention_id,
            observation_ids=(observations[0].observation_id,),
        )
        support = {
            str(row.participant_id): str(row.observation_id)
            for row in connection.execute(select(relationship_conversation_observations))
        }
        assert support == {
            person_participant_id: observations[1].observation_id,
            unresolved_participant_id: observations[0].observation_id,
        }
        profile = repository.profile(person_id, expected_domains=("calendar", "contacts", "email"))
        assert profile is not None
        assert {item.observation_ids for item in profile.timeline} == {
            (observations[0].observation_id,),
            (observations[1].observation_id,),
        }
        assert {item.authority.value for item in profile.timeline} == {"source_observation"}
        assert profile.coverage[0].freshness.value == "unavailable"
        assert profile.coverage[0].as_of >= WHEN
        repository.record_source_affiliation(
            organization_id=_id("org", 40),
            organization_name="Synthetic Organization",
            affiliation_id=_id("aff", 40),
            person_id=person_id,
            observation_id=observations[0].observation_id,
            role="Synthetic Role",
            effective_from=WHEN,
            effective_to=None,
        )
        organization = repository.organization_profile(_id("org", 40))
        assert organization is not None
        assert organization.affiliations == ((person_id, "Synthetic Role", WHEN, None),)
        assert organization.observation_ids == (observations[0].observation_id,)
        with pytest.raises(IdentityResolutionError, match="cannot be rebound"):
            repository.record_source_affiliation(
                organization_id=_id("org", 40),
                organization_name="Different Synthetic Organization",
                affiliation_id=_id("aff", 41),
                person_id=person_id,
                observation_id=observations[0].observation_id,
                role=None,
                effective_from=None,
                effective_to=None,
            )
        affiliation_before_plants = tuple(
            connection.execute(
                select(relationship_affiliations).order_by(
                    relationship_affiliations.c.affiliation_id
                )
            )
        )
        participant_columns = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' "
                    "AND table_name = 'relationship_conversation_participants'"
                )
            )
        }
        assert participant_columns == {
            "participant_id",
            "conversation_id",
            "person_id",
            "unresolved_mention_id",
        }
        with pytest.raises(IdentityResolutionError, match="support is bounded"):
            repository.attach_conversation_participant(
                ids["conversation"],
                person_id=person_id,
                observation_ids=tuple(_id("iobs", index) for index in range(200, 401)),
            )

    affiliation_plants = (
        (
            "UPDATE knowledge.relationship_affiliations SET role = 'Invented Role' "
            "WHERE affiliation_id = :id",
            {"id": _id("aff", 40)},
            "affiliation provenance is immutable",
        ),
        (
            "UPDATE knowledge.relationship_affiliations SET person_id = :person "
            "WHERE affiliation_id = :id",
            {"id": _id("aff", 40), "person": _id("per", 999)},
            "exact current ownership",
        ),
        (
            "DELETE FROM knowledge.relationship_affiliations WHERE affiliation_id = :id",
            {"id": _id("aff", 40)},
            "source-bound affiliations cannot be deleted",
        ),
    )
    for statement, parameters, message in affiliation_plants:
        with pytest.raises(DBAPIError, match=message), relationship_engine.begin() as connection:
            connection.execute(text(statement), parameters)
    with relationship_engine.connect() as connection:
        assert (
            tuple(
                connection.execute(
                    select(relationship_affiliations).order_by(
                        relationship_affiliations.c.affiliation_id
                    )
                )
            )
            == affiliation_before_plants
        )

    with relationship_engine.connect() as connection:
        organization_count = connection.execute(
            text("SELECT count(*) FROM knowledge.relationship_organizations")
        ).scalar_one()
    with (
        pytest.raises(DBAPIError, match="organization identity is append-only"),
        relationship_engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE knowledge.relationship_organizations SET display_name = :name "
                "WHERE organization_id = :id"
            ),
            {"id": _id("org", 40), "name": "Conflicting Raw Organization"},
        )
    with relationship_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM knowledge.relationship_organizations")
            ).scalar_one()
            == organization_count
        )
        assert (
            connection.execute(
                text(
                    "SELECT display_name FROM knowledge.relationship_organizations "
                    "WHERE organization_id = :id"
                ),
                {"id": _id("org", 40)},
            ).scalar_one()
            == "Synthetic Organization"
        )

    with relationship_engine.connect() as connection:
        participant_state_before_raw_mismatch = (
            tuple(
                connection.execute(
                    select(relationship_conversation_participants).order_by(
                        relationship_conversation_participants.c.participant_id
                    )
                )
            ),
            tuple(
                connection.execute(
                    select(relationship_conversation_observations).order_by(
                        relationship_conversation_observations.c.participant_id,
                        relationship_conversation_observations.c.observation_id,
                    )
                )
            ),
        )
    for participant_id, observation_id, message in (
        (person_participant_id, observations[2].observation_id, "resolved participant"),
        (
            unresolved_participant_id,
            observations[1].observation_id,
            "unresolved source identity",
        ),
    ):
        with (
            pytest.raises(DBAPIError, match=message),
            relationship_engine.begin() as connection,
        ):
            connection.execute(
                insert(relationship_conversation_observations).values(
                    participant_id=participant_id,
                    observation_id=observation_id,
                )
            )
    with relationship_engine.connect() as connection:
        participant_state_after_raw_mismatch = (
            tuple(
                connection.execute(
                    select(relationship_conversation_participants).order_by(
                        relationship_conversation_participants.c.participant_id
                    )
                )
            ),
            tuple(
                connection.execute(
                    select(relationship_conversation_observations).order_by(
                        relationship_conversation_observations.c.participant_id,
                        relationship_conversation_observations.c.observation_id,
                    )
                )
            ),
        )
    assert participant_state_after_raw_mismatch == participant_state_before_raw_mismatch

    for ordinal, duplicate_values in enumerate(
        (
            {"person_id": person_id, "unresolved_mention_id": None},
            {"person_id": None, "unresolved_mention_id": unresolved.unresolved_mention_id},
        ),
        start=90,
    ):
        with pytest.raises(DBAPIError), relationship_engine.begin() as connection:
            connection.execute(
                insert(relationship_conversation_participants).values(
                    participant_id=_id("cpart", ordinal),
                    conversation_id=ids["conversation"],
                    **duplicate_values,
                )
            )
    with relationship_engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(relationship_conversation_participants)
            ).scalar_one()
            == 2
        )


@pytest.mark.database
def test_single_observation_can_become_a_person_only_through_review(
    relationship_engine: Engine,
) -> None:
    observation = _observation(51, "contacts")
    with relationship_engine.begin() as connection:
        repository = SqlRelationshipRepository(connection)
        repository.record_observations("contacts", (observation,))
        candidates = IdentityCandidateSet(
            candidate_set_id=_id("dups", 51),
            person_ids=(),
            observation_ids=(observation.observation_id,),
            created_at=WHEN,
        )
        review_id = repository.open_identity_review(candidates, ResolutionAction.LINK_OBSERVATION)
        decision_id = repository.decide_identity_review(
            review_id, disposition="accept", principal_id=_id("prn", 1), decided_at=WHEN
        )
        repository.apply_resolution(
            IdentityResolution(
                resolution_id=_id("ires", 51),
                action=ResolutionAction.LINK_OBSERVATION,
                review_case_id=review_id,
                decision_id=decision_id,
                retained_person_id=_id("per", 51),
                prior_person_id=None,
                observation_ids=(observation.observation_id,),
                decided_at=WHEN,
            ),
            display_name="Synthetic Single Observation",
        )
    with relationship_engine.connect() as connection:
        assert connection.execute(
            select(relationship_observation_links.c.person_id).where(
                relationship_observation_links.c.observation_id == observation.observation_id
            )
        ).scalar_one() == _id("per", 51)


@pytest.mark.database
def test_relationship_revision_round_trips(relationship_engine: Engine) -> None:
    command.downgrade(_config(), "3c8f1e2a5b74")
    with relationship_engine.connect() as connection:
        assert not connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'knowledge' AND table_name LIKE 'relationship_%'"
            )
        ).all()
    command.upgrade(_config(), "head")
