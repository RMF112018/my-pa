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
import re
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    MENTION_DISPLAY_NAME_LIMIT,
    EntityMergeRecord,
    EntityObservation,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import EntityProposalPayload
from my_pa.infrastructure.persistence import tables
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
        repository.create(
            PRINCIPAL_B,
            _entity("ent_dddd0004dddd0004", PRINCIPAL_B, "Robert Chen"),
        )
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


def _propose(engine: Engine, kind: EntityProposalKind = EntityProposalKind.MERGE_ENTITIES) -> str:
    """One open proposal in A's partition. Returns the identifier the server minted."""
    with engine.begin() as connection:
        return (
            EntityGovernanceService(SqlEntityRepository(connection))
            .propose(
                PRINCIPAL_A,
                kind=kind,
                payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
                observation_ids=(),
                proposed_by="resolver",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
            )
            .proposal_id
        )


def _merge(engine: Engine, proposal_id: str, *, merge_id: str = "emrg_aaaa0001aaaa0001") -> None:
    """Perform the identity merge an accepted proposal asks for.

    Two repository calls rather than a service call, and that is the point of
    the helper: since `WP-RI-B-05` no review disposition performs a merge, so a
    test that needs merged state stages it the way `entities.merge` will --
    redirect, then lineage. Everything below that reads merged state uses this,
    which is also why none of those tests silently became assertions about
    nothing when acceptance stopped merging.
    """
    with engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.redirect_entity(PRINCIPAL_A, ALICE_TWO, ALICE)
        repository.record_merge(
            PRINCIPAL_A,
            EntityMergeRecord(
                merge_id=merge_id,
                principal_id=PRINCIPAL_A,
                retained_entity_id=ALICE,
                merged_entity_id=ALICE_TWO,
                proposal_id=proposal_id,
                decided_by="the operator",
                reason="confirmed by employee number",
                decided_at=LATER,
            ),
        )


def test_a_proposal_round_trips_with_its_payload(two_principals: Engine) -> None:
    proposal_id = _propose(two_principals)
    with two_principals.connect() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
    assert held is not None
    assert held.kind is EntityProposalKind.MERGE_ENTITIES
    # `needs_review` and not `proposed`, since `WP-RI-B-05` made the initial
    # state derive from the kind's review requirement: a merge is
    # `REQUIRES_OPERATOR`, so a person has to look at it and the state says so
    # rather than leaving a reader to recompute it from the kind.
    assert held.state is EntityProposalState.NEEDS_REVIEW
    assert held.payload.as_mapping() == {
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
    proposal_id = _propose(two_principals)
    with (
        pytest.raises(
            IntegrityError, match="a_proposal_is_decided_exactly_when_something_decided_it"
        ),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals SET state = 'accepted' "  # noqa: S608
                "WHERE proposal_id = :pid"
            ),
            {"pid": proposal_id},
        )


def test_the_server_refuses_an_actor_on_an_open_proposal(two_principals: Engine) -> None:
    """The other direction: an open proposal that names a decider is also refused."""
    proposal_id = _propose(two_principals)
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
                "WHERE proposal_id = :pid"
            ),
            {"pid": proposal_id},
        )


def test_the_server_refuses_a_decision_without_a_moment(two_principals: Engine) -> None:
    proposal_id = _propose(two_principals)
    with (
        pytest.raises(IntegrityError, match="a_proposal_decision_has_both_an_actor_and_a_moment"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET state = 'accepted', decided_by = 'someone' "
                "WHERE proposal_id = :pid"
            ),
            {"pid": proposal_id},
        )


def test_the_server_refuses_a_decision_before_the_proposal(two_principals: Engine) -> None:
    proposal_id = _propose(two_principals)
    with (
        pytest.raises(IntegrityError, match="a_proposal_is_not_decided_before_it_was_proposed"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_proposals "  # noqa: S608
                "SET state = 'accepted', decided_by = 'someone', "
                "decided_at = '2020-01-01T00:00:00Z' "
                "WHERE proposal_id = :pid"
            ),
            {"pid": proposal_id},
        )


# --- accepting a merge proposal, end to end ---------------------------------


def test_an_operator_accepted_merge_leaves_both_identities_untouched(
    two_principals: Engine,
) -> None:
    """`WP-RI-B-05`, proved against the real schema rather than against a double.

    This test replaces one that asserted the opposite. Until `WP-RI-B-05`,
    accepting a `merge_entities` proposal redirected the merged-away entity and
    wrote the lineage row, and the test here checked that it had. Section 15 of
    the Phase B contract forbids exactly that: acceptance establishes reviewed
    identity-correction intent and performs no identity mutation, because a
    reviewer's grant is not an identity-correction grant.

    Both rows are read before and after, and the three columns a merge writes --
    `status`, `superseded_by_entity_id` and `version` -- are compared on each.
    Restoring the redirect turns two of the six comparisons red, and restoring
    the lineage write turns the fourth assertion red, so the correction cannot be
    half-undone without this test noticing.
    """
    proposal_id = _propose(two_principals)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        before = {
            entity_id: repository.get(PRINCIPAL_A, entity_id) for entity_id in (ALICE, ALICE_TWO)
        }
    for held in before.values():
        assert held is not None
        # Active and unredirected beforehand, so "unchanged" below is an
        # assertion about a value rather than about an absence.
        assert held.status is EntityStatus.ACTIVE
        assert held.superseded_by_entity_id is None

    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_A,
            proposal_id,
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed by employee number",
            has_operator_authority=True,
        )

    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        after = {
            entity_id: repository.get(PRINCIPAL_A, entity_id) for entity_id in (ALICE, ALICE_TWO)
        }
        lineage = repository.merges(PRINCIPAL_A)
        decided = repository.proposal(PRINCIPAL_A, proposal_id)
    for entity_id, was in before.items():
        now = after[entity_id]
        assert was is not None
        assert now is not None
        assert now.status is was.status
        assert now.superseded_by_entity_id is was.superseded_by_entity_id
        assert now.version == was.version
    assert lineage == [], "a review disposition wrote merge lineage"

    # And the acceptance itself is recorded, so the test is not passing because
    # nothing happened at all.
    assert decided is not None
    assert decided.state is EntityProposalState.ACCEPTED
    assert decided.decided_by == "the operator"
    assert decided.accepted_record_id is None


def test_an_entity_can_be_merged_away_only_once(two_principals: Engine) -> None:
    """A redirect with two targets resolves to neither, so the schema refuses it."""
    proposal_id = _propose(two_principals)
    _merge(two_principals, proposal_id)
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
                "prop": proposal_id,
            },
        )


def test_the_server_refuses_a_merge_of_an_entity_into_itself(two_principals: Engine) -> None:
    proposal_id = _propose(two_principals)
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
                "prop": proposal_id,
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
    _merge(two_principals, _propose(two_principals))
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
    callers can both read "open" and both write. The repository's `UPDATE`
    carries the undecided states in its own predicate, which is where that race
    is actually settled. (It carried the `proposed` literal until `WP-RI-B-05`
    began writing `needs_review`; both are undecided and the predicate names the
    set the record's own `is_open` reads, so the two cannot disagree.) Driven
    through `SqlEntityRepository` directly, because going through the service
    would prove only the service's check.

    What the second write would otherwise do is replace `decided_by`,
    `decided_at` and the reason: the record of who decided and why becomes
    whoever called last, and a rejected merge can be re-accepted with nothing
    left to show it was ever refused.
    """
    proposal_id = _propose(two_principals)
    with two_principals.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).reject(
            PRINCIPAL_A,
            proposal_id,
            decided_by="the operator",
            decided_at=WHEN,
            reason="different people",
        )
    with two_principals.connect() as connection:
        decided = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
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
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
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
        theirs = EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_B,
            kind=EntityProposalKind.MERGE_ENTITIES,
            payload={
                "retained_entity_id": "ent_cccc0003cccc0003",
                "merged_entity_id": "ent_dddd0004dddd0004",
            },
            observation_ids=(),
            proposed_by="resolver",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="1",
            at=WHEN,
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
                proposal_id=theirs.proposal_id,
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

#: The two entities Principal B already holds, from the `two_principals` fixture.
BEE_ONE: Final = "ent_cccc0003cccc0003"
BEE_TWO: Final = "ent_dddd0004dddd0004"
B_MERGE: Final = "emrg_bbbb0002bbbb0002"
A_MERGE: Final = "emrg_aaaa0001aaaa0001"


def _propose_for_b(engine: Engine) -> str:
    """One open proposal in Principal B's partition, so every read below has a decoy.

    Returns the minted identifier. Proposal identifiers are the server's to
    choose since `WP-RI-B-05`, so the decoy's identity is read back rather than
    named -- which also means these partition assertions compare two identifiers
    the server actually issued instead of two literals that could both be wrong.
    """
    with engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        return (
            EntityGovernanceService(repository)
            .propose(
                PRINCIPAL_B,
                kind=EntityProposalKind.MERGE_ENTITIES,
                payload={"retained_entity_id": BEE_ONE, "merged_entity_id": BEE_TWO},
                observation_ids=(),
                proposed_by="resolver",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="1",
                at=WHEN,
            )
            .proposal_id
        )


def _a_decided_merge_for_b(engine: Engine) -> str:
    """A whole merge in B's partition: second entity, proposal, decision, redirect, lineage.

    The decision and the merge are two acts now. Both are staged here because
    what the tests below need is B's *lineage* to exist, and since `WP-RI-B-05`
    accepting the proposal does not produce any.
    """
    proposal_id = _propose_for_b(engine)
    with engine.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).accept(
            PRINCIPAL_B,
            proposal_id,
            decided_by="B's operator",
            decided_at=LATER,
            reason="same person",
            has_operator_authority=True,
        )
    with engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.redirect_entity(PRINCIPAL_B, BEE_TWO, BEE_ONE)
        repository.record_merge(
            PRINCIPAL_B,
            EntityMergeRecord(
                merge_id=B_MERGE,
                principal_id=PRINCIPAL_B,
                retained_entity_id=BEE_ONE,
                merged_entity_id=BEE_TWO,
                proposal_id=proposal_id,
                decided_by="B's operator",
                reason="same person",
                decided_at=LATER,
            ),
        )
    return proposal_id


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
    a_proposal = _propose(two_principals)
    b_proposal = _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        foreign = repository.proposal(PRINCIPAL_A, b_proposal)
        absent = repository.proposal(PRINCIPAL_A, "eprp_ffff0006ffff0006")
        mine = repository.proposal(PRINCIPAL_A, a_proposal)
        theirs = repository.proposal(PRINCIPAL_B, b_proposal)
    assert foreign is None
    assert foreign == absent
    assert mine is not None
    assert mine.proposal_id == a_proposal
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
    a_proposal = _propose(two_principals)
    b_proposal = _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.proposals(PRINCIPAL_A)
        theirs = repository.proposals(PRINCIPAL_B)
        mine_open = repository.proposals(PRINCIPAL_A, EntityProposalState.NEEDS_REVIEW)
    assert [item.proposal_id for item in mine] == [a_proposal]
    assert [item.proposal_id for item in theirs] == [b_proposal], (
        "the staged foreign row went missing"
    )
    assert [item.proposal_id for item in mine_open] == [a_proposal]


def test_a_decision_cannot_reach_another_principals_proposal(
    two_principals: Engine,
) -> None:
    """`decide_proposal` settles at the database, and its partition is part of that.

    The UPDATE already carries the undecided states so a decision happens once.
    The partition is the other half: `proposal_id` is a global primary key, so
    without it A's decision matches B's open proposal exactly and accepts it --
    B's merge authorised by A's operator, recorded as B's own decision, with
    `decided_by` naming someone in a partition B cannot read.

    The direct-repository attack supplies A-owned participant references while
    retaining B's proposal identifier. That deliberately satisfies the earlier
    participant-scope guard so this test reaches the proposal partition
    predicate it exists to prove; B's stored proposal remains unchanged.
    """
    b_proposal = _propose_for_b(two_principals)
    with two_principals.connect() as connection:
        staged = SqlEntityRepository(connection).proposal(PRINCIPAL_B, b_proposal)
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
                payload=EntityProposalPayload.of(
                    EntityProposalKind.MERGE_ENTITIES,
                    {"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
                ),
                state=EntityProposalState.ACCEPTED,
                decided_by="A's operator",
                decided_at=LATER,
                decision_reason="not mine to make",
            ),
        )

    with two_principals.connect() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_B, b_proposal)
    assert held is not None
    assert held.state is EntityProposalState.NEEDS_REVIEW
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

    Both Principals hold a real merge here -- staged as the operator act that
    performs one, since accepting the proposal no longer does -- so neither
    assertion can pass by finding nothing.
    """
    _merge(two_principals, _propose(two_principals), merge_id=A_MERGE)
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


def test_the_declared_check_is_the_one_the_server_holds(two_principals: Engine) -> None:
    """`tables.py`'s declaration is never emitted, so nothing verified it.

    `METADATA` is not used to create this schema -- the Alembic chain is -- and
    `tests/schema/test_entity_schema_migration.py` compares constraint *names*
    only. The ninth review measured what that leaves: replacing the whole
    declared expression with `1 = 0 AND length(mention_display_name) BETWEEN 1
    AND 999999` left 103 tests green across the schema and governance suites.
    The declaration is what a reader of `tables.py` believes the column is
    bounded by, and it could say anything.

    Compared as normalized text rather than byte-for-byte: PostgreSQL rewrites
    `BETWEEN` into two comparisons, parenthesizes to its own taste, and requotes
    the regex literals, so an exact match would fail on formatting and be
    "fixed" by deleting the assertion.

    Three comparisons, each added because the one before it was measured to miss
    a real drift. The **multiset of operands** catches a changed literal or a
    dropped clause; a plain set did not, because inverting one of two `!~` left
    the set unchanged. The **connectives** are in that multiset because filtering
    `AND` and `OR` out by name let `AND` become `OR` invisibly -- turning "must
    not begin *and* must not end with whitespace" into a rule every non-empty
    name satisfies. And each **operator is paired with its operand**, because a
    multiset has no notion of which bound belongs to which comparison, so the
    unsatisfiable `BETWEEN 200 AND 1` produced exactly the multiset of the
    correct `BETWEEN 1 AND 200`.

    What it still permits, deliberately: reordering whole clauses, which is
    semantically identical. What it does not permit, and arguably should: a
    redundant clause that changes nothing. That direction is over-strict and
    left that way, since a declaration is supposed to mirror the constraint.
    `tests/schema/test_wp12_slice_c_admission.py` does the same comparison for
    `capability_is_known`; this is the entity plane's.
    """
    declared = next(
        constraint
        for constraint in tables.entity_observations.constraints
        if getattr(constraint, "name", None) == "a_disclosed_mention_name_is_bounded"
    )
    declared_text = str(declared.sqltext)  # type: ignore[attr-defined]

    with two_principals.connect() as connection:
        live = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'a_disclosed_mention_name_is_bounded'"
            )
        ).scalar_one()

    def operands(expression: str) -> list[str]:
        """The literals and column names the expression is built out of.

        `::type` casts are stripped first. PostgreSQL renders every literal in a
        stored constraint with its type -- `'...'::text` -- and the declaration
        does not, so leaving them in would compare a rendering convention rather
        than the rule and be "fixed" by deleting the assertion.
        """
        # `BETWEEN a AND b` is stored as two comparisons, so the declaration is
        # rewritten the same way before tokenizing. A rendering difference, not
        # a drift -- unlike the operators below it, which are both.
        expanded = re.sub(
            r"(\S+)\s+BETWEEN\s+(\S+)\s+AND\s+(\S+)",
            r"\1 >= \2 AND \1 <= \3",
            expression,
            flags=re.IGNORECASE,
        )
        without_casts = re.sub(r"::[a-z_ ]+", "", expanded)
        return [
            token
            for token in re.findall(
                # Operators and connectives too. Without the operators the
                # comparison saw only column names, literals and numbers, and
                # the tenth review measured what that costs. Without the
                # connectives it still did: the eleventh review turned the `AND`
                # between the two `!~` clauses into `OR` -- "must not begin
                # *or* must not end with whitespace", which every non-empty name
                # satisfies -- and the multiset was unchanged, because `AND` and
                # `OR` were filtered out by name.
                r"'[^']*'|!~\*?|~\*?|<=|>=|<>|!=|=|<|>|\bIS NOT NULL\b|\bIS NULL\b"
                r"|\bAND\b|\bOR\b|\bNOT\b|\b[a-z_]+\b|\b\d+\b",
                without_casts,
            )
            if token.lower() != "check"
        ]

    def bindings(tokens: list[str]) -> Counter[tuple[str, str]]:
        """Each operator paired with the operand it applies to.

        A multiset of tokens has no notion of which operand belongs to which
        operator, so `BETWEEN 200 AND 1` -- an unsatisfiable bound, expanded to
        `>= 200 AND <= 1` -- produced exactly the multiset of the correct
        `>= 1 AND <= 200` and passed. The eleventh review measured that. Pairing
        each operator with the token after it distinguishes them while leaving
        a reordering of whole clauses, which is semantically identical, alone.
        """
        operators = {"!~", "!~*", "~", "~*", "<=", ">=", "<>", "!=", "=", "<", ">"}
        return Counter(
            (token, tokens[index + 1])
            for index, token in enumerate(tokens)
            if token in operators and index + 1 < len(tokens)
        )

    # **Counted, not merely present.** A set comparison ignores multiplicity, and
    # this constraint applies `!~` twice and `~` once. Flipping one `!~` to `~`
    # -- so a disclosed mention name may begin with whitespace -- leaves the set
    # `{!~, ~}` unchanged and passed. Measured, after the operators were added
    # and before the count was.
    declared_operands = Counter(operands(declared_text))
    live_operands = Counter(operands(live))
    missing = declared_operands - live_operands
    assert missing == Counter(), (
        f"`tables.py` declares operands the server's constraint does not hold: "
        f"{sorted(missing.elements())}. The declaration is not emitted, so only "
        f"this test can notice.\ndeclared: {declared_text}\nlive:     {live}"
    )
    extra = live_operands - declared_operands
    assert extra == Counter(), (
        f"the server holds operands `tables.py` does not declare: "
        f"{sorted(extra.elements())}.\ndeclared: {declared_text}\nlive:     {live}"
    )

    declared_pairs = bindings(operands(declared_text))
    live_pairs = bindings(operands(live))
    assert declared_pairs == live_pairs, (
        "`tables.py` binds an operator to a different operand than the server "
        f"does: declared {sorted(declared_pairs - live_pairs)}, live "
        f"{sorted(live_pairs - declared_pairs)}.\ndeclared: {declared_text}\n"
        f"live:     {live}"
    )


def test_walking_the_queue_at_the_server_serves_every_mention_exactly_once(
    two_principals: Engine,
) -> None:
    """The observations keyset, against SQL rather than against the double.

    `search` and `relationships` each have a database-tier walk that reddens
    when their keyset widens from `>` to `>=`. The queue did not: the ninth
    review made that mutation and 110 database tests and 106 contract tests
    stayed green. The only walk-the-queue test in the repository --
    `tests/contract/test_entity_read_bounds.py::
    test_walking_the_queue_reaches_every_mention_exactly_once`, whose own
    assertion message reads "a mention was served on two pages" -- runs entirely
    against `tests/conftest.py::_Entities`.

    So the one paged read whose continuation semantics were proved only by the
    fake is the operator queue, which is the read where repeating a page is
    worst: a mention served twice is a mention an operator resolves twice.
    """
    identifiers = [f"eobs_walk{index:04d}walk0001" for index in range(5)]
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        for identifier in identifiers:
            repository.record_observation(
                PRINCIPAL_A, _observation(identifier, principal_id=PRINCIPAL_A)
            )

    seen: list[str] = []
    cursor: str | None = None
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        for _ in range(len(identifiers) + 2):
            page = repository.observations(
                PRINCIPAL_A, unresolved_only=True, limit=2, after_observation_id=cursor
            )
            if not page:
                break
            seen.extend(item.observation_id for item in page)
            if len(page) < 2:
                break
            cursor = page[-1].observation_id

    assert len(seen) == len(set(seen)), f"a mention was served on two pages: {seen}"
    assert sorted(seen) == sorted(identifiers), (
        f"the walk did not reach every mention exactly once: {sorted(seen)}"
    )
