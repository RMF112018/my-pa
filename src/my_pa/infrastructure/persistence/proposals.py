"""Writes and reads for the proposal plane: stages, text, spans, and proposals.

Free functions over a `Connection`, with the caller owning the transaction —
the same shape `persistence.capture` and `persistence.jobs` take, and for the
reason `contracts.ports` gives: the transaction boundary belongs to the
application, so nothing here opens or commits one.

**Validation re-derives; it never compares two stored values.**
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:185` requires a span's quoted
text to be re-derived from the immutable source version, and a mismatch to
quarantine the proposal that cites it. `capture_spans` therefore stores a digest
and not a quote, and `span_faults` recomputes the digest from
`capture_versions.content` — a column a `BEFORE UPDATE OR DELETE` trigger makes
immutable. That immutability is why the specification's own suggested proof,
"mutate a version and re-run", cannot be executed here: no writer, including a
test, can update a stored version. The reachable faults are the three
`ProposalQuarantineReason` members, and each is produced by writing a span that
does not hold rather than by changing text that does.

**A quarantined proposal is not deleted and its spans are not rewritten.** The
row stays, its state becomes `invalidated`, and the reason is recorded beside
it, which is `AGENTS.md` section 5's rule that a defect is named rather than
laundered. `presentable_proposals` is the read that excludes them, so the
difference between "quarantined" and "absent" survives into what a caller sees.

**Nothing here writes an error message, a fragment of capture text, or a
locator.** Every value crossing these functions is an opaque identifier, an
enumerated code, a bounded token, a digest, a count, or a timestamp — except
`normalized_text`, which is `P-02`'s processing text and is one of the schema's
three declared content columns.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.domain.capture.classification import (
    CaptureClassification,
    CaptureEntityMention,
)
from my_pa.domain.capture.pipeline import PipelineStage, ProcessingState
from my_pa.domain.capture.proposal import (
    Proposal,
    ProposalQuarantineReason,
    ProposalState,
)
from my_pa.domain.capture.span import SourceSpan
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    capture_classifications,
    capture_entity_mentions,
    capture_processing_text,
    capture_proposal_spans,
    capture_proposals,
    capture_spans,
    capture_stage_results,
    capture_versions,
)

__all__ = [
    "OffsetMapping",
    "SpanFault",
    "StageOutcome",
    "invalidate_proposal",
    "presentable_proposals",
    "record_classification",
    "record_entity_mention",
    "record_processing_text",
    "record_proposal",
    "record_span",
    "record_stage_result",
    "span_faults",
    "stage_result_for",
    "version_content",
]


@dataclass(frozen=True, slots=True)
class OffsetMapping:
    """`P-02`'s reversible mapping, as runs rather than as one pair per character.

    Conservative normalization is piecewise affine — a run of characters shifts
    by a constant — so three parallel arrays describe it exactly. A per-character
    array would be a hundred thousand integers for a transformation that changes
    almost nothing, and it would not be any more reversible.

    `original_offset_of` is the reverse direction, and it exists here rather
    than in a caller because a mapping whose inverse is computed differently by
    each reader is a mapping with more than one meaning.
    """

    normalized_starts: tuple[int, ...]
    original_starts: tuple[int, ...]
    lengths: tuple[int, ...]

    def __post_init__(self) -> None:
        counts = {len(self.normalized_starts), len(self.original_starts), len(self.lengths)}
        if len(counts) != 1:
            raise ValueError("an offset mapping states one original start and length per run")
        if not self.lengths:
            raise ValueError("an offset mapping covers at least one run")
        previous = -1
        for start, origin, length in zip(
            self.normalized_starts, self.original_starts, self.lengths, strict=True
        ):
            if start < 0 or origin < 0 or length < 1:
                raise ValueError("an offset mapping run is non-negative and non-empty")
            if start <= previous:
                raise ValueError("offset mapping runs are ordered and do not overlap")
            previous = start + length - 1

    def original_offset_of(self, normalized_offset: int) -> int:
        """The offset in the original text that `normalized_offset` came from.

        Raises rather than clamping or returning the input unchanged. A mapping
        asked about an offset it does not cover has been given an offset from a
        different text, and answering with a plausible number would attribute a
        span to bytes the mapping never saw.
        """
        for start, origin, length in zip(
            self.normalized_starts, self.original_starts, self.lengths, strict=True
        ):
            if start <= normalized_offset < start + length:
                return origin + (normalized_offset - start)
        raise ValueError("the offset lies outside this mapping")


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One stage result as a replay read sees it.

    `created` false means the stage had already completed under this exact key,
    so the correct answer is the one the first run produced — `11_…:212`'s "a
    completed stage with the same key returns the prior output", answered
    without comparing outputs.
    """

    stage_result_id: str
    stage: PipelineStage
    processing_state: ProcessingState
    output_sha256: str | None
    output_row_count: int
    created: bool


@dataclass(frozen=True, slots=True)
class SpanFault:
    """One span that does not hold against the version its proposal cites."""

    span_id: str
    reason: ProposalQuarantineReason


def version_content(connection: Connection, version_id: str) -> str | None:
    """The stored text of one capture version, or `None`.

    The one read in this module that returns capture content, and it exists so
    that validation re-derives from the version rather than from anything a
    writer stored beside it.
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    row = connection.execute(
        select(capture_versions.c.content).where(capture_versions.c.version_id == version_id)
    ).one_or_none()
    return None if row is None else str(row[0])


def record_processing_text(
    connection: Connection,
    *,
    version_id: str,
    normalized_text: str,
    normalization_version: str,
    mapping: OffsetMapping,
    language: str | None = None,
) -> str:
    """Store `P-02`'s output for one version, and return its identifier.

    The digest is computed here from the text being stored, so a caller cannot
    file text under a hash of something else — the same rule
    `domain.capture.version.digest_of` states for the original.
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    processing_text_id = issue_identifier(IdKind.PROCESSING_TEXT)
    connection.execute(
        capture_processing_text.insert().values(
            processing_text_id=processing_text_id,
            version_id=version_id,
            normalization_version=normalization_version,
            normalized_text=normalized_text,
            normalized_sha256=digest_of(normalized_text),
            language=language,
            run_normalized_start=list(mapping.normalized_starts),
            run_original_start=list(mapping.original_starts),
            run_length=list(mapping.lengths),
        )
    )
    return processing_text_id


def record_span(
    connection: Connection, span: SourceSpan, *, processing_text_id: str | None = None
) -> str:
    """Store one span and return its identifier.

    Takes an already-built `SourceSpan` rather than offsets, because `over`
    derives the digest and the four line and column values from one text and
    this function has no text to derive them from. That is deliberate: the
    fault this plane must be able to represent is a span whose digest does not
    re-derive, so the writer has to be able to store one, and `span_faults` is
    what finds it rather than a refusal here that would make the fault
    unreachable and `QC-AC-011` unprovable.
    """
    span_id = issue_identifier(IdKind.SPAN)
    connection.execute(
        capture_spans.insert().values(
            span_id=span_id,
            version_id=span.version_id,
            processing_text_id=processing_text_id,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            offset_basis=span.offset_basis.value,
            line_start=span.line_start,
            column_start=span.column_start,
            line_end=span.line_end,
            column_end=span.column_end,
            quoted_text_sha256=span.quoted_text_sha256,
            span_role=span.span_role.value,
            mapping_version=span.mapping_version,
        )
    )
    return span_id


def record_stage_result(
    connection: Connection,
    *,
    version_id: str,
    operation_id: str,
    stage: PipelineStage,
    pipeline_version: str,
    stage_config_sha256: str,
    idempotency_key: str,
    processing_state: ProcessingState,
    output_sha256: str | None = None,
    output_row_count: int = 0,
    completed_at: datetime | None = None,
) -> StageOutcome:
    """Store one stage result, or return the one already stored under its key.

    `ON CONFLICT DO NOTHING` against `a_stage_key_admits_one_result`, so two
    workers racing the same stage produce one row and the loser reads the
    winner's. Enforcing that in Python alone would leave both able to read
    "absent" and both insert, which is the same argument
    `a_capture_key_admits_one_submission` makes for a save.
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    validate_identifier(operation_id, IdKind.OPERATION)
    stage_result_id = issue_identifier(IdKind.STAGE_RESULT)
    inserted = connection.execute(
        pg_insert(capture_stage_results)
        .values(
            stage_result_id=stage_result_id,
            version_id=version_id,
            operation_id=operation_id,
            stage=stage.value,
            pipeline_version=pipeline_version,
            stage_config_sha256=stage_config_sha256,
            idempotency_key=idempotency_key,
            processing_state=processing_state.value,
            output_sha256=output_sha256,
            output_row_count=output_row_count,
            completed_at=completed_at,
        )
        .on_conflict_do_nothing(constraint="a_stage_key_admits_one_result")
        .returning(capture_stage_results.c.stage_result_id)
    ).one_or_none()
    if inserted is not None:
        return StageOutcome(
            stage_result_id=stage_result_id,
            stage=stage,
            processing_state=processing_state,
            output_sha256=output_sha256,
            output_row_count=output_row_count,
            created=True,
        )
    prior = stage_result_for(connection, idempotency_key)
    if prior is None:  # pragma: no cover - the conflict says the row is there
        raise RuntimeError("a stage key conflicted with a result that cannot be read back")
    return prior


def stage_result_for(connection: Connection, idempotency_key: str) -> StageOutcome | None:
    """The stage result stored under `idempotency_key`, or `None`."""
    row = connection.execute(
        select(
            capture_stage_results.c.stage_result_id,
            capture_stage_results.c.stage,
            capture_stage_results.c.processing_state,
            capture_stage_results.c.output_sha256,
            capture_stage_results.c.output_row_count,
        ).where(capture_stage_results.c.idempotency_key == idempotency_key)
    ).one_or_none()
    if row is None:
        return None
    return StageOutcome(
        stage_result_id=str(row.stage_result_id),
        stage=PipelineStage(row.stage),
        processing_state=ProcessingState(row.processing_state),
        output_sha256=None if row.output_sha256 is None else str(row.output_sha256),
        output_row_count=int(row.output_row_count),
        created=False,
    )


def record_proposal(connection: Connection, proposal: Proposal, span_ids: Sequence[str]) -> str:
    """Store one proposal and the spans it cites, in that order.

    The order is forced by the foreign key and the cardinality is forced by a
    deferred constraint trigger: a proposal with no span is refused **at
    commit**, not here, so a caller cannot avoid the rule by writing the rows in
    another order or by taking a savepoint. This function still refuses an empty
    list, because failing at the call site names the defect where it was made;
    the server's refusal is what catches the caller that does not use this
    function.
    """
    if not span_ids:
        raise ValueError("a proposal cites at least one span")
    connection.execute(
        capture_proposals.insert().values(
            proposal_id=proposal.proposal_id,
            version_id=proposal.version_id,
            proposal_type=proposal.proposal_type.value,
            state=proposal.state.value,
            risk_class=proposal.risk_class.value,
            method=proposal.method.value,
            method_version=proposal.method_version,
            schema_version=proposal.schema_version,
            missing_required_fields=[field.value for field in proposal.missing_fields],
            normalized_value=proposal.normalized_value,
            quarantine_reason=(
                None if proposal.quarantine_reason is None else proposal.quarantine_reason.value
            ),
            accepted_record_type=proposal.accepted_record_type,
            accepted_record_id=proposal.accepted_record_id,
        )
    )
    connection.execute(
        capture_proposal_spans.insert(),
        [{"proposal_id": proposal.proposal_id, "span_id": span_id} for span_id in span_ids],
    )
    return proposal.proposal_id


def record_classification(connection: Connection, classification: CaptureClassification) -> str:
    """Store one deterministic label, with the span it was derived from."""
    connection.execute(
        capture_classifications.insert().values(
            classification_id=classification.classification_id,
            version_id=classification.version_id,
            span_id=classification.span_id,
            scheme=classification.scheme,
            scheme_version=classification.scheme_version,
            label=classification.label.value,
            rule=classification.rule,
            rule_version=classification.rule_version,
        )
    )
    return classification.classification_id


def record_entity_mention(connection: Connection, mention: CaptureEntityMention) -> str:
    """Store one unresolved deterministic mention, bound to its span."""
    connection.execute(
        capture_entity_mentions.insert().values(
            mention_id=mention.mention_id,
            version_id=mention.version_id,
            span_id=mention.span_id,
            entity_type=mention.entity_type.value,
            resolution_state=mention.resolution_state.value,
        )
    )
    return mention.mention_id


def span_faults(connection: Connection, proposal_id: str) -> tuple[SpanFault, ...]:
    """Every cited span of `proposal_id` that does not hold, and why.

    Re-derives each span's digest from `capture_versions.content` rather than
    comparing two stored values, which is the only form of this check that can
    fail for the reason `09_LOGICAL_DATA_MODEL.md:185` names. Three faults are
    reachable and each is distinguished, because "the quote changed" and "this
    span belongs to another version" are different facts about the same absence
    and a caller that saw one code for both could not tell them apart.

    Returns an empty tuple for a proposal whose spans all hold. That zero is
    only meaningful beside a non-zero, which is why the test that asserts it
    also asserts a faulty span in the same fixture.
    """
    validate_identifier(proposal_id, IdKind.PROPOSAL)
    rows = connection.execute(
        select(
            capture_spans.c.span_id,
            capture_spans.c.version_id,
            capture_spans.c.start_offset,
            capture_spans.c.end_offset,
            capture_spans.c.quoted_text_sha256,
            capture_proposals.c.version_id.label("proposal_version_id"),
        )
        .select_from(
            capture_proposals.join(
                capture_proposal_spans,
                capture_proposal_spans.c.proposal_id == capture_proposals.c.proposal_id,
            ).join(
                capture_spans,
                capture_spans.c.span_id == capture_proposal_spans.c.span_id,
            )
        )
        .where(capture_proposals.c.proposal_id == proposal_id)
    ).all()

    faults: list[SpanFault] = []
    contents: dict[str, str | None] = {}
    for row in rows:
        span_id = str(row.span_id)
        if str(row.version_id) != str(row.proposal_version_id):
            faults.append(SpanFault(span_id, ProposalQuarantineReason.SPAN_CITES_ANOTHER_VERSION))
            continue
        version_id = str(row.version_id)
        if version_id not in contents:
            contents[version_id] = version_content(connection, version_id)
        content = contents[version_id]
        if content is None or int(row.end_offset) > len(content):
            faults.append(SpanFault(span_id, ProposalQuarantineReason.SPAN_OUTSIDE_VERSION_TEXT))
            continue
        derived = digest_of(content[int(row.start_offset) : int(row.end_offset)])
        if derived != str(row.quoted_text_sha256):
            faults.append(SpanFault(span_id, ProposalQuarantineReason.SPAN_TEXT_DOES_NOT_RE_DERIVE))
    return tuple(faults)


def invalidate_proposal(
    connection: Connection, proposal_id: str, reason: ProposalQuarantineReason
) -> None:
    """Move one proposal to `invalidated` and record why.

    An update rather than a delete, and the rows it cites are left where they
    are. Deleting the proposal would satisfy the criterion by removing the
    evidence that it failed, which is the one repair `AGENTS.md` section 5 names
    outright; the constraint the schema carries states the same rule, so a
    hand-run statement that set the state without the reason is refused too.
    """
    validate_identifier(proposal_id, IdKind.PROPOSAL)
    connection.execute(
        capture_proposals.update()
        .where(capture_proposals.c.proposal_id == proposal_id)
        .values(state=ProposalState.INVALIDATED.value, quarantine_reason=reason.value)
    )


def presentable_proposals(connection: Connection, version_id: str) -> tuple[str, ...]:
    """The proposals of `version_id` that may be shown, newest first.

    `invalidated` is excluded here and nowhere else, so "quarantined" and
    "absent" stay different facts: the row is still readable by anything that
    asks for it by identifier, and `span_faults` still says why it failed.
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    rows = connection.execute(
        select(capture_proposals.c.proposal_id)
        .where(
            capture_proposals.c.version_id == version_id,
            capture_proposals.c.state != ProposalState.INVALIDATED.value,
        )
        .order_by(capture_proposals.c.created_at.desc(), capture_proposals.c.proposal_id)
    ).all()
    return tuple(str(row[0]) for row in rows)


def proposal_count(connection: Connection, version_id: str, *, states: Iterable[str] = ()) -> int:
    """How many proposals `version_id` holds, optionally in `states`.

    A count rather than a stored column on `captures`: a counter there would
    need an `UPDATE` path on a table that has none, and would be a second
    statement of a fact these rows already hold (`D-48`'s carve-out is about new
    tables, and `captures` is not one).
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    statement = (
        select(func.count())
        .select_from(capture_proposals)
        .where(capture_proposals.c.version_id == version_id)
    )
    wanted = tuple(states)
    if wanted:
        statement = statement.where(capture_proposals.c.state.in_(wanted))
    return int(connection.execute(statement).scalar_one())
