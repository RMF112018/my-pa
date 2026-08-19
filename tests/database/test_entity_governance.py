"""The governance plane against a real PostgreSQL server.

The unit suite proves the service refuses. This proves the *server* refuses,
which is the half that survives a caller who does not go through the service —
a migration, a backfill, a future writer, a hand-run statement.

The constraint that carries the most weight here is
`a_proposal_is_decided_exactly_when_something_decided_it`: it is what makes
"nothing has decided this" a shape a reader can trust rather than a convention a
writer has to remember. A proposal marked accepted with no actor is exactly the
row an autonomous merge would leave behind, and the database refuses to hold it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityMergeRecord,
    EntityObservation,
    EntityProposalKind,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entity_governance_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)


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
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


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


def _observation(
    observation_id: str = "eobs_aaaa0001aaaa0001",
    entity_id: str | None = None,
    principal_id: str = PRINCIPAL_A,
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.test>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
    )


@pytest.fixture
def two_principals(migrated_engine: Engine) -> Engine:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(ALICE))
        repository.create(PRINCIPAL_A, _entity(ALICE_TWO, name="Alice Chen"))
        repository.create(PRINCIPAL_B, _entity("ent_cccc0003cccc0003", PRINCIPAL_B, "Bob Chen"))
    return migrated_engine


# --- observations -----------------------------------------------------------


def test_an_observation_round_trips(two_principals: Engine) -> None:
    observation = _observation()
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, observation)
    with two_principals.connect() as connection:
        stored = SqlEntityRepository(connection).observations(PRINCIPAL_A)
    assert stored == [observation]


def test_an_unlinked_observation_is_on_the_unresolved_queue(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, _observation())
    with two_principals.connect() as connection:
        pending = SqlEntityRepository(connection).observations(PRINCIPAL_A, unresolved_only=True)
    assert [item.observation_id for item in pending] == ["eobs_aaaa0001aaaa0001"]


def test_linking_an_observation_moves_it_off_the_queue(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation())
        repository.link_observation(PRINCIPAL_A, "eobs_aaaa0001aaaa0001", ALICE)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.observations(PRINCIPAL_A, unresolved_only=True) == []
        assert repository.observations(PRINCIPAL_A, ALICE)[0].entity_id == ALICE


def test_observations_cannot_reach_another_principals_partition(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_B, _observation("eobs_bbbb0002bbbb0002", principal_id=PRINCIPAL_B)
        )
    with two_principals.connect() as connection:
        assert SqlEntityRepository(connection).observations(PRINCIPAL_A) == []


def test_the_server_refuses_an_observation_recorded_before_it_was_observed(
    two_principals: Engine,
) -> None:
    with (
        pytest.raises(
            IntegrityError, match="an_observation_is_not_recorded_before_it_was_observed"
        ),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_observations "  # noqa: S608
                "(observation_id, principal_id, kind, observed_value, normalized_value, "
                "source_id, source_object_id, source_version_id, observed_at, recorded_at) "
                "VALUES (:oid, :pid, 'contact_record', 'x', 'x', :src, :obj, :ver, "
                "'2026-08-18T12:00:00Z', '2026-08-17T12:00:00Z')"
            ),
            {
                "oid": "eobs_cccc0003cccc0003",
                "pid": PRINCIPAL_A,
                "src": SOURCE,
                "obj": OBJECT,
                "ver": VERSION,
            },
        )


# --- proposals --------------------------------------------------------------


def _propose(engine: Engine, kind: EntityProposalKind = EntityProposalKind.MERGE_ENTITIES) -> None:
    with engine.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_A,
            proposal_id="eprp_aaaa0001aaaa0001",
            kind=kind,
            payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
            observation_ids=(),
            proposed_by="resolver",
            proposed_at=WHEN,
        )


def test_a_proposal_round_trips_with_its_payload(two_principals: Engine) -> None:
    _propose(two_principals)
    with two_principals.connect() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa0001")
    assert held is not None
    assert held.kind is EntityProposalKind.MERGE_ENTITIES
    assert held.state is EntityProposalState.PROPOSED
    assert dict(held.payload) == {
        "retained_entity_id": ALICE,
        "merged_entity_id": ALICE_TWO,
    }
    assert held.decided_by is None


def test_the_server_refuses_a_decided_proposal_with_no_actor(two_principals: Engine) -> None:
    """The row an autonomous merge would leave behind, refused by the database.

    This is the constraint that makes the service's gate more than a policy in
    one module: a writer that skipped the service entirely still cannot mark a
    proposal accepted without saying who accepted it.
    """
    _propose(two_principals)
    with (
        pytest.raises(
            IntegrityError, match="a_proposal_is_decided_exactly_when_something_decided_it"
        ),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals SET state = 'accepted' "  # noqa: S608
                "WHERE proposal_id = 'eprp_aaaa0001aaaa0001'"
            )
        )


def test_the_server_refuses_an_actor_on_an_open_proposal(two_principals: Engine) -> None:
    """The other direction: an open proposal that names a decider is also refused."""
    _propose(two_principals)
    with (
        pytest.raises(
            IntegrityError, match="a_proposal_is_decided_exactly_when_something_decided_it"
        ),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET decided_by = 'someone', decided_at = now() "
                "WHERE proposal_id = 'eprp_aaaa0001aaaa0001'"
            )
        )


def test_the_server_refuses_a_decision_without_a_moment(two_principals: Engine) -> None:
    _propose(two_principals)
    with (
        pytest.raises(IntegrityError, match="a_proposal_decision_has_both_an_actor_and_a_moment"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET state = 'accepted', decided_by = 'someone' "
                "WHERE proposal_id = 'eprp_aaaa0001aaaa0001'"
            )
        )


def test_the_server_refuses_a_decision_before_the_proposal(two_principals: Engine) -> None:
    _propose(two_principals)
    with (
        pytest.raises(IntegrityError, match="a_proposal_is_not_decided_before_it_was_proposed"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET state = 'accepted', decided_by = 'someone', "
                "decided_at = '2020-01-01T00:00:00Z' "
                "WHERE proposal_id = 'eprp_aaaa0001aaaa0001'"
            )
        )


# --- merge, end to end ------------------------------------------------------


def test_an_operator_accepted_merge_redirects_and_leaves_lineage(
    two_principals: Engine,
) -> None:
    _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            "eprp_aaaa0001aaaa0001",
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed by employee number",
            has_operator_authority=True,
            merge_id="emrg_aaaa0001aaaa0001",
        )
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        merged = repository.get(PRINCIPAL_A, ALICE_TWO)
        lineage = repository.merges(PRINCIPAL_A, ALICE_TWO)
        decided = repository.proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa0001")
    assert merged is not None
    assert merged.status is EntityStatus.MERGED_REDIRECT
    assert merged.superseded_by_entity_id == ALICE
    assert [record.retained_entity_id for record in lineage] == [ALICE]
    assert decided is not None
    assert decided.state is EntityProposalState.ACCEPTED
    assert decided.decided_by == "the operator"


def test_an_entity_can_be_merged_away_only_once(two_principals: Engine) -> None:
    """A redirect with two targets resolves to neither, so the schema refuses it."""
    _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            "eprp_aaaa0001aaaa0001",
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed",
            has_operator_authority=True,
            merge_id="emrg_aaaa0001aaaa0001",
        )
    with (
        pytest.raises(IntegrityError),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_merge_records "  # noqa: S608
                "(merge_id, principal_id, retained_entity_id, merged_entity_id, "
                "proposal_id, decided_by, reason, decided_at) VALUES "
                "(:mid, :pid, :retained, :merged, :prop, 'someone', 'again', now())"
            ),
            {
                "mid": "emrg_bbbb0002bbbb0002",
                "pid": PRINCIPAL_A,
                "retained": "ent_cccc0003cccc0003",
                "merged": ALICE_TWO,
                "prop": "eprp_aaaa0001aaaa0001",
            },
        )


def test_the_server_refuses_a_merge_of_an_entity_into_itself(two_principals: Engine) -> None:
    _propose(two_principals)
    with (
        pytest.raises(IntegrityError, match="a_merge_joins_two_distinct_entities"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_merge_records "  # noqa: S608
                "(merge_id, principal_id, retained_entity_id, merged_entity_id, "
                "proposal_id, decided_by, reason, decided_at) VALUES "
                "(:mid, :pid, :same, :same, :prop, 'someone', 'why', now())"
            ),
            {
                "mid": "emrg_cccc0003cccc0003",
                "pid": PRINCIPAL_A,
                "same": ALICE,
                "prop": "eprp_aaaa0001aaaa0001",
            },
        )


def test_a_merge_record_requires_the_proposal_it_names(two_principals: Engine) -> None:
    """A merge with no proposal behind it is a merge nobody asked for."""
    with (
        pytest.raises(IntegrityError),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_merge_records "  # noqa: S608
                "(merge_id, principal_id, retained_entity_id, merged_entity_id, "
                "proposal_id, decided_by, reason, decided_at) VALUES "
                "(:mid, :pid, :retained, :merged, :prop, 'someone', 'why', now())"
            ),
            {
                "mid": "emrg_dddd0004dddd0004",
                "pid": PRINCIPAL_A,
                "retained": ALICE,
                "merged": ALICE_TWO,
                "prop": "eprp_absent0001absent",
            },
        )


def test_a_merged_entity_still_resolves_historically(two_principals: Engine) -> None:
    """Section 15.3: preserved as lineage, not erased.

    Proved through the resolver rather than by reading the row, because what
    matters is that a reference to the old identity still finds *something* and
    is told it is not current.
    """
    from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
    from my_pa.domain.relationship.entity import AliasType, EntityAlias
    from my_pa.domain.relationship.resolution import ResolutionOutcome

    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_alias(
            PRINCIPAL_A,
            EntityAlias(
                alias_id="eals_aaaa0001aaaa0001",
                entity_id=ALICE_TWO,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Ali Two"),
                display_value="Ali Two",
                principal_id=PRINCIPAL_A,
            ),
        )
    _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            "eprp_aaaa0001aaaa0001",
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed",
            has_operator_authority=True,
            merge_id="emrg_aaaa0001aaaa0001",
        )
    with two_principals.connect() as connection:
        answer = EntityResolutionService(SqlEntityRepository(connection)).resolve(
            PRINCIPAL_A, ResolutionRequest(raw_reference="Ali Two")
        )
    assert answer.outcome is ResolutionOutcome.HISTORICAL_MATCH
    assert answer.resolved_entity_id is None
    assert answer.candidates[0].superseded_by_entity_id == ALICE


# --- a decision is a one-time act -------------------------------------------


def test_the_repository_refuses_to_decide_a_proposal_a_second_time(
    two_principals: Engine,
) -> None:
    """Defence in depth, asserted at the layer that holds it.

    `EntityGovernanceService` already refuses with `ProposalNotOpenError`, and
    that check reads the proposal and then writes — two statements, so two
    callers can both read "open" and both write. The repository's `UPDATE` now
    carries `state = 'proposed'` in its own predicate, which is where that race
    is actually settled. Driven through `SqlEntityRepository` directly, because
    going through the service would prove only the service's check.

    What the second write would otherwise do is replace `decided_by`,
    `decided_at` and the reason: the record of who decided and why becomes
    whoever called last, and a rejected merge can be re-accepted with nothing
    left to show it was ever refused.
    """
    _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).reject(
            PRINCIPAL_A,
            "eprp_aaaa0001aaaa0001",
            decided_by="the operator",
            decided_at=WHEN,
            reason="different people",
        )
    with two_principals.connect() as connection:
        decided = SqlEntityRepository(connection).proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa0001")
    assert decided is not None

    with (
        pytest.raises(UnknownScopeError, match="open proposal"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).decide_proposal(
            PRINCIPAL_A,
            replace(
                decided,
                state=EntityProposalState.ACCEPTED,
                decided_by="someone else",
                decision_reason="on reflection",
            ),
        )

    with two_principals.connect() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa0001")
    assert held is not None
    assert held.state is EntityProposalState.REJECTED
    assert held.decided_by == "the operator"
    assert held.decision_reason == "different people"


def test_a_merge_record_cannot_cite_another_principals_proposal(
    two_principals: Engine,
) -> None:
    """`proposal_id` reads as the authority for the merge, so it is partitioned.

    The foreign key alone only proves the proposal exists *somewhere*. A record
    citing Principal B's proposal would present B's decision as A's own — a
    lineage row that looks like authority and is not. Nothing above catches it:
    the entities are A's, the record is A's, and only the citation crosses.
    """
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_B,
            proposal_id="eprp_bbbb0002bbbb0002",
            kind=EntityProposalKind.MERGE_ENTITIES,
            payload={"retained_entity_id": "ent_cccc0003cccc0003"},
            observation_ids=(),
            proposed_by="resolver",
            proposed_at=WHEN,
        )
    with (
        pytest.raises(UnknownScopeError, match="cites a proposal"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).record_merge(
            PRINCIPAL_A,
            EntityMergeRecord(
                merge_id="emrg_aaaa0001aaaa0001",
                principal_id=PRINCIPAL_A,
                retained_entity_id=ALICE,
                merged_entity_id=ALICE_TWO,
                proposal_id="eprp_bbbb0002bbbb0002",
                decided_by="the operator",
                reason="borrowed authority",
                decided_at=WHEN,
            ),
        )
    with two_principals.connect() as connection:
        assert SqlEntityRepository(connection).merges(PRINCIPAL_A) == []


def test_an_observation_read_honours_its_limit_at_the_server(two_principals: Engine) -> None:
    """The `LIMIT` is on the statement, not a slice of a full result set.

    `EntityContextService` caps how many observations it reads to compute
    coverage, and the whole point of the cap is that the surplus rows never
    leave the server. Asserted here because an in-memory double returns the same
    card either way, so nothing in the FAST tier can tell a `LIMIT` from a
    slice.
    """
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        for index in range(5):
            repository.record_observation(
                PRINCIPAL_A, _observation(f"eobs_{index:05d}aaaa0001aaa", ALICE)
            )
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert len(repository.observations(PRINCIPAL_A, ALICE)) == 5
        assert len(repository.observations(PRINCIPAL_A, ALICE, limit=2)) == 2
        assert len(repository.observations(PRINCIPAL_A, limit=3)) == 3
        with pytest.raises(ValueError, match="at least one row"):
            repository.observations(PRINCIPAL_A, ALICE, limit=0)


def test_an_observation_limit_reaches_the_server_as_a_limit_clause(
    two_principals: Engine,
) -> None:
    """Counting the rows back cannot tell a `LIMIT` from a slice. This can.

    The test above asserts only that two rows come back, which is equally true
    of an implementation that fetches every observation and truncates in Python
    -- so replacing `statement.limit(limit)` with `rows[:limit]` left it green,
    and the guard on the one property it exists to protect was inert. Observations
    are the collection that grows with every source record that ever mentioned
    anyone, so "the surplus never leaves the server" is the whole claim.

    The SQL actually issued is captured instead, which is the only place that
    distinction is visible.
    """
    issued: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        issued.append(statement)

    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        for index in range(5):
            repository.record_observation(
                PRINCIPAL_A, _observation(f"eobs_{index:05d}bbbb0002bbb", ALICE)
            )
    event.listen(two_principals, "before_cursor_execute", _capture)
    try:
        with two_principals.connect() as connection:
            SqlEntityRepository(connection).observations(PRINCIPAL_A, ALICE, limit=2)
    finally:
        event.remove(two_principals, "before_cursor_execute", _capture)

    selects = [statement for statement in issued if "entity_observations" in statement]
    assert selects, "the read issued no statement against entity_observations"
    assert all("LIMIT" in statement.upper() for statement in selects), selects
