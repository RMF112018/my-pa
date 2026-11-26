"""WP5-S4: the pure parts of the `pulse` section (FAST).

* `pulse_rfi_numbers`: the Meeting's own `rfi:N` ascending, then the returned
  messages' by how many carry each, then `N`; each number once; at most
  `MAX_PULSE_RFI_NUMBERS` asked, with the total found;
* `_pulse`: the counts in family order (observations, coordination issues,
  RFIs; the repository's order within one), at most `MAX_PULSE_COUNTS` with
  the total; `none` matches dropped, the others with their source; an
  unavailable Project with its reason.

The project-report values come from the synthetic FAST reads world
(`tests/unit/project_report_reads_scene.py`). Every value is synthetic.
"""

from __future__ import annotations

from my_pa.application.meeting_context import (
    MAX_PULSE_COUNTS,
    MAX_PULSE_RFI_NUMBERS,
    PulseState,
    RfiSource,
    _pulse,
    pulse_rfi_numbers,
)
from my_pa.application.project_reports_reads import (
    Availability,
    ContextSummary,
    ProjectSummary,
    RfiNumberMatch,
)
from my_pa.domain.communications.identifiers import IdentifierKind, TechnicalIdentifier
from my_pa.domain.project_reports.model import RecordFamily
from tests.unit.project_report_reads_scene import OBS_PROJECT, RFI_PROJECT, build_world, fast_scene
from tests.unit.project_reports_reads_service_cases import extend_world, service

M, C = RfiSource.MEETING, RfiSource.COMMUNICATIONS


def _rfi(n: int | str) -> TechnicalIdentifier:
    return TechnicalIdentifier(IdentifierKind.RFI, str(n))


def test_the_meetings_own_numbers_come_first_then_the_messages_by_frequency() -> None:
    own = (_rfi(175), TechnicalIdentifier(IdentifierKind.CHANGE_ORDER, "3"), _rfi(9), _rfi(175))
    carried = {"m1": ("203", "175", "12"), "m2": ("203", "203"), "m3": ("12", "40"), "m4": ("40",)}
    numbers, found = pulse_rfi_numbers(own, ["m1", "m2", "m3", "m4", "absent"], carried)
    # 203 in 2 messages (once each), 12 in 2, 40 in 2 -> by N; 175 is the Meeting's own.
    assert numbers == ((9, M), (175, M), (12, C), (40, C), (203, C))
    assert found == 5


def test_a_message_counts_once_per_number_and_only_returned_messages_count() -> None:
    numbers, _found = pulse_rfi_numbers(
        (), ["a", "b"], {"a": ("7", "7", "8"), "b": ("8",), "z": ("1",)}
    )
    assert numbers == ((8, C), (7, C))


def test_at_most_ten_numbers_are_asked_and_the_total_is_kept() -> None:
    own = tuple(_rfi(n) for n in range(100, 107))
    carried = {f"m{n}": (str(n),) for n in range(1, 9)}
    numbers, found = pulse_rfi_numbers(own, list(carried), carried)
    assert len(numbers) == MAX_PULSE_RFI_NUMBERS == 10
    assert found == 15
    assert [n for n, _ in numbers] == [*range(100, 107), 1, 2, 3]
    assert pulse_rfi_numbers((), [], {}) == ((), 0)


def test_a_value_that_is_not_a_number_is_never_asked() -> None:
    numbers, found = pulse_rfi_numbers((_rfi("\uff11\uff12"),), ["m"], {"m": ("x1", "", "²")})
    assert (numbers, found) == ((), 0)


def _summaries() -> tuple[ProjectSummary, ProjectSummary]:
    scene, *_ = fast_scene()
    build_world(scene)
    extend_world(scene)
    reads = service(scene)
    return (
        reads.project_summary(scene.principal, RFI_PROJECT[1]),
        reads.project_summary(scene.principal, OBS_PROJECT[1]),
    )


def test_counts_are_in_family_order_and_bounded_with_their_total() -> None:
    rfis, observations = _summaries()
    assert rfis.counts and observations.counts
    # RFI counts, then an observation count, then the RFI counts again: 9 entries.
    merged = ProjectSummary(
        RFI_PROJECT[1],
        Availability("available"),
        counts=(*rfis.counts, *observations.counts, *rfis.counts),
        versions=(*rfis.versions, *observations.versions),
        qualifiers=rfis.qualifiers,
    )
    section = _pulse(ContextSummary(RFI_PROJECT[1], merged.availability, merged, ()), (), 0)
    assert section.state is PulseState.AVAILABLE
    assert section.counts_total == len(merged.counts) > MAX_PULSE_COUNTS
    assert len(section.counts) == MAX_PULSE_COUNTS
    family = {b.record.snapshot_id: b.record.record_family for b in merged.versions}
    assert [family[str(e.version)] for e in section.counts] == [
        RecordFamily.OBSERVATIONS,
        *[RecordFamily.RFIS] * (MAX_PULSE_COUNTS - 1),
    ]
    # Within a family the repository's order is kept (a stable sort).
    assert section.counts[1:] == (*rfis.counts, *rfis.counts)[: MAX_PULSE_COUNTS - 1]
    assert section.summary is merged


def test_none_matches_are_dropped_and_the_others_carry_their_source() -> None:
    rfis, _observations = _summaries()
    matches = (
        RfiNumberMatch(None, 174, "ambiguous_prefix", (("GMP", 174, "r1"), (None, 174, "r2"))),
        RfiNumberMatch(None, 9, "none", ()),
        RfiNumberMatch(None, 176, "exact", (("GMP", 176, "r3"),)),
    )
    section = _pulse(
        ContextSummary(RFI_PROJECT[1], rfis.availability, rfis, matches),
        ((174, M), (9, C), (176, C)),
        4,
    )
    assert [(r.match.suffix, r.source) for r in section.rfis] == [(174, M), (176, C)]
    assert section.rfi_numbers_total == 4


def test_an_unavailable_project_states_its_reason_and_nothing_else() -> None:
    state = Availability("unavailable", "never_ingested")
    section = _pulse(
        ContextSummary("prj_synpulse0001x", state, ProjectSummary("prj_synpulse0001x", state), ()),
        ((174, M),),
        1,
    )
    assert (section.state, section.reason, section.project_id) == (
        PulseState.UNAVAILABLE,
        "never_ingested",
        "prj_synpulse0001x",
    )
    assert (section.summary, section.counts, section.rfis) == (None, (), ())
