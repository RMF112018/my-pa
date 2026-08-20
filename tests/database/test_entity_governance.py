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

import dataclasses
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
    MENTION_DISPLAY_NAME_LIMIT,
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


def test_the_server_refuses_an_observation_whose_matched_form_is_not_normalized(
    two_principals: Engine,
) -> None:
    """The write half of the one guard on the field the queue discloses.

    `entities.unresolved_mentions` publishes `normalized_value` and withholds
    `observed_value`. `EntityObservation` itself checks only that the value is
    non-blank — unlike `Entity`, `EntityAlias` and `ExternalIdentifier`, whose
    own `__post_init__` refuse an unnormalized value — so before this guard the
    repository accepted a raw mail envelope into the column it later serves.

    **The guard is necessary and it is not sufficient, and that distinction is
    the whole point of this test's neighbour below.** It establishes that the
    value is normalized, not that it is a *name*: normalized raw text passes it.
    What keeps an envelope out is the contract on
    `EntityRepository.record_observation`, which no predicate over the stored
    string can check.
    """
    envelope = dataclasses.replace(
        _observation(), normalized_value="A. Chen <a.chen@northwind.test>"
    )
    with (
        pytest.raises(ValueError, match="form resolution compares in"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, envelope)


def test_a_row_written_around_the_repository_is_refused_on_the_way_out(
    two_principals: Engine,
) -> None:
    """The read half, and the reason the module docstring can say "every read mapper".

    The matched form has no CHECK constraint — the module explains at length why
    `normalize_name` does not survive translation to SQL — so a hand-run INSERT
    can still store an unnormalized value. That residual is documented. What is
    *not* acceptable is serving such a row to
    `entities.unresolved_mentions`, which is the one capability that discloses
    this column: the row would go out with its angle brackets and its `@`
    intact, past a boundary whose stated job is to withhold the raw text.

    So the mapper refuses it. Staged with SQL deliberately, because the
    repository is what refuses to *write* such a row and the row this guards
    against is the one that arrived some other way.
    """
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, _observation())
    with two_principals.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_observations "  # noqa: S608
                "SET normalized_value = :raw WHERE observation_id = :identifier"
            ),
            {"raw": "A. Chen <a.chen@northwind.test>", "identifier": "eobs_aaaa0001aaaa0001"},
        )
    with (
        pytest.raises(ValueError, match="form resolution compares in"),
        two_principals.connect() as connection,
    ):
        SqlEntityRepository(connection).observations(PRINCIPAL_A, unresolved_only=True)


def test_the_disclosed_mention_name_round_trips_and_defaults_to_nothing(
    two_principals: Engine,
) -> None:
    """The column the queue reads, against a real server.

    Two properties, and the second is the one the change was made for: a value
    a writer supplies comes back exactly, and a writer that supplies nothing
    stores `NULL` rather than anything derived from the matched form.
    """
    named = dataclasses.replace(
        _observation("eobs_named0001named01"), mention_display_name="A. Chen"
    )
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, named)
        repository.record_observation(PRINCIPAL_A, _observation("eobs_plain0001plain01"))
    with two_principals.connect() as connection:
        stored = {
            item.observation_id: item.mention_display_name
            for item in SqlEntityRepository(connection).observations(PRINCIPAL_A)
        }
    assert stored["eobs_named0001named01"] == "A. Chen"
    assert stored["eobs_plain0001plain01"] is None


def test_the_server_refuses_a_disclosed_mention_name_past_its_bound(
    two_principals: Engine,
) -> None:
    """The CHECK, not the record's own guard.

    `EntityObservation.__post_init__` bounds this too, so the assertion has to
    reach the server around it — `object.__setattr__` writes the value the
    record would have refused, which is the row a bulk import produces. A column
    with no ceiling is a column an ingester can put a document in, and this is
    the one column the queue publishes.
    """
    oversized = _observation("eobs_longer001longer1")
    object.__setattr__(oversized, "mention_display_name", "x" * 400)
    with pytest.raises(IntegrityError), two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, oversized)


#: Values the record and the CHECK must classify identically. Both lists matter:
#: an earlier version of this test carried only refusals, and every one of them
#: happened to be a value both sides already refused, so it was structurally
#: incapable of seeing the half of the divergence that survived.
AGREED_REFUSALS: Final = (
    ("\t", "tab-only"),
    ("   ", "spaces-only"),
    (" A. Chen", "leading-space"),
    ("A. Chen ", "trailing-space"),
    ("\tA. Chen", "leading-tab"),
    ("A. Chen\t", "trailing-tab"),
    ("\nA. Chen", "leading-newline"),
    ("A. Chen\r", "trailing-return"),
    ("\x0bA. Chen", "leading-vertical-tab"),
    ("\x0cA. Chen", "leading-form-feed"),
    ("\t" * 10 + "x" * 195, "tab-padded-long"),
    ("x" * (MENTION_DISPLAY_NAME_LIMIT + 1), "too-long"),
)

AGREED_ACCEPTANCES: Final = (
    ("A. Chen", "plain"),
    ("A.\tChen", "interior-tab"),
    ("\xa0A. Chen", "leading-no-break-space"),
    ("\u3000A. Chen", "leading-ideographic-space"),
    ("\u2003A. Chen", "leading-em-space"),
    ("x" * MENTION_DISPLAY_NAME_LIMIT, "exactly-at-the-bound"),
)


@pytest.mark.parametrize(("value", "case"), AGREED_REFUSALS, ids=[c for _, c in AGREED_REFUSALS])
def test_the_server_and_the_record_refuse_the_same_mention_names(
    two_principals: Engine, value: str, case: str
) -> None:
    """Both enforcement points must refuse the same values.

    They did not, twice. The first version compared Python's `str.strip()`
    against SQL's `trim()`, which disagree in both directions. The second moved
    the CHECK to `[[:space:]]`, which closed the two values a reviewer had named
    and left the class open — `"\tA. Chen"` was still refused by the record and
    accepted by the server, so that row could be written around the repository
    and then make the whole queue page raise on read.

    The leading-tab case is here because it is the one that survived, and it
    fails against either earlier version.
    """
    smuggled = _observation("eobs_agree0001agree01")
    object.__setattr__(smuggled, "mention_display_name", value)
    with pytest.raises(IntegrityError), two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, smuggled)
    with pytest.raises(ValueError):
        dataclasses.replace(_observation(), mention_display_name=value)


@pytest.mark.parametrize(
    ("value", "case"), AGREED_ACCEPTANCES, ids=[c for _, c in AGREED_ACCEPTANCES]
)
def test_the_server_and_the_record_accept_the_same_mention_names(
    two_principals: Engine, value: str, case: str
) -> None:
    """And they must **accept** the same values, which nothing checked.

    This is the direction that hid the surviving defect: a test written only
    over refusals passes on a rule that is far too strict at one end, and the
    consequence of the record being stricter than the CHECK is not a refused
    write — it is a row the server stored happily that the mapper then cannot
    rebuild, which takes the whole `entities.unresolved_mentions` page down.

    The Unicode-space cases are here deliberately. `[[:space:]]` is decided by
    the server's collation and was measured matching U+2003 and U+3000 but not
    U+00A0, so a rule written against it agrees with Python on one server and
    not another. The explicit set both sides now name has no such freedom, and
    these three prove the two engines agree that those characters are *not*
    edge whitespace.
    """
    named = dataclasses.replace(_observation("eobs_accept001accept1"), mention_display_name=value)
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(PRINCIPAL_A, named)
    with two_principals.connect() as connection:
        stored = SqlEntityRepository(connection).observations(PRINCIPAL_A)
    assert [item.mention_display_name for item in stored] == [value]


def test_the_stated_bound_is_the_one_the_server_enforces(two_principals: Engine) -> None:
    """`MENTION_DISPLAY_NAME_LIMIT` and the CHECK's literal are coupled by hand.

    Nothing tied them: lowering the constant would make the record refuse a
    value the server accepts, with the agreement tests above still green,
    because a value long enough to reach the record's length branch is caught by
    the trim rule first. Read back from the server rather than from the
    declaration, so a migration that wrote a different number than `tables.py`
    declares is caught too.
    """
    with two_principals.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'a_disclosed_mention_name_is_bounded'"
            )
        ).scalar_one()
    # PostgreSQL rewrites `BETWEEN` into two comparisons, so the assertion is
    # against what the server stores rather than against what was written.
    assert f"length(mention_display_name) <= {MENTION_DISPLAY_NAME_LIMIT}" in definition
    assert "length(mention_display_name) >= 1" in definition


def test_an_observation_cursor_the_caller_cannot_read_is_refused(
    two_principals: Engine,
) -> None:
    """The third of the plane's three paged reads, and the last to get this rule.

    `search` refused an unreadable cursor from the day it was paged; the other
    two applied a bare `>` to whatever they were handed. On this read that is
    the worst of the three: a foreign cursor sorting above the caller's own
    mentions answers with an empty page and no truncation, which an operator
    reads as "nothing left to resolve" — the exact opposite of what an
    unreadable cursor establishes.
    """
    foreign = "eobs_bbbb0002bbbb0002"
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation())
        repository.record_observation(PRINCIPAL_B, _observation(foreign, principal_id=PRINCIPAL_B))
    with (
        pytest.raises(UnknownScopeError, match="observation cursor"),
        two_principals.connect() as connection,
    ):
        SqlEntityRepository(connection).observations(
            PRINCIPAL_A, unresolved_only=True, after_observation_id=foreign
        )


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


# --- the governance plane's partition, where nothing had reached it ----------

#: The entity Principal B already holds, from the `two_principals` fixture.
BEE_ONE: Final = "ent_cccc0003cccc0003"
BEE_TWO: Final = "ent_dddd0004dddd0004"
B_PROPOSAL: Final = "eprp_bbbb0002bbbb0002"
B_MERGE: Final = "emrg_bbbb0002bbbb0002"
A_PROPOSAL: Final = "eprp_aaaa0001aaaa0001"
A_MERGE: Final = "emrg_aaaa0001aaaa0001"


def _propose_for_b(engine: Engine) -> None:
    """One open proposal in Principal B's partition, so every read below has a decoy."""
    with engine.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_B,
            proposal_id=B_PROPOSAL,
            kind=EntityProposalKind.MERGE_ENTITIES,
            payload={"retained_entity_id": BEE_ONE},
            observation_ids=(),
            proposed_by="resolver",
            proposed_at=WHEN,
        )


def _a_decided_merge_for_b(engine: Engine) -> None:
    """A whole accepted merge in B's partition: second entity, proposal, decision, lineage."""
    with engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_B, _entity(BEE_TWO, PRINCIPAL_B, "Bob Chen"))
        EntityGovernanceService(repository).propose(
            PRINCIPAL_B,
            proposal_id=B_PROPOSAL,
            kind=EntityProposalKind.MERGE_ENTITIES,
            payload={"retained_entity_id": BEE_ONE, "merged_entity_id": BEE_TWO},
            observation_ids=(),
            proposed_by="resolver",
            proposed_at=WHEN,
        )
    with engine.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_B,
            B_PROPOSAL,
            decided_by="B's operator",
            decided_at=LATER,
            reason="same person",
            has_operator_authority=True,
            merge_id=B_MERGE,
        )


def test_an_observation_write_decides_a_collision_on_its_own_partitions_rows(
    two_principals: Engine,
) -> None:
    """`record_observation`'s idempotency read is partitioned, so it judges A's rows only.

    `observation_id` is a *global* primary key, so an identifier B already holds
    is unavailable to A either way -- what the partition decides is which refusal
    A receives, and on what evidence. Without it the read finds B's observation,
    compares it against what A described, and tells A its own identifier is bound
    to different values, from a row in another partition. With it the read finds
    nothing and the server refuses the key collision that is really there.
    """
    identifier = "eobs_cccc0003cccc0003"
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_B, _observation(identifier, principal_id=PRINCIPAL_B)
        )
    with pytest.raises(IntegrityError), two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation(identifier, entity_id=ALICE)
        )
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        theirs = repository.observations(PRINCIPAL_B)
        assert [item.observation_id for item in theirs] == [identifier], (
            "the staged foreign row went missing"
        )
        assert theirs[0].entity_id is None
        assert repository.observations(PRINCIPAL_A) == []


def test_linking_an_observation_cannot_reach_another_principals_observation(
    two_principals: Engine,
) -> None:
    """The link is an UPDATE, and its partition is the only thing scoping it.

    `link_observation` checks that the *entity* is A's. Nothing above the
    statement checks the observation, because the statement is where that check
    lives: `observation_id` is a global primary key, so the identifier alone
    names B's row exactly. Without the partition predicate A's link succeeds and
    B's observation is silently re-pointed at an entity in A's partition --
    evidence B recorded, attached to someone B cannot see, with no error raised
    at either end.
    """
    identifier = "eobs_cccc0003cccc0003"
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_B, _observation(identifier, principal_id=PRINCIPAL_B)
        )
    with (
        pytest.raises(UnknownScopeError, match="outside this scope"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).link_observation(PRINCIPAL_A, identifier, ALICE)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        theirs = repository.observations(PRINCIPAL_B)
        assert [item.observation_id for item in theirs] == [identifier], (
            "the staged foreign row went missing"
        )
        assert theirs[0].entity_id is None, "B's observation was re-pointed across the partition"
        assert repository.observations(PRINCIPAL_B, unresolved_only=True) == theirs
        assert repository.observations(PRINCIPAL_A, ALICE) == []


def test_a_proposal_read_answers_a_foreign_proposal_as_an_absent_one(
    two_principals: Engine,
) -> None:
    """A single-proposal read is partitioned, so B's open decision is not A's to see.

    A proposal carries the payload of a mutation someone is asking for -- which
    two entities are the same person, by identifier. Served across the partition
    it discloses both the identifiers and the fact that a merge is pending on
    them.
    """
    _propose(two_principals)
    _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        foreign = repository.proposal(PRINCIPAL_A, B_PROPOSAL)
        absent = repository.proposal(PRINCIPAL_A, "eprp_ffff0006ffff0006")
        mine = repository.proposal(PRINCIPAL_A, A_PROPOSAL)
        theirs = repository.proposal(PRINCIPAL_B, B_PROPOSAL)
    assert foreign is None
    assert foreign == absent
    assert mine is not None
    assert mine.proposal_id == A_PROPOSAL
    assert theirs is not None, "the staged foreign row went missing"
    assert theirs.principal_id == PRINCIPAL_B


def test_the_proposal_queue_does_not_list_another_principals_proposals(
    two_principals: Engine,
) -> None:
    """The queue an operator works through holds only their own partition's proposals.

    Each Principal holds one open proposal here, so the assertion cannot go
    vacuous: it fails if the partition is dropped *and* it fails if the fixture
    ever stops staging either row.
    """
    _propose(two_principals)
    _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.proposals(PRINCIPAL_A)
        theirs = repository.proposals(PRINCIPAL_B)
        mine_open = repository.proposals(PRINCIPAL_A, EntityProposalState.PROPOSED)
    assert [item.proposal_id for item in mine] == [A_PROPOSAL]
    assert [item.proposal_id for item in theirs] == [B_PROPOSAL], (
        "the staged foreign row went missing"
    )
    assert [item.proposal_id for item in mine_open] == [A_PROPOSAL]


def test_a_decision_cannot_reach_another_principals_proposal(
    two_principals: Engine,
) -> None:
    """`decide_proposal` settles at the database, and its partition is part of that.

    The UPDATE already carries `state = 'proposed'` so a decision happens once.
    The partition is the other half: `proposal_id` is a global primary key, so
    without it A's decision matches B's open proposal exactly and accepts it --
    B's merge authorised by A's operator, recorded as B's own decision, with
    `decided_by` naming someone in a partition B cannot read.
    """
    _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        staged = SqlEntityRepository(connection).proposal(PRINCIPAL_B, B_PROPOSAL)
    assert staged is not None, "the staged foreign row went missing"

    with (
        pytest.raises(UnknownScopeError, match="open proposal"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).decide_proposal(
            PRINCIPAL_A,
            replace(
                staged,
                principal_id=PRINCIPAL_A,
                state=EntityProposalState.ACCEPTED,
                decided_by="A's operator",
                decided_at=LATER,
                decision_reason="not mine to make",
            ),
        )

    with two_principals.connect() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_B, B_PROPOSAL)
    assert held is not None
    assert held.state is EntityProposalState.PROPOSED
    assert held.decided_by is None
    assert held.decision_reason is None


def test_merge_lineage_does_not_list_another_principals_merges(
    two_principals: Engine,
) -> None:
    """Lineage is partitioned, both unfiltered and filtered by entity.

    A merge record names two entity identifiers, who decided, and why. Listed
    across the partition it hands A the identifiers of B's entities and the text
    of B's reasoning -- and `merges(entity_id=...)` would answer A with lineage
    for an entity A cannot otherwise see at all.

    Both Principals hold a real accepted merge here, so neither assertion can
    pass by finding nothing.
    """
    _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            A_PROPOSAL,
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed by employee number",
            has_operator_authority=True,
            merge_id=A_MERGE,
        )
    _a_decided_merge_for_b(two_principals)

    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.merges(PRINCIPAL_A)
        theirs = repository.merges(PRINCIPAL_B)
        mine_for_their_entity = repository.merges(PRINCIPAL_A, BEE_TWO)
        theirs_for_their_entity = repository.merges(PRINCIPAL_B, BEE_TWO)
    assert [record.merge_id for record in mine] == [A_MERGE]
    assert [record.merge_id for record in theirs] == [B_MERGE], (
        "the staged foreign row went missing"
    )
    assert mine_for_their_entity == []
    assert [record.merge_id for record in theirs_for_their_entity] == [B_MERGE]
