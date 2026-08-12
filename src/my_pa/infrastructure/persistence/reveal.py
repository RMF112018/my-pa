"""Walking one subject back to the rows that are the evidence for it.

Six statements, and **every one of them is rooted at a table that carries the
Principal partition**, constrained through `principal_scoped` before the join
list is built. That is the difference between a scoped read and a broad read
filtered afterwards: `capture_spans`, `capture_proposals` and
`capture_proposal_spans` carry no partition column of their own, so they are
reachable here only by joining *from* `capture_versions`, whose partition
predicate is already on the statement. `principal_scoped` raises
`UnpartitionedTableError` for a table with no partition column, so a future
statement rooted at one of those three cannot be written through this path at
all — the guard refuses it rather than trusting this module to remember.

**Nothing is filtered in Python.** No statement below reads a row and then
compares an owner; there is no owner comparison in this module, because a
comparison in Python is a comparison that a later refactor can drop while the
tests that only check the returned rows go on passing.

**The subject lookup is the isolation boundary.** A `cap_…` or `asrt_…` that
names another Principal's row produces exactly the same `None` as one that names
nothing: the identifier is compared inside the partitioned statement, so a
foreign subject is not *found and rejected*, it is not found. The caller turns
that into `not_found`, and the two cases are therefore indistinguishable to
anyone holding an identifier they were not given.

**No capture text and no derived value leaves here.** A span carries offsets and
a digest; a proposal carries its method and its type and not its
`normalized_value`; an assertion carries its identifiers and its state and not
its value either. `QC-AC-041` keeps capture content out of the answers a caller
sees most often, and `capture.read` remains the one capability that returns text
under its own audit event.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Select, func, select
from sqlalchemy.engine import Connection

from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.pipeline import PipelineStage, ProcessingState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.reveal import (
    EvidenceGap,
    EvidenceState,
    Reveal,
    RevealedAssertion,
    RevealedProposal,
    RevealedSpan,
    RevealedVersion,
    RevealSubjectKind,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    capture_assertion_spans,
    capture_assertions,
    capture_promotion_receipts,
    capture_proposal_spans,
    capture_proposals,
    capture_review_cases,
    capture_review_decisions,
    capture_spans,
    capture_stage_results,
    capture_versions,
    captures,
)

__all__ = ["reveal_subject", "subject_kind_of"]

#: Which subject prefixes this build's evidence model can walk back from.
_TRAVERSABLE: dict[IdKind, RevealSubjectKind] = {
    IdKind.CAPTURE: RevealSubjectKind.CAPTURE,
    IdKind.ASSERTION: RevealSubjectKind.ASSERTION,
}

#: The stage whose completion means "every proposal this version yields has been
#: written". `PERSIST_PROPOSALS` and not the last stage in `PIPELINE_ORDER`,
#: because `INDEX_CAPTURE_TEXT` runs *before* it and completing the index says
#: nothing about whether proposals were persisted.
_DERIVATION_STAGE = PipelineStage.PERSIST_PROPOSALS


def subject_kind_of(subject_id: str) -> RevealSubjectKind | None:
    """The subject kind this identifier names, or `None` for one not covered.

    `None` here means "this build's evidence model does not reach that plane",
    never "no such thing exists" — the caller turns it into an `unavailable`
    reveal rather than into an absence. The identifier's *shape* has already
    been refused by the command if it was malformed, so a value reaching here
    parses; a prefix outside the covered two is a coverage answer, not a
    validation one.
    """
    kind, _ = parse_identifier(subject_id)
    return _TRAVERSABLE.get(kind)


def _versions(
    connection: Connection, capture_id: str, *, context: PrincipalContext
) -> tuple[RevealedVersion, ...]:
    """The capture's versions, each with how far its derivation stage got.

    The stage result is joined in with an outer join rather than read in a
    second pass, so a version with no stage row at all is `None` here instead of
    being silently absent from the answer — the distinction `RevealedVersion`
    exists to keep.
    """
    latest = connection.execute(
        principal_scoped(
            select(func.max(capture_versions.c.version_number)).where(
                capture_versions.c.capture_id == capture_id
            ),
            capture_versions,
            context,
        )
    ).scalar_one_or_none()
    rows = connection.execute(
        principal_scoped(
            select(
                capture_versions.c.version_id,
                capture_versions.c.version_number,
                capture_versions.c.content_sha256,
                capture_versions.c.recorded_at,
                capture_stage_results.c.processing_state,
            )
            .select_from(
                capture_versions.outerjoin(
                    capture_stage_results,
                    (capture_stage_results.c.version_id == capture_versions.c.version_id)
                    & (capture_stage_results.c.stage == _DERIVATION_STAGE.value),
                )
            )
            .where(capture_versions.c.capture_id == capture_id),
            capture_versions,
            context,
        ).order_by(capture_versions.c.version_number)
    ).all()
    return tuple(
        RevealedVersion(
            version_id=str(row.version_id),
            capture_id=capture_id,
            version_number=int(row.version_number),
            is_current=int(row.version_number) == latest,
            content_sha256=str(row.content_sha256),
            recorded_at=row.recorded_at,
            derivation_state=(
                None if row.processing_state is None else ProcessingState(str(row.processing_state))
            ),
        )
        for row in rows
    )


def _spans(
    connection: Connection, version_ids: tuple[str, ...], *, context: PrincipalContext
) -> tuple[RevealedSpan, ...]:
    """Every span measured against one of these versions, oldest first.

    Rooted at `capture_versions` because `capture_spans` carries no partition
    column: reaching the spans through the partitioned parent is what makes the
    predicate structural rather than a filter this function chose to apply.
    """
    if not version_ids:
        return ()
    rows = connection.execute(
        principal_scoped(
            select(
                capture_spans.c.span_id,
                capture_spans.c.version_id,
                capture_spans.c.start_offset,
                capture_spans.c.end_offset,
                capture_spans.c.offset_basis,
                capture_spans.c.line_start,
                capture_spans.c.column_start,
                capture_spans.c.line_end,
                capture_spans.c.column_end,
                capture_spans.c.quoted_text_sha256,
                capture_spans.c.span_role,
                capture_spans.c.mapping_version,
            )
            .select_from(
                capture_spans.join(
                    capture_versions,
                    capture_versions.c.version_id == capture_spans.c.version_id,
                )
            )
            .where(capture_spans.c.version_id.in_(version_ids)),
            capture_versions,
            context,
        ).order_by(capture_spans.c.created_at, capture_spans.c.span_id)
    ).all()
    return tuple(
        RevealedSpan(
            span_id=str(row.span_id),
            version_id=str(row.version_id),
            start_offset=int(row.start_offset),
            end_offset=int(row.end_offset),
            offset_basis=OffsetBasis(str(row.offset_basis)),
            line_start=int(row.line_start),
            column_start=int(row.column_start),
            line_end=int(row.line_end),
            column_end=int(row.column_end),
            quoted_text_sha256=str(row.quoted_text_sha256),
            span_role=SpanRole(str(row.span_role)),
            mapping_version=None if row.mapping_version is None else str(row.mapping_version),
        )
        for row in rows
    )


def _proposal_span_ids(
    connection: Connection, version_ids: tuple[str, ...], *, context: PrincipalContext
) -> dict[str, tuple[str, ...]]:
    """Which spans each proposal on these versions cites."""
    if not version_ids:
        return {}
    rows = connection.execute(
        principal_scoped(
            select(capture_proposal_spans.c.proposal_id, capture_proposal_spans.c.span_id)
            .select_from(
                capture_proposal_spans.join(
                    capture_proposals,
                    capture_proposals.c.proposal_id == capture_proposal_spans.c.proposal_id,
                ).join(
                    capture_versions,
                    capture_versions.c.version_id == capture_proposals.c.version_id,
                )
            )
            .where(capture_proposals.c.version_id.in_(version_ids)),
            capture_versions,
            context,
        ).order_by(capture_proposal_spans.c.span_id)
    ).all()
    cited: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        cited[str(row.proposal_id)].append(str(row.span_id))
    return {proposal_id: tuple(spans) for proposal_id, spans in cited.items()}


def _proposals(
    connection: Connection,
    version_ids: tuple[str, ...],
    *,
    context: PrincipalContext,
) -> tuple[RevealedProposal, ...]:
    """Every candidate derived from these versions, with its review routing.

    The latest disposition is read as a correlated subquery over the case's own
    decisions, the same way `persistence.review.review_cases` reads it, so the
    two surfaces cannot disagree about what a case currently says.
    """
    if not version_ids:
        return ()
    cited = _proposal_span_ids(connection, version_ids, context=context)
    latest_disposition = (
        select(capture_review_decisions.c.disposition)
        .where(capture_review_decisions.c.review_case_id == capture_review_cases.c.review_case_id)
        .order_by(capture_review_decisions.c.sequence.desc())
        .limit(1)
        .correlate(capture_review_cases)
        .scalar_subquery()
    )
    rows = connection.execute(
        principal_scoped(
            select(
                capture_proposals.c.proposal_id,
                capture_proposals.c.version_id,
                capture_proposals.c.proposal_type,
                capture_proposals.c.state,
                capture_proposals.c.risk_class,
                capture_proposals.c.method,
                capture_proposals.c.method_version,
                capture_proposals.c.schema_version,
                capture_proposals.c.created_at,
                capture_review_cases.c.review_case_id,
                latest_disposition.label("latest_disposition"),
            )
            .select_from(
                capture_proposals.join(
                    capture_versions,
                    capture_versions.c.version_id == capture_proposals.c.version_id,
                ).outerjoin(
                    capture_review_cases,
                    capture_review_cases.c.proposal_id == capture_proposals.c.proposal_id,
                )
            )
            .where(capture_proposals.c.version_id.in_(version_ids)),
            capture_versions,
            context,
        ).order_by(capture_proposals.c.created_at, capture_proposals.c.proposal_id)
    ).all()
    return tuple(
        RevealedProposal(
            proposal_id=str(row.proposal_id),
            version_id=str(row.version_id),
            proposal_type=ProposalType(str(row.proposal_type)),
            state=ProposalState(str(row.state)),
            risk_class=RiskClass(str(row.risk_class)),
            method=str(row.method),
            method_version=str(row.method_version),
            schema_version=str(row.schema_version),
            created_at=row.created_at,
            span_ids=cited.get(str(row.proposal_id), ()),
            review_case_id=(None if row.review_case_id is None else str(row.review_case_id)),
            latest_disposition=(
                None if row.latest_disposition is None else Disposition(str(row.latest_disposition))
            ),
        )
        for row in rows
    )


def _assertion_span_ids(
    connection: Connection, assertion_ids: tuple[str, ...], *, context: PrincipalContext
) -> dict[str, tuple[str, ...]]:
    """Which spans each assertion rests on. Scoped on the link table's own partition."""
    if not assertion_ids:
        return {}
    rows = connection.execute(
        principal_scoped(
            select(capture_assertion_spans.c.assertion_id, capture_assertion_spans.c.span_id).where(
                capture_assertion_spans.c.assertion_id.in_(assertion_ids)
            ),
            capture_assertion_spans,
            context,
        ).order_by(capture_assertion_spans.c.span_id)
    ).all()
    cited: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        cited[str(row.assertion_id)].append(str(row.span_id))
    return {assertion_id: tuple(spans) for assertion_id, spans in cited.items()}


def _assertion_rows(
    connection: Connection,
    statement: Select[tuple],  # type: ignore[type-arg]
    *,
    context: PrincipalContext,
) -> tuple[RevealedAssertion, ...]:
    """Build the accepted records one already-scoped statement selected."""
    rows = connection.execute(statement).all()
    if not rows:
        return ()
    cited = _assertion_span_ids(
        connection, tuple(str(row.assertion_id) for row in rows), context=context
    )
    return tuple(
        RevealedAssertion(
            assertion_id=str(row.assertion_id),
            version_id=str(row.version_id),
            proposal_id=str(row.proposal_id),
            decision_id=str(row.decision_id),
            assertion_type=ProposalType(str(row.assertion_type)),
            state=AssertionState(str(row.state)),
            accepted_at=row.accepted_at,
            span_ids=cited.get(str(row.assertion_id), ()),
            review_case_id=None if row.review_case_id is None else str(row.review_case_id),
            disposition=None if row.disposition is None else Disposition(str(row.disposition)),
            decided_at=row.decided_at,
            receipt_id=None if row.receipt_id is None else str(row.receipt_id),
            policy_version=None if row.policy_version is None else str(row.policy_version),
            revalidation_required_at=row.revalidation_required_at,
        )
        for row in rows
    )


def _assertion_selection() -> Select[tuple]:  # type: ignore[type-arg]
    """The assertion columns and the lineage joined to each, before scoping.

    Left joins throughout: the decision and the case are `NOT NULL` foreign keys
    so they are always present, but the receipt is a separate row written in the
    same transaction, and an assertion that somehow lacks one must be reported
    as lacking one rather than dropped from the answer by an inner join.
    """
    return (
        select(
            capture_assertions.c.assertion_id,
            capture_assertions.c.version_id,
            capture_assertions.c.proposal_id,
            capture_assertions.c.decision_id,
            capture_assertions.c.assertion_type,
            capture_assertions.c.state,
            capture_assertions.c.accepted_at,
            capture_assertions.c.revalidation_required_at,
            capture_review_decisions.c.disposition,
            capture_review_decisions.c.decided_at,
            capture_review_cases.c.review_case_id,
            capture_promotion_receipts.c.receipt_id,
            capture_promotion_receipts.c.policy_version,
        )
        .select_from(
            capture_assertions.outerjoin(
                capture_review_decisions,
                capture_review_decisions.c.decision_id == capture_assertions.c.decision_id,
            )
            .outerjoin(
                capture_review_cases,
                capture_review_cases.c.review_case_id == capture_review_decisions.c.review_case_id,
            )
            .outerjoin(
                capture_promotion_receipts,
                capture_promotion_receipts.c.assertion_id == capture_assertions.c.assertion_id,
            )
        )
        .order_by(capture_assertions.c.accepted_at, capture_assertions.c.assertion_id)
    )


def _state_and_gap(
    versions: tuple[RevealedVersion, ...],
    spans: tuple[RevealedSpan, ...],
    proposed: tuple[RevealedProposal, ...],
    accepted: tuple[RevealedAssertion, ...],
) -> tuple[EvidenceState, EvidenceGap | None]:
    """Which of the three answers the rows in hand actually support.

    The order matters and is the whole control. Evidence first, because rows
    found are rows found whatever the pipeline did afterwards. Then the gap,
    because a scope whose derivation has not completed cannot support "there is
    none". Only what survives both is `NO_EVIDENCE`, which is therefore a
    measurement rather than the default an empty result set falls into.
    """
    if spans or proposed or accepted:
        return EvidenceState.EVIDENCE, None
    if not all(version.derivation_is_complete for version in versions):
        return EvidenceState.UNAVAILABLE, EvidenceGap.DERIVATION_HAS_NOT_COMPLETED
    return EvidenceState.NO_EVIDENCE, None


def _reveal_capture(
    connection: Connection, capture_id: str, *, context: PrincipalContext
) -> Reveal | None:
    """Everything derived from one capture the context's Principal owns."""
    owned = connection.execute(
        principal_scoped(
            select(captures.c.capture_id).where(captures.c.capture_id == capture_id),
            captures,
            context,
        )
    ).scalar_one_or_none()
    if owned is None:
        return None
    versions = _versions(connection, capture_id, context=context)
    version_ids = tuple(version.version_id for version in versions)
    spans = _spans(connection, version_ids, context=context)
    proposed = _proposals(connection, version_ids, context=context)
    accepted = (
        ()
        if not version_ids
        else _assertion_rows(
            connection,
            principal_scoped(
                _assertion_selection().where(capture_assertions.c.version_id.in_(version_ids)),
                capture_assertions,
                context,
            ),
            context=context,
        )
    )
    state, gap = _state_and_gap(versions, spans, proposed, accepted)
    return Reveal(
        subject_id=capture_id,
        subject_kind=RevealSubjectKind.CAPTURE,
        state=state,
        gap=gap,
        capture_id=capture_id,
        versions=versions,
        spans=spans,
        proposed=proposed,
        accepted=accepted,
    )


def _reveal_assertion(
    connection: Connection, assertion_id: str, *, context: PrincipalContext
) -> Reveal | None:
    """One accepted record, the version under it, and the act that promoted it.

    Narrower than the capture traversal on purpose: the question is what this
    assertion rests on, so the answer is its own spans and its own proposal, not
    every candidate its capture ever produced.
    """
    accepted = _assertion_rows(
        connection,
        principal_scoped(
            _assertion_selection().where(capture_assertions.c.assertion_id == assertion_id),
            capture_assertions,
            context,
        ),
        context=context,
    )
    if not accepted:
        return None
    record = accepted[0]
    capture_id = connection.execute(
        principal_scoped(
            select(capture_versions.c.capture_id).where(
                capture_versions.c.version_id == record.version_id
            ),
            capture_versions,
            context,
        )
    ).scalar_one_or_none()
    if capture_id is None:  # pragma: no cover - the FK and the partition agree
        return None
    versions = tuple(
        version
        for version in _versions(connection, str(capture_id), context=context)
        if version.version_id == record.version_id
    )
    spans = _spans(connection, (record.version_id,), context=context)
    cited = tuple(span for span in spans if span.span_id in set(record.span_ids))
    proposed = tuple(
        proposal
        for proposal in _proposals(connection, (record.version_id,), context=context)
        if proposal.proposal_id == record.proposal_id
    )
    return Reveal(
        subject_id=assertion_id,
        subject_kind=RevealSubjectKind.ASSERTION,
        state=EvidenceState.EVIDENCE,
        capture_id=str(capture_id),
        versions=versions,
        spans=cited,
        proposed=proposed,
        accepted=accepted,
    )


def reveal_subject(
    connection: Connection, subject_id: str, *, context: PrincipalContext
) -> Reveal | None:
    """The evidence behind `subject_id`, or `None` when this Principal has none.

    Three outcomes and they are deliberately not the same shape:

    * a subject kind this build does not traverse -> an `unavailable` reveal, so
      the caller is told the plane was not searched rather than shown an empty
      answer about it;
    * a `cap_…` or `asrt_…` that this Principal does not own, or that names
      nothing -> `None`, the same value for both, which is what stops the call
      being an existence oracle;
    * anything else -> the rows, with `EvidenceState` decided by
      `_state_and_gap` from what was actually read.
    """
    kind = subject_kind_of(subject_id)
    if kind is None:
        return Reveal(
            subject_id=subject_id,
            subject_kind=None,
            state=EvidenceState.UNAVAILABLE,
            gap=EvidenceGap.SUBJECT_KIND_NOT_COVERED,
        )
    if kind is RevealSubjectKind.CAPTURE:
        return _reveal_capture(connection, subject_id, context=context)
    return _reveal_assertion(connection, subject_id, context=context)
