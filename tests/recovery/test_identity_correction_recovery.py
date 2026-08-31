"""A governed merge that fails part-way through leaves nothing behind.

Section 21 says apply is atomic and section 29 asks for that to be *proved by an
injected mid-transaction failure*, not asserted. So each test here fails the
merge at a different point after real rows have already been written -- after the
redirect, after a child row moved, after the operation was opened -- and then
checks the whole affected world, not just the table the failure was injected in.

The atomicity itself is the caller's transaction rather than anything this module
compensates for: `IdentityCorrectionService` performs every write on the
connection it was handed, so leaving the block by exception rolls all of them
back. What these tests establish is that the claim is true of *this* write
sequence -- that nothing is written outside the transaction, that the preview is
not consumed by an attempt that failed, and that a retry after a rollback is a
first attempt rather than a replay of one that never happened.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
    MergePreviewReport,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectFamily,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)

pytestmark = pytest.mark.recovery

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_identity_correction_recovery_test"

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
OPERATOR: Final = PRINCIPAL
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
REASON: Final = "two synthetic records describe one synthetic person"


class InjectedFailureError(RuntimeError):
    """A failure with no meaning except where in the sequence it happened.

    Its own class so a test cannot pass because some genuine error was raised
    instead -- an `IntegrityError` from a merge that was actually broken would
    also roll the transaction back, and a test that accepted any exception would
    report that as atomicity.
    """


class _FailsAfterTheLedger(SqlEntityRepository):
    """Fails at the last write, once every row change is already in the transaction."""

    def record_identity_effects(
        self, principal_id: str, effects: tuple[IdentityEffect, ...]
    ) -> None:
        raise InjectedFailureError("the effect ledger could not be written")


class _FailsPartWayThroughTheRows(SqlEntityRepository):
    """Fails on the alias, after the entity redirect has already been written."""

    def reparent_entity_reference(
        self,
        principal_id: str,
        *,
        family: IdentityEffectFamily,
        record_id: str,
        from_entity_ids: frozenset[str],
        to_entity_id: str,
        expected_version: int,
        at: datetime,
        after_state: Mapping[str, object] | None = None,
    ) -> None:
        # RI-ENT-WP-06b widened the real reparent_entity_reference with an
        # after_state keyword (the non-entity-reference columns a reparenting
        # also writes, e.g. is_preferred demotion for names/addresses/
        # communication methods). This fake accepts and ignores its value --
        # the transaction-rollback behaviour this test proves does not depend
        # on what after_state carries, only on the fact that a failure here,
        # after the entity redirect has already been written, leaves nothing
        # behind. A stale signature without this parameter would raise
        # TypeError the moment a real caller passed it, which is exactly the
        # regression this comment exists to prevent recurring silently.
        raise InjectedFailureError("a child row could not be reparented")


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


def _entity(entity_id: str, name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """Two synthetic duplicates, the second carrying an alias the merge must move."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL, _entity(SURVIVOR, "Alice Synthetic"))
        repository.create(PRINCIPAL, _entity(MERGED, "Alice Synthetic Two"))
        repository.record_alias(
            PRINCIPAL,
            EntityAlias(
                alias_id="eals_aaaa0001aaaa01",
                entity_id=MERGED,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Ali"),
                display_value="Ali",
                principal_id=PRINCIPAL,
            ),
        )
    return migrated_engine


def _previewed(connection: Connection) -> MergePreviewReport:
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    ).preview(
        MergePreviewCommand(
            principal_id=PRINCIPAL,
            survivor_entity_id=SURVIVOR,
            expected_survivor_version=1,
            merged_away=((MERGED, 1),),
            reason=REASON,
        ),
        at=WHEN,
        requested_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _apply(
    entities: EntitiesRepository,
    connection: Connection,
    report: MergePreviewReport,
    *,
    key: str = "merge-one",
) -> None:
    IdentityCorrectionService(entities, SqlRelationshipMemoryRepository(connection)).apply(
        MergeCommand(
            principal_id=PRINCIPAL,
            preview_id=report.preview.preview_id,
            preview_digest=report.preview.preview_digest,
            idempotency_key=key,
            reason=REASON,
        ),
        at=WHEN,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        performed_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _assert_nothing_happened(engine: Engine) -> None:
    """Every table a merge touches, back exactly as it stood.

    All of them, and not just the one the failure was injected in: the point of
    atomicity is that a failure in the last write undoes the first, so a check
    that looked only at where the exception came from would pass on a merge that
    had committed half of itself.
    """
    with engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        merged = repository.get(PRINCIPAL, MERGED)
        survivor = repository.get(PRINCIPAL, SURVIVOR)
        aliases = repository.aliases(PRINCIPAL, MERGED)
        assert merged is not None
        assert merged.status is EntityStatus.ACTIVE
        assert merged.superseded_by_entity_id is None
        assert survivor is not None
        assert survivor.version == 1
        assert [alias.alias_id for alias in aliases] == ["eals_aaaa0001aaaa01"]
        assert aliases[0].state is AliasState.ACTIVE
        assert aliases[0].version == 1
        assert _count(connection, "entity_identity_operations") == 0
        assert _count(connection, "entity_identity_effects") == 0
        # The preview survives -- it was committed by its own transaction -- but
        # it was not consumed by an attempt that changed nothing. A merge that
        # spent the operator's approval on a failure would leave them holding a
        # token they cannot use and no merge to show for it.
        assert _count(connection, "entity_identity_previews", "consumed_at IS NOT NULL") == 0


def _count(connection: Connection, table: str, predicate: str = "true") -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {predicate}")  # noqa: S608
        ).scalar_one()
    )


def test_a_failure_writing_the_ledger_rolls_the_whole_merge_back(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with pytest.raises(InjectedFailureError), staged.begin() as connection:
        _apply(_FailsAfterTheLedger(connection), connection, report)
    _assert_nothing_happened(staged)


def test_a_failure_part_way_through_the_rows_rolls_the_redirect_back(staged: Engine) -> None:
    """The redirect is written first; the alias fails; the redirect must not stand."""
    with staged.begin() as connection:
        report = _previewed(connection)
    with pytest.raises(InjectedFailureError), staged.begin() as connection:
        _apply(_FailsPartWayThroughTheRows(connection), connection, report)
    _assert_nothing_happened(staged)


def test_the_merge_still_runs_after_a_rolled_back_attempt(staged: Engine) -> None:
    """A retry after a failure is a first attempt, not a replay of one.

    The failed attempt wrote no operation row, so the same idempotency key finds
    nothing and the merge is performed -- which is the honest answer, and is the
    reason the operation row is written inside the transaction rather than
    before it.
    """
    with staged.begin() as connection:
        report = _previewed(connection)
    with pytest.raises(InjectedFailureError), staged.begin() as connection:
        _apply(_FailsAfterTheLedger(connection), connection, report)
    with staged.begin() as connection:
        _apply(SqlEntityRepository(connection), connection, report)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        merged = repository.get(PRINCIPAL, MERGED)
        assert merged is not None
        assert merged.status is EntityStatus.MERGED_REDIRECT
        assert merged.superseded_by_entity_id == SURVIVOR
        assert [alias.alias_id for alias in repository.aliases(PRINCIPAL, SURVIVOR)] == [
            "eals_aaaa0001aaaa01"
        ]
        assert _count(connection, "entity_identity_operations") == 1
        assert _count(connection, "entity_identity_previews", "consumed_at IS NOT NULL") == 1
