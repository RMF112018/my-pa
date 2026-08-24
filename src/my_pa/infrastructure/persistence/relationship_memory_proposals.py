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

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import RelationshipMemoryProposalRepository
from my_pa.domain.relationship.memory import (
    MemoryProposalEvidence,
    RelationshipMemoryProposal,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
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
    ) -> None:
        """Insert one candidate and the exact records it rests on, atomically.

        Atomically because both statements run on the caller's transaction and
        neither is committed here — the unit of work owns that boundary, so a
        candidate whose evidence insert violates
        `memory_proposal_evidence_names_exactly_one_record` leaves no candidate
        behind either.

        Nothing is validated here. Every rule these rows answer to lives on
        `RelationshipMemoryProposal.__post_init__`, on
        `MemoryProposalEvidence.__post_init__` and on the table CHECKs, and a
        third copy in the writer would be a third thing able to disagree.
        """
        self._connection.execute(
            insert(relationship_memory_proposals).values(
                _bound(
                    relationship_memory_proposals,
                    proposal.principal_id,
                    {
                        "memory_proposal_id": proposal.memory_proposal_id,
                        "subject_entity_id": proposal.subject_entity_id,
                        "proposed_kind": proposal.proposed_kind.value,
                        "proposed_statement": proposal.proposed_statement,
                        "proposed_statement_sha256": proposal.proposed_statement_sha256,
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
                        "accepted_memory_version_id": proposal.accepted_memory_version_id,
                        "invalidated_reason": proposal.invalidated_reason,
                    },
                )
            )
        )
        for link in evidence:
            self._connection.execute(
                insert(relationship_memory_proposal_evidence).values(
                    _bound(
                        relationship_memory_proposal_evidence,
                        link.principal_id,
                        {
                            "proposal_evidence_id": link.proposal_evidence_id,
                            "memory_proposal_id": link.memory_proposal_id,
                            "role": link.role.value,
                            "entity_observation_id": link.entity_observation_id,
                            "capture_span_id": link.capture_span_id,
                            "knowledge_id": link.knowledge_id,
                            "created_at": link.created_at,
                        },
                    )
                )
            )
