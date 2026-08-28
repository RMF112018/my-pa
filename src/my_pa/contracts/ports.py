"""The ports the 104 capability use cases call, and nothing else.

`docs/architecture/module-boundaries.md` section 5.2 puts application ports here
and section 5.3 gives the application the transaction boundary. `AGENTS.md`
section 2 forbids speculative abstraction. Both are satisfied the same way:
every method below is called by a use case that exists today, and no method
exists because a use case might want one later. There is no registry, no
factory, no generic repository, and no extension point. A port with one
implementation and one caller is the point; a port with a method nobody calls
would be the defect.

**What is deliberately not repeated here.** `domain.source.provider.SourceProvider`
already is the read-only source port and is used as it stands. `SourceProviders`
below is not a second one and not a plugin framework: it is the lookup from an
opaque `src_…` to the adapter already constructed for it, which a use case needs
because a capability names a source by identifier and the composition root is
the only thing that may choose an implementation.

**Why the repositories are separate objects rather than one.** They are the four
nouns the capabilities act on — a configured source, an enrollment, a unit of
work in the job plane, and a knowledge record — and each is reached through the
unit of work that owns the transaction they run in. Splitting them is what keeps
each interface small enough to read; merging them would produce the generic
repository this package is required not to have.

**The unit of work is how a use case gets a transaction.** The persistence layer
this wraps is free functions over a `Connection` with the caller owning the
transaction, so something has to own it, and section 5.3 says that something is
the application. `UnitOfWork` is a context manager: leaving the block normally
commits, leaving it by exception rolls back. A use case therefore cannot half
commit an enrollment and its queued work, because it never sees the connection
that would let it.

**Nothing here carries a physical locator.** Every value crossing these
interfaces is an opaque identifier, a closed enum, a bounded count, or a domain
value that has already refused to hold a path. `KnowledgeRecord` carries
extracted text because `knowledge.read` returns it; it is the one value here
that holds source content, and it is bounded by the caller before it is built.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from types import TracebackType
from typing import Any, ClassVar

from my_pa.contracts.v1.disclosure import Disclosure
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.capture.proposal import MAX_NORMALIZED_VALUE_CHARACTERS, ProposalState
from my_pa.domain.capture.reveal import Reveal
from my_pa.domain.capture.review import (
    REVIEW_REASON_LIMIT,
    CorrectionPatch,
    Disposition,
    EntityProposalReviewCase,
    EntityProposalReviewDecision,
    ReviewCase,
    ReviewDecision,
    ReviewSubjectKind,
)
from my_pa.domain.capture.submission import CaptureKind, CaptureReceipt, CaptureTransport
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.context.preference import (
    ContextPreferenceAdmission,
    ContextPreferenceCurrent,
)
from my_pa.domain.context.run import ContextRunRecord
from my_pa.domain.documents.managed import (
    DocumentState,
    LifecycleTransition,
    ManagedDocument,
    ManagedDocumentReceipt,
    ManagedDocumentVersion,
    validate_managed_media_type,
    validate_managed_title,
)
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.goodnotes.models import (
    GoodNotesPageRaster,
    GoodNotesPageWork,
    GoodNotesReviewCase,
    GoodNotesSemanticProposal,
)
from my_pa.domain.policy.decision import validate_policy_version
from my_pa.domain.relationship.authoring import (
    MAX_EVIDENCE_REFERENCES,
    MAX_INITIAL_ALIASES,
    MAX_INITIAL_IDENTIFIERS,
    EntityWriteOperation,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    AssignmentType,
    DirectedWriteOperation,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.event import RelationshipEvent, RelationshipEventType
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_ACTOR_CLASS,
    DEFAULT_MUTATION_AUTHORITY,
    ENTITY_CHANGE_REASON_LIMIT,
    ActorClass,
    EntityFactEvidenceLink,
    EntityMergeRecord,
    EntityMutationEvent,
    EntityObservation,
    EntityProposal,
    EntityProposalEvidenceLink,
    EntityProposalState,
    EntityResolutionDecision,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationState,
)
from my_pa.domain.relationship.identity import (
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    ResolutionAction,
    UnresolvedMention,
)
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityOperation,
    IdentityPreview,
)
from my_pa.domain.relationship.memory import (
    MemoryActorClass,
    MemoryAdmission,
    MemoryAuthority,
    MemoryContextLink,
    MemoryKind,
    MemoryLifecycle,
    MemoryOperation,
    MemoryProposalEvidence,
    MemoryReceipt,
    RelationshipMemory,
    RelationshipMemoryProposal,
    RelationshipMemoryReviewCase,
    RelationshipMemoryVersion,
)
from my_pa.domain.relationship.profile import OrganizationProfile, PersonProfile
from my_pa.domain.search.query import SearchMatch, SearchQuery, SearchRequest
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    CommitmentWorkView,
    ContinuityEvidenceState,
    ContinuityLifecycleEvent,
    ContinuityObjectKind,
    Decision,
    Task,
)
from my_pa.domain.situation.situation import (
    Frame,
    Project,
    ProjectState,
    PulseItem,
    Situation,
    SituationState,
    Trace,
)
from my_pa.domain.source.enrollment import Enrollment, EnrollmentRequest
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import ConfiguredSource
from my_pa.domain.task.bulk import TaskBulkOperation
from my_pa.domain.task.commitment import Commitment as CommitmentAggregate
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry
from my_pa.domain.task.history import TaskHistoryEntry
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.task import Task as TaskAggregate


class WorkCursorError(Exception):
    """A Work cursor anchor is absent from the authenticated Principal's partition."""


class BulkIdempotencyConflictError(Exception):
    """A concurrent bulk request claimed this Principal/idempotency key first."""


__all__ = [
    "Acceptance",
    "AssignmentWriteRequest",
    "AuditSink",
    "AuthoringConflictError",
    "AuthoringReceipt",
    "CaptureAdmission",
    "CaptureAdmissionRequest",
    "CaptureRepository",
    "CaptureSearchMatch",
    "CaptureSearchOutcome",
    "CaptureSearchRequest",
    "CaptureSummary",
    "CommitmentManagementRepository",
    "CommitmentManagementUnitOfWork",
    "ContextPreferenceRepository",
    "ContextRunRepository",
    "ContinuityAuthoringRepository",
    "ContinuityReadRepository",
    "ContinuityRepository",
    "CounterpartyOption",
    "DirectedReceipt",
    "EnrollmentRepository",
    "EntitiesRepository",
    "EntityChildPage",
    "EntityMutationAdmission",
    "EntityMutationReceipt",
    "EntitySummary",
    "EntityWriteRequest",
    "EvidenceUnavailableError",
    "FrameRepository",
    "InitialAlias",
    "InitialIdentifier",
    "KnowledgeRecord",
    "KnowledgeRepository",
    "ManagedAdmission",
    "ManagedByteStore",
    "ManagedDocumentRepository",
    "ManagedWriteRequest",
    "Operation",
    "OperationQueue",
    "PortError",
    "ProjectRepository",
    "ProposalAdmissionConflictError",
    "PulseRepository",
    "RelationshipEventRepository",
    "RelationshipRepository",
    "RelationshipWriteRequest",
    "RepositoryFailureError",
    "ReviewDecisionRequest",
    "ReviewRepository",
    "SearchOutcome",
    "SituationRepository",
    "SourceProviders",
    "SourceRepository",
    "TaskManagementRepository",
    "TaskManagementUnitOfWork",
    "TraceRepository",
    "UnitOfWork",
    "UnknownScopeError",
    "WorkerHealthRepository",
    "WorkerPlaneStatus",
    "WriteRequestConflictError",
    "WriteRequestEvidence",
    "WriteRequestRepository",
    "WriteRequestResult",
]


class RelationshipRepository(ABC):
    """The governed identity writer and deterministic profile reader.

    There is intentionally no `create_person`, `link_observation`, or `merge`
    method. Canonical state enters only through `apply_resolution`, with the
    exact accepted identity-review decision carried in the resolution value.
    """

    @abstractmethod
    def record_observations(
        self, domain: str, observations: tuple[IdentityObservation, ...]
    ) -> int:
        """Idempotently retain source rows as observations, never people."""

    @abstractmethod
    def open_identity_review(
        self,
        candidates: IdentityCandidateSet,
        action: ResolutionAction,
        *,
        retained_person_id: str | None = None,
        prior_person_id: str | None = None,
    ) -> str:
        """Open one review over an explicit candidate set."""

    @abstractmethod
    def decide_identity_review(
        self,
        review_case_id: str,
        *,
        disposition: str,
        principal_id: str,
        decided_at: datetime,
    ) -> str:
        """Append an accept, reject, or defer decision."""

    @abstractmethod
    def apply_resolution(self, resolution: IdentityResolution, *, display_name: str) -> None:
        """Apply only the exact accepted review, preserving reversible lineage."""

    @abstractmethod
    def direct_merge(self, retained_person_id: str, prior_person_id: str) -> None:
        """Always deny before persistence; present to make the denial test non-vacuous."""

    @abstractmethod
    def profile(self, person_id: str, *, expected_domains: tuple[str, ...]) -> PersonProfile | None:
        """Build a cited profile and timeline over its exact observation set."""

    @abstractmethod
    def organization_profile(self, organization_id: str) -> OrganizationProfile | None:
        """Read time-aware affiliations and their exact observations."""

    @abstractmethod
    def record_source_affiliation(
        self,
        *,
        organization_id: str,
        organization_name: str,
        affiliation_id: str,
        person_id: str,
        observation_id: str,
        role: str | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
    ) -> None:
        """Create organization context only from a governed, linked observation."""

    @abstractmethod
    def record_unresolved_mention(self, mention: UnresolvedMention) -> None:
        """Retain one source-bound unresolved identity without raw mention text."""

    @abstractmethod
    def attach_conversation_participant(
        self,
        conversation_id: str,
        *,
        person_id: str | None = None,
        unresolved_mention_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
    ) -> str:
        """Attach exactly one resolved or unresolved target and exact support."""


# --- WP-RI-02: Entity repository port ----------------------------------------
#
# `EntitiesRepository` is the port for the generalized entity model introduced
# in WP-RI-01.  It is *additive*: it does not modify or replace
# `RelationshipRepository`, which remains the governed identity writer and
# deterministic profile reader for the person-and-organization plane.
#
# Every method takes `principal_id` from the caller and it is the authenticated
# caller's partition, exactly as `RelationshipRepository` and
# `TaskManagementRepository` state: an entity belonging to another Principal is
# answered as an absent one, and a write stamped with another Principal is
# refused before it is written.
#
# `EntitySummary` is a lightweight search result — the fields a list or search
# response needs without the full domain model's validation overhead.


@dataclass(frozen=True, slots=True)
class EntitySummary:
    """A lightweight entity summary for search and list results.

    Carries only the fields a caller needs to identify and display an entity
    without loading the full domain model.  `entity_id` and `entity_type`
    are the minimum required; all other fields are optional display hints.
    """

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    display_name: str
    status: EntityStatus


# --- WP-RI-A-02: the entity plane's governed writes ---------------------------
#
# One request shape for every governed change, the way `MemoryWriteRequest` is one
# shape for four. The alternative -- ten request records -- would be ten copies
# of the same seven server-owned fields and ten places the digest that decides a
# replay could be spelled differently.
#
# **Every identifier a write mints travels in the request and is excluded from
# the digest.** That is `MemoryWriteRequest`'s ordering and it is here for the
# same reason: an entity and its first alias are inserted in one statement pair,
# so both identifiers have to exist before either row does, and a digest that
# included them would make every retry a fresh key -- which is to say, no
# idempotency at all.


@dataclass(frozen=True, slots=True)
class InitialAlias:
    """One name form recorded with the entity it belongs to, at creation.

    `alias_id` is minted by the caller of the port and is excluded from the
    request digest; the three remaining fields are what a repeat of the same
    request would carry again, so those are what the digest reads.
    """

    alias_id: str
    alias_type: AliasType
    normalized_value: str
    display_value: str

    def __post_init__(self) -> None:
        validate_identifier(self.alias_id, IdKind.ENTITY_ALIAS)
        if not isinstance(self.alias_type, AliasType):
            raise ValueError("an initial alias has a closed alias type")
        if not self.normalized_value.strip() or not self.display_value.strip():
            raise ValueError("an initial alias carries both of its forms")


@dataclass(frozen=True, slots=True)
class InitialIdentifier:
    """One external identity recorded with the entity it belongs to, at creation."""

    identifier_id: str
    namespace: ExternalIdentifierNamespace
    normalized_value: str
    display_value: str

    def __post_init__(self) -> None:
        validate_identifier(self.identifier_id, IdKind.EXTERNAL_IDENTIFIER)
        if not isinstance(self.namespace, ExternalIdentifierNamespace):
            raise ValueError("an initial external identifier has a closed namespace")
        if not self.normalized_value.strip() or not self.display_value.strip():
            raise ValueError("an initial external identifier carries both of its forms")


def _check_write_authority(authority: MutationAuthority, actor_class: ActorClass) -> None:
    """The one rule the three write requests share about the pair they carry.

    **The two halves are checked against each other rather than each against a
    list**, because either alone is satisfiable by a value that makes the other
    a lie. `review_accepted` says a review case was dispositioned and
    `review_promotion` says the act was that disposition being carried out; a
    row claiming the first under `user` would attribute a source's conclusion to
    the person who merely accepted it, and a row claiming `review_promotion`
    under `user_confirmed_assertion` would say the user asserted what a promotion
    executed. `MutationAuthority.SYSTEM_DETERMINISTIC` is refused outright on
    these three requests: it "may never, by itself, create or merge an identity"
    by its own definition, and every operation these requests carry is either an
    identity assertion or a fact about one.

    Stated once and called from three `__post_init__`s rather than written three
    times, on `_directed_digest`'s argument: two copies of a rule are two things
    that can start disagreeing.
    """
    if not isinstance(authority, MutationAuthority):
        raise ValueError("an entity write names a known mutation authority")
    if not isinstance(actor_class, ActorClass):
        raise ValueError("an entity write names a known actor class")
    if authority is MutationAuthority.SYSTEM_DETERMINISTIC:
        raise ValueError("a governed entity write is not system-deterministic")
    if (authority is MutationAuthority.REVIEW_ACCEPTED) is not (
        actor_class is ActorClass.REVIEW_PROMOTION
    ):
        raise ValueError("review-accepted authority is carried by a review promotion, and only it")


@dataclass(frozen=True, slots=True)
class EntityWriteRequest:
    """One governed change to the entity plane, already normalized and stamped.

    **Nothing a caller may not choose has a field it could arrive in.** There is
    no `principal_id` a transport controls, no `version` and no
    `superseded_by_entity_id`: the first is the authenticated partition the
    application supplies, and the rest are the server's. A payload naming one is
    refused by the command constructor before this record is built, because the
    command has no such field either.

    **`authority` and `actor_class` are fields, and `WP-RI-B-05` is why.** This
    record carried neither until review promotion had to execute: the writers
    stamped `user_confirmed_assertion` from a module constant, so a fact a
    reviewer accepted from a source or a local model would have been recorded as
    one the user asserted, which section 14 forbids in as many words. They are
    still not caller-supplied and cannot become so -- the transport commands
    have no such field, `FORBIDDEN_PAYLOAD_FIELDS` refuses both names inside a
    proposal payload, and the only two constructors of this record are
    `application.entity_authoring` and the promotion path in
    `application.entity_governance`. What changed is that the *server* now has
    two honest values to choose between instead of one, and `__post_init__`
    keeps the pair consistent: `review_accepted` appears exactly with
    `review_promotion`, so neither half can be stamped without the other.

    `entity_id` is `None` exactly on a create, where `minted_entity_id` carries
    the identifier the server issued instead. `expected_version` is required for
    every operation *except* create, because a state-dependent write without one
    is a blind write, and a create has no state to have read.

    **`expected_version` is the entity's, on every operation including the child
    ones.** A binding, a retirement and an alias correction all change what the
    entity says about itself, so the entity is the aggregate and its version is
    the one concurrency control the plane has. `target_child_version` is the
    *second* expectation the two transition operations carry, so a caller that
    read one identifier and a stale entity, or a current entity and a stale
    identifier, is refused either way rather than in one direction only.
    """

    operation: EntityWriteOperation
    #: The public capability name this write was authorized as. Part of the
    #: ledger's idempotency unique, because one key replayed against a different
    #: capability is a different request and answering it from that row would be
    #: wrong.
    capability: str
    principal_id: str
    correlation_id: str
    audit_id: str
    idempotency_key: str
    server_received_at: datetime
    #: The ledger row this write will be recorded as. Minted here for the reason
    #: every other identifier is: it has to exist before the row does.
    event_id: str
    entity_id: str | None
    expected_version: int | None
    minted_entity_id: str | None = None
    minted_child_id: str | None = None
    entity_type: EntityType | None = None
    display_name: str | None = None
    canonical_name: str | None = None
    status: EntityStatus | None = None
    target_child_id: str | None = None
    target_child_version: int | None = None
    namespace: ExternalIdentifierNamespace | None = None
    alias_type: AliasType | None = None
    normalized_value: str | None = None
    display_value: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    reason: str | None = field(default=None, repr=False)
    #: Capture spans the caller cites for this change. Verified against this
    #: Principal by the implementation before any link row is written.
    evidence: tuple[str, ...] = ()
    initial_aliases: tuple[InitialAlias, ...] = ()
    initial_identifiers: tuple[InitialIdentifier, ...] = ()
    #: Minted link identifiers, one per evidence reference and in the same
    #: order. Excluded from the digest with every other minted identifier.
    minted_evidence_link_ids: tuple[str, ...] = ()
    #: What admitted this change, and under whose class it is recorded. The
    #: defaults are the direct authoring path's, so every existing construction
    #: means what it meant before this pair existed.
    authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY
    actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        validate_identifier(self.event_id, IdKind.ENTITY_MUTATION_EVENT)
        _check_write_authority(self.authority, self.actor_class)
        creating = self.operation is EntityWriteOperation.CREATE
        if creating is (self.entity_id is not None):
            raise ValueError("an entity creation names no entity; every other operation does")
        if creating is (self.minted_entity_id is None):
            raise ValueError("an entity creation carries the identifier the server issued")
        if creating is (self.expected_version is not None):
            raise ValueError("a state-dependent entity write names the version it expects")
        if self.entity_id is not None:
            validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.minted_entity_id is not None:
            validate_identifier(self.minted_entity_id, IdKind.ENTITY)
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("an expected entity version starts at one")
        if self.target_child_version is not None and self.target_child_version < 1:
            raise ValueError("an expected child version starts at one")
        if self.operation.names_an_existing_child != (self.target_child_id is not None):
            raise ValueError("a child transition names the record it transitions, and only then")
        if self.operation.names_an_existing_child != (self.target_child_version is not None):
            raise ValueError("a child transition names the child version it expects")
        if self.target_child_id is not None:
            validate_identifier(
                self.target_child_id,
                IdKind.EXTERNAL_IDENTIFIER
                if self.operation.writes_an_identifier
                else IdKind.ENTITY_ALIAS,
            )
        if self.minted_child_id is not None:
            validate_identifier(
                self.minted_child_id,
                IdKind.EXTERNAL_IDENTIFIER
                if self.operation.writes_an_identifier
                else IdKind.ENTITY_ALIAS,
            )
        if creating and (self.entity_type is None or self.display_name is None):
            raise ValueError("an entity creation carries a type and a display name")
        if not self.idempotency_key:
            raise ValueError("an entity write carries an idempotency key")
        if self.reason is not None and (
            not self.reason.strip() or len(self.reason) > ENTITY_CHANGE_REASON_LIMIT
        ):
            raise ValueError("an entity change reason is a bounded non-blank sentence")
        if len(self.evidence) > MAX_EVIDENCE_REFERENCES:
            raise ValueError("an entity write cites a bounded number of evidence records")
        if len(self.minted_evidence_link_ids) != len(self.evidence):
            raise ValueError("an entity write mints one link identifier per evidence record")
        if len(self.initial_aliases) > MAX_INITIAL_ALIASES:
            raise ValueError("an entity creation carries a bounded number of aliases")
        if len(self.initial_identifiers) > MAX_INITIAL_IDENTIFIERS:
            raise ValueError("an entity creation carries a bounded number of external identities")
        ensure_utc(self.server_received_at)

    @property
    def record_family(self) -> MutationRecordFamily:
        """Which canonical record family this write's primary record belongs to."""
        if self.operation.writes_an_identifier:
            return MutationRecordFamily.IDENTIFIER
        if self.operation.writes_an_alias:
            return MutationRecordFamily.ALIAS
        return MutationRecordFamily.ENTITY

    @property
    def payload_digest(self) -> str:
        """What makes a replay decidable, and a conflicting reuse detectable.

        Every field a caller supplied that could differ between two requests
        carrying one key, and none this layer added: the minted identifiers, the
        correlation identifier, the audit identifier and the receipt time are
        excluded because they differ on every attempt by construction, and
        including any one of them would make every retry a conflict rather than
        a replay.

        The evidence references *are* read, because two requests citing
        different evidence for the same change are different requests -- and
        answering the second from the first's receipt would report evidence as
        recorded that never was.
        """
        payload = {
            "operation": self.operation.value,
            "capability": self.capability,
            "entity_id": self.entity_id,
            "expected_version": self.expected_version,
            "entity_type": None if self.entity_type is None else self.entity_type.value,
            "display_name": self.display_name,
            "canonical_name": self.canonical_name,
            "status": None if self.status is None else self.status.value,
            "target_child_id": self.target_child_id,
            "target_child_version": self.target_child_version,
            "namespace": None if self.namespace is None else self.namespace.value,
            "alias_type": None if self.alias_type is None else self.alias_type.value,
            "normalized_value": self.normalized_value,
            "display_value": self.display_value,
            "effective_from": (
                None if self.effective_from is None else self.effective_from.isoformat()
            ),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "reason": self.reason,
            "evidence": sorted(self.evidence),
            "initial_aliases": sorted(
                [alias.alias_type.value, alias.normalized_value, alias.display_value]
                for alias in self.initial_aliases
            ),
            "initial_identifiers": sorted(
                [
                    identifier.namespace.value,
                    identifier.normalized_value,
                    identifier.display_value,
                ]
                for identifier in self.initial_identifiers
            ),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class EntityMutationReceipt:
    """What a caller is handed once one governed entity write commits.

    **The entity's version is on every receipt, whatever was written.** A child
    write advances the aggregate, so a caller that bound an identifier and then
    tried to retire one using the version it read before the bind would be
    refused -- and the receipt is where it learns the version it now holds
    without having to read the entity again.

    **`canonical_entity_id` is always absent today, and saying so is the point.**
    The completion contract's response shape names a canonical successor "if a
    redirect was met", so the field is here; what is *not* here is a path that
    fills it. A write that meets a merged-away entity refuses with
    `HistoricalEntityError` rather than following the redirect, because
    following it would apply a correction to an identity the caller never named,
    and a refusal produces no receipt. The successor is reached through
    `entities.get`, which returns `superseded_by_entity_id`; it is deliberately
    not carried in the refusal, because `application.errors.SafeDetail` is a
    closed token vocabulary that names fields and never values, and an
    identifier in a public error is a disclosure. The field is kept rather than
    dropped so the shape a later governed-merge capability answers with is
    already the one callers read.

    `created` distinguishes a write that happened from a replay that did not, so
    a retrying client can tell them apart without comparing versions.
    """

    event_id: str
    capability: str
    record_family: MutationRecordFamily
    record_id: str
    entity_id: str
    entity_version: int
    entity_status: EntityStatus
    idempotency_key: str
    issued_at: datetime
    created: bool
    child_id: str | None = None
    child_version: int | None = None
    child_state: str | None = None
    superseded_ids: tuple[str, ...] = ()
    evidence_link_ids: tuple[str, ...] = ()
    canonical_entity_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, IdKind.ENTITY_MUTATION_EVENT)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.entity_version < 1:
            raise ValueError("an entity receipt names a positive version")
        if self.child_version is not None and self.child_version < 1:
            raise ValueError("an entity receipt names a positive child version")
        if not isinstance(self.entity_status, EntityStatus):
            raise ValueError("an entity receipt names a known status")
        ensure_utc(self.issued_at)


@dataclass(frozen=True, slots=True)
class EntityMutationAdmission:
    """The outcome of one governed entity write: the receipt, and whether it is new."""

    receipt: EntityMutationReceipt
    created: bool


@dataclass(frozen=True, slots=True)
class EntityChildPage[T: (ExternalIdentifier, EntityAlias)]:
    """One bounded page of an entity's identifiers or aliases.

    `is_truncated` is proved by reading one row past the ceiling rather than
    inferred from a full page, which is the rule every other listing on this
    plane follows: a page that happened to hold exactly `limit` rows and a page
    that was cut are different facts, and only one of them has a continuation.
    """

    records: tuple[T, ...]
    is_truncated: bool = False


def _directed_digest(payload: dict[str, Any]) -> str:
    """The canonical-JSON sha256 the two directed write requests both compute.

    One function rather than two identical properties, for the reason
    `MemoryWriteRequest.payload_digest` states about its own exclusions: what
    makes a replay decidable is that the *same* material fields hash the same
    way, and two copies of a canonicalisation are two things that can start
    disagreeing about key order or separators.
    """
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True, slots=True)
class AssignmentWriteRequest:
    """One request to create, revise or end an assignment, already normalized.

    **What is immutable is what is absent from a revise, not what is validated
    out of one.** `entity_id`, `assignment_type` and `scope_entity_id` are the
    assignment's semantic identity, and a `REVISE` carries `None` for all three
    because the application never puts a value there -- the command has no field
    to carry one. Correcting an identity is `END` followed by `CREATE`, which is
    the only shape in which the plane can say *both* what was believed and what
    replaced it.

    `expected_entity_version` and `expected_scope_version` are the endpoint
    versions a `CREATE` says it read. They are separate from `expected_version`,
    which is the *assignment's* own, and all three are checked: a create binds a
    new row to two existing entities, so an entity archived or merged between
    the caller's read and this write is exactly the interleaving optimistic
    concurrency exists to refuse.

    **`cleared` is how a revise removes a value, and its absence is how a revise
    keeps one.** `role=None` on a revise means "leave it alone", not "make it
    null" -- the Relationship Memory plane wrote `pinned=False` for an omitted
    field and silently unpinned memories on ordinary wording fixes, and this
    request refuses to repeat it. Removal is still reachable and is reachable
    only by naming the field. Stating a value and naming it in `cleared` is a
    contradiction the command refuses before this request is built.

    `evidence_refs` **replaces** the cited set on a revise rather than adding to
    it, exactly as `context_links` replaces on a memory revision: an additive
    field gives a caller no way to withdraw a citation it now knows to be wrong.
    An empty tuple on a revise therefore clears the citations, which is why it
    is a stated tuple and not an optional one.
    """

    operation: DirectedWriteOperation
    assignment_id: str | None
    principal_id: str
    entity_id: str | None
    expected_entity_version: int | None
    assignment_type: AssignmentType | None
    scope_entity_id: str | None
    expected_scope_version: int | None
    expected_version: int | None
    role: str | None
    discipline: str | None
    responsibility_class: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    cleared: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str | None
    idempotency_key: str
    correlation_id: str
    audit_id: str
    server_received_at: datetime
    #: What admitted this change, and under whose class it is recorded. See
    #: `EntityWriteRequest` for why the pair is a field rather than a constant
    #: at the writer, and `_check_write_authority` for the rule between them.
    #: Deliberately outside `payload_digest`: the digest is over what a *caller*
    #: supplied, and this pair is chosen by the server from which path is
    #: executing, so including it would make an idempotency key mean something
    #: different depending on who replayed it.
    authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY
    actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        _check_write_authority(self.authority, self.actor_class)
        creating = self.operation is DirectedWriteOperation.CREATE
        if creating is (self.assignment_id is not None):
            raise ValueError("an assignment creation names no assignment; the others do")
        if creating is (self.expected_version is not None):
            raise ValueError("a state-dependent assignment write names the version it expects")
        if self.assignment_id is not None:
            validate_identifier(self.assignment_id, IdKind.ASSIGNMENT)
        if creating:
            if self.entity_id is None or self.assignment_type is None:
                raise ValueError("an assignment creation names its subject and its type")
            validate_identifier(self.entity_id, IdKind.ENTITY)
            if self.scope_entity_id is not None:
                validate_identifier(self.scope_entity_id, IdKind.ENTITY)
        elif (
            self.entity_id is not None
            or self.assignment_type is not None
            or self.scope_entity_id is not None
        ):
            raise ValueError("only an assignment creation states its semantic identity")
        if (self.operation is DirectedWriteOperation.END) is (self.reason is None):
            raise ValueError("an assignment end carries a reason and no other operation does")
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("an expected assignment version starts at one")
        for expected in (self.expected_entity_version, self.expected_scope_version):
            if expected is not None and expected < 1:
                raise ValueError("an expected entity version starts at one")
        if not self.idempotency_key:
            raise ValueError("an assignment write carries an idempotency key")
        ensure_utc(self.server_received_at)

    @property
    def payload_digest(self) -> str:
        """What decides replay against conflict for one idempotency key.

        Every field a caller supplied that could differ between two requests
        carrying one key, and none this layer added: the correlation identifier,
        the audit identifier and the receipt time are excluded because they
        differ on every attempt by construction, and including any of them would
        make every retry a conflict. The minted assignment identifier is not in
        the request at all on a create, for the same reason.
        """
        return _directed_digest(
            {
                "operation": self.operation.value,
                "assignment_id": self.assignment_id,
                "expected_version": self.expected_version,
                "entity_id": self.entity_id,
                "expected_entity_version": self.expected_entity_version,
                "assignment_type": (
                    None if self.assignment_type is None else self.assignment_type.value
                ),
                "scope_entity_id": self.scope_entity_id,
                "expected_scope_version": self.expected_scope_version,
                "role": self.role,
                "discipline": self.discipline,
                "responsibility_class": self.responsibility_class,
                "effective_from": _moment(self.effective_from),
                "effective_to": _moment(self.effective_to),
                "cleared": sorted(self.cleared),
                "evidence_refs": sorted(self.evidence_refs),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class RelationshipWriteRequest:
    """One request to create, revise or end a directed edge, already normalized.

    **A revise carries effective dates and evidence and nothing else.** An
    edge's semantic identity is `(from, type, to, scope)` -- all four -- so there
    is no descriptive field left over for a revise to touch, and there is
    deliberately no field here through which a caller could redirect an edge.
    Retargeting is `END` plus `CREATE`, which is also the only way a reader can
    later tell that the first edge was ever asserted.

    **Nothing here generates a reciprocal edge.** `works_for` does not imply
    `manages`, and a plane that minted the inverse would be asserting a fact the
    user did not state and could not later withdraw independently.
    """

    operation: DirectedWriteOperation
    relationship_id: str | None
    principal_id: str
    from_entity_id: str | None
    expected_from_version: int | None
    relationship_type: EntityRelationshipType | None
    to_entity_id: str | None
    expected_to_version: int | None
    scope_entity_id: str | None
    expected_scope_version: int | None
    expected_version: int | None
    effective_from: datetime | None
    effective_to: datetime | None
    cleared: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str | None
    idempotency_key: str
    correlation_id: str
    audit_id: str
    server_received_at: datetime
    #: `AssignmentWriteRequest`'s pair, on its terms and outside the digest for
    #: the same reason.
    authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY
    actor_class: ActorClass = DEFAULT_MUTATION_ACTOR_CLASS

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        _check_write_authority(self.authority, self.actor_class)
        creating = self.operation is DirectedWriteOperation.CREATE
        if creating is (self.relationship_id is not None):
            raise ValueError("an edge creation names no edge; the others do")
        if creating is (self.expected_version is not None):
            raise ValueError("a state-dependent edge write names the version it expects")
        if self.relationship_id is not None:
            validate_identifier(self.relationship_id, IdKind.ENTITY_RELATIONSHIP)
        if creating:
            if (
                self.from_entity_id is None
                or self.to_entity_id is None
                or self.relationship_type is None
            ):
                raise ValueError("an edge creation names both endpoints and its type")
            validate_identifier(self.from_entity_id, IdKind.ENTITY)
            validate_identifier(self.to_entity_id, IdKind.ENTITY)
            if self.scope_entity_id is not None:
                validate_identifier(self.scope_entity_id, IdKind.ENTITY)
        elif (
            self.from_entity_id is not None
            or self.to_entity_id is not None
            or self.relationship_type is not None
            or self.scope_entity_id is not None
        ):
            raise ValueError("only an edge creation states its semantic identity")
        if (self.operation is DirectedWriteOperation.END) is (self.reason is None):
            raise ValueError("an edge end carries a reason and no other operation does")
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("an expected edge version starts at one")
        for expected in (
            self.expected_from_version,
            self.expected_to_version,
            self.expected_scope_version,
        ):
            if expected is not None and expected < 1:
                raise ValueError("an expected entity version starts at one")
        if not self.idempotency_key:
            raise ValueError("an edge write carries an idempotency key")
        ensure_utc(self.server_received_at)

    @property
    def payload_digest(self) -> str:
        """What decides replay against conflict, on `AssignmentWriteRequest`'s terms."""
        return _directed_digest(
            {
                "operation": self.operation.value,
                "relationship_id": self.relationship_id,
                "expected_version": self.expected_version,
                "from_entity_id": self.from_entity_id,
                "expected_from_version": self.expected_from_version,
                "relationship_type": (
                    None if self.relationship_type is None else self.relationship_type.value
                ),
                "to_entity_id": self.to_entity_id,
                "expected_to_version": self.expected_to_version,
                "scope_entity_id": self.scope_entity_id,
                "expected_scope_version": self.expected_scope_version,
                "effective_from": _moment(self.effective_from),
                "effective_to": _moment(self.effective_to),
                "cleared": sorted(self.cleared),
                "evidence_refs": sorted(self.evidence_refs),
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class DirectedReceipt:
    """What one admitted directed write leaves behind.

    **The mutation-ledger row is the receipt on this plane**, which is why
    `mutation_event_id` is the identifier a caller is handed rather than a
    reference into a receipt store this Phase does not build. The row is
    append-only, carries the request digest, the idempotency key, the before and
    after state and the audit identifier, so re-reading it answers every
    question a separate receipt record would have.

    `replayed` says the write did not happen this time because it had already
    happened under this key. It is a separate field from anything in the payload
    because a caller retrying after a timeout has to be able to tell "I did this"
    from "this was already done", and both are successes.
    """

    mutation_event_id: str
    record_id: str
    record_family: MutationRecordFamily
    prior_version: int | None
    version: int
    state: str
    audit_id: str
    idempotency_key: str
    superseded_id: str | None
    evidence_refs: tuple[str, ...]
    issued_at: datetime
    replayed: bool


class EntitiesRepository(ABC):
    """The generalized entity read/write port for relationship intelligence v0.3.

    **Additive alongside `RelationshipRepository`.** This port serves the
    `Entity`/`ExternalIdentifier`/`Assignment`/`EntityRelationship` model
    introduced in WP-RI-01.  The existing `RelationshipRepository` serves the
    person-and-organization-only WP-9 substrate and is not modified.

    **`principal_id` is a parameter on every method**, and it is the
    authenticated caller's partition, never a caller-supplied field: the
    concrete repository stamps every write with it and filters every read by
    it, so an entity belonging to another Principal is unreachable through
    this port.

    **Authorization is checked centrally in `authorization.py`**, not in the
    repository.  This port performs only data access; it does not decide
    whether the caller may access it.
    """

    @abstractmethod
    def search(
        self,
        principal_id: str,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 50,
        *,
        after_entity_id: str | None = None,
    ) -> list[EntitySummary]:
        """One bounded page of entities whose canonical or display name matches `query`.

        `after_entity_id` continues a previous page: it names the last entity of
        that page, and the rows after it in this read's own `(canonical_name,
        entity_id)` order come back. It was the last read on this plane without a
        continuation — every other listing could be paged and this one, the
        browse surface a person actually scrolls, could only be truncated.

        A case-insensitive substring match over `canonical_name` and
        `display_name`, scoped by `principal_id` and optionally by
        `entity_type`. Aliases are *not* searched, and that is now a decision
        rather than a gap: `entity_aliases` has existed since `b7f4d1a92c36`,
        and this method still reads only the two name columns.

        Searching aliases would put a nickname, a maiden name and a former
        legal name into a browse result that nobody asked a question about --
        the disclosure `entities.resolve` makes deliberately, made incidentally
        here. A caller who wants alias matching asks the question that means
        it: `entities.resolve` matches aliases and says so in its evidence.
        """

    @abstractmethod
    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        """One entity in this Principal's partition, or `None`.

        `principal_id` is part of the lookup key, not a filter applied after
        the fact: an entity belonging to another Principal is answered as an
        absent one, never as a filtered-out one.
        """

    @abstractmethod
    def create(self, principal_id: str, entity: Entity) -> Entity:
        """Insert one entity row, or return the identical existing one.

        `principal_id` is a parameter here for the reason it is on every other
        write: without it this method took its partition from a field on the
        object handed to it, compared against nothing — so the one method that
        brings a person into existence was the one method that could not refuse
        a foreign Principal, while the port's own preamble said none could.

        Idempotent against the entity's own identifier: a repeat carrying the
        same values returns the stored row, and a repeat carrying different
        values under an identifier already issued is refused rather than
        silently dropped or silently applied.
        """

    @abstractmethod
    def record_alias(self, principal_id: str, alias: EntityAlias) -> None:
        """Record one alias of an entity, idempotently against the *active* one.

        The natural key is `(principal_id, entity_id, alias_type,
        normalized_value)` and it is enforced over the active row only -- a
        partial unique since `2fe4e13fb449`, and a total unique over
        `(entity_id, alias_type, normalized_value)` before it.  Note what that
        key does *not* say: two different entities may hold the same alias,
        because two real people share a name, and a schema that refused it would
        force one of them into the other.

        What `state` changes is what a *repeat* means.  Recording a name form
        this entity actively carries under this alias type is still a no-op,
        whatever `alias_id` the caller minted, because that is what a duplicate
        is.  Recording a `RETIRED` or `SUPERSEDED` form of the same value is a
        **write**: a row outside `ACTIVE` sits outside the unique's predicate,
        so a former name and the name that replaced it are both held.  The total
        unique made that impossible -- recording the correction meant deleting
        the record of what the entity used to be called -- and deleting it is
        what section 10.11 forbids.

        Nothing here is refused.  Unlike `bind_identifier` the unique is already
        per entity, so a conflicting active row can only ever be this entity's
        own.
        """

    @abstractmethod
    def aliases(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[EntityAlias]:
        """Aliases recorded for an entity in this Principal's partition.

        `limit` caps how many rows come back as a `LIMIT` on the query rather
        than a slice of the result, for the reason `observations` states: a
        caller that fetched every alias and kept twenty-five has already paid
        for the ones it discarded, and an entity accumulates an alias for every
        spelling any source ever used for it.

        `None` is genuinely unbounded and is the default, because every existing
        caller reads this collection whole and changing that silently would turn
        a complete answer into a partial one nobody was told about. A caller
        that passes a limit is expected to disclose in its own answer that it
        did -- `EntityContextService` fetches one row past its ceiling and
        reports `MORE_ALIASES_THAN_THIS_CARD_CARRIES` from the overflow.
        """

    @abstractmethod
    def entities_by_identifier(
        self,
        principal_id: str,
        namespace: ExternalIdentifierNamespace,
        normalized_value: str,
    ) -> list[tuple[Entity, ExternalIdentifier]]:
        """Every entity holding this external identity, with the record that says so.

        Returns the identifier row alongside the entity rather than the entity
        alone, because resolution has to report *why* a candidate is a candidate
        and whether the evidence was verified and effective (`RI-AC-011`).

        More than one result is not an error here -- it is the
        `CONFLICTED_IDENTIFIER` case the caller must be able to see. Deciding
        what to do about it is the resolution service's job, not this port's.
        """

    @abstractmethod
    def entities_by_alias(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityAlias]]:
        """Every entity carrying this normalized alias, with the alias that matched."""

    @abstractmethod
    def entities_by_canonical_name(self, principal_id: str, normalized_value: str) -> list[Entity]:
        """Every entity whose canonical name is exactly this normalized value.

        An equality match, not a substring one: `search` is the substring
        surface, and resolution asks a different question -- who *is* this --
        for which a partial match is evidence of nothing.
        """

    # --- WP-RI-06: observation, proposal, and merge lineage -----------------
    #
    # These are the governed half of the plane. They are on this port rather
    # than a second one because they read and write the same partition through
    # the same transaction, and a second port over the same rows would be a
    # second place the partition has to be remembered.

    @abstractmethod
    def record_observation(self, principal_id: str, observation: EntityObservation) -> None:
        """Record one source-bound observation. Idempotent on its identifier.

        Recording an observation never creates or modifies an entity.  Section
        12.2 is explicit that a source row "does not become the canonical person
        by itself", and this method is where that is true rather than intended.

        **`normalized_value` is matched against and is never disclosed;
        `mention_display_name` is disclosed and is never matched against.**
        That separation is the whole reason the second column exists, and it
        replaced a sentence here that asked callers to keep raw text out of the
        first. The sentence could not be enforced: `normalize_name` casefolds
        and replaces punctuation and removes no content, so
        `normalize_name("A. Chen <a.chen@northwind.test>")` is
        `"a chen a chen northwind test"` — local part and domain intact, and
        `is_normalized_name`-true — which means no check over the stored string
        distinguishes it from a long legitimate name.

        So put whatever matching needs in `normalized_value`, and put in
        `mention_display_name` only what an operator should see on the review
        queue. Leaving it `None` is a safe default and the right one when the
        source span is not a name a person would recognise: the mention is still
        queued with its source pointers, carrying no text.
        """

    @abstractmethod
    def observations(
        self,
        principal_id: str,
        entity_id: str | None = None,
        *,
        unresolved_only: bool = False,
        limit: int | None = None,
        after_observation_id: str | None = None,
    ) -> list[EntityObservation]:
        """Observations in this Principal's partition.

        `entity_id` selects those linked to one entity. `unresolved_only`
        selects those linked to none, which is the unresolved-mention queue and
        the reason `entity_id` is nullable at all.

        `limit` caps how many rows come back, as a `LIMIT` on the query rather
        than a slice of the result -- this is the one table on the plane that
        grows with every source record that ever mentioned anyone, so an
        implementation that fetched everything and truncated would have already
        paid the cost the cap exists to avoid.

        `None` is genuinely unbounded, and is right only where a short answer
        would be a misleading one: the unresolved-mention queue, where a caller
        shown a truncated list with nothing saying so would believe they had
        reached the end. Everywhere else a caller passes a limit -- and is
        expected to disclose in its own answer that it did.
        """

    @abstractmethod
    def observation(self, principal_id: str, observation_id: str) -> EntityObservation | None:
        """One observation in this Principal's partition, or `None`.

        `None` for a foreign observation as well as an absent one, which is the
        rule the whole port keeps: a record belonging to somebody else has to be
        indistinguishable from a record that does not exist, or the absence
        itself discloses that it does.

        A read of its own rather than a scan of `observations`, because every
        caller that decides something about one mention needs its current
        `resolution_version`, and reading a page to find one row would make the
        cost of a decision grow with the size of the queue.
        """

    @abstractmethod
    def link_observation(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        """Link one observation to an entity.

        Separate from recording it, because the two happen at different times
        for different reasons: a source produces the observation, and a
        resolution or a review decides what it refers to.
        """

    # --- WP-RI-A-04: the three ledgers WP-RI-A-01 created and left unwritten ---
    #
    # `entity_mutation_events`, `entity_resolution_decisions` and
    # `entity_fact_evidence_links` arrived with the revision that created them
    # and with no writer at all. These are the writes. They are on this port
    # for the reason the governance half is: the same partition, through the
    # same transaction, and a ledger row that could be written outside the
    # transaction that made the change it records would be a ledger that
    # disagrees with the plane.

    @abstractmethod
    def record_mutation_event(self, principal_id: str, event: EntityMutationEvent) -> None:
        """Append one row to the mutation ledger, which is also the idempotency store.

        `(principal_id, capability, idempotency_key)` is unique at the server,
        so two concurrent writers holding one key produce one row and the loser
        raises. Implementations raise `EntityMutationConflictError` when the key is
        held with a *different* `request_digest` -- the caller replayed nothing
        and asked for something else -- and let the constraint violation
        surface otherwise.

        Append-only by trigger. There is no update and no delete, and this port
        offers neither.
        """

    @abstractmethod
    def mutation_event(
        self, principal_id: str, *, capability: str, idempotency_key: str
    ) -> EntityMutationEvent | None:
        """The ledger row this key already wrote under this capability, or `None`.

        The replay pre-read. It is an optimisation and never the decision:
        `record_mutation_event` still relies on the unique constraint, so two
        writers that both read `None` still produce one row.
        """

    @abstractmethod
    def record_resolution_decision(
        self, principal_id: str, decision: EntityResolutionDecision
    ) -> None:
        """Append one disposition of one observation.

        Append-only by trigger, and `UNIQUE (observation_id, sequence)` orders
        the decisions about one observation. A sequence already taken raises
        rather than overwriting: two reviewers deciding one mention is the case
        this table exists to make visible, not the case it absorbs.
        """

    @abstractmethod
    def resolution_decisions(
        self,
        principal_id: str,
        observation_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[EntityResolutionDecision]:
        """Decisions in this Principal's partition, optionally about one observation."""

    @abstractmethod
    def decide_observation(
        self,
        principal_id: str,
        observation_id: str,
        *,
        expected_resolution_version: int,
        entity_id: str | None = None,
        state: ObservationState | None = None,
        state_reason: str | None = None,
    ) -> bool:
        """Advance one observation's resolution version, or write nothing.

        **One guarded `UPDATE` whose rowcount decides everything.** The
        `WHERE` names the Principal, the observation and
        `resolution_version = expected_resolution_version`; a stale expectation
        matches no row, returns `False`, and leaves every column as it was. The
        caller checks the answer before writing anything else, so a decision
        that lost the race writes no ledger row, no evidence link and no
        decision either.

        `entity_id` binds the observation to an entity, which is what
        `link_existing` and `create_new` do. `state` and `state_reason` move it
        out of `CURRENT`, which is what `quarantine` does. Passing neither is a
        decision that changed nothing about the observation except that it has
        now been decided -- `defer` and `reject` -- and the version still
        advances, because deciding is what the version counts.
        """

    @abstractmethod
    def record_fact_evidence_link(self, principal_id: str, link: EntityFactEvidenceLink) -> None:
        """Bind one canonical fact to the single record that evidences it.

        **Not trigger-protected, and that is a property of the table rather
        than an oversight.** `entity_fact_evidence_links` carries six CHECKs and
        six cascading foreign keys and no trigger: its rows are editable and are
        deleted with the fact they cite, because a link to a fact that no longer
        exists is not evidence of anything. The decision that *cited* the link
        is on `entity_resolution_decisions`, which is append-only, so what was
        decided survives even where what it pointed at does not.
        """

    @abstractmethod
    def fact_evidence_links(
        self,
        principal_id: str,
        *,
        entity_observation_id: str | None = None,
        role: EvidenceRole | None = None,
        limit: int | None = None,
    ) -> list[EntityFactEvidenceLink]:
        """Evidence links in this Principal's partition.

        `role=EvidenceRole.COUNTEREVIDENCE` with an observation is how the
        resolution path reads persisted negative identity evidence: the pairings
        a user has already refused, so the same one is not proposed again.
        """

    @abstractmethod
    def record_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        """Record one proposed mutation. Idempotent on its identifier.

        Recording a proposal applies nothing.  A proposal is a request, and the
        decision that grants it is `decide_proposal`.
        """

    @abstractmethod
    def proposal(self, principal_id: str, proposal_id: str) -> EntityProposal | None:
        """One proposal in this Principal's partition, or `None`."""

    @abstractmethod
    def proposal_target_version(
        self,
        principal_id: str,
        family: MutationRecordFamily,
        record_id: str,
    ) -> int | None:
        """The current version of the existing record a reprocess targets."""

    @abstractmethod
    def proposals(
        self, principal_id: str, state: EntityProposalState | None = None
    ) -> list[EntityProposal]:
        """Proposals in this Principal's partition, optionally by state."""

    def serialize_entity_proposal_review_scope(
        self,
        principal_id: str,
        review_case_id: str,
        *,
        correction_patch: Mapping[str, str | bool] | None = None,
    ) -> EntityProposal | None:
        """Lock every Entity participant a proposal review could mutate.

        The implementation performs its own optimistic read, acquires the
        participant locks in stable order, then re-reads and validates the
        proposal and any indirect child target before returning it.  A corrected
        acceptance contributes its corrected payload references to the same
        lock union, so promotion cannot acquire a new participant after the
        proposal row or review ledger has been touched.

        Non-abstract because external in-memory repositories execute serially;
        SQL implementations must override it before composing Entity review.
        """
        proposal = next(
            (row for row in self.proposals(principal_id) if row.review_case_id == review_case_id),
            None,
        )
        return proposal

    def entity_proposal_review_snapshot(
        self, principal_id: str, review_case_id: str
    ) -> tuple[int, str | None, bool] | None:
        """Return a text-free, Principal-scoped case ledger snapshot.

        The members are review version, latest disposition and whether the case
        was ever escalated. Identity-correction planning binds this bounded
        derived state so any ledger-only decision makes a preview stale without
        exposing decision narrative.
        """
        return (
            (0, None, False)
            if any(
                proposal.review_case_id == review_case_id
                for proposal in self.proposals(principal_id)
            )
            else None
        )

    def proposal_by_dedupe(
        self,
        principal_id: str,
        dedupe_sha256: str,
        states: Iterable[EntityProposalState],
    ) -> EntityProposal | None:
        """The proposal this Principal already has under `dedupe_sha256` in `states`.

        The read the open-equivalent unique index is already over. `propose` did
        this as one `proposals(principal_id, state)` call per open-equivalent
        state and compared the digests in Python, which is correct -- the partial
        unique is the authority either way -- and is a scan of every open
        proposal on every create.

        `states` is a parameter rather than `OPEN_EQUIVALENT_PROPOSAL_STATES`
        read here, because a port that named the set would make widening the
        set a change to the port. The caller that owns the rule passes it.

        Non-abstract with a `NotImplementedError` default, on the terms the
        identity-correction methods below are: this port has implementations
        outside this package's own repository.
        """
        raise NotImplementedError

    def record_proposal_evidence_link(
        self, principal_id: str, link: EntityProposalEvidenceLink
    ) -> None:
        """Bind one proposal to a single record it rests on.

        The writer `knowledge.entity_proposal_evidence_links` was created
        without. `EntityProposal.observation_ids` can say "these observations
        were cited"; it cannot cite the capture span a user's own note came
        from, cannot cite a knowledge record, and cannot say that one of the
        records it lists argues *against* the proposal.

        **Same-Principal is proved before the write on the half the schema
        cannot prove.** The proposal and the observation carry composite
        `(id, principal_id)` foreign keys; `capture_spans` carries no principal
        partition, so a span is walked to the capture that owns it, exactly as
        `entity_fact_evidence_links`' writer does. A span behind another
        Principal's capture answers what an absent span answers.
        """
        raise NotImplementedError

    def proposal_evidence_links(
        self, principal_id: str, proposal_id: str
    ) -> list[EntityProposalEvidenceLink]:
        """Everything one proposal rests on, in the order it was cited."""
        raise NotImplementedError

    def merge_proposal_evidence_links(
        self,
        principal_id: str,
        proposal_id: str,
        evidence: Iterable[EntityProposalEvidenceLink],
    ) -> list[EntityProposalEvidenceLink]:
        """Atomically append exact new evidence and return the stored set."""
        raise NotImplementedError

    def proposal_evidence_for(
        self, principal_id: str, proposal_id: str
    ) -> tuple[EntityProposalEvidenceLink, ...]:
        """The immutable exact evidence set used by canonical promotion.

        Kept as a promotion-facing read separate from the legacy list-shaped
        method so callers cannot accidentally fall back to
        ``EntityProposal.observation_ids``. Existing repositories get the exact
        behavior through their ordered link read; persistence owners may
        implement it directly when adding stronger atomicity guarantees.
        """
        return tuple(self.proposal_evidence_links(principal_id, proposal_id))

    def record_proposal_promotion(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        record_family: MutationRecordFamily,
        record_id: str,
        record_version: int,
    ) -> None:
        """Name the canonical record an accepted proposal became.

        Separate from `decide_proposal` because the two happen at different
        moments and one of them can fail: the decision is claimed first, under
        the guarded `UPDATE` that makes deciding a one-time act, and the record
        it produced can only be named once the canonical service has returned a
        receipt. A single call that carried both would have to be issued *after*
        the write, which would leave the window in which a second reviewer could
        decide the same proposal and promote it again.

        Refuses a proposal that is not accepted and refuses one already carrying
        a record, so this cannot become a way to re-point an acceptance at a
        different canonical row.
        """
        raise NotImplementedError

    def supersede_proposal(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        successor_proposal_id: str,
        at: datetime,
    ) -> bool:
        """Retire one undecided proposal in favour of the successor that replaced it.

        Section 13's `reprocess`: "creates successor proposal against current
        evidence/method; predecessor remains historical/superseded". This writes
        the predecessor half. `WP-RI-B-05` provides it and deliberately does not
        provide `reprocess` -- the disposition, the successor's production and
        the review case are the Review plane's, and a repository method that
        also minted the successor would be that plane living here.

        Returns whether a row moved. `False` means the proposal was already
        decided or superseded, which is what makes a stale reprocess create
        nothing rather than overwrite a decision.
        """
        raise NotImplementedError

    @abstractmethod
    def decide_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        """Replace one proposal with its decided form.

        Takes the whole record rather than the fields, so the decided proposal
        has been through `EntityProposal.__post_init__` -- which is what refuses
        a decision with no actor, or an actor on an undecided proposal.
        """

    @abstractmethod
    def record_merge(self, principal_id: str, record: EntityMergeRecord) -> None:
        """Record the lineage of one accepted merge."""

    @abstractmethod
    def merges(self, principal_id: str, entity_id: str | None = None) -> list[EntityMergeRecord]:
        """Merge lineage in this Principal's partition, optionally touching one entity."""

    @abstractmethod
    def redirect_entity(
        self,
        principal_id: str,
        merged_entity_id: str,
        retained_entity_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        """Point one entity at the entity it was merged into.

        Sets `status` to `merged_redirect` and `superseded_by_entity_id` to the
        survivor. Governed correction supplies ``expected_version`` and is
        refused unless the row is still current at that version. The merged
        entity is not deleted: section 15.3 asks a merge to
        preserve prior identifiers as lineage, and a row that still resolves as a
        `HISTORICAL_MATCH` is how that is done.
        """

    @abstractmethod
    def bind_identifier(
        self, principal_id: str, entity_id: str, identifier: ExternalIdentifier
    ) -> None:
        """Bind one external identifier to an entity, idempotently against the *active* one.

        The identifier's `entity_id` must match `entity_id` and its
        `principal_id` must match the acting Principal.

        **The uniqueness this write is idempotent against is not the one this
        docstring stated until `2fe4e13fb449`.**  It said the natural key was
        `(entity_id, namespace, normalized_value)` and that a repeat of it was a
        no-op.  The key is now `(principal_id, namespace, normalized_value)`
        enforced over rows whose `state` is `ACTIVE` only, and the move changed
        the answer in three places, in both directions.

        *Still a no-op.*  Re-binding an address this entity already holds as its
        current identity, whatever `identifier_id` the caller minted for it,
        because that triple is what "the same external identity" means.

        *No longer a no-op -- it **writes**.*  Recording a `RETIRED` or
        `SUPERSEDED` binding of a value this entity already carried, and then
        recording its replacement.  A row outside `ACTIVE` falls outside the
        unique's predicate, so an address that was retired and later reissued is
        held as the several rows it actually was.  The total unique forced the
        plane to *delete* the retired row in order to record the new one, and
        the deleted row is the one that resolves a message sent before the
        address changed.  A caller that binds twice and expects one row must now
        say `ACTIVE` both times to get it.

        *Refused rather than absorbed.*  An address that is currently a
        **different** entity's raises `ConflictedIdentifierError`.  The unique spans the
        Principal rather than the entity, so the row that conflicts need not be
        the caller's -- and answering that with silence would report a binding
        the store does not hold.  Deciding that two entities are the same person
        is a merge, and a merge is a proposal, not a side effect of a bind.

        Concurrency is the implementation's problem, not the caller's: if the
        conflicting holder is retired by another session between the write and
        the read-back that identifies it, the bind is retried and succeeds, and
        a store that cannot settle the question raises `UnsettledBindingError`
        rather than letting a driver exception out through this boundary.

        **The two refusals are different classes, and until `WP-RI-A-02` they
        were one.**  Both were a bare `ValueError` separated only by message, so
        a handler that classified `ValueError` reported a retryable race as a
        permanent conflict -- telling a caller to stop when the address may
        already be free.  Both classes still subclass `ValueError`, so an
        existing `except ValueError` catches them unchanged; a caller that needs
        to tell them apart now can, without comparing strings.
        """

    @abstractmethod
    def external_identifiers(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[ExternalIdentifier]:
        """External identifiers bound to an entity in this Principal's partition.

        `limit` is a query-time `LIMIT` on the same terms as `aliases`, and
        defaults to `None` for the same reason: resolution reads this collection
        whole to decide whether an identifier is conflicted, and a bound applied
        without its knowledge would let a conflict fall off the end of a page
        and read as a clean match.
        """

    @abstractmethod
    def record_assignment(self, principal_id: str, assignment: Assignment) -> None:
        """Record one assignment.

        The assignment's `entity_id`, `scope_entity_id` and `principal_id` are
        verified against the acting Principal before the row is written --
        including the scope, because the schema's foreign key spans every
        Principal and would otherwise admit a cross-partition join.

        Idempotent against the assignment's own identifier, on the same terms
        as `create`.  It is *not* yet idempotent against a natural key: a retry
        that mints a fresh `assignment_id` writes a second row.  Closing that
        needs an idempotency key on a write path, and no work package has one
        yet.
        """

    @abstractmethod
    def assignments(
        self,
        principal_id: str,
        entity_id: str,
        active_only: bool = True,
        *,
        limit: int | None = None,
    ) -> list[Assignment]:
        """Assignments involving an entity, scoped by `principal_id`.

        When `active_only` is true, returns only assignments with status
        `'active'`.

        `limit` is a query-time `LIMIT` on the same terms as `aliases`. It
        matters more here than the name suggests: `active_only=False` is the
        *historical* read, and `WP-RI-12`'s own fixture minimum asks for fifty
        deliberate historical assignment changes on a single programme, so the
        one collection guaranteed to grow without bound in a synthetic corpus is
        this one read with the filter off.
        """

    @abstractmethod
    def record_relationship(self, principal_id: str, rel: EntityRelationship) -> None:
        """Record one entity relationship.

        The relationship's `from_entity_id`, `to_entity_id`, `scope_entity_id`
        and `principal_id` are verified against the acting Principal before the
        row is written, for the reason `record_assignment` states.

        Idempotent against the relationship's own identifier, and not yet
        against a natural key, on the same terms as `record_assignment`.
        """

    @abstractmethod
    def relationships(
        self,
        principal_id: str,
        entity_id: str,
        direction: str = "any",
        *,
        limit: int | None = None,
        after_relationship_id: str | None = None,
    ) -> list[EntityRelationship]:
        """Entity relationships involving an entity, scoped by `principal_id`.

        `direction` is `'any'` (default), `'outgoing'` (from_entity_id matches),
        or `'incoming'` (to_entity_id matches).

        **Depth one was the only bound this read had.** Adjacency is what stops
        a graph walk; it is not what stops a hub. A programme every person on it
        is assigned to has an edge per person, so "one hop from this entity" and
        "a bounded number of rows" are different claims, and only the first was
        being made. `limit` makes the second, as a `LIMIT` on the query rather
        than a slice of the result -- the cost the cap exists to avoid is paid
        the moment the rows leave the server.

        `after_relationship_id` continues a previous page: rows are ordered by
        `relationship_id` and this excludes every identifier at or before the
        one named. A keyset rather than an offset, because `relationship_id` is
        unique and the order is total, so a row inserted between two requests
        cannot shift a later page backwards and hide an edge -- which is exactly
        the failure an `OFFSET` has on a table that is still being written to.

        Both default to today's behaviour -- every edge, from the beginning --
        because resolution and re-enrichment read this collection whole, and a
        bound introduced beneath them would answer "no such relationship" for an
        edge that is recorded.
        """

    # --- WP-RI-A-02: the governed write path ---------------------------------
    #
    # Two methods for the whole write half, plus two paged reads. The writes are one
    # method because they share one transaction, one idempotency store and one
    # concurrency control: the entity is the aggregate, `entity_mutation_events`
    # is both its ledger and its replay index, and a second method would be a
    # second place the guarded `UPDATE` has to be remembered.
    #
    # The methods above stay exactly as they were. `create`, `bind_identifier`
    # and `record_alias` are the *unguarded* writes the resolution and
    # re-enrichment paths already use, and narrowing them to require an expected
    # version and an idempotency key would break every existing caller for the
    # benefit of one that has both.

    @abstractmethod
    def admit_mutation(self, request: EntityWriteRequest) -> EntityMutationAdmission:
        """Admit one governed entity write, or return the receipt its key is bound to.

        Raises `EntityIdempotencyConflictError` when the key is bound to a
        materially different request, `StaleEntityVersionError` when the named
        expected entity or child version is no longer current,
        `HistoricalEntityError` when the entity has been merged away,
        `AmbiguousEntityError` when a create cannot be told apart from entities
        that already exist, `ConflictedIdentifierError` when an address is
        already a different entity's current identity,
        `DuplicateEntityFactError` when the transition is not available from the
        state the record holds, `EntityEvidenceError` when a cited span is not
        this Principal's, and `UnknownScopeError` when the request names an
        entity or child record this Principal does not hold.

        **A refused write leaves nothing behind.** The guarded `UPDATE` on the
        entity is the first statement of every operation that names one, and its
        row count is read before any other row is written -- so a stale
        expectation has no successor to roll back rather than a successor that
        is rolled back.
        """

    @abstractmethod
    def mutation_replay_for(
        self,
        idempotency_key: str,
        request_digest: str,
        *,
        principal_id: str,
        capability: str,
    ) -> EntityMutationReceipt | None:
        """The receipt this Principal's key is already bound to, or `None`.

        Takes the digest for the reason `RelationshipMemoryRepository.replay_for`
        does: a lookup on the key alone would answer a *conflicting* request
        with the original receipt, silently reporting a write that never
        happened as durable. A key bound to a different digest raises
        `EntityIdempotencyConflictError` here, exactly as `admit_mutation` does
        at the unique constraint.

        `capability` is part of the lookup because it is part of the constraint.
        One key spent on `entities.aliases.add` says nothing about the same key
        arriving on `entities.identifiers.bind`.
        """

    @abstractmethod
    def identifier_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[IdentifierState] | None = None,
        namespaces: frozenset[ExternalIdentifierNamespace] | None = None,
        after_identifier_id: str | None = None,
    ) -> EntityChildPage[ExternalIdentifier]:
        """One bounded page of an entity's external identifiers.

        Separate from `external_identifiers` rather than a parameter on it, and
        the difference is the default. That method is unbounded because
        resolution reads the collection whole to decide whether an identifier is
        conflicted, and a bound applied beneath it would let a conflict fall off
        the end of a page and read as a clean match. This one is bounded because
        it answers a person scrolling, and it *discloses* its bound.

        The keyset is `identifier_id`, which is unique and totally ordered, so a
        row written between two requests cannot shift a later page backwards and
        hide a binding -- which is exactly what an `OFFSET` does to a table that
        is still being written to. A cursor naming a record this Principal
        cannot read is refused rather than silently restarting the walk.
        """

    @abstractmethod
    def alias_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[AliasState] | None = None,
        alias_types: frozenset[AliasType] | None = None,
        after_alias_id: str | None = None,
    ) -> EntityChildPage[EntityAlias]:
        """One bounded page of an entity's recorded name forms.

        The terms `identifier_page` states, over the alias plane's own
        vocabulary.
        """

    # --- the directed-relationship write path (WP-RI-A-03) ------------------
    #
    # Six methods and two lookups, all of them beside `record_assignment` and
    # `record_relationship` rather than replacing them. The two older writers
    # take a fully-formed domain record and mint nothing; they are how the
    # resolver and the fixtures put a row in place, and they carry no
    # idempotency key, no version guard and no ledger row. The six below are the
    # *capability* path: they own the identifier, the version, the lifecycle and
    # the ledger, and they are the only writers on this plane a request reaches.

    @abstractmethod
    def assignment(self, principal_id: str, assignment_id: str) -> Assignment | None:
        """One assignment by identifier, within this Principal's partition.

        `None` for an absent row and for one belonging to another Principal,
        and the two are indistinguishable by construction: `principal_id` is
        part of the lookup key, so there is no branch here that could tell them
        apart even by accident.
        """

    @abstractmethod
    def relationship(self, principal_id: str, relationship_id: str) -> EntityRelationship | None:
        """One directed edge by identifier, on `assignment`'s terms."""

    @abstractmethod
    def assignments_page(
        self,
        principal_id: str,
        entity_id: str,
        *,
        active_only: bool,
        limit: int,
        after_assignment_id: str | None = None,
    ) -> list[Assignment]:
        """One bounded, keyset-continued page of an entity's assignments.

        Separate from `assignments` rather than a widening of it, and the
        separation is deliberate: that method defaults to *every* row because
        resolution and re-enrichment read the collection whole and a bound
        introduced beneath them would answer "no such assignment" for a recorded
        one. This one exists for `entities.assignments.list`, whose contract is
        the opposite -- bounded output, and a cursor that continues rather than
        an offset that shifts. Rows are ordered by `assignment_id` and
        `after_assignment_id` excludes every identifier at or before the one
        named, for the reason `relationships` gives for its own keyset.
        """

    @abstractmethod
    def directed_replay(
        self,
        capability: str,
        idempotency_key: str,
        payload_digest: str,
        *,
        principal_id: str,
    ) -> DirectedReceipt | None:
        """The receipt already issued for this key, or `None` if the key is unused.

        Raises `DuplicateDirectedFactError`'s sibling
        `RelationshipMemoryError`-style refusal -- concretely,
        `my_pa.domain.relationship.entity.DirectedWriteError` -- when the key is
        in use for a *different* request: same key, different digest is an
        idempotency conflict and never a silent second write.

        `capability` is part of the key because
        `entity_mutation_events` is unique on
        `(principal_id, capability, idempotency_key)`. A caller that reuses one
        key across `create` and `revise` is therefore making two writes and not
        one, which is the honest reading: they are different acts on different
        state.
        """

    @abstractmethod
    def create_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        """Admit one new assignment, refusing a duplicate active semantic key.

        Refuses with `DuplicateDirectedFactError` when an active assignment
        already exists for `(entity, type, scope, role, discipline,
        responsibility class)` folded case- and whitespace-insensitively --
        which is the partial unique index `an_active_assignment_is_recorded_once`
        stated in the application's terms, not a second rule: the index is what
        actually decides, and the pre-read exists only so the refusal is
        classified rather than escaping as a driver error.

        Refuses with `StaleDirectedVersionError` when the subject or the scope
        entity is not at the version the request says it read, and with
        `MergedEndpointError` when either has been merged away.
        """

    @abstractmethod
    def revise_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        """Append the descriptive change, refusing a stale expected version.

        One guarded `UPDATE` whose rowcount decides everything: a stale
        expectation writes no row, no ledger entry and no evidence link, and
        leaves the prior state exactly as it stood.
        """

    @abstractmethod
    def end_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        """Move one assignment to `ended`, on `revise_assignment`'s guard.

        The row is kept. `ended_at` records when it left service and `state`
        records that it did; nothing is deleted, on the rule section 10.11
        states and `IdentifierState` explains.
        """

    @abstractmethod
    def create_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        """Admit one new directed edge, refusing a duplicate active semantic key.

        The key is `(from, type, to, scope)`, so the *opposite* direction of the
        same pair is not a duplicate and is admitted -- which is what a directed
        model is for. No reciprocal edge is generated.
        """

    @abstractmethod
    def revise_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        """Append the effective-date and evidence change, on the same guard."""

    @abstractmethod
    def end_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        """Move one directed edge to `ended`, on `end_assignment`'s terms."""

    # --- governed identity correction (WP-RI-06) ----------------------------
    #
    # **These sixteen are declared with a default that raises rather than as
    # `@abstractmethod`, and the reason is the one `UnitOfWork.continuity_read`
    # and `UnitOfWork.worker_health` already state.** Identity correction is a
    # bounded operator-only surface reached by `entities.merge.preview` and
    # `entities.merge` alone. The older in-memory doubles implement the entity
    # plane a resolver and a context card need and nothing else; making these
    # abstract would make every one of them unconstructable in order to serve a
    # path none of them reaches.
    # The canonical PostgreSQL repository overrides every one of them, so the
    # production composition is total, and a double that does not implement one
    # fails loudly on the call rather than answering an empty result -- which is
    # the difference between "this store does not serve merge" and "this merge
    # found nothing to do".
    #
    # `principal_id` is the acting Principal on every one of them, on the terms
    # this port's preamble states.

    def assignments_scoped_by(
        self, principal_id: str, scope_entity_id: str, *, limit: int | None = None
    ) -> list[Assignment]:
        """Assignments whose *scope* names one entity.

        Separate from `assignments`, which reads the rows an entity *holds*. A
        merge has to find both: an assignment of somebody else scoped to a
        merged-away project is as materially affected as the project's own, and
        a preview that read only the first would move an identity out from under
        a row it never mentioned.
        """
        raise NotImplementedError

    def relationships_scoped_by(
        self, principal_id: str, scope_entity_id: str, *, limit: int | None = None
    ) -> list[EntityRelationship]:
        """Directed edges whose *scope* names one entity.

        `relationships` reads `from` and `to`; `scope_entity_id` is the third
        entity reference on the row and no existing read reaches it.
        """
        raise NotImplementedError

    def resolution_decisions_naming(self, principal_id: str, entity_ids: frozenset[str]) -> int:
        """How many resolution decisions name one of these entities.

        **A count, not the rows, and that is a disclosure decision rather than a
        convenience.** A merge preview reports what a merge would touch;
        `entity_resolution_decisions` carries a reason a person wrote about why
        one mention was or was not somebody, and the preview has no business
        rendering those. What the operator needs is the fact that decisions
        exist and that this merge leaves every one of them exactly as recorded.
        """
        raise NotImplementedError

    def fact_evidence_links_naming(self, principal_id: str, entity_ids: frozenset[str]) -> int:
        """How many evidence links name one of these entities directly.

        A count for `resolution_decisions_naming`'s reason. These links are the
        source-link family: they record which evidence supported which fact at
        the moment it was recorded, and a merge does not rewrite them.
        """
        raise NotImplementedError

    def serialize_identifier_entity_scopes(
        self, principal_id: str, entity_ids: frozenset[str]
    ) -> None:
        """Hold participant-wide locks against Entity-reference mutations.

        The compatibility name predates the wider protocol. PostgreSQL now uses
        this same transaction key for Entity, alias, identifier, assignment,
        relationship, observation, proposal, and Relationship Memory writers;
        the separate claim-key lock remains identifier-specific. In-memory
        repositories execute serially and need no implementation.
        """
        return None

    def serialize_identifier_claim_keys(
        self, principal_id: str, claims: frozenset[tuple[str, str]]
    ) -> None:
        """Hold transaction locks for every state of these normalized claims."""
        return None

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
    ) -> None:
        """Rewrite every reference this row makes to a merged-away entity.

        One method over five families rather than one per family, and the shape
        is what makes it correct rather than merely shorter. A directed edge can
        name a merged-away entity in `from`, in `to` and in `scope` at once, and
        the row's own CHECK forbids `from = to`: a per-column writer would need
        three statements against a row whose intermediate states the server
        refuses. This substitutes every reference in one `UPDATE`, so the row is
        never momentarily illegal.

        `from_entity_ids` is the whole merged-away set and not the single
        identifier the caller happened to walk in on, for the same reason.

        **The `WHERE` names the version and the references it expects to find.**
        A row somebody else moved or revised between the preview's read and this
        write matches nothing, and the method raises rather than reporting a
        rewrite it did not perform -- which is the concurrency rule this plane
        applies everywhere: no state-dependent write may silently
        last-write-wins.

        `expected_version` is the row's `version` for the four records that
        carry one, and an observation's `resolution_version`. The first four are
        advanced by one because their content changed; a rebinding does *not*
        advance an observation's resolution version, because moving a mention to
        the surviving identity is a consequence of a merge rather than a new
        decision about what the mention referred to.

        Admits `ALIAS`, `IDENTIFIER`, `ASSIGNMENT`, `RELATIONSHIP` and
        `OBSERVATION`. `ENTITY` is refused: an entity's own identity is changed
        by `redirect_entity`, and the other three families of
        `IdentityEffectFamily` name records this method does not own.
        """
        raise NotImplementedError

    def supersede_child_record(
        self,
        principal_id: str,
        *,
        family: IdentityEffectFamily,
        record_id: str,
        superseded_by_record_id: str | None,
        expected_version: int,
        at: datetime,
    ) -> None:
        """Take one child row out of service, optionally naming what replaced it.

        Two merge outcomes share one statement because they are one row change
        with and without a successor. A row the survivor already held an
        equivalent of is *coalesced*: it is superseded and
        `superseded_by_record_id` names the counterpart, so a later inversion can
        revive this row and know which row to stop treating as its replacement.
        A directed edge whose two ends became the same entity is *superseded with
        no successor*: it was folded into nothing, and the row's own
        `from <> to` CHECK is why it cannot simply be reparented.

        Nothing is deleted. Section 10.11's rule holds through a merge exactly as
        it holds everywhere else, and a merged-away entity keeps every row it
        ever held.

        `expected_version` guards the write on `reparent_entity_reference`'s
        terms and is advanced by one, because a row that left service changed.

        Admits `ALIAS`, `IDENTIFIER`, `ASSIGNMENT` and `RELATIONSHIP` -- the four
        families whose records carry a `state` and a successor column.
        `OBSERVATION` is refused: an observation is rebound, never superseded,
        because superseding it would change what a source said.
        """
        raise NotImplementedError

    def invalidate_proposal(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        reason: str,
        decided_by: str,
        decided_at: datetime,
    ) -> None:
        """Close one open proposal whose subject an identity correction changed.

        Separate from `decide_proposal`, which replaces a whole record a reviewer
        decided and has no column for `invalidated_reason`. This is not a review
        decision: nobody looked at the proposal and refused it, the identity it
        named stopped existing under that name. The reason is recorded because
        `EntityProposal` refuses an invalidated proposal that does not carry one.

        **The undecided states are part of the predicate**, on
        `decide_proposal`'s argument: a proposal a reviewer decided between the
        preview and the apply is not this merge's to close, and a rowcount of
        zero says so.

        That predicate was the `proposed` literal until `WP-RI-B-05` began
        writing `needs_review` for every kind a person has to look at, which
        made it refuse exactly the proposals a merge most often has to close.
        It reads `UNDECIDED_PROPOSAL_STATES` now -- the same tuple
        `EntityProposal.is_open` returns, which is what the planner selects on,
        so the plan and the statement cannot disagree about which proposals are
        open. `DEFERRED` stays outside it: a deferral is a decision, and this
        statement overwrites `decided_by`, so matching a deferred row would
        replace the deferring reviewer with the merging operator.
        """
        raise NotImplementedError

    def record_identity_preview(self, principal_id: str, preview: IdentityPreview) -> None:
        """Persist one merge preview as the binding an apply is checked against.

        Takes the whole record, so the fifteen-minute expiry, the bounded
        merged-away set and all three digests have been through
        `IdentityPreview.__post_init__` before a row exists.
        """
        raise NotImplementedError

    def identity_preview(self, principal_id: str, preview_id: str) -> IdentityPreview | None:
        """One preview in this Principal's partition, or `None`.

        Foreign and absent are one answer, on this port's standing rule. A
        preview names exact entity identifiers, and an error that distinguished
        the two would let a caller enumerate another Principal's identities by
        guessing preview identifiers.
        """
        raise NotImplementedError

    def consume_identity_preview(self, principal_id: str, preview_id: str, *, at: datetime) -> bool:
        """Claim one preview for exactly one operation, or answer `False`.

        A guarded `UPDATE` with `consumed_at IS NULL` in the predicate, so two
        applies racing on one preview settle at the database: one writes the
        stamp and proceeds, the other matches no row and is refused. The claim
        happens in the transaction that writes the operation, which is what makes
        "a consumed preview cannot produce a materially different second
        operation" a property of the schema rather than of call order.
        """
        raise NotImplementedError

    def record_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        """Open one identity operation before the work it records.

        Written first for two reasons that are both structural.
        `UNIQUE (principal_id, idempotency_key)` is what makes two concurrent
        applies under one key serialise here rather than each perform a whole
        merge and then discover the other; and the effect ledger's foreign key
        means no effect can be stored until this row exists.
        """
        raise NotImplementedError

    def complete_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        """Settle one open operation at its outcome.

        `state = 'in_progress'` is part of the predicate: an operation is settled
        once, and a second settlement would overwrite the moment and the receipt
        of the first.
        """
        raise NotImplementedError

    def identity_operation_for_key(
        self, principal_id: str, idempotency_key: str
    ) -> IdentityOperation | None:
        """The operation this Principal's key is already bound to, or `None`.

        Returns the record rather than a receipt, because the caller has to
        compare `request_digest` itself: the same key carrying the same digest is
        a retry and is answered with the first result, and the same key carrying
        a different digest is a caller reusing a key for a different merge and is
        refused. A lookup that decided that here would have to know what
        "materially the same request" means, which is the application's question.
        """
        raise NotImplementedError

    def record_identity_effects(
        self, principal_id: str, effects: tuple[IdentityEffect, ...]
    ) -> None:
        """Append one operation's whole effect ledger.

        The tuple rather than a row at a time, because the ledger is complete or
        it is not evidence: `UNIQUE (operation_id, sequence)` and the append-only
        trigger both assume the sequence arrives whole, and a writer that could
        append one effect later could append it out of order.
        """
        raise NotImplementedError

    def identity_effects(
        self, principal_id: str, identity_operation_id: str
    ) -> list[IdentityEffect]:
        """One operation's effects, in sequence order.

        Read back by an idempotent retry, which has to answer with the *prior*
        result rather than with a fresh analysis of a world the first attempt
        already changed.
        """
        raise NotImplementedError

    def identity_operation(
        self, principal_id: str, identity_operation_id: str
    ) -> IdentityOperation | None:
        """One identity operation in this Principal's partition, or ``None``."""
        raise NotImplementedError

    def split_for_source_operation(
        self, principal_id: str, source_identity_operation_id: str
    ) -> IdentityOperation | None:
        """The completed inverse already recorded for one merge, if any."""
        raise NotImplementedError

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        """Whether the canonical row still exactly equals a source effect's after state."""
        raise NotImplementedError

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        """Restore one source effect's exact before state under an after-state guard."""
        raise NotImplementedError


class PortError(Exception):
    """A failure an implementation of one of these ports may report.

    These exist because the boundary has to be closed in both directions. A use
    case may not import `infrastructure`, so it cannot catch a SQLAlchemy error,
    an `IsolationLevelError`, or `persistence.search`'s private classes; and an
    adapter may not import `application`, so it cannot raise the public error
    directly. The vocabulary therefore belongs here, where both sides can see
    it, and an adapter's job includes translating into it.

    Each carries nothing. The values that would be worth carrying — a statement,
    a bound parameter, a driver message — are exactly the ones `docs/specs`
    section 10 excludes from a public error, and the classification is the only
    thing the caller can act on.
    """


class UnknownScopeError(PortError):
    """The scope a request names does not exist.

    Distinct from "the search found nothing", which is an answer rather than a
    failure. Section 10 puts this under `not_found`.
    """


class EvidenceUnavailableError(PortError):
    """The backing store could not be read. Conditionally retryable."""


class RepositoryFailureError(PortError):
    """The read failed for a reason that is this system's fault.

    Separated from unavailability because telling a caller to retry a missing
    column would be a lie with a retry budget attached.
    """


class WriteRequestConflictError(PortError):
    """One server request identity was reused for materially different work."""


class ProposalAdmissionConflictError(PortError):
    """A concurrent producer admitted the same open Entity proposal first."""


class ProposalReviewScopeConflictError(PortError):
    """A proposal or indirect target changed while its participant lock waited."""


class ProposalEvidenceConflictError(PortError):
    """A proposal stopped being open while evidence append waited for its scope."""


@dataclass(frozen=True, slots=True)
class WriteRequestEvidence:
    """One content-free evidence identity preserved with a proposal receipt."""

    sequence: int
    role: str
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None


@dataclass(frozen=True, slots=True)
class WriteRequestResult:
    """The safe typed fields required to replay one logical write receipt.

    No request body or Relationship Memory statement can fit this record. Fixed
    columns preserve identifiers, closed state tokens, counts and digests
    without creating a generic second response store.
    """

    result_family: str
    result_id: str
    result_secondary_id: str | None = None
    result_version: int | None = None
    result_state: str | None = None
    result_subtype: str | None = None
    result_requirement: str | None = None
    result_disposition: str | None = None
    result_assertion_id: str | None = None
    result_classification: str | None = None
    result_method: str | None = None
    result_at: datetime | None = None
    result_digest: str | None = None
    result_count: int | None = None
    result_created: bool | None = None
    receipt_id: str | None = None
    audit_id: str | None = None
    evidence: tuple[WriteRequestEvidence, ...] = ()


class WriteRequestRepository(ABC):
    """Server-bound replay arbitration shared by proposals and Review."""

    @abstractmethod
    def reserve(
        self,
        principal_id: str,
        capability: str,
        request_id: str,
        request_digest: str,
    ) -> WriteRequestResult | None:
        """Reserve this request or return its completed original result."""

    @abstractmethod
    def complete(
        self,
        principal_id: str,
        capability: str,
        request_id: str,
        request_digest: str,
        result: WriteRequestResult,
    ) -> None:
        """Bind the reserved identity to its stable logical receipt."""


@dataclass(frozen=True, slots=True)
class Acceptance:
    """An accepted enrollment, and whether this call is what created it.

    `created` false means the idempotency key was already bound to this exact
    normalized request, so the correct answer is the one the first call got.
    A caller that audits acceptance separately from retry needs to tell them
    apart; one that does not may ignore it.
    """

    enrollment: Enrollment
    created: bool


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    """One stored extraction and the source state it is bound to.

    The provenance is mandatory rather than optional because `docs/specs`
    section 9.8 makes the source, object, and version bindings mandatory: a
    record returned without them would be derived text with no way back to the
    bytes it came from.
    """

    knowledge_id: str
    enrollment_id: str
    media_type: str | None
    text: str
    is_truncated: bool
    provenance: Provenance

    def __post_init__(self) -> None:
        validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """One page of matches and the disclosure that must accompany it.

    The two travel together because section 8.3 makes the envelope mandatory: a
    caller able to hold the matches without the coverage could report "nothing
    found" for a scope that was never indexed.
    """

    matches: tuple[SearchMatch, ...]
    disclosure: Disclosure


@dataclass(frozen=True, slots=True)
class CaptureAdmissionRequest:
    """Everything one admission needs, decided before the transaction opens.

    `capture_id` is `None` for `capture.create` and names an existing capture for
    `capture.revise`, which is the whole difference between the two: one starts a
    chain and the other appends to it.

    **Three of the five timestamps are supplied here and two are not.**
    `server_received_at` is when this process received the request,
    `accepted_at` is when the admission decided, and the store writes
    `recorded_at` from the server's own clock — three different clocks reading at
    three different moments, so the criterion that they stay distinct is a
    property of where they come from rather than of a caller remembering to pass
    three values. `client_created_at` and `occurred_at` are the caller's, and
    both are optional: a transport may supply no device clock and a note may be
    about no particular moment. Neither is defaulted from anything.

    `audit_id` names the audit event that has *already committed*, on the audit
    sink's own connection (`D-34`). The version stores the reference so that a
    stored capture can be tied back to the authorization that admitted it,
    without the audit's durability depending on this transaction.
    """

    capture_id: str | None
    content: CaptureContent
    idempotency_key: str
    request_id: str
    correlation_id: str
    principal_id: str
    audit_id: str
    classification: Classification
    processing_policy: ProcessingPolicy
    server_received_at: datetime
    accepted_at: datetime
    client_created_at: datetime | None = None
    occurred_at: datetime | None = None
    capture_kind: CaptureKind = CaptureKind.QUICK_NOTE
    context_source_object_id: str | None = None
    context_source_version_id: str | None = None
    #: How the submission reached this process, established by the transport and
    #: never stated by the caller (WP-10). It defaults to `LOCAL` because that is
    #: what every path that does not say otherwise is: the loopback gateway, MCP
    #: over stdio, and the CLI are all the composition root's own process
    #: principal. The remote ingress is the one caller that says otherwise, and
    #: it says so through `ApplicationService.invoke`'s own parameter — the same
    #: trust channel the acting `Principal` arrives on — rather than through any
    #: field of any command, payload, or envelope.
    #:
    #: **It is deliberately outside `payload_digest`.** The digest decides
    #: whether a replayed idempotency key carries the same request, and two
    #: submissions of the same note under the same key from the same Principal
    #: are the same request whether one arrived over loopback and the other over
    #: the ingress. Including the transport would turn a device retrying over a
    #: different route into a `409` conflict, which is exactly the failure
    #: `QC-AC-031` exists to prevent.
    transport: CaptureTransport = CaptureTransport.LOCAL

    @property
    def payload_digest(self) -> str:
        """Digest every material admission input without copying source text."""
        canonical = json.dumps(
            {
                "content_sha256": self.content.digest,
                "capture_kind": self.capture_kind.value,
                "context_source_object_id": self.context_source_object_id,
                "context_source_version_id": self.context_source_version_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def __post_init__(self) -> None:
        if not isinstance(self.capture_kind, CaptureKind):
            raise ValueError("an admission names one capture kind")
        if not isinstance(self.transport, CaptureTransport):
            raise ValueError("an admission names one transport")
        if (self.context_source_object_id is None) is not (self.context_source_version_id is None):
            raise ValueError("a launch context names both object and version")
        if self.context_source_object_id is not None:
            context_version_id = self.context_source_version_id
            if context_version_id is None:  # narrowed from the paired-field invariant above
                raise ValueError("a launch context names both object and version")
            validate_identifier(self.context_source_object_id, IdKind.SOURCE_OBJECT)
            validate_identifier(context_version_id, IdKind.VERSION)


@dataclass(frozen=True, slots=True)
class CaptureAdmission:
    """The receipt for an admitted capture, and whether this call created it.

    `created` false means the idempotency key was already bound to byte-identical
    content, so the correct answer is the receipt the first call got — the
    `QC-AC-031` replay. A key bound to different content is a
    `domain.capture.errors.CaptureConflictError` and never a receipt.
    """

    receipt: CaptureReceipt
    created: bool


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    """One capture as a listing sees it: identity, size, and where its chain got to.

    No content and no digest of a version the caller did not ask for. A listing
    that carried text would put every capture's content into one response, which
    is the opposite of what `capture.read` exists to bound.
    """

    capture_id: str
    owner_principal_id: str
    created_at: datetime
    version_count: int
    latest_version_id: str
    latest_version_number: int
    latest_recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.latest_version_id, IdKind.CAPTURE_VERSION)


@dataclass(frozen=True, slots=True)
class CaptureSearchRequest:
    """One `capture.search` request, bounded on construction.

    **No cursor**, and that is the same call `capture.list` makes: a bounded
    page whose truncation is disclosed, rather than a keyset cursor whose
    binding would have to carry a scope a capture does not have. `SearchCursor`
    binds to an enrollment identifier and a `kn_…`, and a capture plane has
    neither.

    `query` is a `SearchQuery`, so the text is normalized once, bounded once,
    and redacts itself in every rendering — the one sensitive string this plane
    carries.
    """

    query: SearchQuery
    limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.query, SearchQuery):
            raise ValueError("a capture search carries a normalized SearchQuery")
        if isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("a capture search page holds at least one capture")


@dataclass(frozen=True, slots=True)
class CaptureSearchMatch:
    """One capture version whose stored text matched.

    **No text and no snippet, and neither model has a field one could go in.**
    `QC-AC-041` keeps capture content out of the answers a caller sees most
    often, and a search result is one of those; the caller obtains the text
    through `capture.read`, under its own capability and its own audit event.
    `character_count` is the size of what matched, which is a count rather than
    the content.
    """

    capture_id: str
    version_id: str
    version_number: int
    character_count: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.version_number < 1:
            raise ValueError("version numbers start at one")
        if self.character_count < 1:
            raise ValueError("a stored capture version carries text")


@dataclass(frozen=True, slots=True)
class CaptureSearchOutcome:
    """One page of capture matches and the counts a disclosure is built from.

    The two counts are read in the page's own snapshot: `searchable_versions` is
    how many versions the search could have returned and `stored_versions` is
    how many exist. Their difference is what a caller is owed when a revised
    capture's earlier version did not match because it is no longer current —
    an absence with a reason, rather than an absence.
    """

    matches: tuple[CaptureSearchMatch, ...]
    searchable_versions: int
    stored_versions: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.searchable_versions < 0 or self.stored_versions < self.searchable_versions:
            raise ValueError("a scope cannot hold more versions than the store does")


class CaptureRepository(ABC):
    """The capture plane, as the five operations the capabilities need.

    **`reveal` is the fifth, and it is here rather than behind a port of its
    own.** It reads captures, versions, spans, proposals, review cases,
    decisions, assertions and receipts — every one of them a row keyed, directly
    or through a foreign key, to a capture this Principal owns. A second port
    would be a second object over the same partition with the same context
    translation, which is the speculative abstraction the module docstring above
    forbids; the honest cost is that this interface is now the widest of the
    five here, and that is stated rather than hidden.

    **No update and no delete, and their absence is the port's contribution to
    `QC-AC-010`.** A method that changed a stored version could not be added here
    without also defeating the `BEFORE UPDATE OR DELETE` trigger the schema
    carries, so the two halves fail independently: the port offers no such call,
    and the server refuses one made anyway.

    **Every operation takes the authenticated Principal as an input** (WP-03,
    `PKL-MYPA-D-WP03-001`, superseding `D-72`). `owner_principal_id` was stored
    on every version because `ADR-003` clause 6 required it and was read back
    without ever deciding anything; under the ratified campaign it decides
    everything: a read, a list, a search, and a revise each answer only within
    the caller's own partition. `D-72`'s argument — identity was process-scoped,
    so owner equality would strand captures across restarts — is dissolved
    rather than overruled: the local operator's identity is now durable
    (`domain.identity.binding`), so the same person holds the same partition
    across restarts. The parameter is `principal_id` as the knowledge schema's
    text vocabulary (`prn_…`) because that is what the rows carry; it is the
    composition root's authenticated Principal and never a request field
    (MU-AC-02).
    """

    @abstractmethod
    def admit(self, request: CaptureAdmissionRequest, *, principal_id: str) -> CaptureAdmission:
        """Store one capture version and everything that commits with it.

        The capture (for a new chain), the version, the receipt, the submission,
        and the queued processing job are written on this transaction's
        connection, so they commit together or not at all. The audit event the
        request's `audit_id` names is not among them: it committed first, on its
        own connection, and this stores the reference (`D-34`).

        Raises `domain.capture.errors.CaptureConflictError` when the idempotency
        key is already bound to different content *by this Principal*, and
        `UnknownScopeError` when `capture_id` names no capture this Principal
        owns — a capture another Principal owns earns the same refusal a
        nonexistent one does, so the answer maps nothing. The request's own
        `principal_id` must equal this parameter and is verified below rather
        than trusted.
        """

    @abstractmethod
    def version(
        self, capture_id: str, *, version_id: str | None = None, principal_id: str
    ) -> CaptureVersion | None:
        """One stored version of `capture_id`, or `None`.

        `version_id` omitted means the current one, which is the greatest version
        number the capture holds. Named, it means exactly that version — a
        superseded predecessor included, which is the "independently
        retrievable" half of `QC-AC-010`. A version of another capture is `None`,
        the same answer as one that does not exist — and a capture another
        Principal owns is `None` too, the third absence with the same face.
        """

    @abstractmethod
    def captures(self, *, limit: int, principal_id: str) -> tuple[CaptureSummary, ...]:
        """One bounded page of the Principal's own captures, newest first."""

    @abstractmethod
    def search(self, request: CaptureSearchRequest, *, principal_id: str) -> CaptureSearchOutcome:
        """One bounded page of capture versions whose stored text matched.

        Exact at word granularity always, and at character granularity where
        the server reports the query as one contiguous run of text: the plane is
        indexed with the `simple` text-search configuration, which neither stems
        nor drops stop words, because `QC-AC-050` asks for *exact* original text
        to be searchable. Which queries get the character-granularity pass is
        decided by PostgreSQL and not by this contract, so a caller's quoting or
        punctuation never removes a capture the index matched. The cost —
        `meetings` does not find `meeting` — is a limitation the caller is told
        about rather than a property it has to discover.

        Independent of enrichment: the index is over
        `capture_versions.content`, which is written by the save, so a capture
        whose processing failed is searchable on the same terms as one whose
        processing succeeded.
        """

    @abstractmethod
    def reveal(self, subject_id: str, *, principal_id: str) -> Reveal | None:
        """The evidence behind one subject, or `None` when there is no subject.

        `None` is the *one* absence with three causes, exactly as `version` has:
        the subject does not exist, the subject belongs to another Principal, or
        the identifier is well formed and names nothing. A caller that could tell
        those apart could enumerate another Principal's records by asking, so it
        cannot.

        A subject kind this build cannot traverse is **not** `None`. It is a
        `Reveal` in the `unavailable` state naming
        `EvidenceGap.SUBJECT_KIND_NOT_COVERED`, because "we do not cover this
        plane" is a fact about this build and says nothing about whether the
        subject exists.
        """

    def accepts_work_evidence_reference(self, reference: str, *, principal_id: str) -> bool:
        """Whether ``reference`` is usable as Work origin/closure evidence.

        Implementations must answer from metadata only: a Principal-owned Quick
        Capture (``cap_...``), or an accepted, non-superseded assertion
        (``asrt_...``).  The operation deliberately exposes neither evidence
        content nor whether a differently-owned reference exists.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ReviewDecisionRequest:
    """Everything one review transition needs inside a single transaction.

    **Two shapes of correction, and they never travel together.**
    `corrected_value` is the capture and GoodNotes shape and is unchanged: those
    subjects have one normalized value, so a correction to one is one bounded
    string. `correction_patch` is the typed-target shape: Entity and Relationship
    Memory proposals ask for mutations with *named arguments*, so a correction
    has to say which of them the reviewer changed, and it is routed and validated
    against that target command's schema by the plane that owns the subject before
    anything commits. Exactly one of the
    two accompanies `correct_and_accept` and neither accompanies anything else --
    which is what stops a widening of the Entity shape from quietly relaxing the
    bound the capture plane has always had on its one string.

    **`reason` explains a departure.** Section 13 states one for `reject`,
    `defer`, `mark_unresolved`, `escalate` and `invalidate`; it states none for
    `accept`, `correct_and_accept` or `reprocess`, and a reason attached to those
    would attribute a refusal to a decision nobody refused. So a reason is
    refused on the three and permitted on the five -- and *required* on
    `invalidate` and `escalate`, the two this package makes reachable and that
    therefore have no caller to regress. Requiring it on the other three would
    refuse every capture and GoodNotes reviewer that exists today, so the planes
    that can require it do: `EntityProposalReviewService` requires a reason on all
    five, because it is new and nothing calls it yet. That asymmetry is a
    fact about what already ships, and it is recorded here rather than hidden.
    """

    review_case_id: str
    expected_review_version: int
    disposition: Disposition
    principal_id: str
    correlation_id: str
    audit_id: str
    policy_version: str
    decided_at: datetime
    corrected_value: str | None = field(default=None, repr=False)
    correction_patch: CorrectionPatch | None = field(default=None, repr=False)
    reason: str | None = field(default=None, repr=False)

    #: The dispositions section 13 gives a reason. `accept`,
    #: `correct_and_accept` and `reprocess` are deliberately absent.
    _REASONED: ClassVar[frozenset[Disposition]] = frozenset(
        {
            Disposition.REJECT,
            Disposition.DEFER,
            Disposition.MARK_UNRESOLVED,
            Disposition.ESCALATE,
            Disposition.INVALIDATE,
        }
    )

    #: The dispositions that cannot be recorded without one.
    _REQUIRES_REASON: ClassVar[frozenset[Disposition]] = frozenset(
        {Disposition.ESCALATE, Disposition.INVALIDATE}
    )

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        validate_policy_version(self.policy_version)
        ensure_utc(self.decided_at)
        if type(self.expected_review_version) is not int or self.expected_review_version < 0:
            raise ValueError("the expected review version is a non-negative integer")
        if not isinstance(self.disposition, Disposition):
            raise ValueError("a review request names one disposition")
        self._check_correction()
        self._check_reason()

    def _check_correction(self) -> None:
        corrected = self.disposition is Disposition.CORRECT_AND_ACCEPT
        supplied = (self.corrected_value is not None) + (self.correction_patch is not None)
        if corrected is not (supplied == 1):
            raise ValueError("correct-and-accept carries exactly one correction, and only it")
        if self.correction_patch is not None and not isinstance(
            self.correction_patch, CorrectionPatch
        ):
            raise ValueError("a correction patch is a typed patch")
        if self.corrected_value is not None and (
            not self.corrected_value.strip()
            or len(self.corrected_value) > MAX_NORMALIZED_VALUE_CHARACTERS
        ):
            raise ValueError("a correction value is bounded and not blank")

    def _check_reason(self) -> None:
        if self.reason is None:
            if self.disposition in self._REQUIRES_REASON:
                raise ValueError("this disposition states the reason for it")
            return
        if self.disposition not in self._REASONED:
            raise ValueError("a reason explains a departure, and this disposition is not one")
        if not self.reason.strip() or len(self.reason) > REVIEW_REASON_LIMIT:
            raise ValueError("a reason is bounded and not blank")


class ReviewRepository(ABC):
    """Review cases, and the storage every decision on them needs.

    This said "the only port capable of canonical promotion", and for three of
    the four subject kinds on this surface it still is: a capture proposal, a
    GoodNotes region and a Relationship Memory candidate are each promoted inside
    `decide`, because everything their promotion does is SQL. An accepted Entity
    proposal is not. It is executed through the canonical Phase A mutation
    services, which live in the application layer, so the promotion `review.decide`
    performs for that subject reaches `EntitiesRepository` and never this port --
    which is what section 14's "do not duplicate mutation logic inside Review"
    asks for, and is why the sentence had to change rather than be repeated.
    """

    @abstractmethod
    def cases(
        self,
        *,
        limit: int,
        principal_id: str,
        subject_kind: ReviewSubjectKind | None = None,
        state: ProposalState | None = None,
        entity_id: str | None = None,
        after_opened_at: datetime | None = None,
        after_review_case_id: str | None = None,
    ) -> tuple[
        ReviewCase | GoodNotesReviewCase | RelationshipMemoryReviewCase | EntityProposalReviewCase,
        ...,
    ]:
        """One bounded page for this Principal, oldest case first.

        `principal_id` is the authenticated caller's identifier: the page is
        confined to that Principal's partition, and a case belonging to any
        other Principal is unreachable through this port (MU-AC-04).

        Four variants and one surface. A capture proposal, a GoodNotes region, a
        Relationship Memory candidate and an Entity proposal are decided by the
        same reviewer through the same capability; the union is what keeps that
        one surface from becoming four, and each variant carries only the subject
        facts its own decision needs.

        **The three filters narrow one page; they do not open a second listing.**
        `subject_kind` selects which planes are asked at all, `state` is the
        shared `ProposalState` every variant already presents, and `entity_id`
        selects the cases that are *about* one entity -- which only the two
        entity-bearing variants can answer, so a filtered page contains only
        those and a plane that cannot answer it contributes nothing rather than
        contributing everything. Every filter is applied where the rows are, so a
        narrowed page is still a full page of `limit` and not the remains of one.

        `after_opened_at` and `after_review_case_id` are one decoded keyset
        position and therefore either both present or both absent. The public
        opaque cursor never crosses this port; authority and filter binding are
        checked in the application layer before the position reaches storage.
        """

    @abstractmethod
    def decide(
        self, request: ReviewDecisionRequest, *, has_operator_authority: bool = False
    ) -> ReviewDecision | None:
        """Append a disposition; authority is authenticated server context."""

    # --- the Entity proposal plane's own case read and decision ledger -------
    #
    # Five methods rather than a `decide` branch, and the split is section 14's.
    # The other three subject kinds are decided *inside* this port, because
    # everything their decision does is SQL. An accepted Entity proposal is
    # executed through the canonical Phase A mutation services, which live in
    # the application layer and which infrastructure may not import -- so the
    # ordering of a decision belongs to `EntityProposalReviewService` and what
    # is left here is exactly the storage that service cannot reach any other
    # way. Non-abstract with a `NotImplementedError` default, on the terms
    # `EntitiesRepository` uses for the same reason: this port has
    # implementations outside the package.

    def entity_proposal_case(
        self, principal_id: str, review_case_id: str
    ) -> EntityProposalReviewCase | None:
        """The Entity proposal case `review_case_id` names, or `None`.

        `None` is also the answer for another Principal's case, which is what
        makes it indistinguishable from an identifier that names nothing.
        """
        raise NotImplementedError

    def entity_proposal_decisions(
        self, principal_id: str, review_case_id: str
    ) -> tuple[Disposition, ...]:
        """Every decision already appended to this case, in sequence order."""
        raise NotImplementedError

    def record_entity_proposal_decision(
        self, principal_id: str, decision: EntityProposalReviewDecision
    ) -> None:
        """Append one decision to an Entity proposal's case."""
        raise NotImplementedError

    def invalidate_entity_proposal(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        reason: str,
        decided_by: str,
        decided_at: datetime,
    ) -> bool:
        """Close an open proposal a reviewer invalidated, naming why, in one act.

        Distinct from `EntitiesRepository.invalidate_proposal`, which is the
        merge's writer and records no `decision_reason` because no reviewer
        decided anything. `False` when the proposal was decided in flight.
        """
        raise NotImplementedError

    def supersede_entity_proposal(
        self, principal_id: str, proposal_id: str, *, at: datetime
    ) -> bool:
        """Take an open proposal out of the open set, naming no successor yet.

        `False` when it was decided in flight: a stale reprocess creates nothing.
        Two statements rather than one because the successor pointer's foreign
        key cannot name a row that does not exist yet, and the successor cannot
        be inserted while the predecessor is still open-equivalent.
        """
        raise NotImplementedError

    def name_entity_proposal_successor(
        self, principal_id: str, proposal_id: str, *, successor_proposal_id: str
    ) -> None:
        """Point a superseded proposal at the successor that replaced it."""
        raise NotImplementedError


class SourceRepository(ABC):
    """The configured-source facts a capability needs, and no locator."""

    @abstractmethod
    def source(self, source_id: str) -> ConfiguredSource | None:
        """Return the configured source `source_id` names, or `None`.

        `None` rather than an exception because the caller's next act is to
        report `not_found`, and section 10 requires that answer to be
        indistinguishable from a denial.
        """

    @abstractmethod
    def source_of_object(self, source_object_id: str) -> str | None:
        """Return the `src_…` an object belongs to, or `None`.

        `sources.status` accepts an object as its subject, and the scope that
        request has to be authorized against is the object's source.
        """


class EnrollmentRepository(ABC):
    """Enrollments: the grants that authorize every read this system performs."""

    @abstractmethod
    def for_principal(self, principal_id: str) -> tuple[Enrollment, ...]:
        """Every enrollment held by `principal_id`.

        This is what the shared authorization path evaluates scope against, so
        the authorized set is a stored fact rather than something a caller
        supplies alongside its request.
        """

    @abstractmethod
    def accept(self, request: EnrollmentRequest) -> Acceptance:
        """Accept `request`, or return what its idempotency key is already bound to.

        Raises `domain.source.enrollment.EnrollmentConflictError` when the key
        is bound to a materially different normalized request.
        """

    @abstractmethod
    def record_scope(self, enrollment_id: str, source_object_ids: Iterable[str]) -> int:
        """Record the objects this enrollment authorizes, and return how many.

        Called once, inside the transaction that accepted the enrollment and
        only where that acceptance created it, so a retried request
        re-enumerates nothing. Idempotent by constraint rather than by
        convention: running the same enumeration twice records no second row.

        Raises `UnknownScopeError` when an identifier names no object of this
        enrollment's source, and `ValueError` for an empty set. Both roll the
        accepting transaction back, which is what makes "an enrollment that
        cannot be enumerated does not exist" structural: the alternative is an
        accepted grant with a zero denominator and queued work behind it.
        """


@dataclass(frozen=True, slots=True)
class Operation:
    """One unit of queued work: which grant it belongs to, and where it is.

    The enrollment travels with the state because `sources.status` has to
    authorize a request that names only an operation, and the scope such a
    request runs in is the enrollment's source. Returning both in one call keeps
    that from being two reads whose answers could disagree.
    """

    operation_id: str
    enrollment_id: str
    state: SourceStatusState

    def __post_init__(self) -> None:
        validate_identifier(self.operation_id, IdKind.OPERATION)
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)


class OperationQueue(ABC):
    """The application's job plane, as the two operations a capability needs."""

    @abstractmethod
    def enqueue(self, enrollment_id: str) -> str:
        """Queue the work an accepted enrollment implies and return its `op_…`."""

    @abstractmethod
    def operation(self, operation_id: str, *, principal_id: str) -> Operation | None:
        """One of `principal_id`'s operations, or `None` when there is no such job.

        The Principal is a parameter rather than something the operation is
        trusted to carry, so a job queued under one Principal cannot be read
        through another — the same shape `KnowledgeRepository.read` takes for the
        grant. It is required and has no default: a default would make an
        unvisited call site read the whole plane again.

        `None` covers both "no such job" and "not yours", deliberately. Telling
        them apart would let a caller confirm an operation identifier it has no
        authority over.
        """


class KnowledgeRepository(ABC):
    """Coverage, outcomes, search, and the one read of a stored record."""

    @abstractmethod
    def coverage(
        self,
        enrollment_id: str,
        *,
        observed_at: datetime,
        queued: int = 0,
    ) -> CoverageCounts:
        """Coverage of `enrollment_id` at `observed_at`.

        There is no `eligible` parameter. The denominator is the enumerated
        object set the enrollment stores, so it is read beside the numerators
        rather than stated by a caller that would have had to measure it
        somewhere else. `queued` stays the caller's, because work in flight is a
        fact about the job plane and not about the scope.
        """

    @abstractmethod
    def corpus(self, principal_id: str, *, observed_at: datetime) -> CorpusCoverage:
        """Coverage of everything `principal_id` holds, composed from stated facts.

        **A Principal and not a scope, and that is the whole shape of it.** Every
        other method here takes an enrollment, because coverage "is for a stated
        enrollment/snapshot and never inferred globally". This one takes the
        Principal whose enrollments those are, and returns each enrollment's own
        stated coverage unmerged beside the territory none of them reaches. No
        source and no enrollment crosses this boundary, so there is no argument a
        caller could widen: the implementation partitions on
        `enrollments.principal_id` at the query.

        Not a second coverage definition. The per-enrollment members are the
        values `coverage` above returns, so a corpus answer and a status answer
        cannot disagree about one enrollment.
        """

    @abstractmethod
    def scope_beyond_enrollment(self, principal_id: str, *, enrollment_id: str) -> bool:
        """Whether `principal_id` holds scope that `enrollment_id` does not cover.

        **A boolean and not a count, and that is the contract rather than a
        simplification.** Its one caller is `knowledge.search`, which is
        authorized for the enrollment it names and for nothing else; a number
        here would tell that caller the size of a scope its request never
        authorized, which is the side channel the aggregate-limitation rule
        permits only for the scope actually in question. "There is scope outside
        this answer" is what a caller can act on, and it is all of it.

        This does not widen what a search may read. It is asked *beside* the
        search, answers about the enrollment set the acting Principal already
        holds, and reaches no row of any enrollment the search does not name.
        """

    @abstractmethod
    def limitations(self, enrollment_id: str) -> tuple[AggregateLimitation, ...]:
        """The aggregate limitations recorded at the enrollment's latest snapshot.

        Separate from `coverage` because the two ask different questions of the
        same rows: coverage counts every outcome recorded so far, while a
        limitation belongs to the single enumeration pass that observed it.
        """

    @abstractmethod
    def outcome_for_object(
        self, *, enrollment_id: str, source_object_id: str
    ) -> ExtractionStatus | None:
        """What happened to one object under one enrollment, or `None` for nothing yet."""

    @abstractmethod
    def search(self, request: SearchRequest, *, now: datetime) -> SearchOutcome:
        """Search one enrollment's extracted text and disclose what was searched."""

    @abstractmethod
    def read(self, knowledge_id: str, *, enrollment_id: str) -> KnowledgeRecord | None:
        """Return one stored record inside `enrollment_id`'s grant, or `None`.

        The grant is a parameter rather than something the record is trusted to
        carry, so a record written under one enrollment cannot be read through
        another.
        """


class AuditSink(ABC):
    """Where a redacted audit event goes.

    One method, and it takes an `AuditEvent` rather than fields, because that
    type has no place a payload could be put. The redaction is therefore a
    property of what crosses this boundary rather than of how it is called.
    """

    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Persist one redacted audit event."""


class ContextRunRepository(ABC):
    """Insert-only persistence of a prepared-context disclosure.

    The record holds identifiers, digests, fingerprints, and policy versions.
    It does not hold the query, conversation_context, or excerpt text. There is
    no read method on this port yet: reconstruction of disclosed references is
    a later reader, and YAGNI keeps this to `record`.
    """

    @abstractmethod
    def record(self, run: ContextRunRecord) -> None:
        """Persist one context run and its items, filtered by `run.principal_id`."""


class PreferenceConflictError(Exception):
    """The same idempotency key was reused with a different preference payload."""


class ContextPreferenceRepository(ABC):
    """Append-only preference events plus the current projection fold.

    Events are never deleted. Reversal appends an opposing event and updates
    the projection in the same transaction. Every method is principal-partitioned.
    """

    @abstractmethod
    def record(
        self,
        *,
        principal_id: str,
        action: str,
        target_id: str,
        idempotency_key: str,
        alias: str | None,
        source_id: str | None,
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> ContextPreferenceAdmission:
        """Append one event, fold the projection, or replay/conflict on the key."""

    @abstractmethod
    def current_for(self, principal_id: str) -> tuple[ContextPreferenceCurrent, ...]:
        """The acting Principal's current projection. Empty when none are set."""


class GoodNotesProposalConflictError(Exception):
    """The same idempotency key was reused with a different proposal body."""


@dataclass(frozen=True, slots=True)
class GoodNotesProposalAdmission:
    """One semantic proposal write: the stored receipt, and whether it was created."""

    proposal: GoodNotesSemanticProposal
    created: bool


class GoodNotesSemanticRepository(ABC):
    """Principal-bound GoodNotes page-version work and semantic proposal receipts.

    Work is a read of immutable page-version identity. Proposals are insert-only
    receipts. Neither writes canonical notes, occurrences, revisions, or
    run-note-changes. `principal_id` is a parameter on every method and is the
    authenticated caller's partition, never a caller-supplied field.
    """

    @abstractmethod
    def page_work(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageWork | None:
        """The page version belonging to `run_id` for this Principal, or `None`."""

    @abstractmethod
    def page_raster(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageRaster | None:
        """The pinned visual raster for this run and page version, or `None`.

        The page version must appear in this run's positions. Bytes are the
        admitted PNG, never a path.
        """

    @abstractmethod
    def submit_proposal(
        self,
        *,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        content_sha256: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        idempotency_key: str,
        request_fingerprint: str,
        payload_sha256: str,
        payload: dict[str, object],
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> GoodNotesProposalAdmission:
        """Insert one receipt, or replay/conflict on the Principal's idempotency key."""


class SourceProviders(ABC):
    """The lookup from a configured source's identity to its read-only adapter.

    Not a registry of provider *kinds* and not a plugin framework: the adapters
    are already constructed by the composition root, and this answers only "which
    one serves this `src_…`". A use case cannot construct an adapter, which is
    what keeps the choice of implementation in the one place allowed to make it.
    """

    @abstractmethod
    def for_source(self, source_id: str) -> SourceProvider | None:
        """The provider serving `source_id`, or `None` when none is configured."""


@dataclass(frozen=True, slots=True)
class WorkerPlaneStatus:
    """Content-free operational state for one Principal's worker plane."""

    plane: str
    state: str
    backlog: int
    dead_lettered: int
    last_heartbeat_at: datetime | None


class WorkerHealthRepository(ABC):
    """Worker liveness and backlog for the authenticated Principal only."""

    @abstractmethod
    def for_principal(self, principal_id: str) -> tuple[WorkerPlaneStatus, ...]:
        """Return both worker planes without identifiers or queued content."""


class AuthoringConflictError(Exception):
    """The same idempotency key was reused with a different payload."""


@dataclass(frozen=True, slots=True)
class AuthoringReceipt:
    """What a prior user-directed continuity write produced for one key."""

    capability: str
    object_id: str
    payload_digest: str


class ContinuityAuthoringRepository(ABC):
    """Idempotent user-directed Project, Situation, and Task writes."""

    @abstractmethod
    def recall(self, principal_id: str, idempotency_key: str) -> AuthoringReceipt | None:
        """The prior receipt for this key, or None if the key is unused."""

    @abstractmethod
    def reserve(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        capability: str,
        payload_digest: str,
        object_id: str,
    ) -> bool:
        """Claim the key before any continuity row is written.

        Returns True when this transaction now owns `object_id` for the key.
        Returns False when the key already exists with the same digest.
        Raises AuthoringConflictError when the key is bound to different content.
        """

    @abstractmethod
    def author_project(
        self,
        *,
        principal_id: str,
        project_id: str,
        name: str,
        description: str | None,
    ) -> Project:
        """Create one Project under a key this transaction already reserved."""

    @abstractmethod
    def author_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        title: str,
        description: str | None,
    ) -> Situation:
        """Open one Situation under a key this transaction already reserved."""

    @abstractmethod
    def author_task(
        self,
        *,
        principal_id: str,
        task_id: str,
        title: str,
        origin_evidence_ref: str,
        project_id: str | None = None,
        situation_id: str | None = None,
        due_at: datetime | None = None,
    ) -> Task:
        """Create one accepted Task under a key this transaction already reserved."""


class UnitOfWork(ABC):
    """One transaction, and the repositories that run inside it.

    Leaving the block normally commits; leaving it by exception rolls back. That
    is the whole of the transaction contract, and it is what makes the enrollment
    rule of `module-boundaries.md` section 10 — enrollment, queued work, and
    audit committed together or not at all — a property of the structure rather
    than of the order a use case happens to call things in.
    """

    @abstractmethod
    def __enter__(self) -> UnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def providers(self) -> SourceProviders:
        """The source providers, inside this transaction.

        Inside, for the reason the four repositories are: a provider resolves an
        `obj_…` against `knowledge.source_objects`, so it has to read the same
        rows under the same snapshot as the coverage reported beside its result,
        and identifiers it issues have to roll back with the work that issued
        them. A provider holding its own connection while a use case holds a work
        connection is the pool cycle `bootstrap.gateway` derives, and it would
        form at exactly five concurrent requests.

        This is a *removal* of a constructor dependency rather than a new
        contract: `ApplicationService` was handed a `SourceProviders` at
        construction and no longer is. It satisfies
        `module-boundaries.md` section 5.2's rule that contracts exist only for a
        current use case because there are four current callers — `sources.list`,
        `sources.metadata`, `sources.fetch`, and the enumeration inside
        `sources.enroll`.
        """

    @property
    @abstractmethod
    def sources(self) -> SourceRepository:
        """Configured sources, inside this transaction."""

    @property
    @abstractmethod
    def enrollments(self) -> EnrollmentRepository:
        """Enrollments, inside this transaction."""

    @property
    @abstractmethod
    def operations(self) -> OperationQueue:
        """The job plane, inside this transaction."""

    @property
    @abstractmethod
    def knowledge(self) -> KnowledgeRepository:
        """Coverage and stored records, inside this transaction."""

    @property
    @abstractmethod
    def captures(self) -> CaptureRepository:
        """The capture plane, inside this transaction.

        Inside, and that is the whole of the durable-first guarantee: the capture,
        its version, its receipt, its submission, and its queued processing job
        are written on the connection this unit of work owns, so a failure
        anywhere in the request leaves none of them.
        """

    @property
    @abstractmethod
    def reviews(self) -> ReviewRepository:
        """The review and promotion plane, inside this transaction."""

    @property
    def write_requests(self) -> WriteRequestRepository:
        """Server-bound proposal and Review replay ledger in this transaction."""
        raise NotImplementedError

    @property
    @abstractmethod
    def situations(self) -> SituationRepository:
        """The Situation plane, inside this transaction.

        Reached by `continuity.situations` (WP-11). Inside for the reason every
        other repository is: the listing has to read the same rows under the same
        snapshot as the disclosure reported beside it.
        """

    @property
    @abstractmethod
    def projects(self) -> ProjectRepository:
        """The Project plane, inside this transaction. Reached by `continuity.projects`."""

    @property
    @abstractmethod
    def pulse(self) -> PulseRepository:
        """The Pulse plane, inside this transaction. Reached by `continuity.pulse`.

        The derivation runs four `SELECT`s and has to see one consistent picture
        of the Principal's accepted continuity; four reads across four
        transactions could rank a commitment that a fifth statement had already
        closed.
        """

    @property
    def continuity_read(self) -> ContinuityReadRepository:
        """Complete accepted continuity read model, inside this transaction.

        Older test doubles intentionally implement only the narrower WP-11 ports;
        the canonical PostgreSQL composition overrides this property. A caller
        must treat the absence as an unavailable optional projection, never as
        an empty authoritative result.
        """
        raise NotImplementedError

    @property
    def continuity_authoring(self) -> ContinuityAuthoringRepository:
        """User-directed continuity writes and their idempotency receipts.

        Optional on older test doubles. Production and the FAST world implement
        it; a caller that meets this default must treat authoring as unsupported.
        """
        raise NotImplementedError

    @property
    def worker_health(self) -> WorkerHealthRepository:
        """Content-free worker readiness inside this transaction.

        Kept optional for older test doubles. Production composition overrides
        it; a caller that meets this default must report health as unavailable,
        never healthy.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def managed_documents(self) -> ManagedDocumentRepository:
        """The managed-document rows, inside this transaction (WP-28).

        **WP-27 deliberately kept this off the unit of work and WP-28 puts it
        on, so the reversal is argued rather than quietly made.** WP-27's reason
        was reach: the managed write plane would sit on the same object every
        read capability already holds. What changed is that the plane now has a
        capability seat, so it is reached the same way every other plane is —
        through `ApplicationService.invoke`, behind `authorize`, inside the one
        transaction a request owns — and a handler that had to open a *second*
        transaction to write a document would put the rows outside the
        transaction whose rollback is what makes a failed request leave nothing.
        Reach is bounded by dispatch, not by which object holds the property:
        `_HANDLERS` gives each capability exactly one handler, and only the
        `documents.` handlers name this.

        **The byte store is still not here, and that is `AGENTS.md` section 4's
        actual line.** It separates source providers from managed-document
        *stores*; this is a repository over `knowledge.managed_documents` and its
        four sibling tables, which is PostgreSQL like every other repository
        above. The store — the thing that writes bytes to a filesystem — is
        composed once at the composition root and handed to `ApplicationService`,
        so a process with no configured managed root has no store, and the
        capabilities it serves are not published at all.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def tasks(self) -> TaskManagementRepository:
        """The task-management rows, inside this transaction (WP-TM-02/03).

        Placed here for the same reason `managed_documents` is: WP-TM-02 gave
        the plane a capability seat of its own for mutation, and WP-TM-03 gives
        it four more for reading, so it is reached the way every other plane
        with a seat is — through `ApplicationService.invoke`, behind
        `authorize`, inside the one transaction a request owns. A handler that
        opened a second transaction to read or write a task would put the rows
        outside the transaction whose rollback is what makes a failed request
        leave nothing.

        `TaskManagementRepository` is the one ABC for both directions: WP-TM-02
        defined the locking write-side methods on it, and WP-TM-03 adds the
        four non-locking read methods alongside them, rather than splitting a
        read-only ABC off. A `list_tasks` or `search` call has no single row to
        lock in the first place — each answers with a page, not a row a
        subsequent write in the same request will touch — so the distinction
        that matters is per-method, not per-object.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management rows, inside this transaction (WP-TM-05).

        Placed here for the same reason `tasks` is: WP-TM-05 gives the plane
        capability seats for read and write, so it is reached through
        `ApplicationService.invoke`, behind `authorize`, inside the one
        transaction a request owns.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def entities(self) -> EntitiesRepository:
        """The generalized entity rows, inside this transaction (WP-RI-02).

        Placed here for the same reason every other plane with capability seats
        is: WP-RI-02 gives the relationship-intelligence plane read and write
        seats, so it is reached through `ApplicationService.invoke`, behind
        `authorize`, inside the one transaction a request owns.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """

    @property
    def identity_history(self) -> object:
        """The optional Principal-scoped identity-history read projection.

        Kept optional for narrow test doubles. The application handler narrows
        this object to its one-method ``IdentityHistoryQuery`` protocol before
        use; the canonical PostgreSQL composition supplies that implementation.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def context_runs(self) -> ContextRunRepository:
        """Insert-only context-run metadata, inside this transaction.

        Written after packing, in the same unit of work as `context.prepare`, so
        a handler failure rolls the disclosure record back with the request.
        The port has no update or delete: rollback of the capability is revoke
        (AC-KC-037), not a row mutation. Every write is principal-partitioned.
        """

    @property
    @abstractmethod
    def context_preferences(self) -> ContextPreferenceRepository:
        """Append-only retrieval preferences, inside this transaction.

        Written by `context.feedback` and read by `context.prepare`. Events are
        never deleted; the current projection is folded in the same transaction.
        `principal_id` is a parameter on every method and is the authenticated
        caller's partition, never a caller-supplied field.
        """

    @property
    @abstractmethod
    def goodnotes_semantics(self) -> GoodNotesSemanticRepository:
        """Immutable GoodNotes page-version work and semantic proposal receipts.

        Written by `goodnotes.propose` and read by `goodnotes.work` and
        `goodnotes.content`. Proposals are insert-only. `principal_id` is a
        parameter on every method and is the authenticated caller's partition,
        never a caller-supplied field.
        """

    def intelligence_for(self, principal_id: str) -> object:
        """Intelligence Artifact store for the authenticated Principal.

        Optional on older test doubles. Production and the FAST world implement
        it. `principal_id` is the authenticated partition, never a payload field.
        """
        raise NotImplementedError

    @property
    def relationship_memory(self) -> RelationshipMemoryRepository:
        """The Relationship Memory rows, inside this transaction.

        Non-abstract with a refusal rather than `@abstractmethod`, the shape
        `continuity_read` and `worker_health` already use: the narrow test
        doubles in `tests/schema` and `tests/concurrency` implement only the
        ports their subject needs, and making this abstract would break them for
        a plane they never reach. The canonical PostgreSQL composition overrides
        it; a build that has not composed the plane refuses here rather than
        answering with something that is not the plane.

        `principal_id` remains a parameter on every method of the port and is
        the authenticated caller's partition, never a caller-supplied field.
        """
        raise NotImplementedError

    @property
    def relationship_memory_proposals(self) -> RelationshipMemoryProposalRepository:
        """The producer's one insert on the memory plane, inside this transaction.

        A property of its own beside `relationship_memory` rather than a method
        on it, and the separation is what operator §12 rests on: the object
        `relationship_memory.propose` is handed cannot reach
        `relationship_memories`, so "a producer must not create active memory
        directly" is a fact about the port rather than a branch a later writer
        might add.

        Non-abstract with a refusal, exactly as `relationship_memory` above is
        and for the same reason: the narrow doubles in `tests/schema` and
        `tests/concurrency` implement only the ports their subject needs.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def audit(self) -> AuditSink:
        """The audit sink, inside this transaction.

        Inside, because an operator-only command whose audit did not commit must
        not have committed either.
        """


# --- WP-06 R5 continuity ports ---------------------------------------------
#
# These ports take explicit descriptive arguments and return domain objects,
# rather than accepting the `application.commands` continuity commands directly.
# The reason is the dependency direction `contracts` sits under: a port may
# reference `domain` and `contracts` and nothing outer, so importing an
# application command here would invert the layering `test_dependency_direction`
# enforces. This is the same shape `RelationshipRepository` and `ReviewRepository`
# already take — the application service unpacks its command and calls the port
# with plain arguments, and the port answers in domain terms.
#
# `principal_id` is a parameter on every method, and it is the authenticated
# caller's partition, not a caller-supplied field: the concrete repository
# stamps every write with it and filters every read by it, so a continuity
# record belonging to another Principal is unreachable through these ports
# (WP-06 acceptance criteria 1, 3, and 4). `PulseRepository.generate_pulse`
# additionally reads only accepted state (criterion 2), which the migration
# pins with `pulse_reads_only_accepted_records`.


class SituationRepository(ABC):
    """Situations: open, close, read one, and list within a Principal's partition."""

    @abstractmethod
    def open_situation(
        self,
        *,
        principal_id: str,
        title: str,
        description: str | None,
        object_refs: tuple[str, ...],
    ) -> Situation:
        """Open one Situation for `principal_id`, issuing its identifier."""

    @abstractmethod
    def close_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        outcome: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> Situation:
        """Close one Situation the Principal owns, recording its outcome and evidence.

        Refuses when `situation_id` names no Situation in this Principal's
        partition — a Situation belonging to any other Principal is unreachable.
        Closing never deletes the objects the Situation referenced.

        **`evidence_kind` and `evidence_ref` are required (WP-11)** and are
        appended as a `closed` row in `continuity_lifecycle_events` in the same
        transaction as the state change. An outcome sentence with nothing under
        it is a status field changing with no trace, which is what this pair
        exists to refuse; a blank reference raises rather than closing.
        """

    @abstractmethod
    def get_situation(self, principal_id: str, situation_id: str) -> Situation | None:
        """Return the Situation the Principal owns, or `None`.

        `None` for one that names nothing in this partition, indistinguishable
        from one that names a Situation owned by another Principal.
        """

    @abstractmethod
    def list_situations(
        self, principal_id: str, state_filter: SituationState | None = None
    ) -> tuple[Situation, ...]:
        """One page of this Principal's Situations, newest first."""


class FrameRepository(ABC):
    """Frames: enter one within a Situation, and read a Situation's frames."""

    @abstractmethod
    def enter_frame(
        self,
        *,
        principal_id: str,
        situation_id: str,
        label: str,
        evidence_refs: tuple[str, ...],
        alternatives: tuple[str, ...],
        obligations: tuple[str, ...],
        uncertainty: str | None,
        next_authority: str | None,
    ) -> Frame:
        """Enter one Frame in a Situation the Principal owns.

        Refuses when the Situation is not in this Principal's partition, so a
        Frame can never be attached across the boundary.
        """

    @abstractmethod
    def get_frames(self, principal_id: str, situation_id: str) -> tuple[Frame, ...]:
        """Every Frame of a Situation the Principal owns, newest first."""


class TraceRepository(ABC):
    """Traces: record one derived reconstruction and read it back."""

    @abstractmethod
    def record_trace(
        self,
        *,
        principal_id: str,
        object_id: str,
        object_type: str,
        time_range_start: datetime | None,
        time_range_end: datetime | None,
    ) -> Trace:
        """Record one Trace for `principal_id`. A Trace is a projection, not evidence."""

    @abstractmethod
    def get_trace(self, principal_id: str, trace_id: str) -> Trace | None:
        """Return the Trace the Principal owns, or `None`."""


class ProjectRepository(ABC):
    """Projects: create, read one, list, and link a Situation into one."""

    @abstractmethod
    def add_project(
        self,
        *,
        principal_id: str,
        name: str,
        description: str | None,
        participants: tuple[str, ...],
    ) -> Project:
        """Create one Project for `principal_id`, issuing its identifier."""

    @abstractmethod
    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        """Return the Project the Principal owns, or `None`."""

    @abstractmethod
    def list_projects(
        self, principal_id: str, state_filter: ProjectState | None = None
    ) -> tuple[Project, ...]:
        """One page of this Principal's Projects, newest first."""

    @abstractmethod
    def link_situation(
        self,
        *,
        principal_id: str,
        project_id: str,
        situation_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        """Bind a Situation into a Project, both owned by this Principal.

        Refuses when either the Project or the Situation is not in this
        Principal's partition. Idempotent per (project, situation).
        """


class RelationshipEventRepository(ABC):
    """Relationship-timeline events, with acceptance gating what Today/Pulse read."""

    @abstractmethod
    def record_event(
        self,
        *,
        principal_id: str,
        person_id: str,
        event_type: RelationshipEventType,
        occurred_at: datetime,
        context: str | None,
        accepted: bool,
        source_ref: str | None,
    ) -> RelationshipEvent:
        """Record one event on a Person's timeline for `principal_id`.

        `accepted` defaults to a proposed event elsewhere; recorded as given
        here. A proposed event is never read as an accepted timeline fact.
        """

    @abstractmethod
    def list_events(self, principal_id: str, person_id: str) -> tuple[RelationshipEvent, ...]:
        """Every event on a Person's timeline the Principal owns, newest first.

        Includes proposed and accepted events, clearly distinguished by the
        `accepted` flag, for the relationship briefing.
        """

    @abstractmethod
    def list_accepted_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        """Only the accepted events across this Principal's relationships.

        This is the accepted-timeline read Today and the briefing use: an event
        that has not passed a human disposition never appears here.
        """


class PulseRepository(ABC):
    """Pulse: derived attention recommendations, generated only from accepted state."""

    @abstractmethod
    def generate_pulse(self, principal_id: str) -> tuple[PulseItem, ...]:
        """This Principal's active Pulse items, highest priority first.

        Returns only items with `accepted_only` true — the structural encoding
        of "Today/Pulse read only accepted records" (WP-06 criterion 2), which
        the schema also pins with the CHECK `pulse_reads_only_accepted_records`.
        Dismissed items are excluded.
        """

    @abstractmethod
    def dismiss_pulse_item(self, principal_id: str, pulse_id: str) -> None:
        """Dismiss one Pulse item the Principal owns.

        Refuses when `pulse_id` names no item in this Principal's partition.
        """

    @abstractmethod
    def derive_pulse(self, principal_id: str, now: datetime) -> tuple[PulseItem, ...]:
        """Derive this Principal's Pulse from accepted continuity, at `now`.

        **A read, and only a read.** It selects the Principal's accepted
        commitments, tasks, decisions and framed obligations, hands them to
        `domain.situation.pulse_derivation.derive_pulse`, and returns what comes
        back. It writes no row, promotes no state, and accepts no review — an
        implementation that did any of those would be the automatic consequential
        promotion `QC-AC-020` forbids, arriving through the one path nobody
        audits because it looks like a listing.

        The acceptance filter is a `WHERE evidence_state = 'accepted'` predicate
        on every one of those selects, alongside the `principal_id` predicate, so
        a proposal is excluded by the query rather than by the caller.
        """


# --- Read model for the complete continuity workspace -----------------------


class ContinuityReadRepository(ABC):
    """Principal-scoped accepted read model used by canonical continuity surfaces."""

    @abstractmethod
    def frames(self, principal_id: str) -> tuple[Frame, ...]:
        """All frames owned by the Principal, newest first."""

    @abstractmethod
    def traces(self, principal_id: str) -> tuple[Trace, ...]:
        """All source-linked traces owned by the Principal, newest first."""

    @abstractmethod
    def commitments(self, principal_id: str) -> tuple[Commitment, ...]:
        """Accepted commitments owned by the Principal."""

    @abstractmethod
    def decisions(self, principal_id: str) -> tuple[Decision, ...]:
        """Accepted decisions owned by the Principal."""

    @abstractmethod
    def tasks(self, principal_id: str) -> tuple[Task, ...]:
        """Accepted tasks owned by the Principal."""

    @abstractmethod
    def relationship_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        """Accepted relationship events owned by the Principal."""


# --- WP-11: the continuity objects, their lifecycle, and their associations ---


class ContinuityRepository(ABC):
    """Commitments, Decisions, Tasks, and the append-only record of their lives.

    One port rather than three, because the three objects share exactly one
    lifecycle, one acceptance gate and one association record, and three ports
    over one table family would be three copies of the same four methods. The
    object kind travels as a closed enum, so a caller cannot name a table.

    **Every method takes `principal_id` and it is the authenticated caller's
    partition.** A commitment, decision or task belonging to another Principal is
    answered exactly as an absent one: `None` from a getter, absence from a
    listing, `UnknownScopeError` from a mutation.

    **Proposing and accepting are different methods, and only one of them can
    produce continuity.** `propose_*` writes `evidence_state = 'proposed'` and
    has no parameter that could make it write anything else. `accept` is the only
    path to `'accepted'`, and it requires the identifier of a review decision in
    the caller's own partition whose disposition accepted something — so a
    derivation, an import, or a model cannot promote its own output by calling
    the method it already has.
    """

    @abstractmethod
    def propose_commitment(
        self,
        *,
        principal_id: str,
        counterparty_person_id: str,
        direction: CommitmentDirection,
        summary: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Commitment:
        """Record one proposed social obligation, and its `opened` lifecycle row."""

    @abstractmethod
    def propose_decision(
        self,
        *,
        principal_id: str,
        question: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        awaiting_authority_ref: str | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Decision:
        """Record one proposed decision, and its `opened` lifecycle row."""

    @abstractmethod
    def propose_task(
        self,
        *,
        principal_id: str,
        title: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Task:
        """Record one proposed task, and its `opened` lifecycle row."""

    @abstractmethod
    def accept(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        review_decision_id: str,
    ) -> None:
        """Promote one proposal to accepted continuity, on a review decision.

        `review_decision_id` must name a `capture_review_decisions` row in this
        Principal's partition whose disposition accepted something. Anything else
        — a decision that rejected, a decision belonging to another Principal, a
        well-formed identifier naming nothing — raises `UnknownScopeError` and
        the object stays a proposal.
        """

    @abstractmethod
    def close(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
        occurred_at: datetime,
    ) -> None:
        """Close one object and append the closure evidence, in one transaction.

        The state change and the `closed` lifecycle row are written on the same
        connection inside the caller's transaction, so a closure whose evidence
        did not commit did not close anything. `evidence_ref` must be non-blank;
        the schema refuses the row otherwise.
        """

    @abstractmethod
    def associate(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        project_id: str | None,
        situation_id: str | None,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        """Bind one object to a Project and/or a Situation, citing the evidence.

        Both ends must be in this Principal's partition. The association is
        recorded twice on purpose: as the object's own `project_id`/`situation_id`
        so a read is one row, and as an `associated` lifecycle row carrying the
        evidence that justified it, so *why* it belongs is reconstructable from
        the append-only record rather than inferred from a column.
        """

    @abstractmethod
    def association_evidence(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        """Every `associated` row for one object, oldest first.

        This is the answer to "why does this belong to that project": the rows
        name the evidence, and an object with no association evidence returns
        nothing rather than a guess.
        """

    @abstractmethod
    def lifecycle_events(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        """Every lifecycle row for one object, oldest first."""

    @abstractmethod
    def get_commitment(self, principal_id: str, commitment_id: str) -> Commitment | None:
        """One commitment in this Principal's partition, or `None`."""

    @abstractmethod
    def get_decision(self, principal_id: str, decision_id: str) -> Decision | None:
        """One decision in this Principal's partition, or `None`."""

    @abstractmethod
    def get_task(self, principal_id: str, task_id: str) -> Task | None:
        """One task in this Principal's partition, or `None`."""

    @abstractmethod
    def list_commitments(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Commitment, ...]:
        """This Principal's commitments, optionally only the accepted ones."""

    @abstractmethod
    def list_decisions(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Decision, ...]:
        """This Principal's decisions, optionally only the accepted ones."""

    @abstractmethod
    def list_tasks(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Task, ...]:
        """This Principal's tasks, optionally only the accepted ones."""


# --- WP-27 the managed-document plane ---------------------------------------
#
# One port. WP-27 kept it off `UnitOfWork` and WP-28 put it on, once the plane
# acquired a capability seat and began being reached through
# `ApplicationService.invoke` inside the request's own transaction; the property's
# own docstring argues the reversal. The *byte store* is still not on the unit of
# work and is composed at the composition root, which is the separation
# `AGENTS.md` section 4 actually draws — source providers and managed-document
# stores are separate capabilities.
#
# The operator paths (`verify`, `back_up`, `restore_from_backup`) still take the
# repository directly from a connection `apps/cli/managed_documents.py` opens,
# because they are not requests and have no authorization behind them.
#
# `principal_id` is a parameter on every method and it is the authenticated
# caller's partition, never a caller-supplied field: the concrete repository
# stamps every write with it and filters every read by it.


@dataclass(frozen=True, slots=True)
class ManagedWriteRequest:
    """One request to write a managed document version, already normalized.

    **The version identifier is minted by the caller and travels in the request**,
    which is unusual here and is the ordering the transactional boundary requires:
    the bytes have to be on the device under some identifier before the row that
    names them is inserted, so the identifier is issued first and the same value
    reaches both. `application.managed_documents` is the only thing that mints
    one, and the store derives a location from it rather than being told one.

    **No bytes.** The digest and the size are what the row records; the bytes went
    to the byte store, which is the only component that holds them. A request
    value carrying the content would put a document body on an interface that is
    logged, compared, and rendered in test failures.

    `document_id` absent means "create", present means "revise" — a difference in
    the value rather than in a flag, so no request can be ambiguous about which it
    is. `expected_version_number` is required exactly when revising, because a
    revision without one is a blind write.
    """

    document_id: str | None
    expected_version_number: int | None
    version_id: str
    title: str
    media_type: str
    content_sha256: str
    byte_size: int
    idempotency_key: str
    correlation_id: str
    principal_id: str
    server_received_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.document_id is not None:
            validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        if (self.document_id is None) is not (self.expected_version_number is None):
            raise ValueError(
                "a managed revision names the version it expects; a creation names none"
            )
        if self.expected_version_number is not None and self.expected_version_number < 1:
            raise ValueError("an expected managed version number starts at one")
        validate_managed_title(self.title)
        validate_managed_media_type(self.media_type)
        if not self.idempotency_key:
            raise ValueError("a managed write carries an idempotency key")
        if self.byte_size < 1:
            raise ValueError("a managed write carries bytes")
        ensure_utc(self.server_received_at)

    @property
    def payload_digest(self) -> str:
        """What makes a replay decidable without a second copy of the content.

        Every field a caller supplied that could differ between two requests
        carrying one key, and none this layer added: the minted version
        identifier and the correlation identifier are excluded because they
        differ on every attempt by construction, and including either would make
        every retry a conflict.
        """
        payload = {
            "document_id": self.document_id,
            "expected_version_number": self.expected_version_number,
            "title": self.title,
            "media_type": self.media_type,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryWriteRequest:
    """One request to write a relationship memory, already normalized.

    **The identifiers are minted by the caller and travel in the request**, the
    ordering `ManagedWriteRequest` uses and for a related reason: the aggregate
    and its first version are mutually dependent, so both identifiers have to
    exist before either row is inserted, and the same values reach the
    submission row that records the write.

    `memory_id` absent means "create", present means "revise", "archive" or
    "restore" — which one is `operation`. `expected_version` is required for
    every operation except `create`, because a state-dependent write without one
    is a blind write.

    `statement` is `repr=False` for the reason it is on the version: a request
    value is logged, compared and rendered in test failures, and this is the
    field carrying what the user wrote about another person.
    """

    operation: MemoryOperation
    memory_id: str | None
    memory_version_id: str
    expected_version: int | None
    principal_id: str
    subject_entity_id: str | None
    memory_kind: MemoryKind | None
    statement: str | None = field(repr=False)
    statement_sha256: str | None
    structured_value: dict[str, Any] | None = field(repr=False)
    authority: MemoryAuthority
    classification: Classification
    created_by_actor: MemoryActorClass
    context_links: tuple[Mapping[str, str], ...]
    pinned: bool | None
    observed_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    correction_reason: str | None = field(repr=False)
    idempotency_key: str
    correlation_id: str
    server_received_at: datetime
    proposal_id: str | None = None
    review_case_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.memory_id is not None:
            validate_identifier(self.memory_id, IdKind.RELATIONSHIP_MEMORY)
        creating = self.operation is MemoryOperation.CREATE
        if creating is (self.memory_id is not None):
            raise ValueError("a memory creation names no memory; every other operation does")
        if creating is (self.expected_version is not None):
            raise ValueError("a state-dependent memory write names the version it expects")
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("an expected memory version starts at one")
        writes_content = self.operation in (MemoryOperation.CREATE, MemoryOperation.REVISE)
        if writes_content:
            if self.statement is None or self.statement_sha256 is None:
                raise ValueError("a memory create or revise carries a statement")
            if self.memory_kind is None:
                raise ValueError("a memory create or revise carries a kind")
        if creating and self.subject_entity_id is None:
            raise ValueError("a memory creation names its subject")
        if self.subject_entity_id is not None:
            validate_identifier(self.subject_entity_id, IdKind.ENTITY)
        if not self.idempotency_key:
            raise ValueError("a memory write carries an idempotency key")
        ensure_utc(self.server_received_at)

    @property
    def payload_digest(self) -> str:
        """What makes a replay decidable without a second copy of the content.

        Every field a caller supplied that could differ between two requests
        carrying one key, and none this layer added: the minted identifiers, the
        correlation identifier and the receipt time are excluded because they
        differ on every attempt by construction, and including any of them would
        make every retry a conflict.

        The *digest* of the statement stands in for the statement, so a payload
        digest can be computed and stored without the note itself passing through
        a second value that is compared and logged.
        """
        payload = {
            "operation": self.operation.value,
            "memory_id": self.memory_id,
            "expected_version": self.expected_version,
            "subject_entity_id": self.subject_entity_id,
            "memory_kind": None if self.memory_kind is None else self.memory_kind.value,
            "statement_sha256": self.statement_sha256,
            "structured_value": self.structured_value,
            "authority": self.authority.value,
            "classification": self.classification.value,
            "context_links": [dict(sorted(link.items())) for link in self.context_links],
            "pinned": self.pinned,
            "observed_at": None if self.observed_at is None else self.observed_at.isoformat(),
            "effective_from": (
                None if self.effective_from is None else self.effective_from.isoformat()
            ),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "correction_reason": self.correction_reason,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryListingFacts:
    """What one memory's *current version* contributes to a listing row.

    **One record rather than three mappings, and the difference is not
    presentational.** `statement`, `authority` and `classification` are read off
    a single joined row and are only true together. Three parallel mappings
    keyed by `memory_id` can disagree in ways nothing in the type would notice —
    one populated, one missing the key, one carrying an earlier version's value —
    and every way they can disagree is a false claim about provenance: a
    listing that printed `source_backed_assertion` beside a statement the user
    typed would attribute the user's own note to a source, and one that printed
    `user_authored_private_note` beside a promoted assertion would hide that a
    reviewer, not the user, put it there. Binding the three into one record makes
    that drift unrepresentable: they are written once, from one row, or not at
    all.

    They are carried *here* rather than on `RelationshipMemory` because they are
    not properties of the memory. The aggregate is the stable identity and the
    pointer to its current version; authority and classification belong to the
    version, and a revision may change either. A listing states the current
    version's values, and this record is exactly that scope.

    `statement` is `repr=False` for the reason it is on `RelationshipMemoryVersion`
    and on `MemoryWriteRequest`: a value that reaches a log line or a
    test-failure diff must not be the note the user wrote about another person.
    `authority` and `classification` say *how* the memory came to be and how
    widely it may travel; they disclose nothing the user wrote and stay in the
    repr, which is what makes a page's repr useful for diagnosing a disclosure
    bug without printing the notes.
    """

    statement: str = field(repr=False)
    authority: MemoryAuthority
    classification: Classification


@dataclass(frozen=True, slots=True)
class MemoryPage:
    """One bounded page of memories, and whether the bound bit.

    `listing_facts` holds exactly one record per memory in `memories` — no more,
    because a withheld memory must leave no trace a caller could read, and no
    fewer, because a row whose authority the renderer could not state would be
    disclosed as though it carried no provenance at all. That is checked here
    rather than trusted, since the two collections are built in one loop by each
    implementation and a `continue` in the wrong place is the exact defect the
    check catches.
    """

    memories: tuple[RelationshipMemory, ...]
    listing_facts: Mapping[str, MemoryListingFacts]
    is_truncated: bool = False
    withheld_by_policy: int = 0

    def __post_init__(self) -> None:
        if set(self.listing_facts) != {memory.memory_id for memory in self.memories}:
            raise ValueError("a memory page carries one facts record per disclosed memory")


@dataclass(frozen=True, slots=True)
class MemoryDetail:
    """One memory with its current version, as `relationship_memory.get` answers."""

    memory: RelationshipMemory
    current_version: RelationshipMemoryVersion
    context_links: tuple[MemoryContextLink, ...] = ()
    evidence_count: int = 0
    canonical_entity_id: str | None = None


class RelationshipMemoryRepository(ABC):
    """The Relationship Memory plane, inside one transaction.

    Every method is principal-scoped. A memory another Principal owns answers
    exactly what a memory that does not exist answers, so a refusal cannot be
    used to learn that an identifier names something.
    """

    @abstractmethod
    def admit(self, request: MemoryWriteRequest) -> MemoryAdmission:
        """Admit one memory write, or return the receipt its key is bound to.

        Raises `MemoryConflictError` when the key is bound to a materially
        different request, `StaleMemoryVersionError` when the named expected
        version is no longer current, `MergedSubjectError` when the subject has
        been merged away, and `UnknownScopeError` when the request names a
        memory, subject or context target this Principal does not hold.
        """

    @abstractmethod
    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> MemoryReceipt | None:
        """The receipt this Principal's key is already bound to, or `None`.

        Takes the digest for the reason `ManagedDocumentRepository.replay_for`
        does: a lookup on the key alone would answer a *conflicting* request with
        the original receipt, silently reporting a write that never happened as
        durable. A key bound to a different digest raises `MemoryConflictError`
        here, exactly as `admit` does at the unique constraint.
        """

    @abstractmethod
    def detail(self, memory_id: str, *, principal_id: str) -> MemoryDetail | None:
        """One memory this Principal owns, with its current version, or `None`."""

    @abstractmethod
    def page_for_entity(
        self,
        subject_entity_id: str,
        *,
        principal_id: str,
        limit: int,
        kinds: frozenset[MemoryKind] | None = None,
        lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
        context_entity_id: str | None = None,
        as_of: datetime | None = None,
        after_memory_id: str | None = None,
        include_restricted: bool = False,
    ) -> MemoryPage:
        """One bounded page of one entity's memories, newest first."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        principal_id: str,
        limit: int,
        subject_entity_id: str | None = None,
        kinds: frozenset[MemoryKind] | None = None,
        after_memory_id: str | None = None,
    ) -> MemoryPage:
        """One bounded page of lexical matches over eligible current memories.

        Never returns a `restricted_local` memory and never reports one in any
        count, so a caller cannot learn that one exists by probing terms.
        """

    @abstractmethod
    def history(
        self, memory_id: str, *, principal_id: str, limit: int, after_version_id: str | None = None
    ) -> tuple[tuple[RelationshipMemoryVersion, ...], bool]:
        """Every stored version of one memory this Principal owns, oldest first."""

    @abstractmethod
    def summaries_for_context(
        self, subject_entity_id: str, *, principal_id: str, limit: int
    ) -> tuple[tuple[MemoryDetail, ...], bool, int]:
        """The bounded memory summary `entities.context` carries.

        Returns the summaries, whether more exist than the card can hold, and how
        many were withheld by classification policy. Three values rather than a
        list, because "there are none", "there are more" and "some are withheld"
        are different facts and a card that could not tell them apart would let a
        reader infer absence from a policy decision.
        """

    def subject_entity_ids(
        self, entity_ids: frozenset[str], *, principal_id: str
    ) -> frozenset[str]:
        """Which of these entities a memory or a memory proposal is about (WP-RI-06).

        **Entity identifiers out, never memory identifiers, and never a count per
        entity.** Restricted memory must not be distinguishable through a merge
        preview, and a count would be exactly that channel: an operator who could
        see "three memories" for one identity and "none" for another would learn
        what this plane holds without being permitted to read it. Existence per
        *entity* is the only thing a merge needs, because the whole Relationship
        Memory family is refused as unsupported when any row names a merged-away
        entity -- `WP-RI-08` owns origin-subject redistribution and `WP-RI-06`'s
        effect ledger has no family that could record what a merge did to a
        memory.

        **On this port and not on `EntitiesRepository`**, although the question is
        asked by the entity plane and the answer is entity identifiers. Every
        statement over a memory table belongs to the two modules
        `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`
        enumerates, and a read of `relationship_memories` issued from the entity
        repository would make a third -- which is exactly the reach that guard
        exists to make visible rather than convenient.

        Declared with a default that raises rather than as `@abstractmethod`, on
        the terms `UnitOfWork.continuity_read` states: the older doubles implement
        the plane the memory capabilities need and this is reached by one
        operator-only path none of them serves.
        """
        raise NotImplementedError

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        """Content-blind equality check for a memory binding effect."""
        raise NotImplementedError

    def plan_identity_merge(
        self,
        principal_id: str,
        merged_entity_ids: frozenset[str],
        survivor_entity_id: str,
    ) -> tuple[IdentityEffectDraft, ...]:
        """Plan content-blind RM binding moves while retaining immutable origins."""
        raise NotImplementedError

    def apply_identity_effect(self, principal_id: str, effect: IdentityEffectDraft) -> None:
        """Apply one planned RM binding move under its exact before-state guard."""
        raise NotImplementedError

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        """Restore one opaque memory binding to its immutable origin subject."""
        raise NotImplementedError


class RelationshipMemoryProposalRepository(ABC):
    """The producer's whole persistence surface on the memory plane: one insert.

    **One method, and the count is the contract.** Operator §16 requires that a
    source, rule or model worker never accept its own proposal, and this is where
    that is structural rather than asserted: the port a producer's use case is
    handed declares no `decide`, no `accept`, no `promote` and no memory write, so
    a producer holding it has nothing to call. `RelationshipMemoryRepository` is a
    different port reached by a different service, and promotion lives in the
    Review path.

    **Declared here rather than beside its use case, and that is a change from
    the wave that wrote it.** `RelationshipMemoryProposalService` shipped against
    an identical `Protocol` in `application/relationship_memory.py`, on the
    `GoodNotesCorrectionRepository` precedent — a port whose only implementor and
    only caller are one use case is a port the use case may own. That reasoning
    held while nothing exposed it on the unit of work. It stops holding here:
    `ApplicationService` reaches this through `UnitOfWork`, and a port a
    dispatcher reaches has to be declared where `UnitOfWork` can name it, because
    `contracts` may not import `application`. The application module now imports
    this name so the service's own argument about it stays readable next to the
    service.
    """

    @abstractmethod
    def record_proposal(
        self,
        proposal: RelationshipMemoryProposal,
        evidence: tuple[MemoryProposalEvidence, ...],
    ) -> tuple[RelationshipMemoryProposal, int, bool]:
        """Insert one candidate and the exact records it rests on, atomically.

        Takes the whole domain records rather than their fields, so what reaches
        storage has been through `RelationshipMemoryProposal.__post_init__` and
        `MemoryProposalEvidence.__post_init__` — which is what refuses a candidate
        naming an accepted memory, a model proposal with no model, or a
        classification below its kind's floor. Returns the stored proposal,
        complete evidence count, and whether this call created it.
        """


@dataclass(frozen=True, slots=True)
class ManagedAdmission:
    """The outcome of one managed write: the receipt, and whether it is new."""

    receipt: ManagedDocumentReceipt
    created: bool


class ManagedDocumentRepository(ABC):
    """The managed-document plane, inside one transaction.

    Every method is principal-scoped. A document another Principal owns answers
    exactly what a document that does not exist answers, so a refusal cannot be
    used to learn that an identifier names something.
    """

    @abstractmethod
    def admit(self, request: ManagedWriteRequest) -> ManagedAdmission:
        """Admit one managed write, or return the receipt its key is bound to.

        Raises `ManagedDocumentConflictError` when the key is bound to a
        materially different request, `StaleExpectedVersionError` when the named
        expected version is no longer the head, and `UnknownScopeError` when the
        request names no document this Principal owns.
        """

    @abstractmethod
    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> ManagedDocumentReceipt | None:
        """The receipt this Principal's key is already bound to, or `None`.

        Read before bytes are written, so an ordinary replay stores no second
        copy of them. It is an optimisation and never the decision: `admit` still
        relies on the unique constraint, so two concurrent writers that both read
        `None` still produce one version.

        **It takes the digest, and that is not an optimisation.** A lookup on the
        key alone would answer a *conflicting* request — the same key carrying a
        different document — with the original receipt, silently reporting a
        write that never happened as durable. So a key bound to a different
        digest raises `ManagedDocumentConflictError` here, exactly as `admit`
        does when it meets the same case at the unique constraint.
        """

    @abstractmethod
    def version(
        self, document_id: str, *, version_id: str | None = None, principal_id: str
    ) -> ManagedDocumentVersion | None:
        """One stored version of a document this Principal owns, or `None`.

        `version_id` omitted returns the head, which is the greatest version
        number the document holds — read from the rows rather than from a pointer
        column that could disagree with them.
        """

    @abstractmethod
    def versions(
        self, document_id: str, *, principal_id: str
    ) -> tuple[ManagedDocumentVersion, ...]:
        """Every stored version of one document this Principal owns, oldest first."""

    @abstractmethod
    def documents(
        self, *, limit: int, principal_id: str, include_archived: bool = False
    ) -> tuple[ManagedDocument, ...]:
        """One bounded page of this Principal's documents, newest first."""

    @abstractmethod
    def state(self, document_id: str, *, principal_id: str) -> DocumentState | None:
        """Whether a document this Principal owns is active or archived, or `None`."""

    @abstractmethod
    def transition(
        self,
        document_id: str,
        *,
        transition: LifecycleTransition,
        principal_id: str,
        correlation_id: str,
    ) -> bool:
        """Append one lifecycle row, and report whether it changed anything.

        `False` means the document is already in the state the transition would
        produce, and no row is appended — archiving an archived document is a
        no-op rather than a second event. Raises `UnknownScopeError` when the
        identifier names no document this Principal owns.
        """

    @abstractmethod
    def restore_version(self, version: ManagedDocumentVersion, *, principal_id: str) -> None:
        """Insert one version exactly as a backup recorded it.

        The restore path, and the only writer that supplies its own timestamps
        and version numbers. It refuses a version whose owner is not the
        Principal being restored, so a tampered backup cannot move a document
        between partitions.
        """

    @abstractmethod
    def known_version_identifiers(self) -> frozenset[str]:
        """Every managed version identifier the database holds, across Principals.

        **The one unpartitioned read on this plane, and it is unpartitioned on
        purpose.** Its whole subject is the reverse direction — bytes in the store
        that no row claims — and a partitioned answer would report every other
        Principal's objects as orphans, which is how a reclamation deletes live
        data. It returns opaque identifiers and nothing else: no title, no digest,
        no owner, no content. Operator use only, from the reconciliation path.
        """


class ManagedByteStore(ABC):
    """Durable storage for the bytes of managed document versions.

    **No method takes a path, and that absence is the port's whole security
    property.** Every operation names an opaque `mdver_…` or nothing at all; where
    the bytes actually live is derived by the implementation from that identifier.
    A port with a location parameter would put the choice of location on the
    caller, and the caller is where a traversal enters.

    Separate from `SourceProvider` rather than an extension of it, because
    `AGENTS.md` section 4 makes source providers and managed-document stores
    separate capabilities: the source port has no write method and must not gain
    one, and this port has no read of any source.
    """

    @abstractmethod
    def put(self, version_id: str, content: bytes) -> None:
        """Store `content` as the bytes of `version_id`, durably, exactly once.

        Returns only once the bytes and the name that reaches them are on the
        device. A second call for the same identifier raises: bytes are written
        once, and overwriting is the operation this plane does not have.
        """

    @abstractmethod
    def read(self, version_id: str) -> bytes:
        """Return the stored bytes of `version_id`, or raise."""

    @abstractmethod
    def has(self, version_id: str) -> bool:
        """Whether `version_id`'s bytes are present as a plain readable file."""

    @abstractmethod
    def stored_version_ids(self) -> tuple[str, ...]:
        """Every version identifier this store currently holds bytes for."""

    @abstractmethod
    def unreadable_entries(self) -> tuple[str, ...]:
        """Entries in the store that are not well-formed managed version objects."""

    @abstractmethod
    def put_manifest(self, content: bytes) -> None:
        """Store the backup manifest at this store's one fixed artifact location."""

    @abstractmethod
    def read_manifest(self) -> bytes:
        """Return the backup manifest this store holds."""


# --- WP-TM-02: canonical Task mutation, receipts, idempotency, concurrency --
#
# Deliberately **not** a method added to the existing `UnitOfWork` at the time
# this section was written, and deliberately not `ContinuityRepository`.
# `ContinuityRepository` is the WP-11 two-state `Task`'s port, reached by the
# capability dispatcher `ApplicationService.invoke` already serves. Wiring the
# richer `domain.task.task.Task` into that same dispatcher and its shared
# transaction was explicitly deferred past WP-TM-02 — WP-TM-01's own deferral
# note names "wiring the new domain into ... the application-service layer"
# as such — so adding a property to `UnitOfWork` in WP-TM-02 would have reached
# past what that package did and would have forced every existing fake that
# implements `UnitOfWork` to grow a method it had no use for yet.
#
# `TaskManagementUnitOfWork` is therefore its own transaction boundary, over its
# own repository, following the identical shape `UnitOfWork` already
# establishes: a context manager that commits on success and rolls back on
# exception, handing out one repository bound to the connection it opened.
#
# **WP-TM-03 is the wiring that comment deferred, and only the read half of
# it.** This package gives `Capability.TASKS_*` a dispatch seat in
# `ApplicationService.invoke`, which means the read handlers now run inside
# the one shared transaction every other capability's handler already runs
# in — the same argument `managed_documents` recorded for its own reversal of
# WP-27's separation. `UnitOfWork.tasks` below reaches this same
# `TaskManagementRepository`, unchanged in shape; `TaskManagementUnitOfWork`
# is left in place rather than deleted, because WP-TM-02's own mutation
# service (`application.tasks.TaskManagementService`) still opens it directly
# and is not itself reached from `invoke` yet — wiring *mutation* through the
# shared dispatcher remains WP-TM-04's job, not this one's.


class TaskManagementRepository(ABC):
    """`knowledge.tasks` and `knowledge.task_history`, inside one transaction.

    Every method takes `principal_id` and it is the authenticated caller's
    partition, exactly as `ContinuityRepository` states for the two-state
    model: a task belonging to another Principal is answered as an absent one.

    **`get_for_update` is the read every mutation attempt runs first.** Reading
    the row inside the same transaction that will conditionally write it, under
    a row lock the implementation is asked to hold for the rest of the
    transaction, is what keeps the optimistic-concurrency comparison honest
    against a second writer racing between the read and the write — the
    isolation this port asks of its implementation, stated once here rather
    than left to be assumed true of whichever adapter is composed in.
    """

    @abstractmethod
    def get_for_update(self, principal_id: str, task_id: str) -> TaskAggregate | None:
        """One task in this Principal's partition, row-locked for this transaction, or `None`."""

    @abstractmethod
    def insert_task(self, task: TaskAggregate) -> None:
        """Insert one newly created task row."""

    @abstractmethod
    def update_task(self, task: TaskAggregate) -> None:
        """Overwrite the mutable columns of an existing task row with `task`'s values."""

    @abstractmethod
    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        """The one prior mutation receipt recorded under this key, or `None`.

        `task_history_idempotency_key_is_unique_per_principal` is what makes
        this a lookup rather than a search: at most one row can ever match a
        given `(principal_id, idempotency_key)` pair.
        """

    @abstractmethod
    def insert_history(self, entry: TaskHistoryEntry) -> None:
        """Append one mutation receipt. Never updated, never deleted."""

    def find_bulk_by_preview_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        """A prior preview under this Principal/key, if any."""
        raise NotImplementedError

    def find_bulk_by_confirm_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        """A prior confirmation under this Principal/key, across all operations."""
        raise NotImplementedError

    def get_bulk_for_update(
        self, principal_id: str, bulk_operation_id: str
    ) -> TaskBulkOperation | None:
        """One Principal-owned bulk row, locked through the transaction."""
        raise NotImplementedError

    def insert_bulk(self, operation: TaskBulkOperation) -> None:
        """Persist one content-free preview ledger row."""
        raise NotImplementedError

    def confirm_bulk(self, operation: TaskBulkOperation) -> None:
        """Persist the terminal receipt fields for a confirmed operation."""
        raise NotImplementedError

    # --- WP-TM-03: the read plane -------------------------------------------
    #
    # The four methods below answer `tasks.read`/`list`/`search`/`history` and
    # are deliberately **not** locking. `get_for_update` above exists because a
    # mutation attempt has to compare against, and then overwrite, the exact
    # row it locked; none of these four ever writes anything back, so there is
    # nothing for a lock to protect and taking one would only hold other
    # writers behind a request that was only ever going to look.

    @abstractmethod
    def get(self, principal_id: str, task_id: str) -> TaskAggregate | None:
        """One task in this Principal's partition, unlocked, or `None`.

        The read `ReadTask` (`tasks.read`) runs. A task belonging to another
        Principal is answered exactly as an absent one — `principal_id` is
        part of the lookup key, not a filter applied after the fact, so there
        is no code path in which this method can observe that a differently
        owned row exists at all.
        """

    @abstractmethod
    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        after: str | None = None,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        work_now: datetime | None = None,
        limit: int,
    ) -> tuple[TaskAggregate, ...]:
        """One bounded page of this Principal's own tasks, newest created first.

        `lifecycle_state` and `priority`, when given, are exact matches — a
        structured filter, not the lexical one `search` performs. Archived
        tasks are excluded unless `archive_mode` is `only`, for the
        same reason `ListManagedDocuments` excludes archived documents: a
        caller who wants a withdrawn task back has to ask for it by name.
        """

    @abstractmethod
    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        work_now: datetime | None = None,
    ) -> tuple[TaskAggregate, ...]:
        """One bounded page of this Principal's own tasks whose title matches `query`.

        A case-insensitive substring match against `title`, the one free-text
        field `domain.task.task.Task` carries — `ILIKE`, executed by
        PostgreSQL, and never a vector or embedding search, which stays behind
        an abstraction and a benchmark gate under `AGENTS.md` section 4 rather
        than becoming an MCV prerequisite.
        """

    @abstractmethod
    def list_history(
        self, principal_id: str, task_id: str, limit: int, *, after: str | None = None
    ) -> tuple[TaskHistoryEntry, ...]:
        """One bounded page of one task's append-only mutation record, oldest first.

        Ordered the opposite of `list_tasks`, on purpose: a history answers how
        a task got here, and the useful order for that is the one events
        actually happened in. Scoped by `principal_id` in the same lookup-key
        sense `get` is — a history entry for a task belonging to another
        Principal is unreachable, not merely filtered out.
        """

    @abstractmethod
    def latest_applied_terminal_history(
        self, principal_id: str, task_id: str
    ) -> TaskHistoryEntry | None:
        """Latest applied terminal lifecycle receipt for a Principal-owned Task."""

    def get_follow_up_for_commitment(
        self, principal_id: str, commitment_id: str
    ) -> TaskAggregate | None:
        """The deterministic follow-up Task for one Principal-owned Commitment, if present."""
        raise NotImplementedError


class TaskManagementUnitOfWork(ABC):
    """One transaction over the task-management tables, and the repository inside it.

    The identical shape `UnitOfWork` establishes, held as a separate port for
    the reason given in the section comment above this class.
    """

    @abstractmethod
    def __enter__(self) -> TaskManagementUnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def tasks(self) -> TaskManagementRepository:
        """The task-management repository, inside this transaction."""


# --- WP-TM-05: Commitment/Waiting-On/Follow-Up -----------------------------
#
# `CommitmentManagementRepository`/`CommitmentManagementUnitOfWork` mirror
# `TaskManagementRepository`/`TaskManagementUnitOfWork` method-for-method,
# over `knowledge.commitments`/`knowledge.commitment_history` instead of
# `knowledge.tasks`/`knowledge.task_history`. There is no `WaitingOn`
# repository here and there will not be one: "what am I waiting on" is a
# derived read the application layer assembles from `list_commitments` and
# `TaskManagementRepository.list_tasks`/`get`, per the operator-approved
# scope's explicit refusal of a separate WaitingOn store.


@dataclass(frozen=True, slots=True)
class CounterpartyOption:
    """A verified canonical Person identity paired with its display label."""

    person_id: str
    display_name: str

    def __post_init__(self) -> None:
        validate_identifier(self.person_id, IdKind.PERSON)
        if not self.display_name.strip():
            raise ValueError("a counterparty display name is not blank")


class CommitmentManagementRepository(ABC):
    """`knowledge.commitments` and `knowledge.commitment_history`, inside one transaction.

    Every method takes `principal_id` and it is the authenticated caller's
    partition, exactly as `TaskManagementRepository` states for the task
    plane: a commitment belonging to another Principal is answered as an
    absent one.
    """

    @abstractmethod
    def get_for_update(self, principal_id: str, commitment_id: str) -> CommitmentAggregate | None:
        """One commitment in this Principal's partition, row-locked for this transaction, or `None`.

        `None` when it is absent from this Principal's partition, exactly as
        `TaskManagementRepository.get_for_update` treats an absent task.
        """

    @abstractmethod
    def get(self, principal_id: str, commitment_id: str) -> CommitmentAggregate | None:
        """One commitment in this Principal's partition, unlocked, or `None`."""

    def counterparty(self, principal_id: str, person_id: str) -> CounterpartyOption | None:
        """One current canonical Person label in this Principal's partition.

        The display name is mutable presentation metadata; callers retain and
        submit ``person_id`` as the stable identity. ``None`` deliberately
        covers absent, superseded, and another Principal's Person alike.
        """
        return None

    def list_counterparties(
        self, principal_id: str, *, limit: int
    ) -> tuple[CounterpartyOption, ...]:
        """A bounded alphabetical picker projection of current canonical People.

        This is presentation support for the existing Commitment capability,
        not a new identity write path. Implementations must filter by the
        authenticated Principal before ordering or limiting.
        """
        return ()

    @abstractmethod
    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        evidence_state: ContinuityEvidenceState | None = None,
        work_view: CommitmentWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        after: str | None = None,
        limit: int,
    ) -> tuple[CommitmentAggregate, ...]:
        """One bounded page of this Principal's own commitments, newest created first.

        `direction`, `state`, and `evidence_state`, when given, are exact matches — the same
        structured-filter shape `TaskManagementRepository.list_tasks` gives
        `lifecycle_state`/`priority`.
        """

    @abstractmethod
    def insert_commitment(self, commitment: CommitmentAggregate) -> None:
        """Insert one newly created commitment row."""

    @abstractmethod
    def update_commitment(self, commitment: CommitmentAggregate) -> None:
        """Overwrite the mutable columns of an existing commitment row with `commitment`'s values.

        The identical shape `TaskManagementRepository.update_task` gives.
        """

    @abstractmethod
    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        """The one prior mutation receipt recorded under this key, or `None`."""

    @abstractmethod
    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        """Append one mutation receipt. Never updated, never deleted."""

    @abstractmethod
    def list_history(
        self, principal_id: str, commitment_id: str, limit: int, *, after: str | None = None
    ) -> tuple[CommitmentHistoryEntry, ...]:
        """One bounded page of one commitment's append-only mutation record, oldest first."""

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        work_view: CommitmentWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
    ) -> tuple[CommitmentAggregate, ...]:
        """One bounded lexical page over summaries, optionally after an opaque row ID."""
        raise NotImplementedError


class CommitmentManagementUnitOfWork(ABC):
    """One transaction over the commitment-management tables, and the repository inside it.

    The identical shape `TaskManagementUnitOfWork` establishes.
    """

    @abstractmethod
    def __enter__(self) -> CommitmentManagementUnitOfWork:
        """Begin the transaction and return the unit of work it belongs to."""

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit when the block succeeded, roll back when it did not."""

    @property
    @abstractmethod
    def commitments(self) -> CommitmentManagementRepository:
        """The commitment-management repository, inside this transaction."""
