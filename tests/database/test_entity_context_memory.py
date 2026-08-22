"""`entities.context` and its Relationship Memory summary, against a real server.

`RM-API-AC-013` puts a bounded memory summary on the context card, and the
acceptance criterion is not that the memories appear. It is that **four
different reasons for a memory not appearing never look alike**, because three
of them are not facts about the person and one of them is:

* `MORE_MEMORIES_THAN_THIS_CARD_CARRIES` -- the page filled;
* `MEMORIES_WERE_WITHHELD_BY_CLASSIFICATION` -- policy refused rows, and no page
  size will produce them;
* `NO_MEMORY_HAS_BEEN_RECORDED` -- the store was read and holds none;
* `THE_MEMORY_PLANE_IS_UNAVAILABLE` -- this build never composed the plane, so
  the card cannot speak for it either way.

An empty `memories` list is the same bytes in three of those, which is why the
list is never the statement and the limitations always are. The failure this
module measures is one sentence long: a reader concluding "nothing is recorded
about this person" from a card that did not look, or from a card that looked and
was refused.

**Why the whole stack rather than the service.** Three of the four states are
decided in three different places -- the withholding in a `WHERE` clause on a
real server, the absence in the application service, and the unavailability in
the `entities.context` handler reading the switches its build was composed with.
A test that constructed `EntityContextService` by hand would supply the third
one itself and prove nothing about the handler, and one that drove an in-memory
double would prove nothing about the first. So each card here comes back from
`ApplicationService.invoke` over a disposable PostgreSQL database, and the two
builds -- memory plane composed and not -- are two real compositions.

Every identifier and every statement here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from my_pa.application.commands import GetEntityContext
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import MemoryWriteRequest, UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.relationship.context_card import CONTEXT_CARD_COLLECTION_LIMIT
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    DIRECT_USER_AUTHORITY,
    MemoryActorClass,
    MemoryKind,
    MemoryOperation,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]

#: Distinct from every other database-tier fixture's disposable database, so
#: this suite can run beside them without one dropping the database another is
#: mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_context_memory_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: One entity per state, because the states are properties of what the store
#: holds about a subject and staging them on one entity would make each test
#: depend on the order the others ran in.
ALICE: Final = "ent_aaaa0001aaaa0001"
QUIET: Final = "ent_bbbb0002bbbb0002"
GUARDED: Final = "ent_cccc0003cccc0003"
CROWDED: Final = "ent_dddd0004dddd0004"
THINNED: Final = "ent_eeee0005eeee0005"
#: The other Principal's own entity. Distinct because `entity_id` is a global
#: primary key and no two rows may share one, whoever holds them.
BOB: Final = "ent_ffff0006ffff0006"

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)
APPLIES_FROM: Final = datetime(2026, 1, 1, tzinfo=UTC)
APPLIES_UNTIL: Final = datetime(2026, 12, 31, tzinfo=UTC)

#: The one statement that must never reach a payload. Distinctive on purpose:
#: the assertion that it is absent is a substring search over the whole rendered
#: card, so a leak through any field fails rather than only a leak through the
#: field this module thought to name.
RESTRICTED_STATEMENT: Final = "Synthetic restricted note about the Riverside matter."

#: The four wire values the criterion is about, named once so the tests that
#: quantify over them cannot drift apart from the ones that assert a single
#: member.
MEMORY_LIMITATIONS: Final = frozenset(
    {
        "more_memories_than_this_card_carries",
        "memories_were_withheld_by_classification",
        "no_memory_has_been_recorded",
        "the_memory_plane_is_unavailable",
    }
)

LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


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


def _an_entity(entity_id: str, principal_id: str, display_name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _write(
    repository: SqlRelationshipMemoryRepository,
    principal_id: str,
    subject_entity_id: str,
    *,
    kind: MemoryKind,
    statement: str,
    classification: Classification,
    pinned: bool = False,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> str:
    """One admitted memory, and the identifier it was given.

    Written through the repository rather than through the eight
    `relationship_memory.` capabilities, because what this module is measuring is
    the *read*: the write path has its own suite, and driving it here would make
    every assertion below depend on two planes agreeing.
    """
    admission = repository.admit(
        MemoryWriteRequest(
            operation=MemoryOperation.CREATE,
            memory_id=None,
            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
            expected_version=None,
            principal_id=principal_id,
            subject_entity_id=subject_entity_id,
            memory_kind=kind,
            statement=statement,
            statement_sha256=statement_digest(statement),
            structured_value=None,
            authority=DIRECT_USER_AUTHORITY,
            classification=classification,
            created_by_actor=MemoryActorClass.USER,
            context_links=(),
            pinned=pinned,
            observed_at=None,
            effective_from=effective_from,
            effective_to=effective_to,
            correction_reason=None,
            idempotency_key=issue_identifier(IdKind.CORRELATION),
            correlation_id=issue_identifier(IdKind.CORRELATION),
            server_received_at=WHEN,
        )
    )
    return admission.receipt.memory_id


@pytest.fixture
def staged(disposable_database: str) -> Iterator[str]:
    """Six entities, each staged into exactly one of the states under test.

    `THINNED` is the arrangement no single-cause fixture produces and the one the
    card's invariants are most easily written wrong against: its page is *both*
    truncated and thinned by policy, so it carries fewer than the collection
    limit while a twenty-sixth row genuinely exists. The two restricted rows are
    pinned so the ordering that decides the page (`pinned DESC, memory_id`) puts
    them on it deterministically rather than by identifier luck.
    """
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            entities = SqlEntityRepository(connection)
            entities.create(PRINCIPAL_A, _an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
            entities.create(PRINCIPAL_A, _an_entity(QUIET, PRINCIPAL_A, "Quiet Synthetic"))
            entities.create(PRINCIPAL_A, _an_entity(GUARDED, PRINCIPAL_A, "Guarded Synthetic"))
            entities.create(PRINCIPAL_A, _an_entity(CROWDED, PRINCIPAL_A, "Crowded Synthetic"))
            entities.create(PRINCIPAL_A, _an_entity(THINNED, PRINCIPAL_A, "Thinned Synthetic"))
            entities.create(PRINCIPAL_B, _an_entity(BOB, PRINCIPAL_B, "Bob Synthetic"))

            memories = SqlRelationshipMemoryRepository(connection)
            _write(
                memories,
                PRINCIPAL_A,
                ALICE,
                kind=MemoryKind.WORKING_PREFERENCE,
                statement="Synthetic note: wants cost issues in writing.",
                classification=Classification.PRIVATE_LOCAL,
                pinned=True,
                effective_from=APPLIES_FROM,
                effective_to=APPLIES_UNTIL,
            )
            # `QUIET` gets nothing at all: that is its state.
            _write(
                memories,
                PRINCIPAL_A,
                GUARDED,
                kind=MemoryKind.SENSITIVITY,
                statement=RESTRICTED_STATEMENT,
                classification=Classification.RESTRICTED_LOCAL,
            )
            for index in range(CONTEXT_CARD_COLLECTION_LIMIT + 1):
                _write(
                    memories,
                    PRINCIPAL_A,
                    CROWDED,
                    kind=MemoryKind.GENERAL_NOTE,
                    statement=f"Synthetic crowded note {index:03d}.",
                    classification=Classification.PRIVATE_LOCAL,
                )
            for index in range(CONTEXT_CARD_COLLECTION_LIMIT + 1):
                _write(
                    memories,
                    PRINCIPAL_A,
                    THINNED,
                    kind=MemoryKind.GENERAL_NOTE,
                    statement=f"Synthetic thinned note {index:03d}.",
                    classification=Classification.PRIVATE_LOCAL,
                )
            for index in range(2):
                _write(
                    memories,
                    PRINCIPAL_A,
                    THINNED,
                    kind=MemoryKind.SENSITIVITY,
                    statement=f"{RESTRICTED_STATEMENT} Pinned {index:03d}.",
                    classification=Classification.RESTRICTED_LOCAL,
                    pinned=True,
                )
            _write(
                memories,
                PRINCIPAL_B,
                BOB,
                kind=MemoryKind.GENERAL_NOTE,
                statement="Synthetic note held by the other Principal.",
                classification=Classification.PRIVATE_LOCAL,
            )
    finally:
        engine.dispose()
    yield disposable_database


class _Runtime:
    """One composed build, with the Relationship Memory plane on or off.

    The switch is the whole point of the class: `memory_plane=False` is not a
    stub or a patched attribute, it is the composition an operator gets by
    leaving `MY_PA_RELATIONSHIP_MEMORY_ENABLED` unset, and the card it produces
    is the card that build serves.
    """

    def __init__(self, url: str, *, memory_plane: bool) -> None:
        self.work_engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            relationship_intelligence_enabled=True,
            relationship_memory_enabled=memory_plane,
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def envelope(self, entity_id: str, *, principal_id: str = PRINCIPAL_A) -> ResponseEnvelope:
        purpose = sorted(permitted_purposes(Capability.ENTITIES_CONTEXT))[0]
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=Capability.ENTITIES_CONTEXT,
                purpose=purpose,
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            GetEntityContext(entity_id=entity_id),
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )


def _card(runtime: _Runtime, entity_id: str, *, principal_id: str = PRINCIPAL_A) -> dict[str, Any]:
    envelope = runtime.envelope(entity_id, principal_id=principal_id)
    assert envelope.error is None
    assert envelope.result is not None
    card = envelope.result["context_card"]
    assert isinstance(card, dict)
    return card


@pytest.fixture
def composed(staged: str) -> Iterator[_Runtime]:
    """The build that serves the memory plane."""
    runtime = _Runtime(staged, memory_plane=True)
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.fixture
def withheld_plane(staged: str) -> Iterator[_Runtime]:
    """The build that does not, with the same rows underneath it."""
    runtime = _Runtime(staged, memory_plane=False)
    try:
        yield runtime
    finally:
        runtime.close()


# --- the four states, one at a time -----------------------------------------


def test_a_build_without_the_memory_plane_says_it_cannot_say(withheld_plane: _Runtime) -> None:
    """The rows exist. The card says nothing about them, and says that it is not saying.

    `ALICE` is the entity chosen deliberately: the store holds a memory about her
    the whole time, so a card that reported an absence here would be reporting a
    false one, not merely an unhelpful one.
    """
    card = _card(withheld_plane, ALICE)
    assert card["memories"] == []
    assert "the_memory_plane_is_unavailable" in card["limitations"]
    assert "no_memory_has_been_recorded" not in card["limitations"]
    assert "memories_were_withheld_by_classification" not in card["limitations"]
    assert "more_memories_than_this_card_carries" not in card["limitations"]
    assert "wants cost issues in writing" not in str(card)


def test_a_card_that_asked_and_found_nothing_says_so(composed: _Runtime) -> None:
    """The one member of the four that is a fact about the person."""
    card = _card(composed, QUIET)
    assert card["memories"] == []
    assert "no_memory_has_been_recorded" in card["limitations"]
    assert "the_memory_plane_is_unavailable" not in card["limitations"]
    assert "memories_were_withheld_by_classification" not in card["limitations"]


def test_a_wholly_withheld_page_is_a_withholding_and_never_an_absence(
    composed: _Runtime,
) -> None:
    """The case that decides the criterion: empty list, and not an empty subject.

    Every memory about `GUARDED` is `restricted_local`, so the card carries none
    of them and looks -- in `memories` alone -- exactly like `QUIET`. Reading that
    as "nothing is recorded" would be reading a policy decision as a fact about a
    person, and it is the reading `NO_MEMORY_HAS_BEEN_RECORDED` is refused here
    to prevent.
    """
    card = _card(composed, GUARDED)
    assert card["memories"] == []
    assert "memories_were_withheld_by_classification" in card["limitations"]
    assert "no_memory_has_been_recorded" not in card["limitations"]
    assert "the_memory_plane_is_unavailable" not in card["limitations"]
    assert RESTRICTED_STATEMENT not in str(card)
    assert "Riverside" not in str(card)


def test_a_card_says_when_more_memories_exist_than_it_carries(composed: _Runtime) -> None:
    """The ordinary truncation, and the only one of the four a larger page fixes."""
    card = _card(composed, CROWDED)
    assert len(card["memories"]) == CONTEXT_CARD_COLLECTION_LIMIT
    assert "more_memories_than_this_card_carries" in card["limitations"]
    assert "no_memory_has_been_recorded" not in card["limitations"]
    assert "memories_were_withheld_by_classification" not in card["limitations"]
    assert card["is_complete"] is False


def test_a_page_both_truncated_and_thinned_states_both(composed: _Runtime) -> None:
    """Truncation and withholding are independent, so both can be true at once.

    `THINNED` carries fewer than the collection limit *and* is truncated, because
    policy removed rows from a page that was already full. A card that inferred
    "not truncated" from a short list -- the inference the five older collections
    are allowed to make -- would report the twenty-sixth memory as not existing.
    """
    card = _card(composed, THINNED)
    assert len(card["memories"]) == CONTEXT_CARD_COLLECTION_LIMIT - 2
    assert "more_memories_than_this_card_carries" in card["limitations"]
    assert "memories_were_withheld_by_classification" in card["limitations"]
    assert "no_memory_has_been_recorded" not in card["limitations"]
    assert RESTRICTED_STATEMENT not in str(card)


# --- and the four together ---------------------------------------------------


def test_the_four_states_are_pairwise_distinguishable(
    composed: _Runtime, withheld_plane: _Runtime
) -> None:
    """`RM-AC-029`: no two of the four answer the same way.

    Asserted as a set of sets rather than as four separate `in` checks, because
    the criterion is about the *vocabulary* rather than about any one card: four
    distinct readings have to survive together, and a fifth state collapsing onto
    a fourth is a failure no single-card assertion can see.
    """

    def _said(runtime: _Runtime, entity_id: str) -> frozenset[str]:
        return frozenset(set(_card(runtime, entity_id)["limitations"]) & MEMORY_LIMITATIONS)

    unavailable = _said(withheld_plane, ALICE)
    absent = _said(composed, QUIET)
    guarded = _said(composed, GUARDED)
    crowded = _said(composed, CROWDED)

    assert unavailable == frozenset({"the_memory_plane_is_unavailable"})
    assert absent == frozenset({"no_memory_has_been_recorded"})
    assert guarded == frozenset({"memories_were_withheld_by_classification"})
    assert crowded == frozenset({"more_memories_than_this_card_carries"})
    assert len({unavailable, absent, guarded, crowded}) == 4
    # Three of the four carry no memories at all, which is exactly why the
    # limitations rather than the list have to be what a reader reads.
    assert _card(withheld_plane, ALICE)["memories"] == []
    assert _card(composed, QUIET)["memories"] == []
    assert _card(composed, GUARDED)["memories"] == []


def test_only_a_real_truncation_makes_a_card_incomplete(
    composed: _Runtime, withheld_plane: _Runtime
) -> None:
    """`is_complete` answers "did the card run out of room", and nothing wider.

    A withholding and an unavailable plane are stated in `limitations` and are
    not truncations: asking again returns the identical card, so reporting them
    as truncation would invite a request loop that cannot terminate and would
    attach the reason `card_collection_limit_reached` to a card whose collection
    limit never bit.
    """
    assert _card(withheld_plane, ALICE)["is_complete"] is True
    assert _card(composed, QUIET)["is_complete"] is True
    assert _card(composed, GUARDED)["is_complete"] is True
    assert _card(composed, CROWDED)["is_complete"] is False

    truncation = composed.envelope(CROWDED).disclosure.truncation
    assert truncation.is_truncated is True
    assert truncation.reason == "card_collection_limit_reached"
    assert composed.envelope(GUARDED).disclosure.truncation.is_truncated is False


# --- what one carried memory looks like --------------------------------------


def test_a_carried_memory_renders_its_summary_fields(composed: _Runtime) -> None:
    """Each field read off the half that owns it, and nothing invented.

    `pinned` and `kind` belong to the aggregate; the statement, its authority,
    its classification and the window it applies to belong to the version in
    force. A summary assembled from one half would have had to guess at the
    other.
    """
    card = _card(composed, ALICE)
    assert len(card["memories"]) == 1
    summary = card["memories"][0]
    assert summary["memory_id"].startswith("mem_")
    assert summary["kind"] == MemoryKind.WORKING_PREFERENCE.value
    assert summary["statement"] == "Synthetic note: wants cost issues in writing."
    assert summary["authority"] == DIRECT_USER_AUTHORITY.value
    assert summary["classification"] == Classification.PRIVATE_LOCAL.value
    assert summary["pinned"] is True
    assert summary["effective_from"] == "2026-01-01T00:00:00.000Z"
    assert summary["effective_to"] == "2026-12-31T00:00:00.000Z"
    assert summary["recorded_at"] == "2026-08-22T12:00:00.000Z"
    assert not set(card["limitations"]) & MEMORY_LIMITATIONS


def test_a_memory_summary_never_reaches_another_principals_card(composed: _Runtime) -> None:
    """The partition, at the one read that could disclose a note without naming it.

    Both directions: `B`'s card carries `B`'s memory and not `A`'s, and `A`
    cannot name `B`'s entity at all -- a foreign entity answers exactly what an
    absent one answers, so the refusal cannot be used to learn that the
    identifier names something.
    """
    theirs = _card(composed, BOB, principal_id=PRINCIPAL_B)
    assert [row["statement"] for row in theirs["memories"]] == [
        "Synthetic note held by the other Principal."
    ]
    assert "wants cost issues in writing" not in str(theirs)

    foreign = composed.envelope(BOB, principal_id=PRINCIPAL_A)
    absent = composed.envelope("ent_99990000999900", principal_id=PRINCIPAL_A)
    assert foreign.error is not None
    assert absent.error is not None
    assert foreign.error.code == absent.error.code
