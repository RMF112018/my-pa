"""Relationship Memory use cases: what the server decides, and what the caller may.

Two services, and their whole job is the line between the two. A transport hands
one of them a command carrying only what a user — or a producer — could
legitimately have chosen, and this module supplies everything else from
authenticated context and policy.

`RelationshipMemoryService` owns the direct user-authored path (`create`,
`revise`, `archive`, `restore`, and the reads). It supplies:

* the owning Principal, from `Authorization` and never from a payload;
* the authority, which is always `user_authored_private_note` on this path,
  because a public create or revise that could claim `source_backed_assertion`
  would let a caller manufacture a finding out of a note;
* the classification, from the kind's own floor, so a `sensitivity` is
  `restricted_local` whether or not the caller thought about it;
* cloud eligibility, which is false and has no path to true;
* the actor class, the receipt time, and the correlation identity.

**The caller cannot widen any of them, and the mechanism is absence rather than
validation.** The command dataclasses have no `authority`, `classification`,
`cloud_eligible`, `principal_id`, `recorded_at`, `actor` or `review_state` field,
so a payload naming one is refused by the constructor before this module runs.
There is nothing here that reads such a field and decides to ignore it, because
a field that can be sent is a field a later change can start honouring.

**Restriction is monotonic, and only in one direction.** A caller may not choose
a classification at all in v0.1. What it can do is choose the `sensitivity`
kind, which raises the floor. Nothing lowers one.

**A model cannot reach `RelationshipMemoryService`'s writes**, and that sentence
is now a division between two classes in one file rather than a boundary at the
file's edge. `RelationshipMemoryProposalService` — the second half of this
module, under its own divider below — is the producer path a source, a rule or a
local model reaches, and every candidate it writes lands in
`relationship_memory_proposals` awaiting a reviewer. It holds no
`RelationshipMemoryRepository`, so a producer wired with it cannot reach
`admit`; the two services share a module because they are one plane's two write
postures, and share no port. That separation is why `MemoryActorClass.USER` is
hard-coded on the direct path rather than taken from the request, and why the
producer path names no actor class at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from my_pa.contracts.ports import (
    MemoryDetail,
    MemoryPage,
    MemoryWriteRequest,
    RelationshipMemoryProposalRepository,
    RelationshipMemoryRepository,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus
from my_pa.domain.relationship.memory import (
    DIRECT_USER_AUTHORITY,
    EvidenceLinkRole,
    MemoryActorClass,
    MemoryAdmission,
    MemoryKind,
    MemoryLifecycle,
    MemoryOperation,
    MemoryProposalEvidence,
    MemoryProposalMethod,
    MemoryProposalState,
    MergedSubjectError,
    RelationshipMemoryError,
    RelationshipMemoryProposal,
    RelationshipMemoryVersion,
    StaleMemoryVersionError,
    check_kind_permits_subject,
    classification_floor_for,
    statement_digest,
    validate_statement,
    validate_structured_value,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "ArchiveMemoryCommand",
    "CreateMemoryCommand",
    "MemoryProposalOrigin",
    "MemoryProposalReceipt",
    "ProposeMemoryCommand",
    "ProposedEvidence",
    "RelationshipMemoryProposalRepository",
    "RelationshipMemoryProposalService",
    "RelationshipMemoryService",
    "ReviseMemoryCommand",
]


@dataclass(frozen=True, slots=True)
class CreateMemoryCommand:
    """One direct user-authored memory, with the Principal already resolved."""

    principal_id: str
    subject_entity_id: str
    memory_kind: MemoryKind
    statement: str
    structured_value: dict[str, Any] | None
    context_links: tuple[dict[str, str], ...]
    pinned: bool
    observed_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ReviseMemoryCommand:
    """One successor version, with the Principal already resolved."""

    principal_id: str
    memory_id: str
    expected_version: int
    statement: str
    memory_kind: MemoryKind | None
    structured_value: dict[str, Any] | None
    context_links: tuple[dict[str, str], ...]
    #: `None` keeps whatever the aggregate holds. Only a revise can say that; a
    #: create has nothing to carry forward and states a real boolean.
    pinned: bool | None
    observed_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    correction_reason: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ArchiveMemoryCommand:
    """One reversible lifecycle transition, with the Principal already resolved."""

    principal_id: str
    memory_id: str
    expected_version: int
    idempotency_key: str


class RelationshipMemoryService:
    """Route each Relationship Memory command to the port that answers it."""

    def create(
        self,
        repository: RelationshipMemoryRepository,
        command: CreateMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Record the first immutable version of a new memory."""
        statement = validate_statement(command.statement)
        structured = validate_structured_value(command.memory_kind, command.structured_value)
        request = self._request(
            MemoryOperation.CREATE,
            principal_id=command.principal_id,
            memory_id=None,
            expected_version=None,
            subject_entity_id=command.subject_entity_id,
            memory_kind=command.memory_kind,
            statement=statement,
            structured_value=structured,
            context_links=command.context_links,
            pinned=command.pinned,
            observed_at=command.observed_at,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            correction_reason=None,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def revise(
        self,
        repository: RelationshipMemoryRepository,
        command: ReviseMemoryCommand,
        *,
        at: datetime,
        current_kind: MemoryKind,
    ) -> MemoryAdmission:
        """Append a successor version, refusing a stale expected version.

        `current_kind` is the kind the aggregate holds now, read by the caller.
        A revision that does not restate the kind keeps it, and one that does
        revalidates the structured value against the *new* kind — otherwise a
        caller could move an `important_date` to `general_note` and leave a date
        envelope behind that nothing would validate again.
        """
        statement = validate_statement(command.statement)
        kind = command.memory_kind or current_kind
        structured = validate_structured_value(kind, command.structured_value)
        request = self._request(
            MemoryOperation.REVISE,
            principal_id=command.principal_id,
            memory_id=command.memory_id,
            expected_version=command.expected_version,
            subject_entity_id=None,
            memory_kind=kind,
            statement=statement,
            structured_value=structured,
            context_links=command.context_links,
            pinned=command.pinned,
            observed_at=command.observed_at,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            correction_reason=command.correction_reason,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def archive(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Withdraw one memory from the current set. Reversible; not a delete."""
        return self._transition(repository, command, MemoryOperation.ARCHIVE, at=at)

    def restore(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Return one archived memory to the current set."""
        return self._transition(repository, command, MemoryOperation.RESTORE, at=at)

    # ---- reads -----------------------------------------------------------

    def get(
        self, repository: RelationshipMemoryRepository, memory_id: str, *, principal_id: str
    ) -> MemoryDetail | None:
        return repository.detail(memory_id, principal_id=principal_id)

    def list_for_entity(
        self,
        repository: RelationshipMemoryRepository,
        *,
        principal_id: str,
        subject_entity_id: str,
        limit: int,
        kinds: frozenset[MemoryKind] | None,
        lifecycle: MemoryLifecycle,
        context_entity_id: str | None,
        as_of: datetime | None,
        after_memory_id: str | None,
    ) -> MemoryPage:
        """One bounded page of one entity's memories.

        `include_restricted` is *not* a parameter a caller reaches. A restricted
        memory is disclosed on this path because the request already names one
        entity the Principal owns and holds the read purpose for it, which is the
        narrow profile view the contract admits it in — and it is withheld from
        `search`, which is the broad one. The distinction is made here rather
        than by the caller so a transport cannot ask for the wider behaviour.
        """
        return repository.page_for_entity(
            subject_entity_id,
            principal_id=principal_id,
            limit=limit,
            kinds=kinds,
            lifecycle=lifecycle,
            context_entity_id=context_entity_id,
            as_of=as_of,
            after_memory_id=after_memory_id,
            include_restricted=True,
        )

    def search(
        self,
        repository: RelationshipMemoryRepository,
        *,
        principal_id: str,
        query: str,
        limit: int,
        subject_entity_id: str | None,
        kinds: frozenset[MemoryKind] | None,
        after_memory_id: str | None,
    ) -> MemoryPage:
        return repository.search(
            query,
            principal_id=principal_id,
            limit=limit,
            subject_entity_id=subject_entity_id,
            kinds=kinds,
            after_memory_id=after_memory_id,
        )

    def history(
        self,
        repository: RelationshipMemoryRepository,
        memory_id: str,
        *,
        principal_id: str,
        limit: int,
        after_version_id: str | None,
    ) -> tuple[tuple[RelationshipMemoryVersion, ...], bool]:
        return repository.history(
            memory_id,
            principal_id=principal_id,
            limit=limit,
            after_version_id=after_version_id,
        )

    # ---- the one write path ----------------------------------------------

    def _transition(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        operation: MemoryOperation,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        request = self._request(
            operation,
            principal_id=command.principal_id,
            memory_id=command.memory_id,
            expected_version=command.expected_version,
            subject_entity_id=None,
            memory_kind=None,
            statement=None,
            structured_value=None,
            context_links=(),
            pinned=False,
            observed_at=None,
            effective_from=None,
            effective_to=None,
            correction_reason=None,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def _request(
        self,
        operation: MemoryOperation,
        *,
        principal_id: str,
        memory_id: str | None,
        expected_version: int | None,
        subject_entity_id: str | None,
        memory_kind: MemoryKind | None,
        statement: str | None,
        structured_value: dict[str, Any] | None,
        context_links: tuple[dict[str, str], ...],
        pinned: bool | None,
        observed_at: datetime | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
        correction_reason: str | None,
        idempotency_key: str,
        at: datetime,
    ) -> MemoryWriteRequest:
        """The one place server-owned fields are decided. See the module docstring.

        A transition carries no kind, so it takes the floor of the least
        restrictive classification — which is never stored, because archive and
        restore write no version. The value is supplied only because
        `MemoryWriteRequest` is one shape for four operations.
        """
        floor = classification_floor_for(memory_kind) if memory_kind else None
        return MemoryWriteRequest(
            operation=operation,
            memory_id=memory_id,
            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
            expected_version=expected_version,
            principal_id=principal_id,
            subject_entity_id=subject_entity_id,
            memory_kind=memory_kind,
            statement=statement,
            statement_sha256=None if statement is None else statement_digest(statement),
            structured_value=structured_value,
            authority=DIRECT_USER_AUTHORITY,
            classification=floor or classification_floor_for(MemoryKind.GENERAL_NOTE),
            created_by_actor=MemoryActorClass.USER,
            context_links=context_links,
            pinned=pinned,
            observed_at=observed_at,
            effective_from=effective_from,
            effective_to=effective_to,
            correction_reason=correction_reason,
            idempotency_key=idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            server_received_at=at,
        )

    def _admit(
        self, repository: RelationshipMemoryRepository, request: MemoryWriteRequest
    ) -> MemoryAdmission:
        """Replay first, then write. See `ManagedDocumentService._write` for the shape.

        The replay pre-read happens after the request is built, because the
        payload digest is what decides whether a key in use is a replay or a
        conflict and the request is what computes it. It is an optimisation and
        never the decision: `admit` still relies on the unique constraint, so two
        concurrent writers that both read `None` still produce one memory.
        """
        replayed = repository.replay_for(
            request.idempotency_key, request.payload_digest, principal_id=request.principal_id
        )
        if replayed is not None:
            return MemoryAdmission(receipt=replayed, created=False)
        return repository.admit(request)


# ======================================================================
# The producer path: `relationship_memory.propose`
# ======================================================================
#
# Everything below this divider belongs to the *other* write posture. A source,
# a rule or a local model does not author memory; it raises a candidate, and a
# reviewer decides. The divider is not decoration — the two halves share this
# module and share no port, and the tests in
# `tests/unit/test_relationship_memory_propose.py` read that separation off the
# source rather than trusting this comment.


@dataclass(frozen=True, slots=True)
class ProposedEvidence:
    """One exact record a candidate memory rests on, as a producer names it.

    Three optional targets and exactly one of them non-null, which is the same
    discipline `MemoryProposalEvidence` and the schema's
    `memory_proposal_evidence_names_exactly_one_record` enforce — and it is
    *only* enforced there. This class re-states no rule, because a second copy
    of a one-of-three check is a second copy that can disagree; it exists so a
    producer can name evidence without minting the server-owned identifier, the
    Principal and the timestamp that the stored record also carries.
    """

    role: EvidenceLinkRole
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProposeMemoryCommand:
    """One candidate memory, with the Principal already resolved.

    **What is absent is the contract.** There is no `method`, `method_version`,
    `model_id`, `model_version`, `classification`, `state`, `review_case_id`,
    `authority`, `cloud_eligible`, `actor`, `proposed_at`, `accepted_memory_id`
    or `invalidated_reason` field, so a producer that sends one is refused by the
    constructor before `propose` runs. Operator §12 and §26 assign every one of
    them to the server, and absence is how this module keeps them there: a field
    that can be sent is a field a later change can start honouring.

    `expected_subject_version` is the one version this path binds. A candidate is
    raised *about* a subject as the producer last read it, and a subject that
    moved underneath — renamed, retyped, archived and restored, merged away —
    is a subject the producer did not actually resolve. Refusing is the same
    posture `revise` takes toward its own aggregate.

    `statement` is `repr=False` for the reason `MemoryWriteRequest.statement` is:
    a command value is logged, compared and rendered in test failures, and on
    this path it is the text a *rule* wrote about another person. Operator §28
    forbids it reaching a log or a telemetry field, and a `repr` that never
    carries it is the version of that rule nobody has to remember.
    """

    principal_id: str
    subject_entity_id: str
    expected_subject_version: int
    memory_kind: MemoryKind
    statement: str = field(repr=False)
    structured_value: dict[str, Any] | None = field(repr=False)
    evidence: tuple[ProposedEvidence, ...]


@dataclass(frozen=True, slots=True)
class MemoryProposalOrigin:
    """How a candidate was produced, as the *server* knows it.

    Deliberately not part of `ProposeMemoryCommand`, and the separation is the
    whole control. Operator §12 and §26 give the server the proposal method and
    the model identity; a producer that could state its own method could claim
    `deterministic` for a model's guess, and a reviewer reading the case would
    believe a rule had run. So the method travels beside the command, out of the
    payload, resolved from the authenticated producer's registration exactly as
    the Principal and the clock are.

    The `local_model`/`model_id` pairing is checked once, by
    `RelationshipMemoryProposal.__post_init__` and by the schema's
    `a_model_proposal_names_its_model` CHECK. Nothing is re-checked here.
    """

    method: MemoryProposalMethod
    method_version: str
    model_id: str | None = None
    model_version: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryProposalReceipt:
    """What a producer is handed after a candidate is recorded.

    **It carries no statement, and the absence is the disclosure control** — the
    same one `RelationshipMemoryReviewCase` makes and for the same reason. A
    `sensitivity` candidate floors at `RESTRICTED_LOCAL`, and the read plane
    withholds restricted statements from `search`; handing the proposed words
    back through a producer's receipt would be a second channel for exactly the
    text the accepted form is withheld on, reached by a caller that never had a
    disclosure decision to make. The field is absent from the model rather than
    filtered in a formatter, so a later writer cannot expose it by editing a
    view.

    `classification` and `proposed_kind` *are* disclosed, because a producer has
    to be able to see that the floor it did not choose was applied, and neither
    is the text.
    """

    memory_proposal_id: str
    review_case_id: str
    subject_entity_id: str
    proposed_kind: MemoryKind
    state: MemoryProposalState
    classification: Classification
    method: MemoryProposalMethod
    proposed_at: datetime
    evidence_count: int


class RelationshipMemoryProposalService:
    """`relationship_memory.propose`: raise a candidate, and never a memory.

    A separate class from `RelationshipMemoryService`, which is the only reason
    the prohibitions this path carries are checkable. Operator §12 forbids this
    path from creating active Relationship Memory directly; §16 forbids a
    producer deciding its own proposal. Both hold here because this object has
    no reference to a `RelationshipMemoryRepository` and no reference to the
    Review plane -- not because a method chose not to call one. A future writer
    who wants to promote from here has to add a port to the constructor of a
    class that has none, which is a visible change rather than an added line.

    **`RelationshipMemoryProposalRepository` is imported from `contracts.ports`
    and used to be declared in this module.** It moved at `WP-RI-B-07`, when
    `ApplicationService` started reaching it through
    `UnitOfWork.relationship_memory_proposals`: `contracts` may not import
    `application`, so a port a dispatcher reaches has to be declared where
    `UnitOfWork` can name it. The argument that put it here — a port whose only
    implementor and only caller are one use case is a port the use case may own,
    which is `GoodNotesCorrectionRepository`'s shape — was true while nothing
    exposed it, and that stopped being true rather than turning out to be wrong.
    The "one method, and the count is the contract" reasoning moved with the
    declaration.


    What this path adds beyond `create`, and why each is not duplication:

    * **evidence is required.** A produced candidate with no record behind it is
      an assertion a reviewer cannot check, and the proposal-evidence table's own
      comment says as much ("required for every source- or model-derived
      proposal"). The direct path has the user standing behind it instead, which
      is why `create` requires none.
    * **the subject version is bound.** `create` does not bind one because a user
      writing a note is not asserting anything about the subject record's
      current shape. A producer is: it resolved that entity, at that version,
      from that evidence.
    * **the review case is opened here.** `relationship_memory_review_cases`
      selects on `review_case_id IS NOT NULL`, so a candidate written without one
      would be a candidate no reviewer ever sees — recorded, invisible, and
      indistinguishable from suppressed. Minting it at the moment the candidate
      is written is what makes "lands as a proposal awaiting Review" true rather
      than intended.
    """

    def propose(
        self,
        repository: RelationshipMemoryProposalRepository,
        command: ProposeMemoryCommand,
        *,
        subject: Entity,
        origin: MemoryProposalOrigin,
        at: datetime,
    ) -> MemoryProposalReceipt:
        """Record one candidate memory awaiting Review.

        `subject` is the entity the caller resolved, read through the entity
        plane's own Principal-scoped port — the shape `revise` already uses for
        `current_kind`, and it is what keeps a foreign subject indistinguishable
        from an absent one: a caller that cannot read the entity has `None` and
        raises `NotFoundError`, and never learns which of the two it was.

        The refusals below are ordered subject-first deliberately. Every one of
        them depends on the subject, the expectation or the kind, and none on the
        statement, so a producer cannot tell a restricted candidate's fate from a
        general one's by the error it gets back (operator §28).
        """
        if subject.principal_id != command.principal_id:
            raise RelationshipMemoryError("a candidate names a subject outside this scope")
        if subject.entity_id != command.subject_entity_id:
            raise RelationshipMemoryError("a candidate names the subject it was resolved against")
        if subject.status is EntityStatus.MERGED_REDIRECT:
            # Refused rather than followed, exactly as the direct write path
            # refuses: rebinding a candidate raised about a historical identity
            # onto the current person would put a different statement in front
            # of the reviewer than the evidence supports.
            raise MergedSubjectError(str(subject.superseded_by_entity_id))
        if subject.version != command.expected_subject_version:
            raise StaleMemoryVersionError("the subject has moved since it was resolved")
        check_kind_permits_subject(command.memory_kind, subject.entity_type)
        if not command.evidence:
            raise RelationshipMemoryError("a produced candidate names the records it rests on")

        statement = validate_statement(command.statement)
        structured = validate_structured_value(command.memory_kind, command.structured_value)
        proposal_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
        review_case_id = issue_identifier(IdKind.REVIEW_CASE)
        proposal = RelationshipMemoryProposal(
            memory_proposal_id=proposal_id,
            principal_id=command.principal_id,
            subject_entity_id=command.subject_entity_id,
            expected_subject_version=command.expected_subject_version,
            proposed_kind=command.memory_kind,
            proposed_statement=statement,
            proposed_statement_sha256=statement_digest(statement),
            # `NEEDS_REVIEW` is written as a literal and takes no parameter, so
            # there is no argument a producer could pass to arrive already
            # accepted. `PROPOSED` is the state a candidate would hold if some
            # path decided review was not required; no path here does, because
            # every candidate memory is one private statement about one person
            # and nothing in this build grades that.
            state=MemoryProposalState.NEEDS_REVIEW,
            method=origin.method,
            method_version=origin.method_version,
            # The kind's floor, and not a value anyone chose. A `sensitivity`
            # candidate is `restricted_local` whether the producer thought about
            # it or not, and there is no parameter that could lower it.
            classification=classification_floor_for(command.memory_kind),
            proposed_at=at,
            structured_value=structured,
            model_id=origin.model_id,
            model_version=origin.model_version,
            review_case_id=review_case_id,
        )
        evidence = tuple(
            MemoryProposalEvidence(
                proposal_evidence_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE),
                memory_proposal_id=proposal_id,
                principal_id=command.principal_id,
                role=reference.role,
                created_at=at,
                entity_observation_id=reference.entity_observation_id,
                capture_span_id=reference.capture_span_id,
                knowledge_id=reference.knowledge_id,
            )
            for reference in command.evidence
        )
        repository.record_proposal(proposal, evidence)
        return MemoryProposalReceipt(
            memory_proposal_id=proposal.memory_proposal_id,
            review_case_id=review_case_id,
            subject_entity_id=proposal.subject_entity_id,
            proposed_kind=proposal.proposed_kind,
            state=proposal.state,
            classification=proposal.classification,
            method=proposal.method,
            proposed_at=proposal.proposed_at,
            evidence_count=len(evidence),
        )
