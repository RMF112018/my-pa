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

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

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
from my_pa.contracts.ports import MemoryWriteRequest
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
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
    EntityProposal,
    EntityProposalMethod,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    AmbiguityReason,
    IdentityEffectFamily,
    IdentityOperationState,
    IdentityOperationType,
)
from my_pa.domain.relationship.memory import (
    MemoryActorClass,
    MemoryAuthority,
    MemoryKind,
    MemoryOperation,
    MemoryProposalMethod,
    MemoryProposalState,
    RelationshipMemoryProposal,
    classification_floor_for,
    memory_proposal_dedupe_digest,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
    dedupe_digest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)
from my_pa.infrastructure.persistence.relationship_memory_proposals import (
    SqlRelationshipMemoryProposalRepository,
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
THIRD: Final = "ent_cccc0003cccc0003"

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


def test_entity_still_refuses_outright_with_no_disposition_to_offer(
    staged: Engine,
) -> None:
    """`ENTITY` has no admissible disposition, so it keeps the original refusal.

    `dispositions_for(ENTITY)` returns `()`: an entity's own redirect is
    provable from the merge ledger or the split is refused outright, so there
    is no question a post-merge modification to it could raise -- not even
    `LEAVE_UNRESOLVED`, which needs no writer but is still an *answer*, and
    there is no admissible answer here to record. `REVIEW_CASE` (writes no
    row) and `DERIVED_CONTEXT` (recomputed rather than attributed) keep the
    same refusal for the same reason -- an empty `dispositions_for` -- but only
    `ENTITY` is exercised here, being the one of the three with a plain row to
    perturb. `Classification` is imported only to keep this module's fixture
    surface honest about what a memory write below carries.

    This is **not** the boundary `PROPOSAL`, `RELATIONSHIP_MEMORY`,
    `MEMORY_PROPOSAL` and `MEMORY_CONTEXT_LINK` sit on any more: they now admit
    `LEAVE_UNRESOLVED`, so a post-merge modification to one of them raises an
    ambiguity rather than refusing the split -- see
    `test_a_relationship_memory_the_ledger_can_no_longer_prove_is_an_ambiguity_not_a_refusal`
    below.
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


def test_a_relationship_memory_the_ledger_can_no_longer_prove_is_an_ambiguity_not_a_refusal(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001's gap closed for a fourth family: `RELATIONSHIP_MEMORY`.

    Before this fix, a `RELATIONSHIP_MEMORY` row that changed while the merge
    held it -- exactly the same shape of problem `ALIAS`/`IDENTIFIER`/
    `ASSIGNMENT`/`RELATIONSHIP`/`OBSERVATION` were fixed for -- still hit
    `raise ConflictError(SafeDetail.PREVIEW_STALE)` at the top of the family
    loop, refusing the whole split. `RelationshipMemoryRepository` has no
    operator-directed rebinding writer (it is read/admit/replay only), so
    `ASSIGN_TO_ENTITY` genuinely cannot be carried out for this family --
    but `LEAVE_UNRESOLVED` needs no writer at all, only a settlement row, so
    the fix narrows this family to exactly that one admissible answer instead
    of refusing outright. This test proves three things: the ambiguity is
    raised with the narrowed disposition set (not the old, wider one that
    falsely offered `ASSIGN_TO_ENTITY`); applying with no disposition for it
    still fails closed; and applying with `ASSIGN_TO_ENTITY` for it is rejected
    rather than silently accepted, proving the narrowing is enforced by
    `_validated_dispositions` and not merely advisory in a comment.
    """
    statement = "Synthetic relationship note admitted before the merge."
    with staged.begin() as connection:
        admission = SqlRelationshipMemoryRepository(connection).admit(
            MemoryWriteRequest(
                operation=MemoryOperation.CREATE,
                memory_id=None,
                memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                expected_version=None,
                principal_id=PRINCIPAL_A,
                subject_entity_id=MERGED,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement=statement,
                statement_sha256=statement_digest(statement),
                structured_value=None,
                authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                created_by_actor=MemoryActorClass.USER,
                context_links=(),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason=None,
                idempotency_key="split-ambiguity-memory-create",
                correlation_id=CORRELATION,
                server_received_at=WHEN,
            )
        )
    memory_id = admission.receipt.memory_id

    # The merge reparents the memory to the survivor deterministically, then
    # the world moves under it exactly as `_disturbed` moves the alias: a
    # further change to the same row the merge already touched, so the split's
    # recorded `after_state` no longer describes it.
    merge = _merged(staged)
    with staged.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.relationship_memories "  # noqa: S608
                "SET version = version + 1, updated_at = :at WHERE memory_id = :memory_id"
            ),
            {"at": WHEN + timedelta(minutes=1), "memory_id": memory_id},
        )

    report = _split_preview(staged, merge.operation.identity_operation_id)

    assert len(report.ambiguities) == 1
    (ambiguity,) = report.ambiguities
    assert ambiguity.record_family is IdentityEffectFamily.RELATIONSHIP_MEMORY
    assert ambiguity.record_id == memory_id
    assert ambiguity.reason == AmbiguityReason.POST_MERGE_MODIFIED
    # (a) Narrowed: `LEAVE_UNRESOLVED` only, not the old, wider pair that
    # falsely offered `ASSIGN_TO_ENTITY` for a family with no writer to run it.
    assert ambiguity.allowed_dispositions == (AmbiguityDisposition.LEAVE_UNRESOLVED.value,)
    assert ambiguity.allowed_target_entity_ids == (SURVIVOR, MERGED)

    # (b) Fail-closed preserved: no disposition for this ambiguity still
    # refuses, exactly as it does for every other family's ambiguity.
    with pytest.raises(InvalidRequestError):
        _split_apply(staged, _split_command(report))

    # (c) The narrowing is enforced, not advisory: `ASSIGN_TO_ENTITY` is
    # rejected even though the caller names an admissible target, because
    # `_validated_dispositions` checks the chosen disposition against this
    # ambiguity's own `allowed_dispositions` before anything is written.
    with pytest.raises(InvalidRequestError):
        _split_apply(
            staged,
            _split_command(
                report,
                (
                    SplitDisposition(
                        ambiguity.ambiguity_id,
                        AmbiguityDisposition.ASSIGN_TO_ENTITY,
                        target_entity_id=SURVIVOR,
                    ),
                ),
            ),
        )
    assert _row_count(staged, "entity_identity_operations", "operation_type = 'split'") == 0
    assert _row_count(staged, "entity_identity_ambiguity_settlements") == 0

    # And the one answer this family does admit carries the split through:
    # a settlement row recorded, no writer invoked, and the record left where
    # the merge's own deterministic reparent put it.
    receipt = _split_apply(
        staged,
        _split_command(
            report,
            (SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),),
        ),
    )
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    with staged.connect() as connection:
        settled_subject = connection.execute(
            text(
                f"SELECT subject_entity_id FROM {SCHEMA}.relationship_memories "  # noqa: S608
                "WHERE memory_id = :memory_id"
            ),
            {"memory_id": memory_id},
        ).scalar_one()
    assert settled_subject == SURVIVOR
    with staged.connect() as connection:
        settled = connection.execute(
            text(
                f"SELECT ambiguity_id, record_family, record_id, disposition, target_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_ambiguity_settlements "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"operation_id": receipt.operation.identity_operation_id},
        ).all()
    assert [tuple(row) for row in settled] == [
        (ambiguity.ambiguity_id, "relationship_memory", memory_id, "leave_unresolved", None),
    ]


def _assert_created_ambiguity_is_leave_unresolved_only(
    engine: Engine,
    merge: MergeReceipt,
    *,
    expected_family: IdentityEffectFamily,
    expected_record_id: str,
) -> SplitReceipt:
    """The common shape RI-P2-BLK-001's closed gap proves for `PROPOSAL` and the
    three memory families.

    One row newly bound to the survivor, absent from the merge's ledger, is
    discovered as `POST_MERGE_CREATED`; the family's own narrowed disposition
    set (`LEAVE_UNRESOLVED` only -- none of these four has a writer that could
    carry out `ASSIGN_TO_ENTITY`) is offered and enforced rather than merely
    advisory; every refusal happens before the first write; and the one
    settlement the operator can actually give carries the split through.
    """
    report = _split_preview(engine, merge.operation.identity_operation_id)
    assert len(report.ambiguities) == 1
    (ambiguity,) = report.ambiguities
    assert ambiguity.record_family is expected_family
    assert ambiguity.record_id == expected_record_id
    assert ambiguity.reason == AmbiguityReason.POST_MERGE_CREATED
    assert ambiguity.allowed_dispositions == (AmbiguityDisposition.LEAVE_UNRESOLVED.value,)
    assert ambiguity.allowed_target_entity_ids == (SURVIVOR, MERGED)
    assert all(
        key.endswith(("_id", "_count", "_sequence", "_sha256"))
        for key in ambiguity.evidence_summary
    )

    # (a) Fail-closed preserved: no disposition for this ambiguity still
    # refuses, before anything is written.
    with pytest.raises(InvalidRequestError):
        _split_apply(engine, _split_command(report))

    # (b) The narrowing is enforced, not advisory: `ASSIGN_TO_ENTITY` is
    # rejected even naming an admissible target, because `_validated_dispositions`
    # checks the chosen disposition against this ambiguity's own
    # `allowed_dispositions` before anything is written -- and this family has
    # no writer that could carry it out even if it were accepted.
    with pytest.raises(InvalidRequestError):
        _split_apply(
            engine,
            _split_command(
                report,
                (
                    SplitDisposition(
                        ambiguity.ambiguity_id,
                        AmbiguityDisposition.ASSIGN_TO_ENTITY,
                        target_entity_id=SURVIVOR,
                    ),
                ),
            ),
        )
    assert _row_count(engine, "entity_identity_operations", "operation_type = 'split'") == 0
    assert _row_count(engine, "entity_identity_ambiguity_settlements") == 0

    # (c) The one answer this family does admit carries the split through: a
    # settlement row recorded, no writer invoked, the record left exactly
    # where it already was.
    receipt = _split_apply(
        engine,
        _split_command(
            report,
            (SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),),
        ),
    )
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    with engine.connect() as connection:
        settled = connection.execute(
            text(
                f"SELECT ambiguity_id, record_family, record_id, disposition, target_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_ambiguity_settlements "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"operation_id": receipt.operation.identity_operation_id},
        ).all()
    assert [tuple(row) for row in settled] == [
        (
            ambiguity.ambiguity_id,
            expected_family.value,
            expected_record_id,
            "leave_unresolved",
            None,
        ),
    ]
    return receipt


def test_a_relationship_memory_created_after_the_merge_is_an_ambiguity_too(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001's `POST_MERGE_CREATED` path for `RELATIONSHIP_MEMORY`.

    `test_a_relationship_memory_the_ledger_can_no_longer_prove_is_an_ambiguity_not_a_refusal`
    above proves `POST_MERGE_MODIFIED` for this family: a memory the merge
    itself reparented, that then changed again. This proves the other half a
    split has to catch too: a memory admitted directly against the survivor
    *after* the merge, naming no merged-away identity at any point, so the
    merge's effect ledger carries no lineage for it at all.
    """
    merge = _merged(staged)
    statement = "Synthetic note admitted directly against the survivor after the merge."
    with staged.begin() as connection:
        admission = SqlRelationshipMemoryRepository(connection).admit(
            MemoryWriteRequest(
                operation=MemoryOperation.CREATE,
                memory_id=None,
                memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                expected_version=None,
                principal_id=PRINCIPAL_A,
                subject_entity_id=SURVIVOR,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement=statement,
                statement_sha256=statement_digest(statement),
                structured_value=None,
                authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                created_by_actor=MemoryActorClass.USER,
                context_links=(),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason=None,
                idempotency_key="split-ambiguity-memory-created",
                correlation_id=CORRELATION,
                server_received_at=WHEN,
            )
        )
    memory_id = admission.receipt.memory_id

    _assert_created_ambiguity_is_leave_unresolved_only(
        staged,
        merge,
        expected_family=IdentityEffectFamily.RELATIONSHIP_MEMORY,
        expected_record_id=memory_id,
    )
    with staged.connect() as connection:
        subject = connection.execute(
            text(
                f"SELECT subject_entity_id FROM {SCHEMA}.relationship_memories "  # noqa: S608
                "WHERE memory_id = :memory_id"
            ),
            {"memory_id": memory_id},
        ).scalar_one()
    assert subject == SURVIVOR


def test_an_entity_proposal_bound_to_the_survivor_after_the_merge_is_an_ambiguity_not_a_gap(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001's `POST_MERGE_CREATED` gap closed for `PROPOSAL`.

    `entity_proposals` carries no entity column at all -- its reference lives
    inside a kind-typed payload -- so discovery for this family cannot be
    `EntitiesRepository.records_bound_to_entity_outside`, which only answers
    for a row that names an entity in a column. This proves the mechanism the
    fix uses instead (`self._entities.proposals` read whole and
    `_proposal_is_materially_affected` applied against the survivor) still
    finds a proposal filed directly against the survivor after the merge, with
    no lineage in the merge's own effect ledger naming it, and that the
    family's narrowed disposition set is enforced rather than advisory.
    """
    merge = _merged(staged)
    proposal_id = issue_identifier(IdKind.ENTITY_PROPOSAL)
    payload = EntityProposalPayload.of(
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": SURVIVOR, "alias_type": "nickname", "display_value": "Al"},
    )
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal(
            PRINCIPAL_A,
            EntityProposal(
                proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                kind=EntityProposalKind.RECORD_ALIAS,
                state=EntityProposalState.PROPOSED,
                payload=payload,
                observation_ids=(),
                proposed_at=WHEN,
                proposed_by="synthetic-producer",
                method=EntityProposalMethod.DETERMINISTIC,
                method_version="v1",
                dedupe_sha256=dedupe_digest(payload),
            ),
        )

    _assert_created_ambiguity_is_leave_unresolved_only(
        staged,
        merge,
        expected_family=IdentityEffectFamily.PROPOSAL,
        expected_record_id=proposal_id,
    )
    with staged.connect() as connection:
        untouched = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
    assert untouched is not None
    assert untouched.state is EntityProposalState.PROPOSED


def test_a_memory_proposal_bound_to_the_survivor_after_the_merge_is_an_ambiguity_not_a_gap(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001's `POST_MERGE_CREATED` gap closed for `MEMORY_PROPOSAL`.

    A candidate memory recorded directly against the survivor after the
    merge, through the producer's own insert-only surface
    (`RelationshipMemoryProposalRepository.record_proposal`), with no lineage
    in the merge's own effect ledger naming it.
    """
    merge = _merged(staged)
    with staged.connect() as connection:
        survivor = SqlEntityRepository(connection).get(PRINCIPAL_A, SURVIVOR)
    assert survivor is not None
    memory_proposal_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
    statement = "Synthetic candidate memory proposed directly against the survivor."
    statement_sha256 = statement_digest(statement)
    proposal = RelationshipMemoryProposal(
        memory_proposal_id=memory_proposal_id,
        principal_id=PRINCIPAL_A,
        subject_entity_id=SURVIVOR,
        expected_subject_version=survivor.version,
        proposed_kind=MemoryKind.GENERAL_NOTE,
        proposed_statement=statement,
        proposed_statement_sha256=statement_sha256,
        dedupe_sha256=memory_proposal_dedupe_digest(
            principal_id=PRINCIPAL_A,
            subject_entity_id=SURVIVOR,
            proposed_kind=MemoryKind.GENERAL_NOTE,
            proposed_statement_sha256=statement_sha256,
            structured_value=None,
            context_links=(),
        ),
        state=MemoryProposalState.PROPOSED,
        method=MemoryProposalMethod.RULE,
        method_version="synthetic-origin-v1",
        classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
        proposed_at=WHEN,
    )
    with staged.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(proposal, ())

    _assert_created_ambiguity_is_leave_unresolved_only(
        staged,
        merge,
        expected_family=IdentityEffectFamily.MEMORY_PROPOSAL,
        expected_record_id=memory_proposal_id,
    )
    with staged.connect() as connection:
        row = connection.execute(
            text(
                "SELECT subject_entity_id, state "  # noqa: S608
                f"FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :memory_proposal_id"
            ),
            {"memory_proposal_id": memory_proposal_id},
        ).one()
    assert row.subject_entity_id == SURVIVOR
    assert row.state == MemoryProposalState.PROPOSED.value


def test_a_memory_context_link_bound_to_the_survivor_after_the_merge_is_an_ambiguity_not_a_gap(
    staged: Engine,
) -> None:
    """RI-P2-BLK-001's `POST_MERGE_CREATED` gap closed for `MEMORY_CONTEXT_LINK`.

    The new memory's own subject is a third, uninvolved entity, so this proves
    the context *link* is what discovery finds, not the memory's own
    `subject_entity_id`: the memory this admission writes does not bind to the
    survivor at all, only the `relationship_memory_context_links` row its
    admission also writes does.
    """
    merge = _merged(staged)
    with staged.begin() as connection:
        SqlEntityRepository(connection).create(PRINCIPAL_A, _entity(THIRD, name="Carol Synthetic"))
    statement = "Synthetic note about a third person, contextualised by the survivor."
    with staged.begin() as connection:
        admission = SqlRelationshipMemoryRepository(connection).admit(
            MemoryWriteRequest(
                operation=MemoryOperation.CREATE,
                memory_id=None,
                memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                expected_version=None,
                principal_id=PRINCIPAL_A,
                subject_entity_id=THIRD,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement=statement,
                statement_sha256=statement_digest(statement),
                structured_value=None,
                authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                created_by_actor=MemoryActorClass.USER,
                context_links=(
                    {"target_type": "entity", "target_id": SURVIVOR, "role": "related_to"},
                ),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason=None,
                idempotency_key="split-ambiguity-context-link-created",
                correlation_id=CORRELATION,
                server_received_at=WHEN,
            )
        )
    memory_id = admission.receipt.memory_id
    with staged.connect() as connection:
        context_link_id = connection.execute(
            text(
                f"SELECT context_link_id FROM {SCHEMA}.relationship_memory_context_links "  # noqa: S608
                "WHERE target_id = :target_id"
            ),
            {"target_id": SURVIVOR},
        ).scalar_one()

    _assert_created_ambiguity_is_leave_unresolved_only(
        staged,
        merge,
        expected_family=IdentityEffectFamily.MEMORY_CONTEXT_LINK,
        expected_record_id=context_link_id,
    )
    with staged.connect() as connection:
        target = connection.execute(
            text(
                f"SELECT target_id FROM {SCHEMA}.relationship_memory_context_links "  # noqa: S608
                "WHERE context_link_id = :context_link_id"
            ),
            {"context_link_id": context_link_id},
        ).scalar_one()
    assert target == SURVIVOR
    # The memory itself is untouched: this ambiguity is about the link, not
    # about `relationship_memories.subject_entity_id`, which never named the
    # survivor at any point.
    with staged.connect() as connection:
        memory_subject = connection.execute(
            text(
                f"SELECT subject_entity_id FROM {SCHEMA}.relationship_memories "  # noqa: S608
                "WHERE memory_id = :memory_id"
            ),
            {"memory_id": memory_id},
        ).scalar_one()
    assert memory_subject == THIRD
