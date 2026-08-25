"""`relationship_memory.propose`: what a producer may raise, and what it may never do.

The producer path is the half of the Relationship Memory plane a source, a rule
or a local model reaches. It exists because extracted memory has to be reviewable
rather than authored, and every claim it makes about itself is a claim someone
could quietly withdraw with one line. So this module is deliberately two kinds of
test:

* **behavioural**, over `RelationshipMemoryProposalService.propose` against a
  fake port — what it records, what it refuses, and what it never touches;
* **structural**, read off the module's own source with `ast` and `dataclasses`
  — the separations that must remain true no matter what a later body does.

The structural half is the part that answers operator §16 ("a source, rule or
model worker must never accept its own proposal") and §12 ("MUST NOT create
active Relationship Memory directly"). A behavioural test can only show that
today's body does not promote. `test_the_producer_service_reaches_no_memory_write`
and `test_the_producer_port_declares_exactly_one_method` show that no body could,
because the object holds no port that promotes and the port it does hold declares
one insert. Restoring either reach reddens them, which is what "load-bearing"
has to mean here. `tests/architecture/test_derivation_proposes_and_never_promotes.py`
is the precedent for reading a promotion boundary off the tree rather than
trusting it.

Nothing here opens a database, a file or a network. Every Principal, entity,
statement and evidence identifier is synthetic.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

import my_pa.application.relationship_memory as producer_module
import my_pa.contracts.ports as ports_module
from my_pa.application.relationship_memory import (
    MemoryProposalOrigin,
    MemoryProposalReceipt,
    ProposedEvidence,
    ProposeMemoryCommand,
    RelationshipMemoryProposalRepository,
    RelationshipMemoryProposalService,
)
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryActorClass,
    MemoryAuthority,
    MemoryBoundsError,
    MemoryKind,
    MemoryKindNotPermittedError,
    MemoryProposalEvidence,
    MemoryProposalMethod,
    MemoryProposalState,
    MemoryStructuredValueError,
    MergedSubjectError,
    RelationshipMemoryError,
    RelationshipMemoryProposal,
    RelationshipMemoryVersion,
    StaleMemoryVersionError,
    classification_floor_for,
    statement_digest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.relationship_memory_proposals import (
    SqlRelationshipMemoryProposalRepository,
)

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"
SUBJECT: Final = "ent_aaaa0001aaaa0001"
OTHER_SUBJECT: Final = "ent_bbbb0002bbbb0002"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)

#: One ordinary candidate's words, and one a `sensitivity` kind would floor.
STATEMENT: Final = "prefers cost questions in writing before the owner meeting"
RESTRICTED_STATEMENT: Final = "declines evening site visits while recovering"

MODULE_SOURCE: Final = Path(producer_module.__file__).read_text(encoding="utf-8")


# --- fixtures and fakes -------------------------------------------------------


def a_subject(**overrides: object) -> Entity:
    """One valid subject entity, so each test states only the field it is about."""
    fields: dict[str, object] = {
        "entity_id": SUBJECT,
        "principal_id": PRINCIPAL,
        "entity_type": EntityType.PERSON,
        "canonical_name": "synthetic person",
        "display_name": "Synthetic Person",
        "status": EntityStatus.ACTIVE,
        "created_at": WHEN,
        "updated_at": WHEN,
        "version": 3,
    }
    return Entity(**{**fields, **overrides})  # type: ignore[arg-type]


def a_command(**overrides: object) -> ProposeMemoryCommand:
    """One valid candidate, resolved against `a_subject()`'s version."""
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "subject_entity_id": SUBJECT,
        "expected_subject_version": 3,
        "memory_kind": MemoryKind.WORKING_PREFERENCE,
        "statement": STATEMENT,
        "structured_value": None,
        "evidence": (
            ProposedEvidence(
                role=EvidenceLinkRole.DIRECT,
                entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
            ),
        ),
    }
    return ProposeMemoryCommand(**{**fields, **overrides})  # type: ignore[arg-type]


A_RULE: Final = MemoryProposalOrigin(
    method=MemoryProposalMethod.RULE, method_version="synthetic-rule-v1"
)


class RecordingRepository:
    """The producer port, plus the two memory-plane methods it must never call.

    `admit` and `replay_for` are the whole write surface of
    `RelationshipMemoryRepository`. They are here, raising, so that "the producer
    wrote no memory" is asserted against a port that *would have answered* rather
    than against one that was never offered — the behavioural half of the claim
    `test_the_producer_service_reaches_no_memory_write` makes structurally.
    """

    def __init__(self) -> None:
        self.recorded: list[tuple[RelationshipMemoryProposal, tuple[MemoryProposalEvidence, ...]]]
        self.recorded = []

    def record_proposal(
        self,
        proposal: RelationshipMemoryProposal,
        evidence: tuple[MemoryProposalEvidence, ...],
    ) -> None:
        self.recorded.append((proposal, evidence))

    def admit(self, request: object) -> object:
        raise AssertionError("the producer path reached a memory write")

    def replay_for(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("the producer path reached the memory idempotency plane")


class _FirstResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class EvidenceScopeConnection:
    """A statement recorder that makes one selected evidence family invisible."""

    def __init__(self, missing_marker: str | None = None) -> None:
        self.missing_marker = missing_marker
        self.queries: list[str] = []
        self.writes: list[str] = []

    def execute(self, statement: Any) -> _FirstResult:  # noqa: ANN401 - SQLAlchemy clause
        rendered = str(statement)
        if statement.is_select:
            self.queries.append(rendered)
            missing = self.missing_marker is not None and self.missing_marker in rendered
            return _FirstResult(None if missing else object())
        self.writes.append(rendered)
        return _FirstResult(None)


def propose(
    repository: RelationshipMemoryProposalRepository,
    command: ProposeMemoryCommand,
    *,
    subject: Entity | None = None,
    origin: MemoryProposalOrigin = A_RULE,
) -> MemoryProposalReceipt:
    return RelationshipMemoryProposalService().propose(
        repository,
        command,
        subject=a_subject() if subject is None else subject,
        origin=origin,
        at=WHEN,
    )


# --- what a producer records --------------------------------------------------


def test_a_candidate_is_recorded_awaiting_review_and_is_not_memory() -> None:
    """The whole point of the path: a proposal, in `needs_review`, with a case."""
    repository = RecordingRepository()

    receipt = propose(repository, a_command())

    assert len(repository.recorded) == 1
    proposal, evidence = repository.recorded[0]
    assert proposal.state is MemoryProposalState.NEEDS_REVIEW
    assert proposal.accepted_memory_id is None
    assert proposal.accepted_memory_version_id is None
    assert proposal.invalidated_reason is None
    assert proposal.proposed_statement == STATEMENT
    assert proposal.proposed_statement_sha256 == statement_digest(STATEMENT)
    assert proposal.proposed_at == WHEN
    assert len(evidence) == 1
    assert evidence[0].memory_proposal_id == proposal.memory_proposal_id
    assert evidence[0].principal_id == PRINCIPAL
    assert receipt.memory_proposal_id == proposal.memory_proposal_id
    assert receipt.state is MemoryProposalState.NEEDS_REVIEW
    assert receipt.evidence_count == 1


def test_a_candidate_carries_a_review_case_so_a_reviewer_actually_sees_it() -> None:
    """`relationship_memory_review_cases` selects on `review_case_id IS NOT NULL`.

    A candidate written without one is recorded, invisible, and indistinguishable
    from suppressed — so the case is minted where the candidate is written rather
    than by a later step someone could omit.
    """
    repository = RecordingRepository()

    receipt = propose(repository, a_command())

    proposal, _ = repository.recorded[0]
    assert proposal.review_case_id is not None
    assert proposal.review_case_id == receipt.review_case_id
    assert parse_identifier(receipt.review_case_id)[0] is IdKind.REVIEW_CASE


def test_two_candidates_are_two_proposals_and_two_cases() -> None:
    """Anti-vacuity for the identifier assertions above: nothing is a constant."""
    repository = RecordingRepository()

    first = propose(repository, a_command())
    second = propose(repository, a_command())

    assert first.memory_proposal_id != second.memory_proposal_id
    assert first.review_case_id != second.review_case_id


def test_every_named_evidence_record_becomes_one_stored_link() -> None:
    """Operator §12 asks for exact evidence references, and exact means all of them."""
    repository = RecordingRepository()
    references = (
        ProposedEvidence(
            role=EvidenceLinkRole.DIRECT,
            entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
        ),
        ProposedEvidence(
            role=EvidenceLinkRole.SUPPORTING, capture_span_id=issue_identifier(IdKind.SPAN)
        ),
        ProposedEvidence(
            role=EvidenceLinkRole.COUNTEREVIDENCE,
            knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
        ),
    )

    receipt = propose(repository, a_command(evidence=references))

    _, evidence = repository.recorded[0]
    assert receipt.evidence_count == 3
    assert [link.role for link in evidence] == [reference.role for reference in references]
    assert len({link.proposal_evidence_id for link in evidence}) == 3
    assert [link.created_at for link in evidence] == [WHEN, WHEN, WHEN]


def test_persistence_validates_each_evidence_family_through_its_principal_chain() -> None:
    recording = RecordingRepository()
    propose(
        recording,
        a_command(
            evidence=(
                ProposedEvidence(
                    role=EvidenceLinkRole.DIRECT,
                    entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
                ),
                ProposedEvidence(
                    role=EvidenceLinkRole.SUPPORTING,
                    capture_span_id=issue_identifier(IdKind.SPAN),
                ),
                ProposedEvidence(
                    role=EvidenceLinkRole.COUNTEREVIDENCE,
                    knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
                ),
            )
        ),
    )
    proposal, evidence = recording.recorded[0]
    connection = EvidenceScopeConnection()

    SqlRelationshipMemoryProposalRepository(connection).record_proposal(  # type: ignore[arg-type]
        proposal, evidence
    )

    assert len(connection.writes) == 4
    observation, span, knowledge = connection.queries
    assert "entity_observations.principal_id" in observation
    assert "capture_versions.owner_principal_id" in span
    assert "captures.owner_principal_id" in span
    assert "JOIN knowledge.capture_versions" in span
    assert "JOIN knowledge.captures" in span
    assert "enrollments.principal_id" in knowledge
    assert "JOIN knowledge.enrollments" in knowledge


@pytest.mark.parametrize(
    "missing_marker",
    ("entity_observations.observation_id", "capture_spans.span_id", "extractions.extraction_id"),
)
def test_missing_or_foreign_evidence_is_indistinguishable_and_writes_no_rows(
    missing_marker: str,
) -> None:
    recording = RecordingRepository()
    propose(
        recording,
        a_command(
            evidence=(
                ProposedEvidence(
                    role=EvidenceLinkRole.DIRECT,
                    entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
                ),
                ProposedEvidence(
                    role=EvidenceLinkRole.SUPPORTING,
                    capture_span_id=issue_identifier(IdKind.SPAN),
                ),
                ProposedEvidence(
                    role=EvidenceLinkRole.COUNTEREVIDENCE,
                    knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
                ),
            )
        ),
    )
    proposal, evidence = recording.recorded[0]
    connection = EvidenceScopeConnection(missing_marker)

    with pytest.raises(
        UnknownScopeError, match="proposal evidence cites a record outside this scope"
    ):
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(  # type: ignore[arg-type]
            proposal, evidence
        )

    assert connection.writes == []


def test_a_candidate_with_no_evidence_is_refused_and_nothing_is_recorded() -> None:
    """An extracted assertion with no record behind it is one a reviewer cannot check."""
    repository = RecordingRepository()

    with pytest.raises(RelationshipMemoryError, match="names the records it rests on"):
        propose(repository, a_command(evidence=()))

    assert repository.recorded == []


def test_a_structured_value_is_validated_and_stored_as_its_schema_envelope() -> None:
    repository = RecordingRepository()
    command = a_command(
        memory_kind=MemoryKind.IMPORTANT_DATE,
        statement="anniversary of joining the programme",
        structured_value={"precision": "month_day", "month": 4, "day": 2, "recurrence": "annual"},
    )

    propose(repository, command)

    proposal, _ = repository.recorded[0]
    assert proposal.structured_value is not None
    assert set(proposal.structured_value) == {"schema", "value"}


def test_a_structured_value_for_a_kind_with_no_schema_is_refused() -> None:
    repository = RecordingRepository()

    with pytest.raises(MemoryStructuredValueError):
        propose(repository, a_command(structured_value={"anything": 1}))

    assert repository.recorded == []


@pytest.mark.parametrize("statement", ["", "   ", "x" * 100_000], ids=["empty", "blank", "vast"])
def test_a_statement_outside_its_bounds_is_refused(statement: str) -> None:
    repository = RecordingRepository()

    with pytest.raises(MemoryBoundsError):
        propose(repository, a_command(statement=statement))

    assert repository.recorded == []


# --- what the server owns -----------------------------------------------------


@pytest.mark.parametrize("kind", list(MemoryKind), ids=lambda kind: kind.value)
def test_the_classification_is_the_kinds_floor_for_every_kind(kind: MemoryKind) -> None:
    """Not a value anyone chose, and not one a producer could lower."""
    repository = RecordingRepository()

    receipt = propose(repository, a_command(memory_kind=kind, structured_value=None))

    proposal, _ = repository.recorded[0]
    assert proposal.classification is classification_floor_for(kind)
    assert receipt.classification is classification_floor_for(kind)


def test_a_sensitivity_candidate_floors_at_restricted_local() -> None:
    """The sharpest case of the rule above, stated on its own because it is the one
    the read plane withholds from `search`."""
    repository = RecordingRepository()

    receipt = propose(
        repository,
        a_command(memory_kind=MemoryKind.SENSITIVITY, statement=RESTRICTED_STATEMENT),
    )

    assert receipt.classification is Classification.RESTRICTED_LOCAL


def test_the_method_and_model_identity_come_from_the_origin_and_not_the_payload() -> None:
    repository = RecordingRepository()
    origin = MemoryProposalOrigin(
        method=MemoryProposalMethod.LOCAL_MODEL,
        method_version="extractor-v4",
        model_id="synthetic-local-model",
        model_version="2026.08",
    )

    receipt = propose(repository, a_command(), origin=origin)

    proposal, _ = repository.recorded[0]
    assert proposal.method is MemoryProposalMethod.LOCAL_MODEL
    assert proposal.method_version == "extractor-v4"
    assert proposal.model_id == "synthetic-local-model"
    assert proposal.model_version == "2026.08"
    assert receipt.method is MemoryProposalMethod.LOCAL_MODEL


def test_a_model_origin_that_names_no_model_is_refused_by_the_domain_record() -> None:
    """One check, in the domain and in the schema. This proves the path reaches it."""
    repository = RecordingRepository()
    origin = MemoryProposalOrigin(
        method=MemoryProposalMethod.LOCAL_MODEL, method_version="extractor-v4"
    )

    with pytest.raises(RelationshipMemoryError, match="names its model"):
        propose(repository, a_command(), origin=origin)

    assert repository.recorded == []


# --- what a producer may not reach --------------------------------------------


def test_the_producer_writes_no_memory_even_when_the_memory_port_is_offered() -> None:
    """`RecordingRepository` answers `admit` and `replay_for` by raising."""
    repository = RecordingRepository()

    propose(repository, a_command())

    assert len(repository.recorded) == 1


def test_the_producer_service_reaches_no_memory_write() -> None:
    """Structural, and the load-bearing form of operator §12 and §16.

    `RelationshipMemoryProposalService` names no `RelationshipMemoryRepository`
    and calls none of the four methods that write memory or decide a review. A
    body restored to promote — or a port added to the class — reddens this.
    """
    service = _code_only(_class_node("RelationshipMemoryProposalService"))
    source = ast.dump(service)
    assert "RelationshipMemoryRepository" not in source, (
        "the producer service names the memory-write port. A producer that holds "
        "the port that writes memory is a producer that can promote its own candidate"
    )
    forbidden = {"admit", "replay_for", "decide", "accept", "promote", "restore"}
    reached = sorted(_called_names(service) & forbidden)
    assert reached == [], f"the producer service calls {reached}"


def test_the_producer_port_declares_exactly_one_method() -> None:
    """The port a producer is handed has nothing on it that could decide anything.

    Read out of `contracts/ports.py` since `WP-RI-B-07`, and the move is the
    reason rather than an inconvenience: the port used to be a `Protocol` beside
    the service, on the argument that a port whose only implementor and only
    caller are one use case is a port the use case may own. `ApplicationService`
    now reaches it through `UnitOfWork.relationship_memory_proposals`, and
    `contracts` may not import `application`, so a port a dispatcher reaches has
    to be declared where `UnitOfWork` can name it. The claim this test makes is
    unchanged and is the whole of operator section 16's structural half.
    """
    port = _port_class("RelationshipMemoryProposalRepository")
    declared = sorted(member.name for member in port.body if isinstance(member, ast.FunctionDef))
    assert declared == ["record_proposal"], (
        f"the producer port declares {declared}. Operator §16 makes 'a producer never "
        "accepts its own proposal' true by the port having no method that could"
    )


def test_no_parameter_of_propose_could_carry_a_decision() -> None:
    """The state is a literal, and there is no argument that could replace it."""
    method = _function_node("RelationshipMemoryProposalService", "propose")
    arguments = {argument.arg for argument in method.args.args + method.args.kwonlyargs}
    assert arguments == {"self", "repository", "command", "subject", "origin", "at"}
    source = ast.dump(_code_only(method))
    assert "NEEDS_REVIEW" in source
    for accepting in ("ACCEPTED", "CORRECTED_ACCEPTED"):
        assert accepting not in source, (
            f"`propose` names {accepting}. A producer path that can write an accepted "
            "state is a producer path that self-promotes"
        )


SERVER_OWNED_FIELDS: Final = frozenset(
    {
        "method",
        "method_version",
        "model_id",
        "model_version",
        "classification",
        "state",
        "review_case_id",
        "authority",
        "cloud_eligible",
        "actor",
        "created_by_actor",
        "proposed_at",
        "accepted_memory_id",
        "accepted_memory_version_id",
        "invalidated_reason",
        "capability",
        "purpose",
        "request_id",
        "requested_at",
        "scope",
        "idempotency_key",
        "correlation_id",
    }
)


def test_the_command_declares_none_of_the_server_owned_fields() -> None:
    """Absence rather than validation, which is this module's stated mechanism.

    Operator §12 and §26 assign every name in `SERVER_OWNED_FIELDS` to the
    server. A field a producer can send is a field a later change can start
    honouring, so none of them exists to send.
    """
    declared = {declared.name for declared in dataclasses.fields(ProposeMemoryCommand)}
    assert declared == {
        "principal_id",
        "subject_entity_id",
        "expected_subject_version",
        "memory_kind",
        "statement",
        "structured_value",
        "evidence",
    }
    assert declared & SERVER_OWNED_FIELDS == set()


def test_the_command_refuses_a_server_owned_field_at_the_constructor() -> None:
    """Anti-vacuity for the claim above: absence really does refuse."""
    with pytest.raises(TypeError):
        ProposeMemoryCommand(  # type: ignore[call-arg]
            principal_id=PRINCIPAL,
            subject_entity_id=SUBJECT,
            expected_subject_version=3,
            memory_kind=MemoryKind.GENERAL_NOTE,
            statement=STATEMENT,
            structured_value=None,
            evidence=(),
            method=MemoryProposalMethod.DETERMINISTIC,
        )


def test_no_producer_type_names_cloud_eligibility() -> None:
    """Operator §12: do not broaden cloud eligibility. Nothing here can name it."""
    for declared in (ProposeMemoryCommand, MemoryProposalOrigin, MemoryProposalReceipt):
        names = {member.name for member in dataclasses.fields(declared)}
        assert not any("cloud" in name for name in names)
    assert not any(
        "cloud" in field.name for field in dataclasses.fields(RelationshipMemoryProposal)
    )


def test_a_promoted_memory_version_still_refuses_cloud_eligibility() -> None:
    """The invariant the absence above relies on, pinned rather than assumed.

    `cloud_eligible` is a stored column on the *version*, defaulting false and
    refused when true. A producer path that could not raise it is only safe while
    that refusal stands, so the refusal is asserted here beside the absence.
    """
    declared = {field.name for field in dataclasses.fields(RelationshipMemoryVersion)}
    assert "cloud_eligible" in declared
    with pytest.raises(RelationshipMemoryError, match="not cloud eligible"):
        RelationshipMemoryVersion(
            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
            memory_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY),
            principal_id=PRINCIPAL,
            version_number=1,
            statement=STATEMENT,
            statement_sha256=statement_digest(STATEMENT),
            memory_kind=MemoryKind.GENERAL_NOTE,
            authority=MemoryAuthority.SOURCE_BACKED_ASSERTION,
            classification=Classification.PRIVATE_LOCAL,
            created_by_actor=MemoryActorClass.REVIEW_PROMOTION,
            recorded_at=WHEN,
            idempotency_key="synthetic-key",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            cloud_eligible=True,
        )


#: Side effects operator §12 forbids this path from adding. Each is checked as a
#: substring of the producer half's source, which is why the list is words a
#: mechanism would have to name rather than concepts it might imply.
FORBIDDEN_SIDE_EFFECTS: Final = (
    "delete",
    "reminder",
    "calendar",
    "notify",
    "email",
    "webhook",
    "outbound",
)


@pytest.mark.parametrize("token", FORBIDDEN_SIDE_EFFECTS)
def test_the_producer_half_adds_no_forbidden_side_effect(token: str) -> None:
    assert token not in _producer_source().lower(), (
        f"the producer half names {token!r}. Operator §12 admits no hard delete, "
        "reminder, task or calendar effect and no external send on this path"
    )


def test_the_producer_source_scan_is_reading_something() -> None:
    """Anti-vacuity: the scan above passes trivially if the slice is empty."""
    source = _producer_source()
    assert "class RelationshipMemoryProposalService" in source
    assert len(source.splitlines()) > 100


# --- the subject, and the version a producer resolved it at -------------------


def test_a_stale_subject_version_is_refused() -> None:
    repository = RecordingRepository()

    with pytest.raises(StaleMemoryVersionError):
        propose(repository, a_command(expected_subject_version=2))

    assert repository.recorded == []


def test_the_validated_subject_version_is_persisted_on_the_proposal() -> None:
    repository = RecordingRepository()

    propose(repository, a_command(expected_subject_version=3))

    proposal, _ = repository.recorded[0]
    assert proposal.expected_subject_version == 3


def test_a_merged_away_subject_is_refused_rather_than_followed() -> None:
    """Following the redirect would review a statement about a different person."""
    repository = RecordingRepository()
    merged = a_subject(status=EntityStatus.MERGED_REDIRECT, superseded_by_entity_id=OTHER_SUBJECT)

    with pytest.raises(MergedSubjectError) as refusal:
        propose(repository, a_command(), subject=merged)

    assert refusal.value.canonical_entity_id == OTHER_SUBJECT
    assert repository.recorded == []


def test_a_subject_belonging_to_another_principal_is_refused() -> None:
    repository = RecordingRepository()

    with pytest.raises(RelationshipMemoryError, match="outside this scope"):
        propose(repository, a_command(), subject=a_subject(principal_id=OTHER_PRINCIPAL))

    assert repository.recorded == []


def test_a_subject_that_is_not_the_one_named_is_refused() -> None:
    """A mis-wired handler cannot bind a candidate to an entity it did not resolve."""
    repository = RecordingRepository()

    with pytest.raises(RelationshipMemoryError, match="resolved against"):
        propose(repository, a_command(subject_entity_id=OTHER_SUBJECT))

    assert repository.recorded == []


def test_a_person_only_kind_is_refused_for_a_subject_that_is_not_a_person() -> None:
    repository = RecordingRepository()

    with pytest.raises(MemoryKindNotPermittedError):
        propose(
            repository,
            a_command(memory_kind=MemoryKind.PERSONAL_DETAIL),
            subject=a_subject(entity_type=EntityType.ORGANIZATION),
        )

    assert repository.recorded == []


# --- disclosure ---------------------------------------------------------------


def test_the_receipt_carries_no_statement_under_any_field() -> None:
    """The absence is the disclosure control, checked by value and not by name."""
    repository = RecordingRepository()

    receipt = propose(
        repository,
        a_command(memory_kind=MemoryKind.SENSITIVITY, statement=RESTRICTED_STATEMENT),
    )

    assert "statement" not in {field.name for field in dataclasses.fields(MemoryProposalReceipt)}
    values = [getattr(receipt, field.name) for field in dataclasses.fields(MemoryProposalReceipt)]
    assert RESTRICTED_STATEMENT not in values
    assert not any(isinstance(value, str) and RESTRICTED_STATEMENT in value for value in values)
    assert RESTRICTED_STATEMENT not in repr(receipt)


def test_the_statement_does_not_survive_a_repr_of_the_command() -> None:
    """Operator §28: the candidate text must not reach a log or a test failure line."""
    rendered = repr(a_command(memory_kind=MemoryKind.SENSITIVITY, statement=RESTRICTED_STATEMENT))
    assert RESTRICTED_STATEMENT not in rendered
    assert "sensitivity" in rendered, "the repr is not rendering the record at all"


@pytest.mark.parametrize(
    ("kind", "statement"),
    [
        (MemoryKind.GENERAL_NOTE, STATEMENT),
        (MemoryKind.SENSITIVITY, RESTRICTED_STATEMENT),
    ],
    ids=["private", "restricted"],
)
def test_a_refusal_reads_the_same_for_a_restricted_candidate(
    kind: MemoryKind, statement: str
) -> None:
    """Operator §28: restricted memory is not disclosed through error differences.

    Every refusal on this path turns on the subject, the expectation or the kind
    and none on the statement, so the two parametrisations must produce the same
    exception type and the same sentence.
    """
    repository = RecordingRepository()

    with pytest.raises(StaleMemoryVersionError) as refusal:
        propose(
            repository,
            a_command(memory_kind=kind, statement=statement, expected_subject_version=99),
        )

    assert str(refusal.value) == "the subject has moved since it was resolved"
    assert statement not in str(refusal.value)


# --- reading the module's own source ------------------------------------------

#: The comment that opens the producer half. The source slice below starts here,
#: so a test asserting "the producer half names no delete" cannot be satisfied by
#: reading a half that moved.
DIVIDER: Final = "# The producer path: `relationship_memory.propose`"


def _producer_source() -> str:
    marker = MODULE_SOURCE.index(DIVIDER)
    return MODULE_SOURCE[marker:]


def _module() -> ast.Module:
    return ast.parse(MODULE_SOURCE, filename=producer_module.__file__)


def _port_class(name: str) -> ast.ClassDef:
    """One class out of `contracts/ports.py`, where the producer's port now lives."""
    source = Path(ports_module.__file__ or "").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source, filename=ports_module.__file__)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in `contracts.ports`; the guard is reading nothing")


def _class_node(name: str) -> ast.ClassDef:
    for node in ast.walk(_module()):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in the module; the guard is reading nothing")


def _function_node(klass: str, name: str) -> ast.FunctionDef:
    for member in _class_node(klass).body:
        if isinstance(member, ast.FunctionDef) and member.name == name:
            return member
    raise AssertionError(f"{klass}.{name} is not in the module; the guard is reading nothing")


def _code_only(node: ast.AST) -> ast.AST:
    """`node` with every docstring removed, so a dump reads code and not prose.

    The guards below assert that a name does *not* appear in a class or a
    function. A docstring that argues about the name it must not call would
    satisfy such a guard by explaining itself, which is precisely the failure the
    guards exist to catch — so the prose is stripped before the dump.
    """
    copied = copy.deepcopy(node)
    for child in ast.walk(copied):
        body = getattr(child, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            del body[0]
    return copied


def _called_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            found.add(target.id)
        elif isinstance(target, ast.Attribute):
            found.add(target.attr)
    return found
