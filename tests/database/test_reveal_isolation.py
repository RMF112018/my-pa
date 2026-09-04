"""Reveal at the row: one Principal's evidence is never another's to read.

**The level this proves, stated first, because the level is the claim.** This is
a *repository-boundary* proof against a live PostgreSQL server. It is not
end-to-end: `D-15` pins the web tier to exactly one Principal under
`local_operator`, so two identities cannot hold sessions while the backend
serves, and an end-to-end two-identity claim is not constructible at this head.
What is constructible — and what is here — is the boundary where the rows
actually live: two Principals, both with stored evidence, and every reveal issued
for one under the other's context.

Three properties, and the second is the one that matters most:

1. **A foreign subject is not returned.** A's capture, revealed under B's
   context, comes back `None`.
2. **A foreign subject is indistinguishable from an absent one.** `None` is the
   same value a `cap_…` that names nothing produces, so a caller holding an
   identifier it was not given learns nothing by asking — not even that the
   identifier exists. An implementation that raised "forbidden" for one and
   "not found" for the other would pass property 1 and fail here, which is why
   the two are separate tests.
3. **"We could not search" is not "we searched and found nothing."** A capture
   whose derivation stage has not completed answers `unavailable` with a gap; a
   capture whose stage completed with nothing derived answers `no_evidence`.
   Both carry no rows, so nothing but the state distinguishes them — which is
   exactly why the state exists.

Every claim is measured against rows written by the production writers —
`admit_capture`, `record_span`, `record_proposal`, `record_stage_result`,
`open_review_case`, `decide_review` — rather than by hand-built `INSERT`s, so
what is revealed is what the product can actually produce. The non-zero control
sits beside every negative: A's own reveal returns evidence in the same test that
B's returns nothing, so an empty answer is a partition and not an empty table.

**Every value here is synthetic.** Two invented opaque Principals, one invented
sentence of capture text, and a disposable database this module creates and drops
— never the configured one, because `downgrade base` deletes schemas.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

from my_pa.contracts.ports import CaptureAdmissionRequest, ReviewDecisionRequest
from my_pa.domain.capture.pipeline import PipelineStage, ProcessingState
from my_pa.domain.capture.proposal import (
    Proposal,
    ProposalMethod,
    ProposalState,
    ProposalType,
    RiskClass,
)
from my_pa.domain.capture.reveal import EvidenceGap, EvidenceState, RevealSubjectKind
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import SourceSpan, SpanRole
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy, digest_of
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.proposals import (
    record_proposal,
    record_span,
    record_stage_result,
)
from my_pa.infrastructure.persistence.reveal import reveal_subject
from my_pa.infrastructure.persistence.review import decide_review, open_review_case

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE: Final = "my_pa_reveal_isolation_test"

#: Two invented opaque identifiers, well-formed under the `^prn_…$` CHECK. A is
#: the writer; B is the Principal whose every read must come back empty.
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: One synthetic sentence. The spans below are offsets into exactly this string.
TEXT: Final = "Pour the north slab on Tuesday and confirm the mix design."

#: A commitment proposal routes to review (`routes_to_review`), which is what
#: lets the promoted-assertion half of this module exist at all.
COMMITMENT_START: Final = 0
COMMITMENT_END: Final = 22

#: The moment this module's synthetic captures were admitted and decided.
#:
#: **Derived from the clock, not written down as a date.** It was
#: `datetime(2026, 8, 10, 12, 0, tzinfo=UTC)` — an absolute literal that was in
#: the future when it was written and stopped being so at noon UTC on that day,
#: at which point every test in this file began erroring in fixture setup. The
#: mechanism is `_complete_derivation` below and is written out there; the
#: mechanism *here* is simply that a calendar literal in a test is a fuse, and
#: the only fix that cannot burn twice is to stop having one.
#:
#: An hour behind the run, rather than at it, so that these instants are
#: unambiguously in the past for any reader and for any future constraint that
#: cares whether a recorded moment has happened. Nothing at this head compares
#: an admission or a decision against `now()` — the only time-ordering CHECK
#: these writers can reach is `a_stage_completes_after_it_starts` — so the offset
#: buys clarity rather than correctness, and the correctness is bought where the
#: constraint actually is.
WHEN: Final = datetime.now(UTC) - timedelta(hours=1)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    created = create_database_engine(disposable_database)
    try:
        yield created
    finally:
        created.dispose()


def _admit(connection: object, principal_id: str, key: str) -> str:
    """One capture written by the production writer. Returns its `cap_…`."""
    admission = admit_capture(
        connection,  # type: ignore[arg-type]
        CaptureAdmissionRequest(
            capture_id=None,
            content=CaptureContent(TEXT),
            idempotency_key=key,
            request_id=f"req-{key}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            principal_id=principal_id,
            audit_id=issue_identifier(IdKind.AUDIT),
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=WHEN,
            accepted_at=WHEN,
        ),
        context=capture_context(principal_id),
    )
    return admission.receipt.capture_id


def _operation_of(connection: object, version_id: str) -> str:
    return str(
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT operation_id FROM knowledge.capture_jobs WHERE version_id = :v"),
            {"v": version_id},
        ).scalar_one()
    )


def _version_of(connection: object, capture_id: str) -> str:
    return str(
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT version_id FROM knowledge.capture_versions WHERE capture_id = :c"),
            {"c": capture_id},
        ).scalar_one()
    )


def _complete_derivation(connection: object, version_id: str, *, key: str) -> None:
    """Record the stage whose completion means "the proposals are all written".

    **The completion instant is the server's own transaction timestamp, and that
    is what makes this row valid by construction rather than by luck.**
    `capture_stage_results` carries `CHECK (completed_at IS NULL OR completed_at
    >= started_at)` — `a_stage_completes_after_it_starts` — and `started_at` has
    no parameter on `record_stage_result`: it is filled by the column's
    `server_default=now()` at `INSERT`. So the only completion this test can
    supply that the constraint will accept is one at or after the moment the
    server assigns.

    Reading `now()` here, on the same connection and inside the same
    transaction, produces *exactly* that moment: PostgreSQL's `now()` is
    `transaction_timestamp()`, fixed for the life of the transaction, so the
    value read a statement earlier is the identical value the default will
    write. `completed_at == started_at` satisfies a `>=` constraint with no
    margin, no clock-skew assumption between this process and the server, and
    nothing in the future.

    This replaces a hardcoded `datetime(2026, 8, 10, 12, 0, tzinfo=UTC)`. That
    literal was ahead of the wall clock when it was written, so `completed_at`
    was comfortably after the `started_at` the server was assigning — until the
    wall clock passed it, at which point every capture this module writes
    violated the CHECK and all six tests died in setup. A relative instant with a
    fixed forward margin would only have moved the fuse; the transaction
    timestamp removes it, because the two values are then the same value.
    """
    completed_at = connection.execute(text("SELECT now()")).scalar_one()  # type: ignore[attr-defined]
    record_stage_result(
        connection,  # type: ignore[arg-type]
        version_id=version_id,
        operation_id=_operation_of(connection, version_id),
        stage=PipelineStage.PERSIST_PROPOSALS,
        pipeline_version="p1",
        stage_config_sha256=digest_of(f"config-{key}"),
        idempotency_key=digest_of(f"stage-{key}"),
        processing_state=ProcessingState.COMPLETE,
        completed_at=completed_at,
    )


def _derive_commitment(connection: object, version_id: str) -> str:
    """One span and the commitment proposal citing it. Returns the `prop_…`."""
    span = SourceSpan.over(
        TEXT,
        version_id=version_id,
        start_offset=COMMITMENT_START,
        end_offset=COMMITMENT_END,
        span_role=SpanRole.DIRECT,
    )
    span_id = record_span(connection, span)  # type: ignore[arg-type]
    proposal = Proposal(
        proposal_id=issue_identifier(IdKind.PROPOSAL),
        version_id=version_id,
        proposal_type=ProposalType.COMMITMENT,
        state=ProposalState.PROPOSED,
        risk_class=RiskClass.HIGH,
        method=ProposalMethod.DETERMINISTIC_RULE,
        method_version="m1",
        schema_version="s1",
        normalized_value="pour the north slab",
    )
    return record_proposal(connection, proposal, [span_id])  # type: ignore[arg-type]


@pytest.fixture
def evidence(engine: Engine) -> dict[str, str]:
    """A's capture with a promoted assertion, and B's capture with its own.

    Both Principals hold real evidence, which is what makes the negative reads
    below a partition rather than an empty database.
    """
    identifiers: dict[str, str] = {}
    with engine.begin() as connection:
        for label, principal_id in (("a", PRINCIPAL_A), ("b", PRINCIPAL_B)):
            capture_id = _admit(connection, principal_id, f"reveal-{label}")
            version_id = _version_of(connection, capture_id)
            proposal_id = _derive_commitment(connection, version_id)
            _complete_derivation(connection, version_id, key=label)
            review_case_id = open_review_case(connection, proposal_id)
            assert review_case_id is not None, "a commitment routes to review"
            decision = decide_review(
                connection,
                ReviewDecisionRequest(
                    review_case_id=review_case_id,
                    expected_review_version=0,
                    disposition=Disposition.ACCEPT,
                    principal_id=principal_id,
                    correlation_id=issue_identifier(IdKind.CORRELATION),
                    audit_id=issue_identifier(IdKind.AUDIT),
                    policy_version="policy-v1",
                    decided_at=WHEN,
                ),
            )
            assert decision is not None and decision.assertion_id is not None
            identifiers[f"{label}_capture"] = capture_id
            identifiers[f"{label}_version"] = version_id
            identifiers[f"{label}_assertion"] = decision.assertion_id
    return identifiers


def test_a_capture_reveals_its_own_spans_versions_and_derivation_trace(
    engine: Engine, evidence: dict[str, str]
) -> None:
    """The non-zero control, and control 6: exact spans tied back to a version.

    Everything the acceptance criterion asks a result to identify is asserted
    here by name: the authority (the promoted assertion's decision and receipt),
    the version each offset is counted in, the source span itself, and the
    coverage of the scope that was searched.
    """
    with engine.connect() as connection:
        revealed = reveal_subject(
            connection, evidence["a_capture"], context=capture_context(PRINCIPAL_A)
        )

    assert revealed is not None
    assert revealed.state is EvidenceState.EVIDENCE
    assert revealed.gap is None
    assert revealed.subject_kind is RevealSubjectKind.CAPTURE
    assert revealed.capture_id == evidence["a_capture"]

    # The version, and the coverage of the scope that was searched.
    assert [version.version_id for version in revealed.versions] == [evidence["a_version"]]
    assert revealed.versions[0].is_current is True
    assert revealed.versions_with_completed_derivation == 1

    # The span, exact: the offsets that were written, the version they are
    # counted in, and the digest of the slice — re-derived here from the same
    # synthetic text, which is what makes it a citation rather than a label.
    assert len(revealed.spans) == 1
    span = revealed.spans[0]
    assert span.version_id == evidence["a_version"]
    assert (span.start_offset, span.end_offset) == (COMMITMENT_START, COMMITMENT_END)
    assert span.quoted_text_sha256 == digest_of(TEXT[COMMITMENT_START:COMMITMENT_END])
    assert span.character_count == COMMITMENT_END - COMMITMENT_START

    # Proposed and accepted are separate collections, and the accepted record
    # carries the whole derivation trace.
    assert len(revealed.proposed) == 1
    assert revealed.proposed[0].review_case_id is not None
    assert revealed.proposed[0].latest_disposition is Disposition.ACCEPT
    assert len(revealed.accepted) == 1
    accepted = revealed.accepted[0]
    assert accepted.assertion_id == evidence["a_assertion"]
    assert accepted.proposal_id == revealed.proposed[0].proposal_id
    assert accepted.review_case_id == revealed.proposed[0].review_case_id
    assert accepted.disposition is Disposition.ACCEPT
    assert accepted.receipt_id is not None
    assert accepted.policy_version == "policy-v1"
    assert accepted.span_ids == (span.span_id,)

    # And nothing in the answer is the capture's text.
    assert TEXT not in repr(revealed)


def test_a_capture_belonging_to_another_principal_is_not_revealed(
    engine: Engine, evidence: dict[str, str]
) -> None:
    """Cross-Principal isolation at the query. A's capture is nothing to B.

    The control is in the same test: B holds evidence of its own and reveals it,
    so B's empty answer for A's capture is a partition rather than a Principal
    with nothing stored.
    """
    with engine.connect() as connection:
        foreign = reveal_subject(
            connection, evidence["a_capture"], context=capture_context(PRINCIPAL_B)
        )
        own = reveal_subject(
            connection, evidence["b_capture"], context=capture_context(PRINCIPAL_B)
        )

    assert foreign is None
    assert own is not None and own.state is EvidenceState.EVIDENCE


def test_a_foreign_subject_is_indistinguishable_from_one_that_does_not_exist(
    engine: Engine, evidence: dict[str, str]
) -> None:
    """No existence disclosure: the two absences are one value.

    Asserted for both subject kinds, because the assertion traversal roots at a
    different table from the capture traversal and could have been written to
    refuse differently.
    """
    absent_capture = issue_identifier(IdKind.CAPTURE)
    absent_assertion = issue_identifier(IdKind.ASSERTION)
    with engine.connect() as connection:
        context = capture_context(PRINCIPAL_B)
        answers = {
            "foreign capture": reveal_subject(connection, evidence["a_capture"], context=context),
            "absent capture": reveal_subject(connection, absent_capture, context=context),
            "foreign assertion": reveal_subject(
                connection, evidence["a_assertion"], context=context
            ),
            "absent assertion": reveal_subject(connection, absent_assertion, context=context),
        }

    assert all(answer is None for answer in answers.values()), answers


def test_an_assertion_reveals_its_own_evidence_and_only_its_own(
    engine: Engine, evidence: dict[str, str]
) -> None:
    """The assertion traversal, and its partition, in one test."""
    with engine.connect() as connection:
        own = reveal_subject(
            connection, evidence["a_assertion"], context=capture_context(PRINCIPAL_A)
        )
        foreign = reveal_subject(
            connection, evidence["b_assertion"], context=capture_context(PRINCIPAL_A)
        )

    assert foreign is None
    assert own is not None
    assert own.subject_kind is RevealSubjectKind.ASSERTION
    assert own.state is EvidenceState.EVIDENCE
    assert [record.assertion_id for record in own.accepted] == [evidence["a_assertion"]]
    assert own.spans and {span.span_id for span in own.spans} == set(own.accepted[0].span_ids)
    assert own.capture_id == evidence["a_capture"]


def test_an_unsearched_scope_is_unavailable_and_a_searched_empty_one_is_not(
    engine: Engine,
) -> None:
    """**The control this whole package turns on**, measured against real rows.

    Two captures, both with no derived evidence whatever, differing in exactly
    one row: whether the stage that persists proposals has completed. Both answer
    with empty `spans`, `proposed` and `accepted` collections — so if the state
    were derived from those collections, the two would be identical. They are
    not, and the difference is the whole distinction between "we searched and
    found nothing" and "we could not search this".
    """
    with engine.begin() as connection:
        searched = _admit(connection, PRINCIPAL_A, "reveal-searched")
        unsearched = _admit(connection, PRINCIPAL_A, "reveal-unsearched")
        _complete_derivation(connection, _version_of(connection, searched), key="searched")

    with engine.connect() as connection:
        context = capture_context(PRINCIPAL_A)
        empty = reveal_subject(connection, searched, context=context)
        unavailable = reveal_subject(connection, unsearched, context=context)

    assert empty is not None and unavailable is not None
    # The two answers hold the same rows: nothing.
    for answer in (empty, unavailable):
        assert (answer.spans, answer.proposed, answer.accepted) == ((), (), ())
        assert len(answer.versions) == 1

    # And they are still different answers.
    assert empty.state is EvidenceState.NO_EVIDENCE
    assert empty.gap is None
    assert empty.versions_with_completed_derivation == 1

    assert unavailable.state is EvidenceState.UNAVAILABLE
    assert unavailable.gap is EvidenceGap.DERIVATION_HAS_NOT_COMPLETED
    assert unavailable.versions_with_completed_derivation == 0
    assert unavailable.versions[0].derivation_state is None


def test_a_subject_kind_this_build_cannot_traverse_is_unavailable_and_not_absent(
    engine: Engine, evidence: dict[str, str]
) -> None:
    """A `kn_…` is not "no such evidence"; it is "this plane was not searched".

    Answered identically for both Principals, which is deliberate: a coverage
    answer is a fact about the build and must not vary with who asked, or the
    variation would itself disclose something.
    """
    subject = issue_identifier(IdKind.KNOWLEDGE)
    with engine.connect() as connection:
        answers = [
            reveal_subject(connection, subject, context=capture_context(principal))
            for principal in (PRINCIPAL_A, PRINCIPAL_B)
        ]

    for answer in answers:
        assert answer is not None
        assert answer.state is EvidenceState.UNAVAILABLE
        assert answer.gap is EvidenceGap.SUBJECT_KIND_NOT_COVERED
        assert answer.subject_kind is None
        assert (answer.versions, answer.spans, answer.proposed, answer.accepted) == ((), (), (), ())
