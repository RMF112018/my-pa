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
    not_,
    null,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.sql import text as sql_text

from my_pa.contracts.ports import (
    EvidenceUnavailableError,
    KnowledgeAssertionHistory,
    KnowledgeAssertionPage,
    KnowledgeAssertionRepository,
    KnowledgeAssertionReveal,
    KnowledgeAssertionRow,
    KnowledgeCaptureWithdrawnError,
    KnowledgeConcurrentDuplicateError,
    KnowledgeCreateEvidence,
    KnowledgeCreateRequest,
    KnowledgeEvidenceNotFoundError,
    KnowledgeEvidenceRow,
    KnowledgeIdempotencyConflictError,
    KnowledgeMutationRow,
    KnowledgeSubmissionResult,
    PortError,
    RecordEventStager,
    RepositoryFailureError,
)
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleSelector,
    CaptureLifecycleState,
    CaptureWithdrawnError,
)
from my_pa.domain.common.classification import (
    CLASSIFICATION_RANK,
    Classification,
    classification_max,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.provenance import (
    KNOWLEDGE_EVENT_ACTOR_CLASSES,
    KNOWLEDGE_EVENT_AUTHORITIES,
    KNOWLEDGE_MUTATION_EVENTS,
    KnowledgeEventOrigin,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAssertionLifecycle,
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeEpistemicStatus,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeMutationKind,
    KnowledgeNormalizationRule,
    KnowledgePredicateAdmissionState,
    KnowledgeQualifierRule,
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
    entities,
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_predicates,
    knowledge_assertion_subject_locks,
    knowledge_assertion_submissions,
    knowledge_assertions,
    knowledge_discovery_source_profiles,
    knowledge_evidence_refs,
    knowledge_submission_evidence,
    projects,
    relationship_memory_versions,
)

__all__ = [
    "KNOWLEDGE_CREATE_CAPABILITY",
    "SqlKnowledgeAssertionRepository",
    "assertion_withheld_remote",
    "classification_rank",
    "knowledge_event_withheld_remote",
]

#: The `source_capability` every explicit-create event names.
KNOWLEDGE_CREATE_CAPABILITY: Final = Capability.KNOWLEDGE_ASSERTIONS_CREATE.value
#: `knowledge_classification_rank('restricted_local')`.
_RESTRICTED_RANK: Final = 2
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


def _translated[ResultT](work: Callable[[], ResultT]) -> ResultT:
    """Run one unit of SQL work, translating a store failure (the feed's rule)."""
    try:
        return work()
    except PortError:
        raise
    except (OperationalError, InterfaceError):
        failure: Exception = EvidenceUnavailableError("the store could not be read")
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


def _result_object(result: KnowledgeSubmissionResult) -> dict[str, object]:
    return {
        "assertion_id": result.assertion_id,
        "assertion_version": result.assertion_version,
        "canonical_owner": result.canonical_owner,
        "mutation_id": result.mutation_id,
        "outcome": result.outcome,
        "reason": result.reason,
        "submission_id": result.submission_id,
    }


def _result_digest(result: KnowledgeSubmissionResult) -> str:
    """SHA-256 of the canonical stored public result (`result_digest`)."""
    encoded = json.dumps(_result_object(result), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        """Each cited version, owned and present, with its rank-max class (C2).

        The cited version must exist in this partition with exactly the cited
        digest; its class is the rank-max over *every* version of the capture or
        memory (R6 S-3), read in one statement. An absent and a foreign citation
        are the same `KnowledgeEvidenceNotFoundError`.
        """
        context = capture_context(principal_id)
        observed: dict[KnowledgeCreateEvidence, Classification] = {}
        for item in request.evidence:
            if item.identity_kind == _CAPTURE:
                rows = self._connection.execute(
                    select(
                        capture_versions.c.classification, capture_versions.c.content_sha256
                    ).where(
                        partition_criterion(capture_versions, context),
                        capture_versions.c.capture_id == item.capture_id,
                    )
                ).all()
            else:
                rows = self._connection.execute(
                    select(
                        relationship_memory_versions.c.classification,
                        relationship_memory_versions.c.statement_sha256,
                    ).where(
                        partition_criterion(relationship_memory_versions, context),
                        relationship_memory_versions.c.memory_id == item.relationship_memory_id,
                    )
                ).all()
            if not any(row[1] == item.content_hash for row in rows):
                raise KnowledgeEvidenceNotFoundError("a cited version is not this Principal's")
            observed[item] = classification_max(
                Classification.PRIVATE_LOCAL, *(Classification(row[0]) for row in rows)
            )
        return observed

    def create(
        self,
        principal_id: str,
        request: KnowledgeCreateRequest,
        *,
        at: datetime,
        correlation_id: str,
    ) -> KnowledgeSubmissionResult:
        transaction = _ExplicitCreate(self._connection, principal_id, request, at)
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
            mapped = KNOWLEDGE_MUTATION_EVENTS[KnowledgeMutationKind.CREATE]
            origin = KnowledgeEventOrigin.EXPLICIT_CREATE
            self._record_events.stage(
                RecordEventDraft.issue(
                    principal_id=principal_id,
                    record_family=RecordEventFamily.KNOWLEDGE_ASSERTION,
                    record_id=created.assertion_id,
                    event_kind=mapped.kind,
                    record_version=1,
                    changed_fields=mapped.changed_fields,
                    source_capability=KNOWLEDGE_CREATE_CAPABILITY,
                    actor_class=KNOWLEDGE_EVENT_ACTOR_CLASSES[origin],
                    classification=created.classification,
                    occurred_at=at,
                    source_receipt_id=created.mutation_id,
                    authority=KNOWLEDGE_EVENT_AUTHORITIES[origin],
                    correlation_id=correlation_id,
                )
            )
        return result


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
    ) -> None:
        self.connection = connection
        self.principal_id = principal_id
        self.request = request
        self.at = at
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
        current = None
        if row.result_assertion_id is not None:
            current = self.connection.execute(
                select(knowledge_assertions.c.lifecycle).where(
                    partition_criterion(knowledge_assertions, self.context),
                    knowledge_assertions.c.assertion_id == row.result_assertion_id,
                )
            ).scalar_one_or_none()
        return KnowledgeSubmissionResult(
            submission_id=row.submission_id,
            outcome=row.outcome,
            reason=row.reason,
            assertion_id=row.result_assertion_id,
            assertion_version=row.result_assertion_version,
            mutation_id=row.result_mutation_id,
            canonical_owner=row.result_canonical_owner,
            current_lifecycle=current,
        )

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
            return replace(result, current_lifecycle=self.lifecycle_of(duplicate.assertion_id))
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
        try:
            require_active_capture_roots(
                self.connection, self.context, capture_ids=self._captures()
            )
        except CaptureWithdrawnError:
            raise KnowledgeCaptureWithdrawnError("a cited capture was archived") from None
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
