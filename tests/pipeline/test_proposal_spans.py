"""`QC-AC-011`: every proposal points at exact, validated source spans.

Two clauses, and the spec's own wording separates them: "every proposal /
accepted derived record points to **exact validated** source spans"
(`20_…:190`). The plan restates that as "at least one span", which is a
*cardinality* — and a count is not a validation (`D-89`).

**(a) cardinality.** Enforced by a `DEFERRABLE INITIALLY DEFERRED` constraint
trigger (`D-98`), so a proposal with no span is refused **at commit** whether or
not it went through `record_proposal`. That matters because the criterion is the
one most likely to be violated by a future repair script, and a repair script
does not run the application.

**(b) validation.** `span_faults` re-derives each cited span's digest from
`capture_versions.content` — it never compares one stored value against another,
which is why `capture_spans` has no `quoted_text` column at all. The fault is
injected at the persistence layer, because the version itself **cannot be
mutated**: `capture_versions_are_append_only` refuses every `UPDATE`, so the
plan's stated proof method ("mutate a version and re-run") cannot be executed on
this schema at all.

**The accepted-derived-record half of this criterion is NOT proved here, and is
not claimed to be.** `20_…:190` covers "proposal / accepted derived record"; no
accepted record exists until WP-8, so `QC-AC-011` is **half-discharged** by WP-7
and WP-8 must re-prove its other half (`D-89`). Nothing in this module should be
read as evidence for it.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from tests.pipeline.conftest import RICH_NOTE, drain, save

from my_pa.domain.capture.proposal import (
    Proposal,
    ProposalMethod,
    ProposalQuarantineReason,
    ProposalState,
    ProposalType,
    RiskClass,
)
from my_pa.domain.capture.span import SourceSpan, SpanRole
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.capture_pipeline import METHOD_VERSION, SCHEMA_VERSION
from my_pa.infrastructure.persistence.proposals import (
    invalidate_proposal,
    presentable_proposals,
    proposal_count,
    record_proposal,
    record_span,
    span_faults,
)
from my_pa.infrastructure.persistence.tables import (
    capture_proposal_spans,
    capture_proposals,
    capture_spans,
)

pytestmark = pytest.mark.database


def test_every_proposal_the_pipeline_persists_cites_a_span_that_re_derives(
    engine: Engine,
) -> None:
    """The pipeline's own output, checked against the version it came from.

    Both halves in one pass: each proposal has at least one span, and each of
    those spans re-derives from `capture_versions.content` at its own offsets.
    The second is the half the plan's restatement drops.

    A non-empty result is asserted first, because "every proposal cites a span"
    is trivially true of a pipeline that persisted none.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    assert drain(engine).completed == 1

    with engine.connect() as connection:
        proposals = presentable_proposals(connection, saved.version_id)
        assert proposals, "the fixture produced no proposal, so nothing below is checked"
        for proposal_id in proposals:
            cited = int(
                connection.execute(
                    select(func.count())
                    .select_from(capture_proposal_spans)
                    .where(capture_proposal_spans.c.proposal_id == proposal_id)
                ).scalar_one()
            )
            assert cited >= 1, f"{proposal_id} cites no span"
            assert span_faults(connection, proposal_id) == (), (
                f"{proposal_id} cites a span that does not re-derive from the version "
                "it names. The digest is recomputed from `capture_versions.content` "
                "rather than compared against a stored quote, so this is a real "
                "mismatch and not a copy that drifted"
            )


def test_a_proposal_without_a_span_cannot_be_committed(engine: Engine) -> None:
    """`QC-AC-011`(a), against the server rather than against `record_proposal`.

    The insert is made directly, past the function that refuses an empty span
    list, because the criterion has to hold for a writer that does not use it.
    The refusal arrives at `COMMIT` and not at the `INSERT`, which is what
    `DEFERRABLE INITIALLY DEFERRED` means and is what lets a legitimate writer
    insert the proposal before the link row.

    **The control is in this test**: a proposal *with* a span commits, and is
    readable afterwards. Without it, the refusal above would also be satisfied by
    a table nothing can write to at all.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)

    spanless = _proposal(saved.version_id)
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(capture_proposals.insert().values(**_row(spanless)))
    assert "at least one span" in str(refused.value), (
        f"the commit was refused for some other reason: {refused.value}"
    )

    with engine.connect() as connection:
        assert proposal_count(connection, saved.version_id) == 0

    # The control: the same shape, with a span, commits and is readable.
    with engine.begin() as connection:
        span_id = record_span(connection, _span(saved.text, saved.version_id))
        record_proposal(connection, _proposal(saved.version_id), (span_id,))
    with engine.connect() as connection:
        assert proposal_count(connection, saved.version_id) == 1, (
            "a proposal with a span did not commit either, so the refusal above says "
            "nothing about the cardinality rule"
        )


def test_a_span_whose_quoted_hash_does_not_re_derive_quarantines_its_proposal(
    engine: Engine,
) -> None:
    """`QC-AC-011`(b), by persistence-layer injection rather than by mutation.

    The version cannot be changed — `capture_versions_are_append_only` is a
    `BEFORE UPDATE OR DELETE` trigger — so the plan's stated proof method is not
    executable here (`D-89`). What *is* reachable is a span row written with a
    digest that does not re-derive, and all three of the reachable faults are
    exercised so that the distinction between them is shown to be real: a changed
    quote, offsets outside the text, and a span citing another version.

    **The control is in the same test**: a correct span produces no fault and its
    proposal stays presentable. Without it, a `span_faults` that reported
    everything as faulty would pass every assertion above.
    """
    with engine.begin() as connection:
        first = save(connection, RICH_NOTE)
        second = save(connection, "A different note entirely, with its own text.")

    with engine.begin() as connection:
        # The control, written first so a later failure cannot hide it.
        good_span = record_span(connection, _span(first.text, first.version_id))
        good = _proposal(first.version_id)
        record_proposal(connection, good, (good_span,))

        wrong_digest = record_span(
            connection,
            SourceSpan(
                version_id=first.version_id,
                start_offset=0,
                end_offset=6,
                offset_basis=_span(first.text, first.version_id).offset_basis,
                line_start=1,
                column_start=1,
                line_end=1,
                column_end=7,
                quoted_text_sha256=digest_of("text this version does not carry"),
                span_role=SpanRole.DIRECT,
            ),
        )
        outside = record_span(
            connection,
            SourceSpan(
                version_id=first.version_id,
                start_offset=len(first.text) + 10,
                end_offset=len(first.text) + 20,
                offset_basis=_span(first.text, first.version_id).offset_basis,
                line_start=1,
                column_start=1,
                line_end=1,
                column_end=11,
                quoted_text_sha256=digest_of("beyond the end"),
                span_role=SpanRole.DIRECT,
            ),
        )
        other_version = record_span(connection, _span(second.text, second.version_id))

        faulty: dict[ProposalQuarantineReason, str] = {}
        for reason, span_id in (
            (ProposalQuarantineReason.SPAN_TEXT_DOES_NOT_RE_DERIVE, wrong_digest),
            (ProposalQuarantineReason.SPAN_OUTSIDE_VERSION_TEXT, outside),
            (ProposalQuarantineReason.SPAN_CITES_ANOTHER_VERSION, other_version),
        ):
            proposal = _proposal(first.version_id)
            record_proposal(connection, proposal, (span_id,))
            faulty[reason] = proposal.proposal_id

    with engine.connect() as connection:
        assert span_faults(connection, good.proposal_id) == (), (
            "the correct span was reported as a fault, so every assertion below is "
            "about a validator that refuses everything"
        )
        for reason, proposal_id in faulty.items():
            found = span_faults(connection, proposal_id)
            assert len(found) == 1, f"{reason.value} produced {found}"
            assert found[0].reason is reason, (
                f"the fault was reported as {found[0].reason.value} rather than "
                f"{reason.value}. `the quote changed` and `this span belongs to "
                "another version` are different facts and a caller that saw one code "
                "for both could not tell them apart"
            )

    # Quarantine is what the fault means: the proposal is invalidated with its
    # reason recorded, and is excluded from what may be presented — but is not
    # deleted, which would satisfy the criterion by removing the evidence.
    with engine.begin() as connection:
        for reason, proposal_id in faulty.items():
            invalidate_proposal(connection, proposal_id, reason)
            # A retry sees an already-quarantined proposal and is a zero-row
            # update, not an `invalidated -> invalidated` state transition.
            invalidate_proposal(connection, proposal_id, reason)

    with engine.connect() as connection:
        presentable = presentable_proposals(connection, first.version_id)
        assert presentable == (good.proposal_id,), (
            f"presentable proposals are {presentable}; the quarantined ones must be "
            "excluded and the correct one must remain"
        )
        assert proposal_count(connection, first.version_id) == 1 + len(faulty), (
            "a quarantined proposal was deleted rather than invalidated. `AGENTS.md` "
            "section 5 forbids satisfying a constraint by removing the row that "
            "failed it"
        )
        states = connection.execute(
            select(capture_proposals.c.state, capture_proposals.c.quarantine_reason).where(
                capture_proposals.c.proposal_id.in_(tuple(faulty.values()))
            )
        ).all()
        assert {(row.state, row.quarantine_reason) for row in states} == {
            (ProposalState.INVALIDATED.value, reason.value) for reason in faulty
        }


def test_no_span_row_carries_the_quoted_text(engine: Engine) -> None:
    """The structural half of (b): there is no stored quote to compare against.

    `09_LOGICAL_DATA_MODEL.md:185` requires validation to *re-derive* the quoted
    text from the immutable version. Storing the quote beside its digest would
    make that a comparison of two values written together, which passes whenever
    both are wrong — so the column's absence is the mechanism and not an
    omission. Asserted against the live table so that a later revision adding one
    is caught here rather than by a reviewer.
    """
    with engine.begin() as connection:
        save(connection, RICH_NOTE)
    columns = {column.name for column in capture_spans.columns}
    assert "quoted_text_sha256" in columns, "the digest column is what validation compares"
    assert not {name for name in columns if name == "quoted_text" or name.endswith("_quote")}, (
        f"`capture_spans` carries a stored quote: {sorted(columns)}. Validation would "
        "then be a comparison of two stored values rather than a re-derivation"
    )


def _span(text: str, version_id: str) -> SourceSpan:
    """A correct span over the first word of `text`."""
    return SourceSpan.over(text, version_id=version_id, start_offset=0, end_offset=6)


def _proposal(version_id: str) -> Proposal:
    return Proposal(
        proposal_id=issue_identifier(IdKind.PROPOSAL),
        version_id=version_id,
        proposal_type=ProposalType.COMMITMENT,
        state=ProposalState.PROPOSED,
        risk_class=RiskClass.LOW,
        method=ProposalMethod.DETERMINISTIC_RULE,
        method_version=METHOD_VERSION,
        schema_version=SCHEMA_VERSION,
    )


def _row(proposal: Proposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "version_id": proposal.version_id,
        "proposal_type": proposal.proposal_type.value,
        "state": proposal.state.value,
        "risk_class": proposal.risk_class.value,
        "method": proposal.method.value,
        "method_version": proposal.method_version,
        "schema_version": proposal.schema_version,
        "missing_required_fields": [],
    }
