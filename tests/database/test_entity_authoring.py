"""The governed entity writes against a real PostgreSQL server (`WP-RI-A-02`).

`tests/unit/test_entity_authoring.py` drives the in-memory double and proves the
*contract*. This drives the SQL and proves the contract holds where it has to:
against a real partial unique index, real composite foreign keys, a real guarded
`UPDATE` whose row count decides, and two sessions racing for one address.

Four claims carry this file, and each is the one a fake cannot make.

**A refused write leaves nothing behind.** The guarded `UPDATE` is the first
write of every operation that names an existing entity, and its row count is read
before any other row is written -- so a stale expectation has no successor to
roll back. Asserted by counting rows in every table the write touches, before and
after, rather than by reading the one the test happened to think of.

**One address is at most one entity's current identity, and the index says so.**
The double spells that rule out in Python; here it is
`an_active_external_identifier_binding_is_unique` arbitrating a real
`ON CONFLICT`, over a real partial predicate the server has to prove implies the
index's.

**A foreign row is indistinguishable from an absent one**, in both directions:
the refusal is the same class carrying the same message, and the write is refused
before it is written rather than written and filtered later.

**Two sessions cannot both claim one address.** The concurrency tests below open
a second connection and commit inside the window the first is working in, which
is the interleaving `BIND_ATTEMPTS` exists to bound.

**Every test in this file writes `knowledge.entity_mutation_events`, and that
table's `capability_is_known`-equivalent lives on `audit_events` rather than
here** -- so these passed even before the vocabulary admitted them. What did not
was any test driving one of these capabilities through
`ApplicationService.invoke`, because the audit row recording the invocation
names a capability the stored `capability_is_known` CHECK had never heard of.
Phase A's single revision `823e23b6cc63` admits this package's `entities.` names
and the `entity_authoring` purpose, so that path is open at head;
`tests/database/test_entity_directed_writes.py` is where it is driven.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from my_pa.application.entity_authoring import EntityAuthoringService, NamedValue
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.authoring import (
    AmbiguousEntityError,
    CallerNamespace,
    ConflictedIdentifierError,
    DuplicateEntityFactError,
    EntityEvidenceError,
    EntityIdempotencyConflictError,
    HistoricalEntityError,
    StaleEntityVersionError,
)
from my_pa.domain.relationship.entity import (
    AliasType,
    Entity,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Distinct from every other database-tier fixture's disposable database, so
#: this suite can run alongside them without one dropping the database another
#: is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_authoring_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

WHEN: Final = datetime(2026, 8, 20, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 21, 12, tzinfo=UTC)

#: Every table one governed write can touch. Counted whole before and after a
#: refused write, because "nothing was written" is a claim about all of them and
#: a test that counted one would pass over a partial write into another.
TOUCHED_TABLES: Final = (
    "entities",
    "entity_aliases",
    "entity_external_identifiers",
    "entity_mutation_events",
    "entity_fact_evidence_links",
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def an_entity(
    entity_id: str,
    principal_id: str,
    display_name: str,
    *,
    entity_type: EntityType = EntityType.PERSON,
    status: EntityStatus = EntityStatus.ACTIVE,
    archived_from: EntityStatus | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=status,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
        archived_from_status=archived_from,
    )


def _service() -> EntityAuthoringService:
    return EntityAuthoringService()


def _context() -> dict[str, object]:
    return {
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": LATER,
    }


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608
                ).scalar_one()
            )
            for table in TOUCHED_TABLES
        }


def _create(connection: Connection, principal_id: str, display_name: str, **kwargs: object) -> str:
    """One entity through the governed path, and the identifier the server issued."""
    admission = _service().create(
        SqlEntityRepository(connection),
        principal_id=principal_id,
        entity_type=kwargs.pop("entity_type", EntityType.PERSON),  # type: ignore[arg-type]
        display_name=display_name,
        aliases=kwargs.pop("aliases", ()),  # type: ignore[arg-type]
        identifiers=kwargs.pop("identifiers", ()),  # type: ignore[arg-type]
        reason="A synthetic creation.",
        idempotency_key=str(kwargs.pop("idempotency_key", f"create-{display_name}")),
        **_context(),  # type: ignore[arg-type]
    )
    return admission.receipt.entity_id


# --- the create: what the server owns, and what it refuses -------------------


def test_a_create_writes_the_entity_its_children_and_one_ledger_row(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            aliases=(NamedValue("nickname", "Sar"),),
            identifiers=(NamedValue("email", "Sarah.Chen@Example.Invalid"),),
        )
    counts = _counts(migrated_engine)
    assert counts["entities"] == 1
    assert counts["entity_aliases"] == 1
    assert counts["entity_external_identifiers"] == 1
    assert counts["entity_mutation_events"] == 1
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT capability, record_family, record_id, prior_version, new_version, "  # noqa: S608
                f"authority, actor_class, reason, receipt_id "
                f"FROM {SCHEMA}.entity_mutation_events"
            )
        ).one()
        stored = SqlEntityRepository(connection).get(PRINCIPAL_A, entity_id)
    assert row.capability == "entities.create"
    assert row.record_family == "entity"
    assert row.record_id == entity_id
    assert row.prior_version is None
    assert row.new_version == 1
    # Server-owned throughout, and there is no request field for either.
    assert row.authority == "user_confirmed_assertion"
    assert row.actor_class == "user"
    # Null, on the whole plane. `receipt_id` points at a separate receipt record
    # and this build keeps none, so the ledger row is what the result hands back
    # under that name -- see `_record_mutation`.
    assert row.receipt_id is None
    assert stored is not None
    assert stored.canonical_name == normalize_name("Sarah Chen")
    assert stored.version == 1


def test_a_create_refuses_an_address_another_entity_currently_holds(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
    before = _counts(migrated_engine)
    with pytest.raises(ConflictedIdentifierError), migrated_engine.begin() as connection:
        _create(
            connection,
            PRINCIPAL_A,
            "Sara Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
    assert _counts(migrated_engine) == before


def test_a_create_of_a_name_that_exists_with_no_identity_is_ambiguous(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _create(connection, PRINCIPAL_A, "Sarah Chen")
    before = _counts(migrated_engine)
    with pytest.raises(AmbiguousEntityError), migrated_engine.begin() as connection:
        _create(connection, PRINCIPAL_A, "Sarah Chen", idempotency_key="second")
    assert _counts(migrated_engine) == before


def test_another_principals_namesake_is_not_a_duplicate(migrated_engine: Engine) -> None:
    """Duplicate resolution reads one partition, so the other one's Sarah is invisible."""
    with migrated_engine.begin() as connection:
        _create(connection, PRINCIPAL_B, "Sarah Chen")
    with migrated_engine.begin() as connection:
        mine = _create(connection, PRINCIPAL_A, "Sarah Chen", idempotency_key="mine")
    assert mine


# --- optimistic concurrency: nothing is written on a stale expectation -------


def test_a_stale_expected_version_writes_nothing_at_all(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chenn")
    before = _counts(migrated_engine)
    with pytest.raises(StaleEntityVersionError), migrated_engine.begin() as connection:
        _service().update(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=9,
            display_name=None,
            # A canonical correction, so a partial write would leave a
            # `former_name` alias behind and the count below would find it.
            canonical_name="Sarah Chen",
            status=None,
            reason="A misspelling.",
            idempotency_key="stale-update",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before


def test_a_stale_child_version_writes_nothing_even_though_the_entity_was_current(
    migrated_engine: Engine,
) -> None:
    """The guard on the entity ran first and its effect is still rolled back.

    This is the case a fake cannot make: the entity `UPDATE` really did execute
    before the child guard refused, and what makes the plane correct is that the
    transaction takes it back.
    """
    with migrated_engine.begin() as connection:
        entity_id = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
        identifier_id = _only_identifier(connection, PRINCIPAL_A, entity_id)
    before = _counts(migrated_engine)
    with pytest.raises(StaleEntityVersionError), migrated_engine.begin() as connection:
        _service().retire_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=7,
            reason="They left.",
            idempotency_key="stale-child",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before
    with migrated_engine.connect() as connection:
        held = SqlEntityRepository(connection).get(PRINCIPAL_A, entity_id)
    assert held is not None
    assert held.version == 1


# --- the partial unique, arbitrated by the server ----------------------------


def test_one_address_is_at_most_one_entitys_current_identity(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        holder = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
        other = _create(connection, PRINCIPAL_A, "Sara Chen", idempotency_key="other")
    assert holder != other
    with pytest.raises(ConflictedIdentifierError), migrated_engine.begin() as connection:
        _service().bind_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=other,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="sarah@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="cross-bind",
            **_context(),  # type: ignore[arg-type]
        )


def test_an_address_retired_from_one_entity_may_be_reissued_to_another(
    migrated_engine: Engine,
) -> None:
    """The whole reason the unique is partial: the historical row is kept."""
    with migrated_engine.begin() as connection:
        first = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "shared@example.invalid"),),
        )
        identifier_id = _only_identifier(connection, PRINCIPAL_A, first)
        _service().retire_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=first,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=1,
            reason="They left.",
            idempotency_key="reissue-retire",
            **_context(),  # type: ignore[arg-type]
        )
        second = _create(connection, PRINCIPAL_A, "Sara Chen", idempotency_key="second")
        _service().bind_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=second,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="shared@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason="The address was reissued.",
            idempotency_key="reissue-bind",
            **_context(),  # type: ignore[arg-type]
        )
    with migrated_engine.connect() as connection:
        states = (
            connection.execute(
                text(
                    f"SELECT state FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                    "ORDER BY state"
                )
            )
            .scalars()
            .all()
        )
    assert sorted(states) == ["active", "retired"]


def test_a_supersede_writes_the_replacement_and_points_the_old_row_at_it(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
        identifier_id = _only_identifier(connection, PRINCIPAL_A, entity_id)
        admission = _service().supersede_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="s.chen@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason="The address changed.",
            idempotency_key="supersede",
            **_context(),  # type: ignore[arg-type]
        )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT state, superseded_by_identifier_id, version "  # noqa: S608
                f"FROM {SCHEMA}.entity_external_identifiers WHERE identifier_id = :id"
            ),
            {"id": identifier_id},
        ).one()
    assert row.state == "superseded"
    assert row.superseded_by_identifier_id == admission.receipt.child_id
    assert row.version == 2


# --- idempotency, against the real unique constraint -------------------------


def test_a_replayed_key_answers_from_the_ledger_and_writes_nothing(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        first = _service().create(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_type=EntityType.PERSON,
            display_name="Sarah Chen",
            aliases=(),
            identifiers=(),
            reason=None,
            idempotency_key="replay",
            **_context(),  # type: ignore[arg-type]
        )
    after_first = _counts(migrated_engine)
    with migrated_engine.begin() as connection:
        second = _service().create(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_type=EntityType.PERSON,
            display_name="Sarah Chen",
            aliases=(),
            identifiers=(),
            reason=None,
            idempotency_key="replay",
            **_context(),  # type: ignore[arg-type]
        )
    assert first.created
    assert not second.created
    assert second.receipt.entity_id == first.receipt.entity_id
    assert second.receipt.event_id == first.receipt.event_id
    assert _counts(migrated_engine) == after_first


def test_a_key_reused_with_a_different_payload_is_refused_by_the_constraint(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _create(connection, PRINCIPAL_A, "Sarah Chen", idempotency_key="reused")
    before = _counts(migrated_engine)
    with pytest.raises(EntityIdempotencyConflictError), migrated_engine.begin() as connection:
        _create(connection, PRINCIPAL_A, "Someone Else", idempotency_key="reused")
    assert _counts(migrated_engine) == before


def test_the_same_key_held_by_two_principals_is_two_writes(migrated_engine: Engine) -> None:
    """The unique spans the Principal, so one caller's key says nothing about another's."""
    with migrated_engine.begin() as connection:
        mine = _create(connection, PRINCIPAL_A, "Sarah Chen", idempotency_key="shared")
    with migrated_engine.begin() as connection:
        theirs = _create(connection, PRINCIPAL_B, "Sarah Chen", idempotency_key="shared")
    assert mine != theirs
    assert _counts(migrated_engine)["entity_mutation_events"] == 2


# --- the partition ------------------------------------------------------------


def test_a_foreign_entity_is_refused_exactly_as_an_absent_one(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        theirs = _create(connection, PRINCIPAL_B, "Their Person")

    def archive(entity_id: str, key: str) -> None:
        with migrated_engine.begin() as connection:
            _service().archive(
                SqlEntityRepository(connection),
                principal_id=PRINCIPAL_A,
                entity_id=entity_id,
                expected_version=1,
                reason="A synthetic withdrawal.",
                idempotency_key=key,
                **_context(),  # type: ignore[arg-type]
            )

    with pytest.raises(UnknownScopeError) as foreign:
        archive(theirs, "foreign")
    with pytest.raises(UnknownScopeError) as absent:
        archive(issue_identifier(IdKind.ENTITY), "absent")
    assert str(foreign.value) == str(absent.value)


def test_a_write_never_lands_in_another_principals_partition(migrated_engine: Engine) -> None:
    """The composite `(entity_id, principal_id)` foreign key, from the write side."""
    with migrated_engine.begin() as connection:
        theirs = _create(connection, PRINCIPAL_B, "Their Person")
    before = _counts(migrated_engine)
    with pytest.raises(UnknownScopeError), migrated_engine.begin() as connection:
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=theirs,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Theirs",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="cross-alias",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before


# --- lifecycle ---------------------------------------------------------------


def test_an_archive_records_the_status_the_restore_returns_to(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        entity_id = issue_identifier(IdKind.ENTITY)
        repository.create(
            PRINCIPAL_A,
            an_entity(entity_id, PRINCIPAL_A, "Sarah Chen", status=EntityStatus.HISTORICAL),
        )
        _service().archive(
            repository,
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            reason="A synthetic withdrawal.",
            idempotency_key="archive",
            **_context(),  # type: ignore[arg-type]
        )
    with migrated_engine.begin() as connection:
        restored = _service().restore(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=2,
            reason="A synthetic restoration.",
            idempotency_key="restore",
            **_context(),  # type: ignore[arg-type]
        )
    assert restored.receipt.entity_status is EntityStatus.HISTORICAL
    with migrated_engine.connect() as connection:
        held = SqlEntityRepository(connection).get(PRINCIPAL_A, entity_id)
    assert held is not None
    assert held.status is EntityStatus.HISTORICAL
    assert held.archived_from_status is None


def test_a_merged_redirect_cannot_be_archived(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        survivor = issue_identifier(IdKind.ENTITY)
        merged = issue_identifier(IdKind.ENTITY)
        repository.create(PRINCIPAL_A, an_entity(survivor, PRINCIPAL_A, "Sarah Chen"))
        repository.create(PRINCIPAL_A, an_entity(merged, PRINCIPAL_A, "Sarah Chenn"))
        repository.redirect_entity(PRINCIPAL_A, merged, survivor)
    before = _counts(migrated_engine)
    with pytest.raises(HistoricalEntityError) as refusal, migrated_engine.begin() as connection:
        _service().archive(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=merged,
            expected_version=1,
            reason="A synthetic withdrawal.",
            idempotency_key="merged-archive",
            **_context(),  # type: ignore[arg-type]
        )
    assert survivor in str(refusal.value)
    assert _counts(migrated_engine) == before


def test_a_canonical_correction_leaves_the_prior_name_matchable(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chenn")
    with migrated_engine.begin() as connection:
        _service().update(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            display_name=None,
            canonical_name="Sarah Chen",
            status=None,
            reason="A misspelling.",
            idempotency_key="rename",
            **_context(),  # type: ignore[arg-type]
        )
    with migrated_engine.connect() as connection:
        rows = SqlEntityRepository(connection).aliases(PRINCIPAL_A, entity_id)
        matched = SqlEntityRepository(connection).entities_by_alias(
            PRINCIPAL_A, normalize_name("Sarah Chenn")
        )
    assert [alias.alias_type for alias in rows] == [AliasType.FORMER_NAME]
    assert [entity.entity_id for entity, _ in matched] == [entity_id]


# --- evidence ----------------------------------------------------------------


def test_a_cited_span_that_is_not_this_principals_is_refused(migrated_engine: Engine) -> None:
    """`capture_spans` has no partition, so the join to the owning capture is the check."""
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chen")
    before = _counts(migrated_engine)
    with pytest.raises(EntityEvidenceError), migrated_engine.begin() as connection:
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(issue_identifier(IdKind.SPAN),),
            reason=None,
            idempotency_key="bad-evidence",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before


# --- paged child reads --------------------------------------------------------


def test_a_child_listing_pages_by_keyset_and_discloses_its_bound(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chen")
        repository = SqlEntityRepository(connection)
        for index in range(3):
            _service().add_alias(
                repository,
                principal_id=PRINCIPAL_A,
                entity_id=entity_id,
                expected_version=index + 1,
                alias_type=AliasType.NICKNAME,
                display_value=f"Sar {index}",
                effective_from=None,
                effective_to=None,
                evidence=(),
                reason=None,
                idempotency_key=f"alias-{index}",
                **_context(),  # type: ignore[arg-type]
            )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        first = repository.alias_page(entity_id, principal_id=PRINCIPAL_A, limit=2)
        second = repository.alias_page(
            entity_id,
            principal_id=PRINCIPAL_A,
            limit=2,
            after_alias_id=first.records[-1].alias_id,
        )
    assert first.is_truncated
    assert len(first.records) == 2
    assert not second.is_truncated
    assert len(second.records) == 1
    assert {alias.alias_id for alias in first.records}.isdisjoint(
        {alias.alias_id for alias in second.records}
    )


def test_a_child_cursor_naming_another_principals_record_is_refused(
    migrated_engine: Engine,
) -> None:
    """Refused rather than silently emptied: an empty page reads as the end."""
    with migrated_engine.begin() as connection:
        mine = _create(connection, PRINCIPAL_A, "Sarah Chen")
        theirs = _create(connection, PRINCIPAL_B, "Their Person")
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_B,
            entity_id=theirs,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Theirs",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="their-alias",
            **_context(),  # type: ignore[arg-type]
        )
        foreign_alias = _only_alias(connection, PRINCIPAL_B, theirs)
    with pytest.raises(UnknownScopeError), migrated_engine.connect() as connection:
        SqlEntityRepository(connection).alias_page(
            mine, principal_id=PRINCIPAL_A, limit=10, after_alias_id=foreign_alias
        )


def test_a_state_filter_separates_a_retired_binding_from_a_current_one(
    migrated_engine: Engine,
) -> None:
    from my_pa.domain.relationship.entity import IdentifierState

    with migrated_engine.begin() as connection:
        entity_id = _create(
            connection,
            PRINCIPAL_A,
            "Sarah Chen",
            identifiers=(NamedValue("email", "sarah@example.invalid"),),
        )
        identifier_id = _only_identifier(connection, PRINCIPAL_A, entity_id)
        _service().retire_identifier(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            identifier_id=identifier_id,
            expected_identifier_version=1,
            reason="They left.",
            idempotency_key="retire",
            **_context(),  # type: ignore[arg-type]
        )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        active = repository.identifier_page(
            entity_id,
            principal_id=PRINCIPAL_A,
            limit=10,
            states=frozenset({IdentifierState.ACTIVE}),
        )
        retired = repository.identifier_page(
            entity_id,
            principal_id=PRINCIPAL_A,
            limit=10,
            states=frozenset({IdentifierState.RETIRED}),
        )
    assert active.records == ()
    assert [row.identifier_id for row in retired.records] == [identifier_id]


# --- concurrency --------------------------------------------------------------


def test_two_sessions_cannot_both_claim_one_address(migrated_engine: Engine) -> None:
    """The second is refused by the index rather than by a check either one made.

    Both connections read a world in which nobody holds the address, which is
    the interleaving a pre-read alone cannot survive.
    """
    with migrated_engine.begin() as connection:
        first = _create(connection, PRINCIPAL_A, "Sarah Chen")
        second = _create(connection, PRINCIPAL_A, "Sara Chen", idempotency_key="second")

    left = migrated_engine.connect()
    right = migrated_engine.connect()
    try:
        left_transaction = left.begin()
        right_transaction = right.begin()
        _service().bind_identifier(
            SqlEntityRepository(left),
            principal_id=PRINCIPAL_A,
            entity_id=first,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="contested@example.invalid",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="left",
            **_context(),  # type: ignore[arg-type]
        )
        left_transaction.commit()
        with pytest.raises(ConflictedIdentifierError):
            _service().bind_identifier(
                SqlEntityRepository(right),
                principal_id=PRINCIPAL_A,
                entity_id=second,
                expected_version=1,
                namespace=CallerNamespace.EMAIL,
                display_value="contested@example.invalid",
                effective_from=None,
                effective_to=None,
                evidence=(),
                reason=None,
                idempotency_key="right",
                **_context(),  # type: ignore[arg-type]
            )
        right_transaction.rollback()
    finally:
        left.close()
        right.close()
    with migrated_engine.connect() as connection:
        held = (
            connection.execute(
                text(
                    f"SELECT entity_id FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                    "WHERE state = 'active'"
                )
            )
            .scalars()
            .all()
        )
    assert held == [first]


def test_a_second_session_that_advanced_the_version_refuses_the_first(
    migrated_engine: Engine,
) -> None:
    """The guarded `UPDATE`, raced. Only one of two equal expectations may win."""
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chen")
    with migrated_engine.begin() as connection:
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="first-writer",
            **_context(),  # type: ignore[arg-type]
        )
    before = _counts(migrated_engine)
    with pytest.raises(StaleEntityVersionError), migrated_engine.begin() as connection:
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            alias_type=AliasType.INITIALS,
            display_value="SC",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="second-writer",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before


def test_a_duplicate_alias_is_refused_by_the_partial_unique(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        entity_id = _create(connection, PRINCIPAL_A, "Sarah Chen")
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=1,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="alias-a",
            **_context(),  # type: ignore[arg-type]
        )
    before = _counts(migrated_engine)
    with pytest.raises(DuplicateEntityFactError), migrated_engine.begin() as connection:
        _service().add_alias(
            SqlEntityRepository(connection),
            principal_id=PRINCIPAL_A,
            entity_id=entity_id,
            expected_version=2,
            alias_type=AliasType.NICKNAME,
            display_value="Sar",
            effective_from=None,
            effective_to=None,
            evidence=(),
            reason=None,
            idempotency_key="alias-b",
            **_context(),  # type: ignore[arg-type]
        )
    assert _counts(migrated_engine) == before


def test_two_entities_may_carry_one_active_alias(migrated_engine: Engine) -> None:
    """Cross-entity name collisions are legal, and the index says so.

    A schema that refused this would force one of two real people into the
    other, which is the false join this plane exists to avoid.
    """
    with migrated_engine.begin() as connection:
        first = _create(connection, PRINCIPAL_A, "Sarah Chen")
        second = _create(connection, PRINCIPAL_A, "Sara Chen", idempotency_key="second")
        for index, entity_id in enumerate((first, second)):
            _service().add_alias(
                SqlEntityRepository(connection),
                principal_id=PRINCIPAL_A,
                entity_id=entity_id,
                expected_version=1,
                alias_type=AliasType.NICKNAME,
                display_value="Sar",
                effective_from=None,
                effective_to=None,
                evidence=(),
                reason=None,
                idempotency_key=f"shared-alias-{index}",
                **_context(),  # type: ignore[arg-type]
            )
    assert _counts(migrated_engine)["entity_aliases"] == 2


def _only_identifier(connection: Connection, principal_id: str, entity_id: str) -> str:
    identifiers = SqlEntityRepository(connection).external_identifiers(principal_id, entity_id)
    assert len(identifiers) == 1
    return identifiers[0].identifier_id


def _only_alias(connection: Connection, principal_id: str, entity_id: str) -> str:
    aliases = SqlEntityRepository(connection).aliases(principal_id, entity_id)
    assert len(aliases) == 1
    return aliases[0].alias_id
