"""The Knowledge Assertion plane, in SQL (KLP-WP-03).

One repository over the frozen WP-02 tables (R6 section 11). Every statement
reaches the partition through `persistence.principal_scope`, so a foreign
assertion, evidence row or submission answers exactly what an absent one does.

**Remote withholding is SQL, before LIMIT** (R6 section 5.2). A remote read --
`transport is REMOTE_CLIENT or capability_grants is not None`, decided by the
caller -- appends `NOT withheld_remote(a)` to the statement that selects the
page, so a withheld assertion cannot reach a row, a truncation flag or a cursor,
and a remote page of N is N permitted rows whenever N permitted rows exist.
`withheld_remote(a)` is computed dynamically on every read, for every lifecycle:

* the assertion's stored class, or its predecessor's, is `restricted_local`;
* any linked evidence row (any role) is `restricted_local`;
* any external row of the same Principal, `external_object_id` and
  `origin_system` (joined through the source profile, every profile and scope)
  is `restricted_local` (KLP-R6V-005);
* any version of a cited Capture or Relationship Memory is `restricted_local`
  (the rank-max over insert-only version rows, R6 simplification S-3);
* a linked external row is unavailable (`permission_lost`, `deleted`) or has
  `availability_revalidation_pending`;
* a cited Capture root is archived (its current lifecycle).

The only rank is `knowledge.knowledge_classification_rank(text)` (R6 11.2): no
`GREATEST`/`MAX` over classification text appears here. Every term is either
stored-monotonic or a max over insert-only rows, so a withheld row never
becomes visible again.

**Explicit create follows R6 section 8.1.** C1 reservation on
`knowledge_submission_explicit_key` (`INSERT ... ON CONFLICT DO NOTHING`, then
the winner by key: equal digest replays, a different digest is
`idempotency_conflict` with no write), C2 immutable reads, C3 one
`lock_entity_mutation_scopes` call for an Entity subject, C4b canonical-order
evidence upsert then one `ORDER BY evidence_ref_id` lock in the strongest mode
needed, C4c one `require_active_capture_roots` call, C6 the subject lock, C7
the assertion, C8 the mutation then the links, C9 the Record Event. The flush is
the unit of work's, last before COMMIT.

**A duplicate writes nothing but its own submission row** (KLP-AC-148). The
live-fingerprint check runs at C2, before any evidence upsert; a duplicate
completes the submission `duplicate_existing` and returns. A duplicate that
appears only after C2 is found again under the C6 lock, and the transaction is
rolled back whole (`KnowledgeConcurrentDuplicateError`), so even the race leaves
no evidence, link, mutation or event row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, cast

from sqlalchemy import (
    ColumnElement,
    Connection,
    Row,
    Table,
    and_,
    case,
    exists,
    func,
    insert,
    literal,
    literal_column,
    not_,
    null,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.sql import text as sql_text

from my_pa.contracts.ports import (
    EvidenceUnavailableError,
    KnowledgeAssertionHistory,
    KnowledgeAssertionPage,
    KnowledgeAssertionRepository,
    KnowledgeAssertionReveal,
    KnowledgeAssertionRow,
    KnowledgeCaptureWithdrawnError,
    KnowledgeCheckpointKindMismatchError,
    KnowledgeCheckpointRequest,
    KnowledgeCheckpointResult,
    KnowledgeConcurrentDuplicateError,
    KnowledgeCreateEvidence,
    KnowledgeCreateRequest,
    KnowledgeEvidenceNotFoundError,
    KnowledgeEvidenceRow,
    KnowledgeIdempotencyConflictError,
    KnowledgeLedgerInvariantError,
    KnowledgeMutationRow,
    KnowledgeReviewCaseRow,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewDecisionResult,
    KnowledgeSourceBinding,
    KnowledgeSourceProfileUnboundError,
    KnowledgeSubjectNotCanonicalError,
    KnowledgeSubmissionResult,
    KnowledgeSubmitEvidence,
    KnowledgeSubmitRequest,
    KnowledgeSupersessionGuardError,
    KnowledgeTriggerNotFoundError,
    PortError,
    RecordEventStager,
    RepositoryFailureError,
    TransactionConflictError,
    is_transaction_conflict,
)
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleSelector,
    CaptureLifecycleState,
    CaptureWithdrawnError,
)
from my_pa.domain.capture.proposal import RiskClass
from my_pa.domain.capture.review import ReviewConflictError, ReviewNotFoundError
from my_pa.domain.common.classification import (
    CLASSIFICATION_RANK,
    Classification,
    classification_max,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.knowledge_assertion.admission import (
    AdmissionDecision,
    AdmissionEvidence,
    AdmissionPath,
    CurrentFact,
    DirectAdmissionBlocker,
    DirectAdmissionFacts,
    SourceProfileFacts,
    SubjectResolution,
    decide_direct_admission,
    decide_domain_route,
    supersession_guard_blockers,
)
from my_pa.domain.knowledge_assertion.checkpoint import CheckpointBinding, CheckpointSeal
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.provenance import (
    CAUSAL_RATE_COUNTED_OUTCOMES,
    CAUSAL_RATE_LIMIT,
    KNOWLEDGE_EVENT_ACTOR_CLASSES,
    KNOWLEDGE_EVENT_AUTHORITIES,
    KNOWLEDGE_MUTATION_EVENTS,
    CausalKey,
    CausalParent,
    CausalPosition,
    CausalRefusal,
    KnowledgeEventOrigin,
    resolve_causal_position,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAssertionLifecycle,
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeCheckpointOutcome,
    KnowledgeCheckpointReason,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeContentOrigin,
    KnowledgeEpistemicStatus,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceAvailability,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeMutationKind,
    KnowledgeNormalizationRule,
    KnowledgeOriginSystem,
    KnowledgeOwnerRefKind,
    KnowledgePredicateAdmissionState,
    KnowledgeProposalState,
    KnowledgeQualifierRule,
    KnowledgeReadOnlyProofState,
    KnowledgeReviewDisposition,
    KnowledgeReviewRequirement,
    KnowledgeSubjectKind,
    KnowledgeSubmissionOrigin,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)
from my_pa.domain.record_events import RecordEventDraft, RecordEventFamily
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import IsolationLevelError
from my_pa.infrastructure.persistence.capture_lifecycle import (
    capture_lifecycle_states,
    lifecycle_selected,
    require_active_capture_roots,
)
from my_pa.infrastructure.persistence.identifier_claim_lock import lock_entity_mutation_scopes
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    commitments,
    entities,
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_predicates,
    knowledge_assertion_proposals,
    knowledge_assertion_review_decisions,
    knowledge_assertion_subject_locks,
    knowledge_assertion_submissions,
    knowledge_assertions,
    knowledge_discovery_checkpoint_requests,
    knowledge_discovery_checkpoints,
    knowledge_discovery_source_profiles,
    knowledge_evidence_refs,
    knowledge_submission_evidence,
    knowledge_submission_trigger_events,
    meetings,
    project_constraints,
    projects,
    relationship_memory_versions,
    tasks,
)

__all__ = [
    "KNOWLEDGE_CREATE_CAPABILITY",
    "KNOWLEDGE_LEDGER_TRIGGERS",
    "KNOWLEDGE_MAINTENANCE_SOURCE",
    "KNOWLEDGE_REVIEW_CAPABILITY",
    "KNOWLEDGE_SUBMIT_CAPABILITY",
    "MAINTENANCE_BATCH",
    "KnowledgeMaintenanceResult",
    "KnowledgeSourceProfileChange",
    "KnowledgeSourceProfileConflictError",
    "KnowledgeSourceProfileRecord",
    "SqlKnowledgeAssertionRepository",
    "assertion_withheld_remote",
    "classification_rank",
    "knowledge_event_withheld_remote",
    "knowledge_ledger_failure",
    "proposal_withheld_remote",
]

#: The `source_capability` every explicit-create event names.
KNOWLEDGE_CREATE_CAPABILITY: Final = Capability.KNOWLEDGE_ASSERTIONS_CREATE.value
#: `knowledge_classification_rank('restricted_local')`.
_RESTRICTED_RANK: Final = 2
#: SQLSTATE `lock_not_available` (a `NOWAIT` row lock held by another transaction).
_LOCK_NOT_AVAILABLE: Final = "55P03"
_LIVE: Final = (
    KnowledgeAssertionLifecycle.ACTIVE.value,
    KnowledgeAssertionLifecycle.REVALIDATION_REQUIRED.value,
)
_UNAVAILABLE: Final = ("permission_lost", "deleted")
_EXTERNAL: Final = KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT.value
_CAPTURE: Final = KnowledgeEvidenceIdentityKind.CAPTURE.value
_MEMORY: Final = KnowledgeEvidenceIdentityKind.RELATIONSHIP_MEMORY.value
_EXPLICIT: Final = KnowledgeSubmissionOrigin.EXPLICIT_CREATE.value

# Aliases the withholding predicate reads through. Only keys, classification and
# availability columns are ever named on them.
_A: Final = cast(Table, knowledge_assertions.alias("ka_withheld"))
_PREDECESSOR: Final = cast(Table, knowledge_assertions.alias("ka_predecessor"))
_LINK: Final = cast(Table, knowledge_assertion_evidence_links.alias("ka_link"))
_EVIDENCE: Final = cast(Table, knowledge_evidence_refs.alias("ka_evidence"))
_SIBLING: Final = cast(Table, knowledge_evidence_refs.alias("ka_sibling"))
_PROFILE: Final = cast(Table, knowledge_discovery_source_profiles.alias("ka_profile"))
_SIBLING_PROFILE: Final = cast(
    Table, knowledge_discovery_source_profiles.alias("ka_sibling_profile")
)
_CAPTURE_VERSION: Final = cast(Table, capture_versions.alias("ka_capture_version"))
_MEMORY_VERSION: Final = cast(Table, relationship_memory_versions.alias("ka_memory_version"))
_SUCCESSOR: Final = cast(Table, knowledge_assertions.alias("ka_successor"))


def classification_rank(value: ColumnElement[Any]) -> ColumnElement[int]:
    """`knowledge.knowledge_classification_rank(value)`: the one SQL rank (R6 11.2)."""
    return cast(
        "ColumnElement[int]",
        func.knowledge.knowledge_classification_rank(value),
    )


def _restricted(value: ColumnElement[Any]) -> ColumnElement[bool]:
    return classification_rank(value) >= _RESTRICTED_RANK


def _evidence_withheld(evidence: Table, context: PrincipalContext) -> ColumnElement[bool]:
    """Whether one linked evidence row makes its assertion `withheld_remote`."""
    # The cited row's own profile is joined *inside* this EXISTS, so every name
    # it reads off `evidence` is a direct correlation to the enclosing link
    # SELECT (a nested scalar subquery would not correlate two levels out).
    sibling_restricted = exists(
        select(literal(1))
        .select_from(
            _SIBLING.join(
                _SIBLING_PROFILE,
                and_(
                    matching_partition_criterion(_SIBLING_PROFILE, _SIBLING),
                    _SIBLING_PROFILE.c.source_profile_id == _SIBLING.c.source_profile_id,
                ),
            ).join(
                _PROFILE,
                _PROFILE.c.origin_system == _SIBLING_PROFILE.c.origin_system,
            )
        )
        .where(
            partition_criterion(_SIBLING, context),
            partition_criterion(_SIBLING_PROFILE, context),
            partition_criterion(_PROFILE, context),
            _PROFILE.c.source_profile_id == evidence.c.source_profile_id,
            _SIBLING.c.identity_kind == _EXTERNAL,
            _SIBLING.c.external_object_id == evidence.c.external_object_id,
            _restricted(_SIBLING.c.source_classification),
        )
    )
    capture_restricted = exists(
        select(literal(1)).where(
            partition_criterion(_CAPTURE_VERSION, context),
            _CAPTURE_VERSION.c.capture_id == evidence.c.capture_id,
            _restricted(_CAPTURE_VERSION.c.classification),
        )
    )
    memory_restricted = exists(
        select(literal(1)).where(
            partition_criterion(_MEMORY_VERSION, context),
            _MEMORY_VERSION.c.memory_id == evidence.c.relationship_memory_id,
            _restricted(_MEMORY_VERSION.c.classification),
        )
    )
    archived = lifecycle_selected(
        evidence.c.capture_id, CaptureLifecycleSelector.ARCHIVED, context=context
    )
    assert archived is not None  # noqa: S101 - ARCHIVED always yields a condition
    return or_(
        _restricted(evidence.c.source_classification),
        and_(
            evidence.c.identity_kind == _EXTERNAL,
            or_(
                evidence.c.availability_revalidation_pending,
                evidence.c.availability_state.in_(_UNAVAILABLE),
                sibling_restricted,
            ),
        ),
        and_(evidence.c.identity_kind == _CAPTURE, or_(capture_restricted, archived)),
        and_(evidence.c.identity_kind == _MEMORY, memory_restricted),
    )


def assertion_withheld_remote(assertion: Table, principal_id: str) -> ColumnElement[bool]:
    """`withheld_remote(a)` of R6 section 5.2 for the row `assertion` names.

    A correlated predicate over `assertion` (any alias of
    `knowledge_assertions`): usable in a page's WHERE, a keyed read, and the
    Record Event reader's family predicate alike.
    """
    context = capture_context(principal_id)
    predecessor_restricted = exists(
        select(literal(1)).where(
            partition_criterion(_PREDECESSOR, context),
            _PREDECESSOR.c.assertion_id == assertion.c.supersedes_assertion_id,
            _restricted(_PREDECESSOR.c.classification),
        )
    )
    evidence_withheld = exists(
        select(literal(1))
        .select_from(
            _LINK.join(
                _EVIDENCE,
                and_(
                    matching_partition_criterion(_EVIDENCE, _LINK),
                    _EVIDENCE.c.evidence_ref_id == _LINK.c.evidence_ref_id,
                ),
            )
        )
        .where(
            partition_criterion(_LINK, context),
            partition_criterion(_EVIDENCE, context),
            _LINK.c.assertion_id == assertion.c.assertion_id,
            _evidence_withheld(_EVIDENCE, context),
        )
    )
    return or_(
        _restricted(assertion.c.classification),
        predecessor_restricted,
        evidence_withheld,
    )


def knowledge_event_withheld_remote(event: Table, principal_id: str) -> ColumnElement[bool]:
    """A `knowledge_assertion` Record Event a remote caller must not see.

    Fails closed: a remote caller sees the event only when its stored class is
    not `restricted_local` *and* there EXISTS an assertion of the same
    Principal with the event's `record_id` that is not `withheld_remote` now --
    in any lifecycle, so source tightening after supersession or archive
    withholds old events without any fan-out, and an event naming no visible
    assertion at all is withheld rather than shown.
    """
    context = capture_context(principal_id)
    return and_(
        event.c.record_family == RecordEventFamily.KNOWLEDGE_ASSERTION.value,
        or_(
            _restricted(event.c.classification),
            not_(
                exists(
                    select(literal(1)).where(
                        partition_criterion(_A, context),
                        _A.c.assertion_id == event.c.record_id,
                        not_(assertion_withheld_remote(_A, principal_id)),
                    )
                )
            ),
        ),
    )


def _stage_knowledge_event(
    stager: RecordEventStager,
    *,
    principal_id: str,
    assertion_id: str,
    mutation_kind: KnowledgeMutationKind,
    record_version: int,
    origin: KnowledgeEventOrigin,
    source_capability: str,
    classification: Classification,
    mutation_id: str,
    at: datetime,
    correlation_id: str | None,
) -> None:
    """Stage the one mapped Record Event of one `kamut_` mutation (C9).

    The single staging site of this module (KLP-AC-045): metadata only, the
    mutation as its receipt, actor/authority from who caused the write, and no
    `causation_event_id` -- every Knowledge write here is a root write.
    """
    mapped = KNOWLEDGE_MUTATION_EVENTS[mutation_kind]
    stager.stage(
        RecordEventDraft.issue(
            principal_id=principal_id,
            record_family=RecordEventFamily.KNOWLEDGE_ASSERTION,
            record_id=assertion_id,
            event_kind=mapped.kind,
            record_version=record_version,
            changed_fields=mapped.changed_fields,
            source_capability=source_capability,
            actor_class=KNOWLEDGE_EVENT_ACTOR_CLASSES[origin],
            classification=classification,
            occurred_at=at,
            source_receipt_id=mutation_id,
            authority=KNOWLEDGE_EVENT_AUTHORITIES[origin],
            correlation_id=correlation_id,
        )
    )


#: KLP-WP-04 (WP-02 DEV-01, Manager ruling): the one table mapping a Knowledge
#: ledger trigger's refusal -- (trigger function, SQLSTATE) -- to its typed port
#: error. The submission lifecycle guard raises `check_violation` (23514) on an
#: illegal INSERT and `restrict_violation` (23001) on DELETE or a second
#: completion; the submission reserved-at-commit trigger raises 23514; both
#: checkpoint-request triggers raise 23001. Each fires only on a server-side
#: ledger bug, so each is `KnowledgeLedgerInvariantError` (public
#: `internal_error`, no retry hint). Other 23514/23001 sources (CHECKs, the
#: head guard, append-only refusals) keep the generic repository failure.
KNOWLEDGE_LEDGER_TRIGGERS: Final[Mapping[tuple[str, str], type[PortError]]] = MappingProxyType(
    {
        ("knowledge_submission_lifecycle_guard", "23514"): KnowledgeLedgerInvariantError,
        ("knowledge_submission_lifecycle_guard", "23001"): KnowledgeLedgerInvariantError,
        ("knowledge_submission_reserved_at_commit", "23514"): KnowledgeLedgerInvariantError,
        ("knowledge_checkpoint_request_lifecycle_guard", "23001"): KnowledgeLedgerInvariantError,
        (
            "knowledge_checkpoint_request_reserved_at_commit",
            "23001",
        ): KnowledgeLedgerInvariantError,
    }
)


def knowledge_ledger_failure(error: BaseException) -> type[PortError] | None:
    """The typed port error a ledger trigger's refusal maps to, or `None`.

    Duck-typed on the driver error (`.orig` when wrapped): its `sqlstate` and
    the PL/pgSQL `diag.context` line naming the raising function.
    """
    original = getattr(error, "orig", None) or error
    sqlstate = getattr(original, "sqlstate", None)
    context = getattr(getattr(original, "diag", None), "context", None)
    if not isinstance(sqlstate, str) or not isinstance(context, str):
        return None
    for (function, state), failure in KNOWLEDGE_LEDGER_TRIGGERS.items():
        if sqlstate == state and f"function knowledge.{function}()" in context:
            return failure
    return None


def _translated[ResultT](work: Callable[[], ResultT]) -> ResultT:
    """Run one unit of SQL work, translating a store failure (the feed's rule)."""
    try:
        return work()
    except PortError:
        raise
    except DBAPIError as error:
        # R6 section 8.4: a deadlock or serialization victim is a retryable
        # conflict, checked before the OperationalError branch it falls into.
        ledger = knowledge_ledger_failure(error)
        if is_transaction_conflict(error):
            failure: Exception = TransactionConflictError("the transaction lost a race")
        elif ledger is not None:
            failure = ledger("a Knowledge ledger invariant refused the write")
        elif isinstance(error, (OperationalError, InterfaceError)):
            failure = EvidenceUnavailableError("the store could not be read")
        else:
            failure = RepositoryFailureError("the request could not be completed")
    except (SQLAlchemyError, IsolationLevelError):
        failure = RepositoryFailureError("the request could not be completed")
    raise failure


_ASSERTION_COLUMNS: Final = (
    "assertion_id",
    "subject_kind",
    "subject_id",
    "predicate_code",
    "predicate_version",
    "value_type",
    "value_text",
    "value_datetime",
    "qualifier_json",
    "effective_from",
    "effective_to",
    "epistemic_status",
    "classification",
    "lifecycle",
    "version",
    "supersedes_assertion_id",
    "created_at",
    "updated_at",
)


def _assertion_row(row: Row[Any]) -> KnowledgeAssertionRow:
    mapping = row._mapping
    return KnowledgeAssertionRow(
        assertion_id=mapping["assertion_id"],
        subject_kind=mapping["subject_kind"],
        subject_id=mapping["subject_id"],
        predicate_code=mapping["predicate_code"],
        predicate_version=int(mapping["predicate_version"]),
        value_type=mapping["value_type"],
        value_text=mapping["value_text"],
        value_datetime=mapping["value_datetime"],
        qualifier=mapping["qualifier_json"],
        effective_from=mapping["effective_from"],
        effective_to=mapping["effective_to"],
        epistemic_status=mapping["epistemic_status"],
        classification=mapping["classification"],
        lifecycle=mapping["lifecycle"],
        version=int(mapping["version"]),
        supersedes_assertion_id=mapping["supersedes_assertion_id"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
    )


def _predicate(row: Row[Any]) -> KnowledgePredicate:
    m = row._mapping
    return KnowledgePredicate(
        predicate_code=m["predicate_code"],
        predicate_version=int(m["predicate_version"]),
        admission_state=KnowledgePredicateAdmissionState(m["admission_state"]),
        value_type=KnowledgeValueType(m["value_type"]),
        cardinality=KnowledgeCardinality(m["cardinality"]),
        temporal_semantics=KnowledgeTemporalSemantics(m["temporal_semantics"]),
        qualifier_rule=KnowledgeQualifierRule(m["qualifier_rule"]),
        allowed_subject_kinds=frozenset(
            KnowledgeSubjectKind(kind) for kind in m["allowed_subject_kinds"]
        ),
        allowed_entity_types=frozenset(EntityType(kind) for kind in m["allowed_entity_types"]),
        canonical_owner=KnowledgeCanonicalOwner(m["canonical_owner"]),
        autonomous_admission_policy=KnowledgeAutonomousAdmissionPolicy(
            m["autonomous_admission_policy"]
        ),
        review_requirement=KnowledgeReviewRequirement(m["review_requirement"]),
        consequential_class=KnowledgeConsequentialClass(m["consequential_class"]),
        normalization_rule=KnowledgeNormalizationRule(m["normalization_rule"]),
        classification_floor=Classification(m["classification_floor"]),
        conflict_rule=KnowledgeConflictRule(m["conflict_rule"]),
        minimum_evidence_authority=KnowledgeEvidenceAuthority(m["minimum_evidence_authority"]),
        fingerprint_version=int(m["fingerprint_version"]),
    )


def _result_object(
    result: KnowledgeSubmissionResult, *, autonomous: bool = False
) -> dict[str, object]:
    stored: dict[str, object] = {
        "assertion_id": result.assertion_id,
        "assertion_version": result.assertion_version,
        "canonical_owner": result.canonical_owner,
        "mutation_id": result.mutation_id,
        "outcome": result.outcome,
        "reason": result.reason,
        "submission_id": result.submission_id,
    }
    if autonomous:
        # Autonomous submit's stored result also names the Review and route ids
        # (KLP-AC-051/120); explicit create's object is unchanged from WP-03.
        stored.update(
            proposal_id=result.proposal_id,
            review_case_id=result.review_case_id,
            routed_record_id=result.routed_record_id,
            superseded_assertion_id=result.superseded_assertion_id,
        )
    return stored


def _result_digest(result: KnowledgeSubmissionResult, *, autonomous: bool = False) -> str:
    """SHA-256 of the canonical stored public result (`result_digest`)."""
    encoded = json.dumps(
        _result_object(result, autonomous=autonomous), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_lifecycle(
    connection: Connection, principal_id: str, assertion_id: str | None, *, remote: bool
) -> str | None:
    """The read-only `current_lifecycle` of a result assertion (R6 6.3).

    KLP-WP-04 F2: `None` for a remote caller whenever the assertion is now
    `withheld_remote`, so a remote duplicate or replay discloses nothing of a
    withheld fact beyond what the stored result already held.
    """
    if assertion_id is None:
        return None
    a = knowledge_assertions
    criteria: list[ColumnElement[bool]] = [
        partition_criterion(a, capture_context(principal_id)),
        a.c.assertion_id == assertion_id,
    ]
    if remote:
        criteria.append(not_(assertion_withheld_remote(a, principal_id)))
    return connection.execute(select(a.c.lifecycle).where(*criteria)).scalar_one_or_none()


def _stored_result(
    connection: Connection, principal_id: str, row: Row[Any], *, remote: bool
) -> KnowledgeSubmissionResult:
    """A completed submission row as its stored public result (the replay)."""
    if row.submission_state != "completed":  # pragma: no cover - deferred guard backstop
        raise RepositoryFailureError("a reserved submission has no result")
    return KnowledgeSubmissionResult(
        submission_id=row.submission_id,
        outcome=row.outcome,
        reason=row.reason,
        assertion_id=row.result_assertion_id,
        assertion_version=row.result_assertion_version,
        mutation_id=row.result_mutation_id,
        canonical_owner=row.result_canonical_owner,
        current_lifecycle=_current_lifecycle(
            connection, principal_id, row.result_assertion_id, remote=remote
        ),
        superseded_assertion_id=row.result_superseded_assertion_id,
        proposal_id=row.result_proposal_id,
        review_case_id=row.result_review_case_id,
        routed_record_id=row.result_routed_record_id,
    )


def _capture_fence(
    connection: Connection, context: PrincipalContext, capture_ids: tuple[str, ...]
) -> None:
    """C4c: the one Capture-root share fence of a Knowledge write path (R6 8.1, AC-112).

    The module's single `require_active_capture_roots` call site: explicit
    create and autonomous submit each call this exactly once, after C3/C4b and
    before C5/C6, so an archived root refuses the whole transaction.
    """
    try:
        require_active_capture_roots(connection, context, capture_ids=capture_ids)
    except CaptureWithdrawnError:
        raise KnowledgeCaptureWithdrawnError("a cited capture was archived") from None


def _product_classes[ItemT: (KnowledgeCreateEvidence, KnowledgeSubmitEvidence)](
    connection: Connection, principal_id: str, items: Iterable[ItemT]
) -> dict[ItemT, Classification]:
    """Each cited Capture/RM version, owned and present, with its rank-max class (C2).

    The cited version must exist in this partition with exactly the cited
    digest; its class is the rank-max over *every* version of the capture or
    memory (R6 S-3), read in one statement. An absent and a foreign citation
    are the same `KnowledgeEvidenceNotFoundError`. External items are skipped.
    """
    context = capture_context(principal_id)
    observed: dict[ItemT, Classification] = {}
    for item in items:
        if item.identity_kind == _CAPTURE:
            rows = connection.execute(
                select(capture_versions.c.classification, capture_versions.c.content_sha256).where(
                    partition_criterion(capture_versions, context),
                    capture_versions.c.capture_id == item.capture_id,
                )
            ).all()
        elif item.identity_kind == _MEMORY:
            rows = connection.execute(
                select(
                    relationship_memory_versions.c.classification,
                    relationship_memory_versions.c.statement_sha256,
                ).where(
                    partition_criterion(relationship_memory_versions, context),
                    relationship_memory_versions.c.memory_id == item.relationship_memory_id,
                )
            ).all()
        else:
            continue
        if not any(row[1] == item.content_hash for row in rows):
            raise KnowledgeEvidenceNotFoundError("a cited version is not this Principal's")
        observed[item] = classification_max(
            Classification.PRIVATE_LOCAL, *(Classification(row[0]) for row in rows)
        )
    return observed


class SqlKnowledgeAssertionRepository(KnowledgeAssertionRepository):
    """The Knowledge Assertion plane on one transaction's connection.

    `stager` is required and keyword-only (KLP-AC-123): a construction without
    the unit of work's Record Event buffer cannot be written.
    """

    def __init__(self, connection: Connection, *, stager: RecordEventStager) -> None:
        self._connection = connection
        self._record_events = stager

    # ---- reads -----------------------------------------------------------

    def predicate_head(self, predicate_code: str) -> KnowledgePredicate | None:
        statement = (
            select(knowledge_assertion_predicates)
            .where(knowledge_assertion_predicates.c.predicate_code == predicate_code)
            .order_by(knowledge_assertion_predicates.c.predicate_version.desc())
            .limit(1)
        )
        row = _translated(lambda: self._connection.execute(statement).one_or_none())
        return None if row is None else _predicate(row)

    def _owned(self, principal_id: str, *, remote: bool) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [
            partition_criterion(knowledge_assertions, capture_context(principal_id))
        ]
        if remote:
            criteria.append(not_(assertion_withheld_remote(knowledge_assertions, principal_id)))
        return criteria

    def read_assertion(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionRow | None:
        statement = select(*(knowledge_assertions.c[name] for name in _ASSERTION_COLUMNS)).where(
            *self._owned(principal_id, remote=remote),
            knowledge_assertions.c.assertion_id == assertion_id,
        )
        row = _translated(lambda: self._connection.execute(statement).one_or_none())
        return None if row is None else _assertion_row(row)

    def page(
        self,
        principal_id: str,
        *,
        remote: bool,
        subject_kind: str | None,
        subject_id: str | None,
        predicate_code: str | None,
        lifecycles: frozenset[str],
        query: str | None,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> KnowledgeAssertionPage:
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("a page holds at least one assertion")
        table = knowledge_assertions
        criteria = self._owned(principal_id, remote=remote)
        criteria.append(table.c.lifecycle.in_(sorted(lifecycles)))
        if subject_kind is not None:
            criteria.append(table.c.subject_kind == subject_kind)
        if subject_id is not None:
            criteria.append(table.c.subject_id == subject_id)
        if predicate_code is not None:
            criteria.append(table.c.predicate_code == predicate_code)
        if query is not None:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            criteria.append(table.c.value_text.ilike(f"%{escaped}%", escape="\\"))
        if after is not None:
            created_at, assertion_id = after
            criteria.append(
                or_(
                    table.c.created_at < created_at,
                    and_(table.c.created_at == created_at, table.c.assertion_id < assertion_id),
                )
            )
        statement = (
            select(*(table.c[name] for name in _ASSERTION_COLUMNS))
            .where(*criteria)
            .order_by(table.c.created_at.desc(), table.c.assertion_id.desc())
            .limit(limit + 1)
        )
        rows = _translated(lambda: self._connection.execute(statement).all())
        return KnowledgeAssertionPage(
            rows=tuple(_assertion_row(row) for row in rows[:limit]),
            has_more=len(rows) > limit,
        )

    def history(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionHistory | None:
        assertion = self.read_assertion(principal_id, assertion_id, remote=remote)
        if assertion is None:
            return None
        context = capture_context(principal_id)
        mutations = _translated(
            lambda: self._connection.execute(
                select(
                    knowledge_assertion_mutations.c.mutation_id,
                    knowledge_assertion_mutations.c.mutation_kind,
                    knowledge_assertion_mutations.c.prior_version,
                    knowledge_assertion_mutations.c.new_version,
                    knowledge_assertion_mutations.c.created_at,
                )
                .where(
                    partition_criterion(knowledge_assertion_mutations, context),
                    knowledge_assertion_mutations.c.assertion_id == assertion_id,
                )
                .order_by(knowledge_assertion_mutations.c.new_version)
            ).all()
        )
        neighbour_criteria: list[ColumnElement[bool]] = [partition_criterion(_SUCCESSOR, context)]
        if remote:
            neighbour_criteria.append(not_(assertion_withheld_remote(_SUCCESSOR, principal_id)))
        predecessor_id: str | None = None
        if assertion.supersedes_assertion_id is not None:
            predecessor_id = _translated(
                lambda: self._connection.execute(
                    select(_SUCCESSOR.c.assertion_id).where(
                        *neighbour_criteria,
                        _SUCCESSOR.c.assertion_id == assertion.supersedes_assertion_id,
                    )
                ).scalar_one_or_none()
            )
        successor_id = _translated(
            lambda: self._connection.execute(
                select(_SUCCESSOR.c.assertion_id).where(
                    *neighbour_criteria,
                    _SUCCESSOR.c.supersedes_assertion_id == assertion_id,
                )
            ).scalar_one_or_none()
        )
        return KnowledgeAssertionHistory(
            assertion=assertion,
            mutations=tuple(
                KnowledgeMutationRow(
                    mutation_id=row.mutation_id,
                    mutation_kind=row.mutation_kind,
                    prior_version=int(row.prior_version),
                    new_version=int(row.new_version),
                    created_at=row.created_at,
                )
                for row in mutations
            ),
            predecessor_id=predecessor_id,
            successor_id=successor_id,
        )

    def reveal(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionReveal | None:
        context = capture_context(principal_id)
        statement = (
            select(
                *(knowledge_assertions.c[name] for name in _ASSERTION_COLUMNS),
                knowledge_assertions.c.origin_submission_id,
                knowledge_assertion_submissions.c.origin,
            )
            .select_from(
                knowledge_assertions.join(
                    knowledge_assertion_submissions,
                    and_(
                        matching_partition_criterion(
                            knowledge_assertion_submissions, knowledge_assertions
                        ),
                        knowledge_assertion_submissions.c.submission_id
                        == knowledge_assertions.c.origin_submission_id,
                    ),
                )
            )
            .where(
                *self._owned(principal_id, remote=remote),
                partition_criterion(knowledge_assertion_submissions, context),
                knowledge_assertions.c.assertion_id == assertion_id,
            )
        )
        row = _translated(lambda: self._connection.execute(statement).one_or_none())
        if row is None:
            return None
        links = knowledge_assertion_evidence_links
        evidence = knowledge_evidence_refs
        rows = _translated(
            lambda: self._connection.execute(
                select(
                    evidence.c.evidence_ref_id,
                    links.c.evidence_role,
                    evidence.c.identity_kind,
                    evidence.c.capture_id,
                    evidence.c.relationship_memory_id,
                    evidence.c.source_profile_id,
                    evidence.c.external_object_id,
                    evidence.c.external_version_id,
                    evidence.c.content_hash,
                    evidence.c.excerpt,
                    evidence.c.excerpt_sha256,
                    evidence.c.content_origin,
                    evidence.c.source_classification,
                    evidence.c.availability_state,
                    evidence.c.availability_revalidation_pending,
                )
                .select_from(
                    links.join(
                        evidence,
                        and_(
                            matching_partition_criterion(evidence, links),
                            evidence.c.evidence_ref_id == links.c.evidence_ref_id,
                        ),
                    )
                )
                .where(
                    partition_criterion(links, context),
                    partition_criterion(evidence, context),
                    links.c.assertion_id == assertion_id,
                )
                .order_by(evidence.c.evidence_ref_id, links.c.evidence_role)
            ).all()
        )
        return KnowledgeAssertionReveal(
            assertion=_assertion_row(row),
            submission_id=row.origin_submission_id,
            submission_origin=row.origin,
            evidence=tuple(
                KnowledgeEvidenceRow(
                    evidence_ref_id=item.evidence_ref_id,
                    evidence_role=item.evidence_role,
                    identity_kind=item.identity_kind,
                    capture_id=item.capture_id,
                    relationship_memory_id=item.relationship_memory_id,
                    source_profile_id=item.source_profile_id,
                    external_object_id=item.external_object_id,
                    external_version_id=item.external_version_id,
                    content_hash=item.content_hash,
                    # Unavailability hides the excerpt; it is not removed at
                    # rest (R6 5.5). A restricted row already holds none.
                    excerpt=(
                        item.excerpt
                        if item.availability_state == "available"
                        and not item.availability_revalidation_pending
                        else None
                    ),
                    excerpt_sha256=item.excerpt_sha256,
                    content_origin=item.content_origin,
                    source_classification=item.source_classification,
                    availability_state=item.availability_state,
                    availability_revalidation_pending=bool(item.availability_revalidation_pending),
                )
                for item in rows
            ),
        )

    # ---- explicit create -------------------------------------------------

    def _verified_evidence(
        self, principal_id: str, request: KnowledgeCreateRequest
    ) -> dict[KnowledgeCreateEvidence, Classification]:
        """Each cited version, owned and present, with its rank-max class (C2)."""
        return _product_classes(self._connection, principal_id, request.evidence)

    def create(
        self,
        principal_id: str,
        request: KnowledgeCreateRequest,
        *,
        at: datetime,
        correlation_id: str,
        remote: bool = False,
    ) -> KnowledgeSubmissionResult:
        transaction = _ExplicitCreate(self._connection, principal_id, request, at, remote=remote)
        result = _translated(
            lambda: transaction.run(
                lambda: (
                    {} if request.domain_owned else self._verified_evidence(principal_id, request)
                )
            )
        )
        created = transaction.created
        if created is not None:
            # C9: exactly the mapped event, metadata only (KLP-AC-042/044), with
            # the `kamut_` mutation as its receipt. A replay, a duplicate, a
            # domain-owned completion and a refusal stage nothing.
            _stage_knowledge_event(
                self._record_events,
                principal_id=principal_id,
                assertion_id=created.assertion_id,
                mutation_kind=KnowledgeMutationKind.CREATE,
                record_version=1,
                origin=KnowledgeEventOrigin.EXPLICIT_CREATE,
                source_capability=KNOWLEDGE_CREATE_CAPABILITY,
                classification=created.classification,
                mutation_id=created.mutation_id,
                at=at,
                correlation_id=correlation_id,
            )
        return result

    def replay_create(
        self, principal_id: str, idempotency_key: str, request_digest: str, *, remote: bool
    ) -> KnowledgeSubmissionResult | None:
        s = knowledge_assertion_submissions
        row = _translated(
            lambda: self._connection.execute(
                select(s).where(
                    partition_criterion(s, capture_context(principal_id)),
                    s.c.origin == _EXPLICIT,
                    s.c.idempotency_key == idempotency_key,
                )
            ).one_or_none()
        )
        if row is None:
            return None
        if row.request_digest != request_digest:
            raise KnowledgeIdempotencyConflictError("the key is bound to another request")
        return _translated(
            lambda: _stored_result(self._connection, principal_id, row, remote=remote)
        )

    # ---- autonomous submit (KLP-WP-04 slice B2) -----------------------------

    def source_binding(
        self, principal_id: str, source_profile_id: str, authenticated_client_id: str
    ) -> KnowledgeSourceBinding | None:
        p = knowledge_discovery_source_profiles
        row = _translated(
            lambda: self._connection.execute(
                select(
                    p.c.source_profile_id,
                    p.c.authenticated_client_id,
                    p.c.scope_digest,
                    p.c.origin_system,
                    p.c.is_synthetic,
                ).where(
                    partition_criterion(p, capture_context(principal_id)),
                    p.c.source_profile_id == source_profile_id,
                    p.c.authenticated_client_id == authenticated_client_id,
                )
            ).one_or_none()
        )
        if row is None:
            return None
        return KnowledgeSourceBinding(
            source_profile_id=row.source_profile_id,
            authenticated_client_id=row.authenticated_client_id,
            scope_digest=row.scope_digest,
            origin_system=row.origin_system,
            is_synthetic=bool(row.is_synthetic),
        )

    def replay_submission(
        self,
        principal_id: str,
        *,
        authenticated_client_id: str,
        source_profile_id: str,
        external_run_id: str,
        external_candidate_id: str,
        request_digest: str,
        remote: bool,
    ) -> KnowledgeSubmissionResult | None:
        s = knowledge_assertion_submissions
        row = _translated(
            lambda: self._connection.execute(
                select(s).where(
                    partition_criterion(s, capture_context(principal_id)),
                    s.c.origin == _AUTONOMOUS,
                    s.c.authenticated_client_id == authenticated_client_id,
                    s.c.source_profile_id == source_profile_id,
                    s.c.external_run_id == external_run_id,
                    s.c.external_candidate_id == external_candidate_id,
                )
            ).one_or_none()
        )
        if row is None:
            return None
        if row.request_digest != request_digest:
            raise KnowledgeIdempotencyConflictError("the candidate is bound to another request")
        return _translated(
            lambda: _stored_result(self._connection, principal_id, row, remote=remote)
        )

    def submit(
        self,
        principal_id: str,
        request: KnowledgeSubmitRequest,
        *,
        at: datetime,
        correlation_id: str,
        relationship_intelligence_composed: bool,
        relationship_memory_composed: bool,
    ) -> KnowledgeSubmissionResult:
        transaction = _AutonomousSubmit(
            self._connection,
            principal_id,
            request,
            at,
            relationship_intelligence_composed=relationship_intelligence_composed,
            relationship_memory_composed=relationship_memory_composed,
        )
        result = _translated(
            lambda: transaction.run(
                lambda: {
                    item.identity: observed
                    for item, observed in _product_classes(
                        self._connection, principal_id, request.evidence
                    ).items()
                }
            )
        )
        # The read-only `current_lifecycle`, read as the remote caller sees it
        # (F2: `None` while the result assertion is `withheld_remote`).
        result = replace(
            result,
            current_lifecycle=_translated(
                lambda: _current_lifecycle(
                    self._connection, principal_id, result.assertion_id, remote=True
                )
            ),
        )
        for staged in transaction.staged:
            # C9: exactly the mapped event per mutation, metadata only (KLP-AC-042).
            _stage_knowledge_event(
                self._record_events,
                principal_id=principal_id,
                assertion_id=staged.assertion_id,
                mutation_kind=staged.mutation_kind,
                record_version=staged.record_version,
                origin=KnowledgeEventOrigin.AUTONOMOUS_SUBMIT,
                source_capability=KNOWLEDGE_SUBMIT_CAPABILITY,
                classification=staged.classification,
                mutation_id=staged.mutation_id,
                at=at,
                correlation_id=correlation_id,
            )
        return result

    # ---- discovery checkpoint (KLP-WP-04 slice B3) ---------------------------

    def replay_checkpoint(
        self,
        principal_id: str,
        *,
        authenticated_client_id: str,
        idempotency_key: str,
        request_digest: str,
        seal: CheckpointSeal,
    ) -> KnowledgeCheckpointResult | None:
        r = knowledge_discovery_checkpoint_requests
        row = _translated(
            lambda: self._connection.execute(
                select(r).where(
                    partition_criterion(r, capture_context(principal_id)),
                    r.c.authenticated_client_id == authenticated_client_id,
                    r.c.idempotency_key == idempotency_key,
                )
            ).one_or_none()
        )
        if row is None:
            return None
        if row.request_digest != request_digest:
            raise KnowledgeIdempotencyConflictError("the key is bound to another request")
        return _translated(
            lambda: _stored_checkpoint_result(self._connection, principal_id, row, seal)
        )

    def checkpoint(
        self,
        principal_id: str,
        request: KnowledgeCheckpointRequest,
        *,
        at: datetime,
        seal: CheckpointSeal,
    ) -> KnowledgeCheckpointResult:
        transaction = _CheckpointAdvance(self._connection, principal_id, request, at, seal)
        return _translated(transaction.run)

    # ---- source profiles and maintenance (KLP-WP-04 slice B1) ---------------

    # ---- Knowledge Review (KLP-WP-04 slice C) ---------------------------------

    def review_cases(
        self,
        principal_id: str,
        *,
        remote: bool,
        state: str | None,
        entity_id: str | None,
        after_opened_at: datetime | None,
        after_review_case_id: str | None,
        limit: int,
    ) -> tuple[KnowledgeReviewCaseRow, ...]:
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("a page holds at least one case")
        if (after_opened_at is None) != (after_review_case_id is None):
            raise ValueError("a review cursor position is complete or absent")
        p = knowledge_assertion_proposals
        statement = _review_case_statement(principal_id, remote=remote)
        if state is not None:
            statement = statement.where(p.c.state == state)
        if entity_id is not None:
            statement = statement.where(
                p.c.subject_kind == KnowledgeSubjectKind.ENTITY.value,
                p.c.subject_id == entity_id,
            )
        if after_opened_at is not None and after_review_case_id is not None:
            statement = statement.where(
                or_(
                    p.c.created_at > after_opened_at,
                    and_(
                        p.c.created_at == after_opened_at,
                        p.c.review_case_id > after_review_case_id,
                    ),
                )
            )
        statement = statement.order_by(p.c.created_at, p.c.review_case_id).limit(limit)
        rows = _translated(lambda: self._connection.execute(statement).all())
        return tuple(_review_case_row(row) for row in rows)

    def review_case(
        self, principal_id: str, review_case_id: str, *, remote: bool
    ) -> KnowledgeReviewCaseRow | None:
        statement = _review_case_statement(principal_id, remote=remote).where(
            knowledge_assertion_proposals.c.review_case_id == review_case_id
        )
        row = _translated(lambda: self._connection.execute(statement).one_or_none())
        return None if row is None else _review_case_row(row)

    def decide_review(
        self, principal_id: str, request: KnowledgeReviewDecisionRequest, *, at: datetime
    ) -> KnowledgeReviewDecisionResult:
        transaction = _ReviewDecision(self._connection, principal_id, request, at)
        result = _translated(transaction.run)
        for staged in transaction.staged:
            # C9: the mapped event of each promoting mutation (KLP-AC-042); a
            # reject/defer/mark_unresolved/invalidate stages none (KLP-AC-043).
            _stage_knowledge_event(
                self._record_events,
                principal_id=principal_id,
                assertion_id=staged.assertion_id,
                mutation_kind=staged.mutation_kind,
                record_version=staged.record_version,
                origin=KnowledgeEventOrigin.REVIEW_PROMOTION,
                source_capability=KNOWLEDGE_REVIEW_CAPABILITY,
                classification=staged.classification,
                mutation_id=staged.mutation_id,
                at=at,
                correlation_id=request.correlation_id,
            )
        return result

    def _maintenance(self, principal_id: str, at: datetime) -> _Maintenance:
        return _Maintenance(self._connection, principal_id, self._record_events, at)

    def apply_source_profile(
        self,
        principal_id: str,
        *,
        authenticated_client_id: str,
        origin_system: str,
        scope_digest: str,
        authority_ceiling: str,
        direct_admission_enabled: bool,
        read_only_proof_state: str,
        at: datetime,
    ) -> KnowledgeSourceProfileChange:
        """Create, update the mutable controls of, or keep one active profile binding."""
        body = self._maintenance(principal_id, at)
        return _translated(
            lambda: body.apply_profile(
                authenticated_client_id=authenticated_client_id,
                origin_system=origin_system,
                scope_digest=scope_digest,
                authority_ceiling=authority_ceiling,
                direct_admission_enabled=direct_admission_enabled,
                read_only_proof_state=read_only_proof_state,
            )
        )

    def disable_source_profile(
        self, principal_id: str, source_profile_id: str, *, at: datetime
    ) -> KnowledgeSourceProfileRecord | None:
        body = self._maintenance(principal_id, at)
        return _translated(lambda: body.disable_profile(source_profile_id))

    def source_profiles(
        self, principal_id: str, *, at: datetime
    ) -> tuple[KnowledgeSourceProfileRecord, ...]:
        body = self._maintenance(principal_id, at)
        return _translated(body.profiles)

    def classify_evidence_restricted(
        self, principal_id: str, evidence_ref_id: str, *, at: datetime
    ) -> KnowledgeMaintenanceResult:
        """The single source-classification ingress (R6 5.1, KLP-AC-164)."""
        body = self._maintenance(principal_id, at)
        return _translated(lambda: body.classify_restricted(principal_id, evidence_ref_id))

    def record_evidence_availability(
        self,
        principal_id: str,
        evidence_ref_id: str,
        availability: KnowledgeEvidenceAvailability,
        *,
        at: datetime,
        verified_at: datetime | None = None,
    ) -> KnowledgeMaintenanceResult:
        """The single availability ingress (R6 5.4, KLP-AC-070/142)."""
        body = self._maintenance(principal_id, at)
        return _translated(
            lambda: body.record_availability(
                principal_id, evidence_ref_id, availability, verified_at=verified_at
            )
        )

    def drain_availability_revalidation(
        self, principal_id: str, *, at: datetime
    ) -> KnowledgeMaintenanceResult:
        body = self._maintenance(principal_id, at)
        return _translated(lambda: body.drain_revalidation(principal_id))

    def redact_sealed_checkpoint_requests(
        self, principal_id: str, *, below_seal: int, at: datetime
    ) -> int:
        body = self._maintenance(principal_id, at)
        return _translated(lambda: body.redact_sealed(below_seal))


@dataclass(frozen=True, slots=True)
class _CreatedEvent:
    """What the one Record Event of an admitted create names."""

    assertion_id: str
    mutation_id: str
    classification: Classification


class _ExplicitCreate:
    """One explicit-create transaction body (R6 sections 6 and 8)."""

    def __init__(
        self,
        connection: Connection,
        principal_id: str,
        request: KnowledgeCreateRequest,
        at: datetime,
        *,
        remote: bool = False,
    ) -> None:
        self.connection = connection
        self.principal_id = principal_id
        self.request = request
        self.at = at
        self.remote = remote
        self.context = capture_context(principal_id)
        self.created: _CreatedEvent | None = None

    def _bound(self, table: Table, values: dict[str, object]) -> dict[str, object]:
        """`values` stamped with this Principal through the partition guard."""
        return principal_bound_values(values, table, self.context)

    # -- C1: the explicit-key arbiter ---------------------------------------

    def _winner(self) -> KnowledgeSubmissionResult | None:
        """The completed submission already bound to this key, replayed, or `None`."""
        s = knowledge_assertion_submissions
        row = self.connection.execute(
            select(s).where(
                partition_criterion(s, self.context),
                s.c.origin == _EXPLICIT,
                s.c.idempotency_key == self.request.idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        if row.request_digest != self.request.request_digest:
            raise KnowledgeIdempotencyConflictError("the key is bound to another request")
        return _stored_result(self.connection, self.principal_id, row, remote=self.remote)

    def _insert_submission(
        self, submission_id: str, *, refused: KnowledgeSubmissionReason | None
    ) -> bool:
        """Reserve the key (or insert a born-completed refusal). False when another won."""
        values: dict[str, object] = {
            "submission_id": submission_id,
            "origin": _EXPLICIT,
            "authenticated_client_id": self.request.authenticated_client_id,
            "idempotency_key": self.request.idempotency_key,
            "origin_is_synthetic": False,
            "subject_kind": self.request.subject_kind,
            "subject_id": self.request.subject_id,
            "predicate_code": self.request.predicate_code,
            "request_digest": self.request.request_digest,
            # R6 9.1(b): explicit create is always a root, depth 0, root = self.
            "causal_depth": 0,
            "causal_root_submission_id": submission_id,
            "submission_state": "reserved",
            "created_at": self.at,
        }
        if refused is not None:
            result = KnowledgeSubmissionResult(
                submission_id=submission_id,
                outcome=KnowledgeSubmissionOutcome.REFUSED.value,
                reason=refused.value,
                assertion_id=None,
                assertion_version=None,
                mutation_id=None,
                canonical_owner=None,
                current_lifecycle=None,
            )
            values.update(
                submission_state="completed",
                outcome=result.outcome,
                reason=result.reason,
                result_digest=_result_digest(result),
                completed_at=self.at,
            )
        statement = (
            pg_insert(knowledge_assertion_submissions)
            .values(**self._bound(knowledge_assertion_submissions, values))
            .on_conflict_do_nothing(
                index_elements=["principal_id", "idempotency_key"],
                index_where=sql_text(f"origin = '{_EXPLICIT}'"),
            )
            .returning(knowledge_assertion_submissions.c.submission_id)
        )
        return self.connection.execute(statement).scalar_one_or_none() is not None

    def _complete(self, result: KnowledgeSubmissionResult) -> KnowledgeSubmissionResult:
        s = knowledge_assertion_submissions
        done = self.connection.execute(
            update(s)
            .where(
                partition_criterion(s, self.context),
                s.c.submission_id == result.submission_id,
                s.c.submission_state == "reserved",
            )
            .values(
                submission_state="completed",
                outcome=result.outcome,
                reason=result.reason,
                result_assertion_id=result.assertion_id,
                result_assertion_version=result.assertion_version,
                result_mutation_id=result.mutation_id,
                result_canonical_owner=result.canonical_owner,
                result_digest=_result_digest(result),
                completed_at=self.at,
            )
        )
        if done.rowcount != 1:
            raise RepositoryFailureError("the reservation was not held")
        return result

    # -- C2: immutable reads -----------------------------------------------

    def _subject_is_canonical(self, *, lock: bool) -> bool:
        kind = self.request.subject_kind
        subject_id = self.request.subject_id
        if kind == KnowledgeSubjectKind.PRINCIPAL.value:
            return subject_id == self.principal_id
        if kind == KnowledgeSubjectKind.PROJECT.value:
            return (
                self.connection.execute(
                    select(projects.c.project_id).where(
                        partition_criterion(projects, self.context),
                        projects.c.project_id == subject_id,
                    )
                ).scalar_one_or_none()
                is not None
            )
        if kind == KnowledgeSubjectKind.ENTITY.value:
            if lock:
                # C3: one call over the complete Entity set (R6 8.1, 8.2).
                lock_entity_mutation_scopes(self.connection, self.principal_id, (subject_id,))
            row = self.connection.execute(
                select(entities.c.entity_type, entities.c.status).where(
                    partition_criterion(entities, self.context),
                    entities.c.entity_id == subject_id,
                )
            ).one_or_none()
            return (
                row is not None
                and row.status == EntityStatus.ACTIVE.value
                and row.entity_type in self.request.allowed_entity_types
            )
        # managed_document / evidence_ref subjects have no WP-03 owner check.
        return False

    def _captures(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(item.capture_id)
                    for item in self.request.evidence
                    if item.identity_kind == _CAPTURE
                }
            )
        )

    def _live_duplicate(self) -> Row[Any] | None:
        a = knowledge_assertions
        return self.connection.execute(
            select(a.c.assertion_id, a.c.version).where(
                partition_criterion(a, self.context),
                a.c.fingerprint_version == 1,
                a.c.assertion_fingerprint == self.request.assertion_fingerprint,
                a.c.lifecycle.in_(_LIVE),
            )
        ).one_or_none()

    def _slot_taken(self) -> bool:
        if self.request.cardinality != KnowledgeCardinality.SINGLE_CURRENT.value:
            return False
        a = knowledge_assertions
        return (
            self.connection.execute(
                select(a.c.assertion_id).where(
                    partition_criterion(a, self.context),
                    a.c.subject_kind == self.request.subject_kind,
                    a.c.subject_id == self.request.subject_id,
                    a.c.predicate_code == self.request.predicate_code,
                    a.c.cardinality == KnowledgeCardinality.SINGLE_CURRENT.value,
                    a.c.lifecycle.in_(_LIVE),
                )
            ).first()
            is not None
        )

    # -- the transaction ----------------------------------------------------

    def run(
        self, verify: Callable[[], dict[KnowledgeCreateEvidence, Classification]]
    ) -> KnowledgeSubmissionResult:
        replay = self._winner()
        if replay is not None:
            return replay
        submission_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_SUBMISSION)
        refusal: KnowledgeSubmissionReason | None = None
        observed: dict[KnowledgeCreateEvidence, Classification] = {}
        if not self.request.domain_owned:
            observed = verify()
            if not self._subject_is_canonical(lock=False):
                refusal = KnowledgeSubmissionReason.SUBJECT_NOT_CANONICAL
            elif any(
                state is CaptureLifecycleState.ARCHIVED
                for state in capture_lifecycle_states(
                    self.connection, self._captures(), context=self.context
                ).values()
            ):
                refusal = KnowledgeSubmissionReason.CAPTURE_ARCHIVED
        if not self._insert_submission(submission_id, refused=refusal):
            winner = self._winner()
            if winner is None:
                raise RepositoryFailureError("the key's winner could not be read")
            return winner
        if refusal is not None:
            return KnowledgeSubmissionResult(
                submission_id=submission_id,
                outcome=KnowledgeSubmissionOutcome.REFUSED.value,
                reason=refusal.value,
                assertion_id=None,
                assertion_version=None,
                mutation_id=None,
                canonical_owner=None,
                current_lifecycle=None,
            )
        if self.request.domain_owned:
            return self._complete(
                KnowledgeSubmissionResult(
                    submission_id=submission_id,
                    outcome=KnowledgeSubmissionOutcome.DOMAIN_OWNED_NO_INTAKE.value,
                    reason=KnowledgeSubmissionReason.CANONICAL_OWNER_NO_INTAKE.value,
                    assertion_id=None,
                    assertion_version=None,
                    mutation_id=None,
                    canonical_owner=self.request.canonical_owner,
                    current_lifecycle=None,
                )
            )
        duplicate = self._live_duplicate()
        if duplicate is not None:
            # KLP-AC-148: only this submission row is written.
            result = self._complete(
                KnowledgeSubmissionResult(
                    submission_id=submission_id,
                    outcome=KnowledgeSubmissionOutcome.DUPLICATE_EXISTING.value,
                    reason=KnowledgeSubmissionReason.EXACT_DUPLICATE.value,
                    assertion_id=duplicate.assertion_id,
                    assertion_version=int(duplicate.version),
                    mutation_id=None,
                    canonical_owner=KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION.value,
                    current_lifecycle=None,
                )
            )
            return replace(
                result,
                current_lifecycle=_current_lifecycle(
                    self.connection, self.principal_id, duplicate.assertion_id, remote=self.remote
                ),
            )
        if self._slot_taken():
            return self._complete(
                KnowledgeSubmissionResult(
                    submission_id=submission_id,
                    outcome=KnowledgeSubmissionOutcome.CONFLICT.value,
                    reason=KnowledgeSubmissionReason.INCOMPATIBLE_CURRENT_FACT.value,
                    assertion_id=None,
                    assertion_version=None,
                    mutation_id=None,
                    canonical_owner=KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION.value,
                    current_lifecycle=None,
                )
            )
        return self._admit(submission_id, observed)

    def _admit(
        self, submission_id: str, observed: Mapping[KnowledgeCreateEvidence, Classification]
    ) -> KnowledgeSubmissionResult:
        # C3: the Entity mutation scope, re-checking the subject under it.
        if not self._subject_is_canonical(lock=True):
            return self._complete(
                KnowledgeSubmissionResult(
                    submission_id=submission_id,
                    outcome=KnowledgeSubmissionOutcome.REFUSED.value,
                    reason=KnowledgeSubmissionReason.SUBJECT_NOT_CANONICAL.value,
                    assertion_id=None,
                    assertion_version=None,
                    mutation_id=None,
                    canonical_owner=None,
                    current_lifecycle=None,
                )
            )
        # C4b: canonical-order upsert, then one sorted lock in the strongest mode.
        evidence_ids = self._resolve_evidence(observed)
        # C4c: exactly one publication fence over the cited Capture roots.
        _capture_fence(self.connection, self.context, self._captures())
        stored = self._stored_classes(evidence_ids.values())
        classification = classification_max(
            Classification.PRIVATE_LOCAL, self.request.classification_floor, *stored
        )
        # C6: the complete (here: single) subject-lock set.
        self._lock_subject()
        if self._live_duplicate() is not None or self._slot_taken():
            raise KnowledgeConcurrentDuplicateError("a concurrent create took this fact")
        # C7: the assertion.
        assertion_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION)
        request = self.request
        self.connection.execute(
            insert(knowledge_assertions).values(
                **self._bound(
                    knowledge_assertions,
                    {
                        "assertion_id": assertion_id,
                        "subject_kind": request.subject_kind,
                        "subject_id": request.subject_id,
                        "predicate_code": request.predicate_code,
                        "predicate_version": request.predicate_version,
                        "value_type": request.value_type,
                        "cardinality": request.cardinality,
                        "temporal_semantics": request.temporal_semantics,
                        "qualifier_rule": request.qualifier_rule,
                        "value_text": request.value_text,
                        "value_datetime": request.value_datetime,
                        "qualifier_json": null()
                        if request.qualifier is None
                        else dict(request.qualifier),
                        "effective_from": request.effective_from,
                        "effective_to": request.effective_to,
                        "normalized_value_sha256": request.normalized_value_sha256,
                        "fingerprint_version": 1,
                        "assertion_fingerprint": request.assertion_fingerprint,
                        "epistemic_status": KnowledgeEpistemicStatus.PRINCIPAL_ASSERTED.value,
                        "classification": classification.value,
                        "origin_is_synthetic": False,
                        "lifecycle": KnowledgeAssertionLifecycle.ACTIVE.value,
                        "version": 1,
                        "origin_submission_id": submission_id,
                        "created_at": self.at,
                        "updated_at": self.at,
                    },
                )
            )
        )
        # C8: the mutation receipt, then the links and the submission's evidence.
        mutation_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION)
        self.connection.execute(
            insert(knowledge_assertion_mutations).values(
                **self._bound(
                    knowledge_assertion_mutations,
                    {
                        "mutation_id": mutation_id,
                        "assertion_id": assertion_id,
                        "mutation_kind": KnowledgeMutationKind.CREATE.value,
                        "prior_version": 0,
                        "new_version": 1,
                        "submission_id": submission_id,
                        "created_at": self.at,
                    },
                )
            )
        )
        for item in sorted(request.evidence, key=lambda entry: (evidence_ids[entry], entry.role)):
            self.connection.execute(
                insert(knowledge_submission_evidence).values(
                    **self._bound(
                        knowledge_submission_evidence,
                        {
                            "submission_id": submission_id,
                            "evidence_ref_id": evidence_ids[item],
                            "evidence_role": item.role,
                            "created_at": self.at,
                        },
                    )
                )
            )
            self.connection.execute(
                insert(knowledge_assertion_evidence_links).values(
                    **self._bound(
                        knowledge_assertion_evidence_links,
                        {
                            "assertion_id": assertion_id,
                            "evidence_ref_id": evidence_ids[item],
                            "evidence_role": item.role,
                            "linked_by_mutation_id": mutation_id,
                            "created_at": self.at,
                        },
                    )
                )
            )
        result = self._complete(
            KnowledgeSubmissionResult(
                submission_id=submission_id,
                outcome=KnowledgeSubmissionOutcome.DIRECT_CREATED.value,
                reason=KnowledgeSubmissionReason.CREATED.value,
                assertion_id=assertion_id,
                assertion_version=1,
                mutation_id=mutation_id,
                canonical_owner=KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION.value,
                current_lifecycle=None,
            )
        )
        # C9 is staged by the repository from this record (KLP-AC-042/044).
        self.created = _CreatedEvent(
            assertion_id=assertion_id, mutation_id=mutation_id, classification=classification
        )
        return KnowledgeSubmissionResult(
            submission_id=result.submission_id,
            outcome=result.outcome,
            reason=result.reason,
            assertion_id=result.assertion_id,
            assertion_version=result.assertion_version,
            mutation_id=result.mutation_id,
            canonical_owner=result.canonical_owner,
            current_lifecycle=KnowledgeAssertionLifecycle.ACTIVE.value,
        )

    def _resolve_evidence(
        self, observed: Mapping[KnowledgeCreateEvidence, Classification]
    ) -> dict[KnowledgeCreateEvidence, str]:
        """R6 5.1 resolution idiom, in canonical identity order (C4b)."""
        e = knowledge_evidence_refs

        def identity(item: KnowledgeCreateEvidence) -> tuple[str, str, str]:
            key = item.capture_id if item.identity_kind == _CAPTURE else item.relationship_memory_id
            return (item.identity_kind, str(key), item.content_hash)

        distinct = sorted({identity(item) for item in self.request.evidence})
        for kind, key, content_hash in distinct:
            item = next(
                entry
                for entry in self.request.evidence
                if identity(entry) == (kind, key, content_hash)
            )
            values: dict[str, object] = {
                "evidence_ref_id": issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF),
                "identity_kind": kind,
                "content_hash": content_hash,
                "content_origin": kind,
                "source_classification": observed[item].value,
                "created_at": self.at,
                "updated_at": self.at,
            }
            column = "capture_id" if kind == _CAPTURE else "relationship_memory_id"
            values[column] = key
            self.connection.execute(
                pg_insert(e)
                .values(**self._bound(e, values))
                .on_conflict_do_nothing(
                    index_elements=["principal_id", column, "content_hash"],
                    index_where=sql_text(f"identity_kind = '{kind}'"),
                )
            )
        rows = self._identity_rows(distinct)
        needs_raise = any(
            CLASSIFICATION_RANK[observed[item]]
            > CLASSIFICATION_RANK[Classification(rows[identity(item)].source_classification)]
            for item in self.request.evidence
        )
        ids = sorted({row.evidence_ref_id for row in rows.values()})
        locked = (
            select(e.c.evidence_ref_id, e.c.source_classification)
            .where(partition_criterion(e, self.context), e.c.evidence_ref_id.in_(ids))
            .order_by(e.c.evidence_ref_id)
        )
        # Locked once, in the strongest mode this transaction needs (R6 8.1 C4b).
        locked = locked.with_for_update() if needs_raise else locked.with_for_update(read=True)
        current = {
            row.evidence_ref_id: Classification(row.source_classification)
            for row in self.connection.execute(locked)
        }
        if needs_raise:
            for item in self.request.evidence:
                evidence_ref_id = rows[identity(item)].evidence_ref_id
                target = observed[item]
                if CLASSIFICATION_RANK[target] > CLASSIFICATION_RANK[current[evidence_ref_id]]:
                    redact = {"excerpt": None} if target is Classification.RESTRICTED_LOCAL else {}
                    self.connection.execute(
                        update(e)
                        .where(
                            partition_criterion(e, self.context),
                            e.c.evidence_ref_id == evidence_ref_id,
                        )
                        .values(
                            source_classification=target.value,
                            updated_at=case(
                                (e.c.updated_at > self.at, e.c.updated_at), else_=self.at
                            ),
                            **redact,
                        )
                    )
                    current[evidence_ref_id] = target
        return {item: rows[identity(item)].evidence_ref_id for item in self.request.evidence}

    def _identity_rows(
        self, identities: Sequence[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], Row[Any]]:
        e = knowledge_evidence_refs
        found: dict[tuple[str, str, str], Row[Any]] = {}
        for kind, key, content_hash in identities:
            column = e.c.capture_id if kind == _CAPTURE else e.c.relationship_memory_id
            found[(kind, key, content_hash)] = self.connection.execute(
                select(e.c.evidence_ref_id, e.c.source_classification).where(
                    partition_criterion(e, self.context),
                    e.c.identity_kind == kind,
                    column == key,
                    e.c.content_hash == content_hash,
                )
            ).one()
        return found

    def _stored_classes(self, evidence_ref_ids: Iterable[str]) -> list[Classification]:
        ids = sorted(set(evidence_ref_ids))
        if not ids:
            return []
        e = knowledge_evidence_refs
        return [
            Classification(value)
            for value in self.connection.execute(
                select(e.c.source_classification).where(
                    partition_criterion(e, self.context), e.c.evidence_ref_id.in_(ids)
                )
            ).scalars()
        ]

    def _lock_subject(self) -> None:
        locks = knowledge_assertion_subject_locks
        key = {
            "subject_kind": self.request.subject_kind,
            "subject_id": self.request.subject_id,
            "predicate_code": self.request.predicate_code,
        }
        self.connection.execute(
            pg_insert(locks).values(**self._bound(locks, dict(key))).on_conflict_do_nothing()
        )
        self.connection.execute(
            select(locks.c.predicate_code)
            .where(
                partition_criterion(locks, self.context),
                locks.c.subject_kind == key["subject_kind"],
                locks.c.subject_id == key["subject_id"],
                locks.c.predicate_code == key["predicate_code"],
            )
            .order_by(
                locks.c.principal_id,
                locks.c.subject_kind,
                locks.c.subject_id,
                locks.c.predicate_code,
            )
            .with_for_update()
        ).all()

    def lifecycle_of(self, assertion_id: str) -> str | None:
        return self.connection.execute(
            select(knowledge_assertions.c.lifecycle).where(
                partition_criterion(knowledge_assertions, self.context),
                knowledge_assertions.c.assertion_id == assertion_id,
            )
        ).scalar_one_or_none()


# ---- autonomous submit (KLP-WP-04 slice B2) -------------------------------------------
#
# R6 sections 5.1-5.3, 6.1-6.5, 8.1-8.5, 9 and 10.4. One `_AutonomousSubmit` body per
# transaction. The order is the global one: replay pre-read -> C2 immutable reads
# (predicate head carried in the request, route, trigger events + causal snapshot,
# Capture/RM version classes) -> C1 reservation (causal fields already computed) ->
# routed outcomes stop here -> C3 one Entity call -> C4a profile FOR SHARE (re-read
# `disabled_at`) -> C4b canonical-order upsert then ONE sorted lock over the cited
# rows and every external sibling -> C4c one Capture fence -> C5 equivalent
# proposals FOR UPDATE -> C6 the subject lock (even with zero assertions) -> C7/C8
# -> C9 staged events. Nothing acquires C3-C5 or a stronger C4b lock after C6.

_AUTONOMOUS: Final = KnowledgeSubmissionOrigin.AUTONOMOUS_SUBMIT.value
#: The `source_capability` every autonomous-submit event names.
KNOWLEDGE_SUBMIT_CAPABILITY: Final = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT.value
_OPEN_PROPOSAL: Final = (
    KnowledgeProposalState.NEEDS_REVIEW.value,
    KnowledgeProposalState.DEFERRED.value,
    KnowledgeProposalState.UNRESOLVED.value,
)
#: The owner-ref kinds `project.critical_date` routes to (R6 section 13).
_OWNER_TABLES: Final[Mapping[KnowledgeOwnerRefKind, tuple[Table, str]]] = {
    KnowledgeOwnerRefKind.TASK: (tasks, "task_id"),
    KnowledgeOwnerRefKind.COMMITMENT: (commitments, "commitment_id"),
    KnowledgeOwnerRefKind.CONSTRAINT: (project_constraints, "constraint_id"),
    KnowledgeOwnerRefKind.MEETING: (meetings, "meeting_id"),
}
_CRITICAL_DATE: Final = "project.critical_date"
_MAX_LINEAGE_LEVELS: Final = 4


@dataclass(frozen=True, slots=True)
class _StagedMutation:
    """One `kamut_` receipt whose mapped Record Event the repository stages (C9)."""

    assertion_id: str
    mutation_kind: KnowledgeMutationKind
    record_version: int
    mutation_id: str
    classification: Classification


@dataclass(frozen=True, slots=True)
class _TriggerSnapshot:
    """The server-derived causal snapshot of one cited trigger event."""

    trigger_event_id: str
    parent_submission_id: str | None
    parent_root_submission_id: str | None
    parent_depth: int | None


def _result(
    submission_id: str,
    outcome: KnowledgeSubmissionOutcome,
    reason: KnowledgeSubmissionReason,
    *,
    owner: KnowledgeCanonicalOwner | str | None = KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION,
    assertion_id: str | None = None,
    assertion_version: int | None = None,
    mutation_id: str | None = None,
    superseded_assertion_id: str | None = None,
    proposal_id: str | None = None,
    review_case_id: str | None = None,
    routed_record_id: str | None = None,
) -> KnowledgeSubmissionResult:
    return KnowledgeSubmissionResult(
        submission_id=submission_id,
        outcome=outcome.value,
        reason=reason.value,
        assertion_id=assertion_id,
        assertion_version=assertion_version,
        mutation_id=mutation_id,
        canonical_owner=None if owner is None else str(owner),
        current_lifecycle=None,
        superseded_assertion_id=superseded_assertion_id,
        proposal_id=proposal_id,
        review_case_id=review_case_id,
        routed_record_id=routed_record_id,
    )


def _refused(submission_id: str, reason: KnowledgeSubmissionReason) -> KnowledgeSubmissionResult:
    return _result(submission_id, KnowledgeSubmissionOutcome.REFUSED, reason, owner=None)


def _risk_class(predicate: KnowledgePredicate) -> RiskClass:
    """Proposal risk: plan-silent, most restrictive (KLP-WP-04 DEV).

    A consequential predicate or one that needs an operator is `high`; every
    other review candidate is `moderate`. Nothing a client sends moves it.
    """
    if (
        predicate.consequential_class is not KnowledgeConsequentialClass.NONE
        or predicate.review_requirement is KnowledgeReviewRequirement.REQUIRES_OPERATOR
    ):
        return RiskClass.HIGH
    return RiskClass.MODERATE


class _AutonomousSubmit:
    """One autonomous-submit transaction body (R6 sections 6, 8, 9, 10.4)."""

    def __init__(
        self,
        connection: Connection,
        principal_id: str,
        request: KnowledgeSubmitRequest,
        at: datetime,
        *,
        relationship_intelligence_composed: bool,
        relationship_memory_composed: bool,
    ) -> None:
        self.connection = connection
        self.principal_id = principal_id
        self.request = request
        self.predicate: KnowledgePredicate = request.predicate
        self.at = at
        self.context = capture_context(principal_id)
        self.relationship_intelligence_composed = relationship_intelligence_composed
        self.relationship_memory_composed = relationship_memory_composed
        self.staged: list[_StagedMutation] = []

    def _bound(self, table: Table, values: dict[str, object]) -> dict[str, object]:
        return principal_bound_values(values, table, self.context)

    @property
    def _floor(self) -> Classification:
        """The intake floor: `synthetic_test` only for a synthetic profile (R6 5.1, 5.3)."""
        return (
            Classification.SYNTHETIC_TEST
            if self.request.origin_is_synthetic
            else Classification.PRIVATE_LOCAL
        )

    # -- C1: the autonomous-candidate arbiter -----------------------------------

    def winner(self, *, remote: bool) -> KnowledgeSubmissionResult | None:
        """The stored result of this candidate identity, replayed, or `None` (R6 6.1)."""
        s = knowledge_assertion_submissions
        request = self.request
        row = self.connection.execute(
            select(s).where(
                partition_criterion(s, self.context),
                s.c.origin == _AUTONOMOUS,
                s.c.authenticated_client_id == request.authenticated_client_id,
                s.c.source_profile_id == request.source_profile_id,
                s.c.external_run_id == request.external_run_id,
                s.c.external_candidate_id == request.external_candidate_id,
            )
        ).one_or_none()
        if row is None:
            return None
        if row.request_digest != request.request_digest:
            raise KnowledgeIdempotencyConflictError("the candidate is bound to another request")
        return _stored_result(self.connection, self.principal_id, row, remote=remote)

    def _insert_submission(
        self,
        submission_id: str,
        *,
        depth: int | None,
        root: str | None,
        refused: KnowledgeSubmissionReason | None = None,
    ) -> bool:
        request = self.request
        values: dict[str, object] = {
            "submission_id": submission_id,
            "origin": _AUTONOMOUS,
            "authenticated_client_id": request.authenticated_client_id,
            "source_profile_id": request.source_profile_id,
            "scope_digest": request.scope_digest,
            "origin_is_synthetic": request.origin_is_synthetic,
            "external_run_id": request.external_run_id,
            "external_candidate_id": request.external_candidate_id,
            "subject_kind": request.subject_kind,
            "subject_id": request.subject_id,
            "predicate_code": self.predicate.predicate_code,
            "owner_ref_kind": request.owner_ref_kind,
            "owner_ref_id": request.owner_ref_id,
            "request_digest": request.request_digest,
            "causal_depth": depth,
            "causal_root_submission_id": root,
            "submission_state": "reserved",
            "created_at": self.at,
        }
        if refused is not None:
            result = _refused(submission_id, refused)
            values.update(
                submission_state="completed",
                outcome=result.outcome,
                reason=result.reason,
                result_digest=_result_digest(result, autonomous=True),
                completed_at=self.at,
            )
        statement = (
            pg_insert(knowledge_assertion_submissions)
            .values(**self._bound(knowledge_assertion_submissions, values))
            .on_conflict_do_nothing(
                index_elements=[
                    "principal_id",
                    "authenticated_client_id",
                    "source_profile_id",
                    "external_run_id",
                    "external_candidate_id",
                ],
                index_where=sql_text(f"origin = '{_AUTONOMOUS}'"),
            )
            .returning(knowledge_assertion_submissions.c.submission_id)
        )
        return self.connection.execute(statement).scalar_one_or_none() is not None

    def _complete(self, result: KnowledgeSubmissionResult) -> KnowledgeSubmissionResult:
        s = knowledge_assertion_submissions
        done = self.connection.execute(
            update(s)
            .where(
                partition_criterion(s, self.context),
                s.c.submission_id == result.submission_id,
                s.c.submission_state == "reserved",
            )
            .values(
                submission_state="completed",
                outcome=result.outcome,
                reason=result.reason,
                result_assertion_id=result.assertion_id,
                result_assertion_version=result.assertion_version,
                result_mutation_id=result.mutation_id,
                result_superseded_assertion_id=result.superseded_assertion_id,
                result_proposal_id=result.proposal_id,
                result_review_case_id=result.review_case_id,
                result_canonical_owner=result.canonical_owner,
                result_routed_record_id=result.routed_record_id,
                result_digest=_result_digest(result, autonomous=True),
                completed_at=self.at,
            )
        )
        if done.rowcount != 1:
            raise RepositoryFailureError("the reservation was not held")
        return result

    # -- C2: triggers and the causal position (R6 9.1) ------------------------------

    def _triggers(self) -> list[_TriggerSnapshot]:
        """Each cited event, owned and visible, with its Knowledge parent (if any).

        A Knowledge trigger resolves `source_receipt_id = kamut_` ->
        `mutation.submission_id`; a NULL submission (server maintenance) or a
        non-Knowledge event contributes no parent. An absent, foreign or
        remotely withheld event is one `KnowledgeTriggerNotFoundError`.
        """
        ids = list(self.request.trigger_event_ids)
        if not ids:
            return []
        # The feed module owns the feed tables; imported here, not at module
        # level, because it imports this module's withholding predicate.
        from my_pa.infrastructure.persistence.record_events import (
            trigger_receipts,
        )

        rows = trigger_receipts(self.connection, self.principal_id, ids)
        snapshots: list[_TriggerSnapshot] = []
        m, s = knowledge_assertion_mutations, knowledge_assertion_submissions
        for event_id in sorted(ids):
            row = rows.get(event_id)
            if row is None or not row.visible:
                raise KnowledgeTriggerNotFoundError("a cited trigger event is not this caller's")
            parent = None
            receipt = row.source_receipt_id
            if row.record_family == RecordEventFamily.KNOWLEDGE_ASSERTION.value and (
                isinstance(receipt, str)
                and receipt.startswith(f"{IdKind.KNOWLEDGE_ASSERTION_MUTATION.value}_")
            ):
                parent = self.connection.execute(
                    select(s.c.submission_id, s.c.causal_root_submission_id, s.c.causal_depth)
                    .select_from(
                        m.join(
                            s,
                            and_(
                                matching_partition_criterion(s, m),
                                s.c.submission_id == m.c.submission_id,
                            ),
                        )
                    )
                    .where(
                        partition_criterion(m, self.context),
                        partition_criterion(s, self.context),
                        m.c.mutation_id == receipt,
                    )
                ).one_or_none()
            if parent is None or parent.causal_depth is None:
                snapshots.append(_TriggerSnapshot(event_id, None, None, None))
            else:
                snapshots.append(
                    _TriggerSnapshot(
                        event_id,
                        parent.submission_id,
                        parent.causal_root_submission_id,
                        int(parent.causal_depth),
                    )
                )
        return snapshots

    def _ancestor_keys(self, parents: Sequence[str]) -> set[CausalKey]:
        """The repeat keys of the parents and their ancestors, at most 4 levels (R6 9.1(d))."""
        s, t = knowledge_assertion_submissions, knowledge_submission_trigger_events
        keys: set[CausalKey] = set()
        frontier = sorted(set(parents))
        seen: set[str] = set()
        for _level in range(_MAX_LINEAGE_LEVELS + 1):
            frontier = [submission for submission in frontier if submission not in seen]
            if not frontier:
                break
            seen.update(frontier)
            for row in self.connection.execute(
                select(
                    s.c.authenticated_client_id,
                    s.c.subject_kind,
                    s.c.subject_id,
                    s.c.predicate_code,
                ).where(partition_criterion(s, self.context), s.c.submission_id.in_(frontier))
            ):
                keys.add(
                    CausalKey(
                        row.authenticated_client_id,
                        row.subject_kind,
                        row.subject_id,
                        row.predicate_code,
                    )
                )
            frontier = sorted(
                {
                    str(parent)
                    for parent in self.connection.execute(
                        select(t.c.parent_submission_id).where(
                            partition_criterion(t, self.context),
                            t.c.submission_id.in_(frontier),
                            t.c.parent_submission_id.is_not(None),
                        )
                    ).scalars()
                }
            )
        return keys

    def _causal(
        self, submission_id: str, snapshots: Sequence[_TriggerSnapshot]
    ) -> CausalPosition | CausalRefusal:
        parents = [
            CausalParent(str(item.parent_root_submission_id), int(item.parent_depth))
            for item in snapshots
            if item.parent_submission_id is not None and item.parent_depth is not None
        ]
        ancestors = self._ancestor_keys(
            [str(item.parent_submission_id) for item in snapshots if item.parent_submission_id]
        )
        return resolve_causal_position(
            own_submission_id=submission_id,
            own_key=CausalKey(
                self.request.authenticated_client_id,
                self.request.subject_kind,
                self.request.subject_id,
                self.predicate.predicate_code,
            ),
            parents=parents,
            ancestor_keys=ancestors,
        )

    def _rate_exceeded(self) -> bool:
        """R6 9.3: >= 16 admitted submissions of this client/run/subject. Unlocked, soft."""
        s = knowledge_assertion_submissions
        count = self.connection.execute(
            select(func.count()).where(
                partition_criterion(s, self.context),
                s.c.origin == _AUTONOMOUS,
                s.c.authenticated_client_id == self.request.authenticated_client_id,
                s.c.external_run_id == self.request.external_run_id,
                s.c.subject_kind == self.request.subject_kind,
                s.c.subject_id == self.request.subject_id,
                s.c.predicate_code == self.predicate.predicate_code,
                s.c.submission_state == "completed",
                s.c.outcome.in_(sorted(outcome.value for outcome in CAUSAL_RATE_COUNTED_OUTCOMES)),
            )
        ).scalar_one()
        return int(count) >= CAUSAL_RATE_LIMIT

    def _insert_snapshots(self, submission_id: str, snapshots: Sequence[_TriggerSnapshot]) -> None:
        for item in snapshots:
            self.connection.execute(
                insert(knowledge_submission_trigger_events).values(
                    **self._bound(
                        knowledge_submission_trigger_events,
                        {
                            "submission_id": submission_id,
                            "trigger_event_id": item.trigger_event_id,
                            "parent_submission_id": item.parent_submission_id,
                            "parent_causal_root_submission_id": item.parent_root_submission_id,
                            "parent_causal_depth": item.parent_depth,
                            "created_at": self.at,
                        },
                    )
                )
            )

    # -- C2: the route (R6 8.5 / section 13) -------------------------------------

    def _route(self, submission_id: str) -> KnowledgeSubmissionResult | None:
        """The DOMAIN_OWNED completion (`decide_domain_route`), or `None` (R6 8.5, 13)."""
        request = self.request
        kind = (
            None
            if request.owner_ref_kind is None
            else KnowledgeOwnerRefKind(request.owner_ref_kind)
        )
        resolves = False
        if kind is not None and self.predicate.predicate_code == _CRITICAL_DATE:
            table, column = _OWNER_TABLES[kind]
            resolves = (
                self.connection.execute(
                    select(table.c[column]).where(
                        partition_criterion(table, self.context),
                        table.c[column] == request.owner_ref_id,
                    )
                ).scalar_one_or_none()
                is not None
            )
        route = decide_domain_route(
            self.predicate,
            owner_ref_kind=kind,
            owner_ref_id=request.owner_ref_id,
            owner_ref_resolves=resolves,
        )
        if route is None:
            return None
        return _result(
            submission_id,
            route.outcome,
            route.reason,
            owner=route.canonical_owner,
            routed_record_id=route.routed_record_id,
        )

    # -- C2 / C3: subject and profile -----------------------------------------------

    def _subject(self, *, lock: bool) -> SubjectResolution:
        kind = self.request.subject_kind
        subject_id = self.request.subject_id
        if kind == KnowledgeSubjectKind.PRINCIPAL.value:
            return (
                SubjectResolution.CANONICAL
                if subject_id == self.principal_id
                else SubjectResolution.UNRESOLVED
            )
        if kind == KnowledgeSubjectKind.PROJECT.value:
            found = self.connection.execute(
                select(projects.c.project_id).where(
                    partition_criterion(projects, self.context),
                    projects.c.project_id == subject_id,
                )
            ).scalar_one_or_none()
            return SubjectResolution.CANONICAL if found else SubjectResolution.UNRESOLVED
        if kind == KnowledgeSubjectKind.ENTITY.value:
            if not self.relationship_intelligence_composed:
                return SubjectResolution.PLANE_NOT_COMPOSED
            if lock:
                # C3: the one call over the complete Entity set (R6 8.1, 8.2).
                lock_entity_mutation_scopes(self.connection, self.principal_id, (subject_id,))
            row = self.connection.execute(
                select(entities.c.entity_type, entities.c.status).where(
                    partition_criterion(entities, self.context),
                    entities.c.entity_id == subject_id,
                )
            ).one_or_none()
            if row is None or row.status != EntityStatus.ACTIVE.value:
                return SubjectResolution.UNRESOLVED
            if EntityType(row.entity_type) not in self.predicate.allowed_entity_types:
                return SubjectResolution.ENTITY_TYPE_NOT_ALLOWED
            return SubjectResolution.CANONICAL
        return SubjectResolution.UNRESOLVED

    def _profile(self, *, lock: bool) -> Row[Any]:
        """The bound profile row; C4a `FOR SHARE` when `lock` (re-read `disabled_at`)."""
        p = knowledge_discovery_source_profiles
        statement = select(
            p.c.source_profile_id,
            p.c.origin_system,
            p.c.authority_ceiling,
            p.c.direct_admission_enabled,
            p.c.read_only_proof_state,
            p.c.is_synthetic,
            p.c.disabled_at,
        ).where(
            partition_criterion(p, self.context),
            p.c.source_profile_id == self.request.source_profile_id,
            p.c.authenticated_client_id == self.request.authenticated_client_id,
        )
        if lock:
            statement = statement.with_for_update(read=True)
        row = self.connection.execute(statement).one_or_none()
        if row is None:
            raise KnowledgeSourceProfileUnboundError("the profile is not this client's")
        return row

    # -- evidence ----------------------------------------------------------------

    def _product_items(self) -> list[KnowledgeSubmitEvidence]:
        return [item for item in self.request.evidence if item.identity_kind != _EXTERNAL]

    def _external_items(self) -> list[KnowledgeSubmitEvidence]:
        return [item for item in self.request.evidence if item.identity_kind == _EXTERNAL]

    def _captures(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(item.capture_id)
                    for item in self.request.evidence
                    if item.identity_kind == _CAPTURE
                }
            )
        )

    def _identities(self) -> list[tuple[str, ...]]:
        """Distinct cited identities in canonical order (R6 5.1, KLP-R6V-002)."""
        return sorted({item.identity for item in self.request.evidence})

    def _identity_criterion(self, identity: tuple[str, ...]) -> ColumnElement[bool]:
        e = knowledge_evidence_refs
        kind = identity[0]
        if kind == _EXTERNAL:
            _kind, profile, object_id, version, content_hash = identity
            return and_(
                e.c.identity_kind == _EXTERNAL,
                e.c.source_profile_id == profile,
                e.c.external_object_id == object_id,
                func.coalesce(e.c.external_version_id, "") == version,
                e.c.content_hash == content_hash,
            )
        _kind, key, content_hash = identity
        column = e.c.capture_id if kind == _CAPTURE else e.c.relationship_memory_id
        return and_(e.c.identity_kind == kind, column == key, e.c.content_hash == content_hash)

    def _existing_rows(self) -> dict[tuple[str, ...], Row[Any]]:
        """Already-stored rows of the cited identities (unlocked C2 read)."""
        e = knowledge_evidence_refs
        found: dict[tuple[str, ...], Row[Any]] = {}
        for identity in self._identities():
            row = self.connection.execute(
                select(
                    e.c.evidence_ref_id,
                    e.c.source_classification,
                    e.c.availability_state,
                    e.c.availability_revalidation_pending,
                ).where(partition_criterion(e, self.context), self._identity_criterion(identity))
            ).one_or_none()
            if row is not None:
                found[identity] = row
        return found

    def _sibling_rows(self) -> dict[str, list[Row[Any]]]:
        """Every stored external row of a cited object under the profile's origin system.

        Keyed by `external_object_id`: same Principal, same object, any profile
        of the same `origin_system`, any version (R6 5.1, KLP-R6V-005/202).
        """
        objects = sorted({str(item.external_object_id) for item in self._external_items()})
        if not objects:
            return {}
        e, p = knowledge_evidence_refs, knowledge_discovery_source_profiles
        rows = self.connection.execute(
            select(e.c.evidence_ref_id, e.c.external_object_id, e.c.source_classification)
            .select_from(
                e.join(
                    p,
                    and_(
                        matching_partition_criterion(p, e),
                        p.c.source_profile_id == e.c.source_profile_id,
                    ),
                )
            )
            .where(
                partition_criterion(e, self.context),
                partition_criterion(p, self.context),
                e.c.identity_kind == _EXTERNAL,
                e.c.external_object_id.in_(objects),
                p.c.origin_system == self.request.origin_system,
            )
        ).all()
        grouped: dict[str, list[Row[Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.external_object_id), []).append(row)
        return grouped

    def _observed(
        self,
        product: Mapping[tuple[str, ...], Classification],
        siblings: Mapping[str, Sequence[Row[Any]]],
    ) -> dict[tuple[str, ...], Classification]:
        """The observed class of each cited identity (R6 5.1 step 3).

        External: rank-max(profile floor, sibling max); product shapes: the
        rank-max over every version (read at C2). Callers declare no class.
        """
        observed = dict(product)
        for item in self._external_items():
            observed[item.identity] = classification_max(
                self._floor,
                *(
                    Classification(row.source_classification)
                    for row in siblings.get(str(item.external_object_id), ())
                ),
            )
        return observed

    def _resolve_evidence(
        self, product: Mapping[tuple[str, ...], Classification]
    ) -> dict[tuple[str, ...], str]:
        """C4b: canonical-order upsert, then ONE sorted lock over cited rows and siblings.

        KLP-R6V-202: every existing sibling row is in the one sorted SELECT, so a
        concurrent restriction of any sibling is waited for *before* this
        transaction decides its own rows' class; the sibling max is recomputed
        under the lock and a restricted object raises (and redacts) this
        transaction's own new row in the same transaction. KLP-R6V-201: every
        raise to `restricted_local` nulls the excerpt in the same UPDATE. The
        mode is `FOR UPDATE` whenever an observed class could exceed a stored
        one (any sibling exists, or a raise is already due), else `FOR SHARE`.
        """
        e = knowledge_evidence_refs
        siblings = self._sibling_rows()
        observed = self._observed(product, siblings)
        by_identity = {item.identity: item for item in self.request.evidence}
        for identity in self._identities():
            item = by_identity[identity]
            target = observed[identity]
            values: dict[str, object] = {
                "evidence_ref_id": issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF),
                "identity_kind": item.identity_kind,
                "content_hash": item.content_hash,
                "source_classification": target.value,
                "created_at": self.at,
                "updated_at": self.at,
            }
            if item.identity_kind == _EXTERNAL:
                values.update(
                    source_profile_id=item.source_profile_id,
                    source_is_synthetic=self.request.origin_is_synthetic,
                    external_object_id=item.external_object_id,
                    external_version_id=item.external_version_id,
                    content_origin=(
                        KnowledgeContentOrigin.SYNTHETIC_SOURCE.value
                        if self.request.origin_is_synthetic
                        else KnowledgeContentOrigin.EXTERNAL_SOURCE.value
                    ),
                    excerpt_sha256=item.excerpt_sha256,
                    # KLP-R6V-103: a new row of an already-restricted object is born
                    # restricted with no excerpt at rest.
                    excerpt=None if target is Classification.RESTRICTED_LOCAL else item.excerpt,
                )
                statement = (
                    pg_insert(e)
                    .values(**self._bound(e, values))
                    .on_conflict_do_nothing(
                        index_elements=[
                            e.c.principal_id,
                            e.c.source_profile_id,
                            e.c.external_object_id,
                            # A literal '' (never a bound parameter): a server-side
                            # prepared statement cannot infer the expression index
                            # from `COALESCE(col, $n)`.
                            func.coalesce(e.c.external_version_id, literal_column("''")),
                            e.c.content_hash,
                        ],
                        index_where=sql_text(f"identity_kind = '{_EXTERNAL}'"),
                    )
                )
            else:
                column = (
                    "capture_id" if item.identity_kind == _CAPTURE else "relationship_memory_id"
                )
                values[column] = item.capture_id or item.relationship_memory_id
                values["content_origin"] = item.identity_kind
                statement = (
                    pg_insert(e)
                    .values(**self._bound(e, values))
                    .on_conflict_do_nothing(
                        index_elements=["principal_id", column, "content_hash"],
                        index_where=sql_text(f"identity_kind = '{item.identity_kind}'"),
                    )
                )
            self.connection.execute(statement)
        own = self._existing_rows()
        sibling_ids = {row.evidence_ref_id for rows in siblings.values() for row in rows}
        ids = sorted({row.evidence_ref_id for row in own.values()} | sibling_ids)
        needs_raise = bool(sibling_ids) or any(
            CLASSIFICATION_RANK[observed[identity]]
            > CLASSIFICATION_RANK[Classification(row.source_classification)]
            for identity, row in own.items()
        )
        locked = (
            select(
                e.c.evidence_ref_id,
                e.c.identity_kind,
                e.c.external_object_id,
                e.c.source_classification,
            )
            .where(partition_criterion(e, self.context), e.c.evidence_ref_id.in_(ids))
            .order_by(e.c.evidence_ref_id)
        )
        locked = locked.with_for_update() if needs_raise else locked.with_for_update(read=True)
        current = {row.evidence_ref_id: row for row in self.connection.execute(locked)}
        # Recompute the sibling max under the lock (KLP-R6V-202), by object.
        object_max: dict[str, Classification] = {}
        for row in current.values():
            if row.identity_kind == _EXTERNAL and row.evidence_ref_id in sibling_ids:
                key = str(row.external_object_id)
                object_max[key] = classification_max(
                    object_max.get(key, Classification.SYNTHETIC_TEST),
                    Classification(row.source_classification),
                )
        resolved: dict[tuple[str, ...], str] = {}
        for identity, row in own.items():
            item = by_identity[identity]
            target = observed[identity]
            if item.identity_kind == _EXTERNAL:
                target = classification_max(
                    self._floor,
                    object_max.get(str(item.external_object_id), self._floor),
                )
            stored = Classification(current[row.evidence_ref_id].source_classification)
            if CLASSIFICATION_RANK[target] > CLASSIFICATION_RANK[stored]:
                if not needs_raise:  # pragma: no cover - the mode guard above
                    raise RepositoryFailureError("an evidence lock would be upgraded")
                redact = {"excerpt": None} if target is Classification.RESTRICTED_LOCAL else {}
                self.connection.execute(
                    update(e)
                    .where(
                        partition_criterion(e, self.context),
                        e.c.evidence_ref_id == row.evidence_ref_id,
                    )
                    .values(
                        source_classification=target.value,
                        updated_at=_not_before(e.c.updated_at, self.at),
                        **redact,
                    )
                )
            resolved[identity] = row.evidence_ref_id
        return resolved

    def _stored_classes(self, evidence_ref_ids: Iterable[str]) -> list[Classification]:
        ids = sorted(set(evidence_ref_ids))
        if not ids:
            return []
        e = knowledge_evidence_refs
        return [
            Classification(value)
            for value in self.connection.execute(
                select(e.c.source_classification).where(
                    partition_criterion(e, self.context), e.c.evidence_ref_id.in_(ids)
                )
            ).scalars()
        ]

    def _admission_evidence(
        self, existing: Mapping[tuple[str, ...], Row[Any]]
    ) -> tuple[AdmissionEvidence, ...]:
        """Shape-only facts (KLP-AC-068/069): no excerpt, no retrieved_at, no class."""
        facts: list[AdmissionEvidence] = []
        for item in self.request.evidence:
            kind = KnowledgeEvidenceIdentityKind(item.identity_kind)
            role = KnowledgeEvidenceRole(item.role)
            if kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT:
                stored = existing.get(item.identity)
                available = stored is None or (
                    stored.availability_state == KnowledgeEvidenceAvailability.AVAILABLE.value
                    and not stored.availability_revalidation_pending
                )
                facts.append(
                    AdmissionEvidence(
                        identity_kind=kind,
                        role=role,
                        content_hash=item.content_hash,
                        source_profile_id=item.source_profile_id,
                        origin_system=KnowledgeOriginSystem(self.request.origin_system),
                        external_object_id=item.external_object_id,
                        external_version_id=item.external_version_id,
                        available=available,
                    )
                )
            else:
                facts.append(
                    AdmissionEvidence(
                        identity_kind=kind,
                        role=role,
                        content_hash=item.content_hash,
                        product_record_id=item.capture_id or item.relationship_memory_id,
                    )
                )
        return tuple(facts)

    # -- C2 / C6 reads of the subject key --------------------------------------------

    def _live_duplicate(self) -> Row[Any] | None:
        a = knowledge_assertions
        return self.connection.execute(
            select(a.c.assertion_id, a.c.version, a.c.classification).where(
                partition_criterion(a, self.context),
                a.c.fingerprint_version == 1,
                a.c.assertion_fingerprint == self.request.assertion_fingerprint,
                a.c.lifecycle.in_(_LIVE),
            )
        ).one_or_none()

    def _slot_holder(self) -> Row[Any] | None:
        """The live single-current fact of this key, any predicate version (KLP-AC-029)."""
        if self.predicate.cardinality is not KnowledgeCardinality.SINGLE_CURRENT:
            return None
        a = knowledge_assertions
        return self.connection.execute(
            select(
                a.c.assertion_id,
                a.c.version,
                a.c.effective_from,
                a.c.classification,
                a.c.assertion_fingerprint,
            ).where(
                partition_criterion(a, self.context),
                a.c.subject_kind == self.request.subject_kind,
                a.c.subject_id == self.request.subject_id,
                a.c.predicate_code == self.predicate.predicate_code,
                a.c.cardinality == KnowledgeCardinality.SINGLE_CURRENT.value,
                a.c.lifecycle.in_(_LIVE),
            )
        ).one_or_none()

    def _current_fact(self, holder: Row[Any] | None, live: Row[Any] | None) -> CurrentFact | None:
        """The live different-value slot holder as a policy fact (`None`: no such holder)."""
        if holder is None or (live is not None and holder.assertion_id == live.assertion_id):
            return None
        return CurrentFact(
            assertion_id=holder.assertion_id,
            effective_from=holder.effective_from,
            unresolved_counterevidence=self._has_counterevidence(holder.assertion_id),
        )

    def _has_counterevidence(self, assertion_id: str) -> bool:
        return _has_counterevidence(self.connection, self.context, assertion_id)

    def _equivalent_proposals(self, *, lock: bool, ids: Sequence[str] = ()) -> list[Row[Any]]:
        """Open proposals with this fingerprint; C5 `FOR UPDATE` by proposal_id when `lock`."""
        p = knowledge_assertion_proposals
        criteria: list[ColumnElement[bool]] = [partition_criterion(p, self.context)]
        if lock:
            criteria.append(p.c.proposal_id.in_(sorted(ids)))
        else:
            criteria.extend(
                [
                    p.c.fingerprint_version == 1,
                    p.c.proposal_fingerprint == self.request.assertion_fingerprint,
                    p.c.state.in_(_OPEN_PROPOSAL),
                ]
            )
        statement = select(p.c.proposal_id, p.c.review_case_id, p.c.state).where(*criteria)
        statement = statement.order_by(p.c.proposal_id)
        if lock:
            statement = statement.with_for_update()
        return list(self.connection.execute(statement).all())

    def _lock_subject(self) -> None:
        """C6: upsert the key, then one sorted `FOR UPDATE` (KLP-AC-091)."""
        locks = knowledge_assertion_subject_locks
        key = {
            "subject_kind": self.request.subject_kind,
            "subject_id": self.request.subject_id,
            "predicate_code": self.predicate.predicate_code,
        }
        self.connection.execute(
            pg_insert(locks).values(**self._bound(locks, dict(key))).on_conflict_do_nothing()
        )
        self.connection.execute(
            select(locks.c.predicate_code)
            .where(
                partition_criterion(locks, self.context),
                locks.c.subject_kind == key["subject_kind"],
                locks.c.subject_id == key["subject_id"],
                locks.c.predicate_code == key["predicate_code"],
            )
            .order_by(
                locks.c.principal_id,
                locks.c.subject_kind,
                locks.c.subject_id,
                locks.c.predicate_code,
            )
            .with_for_update()
        ).all()

    # -- the transaction ------------------------------------------------------------

    def run(
        self, verify: Callable[[], dict[tuple[str, ...], Classification]]
    ) -> KnowledgeSubmissionResult:
        replay = self.winner(remote=True)
        if replay is not None:
            return replay
        # C2: immutable reads. Capture/RM version classes, then triggers + causality.
        product = verify()
        snapshots = self._triggers()
        submission_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_SUBMISSION)
        position = self._causal(submission_id, snapshots)
        if isinstance(position, CausalRefusal):
            # R6 9.1(c): born completed `refused`, NULL causal fields.
            if not self._insert_submission(
                submission_id, depth=None, root=None, refused=position.reason
            ):
                return self._lost_race()
            self._insert_snapshots(submission_id, snapshots)
            return _refused(submission_id, position.reason)
        profile = self._profile(lock=False)
        route = self._route(submission_id)
        rate_exceeded = self._rate_exceeded()
        # C1: the reservation, causal fields already computed (R6 9.1(a)).
        if not self._insert_submission(
            submission_id, depth=position.depth, root=position.root_submission_id
        ):
            return self._lost_race()
        self._insert_snapshots(submission_id, snapshots)
        if profile.disabled_at is not None:
            return self._complete(
                _refused(submission_id, KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE)
            )
        if rate_exceeded:
            return self._complete(
                _refused(submission_id, KnowledgeSubmissionReason.CAUSAL_RATE_EXCEEDED)
            )
        if route is not None:
            # A routed submission takes C1 and C2 only (R6 8.5, KLP-AC-128).
            return self._complete(route)
        return self._knowledge(submission_id, product)

    def _lost_race(self) -> KnowledgeSubmissionResult:
        winner = self.winner(remote=True)
        if winner is None:
            raise RepositoryFailureError("the candidate's winner could not be read")
        return winner

    def _knowledge(
        self, submission_id: str, product: Mapping[tuple[str, ...], Classification]
    ) -> KnowledgeSubmissionResult:
        # C3: the Entity mutation scope (one call), the subject re-read under it.
        subject = self._subject(lock=True)
        # C4a: the profile FOR SHARE, `disabled_at` re-read under the lock.
        profile = self._profile(lock=True)
        if profile.disabled_at is not None:
            return self._complete(
                _refused(submission_id, KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE)
            )
        existing = self._existing_rows()
        live = self._live_duplicate()
        holder = self._slot_holder()
        current = self._current_fact(holder, live)
        archived = any(
            state is CaptureLifecycleState.ARCHIVED
            for state in capture_lifecycle_states(
                self.connection, self._captures(), context=self.context
            ).values()
        )
        facts = DirectAdmissionFacts(
            predicate=self.predicate,
            profile=SourceProfileFacts(
                source_profile_id=profile.source_profile_id,
                origin_system=KnowledgeOriginSystem(profile.origin_system),
                authority_ceiling=KnowledgeEvidenceAuthority(profile.authority_ceiling),
                direct_admission_enabled=bool(profile.direct_admission_enabled),
                read_only_proof_state=KnowledgeReadOnlyProofState(profile.read_only_proof_state),
                is_synthetic=bool(profile.is_synthetic),
                disabled=False,
            ),
            subject=subject,
            evidence=self._admission_evidence(existing),
            candidate_effective_from=self.request.effective_from,
            now=self.at,
            current=current,
            capture_archived=archived,
        )
        decision = decide_direct_admission(facts)
        if decision.path is AdmissionPath.REFUSE:
            assert decision.reason is not None  # noqa: S101 - a refusal always names one
            return self._complete(_refused(submission_id, decision.reason))
        if (
            live is not None
            and self._nothing_new(live.assertion_id, existing)
            and not self._raise_due(product, existing)
        ):
            # Exact live duplicate citing nothing new: only this row is written.
            result = self._complete(
                _result(
                    submission_id,
                    KnowledgeSubmissionOutcome.DUPLICATE_EXISTING,
                    KnowledgeSubmissionReason.EXACT_DUPLICATE,
                    assertion_id=live.assertion_id,
                    assertion_version=int(live.version),
                )
            )
            return result
        seen = self._equivalent_proposals(lock=False)
        # C4b: canonical-order upsert, then one sorted lock (siblings included).
        evidence_ids = self._resolve_evidence(product)
        # C4c: exactly one publication fence over the cited Capture roots.
        _capture_fence(self.connection, self.context, self._captures())
        # C5: the equivalent proposals seen at C2, sorted, FOR UPDATE.
        locked = (
            self._equivalent_proposals(lock=True, ids=[row.proposal_id for row in seen])
            if seen
            else []
        )
        # C6: the subject lock, even when no assertion exists (KLP-AC-091).
        self._lock_subject()
        # Re-decide on the facts as they stand under the locks, never the stale C2
        # reads: the cited rows are locked since C4b (availability: an ingress or
        # drain that committed while this transaction waited is decided on) and the
        # (subject, predicate) key since C6 (the slot holder, its effective_from and
        # its counterevidence: an enrich linking counterevidence commits under C6,
        # KLP-AC-031). The stored class needs no re-check: the policy never reads it
        # and the writers read it under the lock (`_classification`). The other
        # facts are immutable or held since C3/C4a (fix round 2 audit, SLICE-LOG).
        decision = decide_direct_admission(
            replace(
                facts,
                evidence=self._admission_evidence(self._existing_rows()),
                current=self._current_fact(self._slot_holder(), self._live_duplicate()),
            )
        )
        if decision.path is AdmissionPath.REFUSE:  # pragma: no cover - evidence never refuses
            assert decision.reason is not None  # noqa: S101 - a refusal always names one
            return self._complete(_refused(submission_id, decision.reason))
        return self._decide_under_lock(submission_id, decision, live, holder, locked, evidence_ids)

    def _raise_due(
        self,
        product: Mapping[tuple[str, ...], Classification],
        existing: Mapping[tuple[str, ...], Row[Any]],
    ) -> bool:
        """Whether a cited row's observed class now exceeds its stored class (R6 5.1 step 3).

        A re-observation of a row whose object was restricted since must go
        through C4b to raise (and redact, KLP-R6V-201) it, even for a duplicate.
        """
        observed = self._observed(product, self._sibling_rows())
        return any(
            CLASSIFICATION_RANK[observed[identity]]
            > CLASSIFICATION_RANK[Classification(row.source_classification)]
            for identity, row in existing.items()
        )

    def _nothing_new(self, assertion_id: str, existing: Mapping[tuple[str, ...], Row[Any]]) -> bool:
        """Every cited identity is already linked to `assertion_id` in the same role."""
        if any(item.identity not in existing for item in self.request.evidence):
            return False
        links = knowledge_assertion_evidence_links
        linked = {
            (row.evidence_ref_id, row.evidence_role)
            for row in self.connection.execute(
                select(links.c.evidence_ref_id, links.c.evidence_role).where(
                    partition_criterion(links, self.context),
                    links.c.assertion_id == assertion_id,
                )
            )
        }
        return all(
            (existing[item.identity].evidence_ref_id, item.role) in linked
            for item in self.request.evidence
        )

    def _decide_under_lock(
        self,
        submission_id: str,
        decision: AdmissionDecision,
        live: Row[Any] | None,
        holder: Row[Any] | None,
        locked: Sequence[Row[Any]],
        evidence_ids: Mapping[tuple[str, ...], str],
    ) -> KnowledgeSubmissionResult:
        accepted = any(row.state == KnowledgeProposalState.ACCEPTED.value for row in locked)
        live_now = self._live_duplicate()
        appeared = live_now is not None and (
            live is None or live_now.assertion_id != live.assertion_id
        )
        # Race 14 (a): an equivalent proposal accepted while we waited at C5 is the
        # one way a live duplicate may appear under the lock.
        if appeared and not accepted:
            raise KnowledgeConcurrentDuplicateError("a concurrent write took this fact")
        holder_now = self._slot_holder()
        holder_id = None if holder is None else holder.assertion_id
        holder_now_id = None if holder_now is None else holder_now.assertion_id
        if holder_now_id != holder_id and not (
            accepted and live_now is not None and holder_now_id == live_now.assertion_id
        ):
            raise KnowledgeConcurrentDuplicateError("the current slot changed under the lock")
        locked_ids = {row.proposal_id for row in locked}
        open_now = self._equivalent_proposals(lock=False)
        if any(row.proposal_id not in locked_ids for row in open_now):
            # Race 14 (b): an equivalent open proposal first seen after C6.
            raise KnowledgeConcurrentDuplicateError("an equivalent proposal appeared late")
        self._write_submission_evidence(submission_id, evidence_ids)
        if live_now is not None:
            return self._enrich(submission_id, live_now, evidence_ids)
        still_open = [row for row in locked if row.state in _OPEN_PROPOSAL]
        if still_open:
            older = still_open[0]
            # KLP-AC-151: the older proposal is never mutated.
            return self._complete(
                _result(
                    submission_id,
                    KnowledgeSubmissionOutcome.DUPLICATE_PENDING_REVIEW,
                    KnowledgeSubmissionReason.PENDING_REVIEW_EXISTS,
                    proposal_id=older.proposal_id,
                    review_case_id=older.review_case_id,
                )
            )
        if decision.path is AdmissionPath.REVIEW:
            assert decision.reason is not None  # noqa: S101 - a review path names its reason
            return self._propose(submission_id, decision.reason, evidence_ids)
        if decision.path is AdmissionPath.DIRECT_SUPERSEDE:
            assert holder_now is not None  # noqa: S101 - supersession needs the holder
            return self._supersede(submission_id, holder_now, evidence_ids)
        return self._create(submission_id, evidence_ids, predecessor=None)

    # -- C7 / C8 writers --------------------------------------------------------------

    def _write_submission_evidence(
        self, submission_id: str, evidence_ids: Mapping[tuple[str, ...], str]
    ) -> None:
        for item in sorted(
            self.request.evidence, key=lambda entry: (evidence_ids[entry.identity], entry.role)
        ):
            self.connection.execute(
                insert(knowledge_submission_evidence).values(
                    **self._bound(
                        knowledge_submission_evidence,
                        {
                            "submission_id": submission_id,
                            "evidence_ref_id": evidence_ids[item.identity],
                            "evidence_role": item.role,
                            "created_at": self.at,
                        },
                    )
                )
            )

    def _classification(
        self, evidence_ids: Mapping[tuple[str, ...], str], *extra: Classification
    ) -> Classification:
        return classification_max(
            self._floor,
            self.predicate.classification_floor,
            *self._stored_classes(evidence_ids.values()),
            *extra,
        )

    def _mutation(
        self,
        submission_id: str,
        assertion_id: str,
        kind: KnowledgeMutationKind,
        new_version: int,
        classification: Classification,
    ) -> str:
        mutation_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION)
        self.connection.execute(
            insert(knowledge_assertion_mutations).values(
                **self._bound(
                    knowledge_assertion_mutations,
                    {
                        "mutation_id": mutation_id,
                        "assertion_id": assertion_id,
                        "mutation_kind": kind.value,
                        "prior_version": new_version - 1,
                        "new_version": new_version,
                        "submission_id": submission_id,
                        "created_at": self.at,
                    },
                )
            )
        )
        self.staged.append(
            _StagedMutation(assertion_id, kind, new_version, mutation_id, classification)
        )
        return mutation_id

    def _link(
        self,
        assertion_id: str,
        mutation_id: str,
        evidence_ids: Mapping[tuple[str, ...], str],
        *,
        skip: frozenset[tuple[str, str]] = frozenset(),
    ) -> int:
        written = 0
        for item in sorted(
            self.request.evidence, key=lambda entry: (evidence_ids[entry.identity], entry.role)
        ):
            key = (evidence_ids[item.identity], item.role)
            if key in skip:
                continue
            self.connection.execute(
                insert(knowledge_assertion_evidence_links).values(
                    **self._bound(
                        knowledge_assertion_evidence_links,
                        {
                            "assertion_id": assertion_id,
                            "evidence_ref_id": key[0],
                            "evidence_role": item.role,
                            "linked_by_mutation_id": mutation_id,
                            "created_at": self.at,
                        },
                    )
                )
            )
            written += 1
        return written

    def _create(
        self,
        submission_id: str,
        evidence_ids: Mapping[tuple[str, ...], str],
        *,
        predecessor: Row[Any] | None,
    ) -> KnowledgeSubmissionResult:
        request = self.request
        predicate = self.predicate
        extra = () if predecessor is None else (Classification(predecessor.classification),)
        classification = self._classification(evidence_ids, *extra)
        assertion_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION)
        self.connection.execute(
            insert(knowledge_assertions).values(
                **self._bound(
                    knowledge_assertions,
                    {
                        "assertion_id": assertion_id,
                        "subject_kind": request.subject_kind,
                        "subject_id": request.subject_id,
                        "predicate_code": predicate.predicate_code,
                        "predicate_version": predicate.predicate_version,
                        "value_type": predicate.value_type.value,
                        "cardinality": predicate.cardinality.value,
                        "temporal_semantics": predicate.temporal_semantics.value,
                        "qualifier_rule": predicate.qualifier_rule.value,
                        "value_text": request.value_text,
                        "value_datetime": request.value_datetime,
                        "qualifier_json": null()
                        if request.qualifier is None
                        else dict(request.qualifier),
                        "effective_from": request.effective_from,
                        "effective_to": request.effective_to,
                        "normalized_value_sha256": request.normalized_value_sha256,
                        "fingerprint_version": 1,
                        "assertion_fingerprint": request.assertion_fingerprint,
                        "epistemic_status": KnowledgeEpistemicStatus.SOURCE_OBSERVED.value,
                        "classification": classification.value,
                        "origin_is_synthetic": request.origin_is_synthetic,
                        "lifecycle": KnowledgeAssertionLifecycle.ACTIVE.value,
                        "version": 1,
                        "origin_submission_id": submission_id,
                        "supersedes_assertion_id": None
                        if predecessor is None
                        else predecessor.assertion_id,
                        "created_at": self.at,
                        "updated_at": self.at,
                    },
                )
            )
        )
        kind = (
            KnowledgeMutationKind.CREATE
            if predecessor is None
            else KnowledgeMutationKind.SUPERSEDE_SUCCESSOR
        )
        mutation_id = self._mutation(submission_id, assertion_id, kind, 1, classification)
        self._link(assertion_id, mutation_id, evidence_ids)
        if predecessor is None:
            outcome, reason = (
                KnowledgeSubmissionOutcome.DIRECT_CREATED,
                KnowledgeSubmissionReason.CREATED,
            )
        else:
            outcome, reason = (
                KnowledgeSubmissionOutcome.DIRECT_SUPERSEDED,
                KnowledgeSubmissionReason.SUPERSEDED,
            )
        result = self._complete(
            _result(
                submission_id,
                outcome,
                reason,
                assertion_id=assertion_id,
                assertion_version=1,
                mutation_id=mutation_id,
                superseded_assertion_id=None if predecessor is None else predecessor.assertion_id,
            )
        )
        return replace(result, current_lifecycle=KnowledgeAssertionLifecycle.ACTIVE.value)

    def _supersede(
        self,
        submission_id: str,
        predecessor: Row[Any],
        evidence_ids: Mapping[tuple[str, ...], str],
    ) -> KnowledgeSubmissionResult:
        """KLP-AC-031/118: validated while live, predecessor demoted, then successor inserted."""
        a = knowledge_assertions
        demoted = self.connection.execute(
            update(a)
            .where(
                partition_criterion(a, self.context),
                a.c.assertion_id == predecessor.assertion_id,
                a.c.version == predecessor.version,
                a.c.lifecycle.in_(_LIVE),
            )
            .values(
                lifecycle=KnowledgeAssertionLifecycle.SUPERSEDED.value,
                version=a.c.version + 1,
                updated_at=_not_before(a.c.updated_at, self.at),
            )
            .returning(a.c.version, a.c.classification)
        ).one_or_none()
        if demoted is None:
            raise KnowledgeConcurrentDuplicateError("the predecessor changed under the lock")
        self._mutation(
            submission_id,
            predecessor.assertion_id,
            KnowledgeMutationKind.SUPERSEDE_PREDECESSOR,
            int(demoted.version),
            Classification(demoted.classification),
        )
        return self._create(submission_id, evidence_ids, predecessor=predecessor)

    def _enrich(
        self,
        submission_id: str,
        live: Row[Any],
        evidence_ids: Mapping[tuple[str, ...], str],
    ) -> KnowledgeSubmissionResult:
        """KLP-AC-028: new evidence links + one version bump, no factual change.

        When the newly linked evidence raises the assertion's stored class, a
        second `classify` mutation (same submission) records the raise.
        """
        links = knowledge_assertion_evidence_links
        already = frozenset(
            (row.evidence_ref_id, row.evidence_role)
            for row in self.connection.execute(
                select(links.c.evidence_ref_id, links.c.evidence_role).where(
                    partition_criterion(links, self.context),
                    links.c.assertion_id == live.assertion_id,
                )
            )
        )
        fresh = {
            (evidence_ids[item.identity], item.role) for item in self.request.evidence
        } - already
        if not fresh:
            return self._complete(
                _result(
                    submission_id,
                    KnowledgeSubmissionOutcome.DUPLICATE_EXISTING,
                    KnowledgeSubmissionReason.EXACT_DUPLICATE,
                    assertion_id=live.assertion_id,
                    assertion_version=int(live.version),
                )
            )
        a = knowledge_assertions
        bumped = self.connection.execute(
            update(a)
            .where(
                partition_criterion(a, self.context),
                a.c.assertion_id == live.assertion_id,
                a.c.lifecycle.in_(_LIVE),
            )
            .values(version=a.c.version + 1, updated_at=_not_before(a.c.updated_at, self.at))
            .returning(a.c.version, a.c.classification)
        ).one()
        version = int(bumped.version)
        stored = Classification(bumped.classification)
        mutation_id = self._mutation(
            submission_id, live.assertion_id, KnowledgeMutationKind.EVIDENCE_ENRICH, version, stored
        )
        self._link(live.assertion_id, mutation_id, evidence_ids, skip=already)
        raised = classification_max(stored, *self._stored_classes(evidence_ids.values()))
        if CLASSIFICATION_RANK[raised] > CLASSIFICATION_RANK[stored]:
            classified = self.connection.execute(
                update(a)
                .where(partition_criterion(a, self.context), a.c.assertion_id == live.assertion_id)
                .values(
                    classification=raised.value,
                    version=a.c.version + 1,
                    updated_at=_not_before(a.c.updated_at, self.at),
                )
                .returning(a.c.version)
            ).one()
            version = int(classified.version)
            self._mutation(
                submission_id, live.assertion_id, KnowledgeMutationKind.CLASSIFY, version, raised
            )
        result = self._complete(
            _result(
                submission_id,
                KnowledgeSubmissionOutcome.DUPLICATE_ENRICHED,
                KnowledgeSubmissionReason.EVIDENCE_ENRICHED,
                assertion_id=live.assertion_id,
                assertion_version=version,
                mutation_id=mutation_id,
            )
        )
        return replace(result, current_lifecycle=self.lifecycle_of(live.assertion_id))

    def _propose(
        self,
        submission_id: str,
        reason: KnowledgeSubmissionReason,
        evidence_ids: Mapping[tuple[str, ...], str],
    ) -> KnowledgeSubmissionResult:
        """A new open proposal; its class is R6 5.3's. Proposals emit no event (AC-043)."""
        request = self.request
        predicate = self.predicate
        proposal_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_PROPOSAL)
        review_case_id = issue_identifier(IdKind.REVIEW_CASE)
        requirement = (
            KnowledgeReviewRequirement.REQUIRES_OPERATOR
            if reason is KnowledgeSubmissionReason.REQUIRES_OPERATOR
            else KnowledgeReviewRequirement.REQUIRES_REVIEW
        )
        classification = classification_max(
            self._floor, *self._stored_classes(evidence_ids.values())
        )
        self.connection.execute(
            insert(knowledge_assertion_proposals).values(
                **self._bound(
                    knowledge_assertion_proposals,
                    {
                        "proposal_id": proposal_id,
                        "review_case_id": review_case_id,
                        "origin_submission_id": submission_id,
                        "origin_is_synthetic": request.origin_is_synthetic,
                        "subject_kind": request.subject_kind,
                        "subject_id": request.subject_id,
                        "predicate_code": predicate.predicate_code,
                        "predicate_version": predicate.predicate_version,
                        "value_type": predicate.value_type.value,
                        "cardinality": predicate.cardinality.value,
                        "temporal_semantics": predicate.temporal_semantics.value,
                        "qualifier_rule": predicate.qualifier_rule.value,
                        "value_text": request.value_text,
                        "value_datetime": request.value_datetime,
                        "qualifier_json": null()
                        if request.qualifier is None
                        else dict(request.qualifier),
                        "effective_from": request.effective_from,
                        "effective_to": request.effective_to,
                        "normalized_value_sha256": request.normalized_value_sha256,
                        "fingerprint_version": 1,
                        "proposal_fingerprint": request.assertion_fingerprint,
                        "classification": classification.value,
                        "risk_class": _risk_class(predicate).value,
                        "review_requirement": requirement.value,
                        "state": KnowledgeProposalState.NEEDS_REVIEW.value,
                        "created_at": self.at,
                        "updated_at": self.at,
                    },
                )
            )
        )
        return self._complete(
            _result(
                submission_id,
                KnowledgeSubmissionOutcome.REVIEW_QUEUED,
                reason,
                proposal_id=proposal_id,
                review_case_id=review_case_id,
            )
        )

    def lifecycle_of(self, assertion_id: str) -> str | None:
        return self.connection.execute(
            select(knowledge_assertions.c.lifecycle).where(
                partition_criterion(knowledge_assertions, self.context),
                knowledge_assertions.c.assertion_id == assertion_id,
            )
        ).scalar_one_or_none()


# ---- Knowledge Review (KLP-WP-04 slice C, R6 sections 5.3, 8.1, 8.2, 10) ------------

#: The `source_capability` every Review-promotion event names.
KNOWLEDGE_REVIEW_CAPABILITY: Final = Capability.REVIEW_DECIDE.value
_ACCEPT: Final = KnowledgeReviewDisposition.ACCEPT.value
_CORRECT: Final = KnowledgeReviewDisposition.CORRECT_AND_ACCEPT.value
#: The proposal state each Knowledge disposition leaves (matrix vocabularies).
_STATE_AFTER: Final[Mapping[str, str]] = MappingProxyType(
    {
        _ACCEPT: KnowledgeProposalState.ACCEPTED.value,
        _CORRECT: KnowledgeProposalState.CORRECTED_ACCEPTED.value,
        KnowledgeReviewDisposition.REJECT.value: KnowledgeProposalState.REJECTED.value,
        KnowledgeReviewDisposition.DEFER.value: KnowledgeProposalState.DEFERRED.value,
        KnowledgeReviewDisposition.MARK_UNRESOLVED.value: KnowledgeProposalState.UNRESOLVED.value,
        KnowledgeReviewDisposition.INVALIDATE.value: KnowledgeProposalState.INVALIDATED.value,
    }
)
_SUBMISSION_EVIDENCE: Final = cast(
    Table, knowledge_submission_evidence.alias("ka_submission_evidence")
)


def proposal_withheld_remote(proposal: Table, principal_id: str) -> ColumnElement[bool]:
    """The proposal effective class of R6 section 5.3, as a remote-withholding predicate.

    The section 5.2 terms with "links" read as the origin submission's
    evidence rows (`knowledge_submission_evidence`): the proposal's stored
    class, or any cited row's own class, cross-profile sibling class, Capture
    / Relationship Memory version class, availability or archived Capture
    root. A correlated predicate over `proposal` (any alias of
    `knowledge_assertion_proposals`), applied in the statement before LIMIT.
    """
    context = capture_context(principal_id)
    evidence_withheld = exists(
        select(literal(1))
        .select_from(
            _SUBMISSION_EVIDENCE.join(
                _EVIDENCE,
                and_(
                    matching_partition_criterion(_EVIDENCE, _SUBMISSION_EVIDENCE),
                    _EVIDENCE.c.evidence_ref_id == _SUBMISSION_EVIDENCE.c.evidence_ref_id,
                ),
            )
        )
        .where(
            partition_criterion(_SUBMISSION_EVIDENCE, context),
            partition_criterion(_EVIDENCE, context),
            _SUBMISSION_EVIDENCE.c.submission_id == proposal.c.origin_submission_id,
            _evidence_withheld(_EVIDENCE, context),
        )
    )
    return or_(_restricted(proposal.c.classification), evidence_withheld)


def _review_case_statement(principal_id: str, *, remote: bool) -> Any:  # noqa: ANN401
    """One SELECT of cases with their review version and latest disposition."""
    context = capture_context(principal_id)
    p = knowledge_assertion_proposals
    d = knowledge_assertion_review_decisions
    version = (
        select(func.count())
        .select_from(d)
        .where(partition_criterion(d, context), d.c.review_case_id == p.c.review_case_id)
        .scalar_subquery()
    )
    latest = (
        select(d.c.disposition)
        .where(partition_criterion(d, context), d.c.review_case_id == p.c.review_case_id)
        .order_by(d.c.decision_sequence.desc())
        .limit(1)
        .scalar_subquery()
    )
    criteria: list[ColumnElement[bool]] = [partition_criterion(p, context)]
    if remote:
        criteria.append(not_(proposal_withheld_remote(p, principal_id)))
    return select(
        p.c.review_case_id,
        p.c.proposal_id,
        p.c.subject_kind,
        p.c.subject_id,
        p.c.predicate_code,
        p.c.predicate_version,
        p.c.review_requirement,
        p.c.risk_class,
        p.c.state,
        p.c.classification,
        p.c.created_at,
        p.c.value_text,
        p.c.value_datetime,
        p.c.qualifier_json,
        p.c.effective_from,
        p.c.effective_to,
        version.label("review_version"),
        latest.label("latest_disposition"),
    ).where(*criteria)


def _review_case_row(row: Row[Any]) -> KnowledgeReviewCaseRow:
    return KnowledgeReviewCaseRow(
        review_case_id=row.review_case_id,
        proposal_id=row.proposal_id,
        subject_kind=row.subject_kind,
        subject_id=row.subject_id,
        predicate_code=row.predicate_code,
        predicate_version=int(row.predicate_version),
        review_requirement=row.review_requirement,
        risk_class=row.risk_class,
        state=row.state,
        classification=row.classification,
        opened_at=row.created_at,
        review_version=int(row.review_version),
        latest_disposition=row.latest_disposition,
        value_text=row.value_text,
        value_datetime=row.value_datetime,
        qualifier=None if row.qualifier_json is None else dict(row.qualifier_json),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


def _has_counterevidence(
    connection: Connection, context: PrincipalContext, assertion_id: str
) -> bool:
    """Whether `assertion_id` carries a counterevidence link (unresolved, KLP-AC-031).

    One reader for both supersession paths (autonomous submit and Review).
    """
    links = knowledge_assertion_evidence_links
    return (
        connection.execute(
            select(links.c.evidence_ref_id).where(
                partition_criterion(links, context),
                links.c.assertion_id == assertion_id,
                links.c.evidence_role == KnowledgeEvidenceRole.COUNTEREVIDENCE.value,
            )
        ).first()
        is not None
    )


class _ReviewDecision:
    """One Knowledge `review.decide` transaction body (R6 sections 8.1, 8.2, 10).

    C1 (the `relationship_write_requests` reservation) is the application's,
    taken before this body runs. A promotion (accept / correct_and_accept) then
    takes C3 -- one `lock_entity_mutation_scopes` call over the complete Entity
    set (the subject; a correction cannot name another) -- and re-reads the
    subject under it, C4b the origin submission's evidence rows in one sorted
    `FOR SHARE` SELECT (it links them; it changes no control column), C4c the
    one Capture fence, C5 the proposal `FOR UPDATE`, then C6 the complete
    sorted subject-key set, re-running the duplicate and current-slot checks
    under it. A key set that differs from the one computed before the locks is
    a retryable conflict and never a late lock (KLP-AC-153). Every other
    disposition takes C5 only: it creates no liveness (R6 8.2). C8 inserts the
    decision before any mutation that cites it; proposals and decisions stage
    no Record Event (KLP-AC-043), each promoting mutation stages its mapped one.
    """

    def __init__(
        self,
        connection: Connection,
        principal_id: str,
        request: KnowledgeReviewDecisionRequest,
        at: datetime,
    ) -> None:
        self.connection = connection
        self.principal_id = principal_id
        self.request = request
        self.at = at
        self.context = capture_context(principal_id)
        self.promoting = request.disposition in (_ACCEPT, _CORRECT)
        self.staged: list[_StagedMutation] = []

    def _bound(self, table: Table, values: dict[str, object]) -> dict[str, object]:
        return principal_bound_values(values, table, self.context)

    # -- reads ------------------------------------------------------------------

    def _proposal(self, *, lock: bool) -> Row[Any] | None:
        p = knowledge_assertion_proposals
        statement = select(p).where(
            partition_criterion(p, self.context),
            p.c.review_case_id == self.request.review_case_id,
        )
        if lock:
            statement = statement.with_for_update()
        return self.connection.execute(statement).one_or_none()

    def _subject_keys(self, proposal: Row[Any]) -> frozenset[tuple[str, str, str]]:
        """The complete Knowledge subject-key set this decision would write (C6).

        The proposal's own key: a correction patch can name no subject or
        predicate (KLP-AC-037), so the corrected key equals it.
        """
        return frozenset({(proposal.subject_kind, proposal.subject_id, proposal.predicate_code)})

    def _require_canonical(self, proposal: Row[Any]) -> None:
        """The subject is still canonical, read under C3 (merged-away refused, AC-036)."""
        kind, subject_id = proposal.subject_kind, proposal.subject_id
        predicate: KnowledgePredicate = self.request.predicate
        canonical = False
        if kind == KnowledgeSubjectKind.PRINCIPAL.value:
            canonical = subject_id == self.principal_id
        elif kind == KnowledgeSubjectKind.PROJECT.value:
            canonical = (
                self.connection.execute(
                    select(projects.c.project_id).where(
                        partition_criterion(projects, self.context),
                        projects.c.project_id == subject_id,
                    )
                ).scalar_one_or_none()
                is not None
            )
        elif kind == KnowledgeSubjectKind.ENTITY.value:
            row = self.connection.execute(
                select(entities.c.entity_type, entities.c.status).where(
                    partition_criterion(entities, self.context),
                    entities.c.entity_id == subject_id,
                )
            ).one_or_none()
            canonical = (
                row is not None
                and row.status == EntityStatus.ACTIVE.value
                and EntityType(row.entity_type) in predicate.allowed_entity_types
            )
        if not canonical:
            raise KnowledgeSubjectNotCanonicalError("the subject is no longer canonical")

    def _lock_evidence(self, proposal: Row[Any]) -> tuple[list[Row[Any]], list[Row[Any]]]:
        """C4b: the origin submission's evidence rows, one sorted `FOR SHARE` SELECT."""
        se, e = knowledge_submission_evidence, knowledge_evidence_refs
        cited = select(se.c.evidence_ref_id).where(
            partition_criterion(se, self.context),
            se.c.submission_id == proposal.origin_submission_id,
        )
        rows = list(
            self.connection.execute(
                select(
                    e.c.evidence_ref_id,
                    e.c.identity_kind,
                    e.c.capture_id,
                    e.c.source_classification,
                )
                .where(partition_criterion(e, self.context), e.c.evidence_ref_id.in_(cited))
                .order_by(e.c.evidence_ref_id)
                .with_for_update(read=True)
            ).all()
        )
        roles = list(
            self.connection.execute(
                select(se.c.evidence_ref_id, se.c.evidence_role)
                .where(
                    partition_criterion(se, self.context),
                    se.c.submission_id == proposal.origin_submission_id,
                )
                .order_by(se.c.evidence_ref_id, se.c.evidence_role)
            ).all()
        )
        return rows, roles

    def _review_version(self) -> int:
        d = knowledge_assertion_review_decisions
        return int(
            self.connection.execute(
                select(func.count())
                .select_from(d)
                .where(
                    partition_criterion(d, self.context),
                    d.c.review_case_id == self.request.review_case_id,
                )
            ).scalar_one()
        )

    def _lock_subjects(self, keys: frozenset[tuple[str, str, str]]) -> None:
        """C6: upsert every key, then one sorted `SELECT ... FOR UPDATE`."""
        locks = knowledge_assertion_subject_locks
        ordered = sorted(keys)
        for kind, subject_id, predicate_code in ordered:
            self.connection.execute(
                pg_insert(locks)
                .values(
                    **self._bound(
                        locks,
                        {
                            "subject_kind": kind,
                            "subject_id": subject_id,
                            "predicate_code": predicate_code,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        self.connection.execute(
            select(locks.c.predicate_code)
            .where(
                partition_criterion(locks, self.context),
                tuple_(locks.c.subject_kind, locks.c.subject_id, locks.c.predicate_code).in_(
                    ordered
                ),
            )
            .order_by(
                locks.c.principal_id,
                locks.c.subject_kind,
                locks.c.subject_id,
                locks.c.predicate_code,
            )
            .with_for_update()
        ).all()

    def _live_duplicate(self, fingerprint: str) -> bool:
        a = knowledge_assertions
        return (
            self.connection.execute(
                select(a.c.assertion_id).where(
                    partition_criterion(a, self.context),
                    a.c.fingerprint_version == 1,
                    a.c.assertion_fingerprint == fingerprint,
                    a.c.lifecycle.in_(_LIVE),
                )
            ).first()
            is not None
        )

    def _slot_holder(self, proposal: Row[Any]) -> Row[Any] | None:
        predicate: KnowledgePredicate = self.request.predicate
        if predicate.cardinality is not KnowledgeCardinality.SINGLE_CURRENT:
            return None
        a = knowledge_assertions
        return self.connection.execute(
            select(a.c.assertion_id, a.c.version, a.c.classification, a.c.effective_from).where(
                partition_criterion(a, self.context),
                a.c.subject_kind == proposal.subject_kind,
                a.c.subject_id == proposal.subject_id,
                a.c.predicate_code == proposal.predicate_code,
                a.c.cardinality == KnowledgeCardinality.SINGLE_CURRENT.value,
                a.c.lifecycle.in_(_LIVE),
            )
        ).one_or_none()

    # -- the transaction ------------------------------------------------------------

    def run(self) -> KnowledgeReviewDecisionResult:
        request = self.request
        proposal = self._proposal(lock=False)
        if proposal is None:
            raise ReviewNotFoundError("no Knowledge case of this Principal")
        keys = self._subject_keys(proposal)
        evidence: list[Row[Any]] = []
        roles: list[Row[Any]] = []
        if self.promoting:
            entity_ids = sorted(
                subject_id
                for kind, subject_id, _code in keys
                if kind == KnowledgeSubjectKind.ENTITY.value
            )
            if entity_ids:
                # C3: ONE call over the complete Entity set, helper key order.
                lock_entity_mutation_scopes(self.connection, self.principal_id, entity_ids)
            self._require_canonical(proposal)
            # C4b, then C4c: exactly one Capture fence.
            evidence, roles = self._lock_evidence(proposal)
            _capture_fence(
                self.connection,
                self.context,
                tuple(
                    sorted(
                        {str(row.capture_id) for row in evidence if row.identity_kind == _CAPTURE}
                    )
                ),
            )
        # C5: the proposal FOR UPDATE; state and review version re-read under it.
        locked = self._proposal(lock=True)
        if locked is None:  # pragma: no cover - proposals are never deleted (trigger)
            raise ReviewNotFoundError("no Knowledge case of this Principal")
        if locked.state not in _OPEN_PROPOSAL:
            raise ReviewConflictError("the proposal is already terminal")
        version = self._review_version()
        if version != request.expected_review_version:
            raise ReviewConflictError("the review version is stale")
        holder: Row[Any] | None = None
        if self.promoting:
            if self._subject_keys(locked) != keys:
                # KLP-AC-153: the key set moved before C6 -- never a late C3-C6 lock.
                raise TransactionConflictError("the subject-key set changed")
            self._lock_subjects(keys)
            if self._subject_keys(locked) != keys:
                # KLP-AC-153: re-derived after C6; a change is retryable, not re-locked.
                raise TransactionConflictError("the subject-key set changed")
            fingerprint = (
                locked.proposal_fingerprint
                if request.corrected is None
                else request.corrected.assertion_fingerprint
            )
            if self._live_duplicate(fingerprint):
                raise KnowledgeConcurrentDuplicateError("an equal live fact exists")
            holder = self._slot_holder(locked)
            if holder is not None:
                self._require_supersession_guards(locked, holder)
        decision_id = self._insert_decision(locked, version + 1)
        assertion_id: str | None = None
        receipt_id: str | None = None
        if self.promoting:
            assertion_id, receipt_id = self._promote(locked, decision_id, evidence, roles, holder)
        state = _STATE_AFTER[request.disposition]
        p = knowledge_assertion_proposals
        moved = self.connection.execute(
            update(p)
            .where(
                partition_criterion(p, self.context),
                p.c.proposal_id == locked.proposal_id,
                p.c.state.in_(_OPEN_PROPOSAL),
            )
            .values(state=state, updated_at=_not_before(p.c.updated_at, self.at))
        )
        if moved.rowcount != 1:  # pragma: no cover - held FOR UPDATE since C5
            raise ReviewConflictError("the proposal moved under the lock")
        return KnowledgeReviewDecisionResult(
            decision_id=decision_id,
            review_case_id=locked.review_case_id,
            sequence=version + 1,
            disposition=request.disposition,
            proposal_state=state,
            assertion_id=assertion_id,
            receipt_id=receipt_id,
        )

    def _require_supersession_guards(self, proposal: Row[Any], holder: Row[Any]) -> None:
        """KLP-AC-031 on a Review supersession, from facts read under C6 (DEV-66 ruling).

        The holder (and its effective_from) was just read under the C6 subject
        lock and its counterevidence links are read here, still under it; the
        successor's bounds are the corrected candidate's, else the proposal's.
        The same `supersession_guard_blockers` the autonomous policy applies.
        Raised before the decision row: nothing of this decide survives.
        """
        corrected = self.request.corrected
        successor = proposal.effective_from if corrected is None else corrected.effective_from
        blockers = supersession_guard_blockers(
            successor,
            CurrentFact(
                assertion_id=holder.assertion_id,
                effective_from=holder.effective_from,
                unresolved_counterevidence=_has_counterevidence(
                    self.connection, self.context, holder.assertion_id
                ),
            ),
            self.at,
        )
        if blockers:
            counterevidence = (
                DirectAdmissionBlocker.PREDECESSOR_COUNTEREVIDENCE_UNRESOLVED in blockers
            )
            raise KnowledgeSupersessionGuardError(
                bounds=len(blockers) > int(counterevidence), counterevidence=counterevidence
            )

    # -- C7 / C8 writers --------------------------------------------------------------

    def _insert_decision(self, proposal: Row[Any], sequence: int) -> str:
        request = self.request
        decision_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_REVIEW_DECISION)
        self.connection.execute(
            insert(knowledge_assertion_review_decisions).values(
                **self._bound(
                    knowledge_assertion_review_decisions,
                    {
                        "decision_id": decision_id,
                        "review_case_id": proposal.review_case_id,
                        "proposal_id": proposal.proposal_id,
                        "review_requirement": proposal.review_requirement,
                        "decision_sequence": sequence,
                        "disposition": request.disposition,
                        "reason": request.reason,
                        "correction_patch": null()
                        if request.correction_patch is None
                        else dict(request.correction_patch),
                        "authenticated_client_id": request.authenticated_client_id,
                        "decision_channel": request.decision_channel,
                        "operator_authority_class": request.operator_authority_class,
                        "external_feedback_ref_hash": None,
                        "correlation_id": request.correlation_id,
                        "audit_id": request.audit_id,
                        "created_at": self.at,
                    },
                )
            )
        )
        return decision_id

    def _mutation(
        self,
        proposal: Row[Any],
        decision_id: str,
        assertion_id: str,
        kind: KnowledgeMutationKind,
        new_version: int,
        classification: Classification,
    ) -> str:
        mutation_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION)
        self.connection.execute(
            insert(knowledge_assertion_mutations).values(
                **self._bound(
                    knowledge_assertion_mutations,
                    {
                        "mutation_id": mutation_id,
                        "assertion_id": assertion_id,
                        "mutation_kind": kind.value,
                        "prior_version": new_version - 1,
                        "new_version": new_version,
                        "submission_id": proposal.origin_submission_id,
                        "proposal_id": proposal.proposal_id,
                        "review_case_id": proposal.review_case_id,
                        "review_decision_id": decision_id,
                        "created_at": self.at,
                    },
                )
            )
        )
        self.staged.append(
            _StagedMutation(assertion_id, kind, new_version, mutation_id, classification)
        )
        return mutation_id

    def _promote(
        self,
        proposal: Row[Any],
        decision_id: str,
        evidence: Sequence[Row[Any]],
        roles: Sequence[Row[Any]],
        holder: Row[Any] | None,
    ) -> tuple[str, str]:
        """Insert the accepted (or corrected) fact; a single-current holder is superseded.

        Its class is never below the proposal's (trigger
        `knowledge_assertion_is_not_less_restrictive`, KLP-AC-095/116), the
        predicate floor, any cited row's stored class or the superseded
        holder's.
        """
        request = self.request
        predicate: KnowledgePredicate = request.predicate
        corrected = request.corrected
        classification = classification_max(
            Classification(proposal.classification),
            predicate.classification_floor,
            *(Classification(row.source_classification) for row in evidence),
            *(() if holder is None else (Classification(holder.classification),)),
        )
        a = knowledge_assertions
        if holder is not None:
            demoted = self.connection.execute(
                update(a)
                .where(
                    partition_criterion(a, self.context),
                    a.c.assertion_id == holder.assertion_id,
                    a.c.version == holder.version,
                    a.c.lifecycle.in_(_LIVE),
                )
                .values(
                    lifecycle=KnowledgeAssertionLifecycle.SUPERSEDED.value,
                    version=a.c.version + 1,
                    updated_at=_not_before(a.c.updated_at, self.at),
                )
                .returning(a.c.version, a.c.classification)
            ).one_or_none()
            if demoted is None:  # pragma: no cover - the C6 lock serializes the slot
                raise KnowledgeConcurrentDuplicateError("the current fact changed under the lock")
            self._mutation(
                proposal,
                decision_id,
                holder.assertion_id,
                KnowledgeMutationKind.SUPERSEDE_PREDECESSOR,
                int(demoted.version),
                Classification(demoted.classification),
            )
        assertion_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION)
        if corrected is None:
            value_text, value_datetime = proposal.value_text, proposal.value_datetime
            qualifier = proposal.qualifier_json
            effective_from, effective_to = proposal.effective_from, proposal.effective_to
            digest, fingerprint = proposal.normalized_value_sha256, proposal.proposal_fingerprint
        else:
            value_text, value_datetime = corrected.value_text, corrected.value_datetime
            qualifier = corrected.qualifier
            effective_from, effective_to = corrected.effective_from, corrected.effective_to
            digest, fingerprint = (
                corrected.normalized_value_sha256,
                corrected.assertion_fingerprint,
            )
        self.connection.execute(
            insert(a).values(
                **self._bound(
                    a,
                    {
                        "assertion_id": assertion_id,
                        "subject_kind": proposal.subject_kind,
                        "subject_id": proposal.subject_id,
                        "predicate_code": predicate.predicate_code,
                        "predicate_version": predicate.predicate_version,
                        "value_type": predicate.value_type.value,
                        "cardinality": predicate.cardinality.value,
                        "temporal_semantics": predicate.temporal_semantics.value,
                        "qualifier_rule": predicate.qualifier_rule.value,
                        "value_text": value_text,
                        "value_datetime": value_datetime,
                        "qualifier_json": null() if qualifier is None else dict(qualifier),
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "normalized_value_sha256": digest,
                        "fingerprint_version": 1,
                        "assertion_fingerprint": fingerprint,
                        "epistemic_status": KnowledgeEpistemicStatus.REVIEW_ACCEPTED.value,
                        "classification": classification.value,
                        "origin_is_synthetic": proposal.origin_is_synthetic,
                        "lifecycle": KnowledgeAssertionLifecycle.ACTIVE.value,
                        "version": 1,
                        "origin_submission_id": proposal.origin_submission_id,
                        "supersedes_assertion_id": None if holder is None else holder.assertion_id,
                        "accepted_review_case_id": proposal.review_case_id,
                        "created_at": self.at,
                        "updated_at": self.at,
                    },
                )
            )
        )
        kind = (
            KnowledgeMutationKind.REVIEW_ACCEPT
            if corrected is None
            else KnowledgeMutationKind.REVIEW_CORRECT
        )
        mutation_id = self._mutation(proposal, decision_id, assertion_id, kind, 1, classification)
        for row in roles:
            self.connection.execute(
                insert(knowledge_assertion_evidence_links).values(
                    **self._bound(
                        knowledge_assertion_evidence_links,
                        {
                            "assertion_id": assertion_id,
                            "evidence_ref_id": row.evidence_ref_id,
                            "evidence_role": row.evidence_role,
                            "linked_by_mutation_id": mutation_id,
                            "created_at": self.at,
                        },
                    )
                )
            )
        return assertion_id, mutation_id


# ---- discovery checkpoint (KLP-WP-04 slice B3, R6 sections 6.1, 7, 8.1) ------------

_ADVANCED: Final = KnowledgeCheckpointOutcome.ADVANCED.value
_CHECKPOINT_CONFLICT: Final = KnowledgeCheckpointOutcome.CHECKPOINT_CONFLICT.value
_CHECKPOINT_REFUSED: Final = KnowledgeCheckpointOutcome.REFUSED.value
_UNVERIFIABLE: Final = KnowledgeCheckpointReason.ENVELOPE_UNVERIFIABLE.value


def _checkpoint_binding(principal_id: str, row: Row[Any]) -> CheckpointBinding:
    return CheckpointBinding(
        principal_id=principal_id,
        authenticated_client_id=row.authenticated_client_id,
        source_profile_id=row.source_profile_id,
        scope_digest=row.scope_digest,
    )


def _current_checkpoint(
    connection: Connection, principal_id: str, binding: CheckpointBinding
) -> Row[Any] | None:
    """The one checkpoint row of (principal, profile, client, scope), or `None`."""
    c = knowledge_discovery_checkpoints
    return connection.execute(
        select(c).where(
            partition_criterion(c, capture_context(principal_id)),
            c.c.source_profile_id == binding.source_profile_id,
            c.c.authenticated_client_id == binding.authenticated_client_id,
            c.c.scope_digest == binding.scope_digest,
        )
    ).one_or_none()


def _verified(seal: CheckpointSeal, binding: CheckpointBinding, current: Row[Any]) -> bool:
    """Whether the stored checkpoint's envelope may be returned or relied on (R6 7)."""
    return seal.verify(
        binding,
        checkpoint_id=current.checkpoint_id,
        version=current.version,
        seal_version=current.seal_version,
        private_envelope=current.private_envelope,
        envelope_mac=current.envelope_mac,
    )


def _unverifiable(request_id: str, current: Row[Any] | None) -> KnowledgeCheckpointResult:
    """`checkpoint_conflict(envelope_unverifiable)`: current id/version, no envelope."""
    return KnowledgeCheckpointResult(
        checkpoint_request_id=request_id,
        outcome=_CHECKPOINT_CONFLICT,
        reason=_UNVERIFIABLE,
        checkpoint_id=None if current is None else current.checkpoint_id,
        checkpoint_version=None if current is None else current.version,
        checkpoint_kind=None if current is None else current.checkpoint_kind,
        private_envelope=None,
        private_token_redacted=True,
    )


def _stored_checkpoint_result(
    connection: Connection, principal_id: str, row: Row[Any], seal: CheckpointSeal
) -> KnowledgeCheckpointResult:
    """The stored public answer of one completed request, verified before return.

    A stored envelope is returned only when it verifies under the configured
    seal (R6 7): one sealed under another seal version, or whose MAC fails,
    answers `envelope_unverifiable` with the *current* checkpoint id/version.
    A redacted row is its exact public receipt with `private_token_redacted`.
    """
    binding = _checkpoint_binding(principal_id, row)
    if row.result_private_envelope is not None:
        verified = seal.verify(
            binding,
            checkpoint_id=row.result_checkpoint_id,
            version=row.result_checkpoint_version,
            seal_version=row.result_seal_version,
            private_envelope=row.result_private_envelope,
            envelope_mac=row.result_envelope_mac,
        )
        if not verified:
            return _unverifiable(
                row.checkpoint_request_id, _current_checkpoint(connection, principal_id, binding)
            )
    return KnowledgeCheckpointResult(
        checkpoint_request_id=row.checkpoint_request_id,
        outcome=row.result_outcome,
        reason=row.result_reason,
        checkpoint_id=row.result_checkpoint_id,
        checkpoint_version=row.result_checkpoint_version,
        checkpoint_kind=row.result_checkpoint_kind,
        private_envelope=row.result_private_envelope,
        private_token_redacted=bool(row.private_token_redacted)
        or row.result_reason == _UNVERIFIABLE,
    )


class _CheckpointAdvance:
    """One checkpoint transaction body (R6 sections 6.1, 6.4, 7 and 8.1).

    C1 the request reservation on (principal, client, idempotency_key) --
    `INSERT ... ON CONFLICT DO NOTHING`, then the winner by key (equal digest
    replays, a different digest is `idempotency_conflict` with no write); C4a
    the bound profile row `FOR NO KEY UPDATE`, which serializes every advance,
    first or later, of the one (profile, client, scope) checkpoint and every
    disable, with `disabled_at` re-read after locking. Then, in order:

    1. a disabled profile completes `refused(source_profile_inactive)`;
    2. an `expected_version` other than the current version (0 = none) is
       `checkpoint_conflict(stale_expected_version)` carrying the current id,
       version and -- verified first -- the current envelope (lost-response
       recovery, KLP-AC-145), else `envelope_unverifiable` without it;
    3. a matching advance over a stored row sealed under the *current* seal
       whose MAC fails, or under a newer seal, is `envelope_unverifiable`
       (fail closed); a row under an *older* seal is the post-rotation
       re-bootstrap and is advanced over without returning its token;
    4. another `checkpoint_kind` than the stored one is refused as an invalid
       request (the kind is immutable; rolls back whole, DEV-50);
    5. a `submitted_candidate_count` other than the number of completed
       submissions of (client, run, profile, scope) completes
       `refused(candidate_count_mismatch)` (KLP-AC-074);
    6. else the checkpoint is inserted at version 1 or advanced by one, sealed
       under the current seal, the request completes `advanced`, and in the
       same transaction every completed request row of the same (principal,
       profile, client, scope) still holding an envelope with
       `result_checkpoint_version` below the new version is redacted
       (KLP-AC-094), conflict rows included.

    Every outcome is a completed request row; the deferred trigger refuses a
    COMMIT that leaves the reservation reserved (R6 6.4). No Record Event is
    staged: a checkpoint is operational state, not a Knowledge mutation.
    """

    def __init__(
        self,
        connection: Connection,
        principal_id: str,
        request: KnowledgeCheckpointRequest,
        at: datetime,
        seal: CheckpointSeal,
    ) -> None:
        self.connection = connection
        self.principal_id = principal_id
        self.request = request
        self.at = at
        self.seal = seal
        self.context = capture_context(principal_id)
        self.binding = CheckpointBinding(
            principal_id=principal_id,
            authenticated_client_id=request.authenticated_client_id,
            source_profile_id=request.source_profile_id,
            scope_digest=request.scope_digest,
        )

    def _bound(self, table: Table, values: dict[str, object]) -> dict[str, object]:
        return principal_bound_values(values, table, self.context)

    # -- C1 ------------------------------------------------------------------------

    def _reserve(self, request_id: str) -> bool:
        request = self.request
        statement = (
            pg_insert(knowledge_discovery_checkpoint_requests)
            .values(
                **self._bound(
                    knowledge_discovery_checkpoint_requests,
                    {
                        "checkpoint_request_id": request_id,
                        "authenticated_client_id": request.authenticated_client_id,
                        "source_profile_id": request.source_profile_id,
                        "scope_digest": request.scope_digest,
                        "external_run_id": request.external_run_id,
                        "submitted_candidate_count": request.submitted_candidate_count,
                        "expected_version": request.expected_version,
                        "idempotency_key": request.idempotency_key,
                        "request_digest": request.request_digest,
                        "state": "reserved",
                        "created_at": self.at,
                    },
                )
            )
            .on_conflict_do_nothing(
                index_elements=["principal_id", "authenticated_client_id", "idempotency_key"]
            )
            .returning(knowledge_discovery_checkpoint_requests.c.checkpoint_request_id)
        )
        return self.connection.execute(statement).scalar_one_or_none() is not None

    def _winner(self) -> KnowledgeCheckpointResult:
        r = knowledge_discovery_checkpoint_requests
        row = self.connection.execute(
            select(r).where(
                partition_criterion(r, self.context),
                r.c.authenticated_client_id == self.request.authenticated_client_id,
                r.c.idempotency_key == self.request.idempotency_key,
            )
        ).one()
        if row.request_digest != self.request.request_digest:
            raise KnowledgeIdempotencyConflictError("the key is bound to another request")
        return _stored_checkpoint_result(self.connection, self.principal_id, row, self.seal)

    def _complete(
        self,
        result: KnowledgeCheckpointResult,
        *,
        seal_version: int | None = None,
        envelope_mac: str | None = None,
    ) -> KnowledgeCheckpointResult:
        r = knowledge_discovery_checkpoint_requests
        done = self.connection.execute(
            update(r)
            .where(
                partition_criterion(r, self.context),
                r.c.checkpoint_request_id == result.checkpoint_request_id,
                r.c.state == "reserved",
            )
            .values(
                state="completed",
                result_outcome=result.outcome,
                result_reason=result.reason,
                result_checkpoint_id=result.checkpoint_id,
                result_checkpoint_version=result.checkpoint_version,
                result_checkpoint_kind=result.checkpoint_kind,
                result_private_envelope=result.private_envelope,
                result_seal_version=None if result.private_envelope is None else seal_version,
                result_envelope_mac=None if result.private_envelope is None else envelope_mac,
                completed_at=self.at,
            )
        )
        if done.rowcount != 1:
            raise RepositoryFailureError("the reservation was not held")
        return result

    # -- C4a -----------------------------------------------------------------------

    def _lock_profile(self) -> Row[Any]:
        """The bound profile row, C4a `FOR NO KEY UPDATE`; `disabled_at` re-read."""
        p = knowledge_discovery_source_profiles
        row = self.connection.execute(
            select(p.c.source_profile_id, p.c.disabled_at)
            .where(
                partition_criterion(p, self.context),
                p.c.source_profile_id == self.request.source_profile_id,
                p.c.authenticated_client_id == self.request.authenticated_client_id,
                p.c.scope_digest == self.request.scope_digest,
            )
            .with_for_update(key_share=True)
        ).one_or_none()
        if row is None:  # the reservation's FK already proved the binding
            raise KnowledgeSourceProfileUnboundError("the profile is not this client's")
        return row

    def _completed_submissions(self) -> int:
        s = knowledge_assertion_submissions
        request = self.request
        return int(
            self.connection.execute(
                select(func.count()).where(
                    partition_criterion(s, self.context),
                    s.c.origin == _AUTONOMOUS,
                    s.c.authenticated_client_id == request.authenticated_client_id,
                    s.c.source_profile_id == request.source_profile_id,
                    s.c.scope_digest == request.scope_digest,
                    s.c.external_run_id == request.external_run_id,
                    s.c.submission_state == "completed",
                )
            ).scalar_one()
        )

    # -- the body ------------------------------------------------------------------

    def run(self) -> KnowledgeCheckpointResult:
        request_id = issue_identifier(IdKind.KNOWLEDGE_DISCOVERY_CHECKPOINT_REQUEST)
        if not self._reserve(request_id):
            return self._winner()
        profile = self._lock_profile()
        if profile.disabled_at is not None:
            return self._refused(request_id, KnowledgeCheckpointReason.SOURCE_PROFILE_INACTIVE)
        current = _current_checkpoint(self.connection, self.principal_id, self.binding)
        current_version = 0 if current is None else int(current.version)
        if self.request.expected_version != current_version:
            return self._stale(request_id, current)
        if current is not None:
            older_seal = current.seal_version < self.seal.seal_version
            if not older_seal and not _verified(self.seal, self.binding, current):
                return self._complete(_unverifiable(request_id, current))
            if current.checkpoint_kind != self.request.checkpoint_kind:
                raise KnowledgeCheckpointKindMismatchError("the checkpoint kind is immutable")
        if self._completed_submissions() != self.request.submitted_candidate_count:
            return self._refused(request_id, KnowledgeCheckpointReason.CANDIDATE_COUNT_MISMATCH)
        return self._advance(request_id, current)

    def _refused(
        self, request_id: str, reason: KnowledgeCheckpointReason
    ) -> KnowledgeCheckpointResult:
        return self._complete(
            KnowledgeCheckpointResult(
                checkpoint_request_id=request_id,
                outcome=_CHECKPOINT_REFUSED,
                reason=reason.value,
                checkpoint_id=None,
                checkpoint_version=None,
                checkpoint_kind=None,
                private_envelope=None,
                private_token_redacted=False,
            )
        )

    def _stale(self, request_id: str, current: Row[Any] | None) -> KnowledgeCheckpointResult:
        """Lost-response recovery (KLP-AC-145): the current state, to this client only.

        The caller is the bound client of this very (profile, client, scope):
        the C2 binding read refused every other client before the ledger was
        touched, so the current envelope goes to its owner -- verified first.
        """
        if current is not None and not _verified(self.seal, self.binding, current):
            return self._complete(_unverifiable(request_id, current))
        envelope = None if current is None else str(current.private_envelope)
        return self._complete(
            KnowledgeCheckpointResult(
                checkpoint_request_id=request_id,
                outcome=_CHECKPOINT_CONFLICT,
                reason=KnowledgeCheckpointReason.STALE_EXPECTED_VERSION.value,
                checkpoint_id=None if current is None else current.checkpoint_id,
                checkpoint_version=None if current is None else int(current.version),
                checkpoint_kind=None if current is None else current.checkpoint_kind,
                private_envelope=envelope,
                private_token_redacted=False,
            ),
            seal_version=None if current is None else int(current.seal_version),
            envelope_mac=None if current is None else current.envelope_mac,
        )

    def _advance(self, request_id: str, current: Row[Any] | None) -> KnowledgeCheckpointResult:
        request = self.request
        c = knowledge_discovery_checkpoints
        version = 1 if current is None else int(current.version) + 1
        checkpoint_id = (
            issue_identifier(IdKind.KNOWLEDGE_DISCOVERY_CHECKPOINT)
            if current is None
            else str(current.checkpoint_id)
        )
        mac = self.seal.seal(
            self.binding,
            checkpoint_id=checkpoint_id,
            version=version,
            private_envelope=request.private_envelope,
        )
        sealed = {
            "version": version,
            "private_envelope": request.private_envelope,
            "seal_version": self.seal.seal_version,
            "envelope_mac": mac,
            "external_run_id": request.external_run_id,
        }
        if current is None:
            # Unreachable while C4a serializes first advances; a lost insert
            # race still answers the routed conflict, never a 23505.
            written = self.connection.execute(
                pg_insert(c)
                .values(
                    **self._bound(
                        c,
                        {
                            "checkpoint_id": checkpoint_id,
                            "source_profile_id": request.source_profile_id,
                            "authenticated_client_id": request.authenticated_client_id,
                            "scope_digest": request.scope_digest,
                            "checkpoint_kind": request.checkpoint_kind,
                            "created_at": self.at,
                            "updated_at": self.at,
                            **sealed,
                        },
                    )
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "principal_id",
                        "source_profile_id",
                        "authenticated_client_id",
                        "scope_digest",
                    ]
                )
                .returning(c.c.checkpoint_id)
            ).scalar_one_or_none()
        else:
            written = self.connection.execute(
                update(c)
                .where(
                    partition_criterion(c, self.context),
                    c.c.checkpoint_id == checkpoint_id,
                    c.c.version == current.version,
                )
                .values(updated_at=max(self.at, current.updated_at), **sealed)
                .returning(c.c.checkpoint_id)
            ).scalar_one_or_none()
        if written is None:  # pragma: no cover - serialized by the C4a lock
            return self._stale(
                request_id, _current_checkpoint(self.connection, self.principal_id, self.binding)
            )
        result = self._complete(
            KnowledgeCheckpointResult(
                checkpoint_request_id=request_id,
                outcome=_ADVANCED,
                reason=KnowledgeCheckpointReason.ADVANCED.value,
                checkpoint_id=checkpoint_id,
                checkpoint_version=version,
                checkpoint_kind=request.checkpoint_kind,
                private_envelope=request.private_envelope,
                private_token_redacted=False,
            ),
            seal_version=self.seal.seal_version,
            envelope_mac=mac,
        )
        self._redact_superseded(version)
        return result

    def _redact_superseded(self, version: int) -> None:
        """KLP-AC-094: redact every older envelope of this binding, conflict rows too."""
        r = knowledge_discovery_checkpoint_requests
        request = self.request
        self.connection.execute(
            update(r)
            .where(
                partition_criterion(r, self.context),
                r.c.source_profile_id == request.source_profile_id,
                r.c.authenticated_client_id == request.authenticated_client_id,
                r.c.scope_digest == request.scope_digest,
                r.c.state == "completed",
                r.c.result_private_envelope.is_not(None),
                r.c.result_checkpoint_version < version,
            )
            .values(
                result_private_envelope=null(),
                result_envelope_mac=null(),
                private_token_redacted=True,
            )
        )


# ---- source-profile commissioning and maintenance (KLP-WP-04 slice B1) -------------
#
# Reached only through `knowledge_maintenance_transaction` (the guarded operator
# command `apps/cli/knowledge_source_profiles.py`) and, from slice B2 on, from
# the submit/checkpoint synchronization inside a unit of work. No capability
# writes a profile, a class or an availability state.

#: The bounded internal `source_capability` every maintenance event names. Not a
#: `Capability` member: the operator command is configuration, not a capability.
KNOWLEDGE_MAINTENANCE_SOURCE: Final = "knowledge.source_profiles.maintenance"
#: At most this many linked live assertions are mutated per maintenance run
#: (R6 5.1 KLP-R6V-101, 5.4).
MAINTENANCE_BATCH: Final = 128
_RESTRICTED: Final = Classification.RESTRICTED_LOCAL.value
_ACTIVE: Final = KnowledgeAssertionLifecycle.ACTIVE.value


@dataclass(frozen=True, slots=True)
class KnowledgeSourceProfileRecord:
    """One provisioned source profile, as the operator command prints it.

    Holds the scope *digest* only: a native scope identifier is never stored.
    """

    source_profile_id: str
    authenticated_client_id: str
    origin_system: str
    scope_digest: str
    authority_ceiling: str
    direct_admission_enabled: bool
    read_only_proof_state: str
    is_synthetic: bool
    profile_version: int
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeSourceProfileChange:
    """What `apply` did to one profile entry: `created`, `updated` or `unchanged`."""

    action: str
    profile: KnowledgeSourceProfileRecord


@dataclass(frozen=True, slots=True)
class KnowledgeMaintenanceResult:
    """One maintenance run: what it wrote and how much is left for the next run."""

    evidence_ref_ids: tuple[str, ...]
    mutated_assertion_ids: tuple[str, ...]
    remaining: int
    pending: bool = False


class KnowledgeSourceProfileConflictError(ValueError):
    """An active profile binding exists with an immutable field that differs."""


def _profile_record(row: Row[Any]) -> KnowledgeSourceProfileRecord:
    m = row._mapping
    return KnowledgeSourceProfileRecord(
        source_profile_id=m["source_profile_id"],
        authenticated_client_id=m["authenticated_client_id"],
        origin_system=m["origin_system"],
        scope_digest=m["scope_digest"],
        authority_ceiling=m["authority_ceiling"],
        direct_admission_enabled=bool(m["direct_admission_enabled"]),
        read_only_proof_state=m["read_only_proof_state"],
        is_synthetic=bool(m["is_synthetic"]),
        profile_version=int(m["profile_version"]),
        disabled_at=m["disabled_at"],
    )


def _not_before(column: ColumnElement[Any], at: datetime) -> ColumnElement[Any]:
    """`at`, or the stored instant when it is later (the not-earlier triggers)."""
    return case((column > at, column), else_=at)


class _Maintenance:
    """One maintenance body on one transaction's connection (R6 5.1, 5.4, 7, 8.2)."""

    def __init__(
        self, connection: Connection, principal_id: str, stager: RecordEventStager, at: datetime
    ) -> None:
        self.connection = connection
        self._owner = principal_id
        self.context = capture_context(principal_id)
        self.stager = stager
        self.at = at
        self.correlation_id = issue_identifier(IdKind.CORRELATION)

    def _bound(self, table: Table, values: dict[str, object]) -> dict[str, object]:
        return principal_bound_values(values, table, self.context)

    # -- source profiles (C4a) ------------------------------------------------

    def apply_profile(
        self,
        *,
        authenticated_client_id: str,
        origin_system: str,
        scope_digest: str,
        authority_ceiling: str,
        direct_admission_enabled: bool,
        read_only_proof_state: str,
    ) -> KnowledgeSourceProfileChange:
        p = knowledge_discovery_source_profiles
        current = self.connection.execute(
            select(p)
            .where(
                partition_criterion(p, self.context),
                p.c.authenticated_client_id == authenticated_client_id,
                p.c.origin_system == origin_system,
                p.c.scope_digest == scope_digest,
                p.c.disabled_at.is_(None),
            )
            .with_for_update(key_share=True)
        ).one_or_none()
        if current is None:
            row = self.connection.execute(
                insert(p)
                .values(
                    **self._bound(
                        p,
                        {
                            "source_profile_id": issue_identifier(
                                IdKind.KNOWLEDGE_DISCOVERY_SOURCE_PROFILE
                            ),
                            "authenticated_client_id": authenticated_client_id,
                            "origin_system": origin_system,
                            "scope_digest": scope_digest,
                            "authority_ceiling": authority_ceiling,
                            "direct_admission_enabled": direct_admission_enabled,
                            "read_only_proof_state": read_only_proof_state,
                            "is_synthetic": origin_system == "synthetic",
                            "profile_version": 1,
                            "created_at": self.at,
                            "updated_at": self.at,
                        },
                    )
                )
                .returning(p)
            ).one()
            return KnowledgeSourceProfileChange("created", _profile_record(row))
        if current.authority_ceiling != authority_ceiling:
            raise KnowledgeSourceProfileConflictError(
                "an active profile's authority ceiling is immutable; disable it and "
                "provision a new profile"
            )
        if (
            bool(current.direct_admission_enabled) == direct_admission_enabled
            and current.read_only_proof_state == read_only_proof_state
        ):
            return KnowledgeSourceProfileChange("unchanged", _profile_record(current))
        row = self.connection.execute(
            update(p)
            .where(
                partition_criterion(p, self.context),
                p.c.source_profile_id == current.source_profile_id,
            )
            .values(
                direct_admission_enabled=direct_admission_enabled,
                read_only_proof_state=read_only_proof_state,
                profile_version=p.c.profile_version + 1,
                updated_at=_not_before(p.c.updated_at, self.at),
            )
            .returning(p)
        ).one()
        return KnowledgeSourceProfileChange("updated", _profile_record(row))

    def disable_profile(self, source_profile_id: str) -> KnowledgeSourceProfileRecord | None:
        """C4a `FOR NO KEY UPDATE`, re-read `disabled_at`, one terminal UPDATE.

        Disabling deletes no Knowledge row (KLP-AC-090): it sets `disabled_at`
        and clears direct admission together (CHECK
        `knowledge_profile_direct_admission_needs_proof`). `None` when there is
        no active profile of this Principal with that identifier.
        """
        p = knowledge_discovery_source_profiles
        current = self.connection.execute(
            select(p.c.source_profile_id, p.c.disabled_at)
            .where(
                partition_criterion(p, self.context),
                p.c.source_profile_id == source_profile_id,
            )
            .with_for_update(key_share=True)
        ).one_or_none()
        if current is None or current.disabled_at is not None:
            return None
        row = self.connection.execute(
            update(p)
            .where(
                partition_criterion(p, self.context),
                p.c.source_profile_id == source_profile_id,
                p.c.disabled_at.is_(None),
            )
            .values(
                disabled_at=self.at,
                direct_admission_enabled=False,
                profile_version=p.c.profile_version + 1,
                updated_at=_not_before(p.c.updated_at, self.at),
            )
            .returning(p)
        ).one()
        return _profile_record(row)

    def profiles(self) -> tuple[KnowledgeSourceProfileRecord, ...]:
        p = knowledge_discovery_source_profiles
        rows = self.connection.execute(
            select(p)
            .where(partition_criterion(p, self.context))
            .order_by(p.c.created_at, p.c.source_profile_id)
        ).all()
        return tuple(_profile_record(row) for row in rows)

    # -- shared steps ---------------------------------------------------------

    def _lock_evidence(
        self, evidence_ref_ids: Iterable[str], *, nowait: bool = False
    ) -> list[Row[Any]]:
        """C4b: one SELECT, sorted by evidence_ref_id, `FOR UPDATE` (maintenance)."""
        e = knowledge_evidence_refs
        return list(
            self.connection.execute(
                select(
                    e.c.evidence_ref_id,
                    e.c.identity_kind,
                    e.c.source_classification,
                    e.c.availability_state,
                    e.c.availability_revalidation_pending,
                )
                .where(
                    partition_criterion(e, self.context),
                    e.c.evidence_ref_id.in_(sorted(set(evidence_ref_ids))),
                )
                .order_by(e.c.evidence_ref_id)
                .with_for_update(nowait=nowait)
            ).all()
        )

    def _linked(
        self,
        evidence_ref_ids: Sequence[str],
        *,
        lifecycles: Sequence[str],
        below_restricted: bool = False,
    ) -> list[Row[Any]]:
        """Distinct assertions linked (any role) to the rows, sorted by assertion_id."""
        a, links = knowledge_assertions, knowledge_assertion_evidence_links
        criteria: list[ColumnElement[bool]] = [
            partition_criterion(a, self.context),
            a.c.lifecycle.in_(list(lifecycles)),
            exists(
                select(literal(1)).where(
                    partition_criterion(links, self.context),
                    links.c.assertion_id == a.c.assertion_id,
                    links.c.evidence_ref_id.in_(list(evidence_ref_ids)),
                )
            ),
        ]
        if below_restricted:
            criteria.append(classification_rank(a.c.classification) < _RESTRICTED_RANK)
        return list(
            self.connection.execute(
                select(a.c.assertion_id, a.c.subject_kind, a.c.subject_id, a.c.predicate_code)
                .where(*criteria)
                .order_by(a.c.assertion_id)
            ).all()
        )

    def _lock_subjects(self, rows: Sequence[Row[Any]]) -> None:
        """C6: upsert every key of the complete sorted set, then one sorted lock."""
        keys = sorted({(row.subject_kind, row.subject_id, row.predicate_code) for row in rows})
        if not keys:
            return
        locks = knowledge_assertion_subject_locks
        for subject_kind, subject_id, predicate_code in keys:
            self.connection.execute(
                pg_insert(locks)
                .values(
                    **self._bound(
                        locks,
                        {
                            "subject_kind": subject_kind,
                            "subject_id": subject_id,
                            "predicate_code": predicate_code,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        self.connection.execute(
            select(locks.c.predicate_code)
            .where(
                partition_criterion(locks, self.context),
                tuple_(locks.c.subject_kind, locks.c.subject_id, locks.c.predicate_code).in_(keys),
            )
            .order_by(
                locks.c.principal_id,
                locks.c.subject_kind,
                locks.c.subject_id,
                locks.c.predicate_code,
            )
            .with_for_update()
        ).all()

    def _control_mutation(
        self,
        principal_id: str,
        assertion_id: str,
        kind: KnowledgeMutationKind,
        *,
        guard: Sequence[ColumnElement[bool]],
        values: Mapping[str, object],
    ) -> bool:
        """C7/C8/C9 for one control mutation: UPDATE, receipt, staged event.

        `principal_id` is passed down explicitly from the repository method (the
        durable Principal the caller resolved), so the staged event's Principal
        is traceable to its root (RE-AC-103); it must be this body's partition.
        """
        if principal_id != self._owner:
            raise ValueError("a maintenance body writes only its own Principal's partition")
        a = knowledge_assertions
        row = self.connection.execute(
            update(a)
            .where(
                partition_criterion(a, self.context),
                a.c.assertion_id == assertion_id,
                *guard,
            )
            .values(
                version=a.c.version + 1,
                updated_at=_not_before(a.c.updated_at, self.at),
                **values,
            )
            .returning(a.c.version, a.c.classification)
        ).one_or_none()
        if row is None:
            return False
        version = int(row.version)
        mutation_id = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION)
        self.connection.execute(
            insert(knowledge_assertion_mutations).values(
                **self._bound(
                    knowledge_assertion_mutations,
                    {
                        "mutation_id": mutation_id,
                        "assertion_id": assertion_id,
                        "mutation_kind": kind.value,
                        "prior_version": version - 1,
                        "new_version": version,
                        "created_at": self.at,
                    },
                )
            )
        )
        _stage_knowledge_event(
            self.stager,
            principal_id=principal_id,
            assertion_id=assertion_id,
            mutation_kind=kind,
            record_version=version,
            origin=KnowledgeEventOrigin.SERVER_MAINTENANCE,
            source_capability=KNOWLEDGE_MAINTENANCE_SOURCE,
            classification=Classification(row.classification),
            mutation_id=mutation_id,
            at=self.at,
            correlation_id=self.correlation_id,
        )
        return True

    def _mark_revalidation(self, principal_id: str, rows: Sequence[Row[Any]]) -> list[str]:
        a = knowledge_assertions
        marked: list[str] = []
        for row in rows:
            if self._control_mutation(
                principal_id,
                row.assertion_id,
                KnowledgeMutationKind.REVALIDATION_REQUIRED,
                guard=(a.c.lifecycle == _ACTIVE,),
                values={"lifecycle": KnowledgeAssertionLifecycle.REVALIDATION_REQUIRED.value},
            ):
                marked.append(row.assertion_id)
        return marked

    # -- source-classification ingress (R6 5.1, KLP-AC-164, KLP-R6V-201/202) ----

    def _classification_set(self, evidence_ref_id: str) -> list[str]:
        """The named row plus, for an external object, every sibling row of it.

        Siblings: same Principal, same `external_object_id`, and a source profile
        of the same `origin_system` (any profile, scope or version; KLP-R6V-202
        option A: they are raised and redacted in the same run, in the same
        sorted C4b set).
        """
        e, p = knowledge_evidence_refs, knowledge_discovery_source_profiles
        named = self.connection.execute(
            select(
                e.c.evidence_ref_id, e.c.identity_kind, e.c.external_object_id, p.c.origin_system
            )
            .select_from(
                e.outerjoin(
                    p,
                    and_(
                        matching_partition_criterion(p, e),
                        p.c.source_profile_id == e.c.source_profile_id,
                    ),
                )
            )
            .where(partition_criterion(e, self.context), e.c.evidence_ref_id == evidence_ref_id)
        ).one_or_none()
        if named is None:
            raise KnowledgeEvidenceNotFoundError("no evidence row of this Principal")
        if named.identity_kind != _EXTERNAL:
            return [named.evidence_ref_id]
        sibling = cast(Table, knowledge_discovery_source_profiles.alias("ka_classify_profile"))
        siblings = self.connection.execute(
            select(e.c.evidence_ref_id)
            .select_from(
                e.join(
                    sibling,
                    and_(
                        matching_partition_criterion(sibling, e),
                        sibling.c.source_profile_id == e.c.source_profile_id,
                    ),
                )
            )
            .where(
                partition_criterion(e, self.context),
                partition_criterion(sibling, self.context),
                e.c.identity_kind == _EXTERNAL,
                e.c.external_object_id == named.external_object_id,
                sibling.c.origin_system == named.origin_system,
            )
        ).scalars()
        return sorted({named.evidence_ref_id, *siblings})

    def classify_restricted(
        self, principal_id: str, evidence_ref_id: str
    ) -> KnowledgeMaintenanceResult:
        """C4b FOR UPDATE -> one raise+redact UPDATE -> links -> C6 -> <=128 classify.

        Idempotent and resumable: the UPDATE is a no-op for rows already
        restricted, each run classifies at most `MAINTENANCE_BATCH` live linked
        assertions whose stored class is below `restricted_local`, and
        `remaining` counts those still below after this run. It never sets
        `availability_revalidation_pending` and never changes a lifecycle.
        """
        # C4b, KLP-R6V-202 option A: a sibling a submit inserted and held while this
        # waited on the named row is only visible once that submit commits, so the
        # set is re-read under the lock until it is stable. The first lock is the
        # whole set in one sorted statement; a later, grown part may sort below
        # rows already held, so it is taken NOWAIT -- this transaction never
        # *waits* while holding an out-of-order lock, hence never deadlocks with a
        # sorted submit C4b. A held new sibling is a retryable conflict: the
        # caller restarts the transaction, whose first read then has the larger set.
        held: list[str] = []
        locking = self._classification_set(evidence_ref_id)
        while locking:
            try:
                self._lock_evidence(locking, nowait=bool(held))
            except DBAPIError as error:
                if getattr(getattr(error, "orig", None), "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                    raise
                raise TransactionConflictError("a new sibling row is held by a writer") from None
            held = sorted({*held, *locking})
            locking = sorted(set(self._classification_set(evidence_ref_id)) - set(held))
        evidence_ids = held
        e = knowledge_evidence_refs
        # The one UPDATE that raises the class and redacts the excerpt (R6 5.5).
        self.connection.execute(
            update(e)
            .where(
                partition_criterion(e, self.context),
                e.c.evidence_ref_id.in_(evidence_ids),
                classification_rank(e.c.source_classification) < _RESTRICTED_RANK,
            )
            .values(
                source_classification=_RESTRICTED,
                excerpt=null(),
                updated_at=_not_before(e.c.updated_at, self.at),
            )
        )
        below = self._linked(evidence_ids, lifecycles=_LIVE, below_restricted=True)
        batch = below[:MAINTENANCE_BATCH]
        self._lock_subjects(batch)
        # Re-read under C6 (unchanged: every linker waits on the C4b row lock).
        current = {
            row.assertion_id
            for row in self._linked(evidence_ids, lifecycles=_LIVE, below_restricted=True)
        }
        a = knowledge_assertions
        classified = [
            row.assertion_id
            for row in batch
            if row.assertion_id in current
            and self._control_mutation(
                principal_id,
                row.assertion_id,
                KnowledgeMutationKind.CLASSIFY,
                guard=(
                    a.c.lifecycle.in_(_LIVE),
                    classification_rank(a.c.classification) < _RESTRICTED_RANK,
                ),
                values={"classification": _RESTRICTED},
            )
        ]
        remaining = len(self._linked(evidence_ids, lifecycles=_LIVE, below_restricted=True))
        return KnowledgeMaintenanceResult(
            evidence_ref_ids=tuple(evidence_ids),
            mutated_assertion_ids=tuple(classified),
            remaining=remaining,
        )

    # -- availability ingress (R6 5.4, KLP-AC-070/142) -------------------------

    def record_availability(
        self,
        principal_id: str,
        evidence_ref_id: str,
        availability: KnowledgeEvidenceAvailability,
        *,
        verified_at: datetime | None,
    ) -> KnowledgeMaintenanceResult:
        """The single availability ingress. Never touches `source_classification`.

        C4b `FOR UPDATE` on the row -> read links -> sorted C6 (no C3) -> re-read
        links -> each `active` linked assertion becomes `revalidation_required`
        with one mutation, when there are at most 128; above that the row
        commits `availability_revalidation_pending = true` instead and reads
        stay fail-closed until the guarded drain. A restored availability only
        updates the row: it clears neither a lifecycle nor the pending flag.
        """
        locked = self._lock_evidence((evidence_ref_id,))
        if not locked:
            raise KnowledgeEvidenceNotFoundError("no evidence row of this Principal")
        if locked[0].identity_kind != _EXTERNAL:
            raise ValueError("only external evidence carries an availability state")
        e = knowledge_evidence_refs
        changes: dict[str, object] = {
            "availability_state": availability.value,
            "updated_at": _not_before(e.c.updated_at, self.at),
        }
        if verified_at is not None:
            changes["access_last_verified_at"] = verified_at
        lost = availability is not KnowledgeEvidenceAvailability.AVAILABLE
        linked = self._linked([evidence_ref_id], lifecycles=(_ACTIVE,)) if lost else []
        pending = bool(locked[0].availability_revalidation_pending)
        if len(linked) > MAINTENANCE_BATCH:
            changes["availability_revalidation_pending"] = True
            pending = True
        self.connection.execute(
            update(e)
            .where(partition_criterion(e, self.context), e.c.evidence_ref_id == evidence_ref_id)
            .values(**changes)
        )
        if pending and len(linked) > MAINTENANCE_BATCH:
            return KnowledgeMaintenanceResult(
                evidence_ref_ids=(evidence_ref_id,),
                mutated_assertion_ids=(),
                remaining=len(linked),
                pending=True,
            )
        self._lock_subjects(linked)
        current = {
            row.assertion_id for row in self._linked([evidence_ref_id], lifecycles=(_ACTIVE,))
        }
        marked = self._mark_revalidation(
            principal_id, [row for row in linked if row.assertion_id in current]
        )
        return KnowledgeMaintenanceResult(
            evidence_ref_ids=(evidence_ref_id,),
            mutated_assertion_ids=tuple(marked),
            remaining=0,
            pending=pending,
        )

    def drain_revalidation(self, principal_id: str) -> KnowledgeMaintenanceResult:
        """One pending row per run: <=128 marks, then clear the flag only when done.

        One evidence row per transaction, so the run never takes a C4b lock
        after its C6 locks (R6 8.1). `remaining` is the number of evidence rows
        still pending after this run; the operator re-runs until it is 0.
        """
        e = knowledge_evidence_refs
        first = self.connection.execute(
            select(e.c.evidence_ref_id)
            .where(partition_criterion(e, self.context), e.c.availability_revalidation_pending)
            .order_by(e.c.evidence_ref_id)
            .limit(1)
        ).scalar_one_or_none()
        if first is None:
            return KnowledgeMaintenanceResult(
                evidence_ref_ids=(), mutated_assertion_ids=(), remaining=0
            )
        locked = self._lock_evidence((first,))
        marked: list[str] = []
        if locked and locked[0].availability_revalidation_pending:
            linked = self._linked([first], lifecycles=(_ACTIVE,))
            batch = linked[:MAINTENANCE_BATCH]
            self._lock_subjects(batch)
            current = {row.assertion_id for row in self._linked([first], lifecycles=(_ACTIVE,))}
            marked = self._mark_revalidation(
                principal_id, [row for row in batch if row.assertion_id in current]
            )
            if not self._linked([first], lifecycles=(_ACTIVE,)):
                self.connection.execute(
                    update(e)
                    .where(partition_criterion(e, self.context), e.c.evidence_ref_id == first)
                    .values(
                        availability_revalidation_pending=False,
                        updated_at=_not_before(e.c.updated_at, self.at),
                    )
                )
        remaining = int(
            self.connection.execute(
                select(func.count()).where(
                    partition_criterion(e, self.context), e.c.availability_revalidation_pending
                )
            ).scalar_one()
        )
        return KnowledgeMaintenanceResult(
            evidence_ref_ids=(first,),
            mutated_assertion_ids=tuple(marked),
            remaining=remaining,
            pending=remaining > 0,
        )

    # -- seal rotation (R6 7 step 3) -------------------------------------------

    def redact_sealed(self, below_seal: int) -> int:
        """Redact every request envelope sealed below `below_seal`. Idempotent."""
        if isinstance(below_seal, bool) or not 1 <= below_seal <= 32767:
            raise ValueError("the seal version is 1..32767")
        r = knowledge_discovery_checkpoint_requests
        result = self.connection.execute(
            update(r)
            .where(
                partition_criterion(r, self.context),
                r.c.result_private_envelope.is_not(None),
                r.c.result_seal_version < below_seal,
            )
            .values(
                result_private_envelope=null(),
                result_envelope_mac=null(),
                private_token_redacted=True,
            )
        )
        return int(result.rowcount)
