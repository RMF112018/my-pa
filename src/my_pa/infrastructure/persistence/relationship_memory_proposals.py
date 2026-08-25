"""The producer's whole persistence surface on the memory plane: one insert.

A third module over the eight memory tables, and the count is the point rather
than an accident of file layout.
`tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`
asserts exact set equality over the modules that build a statement against one of
them, so this file could not exist until `Capability.RELATIONSHIP_MEMORY_PROPOSE`
did — which is why `RelationshipMemoryProposalService` shipped against a
`Protocol` with no implementor for two waves. That interlock is the guard working,
not a gap it was hiding.

**A separate module from `relationship_memory.py` for the reason
`RelationshipMemoryProposalService` is a separate class from
`RelationshipMemoryService`.** That module holds the aggregate: it creates
memories, revises them, archives and restores them, and reads them back. This one
inserts a candidate and the records it rests on, and can do nothing else. A
producer handed this object has no method that reaches `relationship_memories`,
so operator §12's "MUST NOT create active Relationship Memory directly" is a
property of the port rather than a branch some future writer might add.

**Every statement goes through `persistence.principal_scope`.** The reference
implementation this replaces (`_InsertOnlyProposals`, in
`tests/database/test_relationship_memory_review.py`) stamped the Principal from
the domain record's own field, which is correct as far as it goes and is not the
same guarantee: `principal_bound_values` refuses values that already carry a
partition column, so a write path cannot accept identity from a payload even
through its own composition bug (`MU-AC-02`). The Principal this row is written
under is therefore the context's, and the domain record's `principal_id` is what
the service already checked the subject against.

**No read, deliberately.** The port declares one method and this class implements
one method. A `proposal_by_id` here would be the first half of a producer reading
back what a reviewer did with its candidate, and the Review plane
(`relationship_memory_review.py`) is where that read belongs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import RelationshipMemoryProposalRepository, UnknownScopeError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.memory import (
    MemoryKind,
    MemoryProposalEvidence,
    MemoryProposalMethod,
    MemoryProposalState,
    RelationshipMemoryProposal,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    capture_spans,
    capture_versions,
    captures,
    enrollments,
    entity_observations,
    extractions,
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
)

__all__ = ["SqlRelationshipMemoryProposalRepository"]


def _bound(table: Any, principal_id: str, values: dict[str, object]) -> dict[str, object]:  # noqa: ANN401 - a SQLAlchemy Table
    """`values` stamped with the given Principal for `table`, through the one guard.

    The same helper `relationship_memory.py` carries, and a copy rather than an
    import for the reason that module's own `_mine`/`_bound` pair is private: it
    is two lines over `principal_scope`, and importing one persistence module
    into another to share them would make a dependency between two planes out of
    a spelling convenience.
    """
    return principal_bound_values(values, table, capture_context(principal_id))


def _mine(table: Any, principal_id: str) -> Any:  # noqa: ANN401 - a SQLAlchemy Table
    return partition_criterion(table, capture_context(principal_id))


class SqlRelationshipMemoryProposalRepository(RelationshipMemoryProposalRepository):
    """`RelationshipMemoryProposalRepository`, over the two proposal tables.

    Declared as a subclass rather than typed structurally, the shape every other
    repository in this package uses: the port is an `ABC` in `contracts.ports`
    because `UnitOfWork` exposes it, and inheriting is what makes a missing
    method a failure at composition rather than at the first call.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_proposal(
        self,
        proposal: RelationshipMemoryProposal,
        evidence: tuple[MemoryProposalEvidence, ...],
    ) -> tuple[RelationshipMemoryProposal, int, bool]:
        """Insert one candidate and the exact records it rests on, atomically.

        Atomically because both statements run on the caller's transaction and
        neither is committed here — the unit of work owns that boundary, so a
        candidate whose evidence insert violates
        `memory_proposal_evidence_names_exactly_one_record` leaves no candidate
        behind either.

        Domain shape rules live on the proposal and evidence records. Referential
        scope is necessarily checked here, where the source records and their
        Principal-bearing parent chains are visible; a missing record and a
        foreign record intentionally receive the same refusal.
        """
        for link in evidence:
            if link.principal_id != proposal.principal_id:
                raise ValueError("proposal evidence belongs to the proposal Principal")
            if link.memory_proposal_id != proposal.memory_proposal_id:
                raise ValueError("proposal evidence belongs to the proposal it names")
            owned = None
            if link.entity_observation_id is not None:
                owned = self._connection.execute(
                    select(entity_observations.c.observation_id).where(
                        _mine(entity_observations, proposal.principal_id),
                        entity_observations.c.observation_id == link.entity_observation_id,
                    )
                ).first()
            elif link.capture_span_id is not None:
                owned = self._connection.execute(
                    select(capture_spans.c.span_id)
                    .select_from(
                        capture_spans.join(
                            capture_versions,
                            capture_versions.c.version_id == capture_spans.c.version_id,
                        ).join(captures, captures.c.capture_id == capture_versions.c.capture_id)
                    )
                    .where(
                        capture_spans.c.span_id == link.capture_span_id,
                        _mine(capture_versions, proposal.principal_id),
                        _mine(captures, proposal.principal_id),
                    )
                ).first()
            elif link.knowledge_id is not None:
                owned = self._connection.execute(
                    select(extractions.c.extraction_id)
                    .select_from(
                        extractions.join(
                            enrollments,
                            enrollments.c.enrollment_id == extractions.c.enrollment_id,
                        )
                    )
                    .where(
                        extractions.c.extraction_id == link.knowledge_id,
                        _mine(enrollments, proposal.principal_id),
                    )
                ).first()
            if owned is None:
                raise UnknownScopeError("proposal evidence cites a record outside this scope")

        created = True
        try:
            with self._connection.begin_nested():
                self._connection.execute(
                    insert(relationship_memory_proposals).values(
                        _bound(
                            relationship_memory_proposals,
                            proposal.principal_id,
                            {
                                "memory_proposal_id": proposal.memory_proposal_id,
                                "subject_entity_id": proposal.subject_entity_id,
                                "expected_subject_version": proposal.expected_subject_version,
                                "proposed_kind": proposal.proposed_kind.value,
                                "proposed_statement": proposal.proposed_statement,
                                "proposed_statement_sha256": proposal.proposed_statement_sha256,
                                "dedupe_sha256": proposal.dedupe_sha256,
                                "structured_value": proposal.structured_value,
                                "state": proposal.state.value,
                                "method": proposal.method.value,
                                "method_version": proposal.method_version,
                                "model_id": proposal.model_id,
                                "model_version": proposal.model_version,
                                "classification": proposal.classification.value,
                                "proposed_at": proposal.proposed_at,
                                "review_case_id": proposal.review_case_id,
                                "accepted_memory_id": proposal.accepted_memory_id,
                                "accepted_memory_version_id": (proposal.accepted_memory_version_id),
                                "invalidated_reason": proposal.invalidated_reason,
                                "superseded_at": proposal.superseded_at,
                                "superseded_by_memory_proposal_id": (
                                    proposal.superseded_by_memory_proposal_id
                                ),
                            },
                        )
                    )
                )
        except IntegrityError as error:
            diagnostic = getattr(error.orig, "diag", None)
            if (
                getattr(diagnostic, "constraint_name", None)
                != "an_open_equivalent_memory_proposal_is_raised_once"
            ):
                raise
            created = False

        if created:
            stored = proposal
            existing: set[tuple[str, str | None]] = set()
        else:
            row = self._connection.execute(
                select(relationship_memory_proposals)
                .where(
                    _mine(relationship_memory_proposals, proposal.principal_id),
                    relationship_memory_proposals.c.dedupe_sha256 == proposal.dedupe_sha256,
                    relationship_memory_proposals.c.state.in_(
                        ["proposed", "needs_review", "deferred"]
                    ),
                )
                .with_for_update(of=relationship_memory_proposals)
            ).one()
            stored = RelationshipMemoryProposal(
                memory_proposal_id=str(row.memory_proposal_id),
                principal_id=str(row.principal_id),
                subject_entity_id=str(row.subject_entity_id),
                expected_subject_version=int(row.expected_subject_version),
                proposed_kind=MemoryKind(row.proposed_kind),
                proposed_statement=str(row.proposed_statement),
                proposed_statement_sha256=str(row.proposed_statement_sha256),
                dedupe_sha256=str(row.dedupe_sha256),
                structured_value=row.structured_value,
                state=MemoryProposalState(row.state),
                method=MemoryProposalMethod(row.method),
                method_version=str(row.method_version),
                model_id=row.model_id,
                model_version=row.model_version,
                classification=Classification(row.classification),
                proposed_at=row.proposed_at,
                review_case_id=row.review_case_id,
                accepted_memory_id=row.accepted_memory_id,
                accepted_memory_version_id=row.accepted_memory_version_id,
                invalidated_reason=row.invalidated_reason,
                superseded_at=row.superseded_at,
                superseded_by_memory_proposal_id=row.superseded_by_memory_proposal_id,
            )
            existing = {
                (
                    str(link.role),
                    link.entity_observation_id or link.capture_span_id or link.knowledge_id,
                )
                for link in self._connection.execute(
                    select(relationship_memory_proposal_evidence).where(
                        _mine(relationship_memory_proposal_evidence, proposal.principal_id),
                        relationship_memory_proposal_evidence.c.memory_proposal_id
                        == stored.memory_proposal_id,
                    )
                )
            }
        for link in evidence:
            identity = (
                link.role.value,
                link.entity_observation_id or link.capture_span_id or link.knowledge_id,
            )
            if identity in existing:
                continue
            self._connection.execute(
                insert(relationship_memory_proposal_evidence).values(
                    _bound(
                        relationship_memory_proposal_evidence,
                        link.principal_id,
                        {
                            "proposal_evidence_id": issue_identifier(
                                IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE
                            ),
                            "memory_proposal_id": stored.memory_proposal_id,
                            "role": link.role.value,
                            "entity_observation_id": link.entity_observation_id,
                            "capture_span_id": link.capture_span_id,
                            "knowledge_id": link.knowledge_id,
                            "created_at": link.created_at,
                        },
                    )
                )
            )
            existing.add(identity)
        if created:
            evidence_count = len(existing)
        else:
            evidence_count = self._connection.execute(
                select(func.count())
                .select_from(relationship_memory_proposal_evidence)
                .where(
                    _mine(relationship_memory_proposal_evidence, proposal.principal_id),
                    relationship_memory_proposal_evidence.c.memory_proposal_id
                    == stored.memory_proposal_id,
                )
            ).scalar_one()
        return stored, int(evidence_count), created
