"""`SqlRelationshipMemoryRepository` against a real PostgreSQL server.

Beside `tests/database/test_entity_repository.py`, which makes the same kind of
claim about the plane that owns a memory's subject, and structured the same way:
real statements, real constraints, a real append-only trigger, and a partition
predicate that is either in the WHERE clause or is not.

Four claims carry this plane and each is asserted here against the server rather
than against the code that usually calls it:

* **A version is written once.** `revise` appends a successor and leaves the
  predecessor's exact text retrievable, and a raw `UPDATE` on the version table
  is refused by the trigger — which is the half no application rule can hold,
  because a rule the current writer remembers is not a rule the next writer
  inherits.
* **A stale expectation writes nothing.** The guarded `UPDATE … WHERE version =
  expected` is read for its row count before anything else is written, so the
  rows are counted inside the failed transaction and again after it.
* **A foreign memory answers exactly what an absent one answers.** Asserted as an
  equality between the two answers rather than as two separate `is None` checks,
  because "both happen to be falsey" is a weaker claim than "indistinguishable".
* **Ownership of the subject and of every context target is proven before the
  insert.** A foreign subject, a foreign context target and a merged-away subject
  are each refused, and the row counts show the refusal came first.

Everything is synthetic: two invented Principals, invented entities, invented
notes. No real person and no live data. The database is created and dropped by
this module's own fixture and is never the configured one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import MemoryPage, MemoryWriteRequest, UnknownScopeError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    PERSON_ONLY_KINDS,
    MemoryActorClass,
    MemoryAdmission,
    MemoryAuthority,
    MemoryConflictError,
    MemoryKind,
    MemoryKindNotPermittedError,
    MemoryLifecycle,
    MemoryOperation,
    MemoryReceipt,
    MergedSubjectError,
    StaleMemoryVersionError,
    classification_floor_for,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database
#: another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_relationship_memory_repository_test"

#: This plane's revision and the one it revises, for the round trip below.
#: `e9b2c4d7a150` was the predecessor until the WP-FE-03 Work contracts merged;
#: this revision was rebased onto them rather than forked beside them, so the
#: chain has one head and the downgrade target below is the Work revision.
MEMORY_REVISION: Final = "f1c6b904a2d7"
PREVIOUS_REVISION: Final = "a4d9e7c2b615"

#: The eight tables the revision creates.
MEMORY_TABLES: Final = frozenset(
    {
        "relationship_memories",
        "relationship_memory_versions",
        "relationship_memory_submissions",
        "relationship_memory_context_links",
        "relationship_memory_evidence_links",
        "relationship_memory_proposals",
        "relationship_memory_proposal_evidence",
        "relationship_memory_review_decisions",
    }
)

#: The three tables one admitted write touches, counted together whenever the
#: claim is "nothing was written".
WRITE_TABLES: Final = (
    "relationship_memories",
    "relationship_memory_versions",
    "relationship_memory_submissions",
)

#: The planes an automatic action would have to land in for a note to have
#: quietly become an obligation, a promise or a captured artefact. Named as the
#: schema names them — `tasks` and `commitments`, not `continuity_*`, which is
#: what the first version of this list guessed — and checked against
#: `information_schema` before they are counted.
OTHER_PLANES: Final = ("tasks", "commitments", "captures")

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: A's synthetic people, and one project A owns so a context link has somewhere
#: real to point.
DANA: Final = "ent_aaaa0001aaaa0001"
ELI: Final = "ent_cccc0003cccc0003"
RIVERSIDE: Final = "ent_dddd0004dddd0004"
#: A's merged-away identity, and the identity it was merged into.
OLD_DANA: Final = "ent_eeee0005eeee0005"
#: B's own person, so every read of A's has a foreign decoy beside it.
FOREIGN_PERSON: Final = "ent_bbbb0002bbbb0002"
#: An entity nobody created, so "absent" has an identifier to be absent under.
ABSENT_ENTITY: Final = "ent_ffff0006ffff0006"
ABSENT_MEMORY: Final = "mem_ffff0006ffff0006"

FIRST_NOTE: Final = "Synthetic subject prefers Teams messages."
SECOND_NOTE: Final = "Synthetic subject prefers phone calls now, not Teams."

#: A word that appears in `FIRST_NOTE` and in no other synthetic fixture, so a
#: search for it matches exactly one memory and a second Principal searching it
#: is asking about a term that exists — which is what makes the empty answer
#: isolation rather than a query that matches nobody.
_SEARCHABLE_TERM: Final = "Teams"

THIRD_NOTE: Final = "Synthetic subject prefers email above all."

#: A `sensitivity` note, whose classification floors at `restricted_local` — the
#: one kind a page can withhold. Deliberately shares no token with the search
#: fixtures, so it can never be the thing a term probe matched.
SENSITIVE_NOTE: Final = "Synthetic subject is caring for an unwell relative."

#: Three notes that share one token, so one arrangement serves both keyset
#: reads: `page_for_entity` pages them by subject and `search` pages the same
#: three by the term they have in common. Distinct wording, so a page that lost
#: one is a missing identifier rather than a repeated sentence.
PAGED_NOTES: Final = (
    "Synthetic paged note about the north dock.",
    "Synthetic paged note about the weekday roster.",
    "Synthetic paged note about the pallet count.",
)
PAGED_TERM: Final = "paged"

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 22, 13, tzinfo=UTC)

#: When the user says the thing was observed, as distinct from when the server
#: received it. Deliberately not `WHEN`, `LATER` or either window boundary, so a
#: writer that quietly substituted the receipt time — or either applicability
#: bound — for an absent `observed_at` would be caught by value and not merely
#: by presence.
OBSERVED: Final = datetime(2026, 5, 4, 9, 30, tzinfo=UTC)

#: One timeline for the `as_of` filter: a window that has closed, a window that
#: opened later and is still open, and two probes — one inside the closed window
#: and one after both — so each read has something to include and something to
#: exclude. Both are before `WHEN`, which is when every fixture row is recorded.
WINDOW_OPENED: Final = datetime(2026, 1, 1, 12, tzinfo=UTC)
WINDOW_CLOSED: Final = datetime(2026, 3, 1, 12, tzinfo=UTC)
SECOND_WINDOW_OPENED: Final = datetime(2026, 6, 1, 12, tzinfo=UTC)
INSIDE_THE_FIRST_WINDOW: Final = datetime(2026, 2, 1, 12, tzinfo=UTC)
AFTER_BOTH_WINDOWS_OPENED: Final = datetime(2026, 7, 1, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def an_entity(
    entity_id: str,
    principal_id: str,
    display_name: str,
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def two_principals(migrated_engine: Engine) -> Engine:
    """A holds Dana, Eli, Riverside and a merged-away identity; B holds one person.

    Every read below therefore has a foreign decoy that really exists, so an
    empty answer is evidence about the partition rather than about the fixture.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, an_entity(DANA, PRINCIPAL_A, "Dana Synthetic"))
        repository.create(PRINCIPAL_A, an_entity(ELI, PRINCIPAL_A, "Eli Synthetic"))
        repository.create(
            PRINCIPAL_A,
            an_entity(RIVERSIDE, PRINCIPAL_A, "Riverside Synthetic", EntityType.PROJECT),
        )
        repository.create(PRINCIPAL_A, an_entity(OLD_DANA, PRINCIPAL_A, "Dana Old Synthetic"))
        repository.create(PRINCIPAL_B, an_entity(FOREIGN_PERSON, PRINCIPAL_B, "Bo Synthetic"))
        repository.redirect_entity(PRINCIPAL_A, OLD_DANA, DANA)
    return migrated_engine


# --- request builders ---------------------------------------------------------
#
# `MemoryWriteRequest` is what the repository takes, so these build one directly
# rather than going through `RelationshipMemoryService`. The service is proved
# elsewhere; here it would only stand between the assertion and the SQL.


def _create_request(
    *,
    principal_id: str,
    subject_entity_id: str,
    statement: str,
    idempotency_key: str,
    kind: MemoryKind = MemoryKind.GENERAL_NOTE,
    structured_value: dict[str, Any] | None = None,
    context_links: tuple[Mapping[str, str], ...] = (),
    pinned: bool = False,
    observed_at: datetime | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    at: datetime = WHEN,
) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        operation=MemoryOperation.CREATE,
        memory_id=None,
        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
        expected_version=None,
        principal_id=principal_id,
        subject_entity_id=subject_entity_id,
        memory_kind=kind,
        statement=statement,
        statement_sha256=statement_digest(statement),
        structured_value=structured_value,
        authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        classification=classification_floor_for(kind),
        created_by_actor=MemoryActorClass.USER,
        context_links=context_links,
        pinned=pinned,
        # All three default to `None` and all three are settable, because
        # `RM-AC-008` is a claim about both directions: a create that says
        # nothing about when a thing was observed or when it applies must store
        # nothing, and one that says something must store exactly that. A
        # builder that hard-coded `observed_at=None` could only ever exercise
        # the first half, which is how the criterion came to be cited by tests
        # that no defaulting writer would have reddened.
        observed_at=observed_at,
        # `effective_from`/`effective_to` are read by `page_for_entity` for its
        # `as_of` filter as well, and a builder that could not express a window
        # left that filter unreachable.
        effective_from=effective_from,
        effective_to=effective_to,
        correction_reason=None,
        idempotency_key=idempotency_key,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        server_received_at=at,
    )


def _mutate_request(
    operation: MemoryOperation,
    *,
    principal_id: str,
    memory_id: str,
    expected_version: int,
    idempotency_key: str,
    statement: str | None = None,
    kind: MemoryKind | None = None,
    correction_reason: str | None = None,
    context_links: tuple[Mapping[str, str], ...] = (),
    pinned: bool | None = None,
    at: datetime = LATER,
) -> MemoryWriteRequest:
    # A revise carries a kind because it writes a version; an archive and a
    # restore carry none, because the repository keeps the aggregate's own.
    revising = operation is MemoryOperation.REVISE
    effective_kind = (kind or MemoryKind.GENERAL_NOTE) if revising else None
    floor = classification_floor_for(effective_kind or MemoryKind.GENERAL_NOTE)
    return MemoryWriteRequest(
        operation=operation,
        memory_id=memory_id,
        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
        expected_version=expected_version,
        principal_id=principal_id,
        subject_entity_id=None,
        memory_kind=effective_kind,
        statement=statement,
        statement_sha256=None if statement is None else statement_digest(statement),
        structured_value=None,
        authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        classification=floor,
        created_by_actor=MemoryActorClass.USER,
        context_links=context_links,
        # `None` by default, which is what a revise that says nothing about the
        # pin sends. The repository keeps the aggregate's own value.
        pinned=pinned,
        observed_at=None,
        effective_from=None,
        effective_to=None,
        correction_reason=correction_reason,
        idempotency_key=idempotency_key,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        server_received_at=at,
    )


def _admit(
    repository: SqlRelationshipMemoryRepository, request: MemoryWriteRequest
) -> MemoryAdmission:
    """Replay first, then write — the order `RelationshipMemoryService._admit` uses.

    Written out here rather than imported so the repository's two write entry
    points are both exercised by name: a test that only called `admit` would
    never reach `replay_for`, which is where a conflicting key is refused.
    """
    replayed = repository.replay_for(
        request.idempotency_key, request.payload_digest, principal_id=request.principal_id
    )
    if replayed is not None:
        return MemoryAdmission(receipt=replayed, created=False)
    return repository.admit(request)


def _counts(connection: Connection) -> dict[str, int]:
    """How many rows each write table holds, read on the given connection."""
    return {
        table: int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )
        for table in WRITE_TABLES
    }


def _created(engine: Engine, **overrides: object) -> MemoryReceipt:
    """One admitted create, committed, with `overrides` applied to the request."""
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "subject_entity_id": DANA,
        "statement": FIRST_NOTE,
        "idempotency_key": "synthetic-create-0001",
    }
    with engine.begin() as connection:
        request = _create_request(**{**fields, **overrides})  # type: ignore[arg-type]
        return _admit(SqlRelationshipMemoryRepository(connection), request).receipt


def _revised(
    engine: Engine,
    memory_id: str,
    *,
    expected_version: int,
    statement: str,
    idempotency_key: str,
    pinned: bool | None = None,
) -> MemoryReceipt:
    """One admitted revise of A's memory, committed."""
    with engine.begin() as connection:
        return _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.REVISE,
                principal_id=PRINCIPAL_A,
                memory_id=memory_id,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
                statement=statement,
                pinned=pinned,
            ),
        ).receipt


def _three_paged_notes(engine: Engine) -> list[str]:
    """Three admitted notes about Dana, and the identifiers the plane gave them.

    The identifiers are minted inside `_create`, so a test that needs the sort
    key to disagree with identifier order has to read them back rather than
    choose them — which is why this returns them and the callers below pick out
    the one they want by value.
    """
    return [
        _created(
            engine,
            statement=statement,
            idempotency_key=f"synthetic-paged-{index:04d}",
        ).memory_id
        for index, statement in enumerate(PAGED_NOTES)
    ]


def _walk(read: Callable[[str | None], MemoryPage], *, pages: int) -> tuple[list[str], list[bool]]:
    """Every memory a keyset read reaches, in order, and each page's truncation flag.

    Bounded by `pages` rather than looping until the last page, because a cursor
    that fails to advance is exactly the defect this walk exists to find, and an
    unbounded loop would hang the suite instead of failing it.
    """
    reached: list[str] = []
    truncation: list[bool] = []
    cursor: str | None = None
    for _ in range(pages):
        page = read(cursor)
        reached.extend(memory.memory_id for memory in page.memories)
        truncation.append(page.is_truncated)
        if not page.is_truncated:
            break
        cursor = page.memories[-1].memory_id
    return reached, truncation


def _listed(page: MemoryPage) -> list[str]:
    """The identifiers one page discloses, sorted, for a set comparison."""
    return sorted(memory.memory_id for memory in page.memories)


# --- create, read, list, history ---------------------------------------------


def test_a_created_memory_round_trips_through_every_read(two_principals: Engine) -> None:
    """One write, then the four reads that must agree about it.

    `detail`, `page_for_entity` and `history` each build their own statement, so
    a write that only one of them could see would be a plane whose profile view
    and whose history disagree about what was recorded.
    """
    receipt = _created(two_principals)
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        detail = repository.detail(receipt.memory_id, principal_id=PRINCIPAL_A)
        page = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        versions, truncated = repository.history(
            receipt.memory_id, principal_id=PRINCIPAL_A, limit=10
        )
    assert detail is not None
    assert detail.memory.memory_id == receipt.memory_id
    assert detail.memory.subject_entity_id == DANA
    assert detail.memory.lifecycle_state is MemoryLifecycle.ACTIVE
    assert detail.current_version.statement == FIRST_NOTE
    assert detail.current_version.statement_sha256 == statement_digest(FIRST_NOTE)
    assert [memory.memory_id for memory in page.memories] == [receipt.memory_id]
    assert page.listing_facts[receipt.memory_id].statement == FIRST_NOTE
    assert [version.version_number for version in versions] == [1]
    assert versions[0].statement == FIRST_NOTE
    assert truncated is False


def test_a_create_that_names_no_moment_stores_none_and_one_that_names_them_keeps_them(
    two_principals: Engine,
) -> None:
    """`RM-AC-008`: unknown dates are stored as unknown, not filled in.

    The criterion has two halves and only the pair is worth anything. **A write
    that supplies no `observed_at`, `effective_from` or `effective_to` must read
    back with all three still `None`** — the plane must not decide that a note
    recorded today was *observed* today, because a memory whose observation time
    was invented is indistinguishable from one the user actually dated, and every
    later read (`as_of`, a rendered timeline, an eventual reminder rule) would
    treat the invention as testimony. **A write that supplies all three must read
    them back unchanged** — otherwise the first half could be satisfied by a
    column nothing writes at all, and the row would be `PASS` on the strength of
    a field that does not work.

    Read through `detail` *and* `history`, because they build separate statements
    over the version table and a column dropped from one projection is a real
    defect that the other cannot see.

    Without this test the whole criterion is unheld: before it, `observed_at`
    appeared in this plane's tests only as a fixture input that nothing read
    back, so defaulting it to the server receipt time reddened nothing.
    """
    silent = _created(two_principals, idempotency_key="synthetic-moments-0001")
    dated = _created(
        two_principals,
        subject_entity_id=ELI,
        statement=SECOND_NOTE,
        idempotency_key="synthetic-moments-0002",
        observed_at=OBSERVED,
        effective_from=WINDOW_OPENED,
        effective_to=WINDOW_CLOSED,
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        silent_detail = repository.detail(silent.memory_id, principal_id=PRINCIPAL_A)
        dated_detail = repository.detail(dated.memory_id, principal_id=PRINCIPAL_A)
        dated_history, _ = repository.history(dated.memory_id, principal_id=PRINCIPAL_A, limit=10)
    assert silent_detail is not None
    assert dated_detail is not None

    # Asserted as one tuple rather than three `is None` checks, so a defaulting
    # writer is reported with the value it invented rather than as a bare
    # `assert None`.
    silent_version = silent_detail.current_version
    assert (
        silent_version.observed_at,
        silent_version.effective_from,
        silent_version.effective_to,
    ) == (None, None, None)
    # The receipt time is stored, so "the row holds no times at all" is not an
    # equally good explanation for the three `None`s above.
    assert silent_version.recorded_at == WHEN

    supplied = (OBSERVED, WINDOW_OPENED, WINDOW_CLOSED)
    dated_version = dated_detail.current_version
    assert (
        dated_version.observed_at,
        dated_version.effective_from,
        dated_version.effective_to,
    ) == supplied
    assert [
        (version.observed_at, version.effective_from, version.effective_to)
        for version in dated_history
    ] == [supplied]


def test_both_listing_reads_carry_the_current_versions_authority_and_classification(
    two_principals: Engine,
) -> None:
    """`RM-AC-019`: a listing states where each memory came from, not only what it says.

    The three values are asserted off one `MemoryListingFacts` rather than off
    three lookups, because that is the property the record exists for: the
    statement, the authority that backs it and the classification that bounds it
    are read from one joined row and are only true together. They are checked on
    `page_for_entity` *and* on `search` because each builds its own `SELECT`, and
    a column added to one of them is exactly the shape of drift the pair catches.

    The values compared against are the version's own, read through `detail`,
    rather than the constants this fixture wrote — so a page that answered with a
    plausible default instead of the stored row would still fail.
    """
    receipt = _created(two_principals)
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        page = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        found = repository.search(_SEARCHABLE_TERM, principal_id=PRINCIPAL_A, limit=10)
        detail = repository.detail(receipt.memory_id, principal_id=PRINCIPAL_A)

    assert detail is not None
    listed = page.listing_facts[receipt.memory_id]
    matched = found.listing_facts[receipt.memory_id]
    assert listed.statement == detail.current_version.statement
    assert listed.authority is detail.current_version.authority
    assert listed.classification is detail.current_version.classification
    # The public write path may claim nothing else, so this is the value a
    # promotion has to differ from for the distinction to mean anything.
    assert listed.authority is MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE
    assert matched == listed


def test_a_withheld_memory_leaves_no_facts_record_behind(two_principals: Engine) -> None:
    """A page carries facts for what it disclosed, and for nothing it withheld.

    **The withheld row is the whole test.** The two collections are built in one
    loop with the withholding `continue` above both, so the failure mode is a
    restricted memory contributing a statement, an authority and a
    classification under a key no `memories` entry names — a caller reading the
    mapping rather than the tuple would then be handed the very note the policy
    removed, and the count of withheld rows would tell them where to look.

    Asserted as an equality of key sets rather than as a length: a count still
    matches when one key is dropped and another added.

    `include_restricted=False` is passed explicitly. The use case calls
    `page_for_entity` with `True` — the entity-scoped profile view discloses
    restricted memories on purpose — so this branch has no caller in `src/` and
    is reachable only from here, which is exactly why it needs a test of its own
    rather than cover from one of the reads above.
    """
    ordinary = _created(two_principals, idempotency_key="facts-key-0001", statement=FIRST_NOTE)
    restricted = _created(
        two_principals,
        idempotency_key="facts-key-0002",
        statement=SENSITIVE_NOTE,
        kind=MemoryKind.SENSITIVITY,
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        withholding = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, include_restricted=False
        )
        disclosing = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, include_restricted=True
        )

    # The restricted memory really is there, so the withheld page's silence is a
    # policy decision rather than an empty fixture.
    assert set(disclosing.listing_facts) == {ordinary.memory_id, restricted.memory_id}
    assert withholding.withheld_by_policy == 1
    assert [memory.memory_id for memory in withholding.memories] == [ordinary.memory_id]
    assert set(withholding.listing_facts) == {ordinary.memory_id}
    assert restricted.memory_id not in withholding.listing_facts


def test_the_receipt_names_the_version_that_was_written(two_principals: Engine) -> None:
    """A receipt for a version the write did not create would be unusable as one."""
    receipt = _created(two_principals)
    assert receipt.created is True
    assert receipt.version_number == 1
    assert receipt.aggregate_version == 1
    assert receipt.statement_sha256 == statement_digest(FIRST_NOTE)
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.current_version.memory_version_id == receipt.memory_version_id


# --- the version chain is append only ----------------------------------------


def test_a_revision_appends_a_successor_and_keeps_the_predecessor(
    two_principals: Engine,
) -> None:
    """Correction is an append. The words the user first wrote stay readable.

    Without this, "immutable" would mean only that the current row is not edited
    in place, and a corrected note would lose the wording the user is entitled to
    see in its history.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        revised = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.REVISE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-revise-0001",
                statement=SECOND_NOTE,
                correction_reason="the preference changed",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        versions, _ = repository.history(created.memory_id, principal_id=PRINCIPAL_A, limit=10)
        detail = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].statement == FIRST_NOTE
    assert versions[1].statement == SECOND_NOTE
    assert versions[0].prior_version_id is None
    assert versions[1].prior_version_id == versions[0].memory_version_id
    assert versions[1].correction_reason == "the preference changed"
    assert detail is not None
    assert detail.current_version.memory_version_id == revised.memory_version_id
    assert revised.version_number == 2
    assert revised.aggregate_version == 2


def test_a_raw_update_of_a_stored_version_is_refused_by_the_server(
    two_principals: Engine,
) -> None:
    """The half no application rule can hold.

    A rule enforced only by the current writer is a rule a repair script, a
    backfill or the next repository does not inherit, so the append-only claim is
    made by a `BEFORE UPDATE OR DELETE` trigger and asserted here against the
    server with the application out of the way.
    """
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "SET statement_text = 'rewritten' "
                    "WHERE memory_version_id = :memory_version_id"
                ),
                {"memory_version_id": receipt.memory_version_id},
            )
    with two_principals.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT statement_text FROM {SCHEMA}.relationship_memory_versions "  # noqa: S608
                "WHERE memory_version_id = :memory_version_id"
            ),
            {"memory_version_id": receipt.memory_version_id},
        ).scalar_one()
    assert stored == FIRST_NOTE


def test_a_raw_delete_of_a_stored_version_is_refused_by_the_server(
    two_principals: Engine,
) -> None:
    """The same trigger, and the reason the lifecycle vocabulary has no `deleted`."""
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"DELETE FROM {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "WHERE memory_version_id = :memory_version_id"
                ),
                {"memory_version_id": receipt.memory_version_id},
            )


# --- optimistic concurrency ---------------------------------------------------


def test_a_stale_expected_version_raises_and_writes_nothing(two_principals: Engine) -> None:
    """The refusal happens before the successor is inserted, not after.

    Counted twice: inside the transaction that raised — which is possible because
    the refusal is the guarded UPDATE's own row count rather than a database
    error, so the transaction is still usable — and again from a fresh connection
    afterwards. Counting only after would leave a rollback as an equally good
    explanation for the absent rows.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(StaleMemoryVersionError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _mutate_request(
                    MemoryOperation.REVISE,
                    principal_id=PRINCIPAL_A,
                    memory_id=created.memory_id,
                    expected_version=created.aggregate_version + 99,
                    idempotency_key="synthetic-stale-0001",
                    statement=SECOND_NOTE,
                ),
            )
        assert _counts(connection) == before
    with two_principals.connect() as connection:
        assert _counts(connection) == before
        detail = SqlRelationshipMemoryRepository(connection).detail(
            created.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.current_version.statement == FIRST_NOTE
    assert detail.memory.version == created.aggregate_version


# --- idempotency --------------------------------------------------------------


def test_replaying_one_key_returns_the_original_receipt_and_writes_no_second_row(
    two_principals: Engine,
) -> None:
    """A retry is not a second memory.

    The replayed receipt says `created=False`, so a client can tell an
    acknowledged write from a repeated one without comparing versions.
    """
    first = _created(two_principals, idempotency_key="synthetic-replay-0001")
    with two_principals.connect() as connection:
        before = _counts(connection)
    with two_principals.begin() as connection:
        replay = _admit(
            SqlRelationshipMemoryRepository(connection),
            _create_request(
                principal_id=PRINCIPAL_A,
                subject_entity_id=DANA,
                statement=FIRST_NOTE,
                idempotency_key="synthetic-replay-0001",
            ),
        )
    with two_principals.connect() as connection:
        after = _counts(connection)
    assert replay.created is False
    assert replay.receipt.created is False
    assert replay.receipt.memory_id == first.memory_id
    assert replay.receipt.memory_version_id == first.memory_version_id
    assert replay.receipt.version_number == first.version_number
    assert replay.receipt.statement_sha256 == first.statement_sha256
    assert after == before


def test_one_key_bound_to_a_different_payload_is_a_conflict(two_principals: Engine) -> None:
    """A lookup on the key alone would answer a *different* request with the
    original receipt, reporting a write that never happened as durable."""
    _created(two_principals, idempotency_key="synthetic-conflict-0001")
    with two_principals.begin() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(MemoryConflictError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=DANA,
                    statement=SECOND_NOTE,
                    idempotency_key="synthetic-conflict-0001",
                ),
            )


# --- archive and restore ------------------------------------------------------


def test_archive_and_restore_are_reversible_and_write_no_version(
    two_principals: Engine,
) -> None:
    """Two counters, and only one of them moves.

    The aggregate version advances on each transition — so a caller who read
    before the archive cannot then revise blindly — while the version *number*
    does not, because a lifecycle transition is not a correction and writes no
    statement. Collapsing the two would make `expected_version` on an archive
    either meaningless or a lie about the version chain.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        archived = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.ARCHIVE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-archive-0001",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        while_archived = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
        active_page = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        archived_page = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, lifecycle=MemoryLifecycle.ARCHIVED
        )
        versions_after_archive, _ = repository.history(
            created.memory_id, principal_id=PRINCIPAL_A, limit=10
        )
    with two_principals.begin() as connection:
        restored = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.RESTORE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=archived.aggregate_version,
                idempotency_key="synthetic-restore-0001",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        while_active = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
        versions_after_restore, _ = repository.history(
            created.memory_id, principal_id=PRINCIPAL_A, limit=10
        )

    assert archived.lifecycle_state is MemoryLifecycle.ARCHIVED
    assert while_archived is not None
    assert while_archived.memory.lifecycle_state is MemoryLifecycle.ARCHIVED
    assert while_archived.memory.archived_at is not None
    assert [memory.memory_id for memory in active_page.memories] == []
    assert [memory.memory_id for memory in archived_page.memories] == [created.memory_id]

    assert restored.lifecycle_state is MemoryLifecycle.ACTIVE
    assert while_active is not None
    assert while_active.memory.lifecycle_state is MemoryLifecycle.ACTIVE
    assert while_active.memory.archived_at is None

    # The aggregate version advances each time; the version number never does.
    assert [created.aggregate_version, archived.aggregate_version, restored.aggregate_version] == [
        1,
        2,
        3,
    ]
    assert [created.version_number, archived.version_number, restored.version_number] == [1, 1, 1]
    assert [version.version_number for version in versions_after_archive] == [1]
    assert [version.version_number for version in versions_after_restore] == [1]


# --- the partition ------------------------------------------------------------


def test_the_server_refuses_memory_evidence_naming_two_records(
    two_principals: Engine,
) -> None:
    """`memory_evidence_names_exactly_one_record`, asked of the server.

    The sibling of the proposal-side constraint, and unbound for the same
    reason: no application path writes an evidence link today — promotion does,
    and it writes one target — so nothing exercised the row shape the CHECK
    refuses. A basis naming two families is one a reader cannot resolve, and
    deleting the constraint failed no test until this one.
    """
    created = _created(two_principals)
    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            text(
                "INSERT INTO knowledge.relationship_memory_evidence_links ("
                "evidence_link_id, memory_version_id, principal_id, role, "
                "entity_observation_id, capture_span_id, knowledge_id, created_at) "
                "VALUES (:link_id, :version_id, :principal_id, 'direct', "
                ":observation_id, :span_id, NULL, now())"
            ),
            {
                "link_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_EVIDENCE_LINK),
                "version_id": created.memory_version_id,
                "principal_id": PRINCIPAL_A,
                "observation_id": issue_identifier(IdKind.ENTITY_OBSERVATION),
                "span_id": issue_identifier(IdKind.SPAN),
            },
        )
    assert "memory_evidence_names_exactly_one_record" in str(refused.value)


def test_the_server_refuses_memory_evidence_naming_no_record(
    two_principals: Engine,
) -> None:
    """The exactly-one half the previous test does not reach."""
    created = _created(two_principals)
    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            text(
                "INSERT INTO knowledge.relationship_memory_evidence_links ("
                "evidence_link_id, memory_version_id, principal_id, role, "
                "entity_observation_id, capture_span_id, knowledge_id, created_at) "
                "VALUES (:link_id, :version_id, :principal_id, 'direct', "
                "NULL, NULL, NULL, now())"
            ),
            {
                "link_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_EVIDENCE_LINK),
                "version_id": created.memory_version_id,
                "principal_id": PRINCIPAL_A,
            },
        )
    assert "memory_evidence_names_exactly_one_record" in str(refused.value)


def test_recording_a_memory_writes_into_no_other_plane(two_principals: Engine) -> None:
    """`RM-AC-010`/`RM-AC-011`: a note creates no obligation and no reminder.

    `follow_up_context` is the kind that most invites one — "ask about the
    graduation next time" reads like a to-do — so it is the kind used here. The
    assertion is over the tables an automatic action would have to land in, and
    the counts are taken before and after rather than asserted as zero, because
    an emptiness check over a table the fixture never populates asserts nothing.

    **The plane names are resolved against the catalogue first, and that is the
    whole guard.** This test named `continuity_tasks` and
    `continuity_commitments` for its first three weeks. Neither exists — the
    obligation planes are `tasks` and `commitments` — and `_row_count` answered
    a missing table with `-1` instead of raising. Worse, all three counts shared
    one connection, so the first `ProgrammingError` aborted the transaction and
    `captures` answered `-1` as well: `after == before` compared one constant
    dict with itself, and a repository that opened a task on every note would
    have passed. So the names are checked to exist before anything is counted, a
    table that has been renamed reddens this test rather than vanishing from it,
    and each count runs on a connection of its own so one failure cannot poison
    the rest.
    """
    _require_planes(two_principals, OTHER_PLANES)
    before = {plane: _row_count(two_principals, plane) for plane in OTHER_PLANES}

    receipt = _created(
        two_principals,
        kind=MemoryKind.FOLLOW_UP_CONTEXT,
        statement="Ask about the graduation next time.",
        idempotency_key="synthetic-follow-up-0001",
    )

    after = {plane: _row_count(two_principals, plane) for plane in OTHER_PLANES}
    # The note itself landed, so the unchanged counts are evidence about the
    # other planes rather than about a create that never happened.
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert after == before


def _require_planes(engine: Engine, planes: tuple[str, ...]) -> None:
    """Fail unless `knowledge` really carries every table `planes` names.

    Read from `information_schema.tables` rather than trusted: a count over a
    table this build does not have is not a weaker assertion, it is no assertion
    at all, and the failure mode it produces is silence.
    """
    catalogue = text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
    )
    with engine.connect() as connection:
        present = {row[0] for row in connection.execute(catalogue, {"schema": SCHEMA})}
    assert set(planes) <= present, f"no such plane in {SCHEMA}: {sorted(set(planes) - present)}"


def _row_count(engine: Engine, table: str) -> int:
    """How many rows one `knowledge` table holds, on a connection of its own.

    No `except`: a name this build does not carry raises out of here and fails
    the caller, which is the behaviour a sentinel return value took away. The
    fresh connection is the other half — three counts sharing one transaction
    made the first failure decide the other two.
    """
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )


def test_a_foreign_search_term_reads_exactly_as_an_absent_one(
    two_principals: Engine,
) -> None:
    """`search` is a read like the others, and it was the one nobody checked.

    An independent reviewer deleted the Principal predicate from the search
    statement and watched 506 tests pass while another Principal's private note
    text came back in the results. The other three reads were covered; this one
    was not, so the predicate that stops the disclosure was held in place by
    nothing.

    Two searches rather than one, because a search that returns nothing proves
    nothing on its own: the control establishes that the term *is* findable by
    the Principal who wrote it, so the empty answer to the other one is
    isolation rather than a query that matches nobody.
    """
    created = _created(two_principals)
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        held = repository.search(_SEARCHABLE_TERM, principal_id=PRINCIPAL_A, limit=25)
        foreign = repository.search(_SEARCHABLE_TERM, principal_id=PRINCIPAL_B, limit=25)
        absent = repository.search("nothingmatchesthisterm", principal_id=PRINCIPAL_B, limit=25)
    assert [memory.memory_id for memory in held.memories] == [created.memory_id]
    assert foreign.memories == ()
    assert foreign.withheld_by_policy == 0
    assert not foreign.is_truncated
    # The equality, not two separate emptiness checks: a foreign term must be
    # answered exactly as an absent one, so the shape of the answer cannot be
    # used to learn that the term matched something somewhere.
    assert foreign == absent


# --- the keyset, at the page size that exposes a wrong one --------------------
#
# Every read on this plane is paged and none of them was paged in a test: no
# call passed `after_memory_id` or `after_version_id`, and nothing asserted
# `is_truncated`. So the cursor could be reverted to comparing `memory_id` alone
# and the suite stayed green while a memory became unreachable by any page.
# `limit=1` throughout, because a page size that fits the whole fixture never
# issues a second query and therefore never uses the cursor at all.


def test_listing_at_one_a_page_reaches_every_memory_exactly_once(
    two_principals: Engine,
) -> None:
    """The keyset is the whole sort key, and this is the arrangement that proves it.

    `page_for_entity` orders pinned memories first, so a cursor compared on
    `memory_id` alone names a position in a *different* ordering than the one
    being paged. Put the pin on the memory with the **highest** identifier and
    the two orderings disagree as sharply as they can: page two then asks for
    identifiers above the pinned one, there are none, and both unpinned notes
    are unreachable by any page the caller can construct.

    The pinned memory is chosen after the write rather than before it, because
    `_create` mints the identifier — so the fixture reads them back and pins the
    maximum instead of hoping the order came out the useful way.

    Three assertions, and each kills a different wrong implementation: the exact
    sequence kills a cursor that skips, the set-size equality kills one that
    repeats a row forever, and the truncation flags kill a read that stops early
    or claims a further page that is not there.
    """
    written = _three_paged_notes(two_principals)
    pinned = max(written)
    _revised(
        two_principals,
        pinned,
        expected_version=1,
        statement="Synthetic paged note about the pinned dock roster.",
        idempotency_key="synthetic-paged-pin",
        pinned=True,
    )

    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        reached, truncation = _walk(
            lambda cursor: repository.page_for_entity(
                DANA, principal_id=PRINCIPAL_A, limit=1, after_memory_id=cursor
            ),
            pages=len(written) + 1,
        )

    unpinned = sorted(memory for memory in written if memory != pinned)
    assert reached == [pinned, *unpinned]
    assert len(reached) == len(set(reached)) == len(written)
    assert truncation == [True, True, False]


def test_searching_at_one_a_page_reaches_every_match_exactly_once(
    two_principals: Engine,
) -> None:
    """`search` pages by identifier alone, and nothing had walked it.

    The same three notes, reached through the other keyset. A search whose
    cursor never advanced would return the first match three times and a search
    that advanced twice would drop the middle one; both are green against a page
    large enough to hold everything, which is what every other test of this read
    used.
    """
    written = _three_paged_notes(two_principals)
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        reached, truncation = _walk(
            lambda cursor: repository.search(
                PAGED_TERM, principal_id=PRINCIPAL_A, limit=1, after_memory_id=cursor
            ),
            pages=len(written) + 1,
        )
    assert reached == sorted(written)
    assert len(reached) == len(set(reached)) == len(written)
    assert truncation == [True, True, False]


def test_paging_history_at_one_reaches_every_version_exactly_once(
    two_principals: Engine,
) -> None:
    """The version chain is the thing a user is entitled to read in full.

    Three versions and a page that holds one: the walk has to arrive at every
    wording the user ever wrote, oldest first, and stop exactly once. History
    keys its cursor on the version *number* the named version holds rather than
    on the identifier, which is why a chain whose identifiers are not ascending
    still pages in order — and why nothing here may assume they are.
    """
    created = _created(two_principals)
    second = _revised(
        two_principals,
        created.memory_id,
        expected_version=1,
        statement=SECOND_NOTE,
        idempotency_key="synthetic-history-page-0002",
    )
    third = _revised(
        two_principals,
        created.memory_id,
        expected_version=2,
        statement=THIRD_NOTE,
        idempotency_key="synthetic-history-page-0003",
    )

    reached: list[str] = []
    truncation: list[bool] = []
    cursor: str | None = None
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        for _ in range(4):
            versions, truncated = repository.history(
                created.memory_id, principal_id=PRINCIPAL_A, limit=1, after_version_id=cursor
            )
            reached.extend(version.memory_version_id for version in versions)
            truncation.append(truncated)
            if not truncated:
                break
            cursor = versions[-1].memory_version_id

    assert reached == [
        created.memory_version_id,
        second.memory_version_id,
        third.memory_version_id,
    ]
    assert len(reached) == len(set(reached)) == 3
    assert truncation == [True, True, False]


def test_a_list_cursor_naming_a_memory_outside_the_scope_is_refused(
    two_principals: Engine,
) -> None:
    """Refused, not silently restarted from the top.

    An unknown cursor answered with page one is indistinguishable from having
    reached the end of the list, so a caller paging a foreign or a mistyped
    identifier would be handed a page boundary that is not theirs and would have
    no way to tell. The foreign memory and the absent one are refused
    identically, which is the same equality the reads make: a refusal cannot be
    used to learn that an identifier names something.
    """
    _created(two_principals)
    theirs = _created(
        two_principals,
        principal_id=PRINCIPAL_B,
        subject_entity_id=FOREIGN_PERSON,
        statement="Bo Synthetic prefers email.",
        idempotency_key="synthetic-foreign-cursor-0001",
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        with pytest.raises(UnknownScopeError):
            repository.page_for_entity(
                DANA, principal_id=PRINCIPAL_A, limit=1, after_memory_id=theirs.memory_id
            )
        with pytest.raises(UnknownScopeError):
            repository.page_for_entity(
                DANA, principal_id=PRINCIPAL_A, limit=1, after_memory_id=ABSENT_MEMORY
            )
        # And the read still answers when the cursor is one this Principal holds,
        # so the refusals above are about the cursor rather than about the read.
        held = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=1)
    assert len(held.memories) == 1


def test_a_history_cursor_naming_a_version_of_another_memory_is_refused(
    two_principals: Engine,
) -> None:
    """A position in one chain is not a position in another.

    `history` looks the cursor up *within* the memory being read, so a version
    identifier belonging to a different memory — the caller's own or another
    Principal's — is refused rather than treated as "start again". Restarting
    would hand back version one under a cursor that claimed to be past it.
    """
    read = _created(two_principals, idempotency_key="synthetic-history-scope-0001")
    other = _created(
        two_principals,
        statement=SECOND_NOTE,
        idempotency_key="synthetic-history-scope-0002",
    )
    theirs = _created(
        two_principals,
        principal_id=PRINCIPAL_B,
        subject_entity_id=FOREIGN_PERSON,
        statement="Bo Synthetic prefers email.",
        idempotency_key="synthetic-history-scope-0003",
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        with pytest.raises(UnknownScopeError):
            repository.history(
                read.memory_id,
                principal_id=PRINCIPAL_A,
                limit=1,
                after_version_id=other.memory_version_id,
            )
        with pytest.raises(UnknownScopeError):
            repository.history(
                read.memory_id,
                principal_id=PRINCIPAL_A,
                limit=1,
                after_version_id=theirs.memory_version_id,
            )
        versions, truncated = repository.history(
            read.memory_id,
            principal_id=PRINCIPAL_A,
            limit=1,
            after_version_id=read.memory_version_id,
        )
    # Its own current version is a valid cursor, and there is nothing past it.
    assert versions == ()
    assert truncated is False


# --- the list filters, each with something it must exclude --------------------
#
# `kinds`, `as_of` and `context_entity_id` were supplied by callers and asserted
# by nobody: every test of this read either passed no filter or passed one and
# checked only that the answer was non-empty. Each test below stages rows that
# match and rows that do not, reads once without the filter as a control, and
# compares the filtered answer to an exact set — so deleting the predicate
# reddens the test rather than widening the answer unnoticed.


def test_a_kind_filter_returns_exactly_the_memories_of_those_kinds(
    two_principals: Engine,
) -> None:
    """Three kinds staged, one and then two asked for.

    The unfiltered read is the control: it establishes that all three are
    visible to this Principal at this subject, so the two filtered answers are
    the filter working rather than the fixture being thin. Asking for two kinds
    as well as one is what stops a predicate that always returns a single row
    from passing.
    """
    note = _created(
        two_principals,
        kind=MemoryKind.GENERAL_NOTE,
        statement=FIRST_NOTE,
        idempotency_key="synthetic-kind-note",
    )
    preference = _created(
        two_principals,
        kind=MemoryKind.COMMUNICATION_PREFERENCE,
        statement="Synthetic subject prefers a written summary first.",
        idempotency_key="synthetic-kind-preference",
    )
    follow_up = _created(
        two_principals,
        kind=MemoryKind.FOLLOW_UP_CONTEXT,
        statement="Ask about the graduation next time.",
        idempotency_key="synthetic-kind-follow-up",
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        unfiltered = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        one = repository.page_for_entity(
            DANA,
            principal_id=PRINCIPAL_A,
            limit=10,
            kinds=frozenset({MemoryKind.COMMUNICATION_PREFERENCE}),
        )
        two = repository.page_for_entity(
            DANA,
            principal_id=PRINCIPAL_A,
            limit=10,
            kinds=frozenset({MemoryKind.COMMUNICATION_PREFERENCE, MemoryKind.FOLLOW_UP_CONTEXT}),
        )
    assert _listed(unfiltered) == sorted(
        [note.memory_id, preference.memory_id, follow_up.memory_id]
    )
    assert _listed(one) == [preference.memory_id]
    assert _listed(two) == sorted([preference.memory_id, follow_up.memory_id])


def test_an_as_of_filter_returns_exactly_the_memories_in_effect_then(
    two_principals: Engine,
) -> None:
    """Effective dating is a claim about *when* something was true.

    A memory whose window has closed is not a memory the caller may be shown as
    current, and one whose window has not opened yet is not one they may be
    shown at all. Two probes rather than one, because a single probe is
    satisfied by a predicate that only reads `effective_to`: the closed window
    has to come back at a moment inside it, and the later window has to stay
    away until it opens. The undated memory is in both answers, which is the
    third case — no window means always in effect, and a filter that treated
    `NULL` as "not matching" would hide every ordinary note.
    """
    closed = _created(
        two_principals,
        statement="Synthetic subject was on the north dock rotation.",
        idempotency_key="synthetic-as-of-closed",
        effective_from=WINDOW_OPENED,
        effective_to=WINDOW_CLOSED,
    )
    later = _created(
        two_principals,
        statement="Synthetic subject moved to the weekday roster.",
        idempotency_key="synthetic-as-of-later",
        effective_from=SECOND_WINDOW_OPENED,
    )
    undated = _created(
        two_principals,
        statement=FIRST_NOTE,
        idempotency_key="synthetic-as-of-undated",
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        unfiltered = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        inside = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, as_of=INSIDE_THE_FIRST_WINDOW
        )
        after = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, as_of=AFTER_BOTH_WINDOWS_OPENED
        )
    assert _listed(unfiltered) == sorted([closed.memory_id, later.memory_id, undated.memory_id])
    assert _listed(inside) == sorted([closed.memory_id, undated.memory_id])
    assert _listed(after) == sorted([later.memory_id, undated.memory_id])


def test_a_context_filter_returns_exactly_the_memories_linked_to_that_entity(
    two_principals: Engine,
) -> None:
    """One read answers "what do I know about Dana in the context of Riverside".

    Two different targets are asked for rather than one, so a predicate that
    matched any link at all — or the first link it found — is refused by the
    second answer. The unlinked memory is the third case: it is in the
    unfiltered read and in neither filtered one.
    """
    riverside = _created(
        two_principals,
        statement="Synthetic subject runs the Riverside stand-up.",
        idempotency_key="synthetic-context-riverside",
        context_links=({"target_type": "entity", "target_id": RIVERSIDE, "role": "applies_in"},),
    )
    eli = _created(
        two_principals,
        statement="Synthetic subject hands over to Eli on Fridays.",
        idempotency_key="synthetic-context-eli",
        context_links=({"target_type": "entity", "target_id": ELI, "role": "applies_in"},),
    )
    unlinked = _created(
        two_principals,
        statement=FIRST_NOTE,
        idempotency_key="synthetic-context-none",
    )
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        unfiltered = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        at_riverside = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, context_entity_id=RIVERSIDE
        )
        with_eli = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, context_entity_id=ELI
        )
    staged = sorted([riverside.memory_id, eli.memory_id, unlinked.memory_id])
    assert _listed(unfiltered) == staged
    assert _listed(at_riverside) == [riverside.memory_id]
    assert _listed(with_eli) == [eli.memory_id]


# --- the create path asks the domain whether the kind suits the subject -------

#: The Person-only kinds, written out rather than derived from the domain's own
#: frozenset, so admitting a kind to it is a decision — and so the parametrized
#: test identifiers below are stable. The equality that pays for writing them
#: out is the first test in this section.
PERSON_ONLY_ARGUMENTS: Final = (
    MemoryKind.PERSONAL_DETAIL,
    MemoryKind.IMPORTANT_DATE,
    MemoryKind.INTEREST,
)


def test_the_person_only_kinds_asserted_below_are_all_of_them() -> None:
    """No database. A fourth Person-only kind would otherwise go untested."""
    assert set(PERSON_ONLY_ARGUMENTS) == PERSON_ONLY_KINDS


@pytest.mark.parametrize("kind", PERSON_ONLY_ARGUMENTS, ids=lambda kind: kind.value)
def test_a_person_only_kind_is_refused_for_a_subject_that_is_not_a_person(
    two_principals: Engine, kind: MemoryKind
) -> None:
    """`check_kind_permits_subject` is called by the create path, not merely by DOM.

    The domain proves the function refuses; nothing proved that `_create`
    consults it, so deleting the call left the rule true and unenforced — and a
    birthday could be recorded against a project. The subject is Riverside, the
    project A already holds, rather than a new fixture entity: the plane's own
    fixture already contains a non-Person subject, and adding a second would
    only be a second thing to keep in step.

    The row counts are read inside the failed transaction and again after it,
    the shape the other refusals here use, so the refusal is shown to have come
    before any insert rather than after one that was rolled back.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(MemoryKindNotPermittedError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=RIVERSIDE,
                    statement="Synthetic note that describes a person, not a project.",
                    idempotency_key=f"synthetic-person-only-{kind.value}",
                    kind=kind,
                ),
            )
        assert _counts(connection) == before
    with two_principals.connect() as connection:
        assert _counts(connection) == before


def test_a_kind_that_is_not_person_only_is_admitted_against_a_project(
    two_principals: Engine,
) -> None:
    """The other half, so the refusals above are not passing by refusing everything.

    Without this, a create path that raised for every non-Person subject — or
    for every write to Riverside — would satisfy all three parametrized cases
    while making it impossible to note anything about a project at all.
    """
    receipt = _created(
        two_principals,
        subject_entity_id=RIVERSIDE,
        kind=MemoryKind.GENERAL_NOTE,
        statement="Riverside Synthetic runs its stand-up on Tuesdays.",
        idempotency_key="synthetic-project-note",
    )
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.memory.subject_entity_id == RIVERSIDE
    assert detail.memory.memory_kind is MemoryKind.GENERAL_NOTE


def test_a_revision_that_does_not_restate_pinned_keeps_the_pin(
    two_principals: Engine,
) -> None:
    """Correcting the wording of a pinned memory must not unpin it.

    It did. `pinned` was `bool = False` on the revise command and was written
    into the aggregate unconditionally, so a caller who fixed a typo destroyed a
    presentation choice they never mentioned — and the published tool
    description gave a model no reason to suspect it. Absent now means keep;
    `kind` two fields away has behaved that way all along.
    """
    created = _created(two_principals, pinned=True)
    with two_principals.begin() as connection:
        _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.REVISE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-revise-keeps-pin",
                statement=SECOND_NOTE,
            ),
        )
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            created.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.memory.pinned is True
    assert detail.current_version.statement == SECOND_NOTE


def test_a_revision_that_states_pinned_false_unpins(two_principals: Engine) -> None:
    """The other half, so "absent keeps it" is not satisfied by ignoring the field.

    Without this, a repository that never wrote `pinned` on a revise at all
    would pass the test above, and unpinning would have become impossible.
    """
    created = _created(two_principals, pinned=True)
    with two_principals.begin() as connection:
        _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.REVISE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-revise-unpins",
                statement=SECOND_NOTE,
                pinned=False,
            ),
        )
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            created.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.memory.pinned is False


def test_the_server_refuses_a_sensitivity_stored_below_its_floor(
    two_principals: Engine,
) -> None:
    """The classification floor is defence in depth, and depth has to be tested.

    `classification_floor_for` is proven at the domain layer, but RM-AC-006 and
    RM-P-AC-006 both name the database CHECK as their evidence — and deleting
    `a_sensitivity_memory_is_at_least_restricted` from `tables.py` failed
    nothing. Worse, the migration copies the live table objects rather than
    restating them, and this constraint is not one of the eighteen it freezes,
    so removing it would silently change what an already-merged revision creates
    on a fresh database.

    A raw INSERT rather than a repository call, for the reason the
    cloud-eligibility test beside it uses one: the domain refuses this before
    any statement is issued, so the only way to ask the *server* is to go around
    the domain.
    """
    created = _created(two_principals)
    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            text(
                "INSERT INTO knowledge.relationship_memory_versions ("
                "memory_version_id, memory_id, principal_id, version_number, "
                "statement_text, statement_sha256, memory_kind, authority, "
                "classification, cloud_eligible, created_by_actor, recorded_at, "
                "idempotency_key, correlation_id) VALUES ("
                ":version_id, :memory_id, :principal_id, 99, :statement, :digest, "
                "'sensitivity', 'user_authored_private_note', 'private_local', false, "
                "'user', now(), :key, :correlation_id)"
            ),
            {
                "version_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                "memory_id": created.memory_id,
                "principal_id": PRINCIPAL_A,
                "statement": FIRST_NOTE,
                "digest": statement_digest(FIRST_NOTE),
                "key": "synthetic-floor-probe",
                "correlation_id": issue_identifier(IdKind.CORRELATION),
            },
        )
    assert "a_sensitivity_memory_is_at_least_restricted" in str(refused.value)


def test_a_foreign_memory_reads_exactly_as_an_absent_one(two_principals: Engine) -> None:
    """Not "is also empty": the same answer, asserted as an equality.

    A refusal that differed from an absence — a different error, a different
    shape, a message — would let a caller learn that an identifier names
    something another Principal holds.
    """
    theirs = _created(
        two_principals,
        principal_id=PRINCIPAL_B,
        subject_entity_id=FOREIGN_PERSON,
        statement="Bo Synthetic prefers email.",
        idempotency_key="synthetic-foreign-0001",
    )
    mine = _created(two_principals, idempotency_key="synthetic-mine-0001")
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        held = repository.detail(mine.memory_id, principal_id=PRINCIPAL_A)
        foreign = repository.detail(theirs.memory_id, principal_id=PRINCIPAL_A)
        absent = repository.detail(ABSENT_MEMORY, principal_id=PRINCIPAL_A)
        foreign_history = repository.history(theirs.memory_id, principal_id=PRINCIPAL_A, limit=10)
        absent_history = repository.history(ABSENT_MEMORY, principal_id=PRINCIPAL_A, limit=10)
        foreign_page = repository.page_for_entity(
            FOREIGN_PERSON, principal_id=PRINCIPAL_A, limit=10
        )
        absent_page = repository.page_for_entity(ABSENT_ENTITY, principal_id=PRINCIPAL_A, limit=10)
    assert held is not None, "the fixture wrote nothing, so nothing below is evidence"
    assert foreign is None
    assert foreign == absent
    assert foreign_history == absent_history
    assert foreign_page == absent_page


def test_a_create_naming_another_principals_subject_is_refused_before_any_row(
    two_principals: Engine,
) -> None:
    """A foreign-key constraint proves a row exists, never that it is yours.

    The identifiers are globally unique, so ownership of the subject has to be
    proven by a scoped read before the insert — and the counts show it was.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(UnknownScopeError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=FOREIGN_PERSON,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-foreign-subject-0001",
                ),
            )
        assert _counts(connection) == before
    with two_principals.connect() as connection:
        assert _counts(connection) == before


def test_a_context_link_naming_another_principals_entity_is_refused(
    two_principals: Engine,
) -> None:
    """Every context target is proven to belong to the acting Principal.

    A link is a validated edge, not a free identifier field: without the check a
    memory of A's could name B's project and disclose that it exists.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(UnknownScopeError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=DANA,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-foreign-link-0001",
                    context_links=(
                        {
                            "target_type": "entity",
                            "target_id": FOREIGN_PERSON,
                            "role": "applies_in",
                        },
                    ),
                ),
            )
        assert _counts(connection) == before


def test_a_context_link_naming_the_acting_principals_own_entity_is_stored(
    two_principals: Engine,
) -> None:
    """The other half, so the refusal above is not passing by refusing every link."""
    receipt = _created(
        two_principals,
        idempotency_key="synthetic-own-link-0001",
        context_links=({"target_type": "entity", "target_id": RIVERSIDE, "role": "applies_in"},),
    )
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert [(link.target_type.value, link.target_id) for link in detail.context_links] == [
        ("entity", RIVERSIDE)
    ]


def test_a_write_to_a_merged_away_subject_is_refused_and_names_the_survivor(
    two_principals: Engine,
) -> None:
    """Following the redirect would rebind the note to a different identity.

    A deliberate annotation about a historical identity is a different statement
    from one about the current person, so the write is refused and the caller is
    told where the subject went rather than silently retargeted.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(MergedSubjectError) as refusal:
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=OLD_DANA,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-merged-0001",
                ),
            )
        assert _counts(connection) == before
    assert refusal.value.canonical_entity_id == DANA


# --- the migration ------------------------------------------------------------


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
                {"schema": SCHEMA},
            )
        }


def test_the_revision_is_on_one_unbranched_chain_above_the_one_it_revises() -> None:
    """No database. A branched chain is an upgrade with two possible outcomes."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert script.get_revision(MEMORY_REVISION).down_revision == PREVIOUS_REVISION


@pytest.mark.migration_edge
def test_the_plane_migrates_empty_to_head_and_back_to_head_again(
    empty_database_url: str,
) -> None:
    """Empty to head, head to the previous revision, and up again.

    The downgrade half is the one that matters: it drops two triggers, a
    function, eight tables and restates two closed sets, and a downgrade that
    left residue would make the next upgrade fail on a name that already exists.
    Asserted by running the upgrade a second time rather than by inspecting what
    the downgrade left.
    """
    engine = create_database_engine(empty_database_url)
    try:
        assert _tables(engine).isdisjoint(MEMORY_TABLES), "the database was not empty"
        command.upgrade(_config(), "head")
        assert _tables(engine).issuperset(MEMORY_TABLES)
        command.downgrade(_config(), PREVIOUS_REVISION)
        assert _tables(engine).isdisjoint(MEMORY_TABLES)
        command.upgrade(_config(), "head")
        assert _tables(engine).issuperset(MEMORY_TABLES)
    finally:
        engine.dispose()


def test_the_append_only_trigger_exists_on_the_version_table(migrated_engine: Engine) -> None:
    """Named rather than inferred from behaviour, so a rename is visible here."""
    with migrated_engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :table AND NOT t.tgisinternal"
                ),
                {"schema": SCHEMA, "table": "relationship_memory_versions"},
            )
        }
    assert "relationship_memory_versions_are_append_only" in triggers


def test_the_server_refuses_a_cloud_eligible_version(two_principals: Engine) -> None:
    """The domain refuses it too. This is the copy a repair script cannot skip."""
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "(memory_version_id, memory_id, principal_id, version_number, "
                    "statement_text, statement_sha256, memory_kind, authority, "
                    "classification, cloud_eligible, created_by_actor, recorded_at, "
                    "prior_version_id, idempotency_key, correlation_id) VALUES "
                    "(:version_id, :memory_id, :principal_id, 2, :statement, :digest, "
                    "'general_note', 'user_authored_private_note', 'private_local', true, "
                    "'user', :recorded_at, :prior, 'synthetic-cloud-0001', :correlation)"
                ),
                {
                    "version_id": "memver_cloud0001cloud0001",
                    "memory_id": receipt.memory_id,
                    "principal_id": PRINCIPAL_A,
                    "statement": SECOND_NOTE,
                    "digest": statement_digest(SECOND_NOTE),
                    "recorded_at": LATER,
                    "prior": receipt.memory_version_id,
                    "correlation": issue_identifier(IdKind.CORRELATION),
                },
            )
