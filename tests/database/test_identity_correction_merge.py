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
from threading import Event, Thread
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from my_pa.application.commands import MergeEntities, PreviewEntityMerge
from my_pa.application.entity_authoring import EntityAuthoringService
from my_pa.application.entity_governance import (
    EntityGovernanceService,
    EntityProposalReviewService,
    ProposalNotOpenError,
    ProposedEvidence,
    ReviewConflictError,
)
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
    SplitCommand,
    SplitPreviewCommand,
)
from my_pa.application.relationship_memory import (
    CreateMemoryCommand,
    MemoryProposalOrigin,
    ProposeMemoryCommand,
    RelationshipMemoryProposalService,
    RelationshipMemoryService,
    ReviseMemoryCommand,
)
from my_pa.application.relationship_memory import (
    ProposedEvidence as ProposedMemoryEvidence,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    MemoryWriteRequest,
    ProposalEvidenceConflictError,
    ReviewDecisionRequest,
    UnknownScopeError,
)
from my_pa.contracts.ports import (
    UnitOfWork as UnitOfWorkPort,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import CorrectionPatch, Disposition, ReviewNotFoundError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.relationship.authoring import HistoricalEntityError
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
    MergedEndpointError,
    RelationshipState,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityFactEvidenceLink,
    EntityObservation,
    EntityProposal,
    EntityProposalEvidenceLink,
    EntityProposalMethod,
    EntityProposalState,
    EntityResolutionDecision,
    EvidenceRole,
    MutationAuthority,
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
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryActorClass,
    MemoryAuthority,
    MemoryKind,
    MemoryOperation,
    MemoryProposalMethod,
    MemoryProposalState,
    MergedSubjectError,
    RelationshipMemoryProposal,
    StaleMemoryVersionError,
    classification_floor_for,
    memory_proposal_dedupe_digest,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
    dedupe_digest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.entity_proposal_review import (
    entity_proposal_review_cases,
)
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)
from my_pa.infrastructure.persistence.relationship_memory_proposals import (
    SqlRelationshipMemoryProposalRepository,
)
from my_pa.infrastructure.persistence.relationship_memory_review import (
    decide_relationship_memory_review,
    relationship_memory_review_cases,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork, _Reviews

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


def _entity(
    entity_id: str,
    principal_id: str = PRINCIPAL_A,
    name: str = "Alice Synthetic",
    entity_type: EntityType = EntityType.PERSON,
    *,
    version: int = 1,
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
        version=version,
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


@pytest.fixture
def unequal_staged(migrated_engine: Engine) -> Engine:
    """One survivor at N=4 and one source at N=2, plus the ordinary decoys."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(SURVIVOR, version=4))
        repository.create(
            PRINCIPAL_A,
            _entity(MERGED_ONE, name="Alice Synthetic Two", version=2),
        )
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
    return _typed_proposal(
        proposal_id,
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": entity_id, "alias_type": "nickname", "display_value": "Ali"},
        review_case_id=review_case_id,
    )


def _memory_proposal(
    proposal_id: str,
    review_case_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
    subject_entity_id: str = MERGED_ONE,
    context_entity_id: str = MERGED_ONE,
    expected_subject_version: int = 1,
) -> RelationshipMemoryProposal:
    statement = "Synthetic proposed memory before identity correction."
    context_links = (
        {
            "target_type": "entity",
            "target_id": context_entity_id,
            "role": "applies_in",
        },
    )
    statement_sha256 = statement_digest(statement)
    return RelationshipMemoryProposal(
        memory_proposal_id=proposal_id,
        principal_id=principal_id,
        subject_entity_id=subject_entity_id,
        expected_subject_version=expected_subject_version,
        proposed_kind=MemoryKind.GENERAL_NOTE,
        proposed_statement=statement,
        proposed_statement_sha256=statement_sha256,
        dedupe_sha256=memory_proposal_dedupe_digest(
            principal_id=principal_id,
            subject_entity_id=subject_entity_id,
            proposed_kind=MemoryKind.GENERAL_NOTE,
            proposed_statement_sha256=statement_sha256,
            structured_value=None,
            context_links=context_links,
        ),
        state=MemoryProposalState.NEEDS_REVIEW,
        method=MemoryProposalMethod.RULE,
        method_version="synthetic-origin-v1",
        classification=Classification.PRIVATE_LOCAL,
        proposed_at=WHEN,
        context_links=context_links,
        review_case_id=review_case_id,
    )


def _memory_review_request(
    review_case_id: str,
    disposition: Disposition,
    *,
    corrected_statement: str | None = None,
    principal_id: str = PRINCIPAL_A,
    expected_review_version: int = 0,
    decided_at: datetime = WHEN + timedelta(seconds=2),
) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=expected_review_version,
        disposition=disposition,
        principal_id=principal_id,
        correlation_id="corr_origin01origin01",
        audit_id="audit_origin01origin01",
        policy_version="policy-v1",
        decided_at=decided_at,
        correction_patch=(
            CorrectionPatch.of({"statement": corrected_statement})
            if corrected_statement is not None
            else None
        ),
    )


def _typed_proposal(
    proposal_id: str,
    kind: EntityProposalKind,
    values: dict[str, str | bool],
    *,
    expected_target_version: int | None = None,
    review_case_id: str | None = None,
) -> EntityProposal:
    payload = EntityProposalPayload.of(kind, values)
    return EntityProposal(
        proposal_id=proposal_id,
        principal_id=PRINCIPAL_A,
        kind=kind,
        state=EntityProposalState.PROPOSED,
        payload=payload,
        observation_ids=(),
        proposed_at=WHEN,
        proposed_by="synthetic-producer",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="v1",
        dedupe_sha256=dedupe_digest(payload),
        expected_target_version=expected_target_version,
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


def _memory_with_premerge_revision(
    connection: Connection, *, suffix: str
) -> tuple[str, int, ReviseMemoryCommand]:
    memory_service = RelationshipMemoryService()
    created = memory_service.create(
        SqlRelationshipMemoryRepository(connection),
        CreateMemoryCommand(
            principal_id=PRINCIPAL_A,
            subject_entity_id=MERGED_ONE,
            memory_kind=MemoryKind.GENERAL_NOTE,
            statement="Synthetic note captured before identity correction.",
            structured_value=None,
            context_links=(),
            pinned=False,
            observed_at=None,
            effective_from=None,
            effective_to=None,
            idempotency_key=f"aba-create-{suffix}",
        ),
        at=WHEN,
    ).receipt
    return (
        created.memory_id,
        created.aggregate_version,
        ReviseMemoryCommand(
            principal_id=PRINCIPAL_A,
            memory_id=created.memory_id,
            expected_version=created.aggregate_version,
            statement="Synthetic stale wording correction.",
            memory_kind=None,
            structured_value=None,
            context_links=(),
            pinned=None,
            observed_at=None,
            effective_from=None,
            effective_to=None,
            correction_reason="synthetic correction prepared before merge",
            idempotency_key=f"aba-stale-revise-{suffix}",
        ),
    )


class _PausingMergeRepository(SqlEntityRepository):
    """Expose the point after participant locks and before final revalidation."""

    def __init__(self, connection: Connection, locked: Event, release: Event) -> None:
        super().__init__(connection)
        self._locked = locked
        self._release = release

    def serialize_identifier_claim_keys(
        self, principal_id: str, claims: frozenset[tuple[str, str]]
    ) -> None:
        super().serialize_identifier_claim_keys(principal_id, claims)
        self._locked.set()
        if not self._release.wait(timeout=5):
            raise TimeoutError("the deterministic merge race was not released")


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


def _memory_review_row_counts(engine: Engine) -> tuple[int, int, int, int, int]:
    return (
        _row_count(engine, "relationship_memory_proposals"),
        _row_count(engine, "relationship_memory_review_decisions"),
        _row_count(engine, "relationship_memories"),
        _row_count(engine, "relationship_memory_versions"),
        _row_count(engine, "relationship_memory_context_links"),
    )


def _stale_memory_proposal(
    connection: Connection,
    *,
    subject_entity_id: str,
    expected_subject_version: int,
    at: datetime,
) -> None:
    subject = SqlEntityRepository(connection).get(PRINCIPAL_A, subject_entity_id)
    assert subject is not None
    RelationshipMemoryProposalService().propose(
        SqlRelationshipMemoryProposalRepository(connection),
        ProposeMemoryCommand(
            principal_id=PRINCIPAL_A,
            subject_entity_id=subject_entity_id,
            expected_subject_version=expected_subject_version,
            memory_kind=MemoryKind.GENERAL_NOTE,
            statement="Synthetic stale candidate after identity correction.",
            structured_value=None,
            evidence=(
                ProposedMemoryEvidence(
                    role=EvidenceLinkRole.DIRECT,
                    entity_observation_id="eobs_stale001stale01",
                ),
            ),
        ),
        subject=subject,
        origin=MemoryProposalOrigin(
            method=MemoryProposalMethod.RULE,
            method_version="synthetic-stale-cas-v1",
        ),
        at=at,
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


def test_merged_away_entities_are_normalized_before_preview_and_operation(staged: Engine) -> None:
    command = _preview_command(merged=((MERGED_TWO, 1), (MERGED_ONE, 1)))
    with staged.begin() as connection:
        report = _previewed(connection, command)
    assert report.preview.merged_away == ((MERGED_ONE, 1), (MERGED_TWO, 1))
    with staged.begin() as connection:
        receipt = _applied(connection, report)
    assert receipt.operation.merged_entity_ids == (MERGED_ONE, MERGED_TWO)


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
    redirected = next(
        effect
        for effect in receipt.effects
        if effect.family is IdentityEffectFamily.ENTITY and effect.record_id == MERGED_ONE
    )
    assert redirected.before_state["version"] == 1
    assert redirected.after_state["version"] == merged.version == 2
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert receipt.replayed is False
    # Nothing was deleted: the merged-away entity is still a readable row.
    assert _row_count(staged, "entities", "principal_id = 'prn_aaaa0001aaaa0001aaaa0001'") == 4


def test_premerge_memory_command_is_stale_after_governed_merge(staged: Engine) -> None:
    """RI-FC-WP-07: merge advances the memory CAS token from N to N+1."""
    with staged.begin() as connection:
        memory_id, premerge_version, stale_command = _memory_with_premerge_revision(
            connection, suffix="merge"
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report, key="merge-memory-aba")

    memory_effect = next(
        effect
        for effect in merge.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP_MEMORY
        and effect.record_id == memory_id
    )
    assert memory_effect.before_state["version"] == premerge_version
    assert memory_effect.after_state["version"] == premerge_version + 1
    assert memory_effect.after_state["subject_entity_id"] == SURVIVOR

    with staged.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.memory.version == premerge_version + 1
    assert detail.memory.subject_entity_id == SURVIVOR

    with pytest.raises(StaleMemoryVersionError), staged.begin() as connection:
        RelationshipMemoryService().revise(
            SqlRelationshipMemoryRepository(connection),
            stale_command,
            at=WHEN + timedelta(seconds=1),
            current_kind=MemoryKind.GENERAL_NOTE,
        )
    assert _row_count(staged, "relationship_memory_versions") == 1


def test_premerge_memory_command_is_stale_after_governed_merge_and_split(
    staged: Engine,
) -> None:
    """RI-FC-WP-07: split restores meaning while advancing N+1 to N+2."""
    with staged.begin() as connection:
        memory_id, premerge_version, stale_command = _memory_with_premerge_revision(
            connection, suffix="split"
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report, key="merge-memory-before-split")
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        split = _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-memory-aba",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id="corr_bbbb0002bbbb0002",
            audit_id="audit_bbbb0002bbbb0002",
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )

    merge_effect = next(
        effect
        for effect in merge.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP_MEMORY
        and effect.record_id == memory_id
    )
    split_effect = next(
        effect
        for effect in split.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP_MEMORY
        and effect.record_id == memory_id
    )
    assert merge_effect.before_state["version"] == premerge_version
    assert merge_effect.after_state["version"] == premerge_version + 1
    assert split_effect.before_state["version"] == premerge_version + 1
    assert split_effect.after_state["version"] == premerge_version + 2
    assert split_effect.after_state["subject_entity_id"] == MERGED_ONE

    with staged.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.memory.version == premerge_version + 2
    assert detail.memory.subject_entity_id == MERGED_ONE

    with pytest.raises(StaleMemoryVersionError), staged.begin() as connection:
        RelationshipMemoryService().revise(
            SqlRelationshipMemoryRepository(connection),
            stale_command,
            at=WHEN + timedelta(seconds=3),
            current_kind=MemoryKind.GENERAL_NOTE,
        )
    assert _row_count(staged, "relationship_memory_versions") == 1


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


def test_effect_after_states_equal_every_column_the_merge_writer_changes(staged: Engine) -> None:
    """A writer/effect mismatch makes the ledger insufficient for inversion."""
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_alias(PRINCIPAL_A, _alias("eals_aaaa0001aaaa01", MERGED_ONE))
        repository.bind_identifier(
            PRINCIPAL_A, MERGED_ONE, _identifier("xid_aaaa0001aaaa01", MERGED_ONE)
        )
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", MERGED_ONE))
        repository.record_relationship(PRINCIPAL_A, _edge("erel_aaaa0001aaaa01", MERGED_ONE, TOWER))
        repository.record_proposal(PRINCIPAL_A, _proposal("eprp_aaaa0001aaaa01", MERGED_ONE))
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        receipt = _applied(connection, report)

    effects = {(effect.family, effect.record_id): effect for effect in receipt.effects}
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        alias = next(row for row in repository.aliases(PRINCIPAL_A, SURVIVOR))
        identifier = next(row for row in repository.external_identifiers(PRINCIPAL_A, SURVIVOR))
        assignment = next(row for row in repository.assignments(PRINCIPAL_A, SURVIVOR))
        relationship = next(
            row
            for row in repository.relationships(PRINCIPAL_A, SURVIVOR)
            if row.relationship_id == "erel_aaaa0001aaaa01"
        )
        proposal = repository.proposal(PRINCIPAL_A, "eprp_aaaa0001aaaa01")

    def timestamp(value: datetime | None) -> str | None:
        return value.isoformat().replace("+00:00", "Z") if value is not None else None

    assert effects[(IdentityEffectFamily.ALIAS, alias.alias_id)].after_state == {
        "entity_id": alias.entity_id,
        "state": alias.state.value,
        "version": alias.version,
        "superseded_by_alias_id": alias.superseded_by_alias_id,
        "updated_at": timestamp(alias.updated_at),
    }
    assert effects[(IdentityEffectFamily.IDENTIFIER, identifier.identifier_id)].after_state == {
        "entity_id": identifier.entity_id,
        "state": identifier.state.value,
        "version": identifier.version,
        "superseded_by_identifier_id": identifier.superseded_by_identifier_id,
        "updated_at": timestamp(identifier.updated_at),
    }
    assert effects[(IdentityEffectFamily.ASSIGNMENT, assignment.assignment_id)].after_state == {
        "entity_id": assignment.entity_id,
        "scope_entity_id": assignment.scope_entity_id,
        "state": assignment.state.value,
        "version": assignment.version,
        "superseded_by_assignment_id": assignment.superseded_by_assignment_id,
        "updated_at": timestamp(assignment.updated_at),
    }
    relationship_effect = effects[(IdentityEffectFamily.RELATIONSHIP, relationship.relationship_id)]
    assert relationship_effect.after_state == {
        "from_entity_id": relationship.from_entity_id,
        "to_entity_id": relationship.to_entity_id,
        "scope_entity_id": relationship.scope_entity_id,
        "state": relationship.state.value,
        "version": relationship.version,
        "superseded_by_relationship_id": relationship.superseded_by_relationship_id,
        "updated_at": timestamp(relationship.updated_at),
    }
    assert proposal is not None
    assert effects[(IdentityEffectFamily.PROPOSAL, proposal.proposal_id)].after_state == {
        "state": proposal.state.value,
        "invalidated_reason": proposal.invalidated_reason,
        "decided_by": proposal.decided_by,
        "decided_at": timestamp(proposal.decided_at),
    }


@pytest.mark.parametrize(
    ("scope_entities", "claim_entity", "identifier_id"),
    [
        ((SURVIVOR, MERGED_ONE), SURVIVOR, "xid_aaaa0003aaaa03"),
        ((SURVIVOR, MERGED_ONE), TOWER, "xid_aaaa0004aaaa04"),
    ],
)
def test_identifier_writers_wait_for_merge_serialization_across_entity_scopes(
    staged: Engine,
    scope_entities: tuple[str, ...],
    claim_entity: str,
    identifier_id: str,
) -> None:
    """Former survivor claims and same-address outsider claims cannot slip in."""
    claim = _identifier(
        identifier_id,
        claim_entity,
        value="serialized@example.invalid",
        state=IdentifierState.RETIRED,
    )
    started = Event()
    finished = Event()
    failures: list[BaseException] = []

    def bind_claim() -> None:
        try:
            with staged.begin() as connection:
                started.set()
                SqlEntityRepository(connection).bind_identifier(PRINCIPAL_A, claim_entity, claim)
        except BaseException as error:  # pragma: no cover - asserted in the parent thread
            failures.append(error)
        finally:
            finished.set()

    with staged.connect() as locker:
        transaction = locker.begin()
        repository = SqlEntityRepository(locker)
        repository.serialize_identifier_entity_scopes(PRINCIPAL_A, scope_entities)
        repository.serialize_identifier_claim_keys(
            PRINCIPAL_A,
            ((claim.namespace.value, claim.normalized_value),),
        )
        worker = Thread(target=bind_claim, daemon=True)
        worker.start()
        assert started.wait(timeout=2)
        assert not finished.wait(timeout=0.25)
        transaction.commit()
        assert finished.wait(timeout=5)
        worker.join(timeout=1)

    assert failures == []
    with staged.connect() as connection:
        claims = SqlEntityRepository(connection).external_identifiers(PRINCIPAL_A, claim_entity)
    assert identifier_id in {row.identifier_id for row in claims}


@pytest.mark.parametrize(
    "writer_kind",
    [
        "entity",
        "alias",
        "assignment",
        "relationship",
        "observation",
        "proposal",
        "memory",
        "memory_proposal",
        "review_invalidate",
        "review_reprocess",
        "review_escalate",
        "review_accept",
        "fact_link",
        "memory_context",
        "memory_revise_context",
        "proposal_evidence",
    ],
)
def test_a_writer_waiting_after_final_merge_locking_loses_without_partial_state(
    staged: Engine, writer_kind: str
) -> None:
    """The causative interleaving: final analysis owns A, then a writer targets A."""
    if writer_kind in {"observation", "fact_link", "proposal_evidence"}:
        with staged.begin() as connection:
            SqlEntityRepository(connection).record_observation(
                PRINCIPAL_A,
                _observation(
                    "eobs_race0001race01",
                    MERGED_ONE if writer_kind == "observation" else None,
                ),
            )
    review_case_id = "rvw_race0001race0001"
    proposal_id = "eprp_race0002race02"
    revised_memory_id: str | None = None
    if writer_kind == "memory_revise_context":
        statement = "Synthetic note before concurrent context revision."
        with staged.begin() as connection:
            revised_memory_id = (
                SqlRelationshipMemoryRepository(connection)
                .admit(
                    MemoryWriteRequest(
                        operation=MemoryOperation.CREATE,
                        memory_id=None,
                        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                        expected_version=None,
                        principal_id=PRINCIPAL_A,
                        subject_entity_id=TOWER,
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
                        idempotency_key="race-memory-before-revise",
                        correlation_id=CORRELATION,
                        server_received_at=WHEN,
                    )
                )
                .receipt.memory_id
            )
    if writer_kind.startswith("review_"):
        with staged.begin() as connection:
            SqlEntityRepository(connection).record_proposal(
                PRINCIPAL_A,
                _proposal(proposal_id, MERGED_ONE, review_case_id=review_case_id),
            )
    if writer_kind == "proposal_evidence":
        with staged.begin() as connection:
            SqlEntityRepository(connection).record_proposal(
                PRINCIPAL_A,
                _proposal(
                    "eprp_race0003race03",
                    MERGED_ONE,
                    review_case_id="rvw_race0003race0003",
                ),
            )
    with staged.begin() as connection:
        report = _previewed(connection)

    merge_locked = Event()
    release_merge = Event()
    merge_done = Event()
    writer_started = Event()
    writer_done = Event()
    receipts: list[MergeReceipt] = []
    merge_failures: list[BaseException] = []
    writer_failures: list[BaseException] = []

    def apply_merge() -> None:
        try:
            with staged.begin() as connection:
                service = IdentityCorrectionService(
                    _PausingMergeRepository(connection, merge_locked, release_merge),
                    SqlRelationshipMemoryRepository(connection),
                )
                receipts.append(
                    service.apply(
                        MergeCommand(
                            principal_id=PRINCIPAL_A,
                            preview_id=report.preview.preview_id,
                            preview_digest=report.preview.preview_digest,
                            idempotency_key=f"race-{writer_kind}",
                            reason=REASON,
                        ),
                        at=WHEN,
                        correlation_id=CORRELATION,
                        audit_id=AUDIT,
                        performed_by=OPERATOR,
                        actor_class=ActorClass.USER,
                        has_operator_authority=True,
                    )
                )
        except BaseException as error:  # pragma: no cover - asserted below
            merge_failures.append(error)
        finally:
            merge_done.set()

    def write_child() -> None:
        try:
            with staged.begin() as connection:
                writer_started.set()
                repository = SqlEntityRepository(connection)
                if writer_kind == "entity":
                    EntityAuthoringService().update(
                        repository,
                        principal_id=PRINCIPAL_A,
                        entity_id=MERGED_ONE,
                        expected_version=1,
                        display_name="Alice Concurrent Synthetic",
                        canonical_name=None,
                        status=None,
                        reason="a synthetic concurrent correction",
                        idempotency_key="race-entity-update",
                        correlation_id=CORRELATION,
                        audit_id=AUDIT,
                        at=WHEN,
                    )
                elif writer_kind == "alias":
                    repository.record_alias(PRINCIPAL_A, _alias("eals_race0001race01", MERGED_ONE))
                elif writer_kind == "assignment":
                    repository.record_assignment(
                        PRINCIPAL_A, _assignment("asn_race0001race01", MERGED_ONE)
                    )
                elif writer_kind == "relationship":
                    repository.record_relationship(
                        PRINCIPAL_A,
                        _edge("erel_race0001race01", MERGED_ONE, TOWER),
                    )
                elif writer_kind == "observation":
                    repository.link_observation(PRINCIPAL_A, "eobs_race0001race01", TOWER)
                elif writer_kind == "proposal":
                    repository.record_proposal(
                        PRINCIPAL_A, _proposal("eprp_race0001race01", MERGED_ONE)
                    )
                elif writer_kind == "proposal_evidence":
                    EntityGovernanceService(repository).propose(
                        PRINCIPAL_A,
                        kind=EntityProposalKind.RECORD_ALIAS,
                        payload={
                            "entity_id": MERGED_ONE,
                            "alias_type": "nickname",
                            "display_value": "Ali",
                        },
                        observation_ids=(),
                        proposed_by="synthetic-producer",
                        method=EntityProposalMethod.DETERMINISTIC,
                        method_version="v1",
                        at=WHEN,
                        evidence=(
                            ProposedEvidence(
                                role=EvidenceRole.DIRECT,
                                entity_observation_id="eobs_race0001race01",
                            ),
                        ),
                    )
                elif writer_kind.startswith("review_"):
                    disposition = {
                        "review_invalidate": Disposition.INVALIDATE,
                        "review_reprocess": Disposition.REPROCESS,
                        "review_escalate": Disposition.ESCALATE,
                        "review_accept": Disposition.ACCEPT,
                    }[writer_kind]
                    review = EntityProposalReviewService(
                        repository,
                        _Reviews(
                            connection,
                            relationship_memory_enabled=False,
                            relationship_intelligence_enabled=True,
                        ),
                    )
                    review.decide(
                        ReviewDecisionRequest(
                            review_case_id=review_case_id,
                            expected_review_version=0,
                            disposition=disposition,
                            principal_id=PRINCIPAL_A,
                            correlation_id=CORRELATION,
                            audit_id=AUDIT,
                            policy_version="policy-v1",
                            decided_at=WHEN,
                            reason=(
                                "synthetic concurrent disposition"
                                if disposition in {Disposition.INVALIDATE, Disposition.ESCALATE}
                                else None
                            ),
                        ),
                        decided_by=OPERATOR,
                    )
                elif writer_kind == "fact_link":
                    repository.record_fact_evidence_link(
                        PRINCIPAL_A,
                        EntityFactEvidenceLink(
                            link_id="efev_race0001race01",
                            principal_id=PRINCIPAL_A,
                            role=EvidenceRole.COUNTEREVIDENCE,
                            authority=MutationAuthority.USER_CONFIRMED_ASSERTION,
                            created_at=WHEN,
                            entity_id=MERGED_ONE,
                            entity_observation_id="eobs_race0001race01",
                        ),
                    )
                elif writer_kind == "memory_revise_context":
                    revised = "Synthetic note after concurrent context revision."
                    SqlRelationshipMemoryRepository(connection).admit(
                        MemoryWriteRequest(
                            operation=MemoryOperation.REVISE,
                            memory_id=revised_memory_id,
                            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                            expected_version=1,
                            principal_id=PRINCIPAL_A,
                            subject_entity_id=None,
                            memory_kind=MemoryKind.GENERAL_NOTE,
                            statement=revised,
                            statement_sha256=statement_digest(revised),
                            structured_value=None,
                            authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                            classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                            created_by_actor=MemoryActorClass.USER,
                            context_links=(
                                {
                                    "target_type": "entity",
                                    "target_id": MERGED_ONE,
                                    "role": "applies_in",
                                },
                            ),
                            pinned=None,
                            observed_at=None,
                            effective_from=None,
                            effective_to=None,
                            correction_reason="synthetic correction",
                            idempotency_key="race-memory-revise-context",
                            correlation_id=CORRELATION,
                            server_received_at=WHEN,
                        )
                    )
                elif writer_kind in {"memory", "memory_context"}:
                    statement = "Synthetic concurrent relationship note."
                    SqlRelationshipMemoryRepository(connection).admit(
                        MemoryWriteRequest(
                            operation=MemoryOperation.CREATE,
                            memory_id=None,
                            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                            expected_version=None,
                            principal_id=PRINCIPAL_A,
                            subject_entity_id=(MERGED_ONE if writer_kind == "memory" else TOWER),
                            memory_kind=MemoryKind.GENERAL_NOTE,
                            statement=statement,
                            statement_sha256=statement_digest(statement),
                            structured_value=None,
                            authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                            classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                            created_by_actor=MemoryActorClass.USER,
                            context_links=(
                                ()
                                if writer_kind == "memory"
                                else (
                                    {
                                        "target_type": "entity",
                                        "target_id": MERGED_ONE,
                                        "role": "applies_in",
                                    },
                                )
                            ),
                            pinned=False,
                            observed_at=None,
                            effective_from=None,
                            effective_to=None,
                            correction_reason=None,
                            idempotency_key="race-memory",
                            correlation_id=CORRELATION,
                            server_received_at=WHEN,
                        )
                    )
                else:
                    statement = "Synthetic concurrent proposed memory."
                    proposal_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
                    proposed_sha = statement_digest(statement)
                    SqlRelationshipMemoryProposalRepository(connection).record_proposal(
                        RelationshipMemoryProposal(
                            memory_proposal_id=proposal_id,
                            principal_id=PRINCIPAL_A,
                            subject_entity_id=MERGED_ONE,
                            expected_subject_version=1,
                            proposed_kind=MemoryKind.GENERAL_NOTE,
                            proposed_statement=statement,
                            proposed_statement_sha256=proposed_sha,
                            dedupe_sha256=memory_proposal_dedupe_digest(
                                principal_id=PRINCIPAL_A,
                                subject_entity_id=MERGED_ONE,
                                proposed_kind=MemoryKind.GENERAL_NOTE,
                                proposed_statement_sha256=proposed_sha,
                                structured_value=None,
                            ),
                            state=MemoryProposalState.PROPOSED,
                            method=MemoryProposalMethod.RULE,
                            method_version="synthetic-v1",
                            classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                            proposed_at=WHEN,
                        ),
                        (),
                    )
        except BaseException as error:  # pragma: no cover - asserted below
            writer_failures.append(error)
        finally:
            writer_done.set()

    merge_thread = Thread(target=apply_merge, daemon=True)
    merge_thread.start()
    assert merge_locked.wait(timeout=5)
    writer_thread = Thread(target=write_child, daemon=True)
    writer_thread.start()
    assert writer_started.wait(timeout=2)
    assert not writer_done.wait(timeout=0.25)
    release_merge.set()
    assert merge_done.wait(timeout=5)
    assert writer_done.wait(timeout=5)
    merge_thread.join(timeout=1)
    writer_thread.join(timeout=1)

    assert merge_failures == []
    assert len(receipts) == 1
    assert receipts[0].operation.state is IdentityOperationState.COMPLETED
    assert len(writer_failures) == 1
    expected_failure = {
        "entity": HistoricalEntityError,
        "alias": MergedEndpointError,
        "assignment": MergedEndpointError,
        "relationship": MergedEndpointError,
        "observation": UnknownScopeError,
        "proposal": MergedEndpointError,
        "memory": MergedSubjectError,
        "memory_proposal": ValueError,
        "review_invalidate": ReviewConflictError,
        "review_reprocess": ReviewConflictError,
        "review_escalate": ReviewConflictError,
        "review_accept": ReviewConflictError,
        "fact_link": MergedEndpointError,
        "memory_context": MergedSubjectError,
        "memory_revise_context": MergedSubjectError,
        "proposal_evidence": ProposalNotOpenError,
    }[writer_kind]
    assert type(writer_failures[0]) is expected_failure
    assert not isinstance(writer_failures[0], TimeoutError)
    if writer_kind == "memory_proposal":
        assert "merged-away subject" in str(writer_failures[0])
    assert _row_count(staged, "entity_identity_operations", "state = 'in_progress'") == 0
    assert _row_count(staged, "entity_identity_effects") == len(receipts[0].effects)
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 1
    assert _row_count(staged, "entity_aliases", "alias_id = 'eals_race0001race01'") == 0
    assert _row_count(staged, "entity_assignments", "assignment_id = 'asn_race0001race01'") == 0
    assert (
        _row_count(staged, "entity_relationships", "relationship_id = 'erel_race0001race01'") == 0
    )
    assert _row_count(staged, "entity_proposals", "proposal_id = 'eprp_race0001race01'") == 0
    assert _row_count(staged, "relationship_memories") == (
        1 if writer_kind == "memory_revise_context" else 0
    )
    if writer_kind == "memory_revise_context":
        assert _row_count(staged, "relationship_memory_versions") == 1
        assert _row_count(staged, "relationship_memory_context_links") == 0
    assert _row_count(staged, "relationship_memory_proposals") == 0
    assert _row_count(staged, "entity_fact_evidence_links", "link_id = 'efev_race0001race01'") == 0
    if writer_kind == "proposal_evidence":
        assert _row_count(staged, "entity_proposal_evidence_links") == 0
    if writer_kind.startswith("review_"):
        assert _row_count(staged, "entity_proposal_review_decisions") == 0
        assert _row_count(staged, "entity_proposals", "state <> 'invalidated'") == 0
    if writer_kind == "observation":
        with staged.connect() as connection:
            observation = SqlEntityRepository(connection).observation(
                PRINCIPAL_A, "eobs_race0001race01"
            )
        assert observation is not None
        assert observation.entity_id == SURVIVOR
        observation_effect = next(
            effect
            for effect in receipts[0].effects
            if effect.family is IdentityEffectFamily.OBSERVATION
            and effect.record_id == observation.observation_id
        )
        assert observation_effect.after_state["entity_id"] == observation.entity_id


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


def test_an_observation_added_after_preview_makes_the_plan_stale(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL_A, _observation("eobs_aaaa0001aaaa01", MERGED_ONE)
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_proposal_added_after_preview_makes_the_plan_stale(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal(
            PRINCIPAL_A, _proposal("eprp_aaaa0001aaaa01", MERGED_ONE)
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_ledger_only_review_decision_after_preview_makes_the_plan_stale(
    staged: Engine,
) -> None:
    review_case_id = "rvw_stal0001stal0001"
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal(
            PRINCIPAL_A,
            _proposal("eprp_stal0001stal01", MERGED_ONE, review_case_id=review_case_id),
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        EntityProposalReviewService(
            SqlEntityRepository(connection),
            _Reviews(
                connection,
                relationship_memory_enabled=False,
                relationship_intelligence_enabled=True,
            ),
        ).decide(
            ReviewDecisionRequest(
                review_case_id=review_case_id,
                expected_review_version=0,
                disposition=Disposition.ESCALATE,
                principal_id=PRINCIPAL_A,
                correlation_id=CORRELATION,
                audit_id=AUDIT,
                policy_version="policy-v1",
                decided_at=WHEN,
                reason="synthetic escalation",
            ),
            decided_by=OPERATOR,
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_review_started_after_merge_reports_canonical_conflict(staged: Engine) -> None:
    review_case_id = "rvw_post0001post0001"
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal(
            PRINCIPAL_A,
            _proposal("eprp_post0001post01", MERGED_ONE, review_case_id=review_case_id),
        )
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)

    with pytest.raises(ReviewConflictError), staged.begin() as connection:
        EntityProposalReviewService(
            SqlEntityRepository(connection),
            _Reviews(
                connection,
                relationship_memory_enabled=False,
                relationship_intelligence_enabled=True,
            ),
        ).decide(
            ReviewDecisionRequest(
                review_case_id=review_case_id,
                expected_review_version=0,
                disposition=Disposition.ESCALATE,
                principal_id=PRINCIPAL_A,
                correlation_id=CORRELATION,
                audit_id=AUDIT,
                policy_version="policy-v1",
                decided_at=WHEN,
                reason="synthetic post-merge escalation",
            ),
            decided_by=OPERATOR,
        )
    assert _row_count(staged, "entity_proposal_review_decisions") == 0


def test_a_direct_evidence_append_after_merge_fails_closed(staged: Engine) -> None:
    proposal_id = "eprp_evap0001evap01"
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation("eobs_evap0001evap01", None))
        repository.record_proposal(PRINCIPAL_A, _proposal(proposal_id, MERGED_ONE))
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)

    with pytest.raises(ProposalEvidenceConflictError), staged.begin() as connection:
        SqlEntityRepository(connection).record_proposal_evidence_link(
            PRINCIPAL_A,
            EntityProposalEvidenceLink(
                proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                sequence=1,
                role=EvidenceRole.DIRECT,
                created_at=WHEN,
                entity_observation_id="eobs_evap0001evap01",
            ),
        )
    assert _row_count(staged, "entity_proposal_evidence_links") == 0


def test_a_direct_evidence_append_waiting_on_review_close_fails_closed(
    staged: Engine,
) -> None:
    proposal_id = "eprp_empty001empty01"
    review_case_id = "rvw_empty001empty0001"
    observation_id = "eobs_empty001empty01"
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation(observation_id, None))
        repository.record_proposal(
            PRINCIPAL_A,
            _typed_proposal(
                proposal_id,
                EntityProposalKind.CREATE_ENTITY,
                {"entity_type": "person", "display_name": "Synthetic Empty Scope"},
                review_case_id=review_case_id,
            ),
        )

    review_decided = Event()
    release_review = Event()
    review_done = Event()
    writer_started = Event()
    writer_done = Event()
    review_failures: list[BaseException] = []
    writer_failures: list[BaseException] = []

    def close_review() -> None:
        try:
            with staged.begin() as connection:
                EntityProposalReviewService(
                    SqlEntityRepository(connection),
                    _Reviews(
                        connection,
                        relationship_memory_enabled=False,
                        relationship_intelligence_enabled=True,
                    ),
                ).decide(
                    ReviewDecisionRequest(
                        review_case_id=review_case_id,
                        expected_review_version=0,
                        disposition=Disposition.REJECT,
                        principal_id=PRINCIPAL_A,
                        correlation_id=CORRELATION,
                        audit_id=AUDIT,
                        policy_version="policy-v1",
                        decided_at=WHEN,
                        reason="synthetic review rejection",
                    ),
                    decided_by=OPERATOR,
                )
                review_decided.set()
                if not release_review.wait(timeout=5):
                    raise TimeoutError("the deterministic review race was not released")
        except BaseException as error:  # pragma: no cover - asserted below
            review_failures.append(error)
        finally:
            review_done.set()

    def append_evidence() -> None:
        try:
            with staged.begin() as connection:
                writer_started.set()
                SqlEntityRepository(connection).record_proposal_evidence_link(
                    PRINCIPAL_A,
                    EntityProposalEvidenceLink(
                        proposal_id=proposal_id,
                        principal_id=PRINCIPAL_A,
                        sequence=1,
                        role=EvidenceRole.DIRECT,
                        created_at=WHEN,
                        entity_observation_id=observation_id,
                    ),
                )
        except BaseException as error:  # pragma: no cover - asserted below
            writer_failures.append(error)
        finally:
            writer_done.set()

    review_thread = Thread(target=close_review, daemon=True)
    review_thread.start()
    assert review_decided.wait(timeout=5)
    writer_thread = Thread(target=append_evidence, daemon=True)
    writer_thread.start()
    assert writer_started.wait(timeout=2)
    assert not writer_done.wait(timeout=0.25)
    release_review.set()
    assert review_done.wait(timeout=5)
    assert writer_done.wait(timeout=5)
    review_thread.join(timeout=1)
    writer_thread.join(timeout=1)

    assert review_failures == []
    assert len(writer_failures) == 1
    assert type(writer_failures[0]) is ProposalEvidenceConflictError
    assert not isinstance(writer_failures[0], TimeoutError)
    assert _row_count(staged, "entity_proposal_evidence_links") == 0
    assert _row_count(staged, "entity_proposals", "state = 'rejected'") == 1


def test_a_source_link_added_after_preview_makes_the_plan_stale(staged: Engine) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_observation(PRINCIPAL_A, _observation("eobs_link0001link01", None))
        report = _previewed(connection)
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_fact_evidence_link(
            PRINCIPAL_A,
            EntityFactEvidenceLink(
                link_id="efev_link0001link01",
                principal_id=PRINCIPAL_A,
                role=EvidenceRole.COUNTEREVIDENCE,
                authority=MutationAuthority.USER_CONFIRMED_ASSERTION,
                created_at=WHEN,
                entity_id=MERGED_ONE,
                entity_observation_id="eobs_link0001link01",
            ),
        )
    with pytest.raises(ConflictError) as refused, staged.begin() as connection:
        _applied(connection, report)
    assert [detail.value for detail in refused.value.safe_details] == ["preview_stale"]
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0


def test_a_current_memory_context_link_to_the_merged_identity_reparents_with_origin(
    staged: Engine,
) -> None:
    statement = "Synthetic context-bound note."
    with staged.begin() as connection:
        SqlRelationshipMemoryRepository(connection).admit(
            MemoryWriteRequest(
                operation=MemoryOperation.CREATE,
                memory_id=None,
                memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                expected_version=None,
                principal_id=PRINCIPAL_A,
                subject_entity_id=TOWER,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement=statement,
                statement_sha256=statement_digest(statement),
                structured_value=None,
                authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
                classification=classification_floor_for(MemoryKind.GENERAL_NOTE),
                created_by_actor=MemoryActorClass.USER,
                context_links=(
                    {
                        "target_type": "entity",
                        "target_id": MERGED_ONE,
                        "role": "applies_in",
                    },
                ),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason=None,
                idempotency_key="context-blocker",
                correlation_id=CORRELATION,
                server_received_at=WHEN,
            )
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.RELATIONSHIP_MEMORY) == (
        FamilyDisposition.TRANSFORMED,
        1,
    )
    assert _group(report, MergeFamily.DERIVED_CONTEXT) == (
        FamilyDisposition.NOT_BOUND,
        0,
    )
    assert report.conflicts == ()
    context_effect = next(
        effect
        for effect in report.projected_effects
        if effect.family is IdentityEffectFamily.MEMORY_CONTEXT_LINK
    )
    assert context_effect.before_state == {
        "target_id": MERGED_ONE,
        "origin_subject_entity_id": MERGED_ONE,
    }
    assert context_effect.after_state == {
        "target_id": SURVIVOR,
        "origin_subject_entity_id": MERGED_ONE,
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


def test_every_typed_entity_reference_field_invalidates_an_open_proposal(
    staged: Engine,
) -> None:
    cases: tuple[tuple[str, EntityProposalKind, dict[str, str | bool], int | None], ...] = (
        (
            "eprp_refa0001refa01",
            EntityProposalKind.UPDATE_ENTITY,
            {"entity_id": MERGED_ONE, "display_name": "Alicia", "reason": "correction"},
            1,
        ),
        (
            "eprp_refb0002refb02",
            EntityProposalKind.BIND_IDENTIFIER,
            {"entity_id": MERGED_ONE, "namespace": "email", "display_value": "a@x.invalid"},
            None,
        ),
        (
            "eprp_refc0003refc03",
            EntityProposalKind.RETIRE_IDENTIFIER,
            {"entity_id": MERGED_ONE, "identifier_id": "xid_aaaa0001aaaa01", "reason": "old"},
            1,
        ),
        (
            "eprp_refd0004refd04",
            EntityProposalKind.SUPERSEDE_IDENTIFIER,
            {
                "entity_id": MERGED_ONE,
                "identifier_id": "xid_aaaa0001aaaa01",
                "namespace": "email",
                "display_value": "b@x.invalid",
                "reason": "changed",
            },
            1,
        ),
        (
            "eprp_refe0005refe05",
            EntityProposalKind.RECORD_ALIAS,
            {"entity_id": MERGED_ONE, "alias_type": "nickname", "display_value": "Ali"},
            None,
        ),
        (
            "eprp_reff0006reff06",
            EntityProposalKind.RETIRE_ALIAS,
            {"entity_id": MERGED_ONE, "alias_id": "eals_aaaa0001aaaa01", "reason": "old"},
            1,
        ),
        (
            "eprp_refg0007refg07",
            EntityProposalKind.SUPERSEDE_ALIAS,
            {
                "entity_id": MERGED_ONE,
                "alias_id": "eals_aaaa0001aaaa01",
                "alias_type": "nickname",
                "display_value": "Allie",
                "reason": "changed",
            },
            1,
        ),
        (
            "eprp_refh0008refh08",
            EntityProposalKind.RECORD_ASSIGNMENT,
            {"entity_id": MERGED_ONE, "assignment_type": "project_assignment"},
            None,
        ),
        (
            "eprp_refi0009refi09",
            EntityProposalKind.RECORD_ASSIGNMENT,
            {
                "entity_id": SURVIVOR,
                "assignment_type": "project_assignment",
                "scope_entity_id": MERGED_ONE,
            },
            None,
        ),
        (
            "eprp_refj0010refj10",
            EntityProposalKind.RECORD_RELATIONSHIP,
            {
                "from_entity_id": MERGED_ONE,
                "relationship_type": "affiliated_with",
                "to_entity_id": TOWER,
            },
            None,
        ),
        (
            "eprp_refk0011refk11",
            EntityProposalKind.RECORD_RELATIONSHIP,
            {
                "from_entity_id": TOWER,
                "relationship_type": "affiliated_with",
                "to_entity_id": MERGED_ONE,
            },
            None,
        ),
        (
            "eprp_refl0012refl12",
            EntityProposalKind.RECORD_RELATIONSHIP,
            {
                "from_entity_id": SURVIVOR,
                "relationship_type": "affiliated_with",
                "to_entity_id": TOWER,
                "scope_entity_id": MERGED_ONE,
            },
            None,
        ),
        (
            "eprp_refm0013refm13",
            EntityProposalKind.RESOLVE_MENTION,
            {
                "observation_id": "eobs_aaaa0001aaaa01",
                "disposition": "link_existing",
                "entity_id": MERGED_ONE,
            },
            0,
        ),
        (
            "eprp_refn0014refn14",
            EntityProposalKind.RESOLVE_MENTION,
            {
                "observation_id": "eobs_bbbb0002bbbb02",
                "disposition": "reject",
                "rejected_entity_id": MERGED_ONE,
                "reason": "not this person",
            },
            0,
        ),
        (
            "eprp_refo0015refo15",
            EntityProposalKind.MERGE_ENTITIES,
            {"retained_entity_id": MERGED_ONE, "merged_entity_id": TOWER},
            None,
        ),
        (
            "eprp_refp0016refp16",
            EntityProposalKind.MERGE_ENTITIES,
            {"retained_entity_id": SURVIVOR, "merged_entity_id": MERGED_ONE},
            None,
        ),
        (
            "eprp_refq0017refq17",
            EntityProposalKind.SPLIT_IDENTITY,
            # WP-06 / RI-P4-HIGH-001 made `source_identity_operation_id`
            # required, so the payload now names the governed merge the split
            # would reverse. Inert to what this case asserts -- it needs only a
            # split proposal referencing MERGED_ONE for the merge to invalidate.
            {"entity_id": MERGED_ONE, "source_identity_operation_id": "eiop_aaaa0001aaaa0001"},
            None,
        ),
    )
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        for proposal_id, kind, payload, expected_target_version in cases:
            repository.record_proposal(
                PRINCIPAL_A,
                _typed_proposal(
                    proposal_id,
                    kind,
                    payload,
                    expected_target_version=expected_target_version,
                ),
            )

    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (
        FamilyDisposition.TRANSFORMED,
        len(cases),
    )
    with staged.begin() as connection:
        _applied(connection, report)

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        invalidated = [
            repository.proposal(PRINCIPAL_A, proposal_id) for proposal_id, _, _, _ in cases
        ]
    assert all(
        proposal is not None and proposal.state is EntityProposalState.INVALIDATED
        for proposal in invalidated
    )


def test_an_entity_id_in_ordinary_payload_text_is_not_a_reference(staged: Engine) -> None:
    text_match = _typed_proposal(
        "eprp_text0001text01",
        EntityProposalKind.CREATE_ENTITY,
        {"entity_type": "person", "display_name": MERGED_ONE},
    )
    actual_reference = _proposal("eprp_refx0001refx01", MERGED_ONE)
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_proposal(PRINCIPAL_A, text_match)
        repository.record_proposal(PRINCIPAL_A, actual_reference)

    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)

    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        text_after = repository.proposal(PRINCIPAL_A, text_match.proposal_id)
        reference_after = repository.proposal(PRINCIPAL_A, actual_reference.proposal_id)
    assert text_after is not None
    assert text_after.state is EntityProposalState.PROPOSED
    assert reference_after is not None
    assert reference_after.state is EntityProposalState.INVALIDATED


@pytest.mark.parametrize(
    ("kind", "payload", "proposal_id"),
    [
        (
            EntityProposalKind.REVISE_ASSIGNMENT,
            {"assignment_id": "asn_aaaa0001aaaa01", "role": "lead"},
            "eprp_indr0001indr01",
        ),
        (
            EntityProposalKind.END_ASSIGNMENT,
            {"assignment_id": "asn_aaaa0001aaaa01", "reason": "ended", "end_now": True},
            "eprp_indr0002indr02",
        ),
        (
            EntityProposalKind.REVISE_RELATIONSHIP,
            {"relationship_id": "erel_aaaa0001aaaa01", "effective_to": "2027-01-01T00:00:00Z"},
            "eprp_indr0003indr03",
        ),
        (
            EntityProposalKind.END_RELATIONSHIP,
            {"relationship_id": "erel_aaaa0001aaaa01", "reason": "ended", "end_now": True},
            "eprp_indr0004indr04",
        ),
    ],
)
def test_a_proposal_targeting_a_child_of_the_merged_identity_is_invalidated(
    staged: Engine,
    kind: EntityProposalKind,
    payload: dict[str, str | bool],
    proposal_id: str,
) -> None:
    with staged.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.record_assignment(PRINCIPAL_A, _assignment("asn_aaaa0001aaaa01", MERGED_ONE))
        repository.record_relationship(PRINCIPAL_A, _edge("erel_aaaa0001aaaa01", MERGED_ONE, TOWER))
        review_case_id = f"rvw_{proposal_id.removeprefix('eprp_')}"
        repository.record_proposal(
            PRINCIPAL_A,
            _typed_proposal(
                proposal_id,
                kind,
                payload,
                expected_target_version=1,
                review_case_id=review_case_id,
            ),
        )

    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ENTITY_PROPOSAL) == (
        FamilyDisposition.TRANSFORMED,
        1,
    )
    assert _group(report, MergeFamily.REVIEW_CASE) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        receipt = _applied(connection, report)

    affected = {(effect.family, effect.record_id, effect.kind) for effect in receipt.effects}
    assert (
        IdentityEffectFamily.PROPOSAL,
        proposal_id,
        IdentityEffectKind.DEPENDENT_INVALIDATED,
    ) in affected
    assert (
        IdentityEffectFamily.REVIEW_CASE,
        review_case_id,
        IdentityEffectKind.DEPENDENT_INVALIDATED,
    ) in affected
    with staged.connect() as connection:
        proposal = SqlEntityRepository(connection).proposal(PRINCIPAL_A, proposal_id)
        cases = entity_proposal_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)
    assert proposal is not None
    assert proposal.state is EntityProposalState.INVALIDATED
    case = next(case for case in cases if case.review_case_id == review_case_id)
    assert case.proposal_state is ProposalState.INVALIDATED
    assert case.latest_disposition is None


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
            payload={
                "entity_id": MERGED_ONE,
                "display_name": "Alice Synthetic Corrected",
                "reason": "a synthetic correction",
            },
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
            payload={
                "entity_id": MERGED_ONE,
                "display_name": "Alice Synthetic Corrected",
                "reason": "a synthetic correction",
            },
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
    snapshot = {
        "review_version": 0,
        "latest_disposition": None,
        "escalated": False,
    }
    assert case_effect.before_state == {"state": "needs_review", **snapshot}
    assert case_effect.after_state == {"state": "invalidated", **snapshot}
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


@pytest.mark.parametrize(
    ("disposition", "proposal_id", "review_case_id", "corrected_statement"),
    [
        (
            Disposition.ACCEPT,
            "mprop_origin01origin01",
            "rvw_origin0001origin001",
            None,
        ),
        (
            Disposition.CORRECT_AND_ACCEPT,
            "mprop_origin02origin02",
            "rvw_origin0002origin002",
            "Synthetic reviewer-corrected memory after identity correction.",
        ),
    ],
)
def test_proposal_merge_acceptance_rebinds_the_unequal_current_subject_token(
    unequal_staged: Engine,
    disposition: Disposition,
    proposal_id: str,
    review_case_id: str,
    corrected_statement: str | None,
) -> None:
    proposal = _memory_proposal(
        proposal_id,
        review_case_id,
        expected_subject_version=2,
    )
    with unequal_staged.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(proposal, ())
    with unequal_staged.begin() as connection:
        report = _previewed(
            connection,
            _preview_command(
                merged=((MERGED_ONE, 2),),
                survivor_version=4,
            ),
        )
    assert _group(report, MergeFamily.RELATIONSHIP_MEMORY) == (
        FamilyDisposition.TRANSFORMED,
        1,
    )
    with unequal_staged.begin() as connection:
        _applied(connection, report, key=f"merge-{disposition.value}-origin")

    with unequal_staged.connect() as connection:
        merged_proposal = connection.execute(
            text(
                f"SELECT subject_entity_id, origin_subject_entity_id, "  # noqa: S608
                f"expected_subject_version, context_links "
                f"FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {"proposal_id": proposal_id, "principal_id": PRINCIPAL_A},
        ).one()
    assert merged_proposal.subject_entity_id == SURVIVOR
    assert merged_proposal.origin_subject_entity_id == MERGED_ONE
    assert merged_proposal.expected_subject_version == 4
    assert merged_proposal.context_links == [
        {
            "target_type": "entity",
            "target_id": SURVIVOR,
            "origin_subject_entity_id": MERGED_ONE,
            "role": "applies_in",
        }
    ]

    before_stale_proposal = _memory_review_row_counts(unequal_staged)
    with pytest.raises(StaleMemoryVersionError), unequal_staged.begin() as connection:
        _stale_memory_proposal(
            connection,
            subject_entity_id=SURVIVOR,
            expected_subject_version=2,
            at=WHEN + timedelta(seconds=1),
        )
    assert _memory_review_row_counts(unequal_staged) == before_stale_proposal

    before_refusals = _memory_review_row_counts(unequal_staged)
    with pytest.raises(ReviewNotFoundError), unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
                principal_id=PRINCIPAL_B,
            ),
        )
    assert _memory_review_row_counts(unequal_staged) == before_refusals
    with pytest.raises(ReviewConflictError), unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
                expected_review_version=1,
            ),
        )
    assert _memory_review_row_counts(unequal_staged) == before_refusals

    with unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
            ),
        )
    with unequal_staged.connect() as connection:
        accepted = connection.execute(
            text(
                f"SELECT accepted_memory_id, accepted_memory_version_id, "  # noqa: S608
                f"origin_subject_entity_id FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {"proposal_id": proposal_id, "principal_id": PRINCIPAL_A},
        ).one()
        memory = connection.execute(
            text(
                f"SELECT principal_id, subject_entity_id, origin_subject_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.relationship_memories WHERE memory_id = :memory_id"
            ),
            {"memory_id": accepted.accepted_memory_id},
        ).one()
        context = connection.execute(
            text(
                f"SELECT principal_id, target_id, origin_subject_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.relationship_memory_context_links "
                "WHERE memory_version_id = :version_id"
            ),
            {"version_id": accepted.accepted_memory_version_id},
        ).one()
        foreign_detail = SqlRelationshipMemoryRepository(connection).detail(
            accepted.accepted_memory_id, principal_id=PRINCIPAL_B
        )
        foreign_cases = relationship_memory_review_cases(
            connection, principal_id=PRINCIPAL_B, limit=10
        )

    assert accepted.origin_subject_entity_id == MERGED_ONE
    assert memory.principal_id == PRINCIPAL_A
    assert memory.subject_entity_id == SURVIVOR
    assert memory.origin_subject_entity_id == MERGED_ONE
    assert context.principal_id == PRINCIPAL_A
    assert context.target_id == SURVIVOR
    assert context.origin_subject_entity_id == MERGED_ONE
    assert foreign_detail is None
    assert foreign_cases == ()


def test_proposal_merge_reprocess_preserves_origin_on_the_successor(
    staged: Engine,
) -> None:
    proposal_id = "mprop_origin03origin03"
    review_case_id = "rvw_origin0003origin003"
    with staged.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(
            _memory_proposal(proposal_id, review_case_id), ()
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report, key="merge-reprocess-origin")
    with staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(review_case_id, Disposition.REPROCESS),
        )

    with staged.connect() as connection:
        predecessor = connection.execute(
            text(
                f"SELECT origin_subject_entity_id, superseded_by_memory_proposal_id "  # noqa: S608
                f"FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {"proposal_id": proposal_id, "principal_id": PRINCIPAL_A},
        ).one()
        successor = connection.execute(
            text(
                f"SELECT principal_id, subject_entity_id, origin_subject_entity_id, "  # noqa: S608
                f"context_links, expected_subject_version FROM "
                f"{SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {
                "proposal_id": predecessor.superseded_by_memory_proposal_id,
                "principal_id": PRINCIPAL_A,
            },
        ).one()
        foreign_cases = relationship_memory_review_cases(
            connection, principal_id=PRINCIPAL_B, limit=10
        )

    assert predecessor.origin_subject_entity_id == MERGED_ONE
    assert successor.principal_id == PRINCIPAL_A
    assert successor.subject_entity_id == SURVIVOR
    assert successor.origin_subject_entity_id == MERGED_ONE
    assert successor.context_links == [
        {
            "target_type": "entity",
            "target_id": SURVIVOR,
            "origin_subject_entity_id": MERGED_ONE,
            "role": "applies_in",
        }
    ]
    assert successor.expected_subject_version == 1
    assert _row_count(staged, "relationship_memories") == 0
    assert foreign_cases == ()


@pytest.mark.parametrize(
    ("disposition", "proposal_id", "review_case_id", "corrected_statement"),
    [
        (
            Disposition.ACCEPT,
            "mprop_split001split001",
            "rvw_split0001split001",
            None,
        ),
        (
            Disposition.CORRECT_AND_ACCEPT,
            "mprop_split002split002",
            "rvw_split0002split002",
            "Synthetic reviewer-corrected memory after split.",
        ),
        (
            Disposition.REPROCESS,
            "mprop_split003split003",
            "rvw_split0003split003",
            None,
        ),
    ],
)
def test_proposal_split_review_rebinds_the_restored_current_subject_token(
    unequal_staged: Engine,
    disposition: Disposition,
    proposal_id: str,
    review_case_id: str,
    corrected_statement: str | None,
) -> None:
    with unequal_staged.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(
            _memory_proposal(
                proposal_id,
                review_case_id,
                expected_subject_version=2,
            ),
            (),
        )
    with unequal_staged.begin() as connection:
        merge_report = _previewed(
            connection,
            _preview_command(
                merged=((MERGED_ONE, 2),),
                survivor_version=4,
            ),
        )
    with unequal_staged.begin() as connection:
        merge = _applied(
            connection,
            merge_report,
            key=f"merge-before-split-{disposition.value}",
        )
    with unequal_staged.begin() as connection:
        split_report = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the unequal-version synthetic merge",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with unequal_staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_report.preview.preview_id,
                preview_digest=split_report.preview.preview_digest,
                idempotency_key=f"split-before-{disposition.value}",
                reason="reverse the unequal-version synthetic merge",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id="corr_split001split001",
            audit_id="audit_split001split001",
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )

    with unequal_staged.connect() as connection:
        restored_entity = SqlEntityRepository(connection).get(PRINCIPAL_A, MERGED_ONE)
        restored_proposal = connection.execute(
            text(
                f"SELECT subject_entity_id, origin_subject_entity_id, "  # noqa: S608
                f"expected_subject_version, context_links "
                f"FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {"proposal_id": proposal_id, "principal_id": PRINCIPAL_A},
        ).one()
    assert restored_entity is not None
    assert restored_entity.status is EntityStatus.ACTIVE
    assert restored_entity.version == 4
    assert restored_proposal.subject_entity_id == MERGED_ONE
    assert restored_proposal.origin_subject_entity_id == MERGED_ONE
    assert restored_proposal.expected_subject_version == restored_entity.version
    assert restored_proposal.context_links == [
        {
            "target_type": "entity",
            "target_id": MERGED_ONE,
            "origin_subject_entity_id": MERGED_ONE,
            "role": "applies_in",
        }
    ]

    before_stale_proposal = _memory_review_row_counts(unequal_staged)
    with pytest.raises(StaleMemoryVersionError), unequal_staged.begin() as connection:
        _stale_memory_proposal(
            connection,
            subject_entity_id=MERGED_ONE,
            expected_subject_version=2,
            at=WHEN + timedelta(seconds=3),
        )
    assert _memory_review_row_counts(unequal_staged) == before_stale_proposal

    before_refusals = _memory_review_row_counts(unequal_staged)
    with pytest.raises(ReviewNotFoundError), unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
                principal_id=PRINCIPAL_B,
                decided_at=WHEN + timedelta(seconds=3),
            ),
        )
    assert _memory_review_row_counts(unequal_staged) == before_refusals
    with pytest.raises(ReviewConflictError), unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
                expected_review_version=1,
                decided_at=WHEN + timedelta(seconds=3),
            ),
        )
    assert _memory_review_row_counts(unequal_staged) == before_refusals

    with unequal_staged.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _memory_review_request(
                review_case_id,
                disposition,
                corrected_statement=corrected_statement,
                decided_at=WHEN + timedelta(seconds=3),
            ),
        )
    with unequal_staged.connect() as connection:
        decided_proposal = connection.execute(
            text(
                f"SELECT accepted_memory_id, accepted_memory_version_id, "  # noqa: S608
                f"superseded_by_memory_proposal_id FROM "
                f"{SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
            ),
            {"proposal_id": proposal_id, "principal_id": PRINCIPAL_A},
        ).one()
        foreign_cases = relationship_memory_review_cases(
            connection,
            principal_id=PRINCIPAL_B,
            limit=10,
        )

        if disposition is Disposition.REPROCESS:
            successor = connection.execute(
                text(
                    f"SELECT principal_id, subject_entity_id, origin_subject_entity_id, "  # noqa: S608
                    f"expected_subject_version, context_links FROM "
                    f"{SCHEMA}.relationship_memory_proposals "
                    "WHERE memory_proposal_id = :proposal_id AND principal_id = :principal_id"
                ),
                {
                    "proposal_id": decided_proposal.superseded_by_memory_proposal_id,
                    "principal_id": PRINCIPAL_A,
                },
            ).one()
        else:
            memory = connection.execute(
                text(
                    f"SELECT principal_id, subject_entity_id, origin_subject_entity_id "  # noqa: S608
                    f"FROM {SCHEMA}.relationship_memories WHERE memory_id = :memory_id"
                ),
                {"memory_id": decided_proposal.accepted_memory_id},
            ).one()
            context = connection.execute(
                text(
                    f"SELECT principal_id, target_id, origin_subject_entity_id "  # noqa: S608
                    f"FROM {SCHEMA}.relationship_memory_context_links "
                    "WHERE memory_version_id = :version_id"
                ),
                {"version_id": decided_proposal.accepted_memory_version_id},
            ).one()
            foreign_detail = SqlRelationshipMemoryRepository(connection).detail(
                decided_proposal.accepted_memory_id,
                principal_id=PRINCIPAL_B,
            )

    assert foreign_cases == ()
    if disposition is Disposition.REPROCESS:
        assert decided_proposal.accepted_memory_id is None
        assert successor.principal_id == PRINCIPAL_A
        assert successor.subject_entity_id == MERGED_ONE
        assert successor.origin_subject_entity_id == MERGED_ONE
        assert successor.expected_subject_version == restored_entity.version
        assert successor.context_links == restored_proposal.context_links
        assert _row_count(unequal_staged, "relationship_memories") == 0
    else:
        assert memory.principal_id == PRINCIPAL_A
        assert memory.subject_entity_id == MERGED_ONE
        assert memory.origin_subject_entity_id == MERGED_ONE
        assert context.principal_id == PRINCIPAL_A
        assert context.target_id == MERGED_ONE
        assert context.origin_subject_entity_id == MERGED_ONE
        assert foreign_detail is None


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


def test_a_preview_whose_stored_plan_digest_was_edited_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_previews "  # noqa: S608
                "SET plan_digest = :replacement WHERE preview_id = :preview"
            ),
            {"replacement": "f" * 64, "preview": report.preview.preview_id},
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


# --- the governed merge, through `invoke`, against a real server --------------
#
# Everything above drives `IdentityCorrectionService` directly, which is where
# the merge's rules live and is the right place to prove them. What it cannot
# prove is that a *request* reaches those rules: the command shapes, the
# dispatcher, the server-derived idempotency key, the feature gate and the
# operator boundary are all `WP-RI-B-07`'s, and none of them is exercised by
# constructing the service by hand.
#
# So this block composes `ApplicationService` the way `bootstrap.gateway` does
# and sends each of them by name. It is the only evidence in this
# repository that the published surface of `WP-RI-06` works at all.


class _Composed:
    """`ApplicationService` over a real database, with the three gates on."""

    def __init__(self, url: str, *, identity_correction: bool = True) -> None:
        self.work_engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWorkPort:
            return SqlAlchemyUnitOfWork(
                self.work_engine,
                audit=audit,
                relationship_memory_enabled=True,
                relationship_intelligence_enabled=True,
            )

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=EffectiveLimits(
                max_page_size=100,
                default_page_size=25,
                max_fetch_bytes=1 << 20,
                max_enrollment_depth=0,
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_identity_correction_enabled=identity_correction,
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def invoke(
        self, capability: Capability, command: object, *, operator: bool = True
    ) -> ResponseEnvelope:
        """One request, with the acting Principal's operator flag under test.

        `operator=False` is what a `relationship_standard` or
        `relationship_reviewer` client is: authenticated, holding the capability
        name, and not the operator. Operator §24 says that must not be enough.
        """
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=PRINCIPAL_A,
                requested_at=WHEN,
            ),
            command,  # type: ignore[arg-type]
            principal=Principal(
                principal_id=PRINCIPAL_A,
                kind=PrincipalKind.OPERATOR if operator else PrincipalKind.GATEWAY,
                authenticated=True,
            ),
        )


@pytest.fixture
def composed(staged: Engine, disposable_database: str) -> Iterator[_Composed]:
    runtime = _Composed(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()


def _preview_payload(**overrides: object) -> PreviewEntityMerge:
    fields: dict[str, object] = {
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 1,
        "merged_away": ({"entity_id": MERGED_ONE, "expected_version": 1},),
        "reason": REASON,
    }
    fields.update(overrides)
    return PreviewEntityMerge(**fields)  # type: ignore[arg-type]


def test_the_published_preview_answers_and_persists_the_binding(composed: _Composed) -> None:
    """`entities.merge.preview` by name, and the row it is classified a write for.

    The response is read field by field because it is the contract's own list
    (operator §19) and because nothing else in this repository sends this
    capability: a report assembled correctly and rendered wrongly would pass
    every test above.
    """
    envelope = composed.invoke(Capability.ENTITIES_MERGE_PREVIEW, _preview_payload())

    assert envelope.error is None, envelope.error
    result = envelope.result
    assert result is not None
    assert parse_identifier(str(result["preview_id"]))[0] is IdKind.ENTITY_IDENTITY_PREVIEW
    assert isinstance(result["preview_token"], str)
    assert len(str(result["preview_token"])) == 64
    assert len(str(result["conflict_digest"])) == 64
    assert result["expires_at"]
    assert result["blockers"] == []
    assert result["required_choices"] == []
    assert result["audit_id"]
    groups = result["affected_groups"]
    assert isinstance(groups, list)
    # Every family the contract names answers, rather than only the ones that
    # had rows: §20 forbids silently ignoring an affected family.
    assert {str(group["family"]) for group in groups} == {family.value for family in MergeFamily}
    # And the write this capability is classified for is durable.
    assert _row_count(composed.work_engine, "entity_identity_previews") == 1


def test_the_published_merge_consumes_that_preview_and_replays_on_retry(
    composed: _Composed,
) -> None:
    """`entities.merge` by name, twice, with the idempotency key the server derived.

    The key is never sent — operator §23 and §26 make it server-owned and
    `REMOTE_OWNED_PAYLOAD_FIELDS` refuses one that arrives — so an identical
    retry can only replay if the *handler* derived the same key both times. That
    is the whole claim here, and it cannot be made anywhere the handler is not
    involved.
    """
    previewed = composed.invoke(Capability.ENTITIES_MERGE_PREVIEW, _preview_payload())
    assert previewed.result is not None
    preview_id = str(previewed.result["preview_id"])
    token = str(previewed.result["preview_token"])
    command = MergeEntities(preview_id=preview_id, preview_digest=token, reason=REASON)

    first = composed.invoke(Capability.ENTITIES_MERGE, command)
    assert first.error is None, first.error
    assert first.result is not None
    assert first.result["survivor_entity_id"] == SURVIVOR
    assert first.result["merged_entity_ids"] == [MERGED_ONE]
    assert first.result["state"] == IdentityOperationState.COMPLETED.value
    assert first.result["replayed"] is False
    assert first.result["effects"]
    receipt_id = str(first.result["receipt_id"])
    assert parse_identifier(receipt_id)[0] is IdKind.RECEIPT

    again = composed.invoke(Capability.ENTITIES_MERGE, command)
    assert again.error is None, again.error
    assert again.result is not None
    assert again.result["replayed"] is True
    assert again.result["identity_operation_id"] == first.result["identity_operation_id"]
    assert again.result["receipt_id"] == receipt_id
    assert _row_count(composed.work_engine, "entity_identity_operations") == 1


def test_a_caller_who_is_not_the_operator_is_denied_both_halves(composed: _Composed) -> None:
    """Operator §24, at the entry point rather than in the registry.

    A `relationship_standard` or `relationship_reviewer` client is authenticated
    and holds the capability name; what it does not hold is operator authority,
    and `_OPERATOR_ONLY` is what makes that enough to refuse. Both halves are
    driven, because a boundary on the apply alone would leave the inspection —
    the exact identities of two people — open to a reviewer.
    """
    for capability, sent in (
        (Capability.ENTITIES_MERGE_PREVIEW, _preview_payload()),
        (
            Capability.ENTITIES_MERGE,
            MergeEntities(
                preview_id=issue_identifier(IdKind.ENTITY_IDENTITY_PREVIEW),
                preview_digest="0" * 64,
                reason=REASON,
            ),
        ),
    ):
        envelope = composed.invoke(capability, sent, operator=False)
        assert envelope.result is None, capability.value
        assert envelope.error is not None
        assert envelope.error.code is ErrorCode.DENIED, capability.value
    assert _row_count(composed.work_engine, "entity_identity_previews") == 0


def test_the_feature_gate_refuses_both_halves_before_a_handler_runs(
    staged: Engine, disposable_database: str
) -> None:
    """`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`, at the execution floor.

    `available_capabilities` withholds the governed merge, and two readers consult it
    — `capabilities.get` and the MCP tool list. The HTTP transport is not one of
    them: it routes by path segment and dispatches straight from `_HANDLERS`.
    So the floor is asserted here, on a build whose other two switches are on and
    whose third is not, against a real database that could have been written to.
    """
    runtime = _Composed(disposable_database, identity_correction=False)
    try:
        envelope = runtime.invoke(Capability.ENTITIES_MERGE_PREVIEW, _preview_payload())
        assert envelope.result is None
        assert envelope.error is not None
        assert envelope.error.code is ErrorCode.UNSUPPORTED
        assert Capability.ENTITIES_MERGE_PREVIEW not in runtime.service.available_capabilities
        assert Capability.ENTITIES_MERGE not in runtime.service.available_capabilities
    finally:
        runtime.close()
    assert _row_count(staged, "entity_identity_previews") == 0


def test_a_tampered_token_and_a_stale_version_are_both_refused_through_the_capability(
    composed: _Composed,
) -> None:
    """Two refusals §21 names, reached through the published surface.

    Driven here as well as against the service because the digest and the version
    arrive from a *caller* on this path, and a handler that dropped either on the
    way through would leave every service-level test green.
    """
    previewed = composed.invoke(Capability.ENTITIES_MERGE_PREVIEW, _preview_payload())
    assert previewed.result is not None
    preview_id = str(previewed.result["preview_id"])

    tampered = composed.invoke(
        Capability.ENTITIES_MERGE,
        MergeEntities(preview_id=preview_id, preview_digest="1" * 64, reason=REASON),
    )
    assert tampered.result is None
    assert tampered.error is not None
    assert tampered.error.code is ErrorCode.CONFLICT
    assert tampered.error.safe_details == ("preview_stale",)

    stale = composed.invoke(
        Capability.ENTITIES_MERGE_PREVIEW, _preview_payload(expected_survivor_version=99)
    )
    assert stale.result is None
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
