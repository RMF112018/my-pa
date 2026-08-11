"""A corpus answer composes stated coverages and cannot overstate them.

Four properties, and each exists because its absence is a way to hand a caller a
confident-looking answer over a corpus most of which was never in the question.

**The state can never read as complete while anything is unaccounted for.** Held
at two levels on purpose. `state()` derives it, so nothing can *pass in* a
complete state; and `__post_init__` refuses to construct a value whose state says
`processed` while any object lies outside every enrollment, any object awaits an
outcome, or any single enrollment states anything else. The second is the one
that survives an edit to the first, so it is exercised by breaking the first —
`test_a_broken_state_function_cannot_produce_a_complete_looking_value` monkeypatches
`state` and asserts construction fails.

**Unknown territory is a count and never an identity.** `CorpusLimitation` has
two fields and neither can name a thing, which is asserted against
`dataclasses.fields` rather than described, exactly as the per-enrollment
`AggregateLimitation` is.

**The totals are sums of statements, and say so.** Two enrollments over one
source can enumerate the same object, so `stated_eligible` counts it twice. The
type does not deduplicate — deduplicating would report a number nobody measured —
and `totals_are_per_enrollment_sums` is the flag that obliges the layer above to
publish the caveat.

**The reasons are a closed vocabulary with an exact size.** A vocabulary constant
with no floor passes when it is emptied; this one is pinned as an equality, so
emptying it reddens and growing it is a decision rather than a diff.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.extraction.corpus import (
    CorpusCoverage,
    CorpusLimitation,
    CorpusLimitationReason,
)
from my_pa.domain.extraction.coverage import CoverageCounts

MOMENT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
PRINCIPAL = "prn_corpusalpha01"

#: The reason vocabulary, written out. An exact equality rather than a floor:
#: emptying `CorpusLimitationReason` would satisfy every "is a subset" assertion
#: in this file, and adding a member silently would let a new disclosure token
#: reach the wire with no decision recorded here.
EXPECTED_REASONS = frozenset(
    {
        "objects_outside_every_enrollment",
        "objects_awaiting_an_outcome",
        "enrollments_not_fully_processed",
    }
)


def counts(
    enrollment: str, *, eligible: int = 1, processed: int = 1, **rest: int
) -> CoverageCounts:
    return CoverageCounts(
        observed_at=MOMENT,
        enrollment_id=enrollment,
        eligible=eligible,
        processed=processed,
        **rest,
    )


def test_the_reason_vocabulary_is_closed_at_the_size_it_declares() -> None:
    assert {reason.value for reason in CorpusLimitationReason} == EXPECTED_REASONS
    assert len(CorpusLimitationReason) == len(EXPECTED_REASONS) == 3


def test_a_corpus_limitation_can_carry_a_count_and_nothing_that_identifies() -> None:
    """The `AggregateLimitation` discipline, restated against the new type.

    Read off the dataclass rather than off the docstring, so a field added later
    fails here instead of shipping an existence disclosure.
    """
    names = {field.name for field in fields(CorpusLimitation)}
    assert names == {"reason", "affected_count"}
    forbidden = {
        "source_id",
        "source_object_id",
        "enrollment_id",
        "version_id",
        "native_locator",
        "locator",
        "path",
        "name",
        "label",
        "media_type",
        "observed_at",
        "occurred_at",
    }
    assert names.isdisjoint(forbidden)


@pytest.mark.parametrize("affected", [0, -1, True])
def test_a_limitation_affecting_nothing_is_refused(affected: int) -> None:
    with pytest.raises(ValueError):
        CorpusLimitation(
            reason=CorpusLimitationReason.OBJECTS_OUTSIDE_EVERY_ENROLLMENT,
            affected_count=affected,
        )


def test_a_limitation_token_is_two_closed_components() -> None:
    limitation = CorpusLimitation(
        reason=CorpusLimitationReason.OBJECTS_AWAITING_AN_OUTCOME, affected_count=4
    )
    assert limitation.disclosure == "objects_awaiting_an_outcome:4"


def test_a_principal_holding_nothing_is_not_enrolled_rather_than_empty() -> None:
    """`not_enrolled` is a real answer; "empty" would be the collapse section 12 forbids."""
    corpus = CorpusCoverage(observed_at=MOMENT, principal_id=PRINCIPAL)
    assert corpus.state() is CoverageState.NOT_ENROLLED
    assert corpus.enrollment_count == 0
    assert corpus.disclosed_limitations == ()


def test_a_corpus_with_no_enrollment_may_carry_no_measurement() -> None:
    with pytest.raises(ValueError, match="holds no measured corpus"):
        CorpusCoverage(observed_at=MOMENT, principal_id=PRINCIPAL, objects_in_held_sources=3)


def test_the_principal_is_an_identifier_of_the_right_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        CorpusCoverage(observed_at=MOMENT, principal_id="enr_notaprincipal")


def test_every_member_states_the_enrollment_it_is_for() -> None:
    """An unenrolled `CoverageCounts` is not a statement and cannot compose one."""
    with pytest.raises(ValueError, match="states the enrollment it is for"):
        CorpusCoverage(
            observed_at=MOMENT,
            principal_id=PRINCIPAL,
            enrollments=(CoverageCounts(observed_at=MOMENT),),
            held_sources=1,
            objects_in_held_sources=1,
        )


def test_an_enrollment_states_its_coverage_once() -> None:
    member = counts("enr_alpha0000001")
    with pytest.raises(ValueError, match="states its coverage once"):
        CorpusCoverage(
            observed_at=MOMENT,
            principal_id=PRINCIPAL,
            enrollments=(member, member),
            held_sources=1,
            objects_in_held_sources=2,
        )


def test_a_fully_covered_corpus_is_the_only_way_to_reach_processed() -> None:
    corpus = CorpusCoverage(
        observed_at=MOMENT,
        principal_id=PRINCIPAL,
        enrollments=(counts("enr_alpha0000001", eligible=2, processed=2),),
        held_sources=1,
        objects_in_held_sources=2,
        objects_outside_every_enrollment=0,
        objects_awaiting_an_outcome=0,
    )
    assert corpus.state() is CoverageState.PROCESSED
    assert corpus.disclosed_limitations == ()
    assert corpus.stated_eligible == corpus.stated_processed == 2
    assert corpus.totals_are_per_enrollment_sums is False


@pytest.mark.parametrize(
    ("outside", "pending", "member"),
    [
        (1, 0, counts("enr_alpha0000001", eligible=2, processed=2)),
        (0, 1, counts("enr_alpha0000001", eligible=2, processed=2)),
        (1, 1, counts("enr_alpha0000001", eligible=2, processed=2)),
        (0, 0, counts("enr_alpha0000001", eligible=2, processed=1)),
        (1, 0, counts("enr_alpha0000001", eligible=2, processed=1)),
        (0, 1, counts("enr_alpha0000001", eligible=2, processed=1)),
        (1, 1, counts("enr_alpha0000001", eligible=2, processed=1)),
    ],
    ids=[
        "an unenrolled object alone",
        "work awaiting an outcome alone",
        "both",
        "an enrollment that is not fully processed alone",
        "that enrollment and an unenrolled object",
        "that enrollment and pending work",
        "all three at once",
    ],
)
def test_no_arrangement_of_unknown_territory_reports_as_processed(
    outside: int, pending: int, member: CoverageCounts
) -> None:
    """Exhaustive over the product of the three ways a corpus can be incomplete.

    Seven of the eight cells; the eighth is the all-clear case above. A guard
    that checked one condition would pass six of these.
    """
    corpus = CorpusCoverage(
        observed_at=MOMENT,
        principal_id=PRINCIPAL,
        enrollments=(member,),
        held_sources=1,
        objects_in_held_sources=2 + outside,
        objects_outside_every_enrollment=outside,
        objects_awaiting_an_outcome=pending,
    )
    assert corpus.state() is CoverageState.PARTIALLY_PROCESSED
    assert corpus.state() is not CoverageState.PROCESSED


def test_a_broken_state_function_cannot_produce_a_complete_looking_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invariant is a refusal at construction, not a property of one function.

    `state` is replaced with one that always answers `processed` — the exact
    one-line regression this package exists to make impossible — and the value
    still cannot be built.
    """
    monkeypatch.setattr(CorpusCoverage, "state", lambda self: CoverageState.PROCESSED)
    with pytest.raises(ValueError, match="cannot report as processed"):
        CorpusCoverage(
            observed_at=MOMENT,
            principal_id=PRINCIPAL,
            enrollments=(counts("enr_alpha0000001", eligible=2, processed=2),),
            held_sources=1,
            objects_in_held_sources=3,
            objects_outside_every_enrollment=1,
        )
    with pytest.raises(ValueError, match="cannot report as processed"):
        CorpusCoverage(observed_at=MOMENT, principal_id=PRINCIPAL)


def test_the_limitations_are_derived_from_the_counts_and_not_from_a_flag() -> None:
    corpus = CorpusCoverage(
        observed_at=MOMENT,
        principal_id=PRINCIPAL,
        enrollments=(
            counts("enr_alpha0000001", eligible=2, processed=2),
            counts("enr_beta00000001", eligible=3, processed=1),
        ),
        held_sources=2,
        objects_in_held_sources=9,
        objects_outside_every_enrollment=4,
        objects_awaiting_an_outcome=2,
    )
    assert corpus.disclosed_limitations == (
        "enrollments_not_fully_processed:1",
        "objects_awaiting_an_outcome:2",
        "objects_outside_every_enrollment:4",
    )
    assert corpus.totals_are_per_enrollment_sums is True
    assert corpus.stated_eligible == 5
    assert corpus.stated_processed == 3


def test_more_objects_cannot_lie_outside_the_enrollments_than_the_sources_hold() -> None:
    with pytest.raises(ValueError, match="than the sources hold"):
        CorpusCoverage(
            observed_at=MOMENT,
            principal_id=PRINCIPAL,
            enrollments=(counts("enr_alpha0000001"),),
            held_sources=1,
            objects_in_held_sources=1,
            objects_outside_every_enrollment=2,
        )


@pytest.mark.parametrize(
    "field",
    [
        "held_sources",
        "objects_in_held_sources",
        "objects_outside_every_enrollment",
        "objects_awaiting_an_outcome",
    ],
)
def test_no_count_may_be_negative(field: str) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        CorpusCoverage(
            observed_at=MOMENT,
            principal_id=PRINCIPAL,
            enrollments=(counts("enr_alpha0000001"),),
            **{field: -1},
        )
