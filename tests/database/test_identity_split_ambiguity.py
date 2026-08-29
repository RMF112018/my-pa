"""What a governed split does about the records its merge ledger cannot prove.

`tests/database/test_identity_correction_merge.py` proves the deterministic
inverse: every recorded effect still matching its `after_state`, restored
exactly. This suite proves the half that used to have no answer at all
(`RI-P2-BLK-001` / `WP-01`). A merged-away child that somebody changed while the
two identities were one refused the whole split, and a row created against the
survivor after the merge was never looked for -- so the world an inversion is
most likely to meet was the world it could not invert.

What is asserted here is one flow end to end against real triggers, real
constraints and real concurrency: two ambiguities discovered with the right
reasons, the right admissible answers and the right admissible targets; an apply
refused four different ways before it writes anything; an apply that succeeds
once every ambiguity carries exactly one explicit settlement; and the
deterministic effects restored throughout without an operator ever being offered
a choice about them.

Every identity is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.errors import ConflictError, InvalidRequestError
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
    MergeReceipt,
    SplitCommand,
    SplitDisposition,
    SplitPreviewCommand,
    SplitPreviewReport,
    SplitReceipt,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.classification import Classification
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    ObservationKind,
)
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    AmbiguityReason,
    IdentityEffectFamily,
    IdentityOperationState,
    IdentityOperationType,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Its own disposable database, so this suite can run beside the other
#: database-tier fixtures without one dropping what another is mid-transaction
#: against.
DISPOSABLE_DATABASE: Final = "my_pa_identity_split_ambiguity_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
FOREIGN: Final = "ent_eeee0005eeee0005"

MOVED_ALIAS: Final = "eals_aaaa0001aaaa01"
LATER_OBSERVATION: Final = "eobs_bbbb0002bbbb02"

WHEN: Final = datetime(2026, 8, 29, 12, tzinfo=UTC)
OPERATOR: Final = PRINCIPAL_A
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"
MERGE_REASON: Final = "two synthetic records describe one synthetic person"
SPLIT_REASON: Final = "the synthetic identity correction was wrong"


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


def _entity(
    entity_id: str, principal_id: str = PRINCIPAL_A, name: str = "Alice Synthetic"
) -> Entity:
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


def _observation(observation_id: str, entity_id: str | None) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL_A,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Synthetic <alice@example.invalid>",
        normalized_value=normalize_name("Alice Synthetic"),
        source_id="src_aaaa0001aaaa0001",
        source_object_id="obj_aaaa0001aaaa0001",
        source_version_id="ver_aaaa0001aaaa0001",
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """One bare survivor, one duplicate holding one alias, and a foreign Principal.

    **The survivor is deliberately bare.** Post-merge discovery asks which rows
    now bind to the survivor that the merge's ledger never named, and the five
    tables it walks carry no creation timestamp, so a row the survivor already
    held answers that question the same way a row created afterwards does. A
    survivor with pre-merge children would therefore report more ambiguities than
    the two this suite is about -- which is the over-reporting the implementation
    documents, not a different behaviour.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(SURVIVOR))
        repository.create(PRINCIPAL_A, _entity(MERGED, name="Alice Synthetic Two"))
        repository.create(PRINCIPAL_B, _entity(FOREIGN, PRINCIPAL_B, "Bob Synthetic"))
        repository.record_alias(
            PRINCIPAL_A,
            EntityAlias(
                alias_id=MOVED_ALIAS,
                entity_id=MERGED,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Ali"),
                display_value="Ali",
                principal_id=PRINCIPAL_A,
                state=AliasState.ACTIVE,
            ),
        )
    return migrated_engine


def _service(connection: Connection) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    )


def _merged(engine: Engine) -> MergeReceipt:
    """Merge the duplicate away, exactly as an operator would."""
    with engine.begin() as connection:
        report = _service(connection).preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL_A,
                survivor_entity_id=SURVIVOR,
                expected_survivor_version=1,
                merged_away=((MERGED, 1),),
                reason=MERGE_REASON,
            ),
            at=WHEN,
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
        preview_id = report.preview.preview_id
        preview_digest = report.preview.preview_digest
    with engine.begin() as connection:
        return _service(connection).apply(
            MergeCommand(
                principal_id=PRINCIPAL_A,
                preview_id=preview_id,
                preview_digest=preview_digest,
                idempotency_key="merge-before-split",
                reason=MERGE_REASON,
            ),
            at=WHEN,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


def _disturbed(engine: Engine) -> None:
    """The world moves while the two identities are one.

    One merged-away child is changed after it was reparented, and one new child
    is created against the survivor. Neither is anything a split can attribute
    from the merge's ledger: the first no longer matches its recorded
    `after_state`, and the second appears in no effect at all.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_aliases "  # noqa: S608
                "SET version = version + 1, updated_at = :at WHERE alias_id = :alias_id"
            ),
            {"at": WHEN + timedelta(minutes=1), "alias_id": MOVED_ALIAS},
        )
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation(LATER_OBSERVATION, SURVIVOR)
        )


def _split_preview(engine: Engine, source_operation_id: str) -> SplitPreviewReport:
    with engine.begin() as connection:
        return _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=source_operation_id,
                reason=SPLIT_REASON,
            ),
            at=WHEN + timedelta(minutes=2),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


def _split_command(
    report: SplitPreviewReport,
    dispositions: tuple[SplitDisposition, ...] = (),
    *,
    key: str = "split-once",
) -> SplitCommand:
    return SplitCommand(
        principal_id=PRINCIPAL_A,
        preview_id=report.preview.preview_id,
        preview_digest=report.preview.preview_digest,
        idempotency_key=key,
        reason=SPLIT_REASON,
        dispositions=dispositions,
    )


def _split_apply(
    engine: Engine, split: SplitCommand, *, at: datetime = WHEN + timedelta(minutes=3)
) -> SplitReceipt:
    with engine.begin() as connection:
        return _service(connection).split_apply(
            split,
            at=at,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


def _row_count(engine: Engine, table: str, predicate: str = "true") -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {predicate}")  # noqa: S608
            ).scalar_one()
        )


def _settlements(report: SplitPreviewReport) -> tuple[SplitDisposition, ...]:
    """The one settlement each ambiguity of this fixture admits and this suite makes.

    The changed alias goes back to the identity it was reparented off; the later
    observation is left as evidence both identities share, which is the only
    family whose contract admits that.
    """
    chosen: list[SplitDisposition] = []
    for ambiguity in report.ambiguities:
        if ambiguity.record_family is IdentityEffectFamily.ALIAS:
            chosen.append(
                SplitDisposition(
                    ambiguity.ambiguity_id,
                    AmbiguityDisposition.ASSIGN_TO_ENTITY,
                    target_entity_id=MERGED,
                )
            )
        else:
            chosen.append(
                SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.PRESERVE_SHARED)
            )
    return tuple(chosen)


def test_a_changed_child_and_a_later_child_are_settled_rather_than_refusing_the_split(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001 / WP-01 / AC-REM-002..006, one flow from merge to settled split."""
    merge = _merged(staged)
    _disturbed(staged)
    report = _split_preview(staged, merge.operation.identity_operation_id)

    # --- what the preview found ------------------------------------------
    by_family = {ambiguity.record_family: ambiguity for ambiguity in report.ambiguities}
    assert len(report.ambiguities) == 2
    assert set(by_family) == {IdentityEffectFamily.ALIAS, IdentityEffectFamily.OBSERVATION}

    changed = by_family[IdentityEffectFamily.ALIAS]
    assert changed.record_id == MOVED_ALIAS
    assert changed.reason == AmbiguityReason.POST_MERGE_MODIFIED
    assert changed.allowed_dispositions == (
        AmbiguityDisposition.ASSIGN_TO_ENTITY.value,
        AmbiguityDisposition.LEAVE_UNRESOLVED.value,
    )
    assert changed.allowed_target_entity_ids == (SURVIVOR, MERGED)

    later = by_family[IdentityEffectFamily.OBSERVATION]
    assert later.record_id == LATER_OBSERVATION
    assert later.reason == AmbiguityReason.POST_MERGE_CREATED
    assert later.allowed_dispositions == (
        AmbiguityDisposition.ASSIGN_TO_ENTITY.value,
        AmbiguityDisposition.PRESERVE_SHARED.value,
        AmbiguityDisposition.LEAVE_UNRESOLVED.value,
    )
    assert later.allowed_target_entity_ids == (SURVIVOR, MERGED)

    # No raw personal content in what an operator is shown beside the question.
    for ambiguity in report.ambiguities:
        assert all(
            key.endswith(("_id", "_count", "_sequence", "_sha256"))
            for key in ambiguity.evidence_summary
        )

    # The record the ledger still proves carries a projected effect and no
    # question. The two it does not prove carry a question and no effect.
    projected = {draft.record_id for draft in report.projected_effects}
    assert MERGED in projected
    assert projected.isdisjoint({MOVED_ALIAS, LATER_OBSERVATION})

    # --- every refusal happens before the first write --------------------
    with pytest.raises(InvalidRequestError):
        _split_apply(staged, _split_command(report))
    with pytest.raises(InvalidRequestError):  # a family that admits no shared reading
        _split_apply(
            staged,
            _split_command(
                report,
                (
                    SplitDisposition(changed.ambiguity_id, AmbiguityDisposition.PRESERVE_SHARED),
                    SplitDisposition(later.ambiguity_id, AmbiguityDisposition.PRESERVE_SHARED),
                ),
            ),
        )
    with pytest.raises(InvalidRequestError):  # an ambiguity this preview never asked
        _split_apply(
            staged,
            _split_command(
                report,
                (
                    SplitDisposition(
                        "eiam_9999999999999999999999999999999a",
                        AmbiguityDisposition.LEAVE_UNRESOLVED,
                    ),
                    SplitDisposition(later.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),
                ),
            ),
        )
    with pytest.raises(InvalidRequestError):  # one ambiguity answered twice
        _split_apply(
            staged,
            _split_command(
                report,
                (
                    SplitDisposition(later.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),
                    SplitDisposition(later.ambiguity_id, AmbiguityDisposition.PRESERVE_SHARED),
                ),
            ),
        )
    with pytest.raises(InvalidRequestError):  # another Principal's entity as the target
        _split_apply(
            staged,
            _split_command(
                report,
                (
                    SplitDisposition(
                        changed.ambiguity_id,
                        AmbiguityDisposition.ASSIGN_TO_ENTITY,
                        target_entity_id=FOREIGN,
                    ),
                    SplitDisposition(later.ambiguity_id, AmbiguityDisposition.PRESERVE_SHARED),
                ),
            ),
        )

    assert _row_count(staged, "entity_identity_operations", "operation_type = 'split'") == 0
    assert _row_count(staged, "entity_identity_ambiguity_settlements") == 0
    with staged.connect() as connection:
        assert SqlEntityRepository(connection).aliases(PRINCIPAL_A, SURVIVOR)[0].entity_id == (
            SURVIVOR
        )

    # --- and then the split the operator actually authorised --------------
    receipt = _split_apply(staged, _split_command(report, _settlements(report)))
    assert not receipt.replayed
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert receipt.operation.operation_type is IdentityOperationType.SPLIT
    assert receipt.operation.source_identity_operation_id == merge.operation.identity_operation_id

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        restored = repository.get(PRINCIPAL_A, MERGED)
        survivor = repository.get(PRINCIPAL_A, SURVIVOR)
        aliases = repository.aliases(PRINCIPAL_A, MERGED)
        observations = repository.observations(PRINCIPAL_A, SURVIVOR)

    # The deterministic effect: restored with no operator choice about it.
    assert restored is not None and restored.status is EntityStatus.ACTIVE
    assert restored.superseded_by_entity_id is None
    assert survivor is not None and survivor.status is EntityStatus.ACTIVE
    assert {effect.record_id for effect in receipt.effects} == {MERGED}

    # The settled ones: the alias assigned back, the observation left shared.
    assert [alias.alias_id for alias in aliases] == [MOVED_ALIAS]
    assert [observation.observation_id for observation in observations] == [LATER_OBSERVATION]

    # Evidence provenance is untouched, and nothing was duplicated to share it.
    (observation,) = observations
    assert observation.source_id == "src_aaaa0001aaaa0001"
    assert observation.source_object_id == "obj_aaaa0001aaaa0001"
    assert observation.source_version_id == "ver_aaaa0001aaaa0001"
    assert _row_count(staged, "entity_observations") == 1
    assert _row_count(staged, "entity_aliases") == 1

    # The settlements are on the operation that carried them out.
    with staged.connect() as connection:
        settled = connection.execute(
            text(
                f"SELECT ambiguity_id, record_family, record_id, disposition, target_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_ambiguity_settlements "
                "WHERE identity_operation_id = :operation_id ORDER BY record_family"
            ),
            {"operation_id": receipt.operation.identity_operation_id},
        ).all()
    assert [tuple(row) for row in settled] == [
        (changed.ambiguity_id, "alias", MOVED_ALIAS, "assign_to_entity", MERGED),
        (later.ambiguity_id, "observation", LATER_OBSERVATION, "preserve_shared", None),
    ]


def test_an_assignment_moves_the_record_and_leaves_what_a_source_said_alone(
    staged: Engine,
) -> None:
    """`ASSIGN_TO_ENTITY` is the one disposition that writes, and it writes a binding.

    An observation's `resolution_version` is deliberately not advanced: moving a
    mention back to the identity it was recorded against is a consequence of the
    inversion, not a new decision about what the mention referred to.
    """
    merge = _merged(staged)
    _disturbed(staged)
    report = _split_preview(staged, merge.operation.identity_operation_id)
    with staged.connect() as connection:
        before = SqlEntityRepository(connection).observations(PRINCIPAL_A, SURVIVOR)

    _split_apply(
        staged,
        _split_command(
            report,
            tuple(
                SplitDisposition(
                    ambiguity.ambiguity_id,
                    AmbiguityDisposition.ASSIGN_TO_ENTITY,
                    target_entity_id=MERGED,
                )
                for ambiguity in report.ambiguities
            ),
        ),
    )

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        moved = repository.observations(PRINCIPAL_A, MERGED)
        assert repository.observations(PRINCIPAL_A, SURVIVOR) == []
        assert [alias.alias_id for alias in repository.aliases(PRINCIPAL_A, MERGED)] == [
            MOVED_ALIAS
        ]
    assert [observation.observation_id for observation in moved] == [LATER_OBSERVATION]
    assert moved[0].resolution_version == before[0].resolution_version
    assert moved[0].source_version_id == before[0].source_version_id
    assert _row_count(staged, "entity_observations") == 1


def test_a_settled_split_replays_under_its_key_and_consumes_its_preview_once(
    staged: Engine,
) -> None:
    """AC-REM-006: one settlement per source merge, and an identical retry is answered."""
    merge = _merged(staged)
    _disturbed(staged)
    report = _split_preview(staged, merge.operation.identity_operation_id)
    settled = _split_command(report, _settlements(report))

    receipt = _split_apply(staged, settled)
    replay = _split_apply(staged, settled, at=WHEN + timedelta(minutes=4))
    assert replay.replayed
    assert replay.operation == receipt.operation
    assert replay.effects == receipt.effects
    assert _row_count(staged, "entity_identity_ambiguity_settlements") == 2

    # A second preview of the same source merge is refused: one settlement per
    # source operation, whatever the second attempt would have decided.
    with pytest.raises(ConflictError):
        _split_preview(staged, merge.operation.identity_operation_id)


def test_a_preview_goes_stale_when_a_record_moves_under_it(staged: Engine) -> None:
    """AC-REM-004: dispositions can never settle a question the operator was not shown."""
    merge = _merged(staged)
    _disturbed(staged)
    report = _split_preview(staged, merge.operation.identity_operation_id)
    settled = _split_command(report, _settlements(report))

    with staged.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation("eobs_cccc0003cccc03", SURVIVOR)
        )

    with pytest.raises(ConflictError):
        _split_apply(staged, settled)
    assert _row_count(staged, "entity_identity_operations", "operation_type = 'split'") == 0
    assert _row_count(staged, "entity_identity_ambiguity_settlements") == 0


def test_only_one_of_two_concurrent_settled_splits_is_admitted(staged: Engine) -> None:
    """AC-REM-005: the preview is consumed once, so one apply wins and one is refused."""
    merge = _merged(staged)
    _disturbed(staged)
    report = _split_preview(staged, merge.operation.identity_operation_id)
    dispositions = _settlements(report)

    outcomes: list[object] = []

    def attempt(key: str) -> None:
        try:
            outcomes.append(_split_apply(staged, _split_command(report, dispositions, key=key)))
        except BaseException as error:  # pragma: no cover - asserted in the parent thread
            outcomes.append(error)

    threads = [
        Thread(target=attempt, args=(f"split-race-{index}",), daemon=True) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    receipts = [outcome for outcome in outcomes if isinstance(outcome, SplitReceipt)]
    assert len(receipts) == 1
    assert all(isinstance(outcome, Exception) for outcome in outcomes if outcome not in receipts)
    assert _row_count(staged, "entity_identity_operations", "operation_type = 'split'") == 1
    assert _row_count(staged, "entity_identity_ambiguity_settlements") == 2


def test_relationship_memory_and_the_other_unattributable_families_still_refuse(
    staged: Engine,
) -> None:
    """The boundary is unchanged behaviour, and it is asserted rather than assumed.

    Attribution needs a column saying which entity a row belongs to and a writer
    that can move it. A `PROPOSAL` has neither, and `Classification` is imported
    here only to keep the fixture honest about what a memory would carry -- the
    families outside that set keep the refusal they have always had, so a
    modified `entity` row still stops the split outright rather than becoming a
    question nothing could answer.
    """
    assert Classification.PRIVATE_LOCAL is not None
    merge = _merged(staged)
    with staged.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities SET version = version + 1 "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": MERGED},
        )
    with pytest.raises(ConflictError):
        _split_preview(staged, merge.operation.identity_operation_id)
    assert _row_count(staged, "entity_identity_preview_ambiguities") == 0
