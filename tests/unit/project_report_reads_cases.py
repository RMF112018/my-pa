"""The WP4P-S2 read cases, run against the FAST fake and against PostgreSQL.

Each case takes a `ReadsScene` built by `build_world` (and, for the
superseded case, a count of every derivation row) and asserts through
`UnitOfWork.project_report_reads` alone. `tests/unit/test_project_report_reads_fake.py`
runs them over the fakes; `tests/database/test_project_report_reads.py` over a
head-migrated clone. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Final

from my_pa.contracts.ports import (
    ProjectReportIdentifierTerm,
    ProjectReportLineQuery,
    ProjectReportReadLine,
    ProjectReportReadsRepository,
    ProjectReportRfiTerm,
    ProjectReportVersionRecord,
)
from my_pa.domain.project_reports.catalogue import MEASURES, searchable_text_fields
from my_pa.domain.project_reports.identity import AMBIGUOUS_PREFIX, RfiNumber, match_rfi
from my_pa.domain.project_reports.model import (
    DerivationState,
    FamilyView,
    FilterSemantics,
    NotReportableReason,
    RecordFamily,
    ReportQualifier,
    StatusClass,
)
from my_pa.domain.project_reports.reads import (
    MeasureInputs,
    PlannedLine,
    UsedVersion,
    answer_qualifiers,
    plan_measure,
    version_filter_semantics,
)
from my_pa.domain.project_reports.versions import VersionRef, latest_version
from tests.unit.project_report_reads_scene import (
    NOTE_PROJECT,
    OBS_PROJECT,
    RFI_PROJECT,
    ReadsScene,
    unknown_adapter_registry,
)

OTHER_PRINCIPAL: Final = "prn_synotherreads01"


def _versions(
    scene: ReadsScene, family: RecordFamily | None = None, project: str | None = None
) -> tuple[ProjectReportVersionRecord, ...]:
    with scene.unit() as unit:
        return unit.project_report_reads.list_report_versions(
            scene.principal,
            project_ids=None if project is None else [project],
            record_family=family,
        )


def _series(scene: ReadsScene, slug: str) -> list[ProjectReportVersionRecord]:
    return [v for v in _versions(scene) if v.slug_label == slug]


def _reads(scene: ReadsScene, call: Callable[[ProjectReportReadsRepository], object]) -> object:
    with scene.unit() as unit:
        return call(unit.project_report_reads)


def _lines(
    scene: ReadsScene, derivation_ids: tuple[str, ...], **filters: object
) -> tuple[ProjectReportReadLine, ...]:
    query = ProjectReportLineQuery(
        derivation_ids=derivation_ids,
        limit=int(filters.pop("limit", 1000)),  # type: ignore[call-overload]
        **filters,  # type: ignore[arg-type]
    )
    with scene.unit() as unit:
        return unit.project_report_reads.query_lines(scene.principal, query)


def _number(line: ProjectReportReadLine, key: str = "rfi.number") -> str:
    return next(v.raw_text for v in line.values if v.field_key == key)


def _rfis(scene: ReadsScene) -> tuple[str, ...]:
    """The current derivations of the `qxrfis` series, in version order."""
    return tuple(v.derivation_id for v in _series(scene, "qxrfis"))


# --- the cases -----------------------------------------------------------------------


def case_a_superseded_derivation_is_never_answered_or_counted(
    scene: ReadsScene, derivation_rows: Callable[[], int]
) -> None:
    """A binding correction and an adapter re-derivation leave one current derivation each."""
    before_versions = _versions(scene)
    before_lines = _lines(scene, _rfis(scene))
    rows_before = derivation_rows()
    # The observations export has stated totals, so a superseded one is live (R1-04).
    (observations,) = (v.derivation_id for v in before_versions if v.project_id == OBS_PROJECT[1])
    with scene.unit() as unit:
        stated = unit.project_report_reads.stated_totals_of(scene.principal, [observations])
    assert stated
    scene.correct("rfis")
    scene.correct("observations")
    scene.rederive()
    scene.rederive(unknown_adapter_registry())
    assert derivation_rows() > rows_before  # superseded rows exist beside the current ones
    after_versions = _versions(scene)
    assert [v.snapshot_id for v in after_versions] == [v.snapshot_id for v in before_versions]
    rfis = [v for v in after_versions if v.project_id == RFI_PROJECT[1]]
    assert {v.derivation_id for v in rfis}.isdisjoint(
        {v.derivation_id for v in before_versions if v.project_id == RFI_PROJECT[1]}
    )
    # A superseded derivation named outright answers nothing either.
    superseded = tuple(v.derivation_id for v in before_versions if v.project_id == RFI_PROJECT[1])
    assert _lines(scene, superseded) == ()
    with scene.unit() as unit:
        reads = unit.project_report_reads
        assert reads.stated_totals_of(scene.principal, superseded) == ()
        assert reads.stated_totals_of(scene.principal, [observations]) == ()
        (current,) = (v.derivation_id for v in after_versions if v.project_id == OBS_PROJECT[1])
        assert current != observations
        assert len(reads.stated_totals_of(scene.principal, [current])) == len(stated)
        assert reads.rfi_candidates(scene.principal, superseded, [174]) == ()
        assert reads.cross_checks_of(scene.principal, superseded) == ()
    after_lines = _lines(scene, _rfis(scene))
    assert len(after_lines) == len(before_lines) == 9
    assert [(_number(a), a.row_ordinal) for a in after_lines] == [
        (_number(b), b.row_ordinal) for b in before_lines
    ]
    record = next(line.record_id for line in after_lines if _number(line) == "GMP-174")
    assert record is not None
    history = _reads(scene, lambda r: r.lines_of_records(scene.principal, [record]))
    assert isinstance(history, tuple)
    assert len(history) == 2  # one line in each of the 2 versions, never once per derivation
    # The adapter re-derivation: the unknown signature is now one classified notes version.
    notes = [v for v in after_versions if v.project_id == NOTE_PROJECT[1]]
    assert [(v.state, v.family_view) for v in notes] == [
        (DerivationState.CLASSIFIED, FamilyView.NOTES)
    ]
    note_lines = _lines(scene, (notes[0].derivation_id,))
    assert note_lines and len({line.row_ordinal for line in note_lines}) == len(note_lines)


def case_a_quarantined_latest_version_answers_no_rows(scene: ReadsScene) -> None:
    series = _series(scene, "qxrfiq")
    refs = {v.snapshot_id: VersionRef(v.snapshot_id, v.date_label, v.first_seen_at) for v in series}
    latest = latest_version(refs.values())
    assert latest is not None
    newest = next(v for v in series if v.snapshot_id == latest.snapshot_id)
    assert newest.state is DerivationState.QUARANTINED and newest.date_label == "20261115"
    assert _lines(scene, (newest.derivation_id,)) == ()
    measure = plan_measure(
        MEASURES["open_outstanding.record_count"],
        [],
        MeasureInputs(newest.state, newest.quarantine_reason, newest.reconciliation),
    ).total
    assert measure is not None and measure.value is None
    assert NotReportableReason.SNAPSHOT_QUARANTINED in measure.reasons
    earlier = next(v for v in series if v is not newest)
    assert [_number(line) for line in _lines(scene, (earlier.derivation_id,))] == ["GMP-201"]


def case_versions_follow_the_label_order_not_arrival(scene: ReadsScene) -> None:
    """Ruling D10: the later label was first seen first, and is still the latest."""
    series = _series(scene, "qxrfis")
    assert [v.date_label for v in series] == ["20261110", "20261120"]
    assert series[0].first_seen_at > series[1].first_seen_at
    refs = [VersionRef(v.snapshot_id, v.date_label, v.first_seen_at) for v in series]
    latest = latest_version(refs)
    assert latest is not None and latest.date_label == "20261120"
    assert len({v.series_id for v in series}) == 1
    assert {v.currency for v in series} == {"USD"}
    assert {v.declared_project_number for v in series} == {RFI_PROJECT[2]}
    # Per-version filter semantics: declared after the later label, before the earlier.
    used = [
        UsedVersion(
            VersionRef(v.snapshot_id, v.date_label, v.first_seen_at),
            version_filter_semantics(v.filter_declared_at, v.first_seen_at),
        )
        for v in series
    ]
    assert [u.filter_semantics for u in used] == [
        FilterSemantics.OPERATOR_DECLARED,
        FilterSemantics.UNKNOWN,
    ]
    assert answer_qualifiers(used) == (ReportQualifier.FILTER_SEMANTICS_UNKNOWN,)
    assert all(v.filter_declared_at is None for v in _series(scene, "qxrfiq"))
    families = {v.record_family for v in _versions(scene, RecordFamily.RFIS)}
    assert families == {RecordFamily.RFIS}
    assert {v.project_id for v in _versions(scene, project=OBS_PROJECT[1])} == {OBS_PROJECT[1]}


def case_another_principals_ids_answer_nothing(scene: ReadsScene) -> None:
    versions = _versions(scene)
    derivations = tuple(v.derivation_id for v in versions)
    lines = _lines(scene, derivations)
    records = [line.record_id for line in lines if line.record_id]
    assert versions and lines and records
    with scene.unit() as unit:
        reads = unit.project_report_reads
        assert reads.list_report_versions(OTHER_PRINCIPAL) == ()
        assert reads.list_report_versions(OTHER_PRINCIPAL, project_ids=[RFI_PROJECT[1]]) == ()
        assert (
            reads.query_lines(
                OTHER_PRINCIPAL, ProjectReportLineQuery(derivation_ids=derivations, limit=100)
            )
            == ()
        )
        assert reads.lines_of_records(OTHER_PRINCIPAL, records) == ()
        assert reads.stated_totals_of(OTHER_PRINCIPAL, derivations) == ()
        assert reads.cross_checks_of(OTHER_PRINCIPAL, derivations) == ()
        assert reads.rfi_candidates(OTHER_PRINCIPAL, derivations, [174]) == ()
        # The Principal's own reads of unknown ids answer nothing too.
        assert reads.lines_of_records(scene.principal, ["prrec_synunknown001"]) == ()
        assert (
            reads.query_lines(
                scene.principal,
                ProjectReportLineQuery(derivation_ids=("prdrv_synunknown001",), limit=10),
            )
            == ()
        )


def case_rfi_numbers_match_exactly(scene: ReadsScene) -> None:
    """PULSE-AC-14 through the read: 174 never matches 1740 or 17; the prefix is exact."""
    latest = (_series(scene, "qxrfis")[-1].derivation_id,)

    def numbers(*terms: ProjectReportRfiTerm) -> list[str]:
        return sorted(_number(line) for line in _lines(scene, latest, rfi_terms=terms))

    assert numbers(ProjectReportRfiTerm(None, 174)) == ["174", "CD 50%-174", "GMP-174"]
    assert numbers(ProjectReportRfiTerm("GMP", 174)) == ["GMP-174"]
    assert numbers(ProjectReportRfiTerm("GMP-", 174)) == ["GMP-174"]
    assert numbers(ProjectReportRfiTerm("CD 50%", 174)) == ["CD 50%-174"]
    assert numbers(ProjectReportRfiTerm("GM", 174)) == []
    assert numbers(ProjectReportRfiTerm(None, 17)) == ["17"]
    assert numbers(ProjectReportRfiTerm(None, 1740)) == ["1740"]
    assert numbers(ProjectReportRfiTerm(None, 1)) == []
    assert numbers(ProjectReportRfiTerm(None, 17), ProjectReportRfiTerm("GMP", 175)) == [
        "17",
        "GMP-175",
    ]
    found = _reads(scene, lambda r: r.rfi_candidates(scene.principal, latest, [174]))
    assert isinstance(found, tuple)
    candidates = [RfiNumber("", c.prefix, c.suffix) for c in found]
    assert sorted((c.prefix or "", c.suffix) for c in candidates) == [
        ("", 174),
        ("CD 50%", 174),
        ("GMP", 174),
    ]
    assert match_rfi(None, 174, candidates).flag == AMBIGUOUS_PREFIX
    assert len(match_rfi("GMP", 174, candidates).matches) == 1
    by_identifier = _lines(
        scene, latest, identifiers=(ProjectReportIdentifierTerm("rfi.number", "GMP-176"),)
    )
    assert [_number(line) for line in by_identifier] == ["GMP-176"]


def case_text_never_crosses_fields_and_dates_are_inclusive(scene: ReadsScene) -> None:
    latest = (_series(scene, "qxrfis")[-1].derivation_id,)
    fields = searchable_text_fields(RecordFamily.RFIS)

    def text(needle: str) -> list[str]:
        return sorted(
            _number(line) for line in _lines(scene, latest, text=needle, text_fields=fields)
        )

    assert text("KILO") == ["GMP-175"]  # case-insensitive, per value
    assert text("okil") == []  # "Kilo" + "Kilo" in two fields: never one string
    assert text("synthetic person") == ["GMP-174"]
    assert text("50%") == []  # identifiers are not searched text
    # Ruling R1-08: a non-ASCII needle is folded by the same engine as the value (in SQL
    # on PostgreSQL), so `İ` matches itself; Python's `"İ".lower()` is 2 characters.
    assert text("İota") == ["1740"]
    assert text("délta İOTA") == ["1740"]  # ASCII case folds; non-ASCII matches as written
    assert (
        sorted(_number(line) for line in _lines(scene, latest, text="alpha", text_fields=())) == []
    )

    def dates(start: date | None, end: date | None) -> list[str]:
        return sorted(
            _number(line)
            for line in _lines(
                scene, latest, date_field="rfi.date_initiated", date_from=start, date_to=end
            )
        )

    assert dates(date(2026, 11, 1), date(2026, 11, 5)) == [
        "CD 50%-174",
        "GMP-174",
        "GMP-175",
        "GMP-176",
    ]
    assert dates(date(2026, 11, 10), None) == ["1740"]
    assert dates(None, date(2026, 10, 31)) == ["17"]


def case_a_two_level_export_answers_detail_rows_only(scene: ReadsScene) -> None:
    """PULSE-AC-06 at the database: 99 detail lines, never the 198 a header join gives."""
    (version,) = _versions(scene, project=OBS_PROJECT[1])
    lines = _lines(scene, (version.derivation_id,))
    assert len(lines) == len({line.row_ordinal for line in lines}) == 99
    counted = sum((Decimal(_number(line, "observation.count")) for line in lines), Decimal(0))
    assert counted == 99
    planned = [PlannedLine(line.line_kind, line.status_class, line.identity_key) for line in lines]
    answer = plan_measure(
        MEASURES["open_by_vendor.record_count"], planned, MeasureInputs(version.state)
    )
    assert {s: v.value for s, v in answer.by_status.items()} == {
        StatusClass.OPEN: Decimal(40),
        StatusClass.CLOSED: Decimal(59),
        StatusClass.UNKNOWN: Decimal(0),
    }
    opened = _lines(scene, (version.derivation_id,), status_classes=(StatusClass.OPEN,))
    assert len(opened) == 40
    assert len(_lines(scene, (version.derivation_id,), statuses=("Closed",))) == 59
    by_vendor = _lines(scene, (version.derivation_id,), group_keys=("Synthetic Vendor A",))
    assert len(by_vendor) == 99
    assert _lines(scene, (version.derivation_id,), group_keys=("Synthetic Vendor Zz",)) == ()
    assert all(line.group_path for line in lines)
    totals = _reads(scene, lambda r: r.stated_totals_of(scene.principal, [version.derivation_id]))
    assert isinstance(totals, tuple) and totals
    assert {t.derivation_id for t in totals} == {version.derivation_id}


def case_keyset_pages_are_disjoint_and_complete(scene: ReadsScene) -> None:
    derivations = tuple(reversed(_rfis(scene)))  # the caller's order is the page order
    everything = _lines(scene, derivations)
    assert everything[0].derivation_id == derivations[0]
    pages: list[ProjectReportReadLine] = []
    after: tuple[int, int] | None = None
    while True:
        page = _lines(scene, derivations, limit=2, after=after)
        if not page:
            break
        assert len(page) <= 2
        pages.extend(page)
        last = page[-1]
        after = (derivations.index(last.derivation_id), last.row_ordinal)
    keys = [(line.derivation_id, line.row_ordinal) for line in pages]
    assert keys == [(line.derivation_id, line.row_ordinal) for line in everything]
    assert len(set(keys)) == len(keys) == 9


CASES: Final = (
    case_a_quarantined_latest_version_answers_no_rows,
    case_versions_follow_the_label_order_not_arrival,
    case_another_principals_ids_answer_nothing,
    case_rfi_numbers_match_exactly,
    case_text_never_crosses_fields_and_dates_are_inclusive,
    case_a_two_level_export_answers_detail_rows_only,
    case_keyset_pages_are_disjoint_and_complete,
)
