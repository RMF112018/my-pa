"""A governed merge against real statements, real indexes and real triggers.

`tests/unit/test_identity_correction_planning.py` drives the planning functions
over records and proves what each branch decides. This drives the whole service
against PostgreSQL and proves the decisions survive contact with the schema: the
reparenting actually satisfies `an_active_alias_is_unique_per_entity_and_type`,
the self-edge supersession is the only form `from_entity_id <> to_entity_id`
admits, the effect ledger's append-only trigger accepts what the merge writes,
and every refusal leaves the rows exactly as they stood.

Every identity here is synthetic and every address is `example.invalid`, which
is the operator authorization's condition for exercising merge at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.application.errors import ConflictError, DeniedError, InvalidRequestError, NotFoundError
from my_pa.application.identity_correction import (
    ConflictChoice,
    FamilyDisposition,
    IdentityCorrectionService,
    MergeCommand,
    MergeFamily,
    MergePreviewCommand,
    MergePreviewReport,
    MergeReceipt,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
    RelationshipState,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    EntityProposal,
    EntityProposalMethod,
    EntityProposalState,
    EntityResolutionDecision,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    IdentityConflictKind,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperationState,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
    dedupe_digest,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.entity_proposal_review import (
    entity_proposal_review_cases,
)
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Distinct from every other database-tier fixture's disposable database, so this
#: suite can run beside them without one dropping what another is mid-transaction
#: against.
DISPOSABLE_DATABASE: Final = "my_pa_identity_correction_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED_ONE: Final = "ent_bbbb0002bbbb0002"
MERGED_TWO: Final = "ent_cccc0003cccc0003"
TOWER: Final = "ent_dddd0004dddd0004"
FOREIGN: Final = "ent_eeee0005eeee0005"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
OPERATOR: Final = "prn_aaaa0001aaaa0001aaaa0001"
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
REASON: Final = "two synthetic records describe one synthetic person"


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
    entity_id: str,
    principal_id: str = PRINCIPAL_A,
    name: str = "Alice Synthetic",
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """Two synthetic duplicates of one person, one project, and a decoy Principal."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(SURVIVOR))
        repository.create(PRINCIPAL_A, _entity(MERGED_ONE, name="Alice Synthetic Two"))
        repository.create(PRINCIPAL_A, _entity(MERGED_TWO, name="Alice Synthetic Three"))
        repository.create(
            PRINCIPAL_A, _entity(TOWER, name="Harbour Tower", entity_type=EntityType.PROJECT)
        )
        repository.create(PRINCIPAL_B, _entity(FOREIGN, PRINCIPAL_B, "Bob Synthetic"))
    return migrated_engine


def _alias(
    alias_id: str,
    entity_id: str,
    name: str = "Ali",
    *,
    state: AliasState = AliasState.ACTIVE,
) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=AliasType.NICKNAME,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=PRINCIPAL_A,
        state=state,
    )


def _identifier(
    identifier_id: str,
    entity_id: str,
    value: str = "alice@example.invalid",
    *,
    state: IdentifierState = IdentifierState.ACTIVE,
) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, value),
        display_value=value,
        principal_id=PRINCIPAL_A,
        state=state,
    )


def _assignment(
    assignment_id: str, entity_id: str, *, scope_entity_id: str | None = TOWER
) -> Assignment:
    return Assignment(
        assignment_id=assignment_id,
        entity_id=entity_id,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=scope_entity_id,
        role="Project Manager",
    )


def _edge(relationship_id: str, from_entity_id: str, to_entity_id: str) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=relationship_id,
        from_entity_id=from_entity_id,
        relationship_type=EntityRelationshipType.AFFILIATED_WITH,
        to_entity_id=to_entity_id,
        principal_id=PRINCIPAL_A,
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


def _proposal(
    proposal_id: str, entity_id: str, *, review_case_id: str | None = None
) -> EntityProposal:
    payload = EntityProposalPayload.of(
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": entity_id, "alias_type": "nickname", "display_value": "Ali"},
    )
    return EntityProposal(
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
        review_case_id=review_case_id,
    )


def _preview_command(
    *,
    merged: tuple[tuple[str, int], ...] = ((MERGED_ONE, 1),),
    survivor: str = SURVIVOR,
    survivor_version: int = 1,
    evidence: tuple[str, ...] = (),
) -> MergePreviewCommand:
    return MergePreviewCommand(
        principal_id=PRINCIPAL_A,
        survivor_entity_id=survivor,
        expected_survivor_version=survivor_version,
        merged_away=merged,
        reason=REASON,
        evidence_refs=evidence,
    )


def _service(connection: Connection) -> IdentityCorrectionService:
    """The service over both ports, on the one connection the test transaction owns.

    Two repositories rather than one: the memory plane is reached through its own
    port, so a merge preview's Relationship Memory check crosses the boundary the
    architecture tier sweeps rather than reaching a memory table from the entity
    repository.
    """
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    )


def _previewed(
    connection: Connection,
    command: MergePreviewCommand | None = None,
    *,
    at: datetime = WHEN,
    operator: bool = True,
) -> MergePreviewReport:
    return _service(connection).preview(
        command or _preview_command(),
        at=at,
        requested_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=operator,
    )


def _applied(
    connection: Connection,
    report: MergePreviewReport,
    *,
    key: str = "merge-one",
    at: datetime = WHEN,
    choices: tuple[tuple[str, ConflictChoice], ...] = (),
    digest: str | None = None,
    reason: str = REASON,
    operator: bool = True,
) -> MergeReceipt:
    return _service(connection).apply(
        MergeCommand(
            principal_id=PRINCIPAL_A,
            preview_id=report.preview.preview_id,
            preview_digest=digest or report.preview.preview_digest,
            idempotency_key=key,
            reason=reason,
            choices=choices,
        ),
        at=at,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        performed_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=operator,
    )


def _group(report: MergePreviewReport, family: MergeFamily) -> tuple[FamilyDisposition, int]:
    found = next(group for group in report.groups if group.family is family)
    return found.disposition, found.record_count


def _row_count(engine: Engine, table: str, predicate: str = "true") -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {predicate}")  # noqa: S608
            ).scalar_one()
        )


# --- authority ---------------------------------------------------------------


def test_a_preview_without_operator_authority_is_denied_and_stores_nothing(
    staged: Engine,
) -> None:
    with pytest.raises(DeniedError) as refused, staged.begin() as connection:
        _previewed(connection, operator=False)
    assert [detail.value for detail in refused.value.safe_details] == ["operator_required"]
    assert _row_count(staged, "entity_identity_previews") == 0


def test_an_apply_without_operator_authority_is_denied_and_changes_nothing(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with pytest.raises(DeniedError), staged.begin() as connection:
        _applied(connection, report, operator=False)
    assert _row_count(staged, "entity_identity_operations") == 0
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


# --- the preview binding -----------------------------------------------------


def test_a_preview_is_persisted_bound_and_expires_in_fifteen_minutes(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    assert report.preview.expires_at == WHEN + IDENTITY_PREVIEW_LIFETIME
    assert report.preview.merged_away == ((MERGED_ONE, 1),)
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).identity_preview(
            PRINCIPAL_A, report.preview.preview_id
        )
    assert stored == report.preview


def test_a_preview_answers_for_every_family_the_contract_names(staged: Engine) -> None:
    """Section 20: do not silently ignore an affected family."""
    with staged.begin() as connection:
        report = _previewed(connection)
    assert [group.family for group in report.groups] == list(MergeFamily)
    assert _group(report, MergeFamily.SURVIVOR_ENTITY) == (FamilyDisposition.UNCHANGED, 1)
    assert _group(report, MergeFamily.MERGED_AWAY_ENTITY) == (FamilyDisposition.TRANSFORMED, 1)
    # The two planes section 20 names that nothing binds to an identity yet.
    assert _group(report, MergeFamily.TASK) == (FamilyDisposition.NOT_BOUND, 0)
    assert _group(report, MergeFamily.COMMITMENT) == (FamilyDisposition.NOT_BOUND, 0)
    assert _group(report, MergeFamily.DERIVED_CONTEXT) == (FamilyDisposition.NOT_BOUND, 0)
    assert _group(report, MergeFamily.RE_ENRICHMENT) == (FamilyDisposition.NOT_BOUND, 0)


def test_ten_entities_may_be_merged_away_and_eleven_may_not(migrated_engine: Engine) -> None:
    identifiers = [f"ent_{index:04d}0000{index:04d}0000" for index in range(1, 13)]
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        for index, entity_id in enumerate(identifiers):
            repository.create(PRINCIPAL_A, _entity(entity_id, name=f"Synthetic {index}"))
    survivor, *rest = identifiers
    with migrated_engine.begin() as connection:
        report = _previewed(
            connection,
            _preview_command(
                survivor=survivor, merged=tuple((entity_id, 1) for entity_id in rest[:10])
            ),
        )
    assert _group(report, MergeFamily.MERGED_AWAY_ENTITY) == (FamilyDisposition.TRANSFORMED, 10)
    with pytest.raises(InvalidRequestError), migrated_engine.begin() as connection:
        _previewed(
            connection,
            _preview_command(
                survivor=survivor, merged=tuple((entity_id, 1) for entity_id in rest[:11])
            ),
        )


def test_a_repeated_entity_and_a_self_merge_are_both_refused(staged: Engine) -> None:
    with pytest.raises(InvalidRequestError), staged.begin() as connection:
        _previewed(
            connection,
            _preview_command(merged=((MERGED_ONE, 1), (MERGED_ONE, 1))),
        )
    with pytest.raises(InvalidRequestError), staged.begin() as connection:
        _previewed(connection, _preview_command(merged=((SURVIVOR, 1),)))


def test_a_foreign_entity_is_answered_exactly_as_an_absent_one(staged: Engine) -> None:
    with pytest.raises(NotFoundError) as foreign, staged.begin() as connection:
        _previewed(connection, _preview_command(merged=((FOREIGN, 1),)))
    with pytest.raises(NotFoundError) as absent, staged.begin() as connection:
        _previewed(
            connection,
            _preview_command(merged=(("ent_ffff0006ffff0006", 1),)),
        )
    assert foreign.value.safe_details == absent.value.safe_details
    assert _row_count(staged, "entity_identity_previews") == 0


def test_a_version_that_already_moved_refuses_the_preview(staged: Engine) -> None:
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _previewed(connection, _preview_command(merged=((MERGED_ONE, 4),)))
    assert [detail.value for detail in refused.value.safe_details] == [
        "preview_stale",
        "stale_version",
    ]


def test_cited_evidence_must_be_an_observation_of_this_principal(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation("eobs_aaaa0001aaaa01", None)
        )
    with staged.begin() as connection:
        report = _previewed(
            connection,
            _preview_command(evidence=("eobs_aaaa0001aaaa01",)),
        )
    assert report.preview.preview_id
    with pytest.raises(InvalidRequestError) as refused, staged.begin() as connection:
        _previewed(
            connection,
            _preview_command(evidence=("eobs_ffff0006ffff06",)),
        )
    assert [detail.value for detail in refused.value.safe_details] == ["evidence_invalid"]


# --- what a merge does -------------------------------------------------------


def test_a_merge_redirects_the_merged_entity_and_leaves_the_survivor_alone(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        survivor = repository.get(PRINCIPAL_A, SURVIVOR)
        merged = repository.get(PRINCIPAL_A, MERGED_ONE)
    assert survivor is not None
    assert survivor.status is EntityStatus.ACTIVE
    assert survivor.version == 1
    assert survivor.superseded_by_entity_id is None
    assert merged is not None
    assert merged.status is EntityStatus.MERGED_REDIRECT
    assert merged.superseded_by_entity_id == SURVIVOR
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert receipt.replayed is False
    # Nothing was deleted: the merged-away entity is still a readable row.
    assert _row_count(staged, "entities", "principal_id = 'prn_aaaa0001aaaa0001aaaa0001'") == 4


def test_the_effect_ledger_records_every_change_in_a_stable_order(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE))
        repository.bind_identifier(
            PRINCIPAL_A, MERGED_ONE, _identifier("xid_aaaa0001aaaa01", MERGED_ONE)
        )
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", MERGED_ONE))
        repository.record_observation(PRINCIPAL_A, _observation("eobs_aaaa0001aaaa01", MERGED_ONE))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert [effect.sequence for effect in receipt.effects] == list(
        range(1, len(receipt.effects) + 1)
    )
    assert receipt.effects[0].family is IdentityEffectFamily.ENTITY
    assert {effect.family for effect in receipt.effects} == {
        IdentityEffectFamily.ENTITY,
        IdentityEffectFamily.ALIAS,
        IdentityEffectFamily.IDENTIFIER,
        IdentityEffectFamily.ASSIGNMENT,
        IdentityEffectFamily.OBSERVATION,
    }
    # Every effect carries both sides. Section 22 calls recording only redirects
    # faking invertibility, and a half-recorded effect is the same failure one
    # row at a time.
    for effect in receipt.effects:
        assert effect.before_state
        assert effect.after_state
        assert effect.before_state != effect.after_state
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).identity_effects(
            PRINCIPAL_A, receipt.operation.identity_operation_id
        )
    assert [effect.effect_id for effect in stored] == [
        effect.effect_id for effect in receipt.effects
    ]


def test_the_projected_effects_are_what_the_merge_records(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE))
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", MERGED_ONE))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert {(draft.family, draft.record_id, draft.kind) for draft in report.projected_effects} == {
        (effect.family, effect.record_id, effect.kind) for effect in receipt.effects
    }


def test_an_alias_reparents_and_a_duplicate_one_coalesces(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(PRINCIPAL_A, _alias("eals_ssss0001ssss01", SURVIVOR, "Ali"))
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE, "Ali"))
        repository.record_alias(PRINCIPAL_A, _alias("eals_bbbb0002bbbb02", MERGED_ONE, "Allie"))
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ALIAS) == (FamilyDisposition.TRANSFORMED, 2)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        survivor_aliases = {
            alias.alias_id: alias for alias in repository.aliases(PRINCIPAL_A, SURVIVOR)
        }
        merged_aliases = {
            alias.alias_id: alias for alias in repository.aliases(PRINCIPAL_A, MERGED_ONE)
        }
    assert sorted(survivor_aliases) == ["eals_bbbb0002bbbb02", "eals_ssss0001ssss01"]
    coalesced = merged_aliases["eals_aaaa0001aaaa01"]
    assert coalesced.state is AliasState.SUPERSEDED
    assert coalesced.superseded_by_alias_id == "eals_ssss0001ssss01"


def test_a_current_address_the_survivor_once_held_blocks_the_merge(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.bind_identifier(
            PRINCIPAL_A,
            SURVIVOR,
            _identifier("xid_ssss0001ssss01", SURVIVOR, state=IdentifierState.RETIRED),
        )
        repository.bind_identifier(
            PRINCIPAL_A, MERGED_ONE, _identifier("xid_aaaa0001aaaa01", MERGED_ONE)
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert [conflict.kind for conflict in report.blockers] == [
        IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT
    ]
    assert _group(report, MergeFamily.IDENTIFIER)[0] is FamilyDisposition.BLOCKED
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == [
        "identity_correction_conflict",
        "conflicted_identifier",
    ]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_an_assignment_deduplicates_and_a_scope_reparents(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_ssss0001ssss01", SURVIVOR))
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", MERGED_ONE))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert {
        effect.kind
        for effect in receipt.effects
        if effect.family is IdentityEffectFamily.ASSIGNMENT
    } == {IdentityEffectKind.ROW_COALESCED}
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).assignments(PRINCIPAL_A, SURVIVOR, active_only=True)
    assert [assignment.assignment_id for assignment in held] == ["asn_ssss0001ssss01"]


def test_a_project_scope_moves_with_the_identity(staged: Engine) -> None:
    """The project is merged away; somebody else's assignment keeps its holder."""
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_assignment(
            PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", SURVIVOR, scope_entity_id=MERGED_ONE)
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).assignments(PRINCIPAL_A, SURVIVOR)
    assert [assignment.scope_entity_id for assignment in held] == [SURVIVOR]


def test_a_merge_created_self_edge_is_superseded_rather_than_surviving(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_relationship(
            PRINCIPAL_A, _edge("erel_aaaa0001aaaa01", MERGED_ONE, SURVIVOR)
        )
        repository.record_relationship(PRINCIPAL_A, _edge("erel_bbbb0002bbbb02", MERGED_ONE, TOWER))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    kinds = {
        effect.record_id: effect.kind
        for effect in receipt.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP
    }
    assert kinds == {
        "erel_aaaa0001aaaa01": IdentityEffectKind.SELF_EDGE_SUPERSEDED,
        "erel_bbbb0002bbbb02": IdentityEffectKind.OWNER_REPARENTED,
    }
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        loop = repository.relationship(PRINCIPAL_A, "erel_aaaa0001aaaa01")
        moved = repository.relationship(PRINCIPAL_A, "erel_bbbb0002bbbb02")
    assert loop is not None
    assert loop.state is RelationshipState.SUPERSEDED
    assert loop.superseded_by_relationship_id is None
    # Not rewritten into a loop: the row's own CHECK has no such form to store.
    assert loop.from_entity_id == MERGED_ONE
    assert moved is not None
    assert moved.from_entity_id == SURVIVOR
    assert moved.state is RelationshipState.ACTIVE


def test_a_duplicate_edge_deduplicates(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_relationship(PRINCIPAL_A, _edge("erel_ssss0001ssss01", SURVIVOR, TOWER))
        repository.record_relationship(PRINCIPAL_A, _edge("erel_aaaa0001aaaa01", MERGED_ONE, TOWER))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert {
        effect.kind
        for effect in receipt.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP
    } == {IdentityEffectKind.ROW_COALESCED}
    with staged.connect() as connection:
        folded = SqlEntityRepository(connection).relationship(PRINCIPAL_A, "erel_aaaa0001aaaa01")
    assert folded is not None
    assert folded.superseded_by_relationship_id == "erel_ssss0001ssss01"


def test_an_observation_rebinds_without_its_source_evidence_changing(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation("eobs_aaaa0001aaaa01", MERGED_ONE)
        )
    with staged.connect() as connection:
        before = SqlEntityRepository(connection).observation(PRINCIPAL_A, "eobs_aaaa0001aaaa01")
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        after = SqlEntityRepository(connection).observation(PRINCIPAL_A, "eobs_aaaa0001aaaa01")
    assert before is not None
    assert after is not None
    assert after.entity_id == SURVIVOR
    assert after.observed_value == before.observed_value
    assert (after.source_id, after.source_object_id, after.source_version_id) == (
        before.source_id,
        before.source_object_id,
        before.source_version_id,
    )
    assert after.observed_at == before.observed_at
    assert after.resolution_version == before.resolution_version


def test_an_open_proposal_naming_the_merged_identity_is_invalidated(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_proposal(PRINCIPAL_A, _proposal("eprp_aaaa0001aaaa01", MERGED_ONE))
        repository.record_proposal(PRINCIPAL_A, _proposal("eprp_bbbb0002bbbb02", TOWER))
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        closed = repository.proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa01")
        untouched = repository.proposal(PRINCIPAL_A, "eprp_bbbb0002bbbb02")
    assert closed is not None
    assert closed.state is EntityProposalState.INVALIDATED
    assert closed.invalidated_reason is not None
    assert closed.decided_by == OPERATOR
    assert untouched is not None
    assert untouched.state is EntityProposalState.PROPOSED


def test_a_needs_review_proposal_naming_the_merged_identity_is_invalidated(
    staged: Engine,
) -> None:
    """The cross-wave case neither `WP-RI-B-05` nor `WP-RI-06` exercised alone.

    The test above stages its proposal by constructing the record directly with
    `state=PROPOSED`, so it kept passing when `initial_state_for` began deriving
    the initial state from the kind's review requirement. This one files the
    proposal the way a producer actually does -- through `propose`, with a kind
    `requirement_for` says a person must look at -- so the row lands in
    `needs_review`, which is the state a real review-requiring proposal is in
    when an operator merges the entity it names.

    That combination broke the merge outright: the planner selects on
    `EntityProposal.is_open`, which includes `needs_review`, so it planned an
    invalidation; `invalidate_proposal` still matched the `proposed` literal, so
    the statement changed nothing and raised `UnknownScopeError` -- refusing the
    whole merge with a message asserting the proposal was not open when it was.
    Both sides read `UNDECIDED_PROPOSAL_STATES` now.
    """
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_A,
            kind=EntityProposalKind.UPDATE_ENTITY,
            payload={"entity_id": MERGED_ONE, "reason": "a synthetic correction"},
            observation_ids=(),
            proposed_by="synthetic-producer",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="v1",
            at=WHEN,
        )
    with staged.connect() as connection:
        staged_proposal = SqlEntityRepository(connection).proposals(PRINCIPAL_A)[0]
    assert staged_proposal.state is EntityProposalState.NEEDS_REVIEW, (
        "the fixture is not staging the state this test exists to cover"
    )
    assert staged_proposal.is_open is True

    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        closed = repository.proposal(PRINCIPAL_A, staged_proposal.proposal_id)
    assert closed is not None
    assert closed.state is EntityProposalState.INVALIDATED
    assert closed.invalidated_reason is not None
    assert closed.decided_by == OPERATOR


def test_a_proposal_on_a_review_case_is_invalidated_and_the_case_goes_with_it(
    staged: Engine,
) -> None:
    """The blocker `WP-RI-06` shipped, and why the merge can now perform it.

    It refused because closing a proposal and leaving its Review case standing is
    the half-transformation section 20 forbids. `WP-RI-05` then put Entity
    proposals on the canonical surface as a *derived* case:
    `entity_proposals.review_case_id` is the case identifier and the case's
    state, version and latest disposition are read off the proposal row and the
    decision ledger. There is no second row to leave standing, so invalidating
    the proposal presents the case as invalidated in the same statement.

    Staged the way a producer actually files one -- through `propose`, with a
    kind `requirement_for` says a person must look at -- because that is what
    opens a case at all, and a hand-built record carrying a `review_case_id`
    would prove the plumbing without proving the population.
    """
    with staged.begin() as connection:
        EntityGovernanceService(SqlEntityRepository(connection)).propose(
            PRINCIPAL_A,
            kind=EntityProposalKind.UPDATE_ENTITY,
            payload={"entity_id": MERGED_ONE, "reason": "a synthetic correction"},
            observation_ids=(),
            proposed_by="synthetic-producer",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="v1",
            at=WHEN,
        )
    with staged.connect() as connection:
        staged_proposal = SqlEntityRepository(connection).proposals(PRINCIPAL_A)[0]
    review_case_id = staged_proposal.review_case_id
    assert review_case_id is not None, (
        "the fixture is not staging the review case this test exists to cover"
    )

    with staged.begin() as connection:
        report = _previewed(connection)
    assert report.blockers == ()
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (FamilyDisposition.TRANSFORMED, 1)
    assert _group(report, MergeFamily.REVIEW_CASE) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        receipt = _applied(connection, report)

    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 1
    with staged.connect() as connection:
        closed = SqlEntityRepository(connection).proposal(PRINCIPAL_A, staged_proposal.proposal_id)
    assert closed is not None
    assert closed.state is EntityProposalState.INVALIDATED
    assert closed.review_case_id == review_case_id

    # Both rows, and both from the ledger the split will read rather than from
    # the receipt alone.
    with staged.connect() as connection:
        stored = SqlEntityRepository(connection).identity_effects(
            PRINCIPAL_A, receipt.operation.identity_operation_id
        )
    invalidations = [
        (effect.family, effect.record_id)
        for effect in stored
        if effect.kind is IdentityEffectKind.DEPENDENT_INVALIDATED
    ]
    assert invalidations == [
        (IdentityEffectFamily.PROPOSAL, staged_proposal.proposal_id),
        (IdentityEffectFamily.REVIEW_CASE, review_case_id),
    ]
    case_effect = next(
        effect for effect in stored if effect.family is IdentityEffectFamily.REVIEW_CASE
    )
    assert case_effect.before_state == {"state": "needs_review"}
    assert case_effect.after_state == {"state": "invalidated"}
    # The extra row is inside the gapless sequence, not appended after it.
    assert [effect.sequence for effect in stored] == list(range(1, len(stored) + 1))
    assert stored[-1].family is IdentityEffectFamily.REVIEW_CASE

    # The surface a reviewer reads, and nobody decided anything on it.
    with staged.connect() as connection:
        cases = entity_proposal_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)
    assert [case.review_case_id for case in cases] == [review_case_id]
    assert cases[0].proposal_state is ProposalState.INVALIDATED
    assert cases[0].latest_disposition is None
    assert cases[0].review_version == 0
    assert cases[0].escalated is False
    assert _row_count(staged, "entity_proposal_review_decisions") == 0


def test_a_proposal_with_no_review_case_leaves_the_review_family_unchanged(
    staged: Engine,
) -> None:
    """A proposal a threshold could accept opens no case, and the merge says so.

    The counterpart to the test above, and the reason the `REVIEW_CASE` group is
    counted from `review_case_id` rather than from the fact that a proposal was
    invalidated: there is no case here, so there is nothing for a split to revive
    and nothing the ledger should claim it took off a reviewer's surface.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal(
            PRINCIPAL_A, _proposal("eprp_aaaa0001aaaa01", MERGED_ONE)
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (FamilyDisposition.TRANSFORMED, 1)
    assert _group(report, MergeFamily.REVIEW_CASE) == (FamilyDisposition.UNCHANGED, 0)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert IdentityEffectFamily.REVIEW_CASE not in {effect.family for effect in receipt.effects}
    assert _row_count(staged, "entity_identity_effects", "record_family = 'review_case'") == 0


def test_a_relationship_memory_subject_blocks_the_merge_without_naming_the_memory(
    staged: Engine,
) -> None:
    """WP-RI-08 owns origin-subject; this phase's ledger has no family for it."""
    with staged.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.relationship_memory_proposals ("  # noqa: S608
                "memory_proposal_id, principal_id, subject_entity_id, proposed_kind, "
                "proposed_statement, proposed_statement_sha256, state, method, "
                "method_version, classification, proposed_at) VALUES ("
                "'mprop_aaaa0001aaaa01', :principal, :subject, 'general_note', "
                "'synthetic note', :digest, 'proposed', 'deterministic', 'v1', "
                "'synthetic_test', :moment)"
            ),
            {
                "principal": PRINCIPAL_A,
                "subject": MERGED_ONE,
                "digest": "a" * 64,
                "moment": WHEN,
            },
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.RELATIONSHIP_MEMORY) == (FamilyDisposition.BLOCKED, 1)
    assert [conflict.record_id for conflict in report.blockers] == [MERGED_ONE]
    assert [conflict.family for conflict in report.blockers] == [IdentityEffectFamily.ENTITY]
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == [
        "identity_correction_conflict"
    ]


def test_resolution_decisions_and_source_links_are_reported_and_left_alone(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation("eobs_aaaa0001aaaa01", None))
        assert repository.decide_observation(
            PRINCIPAL_A,
            "eobs_aaaa0001aaaa01",
            expected_resolution_version=0,
            entity_id=MERGED_ONE,
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_resolution_decision(
            PRINCIPAL_A,
            EntityResolutionDecision(
                decision_id="erdc_aaaa0001aaaa01",
                principal_id=PRINCIPAL_A,
                observation_id="eobs_aaaa0001aaaa01",
                sequence=1,
                expected_resolution_version=0,
                disposition=ResolutionDisposition.LINK_EXISTING,
                decided_by=OPERATOR,
                actor_class=ActorClass.USER,
                correlation_id=CORRELATION,
                audit_id=AUDIT,
                decided_at=WHEN,
                entity_id=MERGED_ONE,
            ),
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.RESOLUTION_DECISION) == (FamilyDisposition.UNCHANGED, 1)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        decisions = SqlEntityRepository(connection).resolution_decisions(
            PRINCIPAL_A, "eobs_aaaa0001aaaa01"
        )
    assert [decision.entity_id for decision in decisions] == [MERGED_ONE]


# --- admission, staleness and replay ----------------------------------------


def test_an_expired_preview_is_refused_and_a_new_one_is_required(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    later = WHEN + IDENTITY_PREVIEW_LIFETIME + timedelta(seconds=1)
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report, at=later)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_expired"]
    assert _row_count(staged, "entity_identity_operations") == 0


def test_a_mismatched_digest_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report, digest="f" * 64)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]


def test_a_preview_whose_stored_binding_was_edited_is_refused(staged: Engine) -> None:
    """The one path the repository's own writes do not cover: an edit at the server."""
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_previews "  # noqa: S608
                "SET merged_away = :replacement WHERE preview_id = :preview"
            ),
            {
                "replacement": f'[{{"entity_id": "{MERGED_TWO}", "expected_version": 1}}]',
                "preview": report.preview.preview_id,
            },
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_version_that_moved_after_the_preview_makes_it_stale(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities SET version = version + 1 "  # noqa: S608
                "WHERE entity_id = :entity"
            ),
            {"entity": MERGED_ONE},
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == [
        "preview_stale",
        "stale_version",
    ]


def test_an_identifier_claimed_after_the_preview_cannot_be_bypassed(staged: Engine) -> None:
    """Section 27: a concurrent identifier claim cannot be bypassed by merge.

    The entity versions still agree -- binding an address writes a child row and
    advances no entity version -- so the binding digest matches and only the
    conflict digest can see it.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).bind_identifier(
            PRINCIPAL_A, MERGED_ONE, _identifier("xid_aaaa0001aaaa01", MERGED_ONE)
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert report.blockers == ()
    # The survivor acquires a *former* claim on the same address after the
    # preview was read. Nothing about either entity's version changes, and the
    # partial unique is untouched because the new row is not current.
    with staged.begin() as connection:
        SqlEntityRepository(connection).bind_identifier(
            PRINCIPAL_A,
            SURVIVOR,
            _identifier("xid_ssss0001ssss01", SURVIVOR, state=IdentifierState.RETIRED),
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_consumed_preview_cannot_produce_a_second_operation(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report, key="merge-two")
    assert [detail.value for detail in refused.value.safe_details] == [
        "identity_correction_conflict"
    ]
    assert _row_count(staged, "entity_identity_operations") == 1


def test_an_identical_retry_returns_the_prior_receipt_and_performs_nothing(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        first = _applied(connection, report)
    with staged.begin() as connection:
        second = _applied(connection, report)
    assert second.replayed is True
    assert second.operation.identity_operation_id == first.operation.identity_operation_id
    assert [effect.effect_id for effect in second.effects] == [
        effect.effect_id for effect in first.effects
    ]
    assert _row_count(staged, "entity_identity_operations") == 1
    assert _row_count(staged, "entity_identity_effects") == len(first.effects)


def test_the_same_key_carrying_a_different_request_conflicts(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report, reason="a materially different reason")
    assert [detail.value for detail in refused.value.safe_details] == ["idempotency_conflict"]
    assert _row_count(staged, "entity_identity_operations") == 1


# --- the operator's dispositions ---------------------------------------------


def _ambiguous_alias(engine: Engine) -> MergePreviewReport:
    with engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(
            PRINCIPAL_A, _alias("eals_ssss0001ssss01", SURVIVOR, state=AliasState.RETIRED)
        )
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE))
    with engine.begin() as connection:
        return _previewed(connection)


def test_a_required_choice_must_be_supplied_before_the_merge_is_admitted(
    staged: Engine,
) -> None:
    report = _ambiguous_alias(staged)
    assert report.required_choices == ("eals_aaaa0001aaaa01",)
    assert report.blockers == ()
    with pytest.raises(InvalidRequestError), staged.begin() as connection:
        _applied(connection, report)
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_disposition_for_a_record_that_needs_none_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    assert report.required_choices == ()
    with pytest.raises(InvalidRequestError), staged.begin() as connection:
        _applied(
            connection,
            report,
            choices=(("eals_aaaa0001aaaa01", ConflictChoice.REPARENT),),
        )


@pytest.mark.parametrize(
    ("choice", "expected_owner"),
    [(ConflictChoice.REPARENT, SURVIVOR), (ConflictChoice.COALESCE, MERGED_ONE)],
)
def test_the_operators_disposition_decides_the_ambiguous_alias(
    staged: Engine, choice: ConflictChoice, expected_owner: str
) -> None:
    report = _ambiguous_alias(staged)
    with staged.begin() as connection:
        _applied(
            connection,
            report,
            choices=(("eals_aaaa0001aaaa01", choice),),
        )
    with staged.connect() as connection:
        held = SqlEntityRepository(connection).aliases(PRINCIPAL_A, expected_owner)
    assert "eals_aaaa0001aaaa01" in {alias.alias_id for alias in held}


# --- privacy -----------------------------------------------------------------


def test_a_foreign_preview_is_indistinguishable_from_an_absent_one(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        foreign = repository.identity_preview(PRINCIPAL_B, report.preview.preview_id)
        absent = repository.identity_preview(PRINCIPAL_B, "eipv_ffff0006ffff0006")
    assert foreign is None
    assert foreign == absent


def test_no_effect_state_carries_a_name_an_address_or_a_statement(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE))
        repository.bind_identifier(
            PRINCIPAL_A, MERGED_ONE, _identifier("xid_aaaa0001aaaa01", MERGED_ONE)
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    rendered = str(
        [dict(effect.before_state) | dict(effect.after_state) for effect in receipt.effects]
    )
    assert "Ali" not in rendered
    assert "example.invalid" not in rendered
    assert "Alice" not in rendered
