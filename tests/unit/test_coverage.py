"""Coverage states, and the aggregate limitation that makes an omission sayable.

Two things are proved here.

**The ten states.** `docs/specs` section 12 fixes ten coverage states, requires
them to be distinct, and forbids any of them collapsing into "empty".
`CoverageCounts.state_value` returns the value of one of them rather than the
member, because domain code may not import `my_pa.contracts` — see the module
docstring in `domain/extraction/coverage.py`. The correspondence is therefore not
enforced by the type system, and these tests are what enforce it instead, in both
directions: every value the function can return is a `CoverageState`, and every
`CoverageState` is reachable from some input. A one-directional check would let
the two drift as soon as a state was added.

**The aggregate limitation.** `docs/plans/mcv-completion-plan.md` section 10
records that a refused object vanishes from a listing with no signal at all.
Section 9.2 permits a safe aggregate and forbids the per-object side channel in
the same sentence, so the tests below assert both halves: that the count is
disclosed, and that nothing which could identify an object can be.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from my_pa.contracts.v1.disclosure import (
    Coverage,
    CoverageState,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    Trust,
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.extraction.coverage import (
    AggregateLimitation,
    CoverageCounts,
    LimitationReason,
    SnapshotState,
)
from my_pa.domain.source.registry import issue_identifier

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

ENROLLMENT_ID = issue_identifier(IdKind.ENROLLMENT)


def _counts(**overrides: object) -> CoverageCounts:
    values: dict[str, object] = {
        "observed_at": OBSERVED_AT,
        "enrollment_id": ENROLLMENT_ID,
    }
    values.update(overrides)
    return CoverageCounts(**values)  # type: ignore[arg-type]


#: One input per state, so the mapping is stated case by case rather than
#: re-derived from the implementation. The identifiers are the inputs; the names
#: are the ten states section 12 fixes.
STATE_CASES: list[tuple[str, CoverageCounts]] = [
    ("not_enrolled", CoverageCounts(observed_at=OBSERVED_AT)),
    ("eligible", _counts(eligible=3)),
    ("queued", _counts(eligible=3, queued=3)),
    ("processed", _counts(eligible=3, processed=3)),
    ("partially_processed", _counts(eligible=3, processed=1, quarantined=1)),
    ("unsupported", _counts(eligible=3, unsupported=3)),
    ("quarantined", _counts(eligible=3, quarantined=3)),
    ("unavailable", _counts(eligible=3, unavailable=3)),
    ("stale", _counts(eligible=3, processed=3, snapshot=SnapshotState.STALE)),
    ("superseded", _counts(eligible=3, processed=3, snapshot=SnapshotState.SUPERSEDED)),
]


@pytest.mark.parametrize(("expected", "counts"), STATE_CASES, ids=[case[0] for case in STATE_CASES])
def test_each_situation_reports_its_own_state(expected: str, counts: CoverageCounts) -> None:
    assert counts.state() == expected


def test_every_state_this_module_can_report_is_a_contract_coverage_state() -> None:
    """Half of the pin. A typo or a renamed state fails here."""
    for expected, counts in STATE_CASES:
        assert counts.state() is CoverageState(expected)


def test_every_contract_coverage_state_is_reachable() -> None:
    """The other half, and the one that catches a state nothing can report.

    Without it, a coverage state could be added to the contract and quietly have
    no situation that produces it — which is exactly how "distinct states" decays
    into "some states nobody sets".
    """
    reachable = {counts.state() for _, counts in STATE_CASES}
    assert reachable == {state.value for state in CoverageState}


def test_no_state_collapses_into_empty() -> None:
    """Section 12: the ten are distinct. Same counts, different states, and none
    of them is inferred from a zero."""
    assert len({counts.state() for _, counts in STATE_CASES}) == len(CoverageState)


def test_a_scope_with_nothing_in_it_is_eligible_rather_than_processed() -> None:
    """An enrollment whose scope holds nothing has covered nothing.

    Reporting `processed` here would claim complete coverage of a scope that was
    never examined, which is the global inference section 12 forbids.
    """
    assert _counts(eligible=0).state() is CoverageState.ELIGIBLE


def test_an_outstanding_object_beside_a_result_is_partial_not_complete() -> None:
    """Two of three processed is not `processed`, however the third turns out."""
    assert _counts(eligible=3, processed=2).state() is CoverageState.PARTIALLY_PROCESSED


def test_a_stale_snapshot_outranks_a_complete_count() -> None:
    """A complete count of a snapshot that no longer holds is not a current answer."""
    complete = _counts(eligible=2, processed=2)
    assert complete.state() is CoverageState.PROCESSED
    assert (
        _counts(eligible=2, processed=2, snapshot=SnapshotState.STALE).state()
        is CoverageState.STALE
    )


def test_coverage_names_the_enrollment_and_the_snapshot_it_is_for() -> None:
    counts = _counts(eligible=1, processed=1)

    assert counts.enrollment_id == ENROLLMENT_ID
    assert counts.observed_at == OBSERVED_AT


def test_counts_cannot_exceed_the_scope_they_are_counted_within() -> None:
    """A numerator larger than its denominator is not a coverage report."""
    with pytest.raises(ValueError, match="cannot exceed the eligible count"):
        _counts(eligible=1, processed=1, quarantined=1)


def test_an_unenrolled_scope_carries_no_counts_and_no_limitations() -> None:
    """Nothing is known about content no grant covers, and a count beside a
    missing enrollment would be a claim made outside any authorized scope."""
    with pytest.raises(ValueError, match="unenrolled scope"):
        CoverageCounts(observed_at=OBSERVED_AT, eligible=4)


def test_an_enrollment_identifier_is_validated() -> None:
    with pytest.raises(InvalidIdentifierError):
        _counts(enrollment_id="/synthetic/fixtures/corpus")


def test_a_limitation_discloses_a_count_and_a_reason_and_nothing_else() -> None:
    """The remedy section 9.2 permits, in the shape it permits it."""
    limitation = AggregateLimitation(
        reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
        affected_count=3,
    )

    assert limitation.disclosure == "objects_omitted_containment_unproven:3"
    assert {field.name for field in fields(AggregateLimitation)} == {"reason", "affected_count"}


def test_a_limitation_has_nowhere_to_name_what_it_omitted() -> None:
    """The forbidden half of the same sentence.

    An identifier, a locator, or a name here would turn the aggregate into the
    per-object existence disclosure section 9.2 rules out, so the type has no
    field one could go in.
    """
    forbidden = {
        "source_object_id",
        "object_ids",
        "locator",
        "native_locator",
        "path",
        "paths",
        "name",
        "names",
        "filename",
        "detail",
        "details",
    }
    assert not {field.name for field in fields(AggregateLimitation)} & forbidden


def test_a_limitation_that_affects_nothing_is_refused() -> None:
    """A zero would disclose "nothing was omitted for this reason", which is a
    claim about the source rather than a count of what was seen."""
    with pytest.raises(ValueError, match="at least one object"):
        AggregateLimitation(
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=0,
        )


def test_a_limitation_reason_is_a_closed_code() -> None:
    with pytest.raises(ValueError, match="not a valid LimitationReason"):
        LimitationReason("could not read /synthetic/fixtures/corpus/note.md")


def test_limitations_are_disclosed_in_a_stable_order() -> None:
    counts = _counts(
        eligible=2,
        processed=1,
        limitations=(
            AggregateLimitation(
                reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
                affected_count=2,
            ),
        ),
    )

    assert counts.disclosed_limitations == ("objects_omitted_containment_unproven:2",)


def test_the_counts_populate_the_mandatory_disclosure_envelope() -> None:
    """The end of the plumbing: an omission a listing could not report before.

    This is the finding from `docs/plans/mcv-completion-plan.md` section 10
    answered — the disclosure now says that one object was left out and why,
    without saying which. It also exercises the layering pin end to end, because
    the envelope refuses a state string that is not a `CoverageState`.
    """
    counts = _counts(
        eligible=3,
        processed=2,
        limitations=(
            AggregateLimitation(
                reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
                affected_count=1,
            ),
        ),
    )

    disclosure = Disclosure(
        scope=Scope(enrollment_ids=(ENROLLMENT_ID,)),
        coverage=Coverage(
            state=counts.state(),
            eligible=counts.eligible,
            processed=counts.processed,
            quarantined=counts.quarantined,
            unsupported=counts.unsupported,
        ),
        freshness=Freshness(
            observed_at=counts.observed_at,
            state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION,
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED),
        limitations=counts.disclosed_limitations,
        partial_result=True,
    )

    assert disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert disclosure.limitations == ("objects_omitted_containment_unproven:1",)
    assert all("obj_" not in limitation for limitation in disclosure.limitations)
