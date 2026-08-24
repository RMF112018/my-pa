"""The entity plane's directed writes: what the server decides, and what the caller may.

One service over two record families -- assignments and directed edges -- and its
whole job is the line between the two. A transport hands it a command carrying
only what a user could legitimately have chosen (which entities, which type,
which scope, which role, when it applies, why it ended) and this module supplies
everything else from authenticated context and policy:

* the owning Principal, from `Authorization` and never from a payload;
* the mutation authority, which defaults to `user_confirmed_assertion` -- a
  public create or revise that could claim `review_accepted` would let a caller
  manufacture a governed promotion out of a request, and one that could claim
  `system_deterministic` would let it claim the write was recomputable when a
  person chose it, and `_check_write_authority` refuses the second outright;
* the actor class, which moves with the authority and never independently;
* the correlation identity, the receipt time, and the audit identity the
  authorization already issued;
* every minted identifier, which the repository owns.

**The caller cannot widen any of them, and the mechanism is absence rather than
validation.** The command dataclasses in `application.commands` have no
`principal_id`, `authority`, `actor_class`, `state`, `version`, `recorded_at` or
`superseded_by_*` field, so a payload naming one is refused by the constructor
before this module runs. There is nothing here that reads such a field and
decides to ignore it, because a field that can be sent is a field a later change
can start honouring.

**A model cannot reach these writes, and `WP-RI-B-05` is where that sentence
changed shape without changing meaning.** `entity_proposals` is still where a
source-, rule- or model-derived candidate lives until a reviewer decides, and a
producer still cannot reach `create`. What changed is that acceptance now
*executes* through these same six methods rather than stopping at a routing
table, so the authority is a keyword-only argument defaulting to the direct
path's pair instead of a constant. The separation it used to express is
unchanged and is held elsewhere: the transport commands carry no `authority` and
no `actor_class` field, so nothing a caller sends can reach either parameter,
and the only caller that passes anything but the default is the promotion path
in `application.entity_governance`, which is reachable only from a recorded
review decision.

**Nothing here mints a reciprocal edge.** `works_for` does not imply `manages`.
A plane that generated the inverse would be asserting a fact the user did not
state and could not withdraw independently, which is the one property a directed
model exists to keep.
"""

from __future__ import annotations

from datetime import datetime

from my_pa.application.commands import (
    CreateEntityAssignment,
    CreateEntityRelationship,
    EndEntityAssignment,
    EndEntityRelationship,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
)
from my_pa.contracts.ports import (
    AssignmentWriteRequest,
    DirectedReceipt,
    EntitiesRepository,
    RelationshipWriteRequest,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.entity import (
    DirectedWriteOperation,
    validate_directed_reason,
    validate_directed_text,
)
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_ACTOR_CLASS,
    DEFAULT_MUTATION_AUTHORITY,
    ActorClass,
    MutationAuthority,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = ["EntityDirectedService"]


class EntityDirectedService:
    """Route each directed-relationship command to the port that answers it.

    Six writes and one shared shape: normalize what the caller supplied, supply
    what only the server may, ask the repository whether this key has already
    been answered, and otherwise admit. No rule about duplicates, versions or
    lifecycle is restated here -- the active semantic uniques live in the
    schema, the version guard lives in the repository's guarded `UPDATE`, and
    the vocabulary lives in the domain, so a second copy here could not disagree
    with them.
    """

    def create_assignment(
        self,
        repository: EntitiesRepository,
        command: CreateEntityAssignment,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Admit one new assignment, or return the receipt this key already has."""
        request = AssignmentWriteRequest(
            operation=DirectedWriteOperation.CREATE,
            assignment_id=None,
            principal_id=principal_id,
            entity_id=command.entity_id,
            expected_entity_version=command.expected_entity_version,
            assignment_type=command.assignment_type,
            scope_entity_id=command.scope_entity_id,
            expected_scope_version=command.expected_scope_version,
            expected_version=None,
            role=validate_directed_text(command.role, field="role"),
            discipline=validate_directed_text(command.discipline, field="discipline"),
            responsibility_class=validate_directed_text(
                command.responsibility_class, field="responsibility_class"
            ),
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            cleared=(),
            evidence_refs=command.evidence_refs,
            reason=None,
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository, Capability.ENTITIES_ASSIGNMENTS_CREATE, request, principal_id=principal_id
        )
        return replayed if replayed is not None else repository.create_assignment(request)

    def revise_assignment(
        self,
        repository: EntitiesRepository,
        command: ReviseEntityAssignment,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Append the descriptive change, or return the receipt this key already has."""
        request = AssignmentWriteRequest(
            operation=DirectedWriteOperation.REVISE,
            assignment_id=command.assignment_id,
            principal_id=principal_id,
            entity_id=None,
            expected_entity_version=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_scope_version=None,
            expected_version=command.expected_version,
            role=validate_directed_text(command.role, field="role"),
            discipline=validate_directed_text(command.discipline, field="discipline"),
            responsibility_class=validate_directed_text(
                command.responsibility_class, field="responsibility_class"
            ),
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            cleared=command.clear,
            evidence_refs=command.evidence_refs,
            reason=None,
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository, Capability.ENTITIES_ASSIGNMENTS_REVISE, request, principal_id=principal_id
        )
        return replayed if replayed is not None else repository.revise_assignment(request)

    def end_assignment(
        self,
        repository: EntitiesRepository,
        command: EndEntityAssignment,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Withdraw one assignment from service, keeping the row and its history.

        `end_now` resolves to `at` here and nowhere else. It is the request's own
        received time -- the same moment every other row this request writes is
        stamped with -- rather than a second reading of the wall clock, so a
        request cannot end an assignment at a moment its audit event says it had
        not yet reached.
        """
        request = AssignmentWriteRequest(
            operation=DirectedWriteOperation.END,
            assignment_id=command.assignment_id,
            principal_id=principal_id,
            entity_id=None,
            expected_entity_version=None,
            assignment_type=None,
            scope_entity_id=None,
            expected_scope_version=None,
            expected_version=command.expected_version,
            role=None,
            discipline=None,
            responsibility_class=None,
            effective_from=None,
            effective_to=at if command.end_now else command.effective_end,
            cleared=(),
            evidence_refs=(),
            reason=validate_directed_reason(command.reason),
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository, Capability.ENTITIES_ASSIGNMENTS_END, request, principal_id=principal_id
        )
        return replayed if replayed is not None else repository.end_assignment(request)

    def create_relationship(
        self,
        repository: EntitiesRepository,
        command: CreateEntityRelationship,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Assert one directed edge, or return the receipt this key already has."""
        request = RelationshipWriteRequest(
            operation=DirectedWriteOperation.CREATE,
            relationship_id=None,
            principal_id=principal_id,
            from_entity_id=command.from_entity_id,
            expected_from_version=command.expected_from_version,
            relationship_type=command.relationship_type,
            to_entity_id=command.to_entity_id,
            expected_to_version=command.expected_to_version,
            scope_entity_id=command.scope_entity_id,
            expected_scope_version=command.expected_scope_version,
            expected_version=None,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            cleared=(),
            evidence_refs=command.evidence_refs,
            reason=None,
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository,
            Capability.ENTITIES_RELATIONSHIPS_CREATE,
            request,
            principal_id=principal_id,
        )
        return replayed if replayed is not None else repository.create_relationship(request)

    def revise_relationship(
        self,
        repository: EntitiesRepository,
        command: ReviseEntityRelationship,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Append the effective-window change, or return the receipt this key has."""
        request = RelationshipWriteRequest(
            operation=DirectedWriteOperation.REVISE,
            relationship_id=command.relationship_id,
            principal_id=principal_id,
            from_entity_id=None,
            expected_from_version=None,
            relationship_type=None,
            to_entity_id=None,
            expected_to_version=None,
            scope_entity_id=None,
            expected_scope_version=None,
            expected_version=command.expected_version,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            cleared=command.clear,
            evidence_refs=command.evidence_refs,
            reason=None,
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository,
            Capability.ENTITIES_RELATIONSHIPS_REVISE,
            request,
            principal_id=principal_id,
        )
        return replayed if replayed is not None else repository.revise_relationship(request)

    def end_relationship(
        self,
        repository: EntitiesRepository,
        command: EndEntityRelationship,
        *,
        principal_id: str,
        audit_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
        actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS,
    ) -> DirectedReceipt:
        """Withdraw one directed edge, on `end_assignment`'s terms.

        Only the edge named. An edge in the opposite direction between the same
        two entities is a separate assertion with its own identifier and its own
        version, and nothing here reaches it.
        """
        request = RelationshipWriteRequest(
            operation=DirectedWriteOperation.END,
            relationship_id=command.relationship_id,
            principal_id=principal_id,
            from_entity_id=None,
            expected_from_version=None,
            relationship_type=None,
            to_entity_id=None,
            expected_to_version=None,
            scope_entity_id=None,
            expected_scope_version=None,
            expected_version=command.expected_version,
            effective_from=None,
            effective_to=at if command.end_now else command.effective_end,
            cleared=(),
            evidence_refs=(),
            reason=validate_directed_reason(command.reason),
            idempotency_key=command.idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=audit_id,
            server_received_at=at,
            authority=authority,
            actor_class=actor_class,
        )
        replayed = self._replay(
            repository, Capability.ENTITIES_RELATIONSHIPS_END, request, principal_id=principal_id
        )
        return replayed if replayed is not None else repository.end_relationship(request)

    @staticmethod
    def _replay(
        repository: EntitiesRepository,
        capability: Capability,
        request: AssignmentWriteRequest | RelationshipWriteRequest,
        *,
        principal_id: str,
    ) -> DirectedReceipt | None:
        """Replay first, then write. See `ManagedDocumentService._write` for the shape.

        The pre-read happens after the request is built, because the payload
        digest is what decides whether a key in use is a replay or a conflict and
        the request is what computes it. It is an optimisation and never the
        decision: `entity_mutation_events` carries
        `UNIQUE (principal_id, capability, idempotency_key)`, so two concurrent
        writers that both read `None` still produce one write and one refusal.
        """
        return repository.directed_replay(
            capability.value,
            request.idempotency_key,
            request.payload_digest,
            principal_id=principal_id,
        )
