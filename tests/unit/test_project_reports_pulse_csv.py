"""Project reports: the strict CSV reader, the signature registry and the 15 adapters (WP3P-S2).

Synthetic fixtures only (`tests/fixtures/project_reports/csv`). Every fixture
reconstructs byte-exact from its Layer A plan; every rejection code has a
fixture; an unregistered signature quarantines with every row kept; the
malformed-ratio boundary is exact; each adapter's catalogue is pinned and
checked against its fixture; the filename is never an input.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.project_reports.model import (
    FAMILY_OF_VIEW,
    UNCLASSIFIED_COUNT_KEY,
    Additivity,
    CompletenessClass,
    DerivationState,
    FamilyView,
    IdentityState,
    LineKind,
    ObservationState,
    QuarantineReason,
    ReconciliationOutcome,
    RejectionCode,
    RowReason,
    RowRole,
    StatusClass,
    ValueKind,
)
from my_pa.domain.project_reports.signature import header_signature
from my_pa.infrastructure.project_reports import pulse_csv
from my_pa.infrastructure.project_reports.pulse_csv import (
    MAX_EXPORT_BYTES,
    READER_VERSION,
    REGISTRY,
    ExportRejectedError,
    ExportTooLargeError,
    LayerAPlan,
    ReconstructionError,
    Terminator,
    carries_project_number,
    derive,
    pair_cross_report,
    prepare_export,
)

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "project_reports" / "csv"
SIGNATURES: Final = FIXTURES / "signatures"
PROJECT: Final = "SYN-0001"

#: The 15 full signatures of the schema catalog (docs/evidence/pulse, sections 3-10).
EVIDENCE_SIGNATURES: Final = {
    "bc395d0f219ab8e2dded2c9b2ba23a984221e16e28016944d20c77a18160664d": FamilyView.OAC,
    "4ddbf6c5cfbd42a41651a25b0cb377c76f4113e57367f62200012b310006a5af": (
        FamilyView.WITH_DATE_CLOSED
    ),
    "bf1ffde9268fd40bb2915f1d85210b691d615605be0983758d4b65bb61593241": FamilyView.OPEN_BY_VENDOR,
    "6a3377daa519d55dfc4f4b949ed204c1071ad6d4f6c0e64de8201e527f96bf15": FamilyView.BY_STATUS,
    "36e4ba6dcc3c2e0b1c54540912179835ff2aa3c2dbab155474b4a655e60644d1": (
        FamilyView.LINKED_TO_DRAWINGS
    ),
    "fd8ceefefca08af911d7d598012a5f1a0201b7210de4c5ff427f1e7809a9767b": FamilyView.OPEN_OUTSTANDING,
    "41c0bdf8aa414ce9082b45454faa997ab9cb9c30bd073d5849dada3ee3d72887": FamilyView.RECENTLY_CLOSED,
    "975b497cad710281d61f4b612a52219e5b188f96c88b418e892a9421a4197456": FamilyView.BY_CODE,
    "0340c32b37c19e662f4ce38481f9e20ad020713e62c4cad5810db7952473bcb1": (
        FamilyView.GROUPED_BY_CHANGE
    ),
    "5dce7f210ad1a1f9d279a9cbaa4378778b1a08eb904b8ae7e0bf908edbd28a48": FamilyView.BUYOUT_SUMMARY,
    "d08eb82e2cd4ea797f70f0e7a53699930d9d84e0a68ddbc0611c1a1606360aa2": FamilyView.RECONCILIATION,
    "ec234742713fe41cd66e05c370cb451b8c49e652dd0774f08d00236aa6c5e6c9": FamilyView.DELAYS,
    "cb7292a935751ef3b55575a2197a7cef5e172a3e275af8fd7e1b86db2bd81bcd": FamilyView.MANPOWER,
    "ea8b8dc551db37ce8539f24bfcebbe9eb579648eaaa6dcc6090c9c6092458f52": FamilyView.NOTES,
    "9aece52bb01e577ef20ba5e978951e3be8c09c16bd57407d40665c536dd17f2c": FamilyView.WEATHER,
}

M, N, D, B, T, ID = (
    ValueKind.MONEY,
    ValueKind.NUMBER,
    ValueKind.DATE,
    ValueKind.BOOLEAN,
    ValueKind.TEXT,
    ValueKind.IDENTIFIER,
)
#: The closed field catalogue per view, pinned for review: (field key, value kind).
CATALOGUE: Final = {
    FamilyView.OAC: (
        ("meeting.number", ID), ("meeting.date", D), ("item.category", T), ("item.number", ID),
        ("item.title", T), ("item.description", T), ("item.date_updated", D), ("item.minutes", T),
    ),
    FamilyView.WITH_DATE_CLOSED: (
        ("observation.assignee_vendor", T), ("observation.status", T), ("observation.count", N),
        ("observation.date_created", D), ("observation.date_closed", D),
        ("observation.number", ID), ("observation.title", T), ("observation.type", T),
        ("observation.description", T),
    ),
    FamilyView.OPEN_BY_VENDOR: (
        ("observation.assignee_vendor", T), ("observation.status", T), ("observation.count", N),
        ("observation.date_created", D), ("observation.number", ID), ("observation.title", T),
        ("observation.type", T), ("observation.description", T),
    ),
    FamilyView.BY_STATUS: (
        ("issue.status", T), ("issue.number", ID), ("issue.title", T), ("issue.description", T),
        ("issue.assignee_company", T), ("issue.assignee_name", T), ("issue.date_created", D),
        ("issue.due_date", D), ("issue.type", T), ("issue.trade", T), ("issue.date_updated", D),
    ),
    FamilyView.LINKED_TO_DRAWINGS: (
        ("rfi.number", ID), ("rfi.subject", T), ("rfi.drawing_number", ID),
        ("drawing_link.count", N), ("drawing_link.tool_type", T), ("drawing_link.type", T),
    ),
    FamilyView.OPEN_OUTSTANDING: (
        ("rfi.number", ID), ("rfi.subject", T), ("rfi.ball_in_court", T), ("rfi.priority", T),
        ("rfi.date_initiated", D), ("rfi.due_date", D), ("rfi.due_date_variance_days", N),
    ),
    FamilyView.RECENTLY_CLOSED: (
        ("rfi.number", ID), ("rfi.subject", T), ("rfi.priority", T), ("rfi.date_initiated", D),
        ("rfi.date_closed", D), ("rfi.count", N),
    ),
    FamilyView.GROUPED_BY_CHANGE: (
        ("budget_change.number", ID), ("budget_change.date_created", D),
        ("budget_change.title", T), ("budget_change.status", T), ("budget_code.code", ID),
        ("budget_code.description", T), ("adjustment.amount", M), ("adjustment.description", T),
    ),
    FamilyView.BY_CODE: (
        ("budget_code.code", ID), ("budget_code.description", T), ("adjustment.amount", M),
        ("adjustment.description", T), ("budget_change.number", ID),
        ("budget_change.date_created", D),
    ),
    FamilyView.BUYOUT_SUMMARY: (
        ("budget_code.code", ID), ("budget_line.original_amount", M),
        ("budget_change_line.amount", M), ("prime_co_line.approved_amount", M),
        ("commitment.number", ID), ("vendor.name", T), ("commitment_line.amount", M),
        ("commitment_co_line.approved_amount_with_markup", M),
    ),
    FamilyView.RECONCILIATION: (
        ("prime_co.number", ID), ("pco.number", ID), ("pco.date_created", D), ("pco.status", T),
        ("prime_co_line.description", T), ("prime_co_line.amount", M),
        ("prime_co_line.date_created", D), ("commitment_co.number", ID),
        ("commitment_co.status", T), ("commitment_co_line.description", T),
        ("commitment_co_line.amount", M),
    ),
    FamilyView.DELAYS: (
        ("delay.date", D), ("delay.type", T), ("delay.start_time", T), ("delay.end_time", T),
        ("delay.comments", T), ("weather.is_weather_delay", B),
    ),
    FamilyView.MANPOWER: (
        ("manpower.date", D), ("manpower.vendor", T), ("manpower.workers", N),
        ("manpower.hours", N), ("manpower.total_hours", N), ("manpower.comments", T),
    ),
    FamilyView.NOTES: (("note.date", D), ("note.comment", T)),
    FamilyView.WEATHER: (
        ("weather.date", D), ("weather.humidity_average", N), ("weather.temperature_average", N),
        ("weather.wind_speed_average", N), ("weather.dew_point", N),
        ("weather.precipitation_since_midnight", N),
    ),
}  # fmt: skip
#: Non-additive numeric columns (schema catalog section 11; weather averages).
NON_ADDITIVE: Final = {
    "observation.count",
    "drawing_link.count",
    "rfi.due_date_variance_days",
    "rfi.count",
    "weather.humidity_average",
    "weather.temperature_average",
    "weather.wind_speed_average",
    "weather.dew_point",
}


def _all_fixtures() -> list[Path]:
    return sorted(p for p in FIXTURES.rglob("*.csv") if "rejected" not in p.parts)


def _prepare(path: Path) -> LayerAPlan:
    return prepare_export(path.read_bytes())


def _fixture(view: FamilyView) -> Path:
    return SIGNATURES / f"{view.value}.csv"


# --- registry --------------------------------------------------------------


def test_the_registry_is_exactly_the_15_evidence_signatures() -> None:
    assert {s: a.view for s, a in REGISTRY.items()} == EVIDENCE_SIGNATURES
    assert len({a.view for a in REGISTRY.values()}) == len(FamilyView) == 15
    for signature, adapter in REGISTRY.items():
        assert header_signature(adapter.header) == signature == adapter.signature
        assert adapter.family is FAMILY_OF_VIEW[adapter.view]


@pytest.mark.parametrize("view", list(FamilyView), ids=lambda v: v.value)
def test_each_adapter_catalogue_is_pinned(view: FamilyView) -> None:
    adapter = next(a for a in REGISTRY.values() if a.view is view)
    assert tuple((f.field_key, f.value_kind) for f in adapter.fields) == CATALOGUE[view]
    assert [f.column_index for f in adapter.fields] == list(range(len(adapter.fields)))
    for spec in adapter.fields:
        if spec.field_key in NON_ADDITIVE:
            assert spec.additivity is Additivity.NON_ADDITIVE
        elif spec.value_kind is ValueKind.MONEY:
            assert spec.additivity is Additivity.ADDITIVE
        assert " > " not in spec.field_key


# --- byte-exact reconstruction ----------------------------------------------


@pytest.mark.parametrize("path", _all_fixtures(), ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_fixture_reconstructs_byte_exact(path: Path) -> None:
    data = path.read_bytes()
    plan = prepare_export(data)
    assert plan.reconstruct() == data
    assert plan.reconstruction_sha256 == plan.file_sha256 == hashlib.sha256(data).hexdigest()
    assert plan.reader_version == READER_VERSION == "pulse_csv_reader_v1"
    assert plan.byte_count == len(data)
    assert [r.ordinal for r in plan.records] == list(range(len(plan.records)))
    assert all(r.terminator is not Terminator.NONE for r in plan.records[:-1])


def test_a_reader_defect_is_caught_by_the_reconstruction_assert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pulse_csv._split_records

    def lossy(text: str, base_offset: int) -> list[pulse_csv.RawRecord]:
        records = original(text, base_offset)
        last = records[-1]
        planted = pulse_csv.RawRecord(
            last.ordinal, last.raw_record[:-1], last.terminator, last.cells, last.byte_offset
        )
        return [*records[:-1], planted]

    monkeypatch.setattr(pulse_csv, "_split_records", lossy)
    with pytest.raises(ReconstructionError):
        prepare_export(_fixture(FamilyView.WEATHER).read_bytes())


def test_terminators_bom_and_embedded_breaks_are_recorded() -> None:
    bom = _prepare(FIXTURES / "rfc" / "bom.csv")
    assert bom.bom_present and bom.header.cells[0] == "Daily Log Note > Date"
    assert bom.header.byte_offset == 3
    cr = _prepare(FIXTURES / "rfc" / "cr_only.csv")
    assert {r.terminator for r in cr.records} == {Terminator.CR}
    assert cr.rows[1].cells[1] == "in\rquotes" and cr.rows[1].embedded_cr == 1
    mixed = _prepare(FIXTURES / "rfc" / "mixed_terminators.csv")
    assert [r.terminator for r in mixed.records] == [
        Terminator.CRLF,
        Terminator.LF,
        Terminator.CR,
        Terminator.CRLF,
    ]
    crlf = _prepare(FIXTURES / "rfc" / "embedded_crlf.csv")
    assert crlf.rows[0].cells[1] == "first\r\nsecond" and crlf.rows[0].embedded_crlf == 1
    assert len(crlf.rows) == 1
    last = _prepare(FIXTURES / "rfc" / "no_trailing_terminator.csv")
    assert last.rows[-1].terminator is Terminator.NONE
    quotes = _prepare(FIXTURES / "rfc" / "doubled_quotes.csv")
    assert [r.cells[1] for r in quotes.rows] == ['a "quoted" word', '""']
    for name, terminator in (
        ("header_only_terminated.csv", Terminator.LF),
        ("header_only_unterminated.csv", Terminator.NONE),
    ):
        plan = _prepare(FIXTURES / "rfc" / name)
        assert plan.rows == () and plan.header.terminator is terminator
    blanks = _prepare(FIXTURES / "rfc" / "empty_fields_and_trailing_comma.csv")
    assert [r.cells for r in blanks.rows] == [("", ""), ("7/1/2026", "")]


def test_byte_offsets_are_utf8_byte_positions() -> None:
    data = "Daily Log Note > Date,Daily Log Note > Comment\n7/1/2026,café\n7/2/2026,x\n".encode()
    plan = prepare_export(data)
    for record in plan.records:
        assert data[record.byte_offset :].startswith(record.raw_record.encode())


# --- rejection codes ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("not_utf8.csv", RejectionCode.NOT_UTF8),
        ("unterminated_quote.csv", RejectionCode.MALFORMED_CSV),
        ("quote_in_unquoted.csv", RejectionCode.MALFORMED_CSV),
        ("text_after_closing_quote.csv", RejectionCode.MALFORMED_CSV),
        ("nul_byte.csv", RejectionCode.NUL_BYTE),
        ("duplicate_header.csv", RejectionCode.INVALID_HEADER),
        ("empty_header_cell.csv", RejectionCode.INVALID_HEADER),
        ("empty_file.csv", RejectionCode.INVALID_HEADER),
        ("bom_only.csv", RejectionCode.INVALID_HEADER),
    ],
)
def test_each_rejection_code(name: str, code: RejectionCode) -> None:
    with pytest.raises(ExportRejectedError) as rejected:
        prepare_export((FIXTURES / "rejected" / name).read_bytes())
    assert rejected.value.code is code
    assert str(rejected.value) == code.value  # the message is the code only


def test_rejection_diagnostics_are_record_and_offset_only() -> None:
    with pytest.raises(ExportRejectedError) as rejected:
        prepare_export((FIXTURES / "rejected" / "unterminated_quote.csv").read_bytes())
    assert (rejected.value.record, rejected.value.offset) == (1, 47)
    with pytest.raises(ExportRejectedError) as nul:
        prepare_export((FIXTURES / "rejected" / "nul_byte.csv").read_bytes())
    assert nul.value.offset == 57


def test_every_rejection_code_has_a_fixture() -> None:
    covered = set()
    for path in sorted((FIXTURES / "rejected").glob("*.csv")):
        with pytest.raises(ExportRejectedError) as rejected:
            prepare_export(path.read_bytes())
        covered.add(rejected.value.code)
    assert covered == set(RejectionCode)


def test_oversize_is_skipped_not_rejected() -> None:
    with pytest.raises(ExportTooLargeError):
        prepare_export(b"a\n" + b"x" * MAX_EXPORT_BYTES)
    assert MAX_EXPORT_BYTES == 16 * 1024 * 1024
    with pytest.raises(TypeError):
        prepare_export("text")  # type: ignore[arg-type]


# --- quarantine -------------------------------------------------------------


@pytest.mark.parametrize("name", ["reordered_weather.csv", "unknown_family.csv"])
def test_an_unknown_signature_quarantines_with_every_row_kept(name: str) -> None:
    plan = derive(_prepare(FIXTURES / "variants" / name))
    assert plan.state is DerivationState.QUARANTINED
    assert plan.quarantine_reason is QuarantineReason.UNKNOWN_HEADER_SIGNATURE
    assert plan.adapter is None and plan.rows == () and plan.lines == ()
    assert plan.role_counts == {UNCLASSIFIED_COUNT_KEY: len(plan.layer_a.rows)}
    assert len(plan.layer_a.rows) > 0
    assert plan.layer_a.reconstruct() == (FIXTURES / "variants" / name).read_bytes()


def test_a_reordered_header_is_a_new_signature() -> None:
    reordered = _prepare(FIXTURES / "variants" / "reordered_weather.csv")
    weather = _prepare(_fixture(FamilyView.WEATHER))
    assert sorted(reordered.header.cells) == sorted(weather.header.cells)
    assert reordered.signature != weather.signature and reordered.signature not in REGISTRY


def _notes_export(rows: int, malformed: int) -> bytes:
    lines = ["Daily Log Note > Date,Daily Log Note > Comment"]
    lines += ["7/1/2026,ok"] * (rows - malformed)
    lines += ["7/1/2026,too,wide"] * malformed
    return ("\n".join(lines) + "\n").encode()


def test_the_malformed_ratio_boundary_is_exact() -> None:
    at_one_percent = derive(prepare_export(_notes_export(100, 1)))
    assert at_one_percent.state is DerivationState.CLASSIFIED
    assert at_one_percent.role_counts[RowRole.MALFORMED.value] == 1
    over = derive(prepare_export(_notes_export(99, 1)))
    assert over.state is DerivationState.QUARANTINED
    assert over.quarantine_reason is QuarantineReason.MALFORMED_RATIO_EXCEEDED
    assert over.role_counts == {UNCLASSIFIED_COUNT_KEY: 99}
    assert len(over.layer_a.rows) == 99
    two = derive(prepare_export(_notes_export(100, 2)))
    assert two.state is DerivationState.QUARANTINED


def test_a_malformed_width_fixture_quarantines_over_the_ratio() -> None:
    plan = derive(_prepare(FIXTURES / "variants" / "malformed_width.csv"))
    assert plan.quarantine_reason is QuarantineReason.MALFORMED_RATIO_EXCEEDED
    assert plan.role_counts == {UNCLASSIFIED_COUNT_KEY: 3}


def test_a_malformed_row_under_the_ratio_is_never_a_line() -> None:
    plan = derive(prepare_export(_notes_export(100, 1)))
    malformed = [r for r in plan.rows if r.role is RowRole.MALFORMED]
    assert len(malformed) == 1 and malformed[0].reason is RowReason.WIDTH_MISMATCH
    assert malformed[0].ordinal not in {line.ordinal for line in plan.lines}
    assert len(plan.lines) == 99


# --- adapters against their fixtures ----------------------------------------


@pytest.mark.parametrize("view", list(FamilyView), ids=lambda v: v.value)
def test_every_adapter_against_its_fixture(view: FamilyView) -> None:
    plan = derive(_prepare(_fixture(view)), project_number=PROJECT)
    assert plan.state is DerivationState.CLASSIFIED, plan.quarantine_reason
    assert plan.adapter is not None and plan.adapter.view is view
    assert sum(plan.role_counts.values()) == len(plan.layer_a.rows)
    details = [r for r in plan.rows if r.role is RowRole.DETAIL]
    assert [line.ordinal for line in plan.lines] == [r.ordinal for r in details]
    for line in plan.lines:
        assert line.state is ObservationState.TYPED, line.reasons
        assert tuple((v.field_key, v.value_kind) for v in line.values) == CATALOGUE[view]
        assert line.line_kind in plan.adapter.line_kinds
        cells = plan.layer_a.rows[line.ordinal - 1].cells
        for value, raw in zip(line.values, cells, strict=True):
            assert value.raw_text == raw
            if raw == "":
                assert value.value is None
            elif value.value_kind is ValueKind.MONEY or value.value_kind is ValueKind.NUMBER:
                assert type(value.value) is Decimal
                assert value.value.as_tuple().exponent == -4
            elif value.value_kind is ValueKind.DATE:
                assert type(value.value) is date
            elif value.value_kind is ValueKind.BOOLEAN:
                assert type(value.value) is bool
            else:
                assert value.value == raw
    for check in plan.stated_totals:
        assert check.outcome is not ReconciliationOutcome.MISMATCH, check


def test_completeness_classes_from_the_fixtures() -> None:
    expected = {
        FamilyView.NOTES: CompletenessClass.VALID_EMPTY,
        FamilyView.DELAYS: CompletenessClass.GROUPING_ONLY,
    }
    for view in FamilyView:
        plan = derive(_prepare(_fixture(view)))
        assert plan.completeness is expected.get(view, CompletenessClass.POPULATED)


def test_line_kinds_identity_and_status_per_family() -> None:
    buyout = derive(_prepare(_fixture(FamilyView.BUYOUT_SUMMARY)), project_number=PROJECT)
    kinds = [line.line_kind for line in buyout.lines]
    assert kinds.count(LineKind.VENDOR_ONLY) == 2 and kinds.count(LineKind.COMMITMENT) == 2
    assert {LineKind.BUDGET_LINE, LineKind.BUDGET_CHANGE, LineKind.PRIME_CHANGE_ORDER} <= set(kinds)
    commitments = [line for line in buyout.lines if line.line_kind is LineKind.COMMITMENT]
    # 2 padding styles of one commitment under one code: one normalized key.
    assert {line.identity.key for line in commitments} == {"commitment:SYN-0001.1@SYN-0001.01-100"}
    assert all(line.identity.state is IdentityState.IDENTIFIED for line in commitments)
    vendor_only = [line for line in buyout.lines if line.line_kind is LineKind.VENDOR_ONLY]
    assert all(line.identity.state is IdentityState.SNAPSHOT_SCOPED for line in vendor_only)

    reconciliation = derive(_prepare(_fixture(FamilyView.RECONCILIATION)))
    statuses = [(line.line_kind, line.status_class) for line in reconciliation.lines]
    assert statuses == [
        (LineKind.PRIME_PCO_LINE, StatusClass.APPROVED),
        (LineKind.PRIME_PCO_LINE, StatusClass.PENDING),
        (LineKind.PRIME_PCO_LINE, StatusClass.VOID),
        (LineKind.PRIME_PCO_LINE, StatusClass.APPROVED),
        (LineKind.COMMITMENT_CO_LINE, StatusClass.APPROVED),
    ]
    co_line = reconciliation.lines[-1]
    assert co_line.identity.state is IdentityState.SNAPSHOT_SCOPED
    assert co_line.identity_reason is RowReason.AMBIGUOUS_COMMITMENT_CO

    rfis = derive(_prepare(_fixture(FamilyView.OPEN_OUTSTANDING)))
    assert [line.identity.state for line in rfis.lines] == [
        IdentityState.IDENTIFIED,
        IdentityState.IDENTITY_MISSING,
        IdentityState.IDENTIFIED,
    ]
    assert rfis.lines[1].identity_reason is RowReason.IDENTITY_MISSING
    links = derive(_prepare(_fixture(FamilyView.LINKED_TO_DRAWINGS)))
    # Repeated RFI rows are kept as separate lines, never collapsed.
    assert [line.identity.key for line in links.lines] == ["rfi:GMP-1", "rfi:GMP-1", "rfi:CD 50%-2"]

    issues = derive(_prepare(_fixture(FamilyView.BY_STATUS)))
    assert [line.status_class for line in issues.lines] == [
        StatusClass.OPEN,
        StatusClass.OPEN,
        StatusClass.UNKNOWN,
    ]
    observations = derive(_prepare(_fixture(FamilyView.WITH_DATE_CLOSED)))
    assert [line.status_class for line in observations.lines] == [
        StatusClass.OPEN,
        StatusClass.OPEN,
        StatusClass.CLOSED,
        StatusClass.OPEN,
    ]
    manpower = derive(_prepare(_fixture(FamilyView.MANPOWER)))
    assert [line.identity.key for line in manpower.lines] == [
        "manpower:7/1/2026@Synthetic Vendor A",
        "manpower:7/1/2026@Synthetic Vendor B",
    ]
    budget = derive(_prepare(_fixture(FamilyView.GROUPED_BY_CHANGE)), project_number=PROJECT)
    assert all(line.identity.state is IdentityState.SNAPSHOT_SCOPED for line in budget.lines)
    assert [line.status_class for line in budget.lines] == [StatusClass.APPROVED] * 2 + [
        StatusClass.PENDING
    ] * 2


def test_a_type_failure_degrades_the_line_and_keeps_the_raw_text() -> None:
    data = (
        b"Daily Log Observed Weather Condition > Date,"
        b"Daily Log Observed Weather Condition > Measured Humidity Average,"
        b"Daily Log Observed Weather Condition > Measured Temperature Average,"
        b"Daily Log Observed Weather Condition > Measured Wind Speed Average,"
        b"Daily Log Observed Weather Condition > Measured Dew Point,"
        b"Daily Log Observed Weather Condition > Measured Precipitation Since Midnight\n"
        b"13/40/2026,61.123456,n/a,8,1,0\n"
    )
    plan = derive(prepare_export(data))
    (line,) = plan.lines
    assert line.state is ObservationState.DEGRADED
    assert line.reasons == (RowReason.TYPE_ERROR, RowReason.MORE_THAN_4_DECIMALS)
    assert [v.raw_text for v in line.values][:3] == ["13/40/2026", "61.123456", "n/a"]
    assert [v.value for v in line.values][:3] == [None, None, None]
    assert plan.layer_a.reconstruct() == data


def test_the_two_level_double_count_returns_the_detail_sum() -> None:
    """Grain section 6: detail-only gives 99 where a naive 1-level reading gives 198."""
    plan = derive(_prepare(FIXTURES / "two_level" / "observations_99.csv"))
    assert plan.role_counts["detail"] == 99 and plan.role_counts["group_header"] == 3
    count = [v for line in plan.lines for v in line.values if v.field_key == "observation.count"]
    assert sum(v.value for v in count if isinstance(v.value, Decimal)) == 99
    rows = plan.layer_a.rows
    under_first_level = [
        Decimal(rows[r.ordinal - 1].cells[2])
        for r in plan.rows
        if r.role is not RowRole.GRAND_TOTAL and r.group_level != 1
    ]
    assert sum(under_first_level) == 198
    # Count is non-additive: its stated totals are never checked as a measure.
    assert {c.outcome for c in plan.stated_totals} == {ReconciliationOutcome.NOT_CHECKED}


# --- the filename is never an input -----------------------------------------


def test_derive_reads_bytes_only() -> None:
    plans = [derive(_prepare(_fixture(view))) for view in FamilyView]
    for plan, view in zip(plans, FamilyView, strict=True):
        assert plan.adapter is not None and plan.adapter.view is view
    swapped = derive(prepare_export(_fixture(FamilyView.NOTES).read_bytes()))
    assert swapped.adapter is not None and swapped.adapter.view is FamilyView.NOTES


# --- the project-number cross-check (D11) -----------------------------------


@pytest.mark.parametrize(
    ("value", "number", "carries"),
    [
        ("SYN-0001.01-100", "SYN-0001", True),
        ("SYN-0001", "SYN-0001", True),
        ("SYN-00012.01", "SYN-0001", False),
        ("SYN-0002.01-100", "SYN-0001", False),
        ("01-100", "SYN-0001", False),
        (" SYN-0001.0001 ", "SYN-0001", True),
        ("SYN-0001.01", "", False),
    ],
)
def test_carries_project_number_is_token_bounded(value: str, number: str, carries: bool) -> None:
    assert carries_project_number(value, number) is carries


@pytest.mark.parametrize(
    "view", [FamilyView.BUYOUT_SUMMARY, FamilyView.GROUPED_BY_CHANGE, FamilyView.BY_CODE]
)
def test_the_cross_check_match_mismatch_and_not_checked(view: FamilyView) -> None:
    layer_a = _prepare(_fixture(view))
    assert derive(layer_a, project_number=PROJECT).cross_check is ReconciliationOutcome.MATCH
    assert derive(layer_a).cross_check is ReconciliationOutcome.NOT_CHECKED
    mismatch = derive(layer_a, project_number="SYN-0002")
    assert mismatch.cross_check is ReconciliationOutcome.MISMATCH
    assert mismatch.state is DerivationState.QUARANTINED
    assert mismatch.quarantine_reason is QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH
    assert mismatch.role_counts == {UNCLASSIFIED_COUNT_KEY: len(layer_a.rows)}


def test_views_without_identifier_columns_have_no_cross_check() -> None:
    for view in (FamilyView.RECONCILIATION, FamilyView.OAC, FamilyView.MANPOWER):
        plan = derive(_prepare(_fixture(view)), project_number="SYN-0002")
        assert plan.cross_check is None and plan.state is DerivationState.CLASSIFIED


# --- the cross-report check -------------------------------------------------


def test_the_cross_report_check_on_synthetic_numbers() -> None:
    buyout = derive(_prepare(_fixture(FamilyView.BUYOUT_SUMMARY)), project_number=PROJECT)
    reconciliation = derive(_prepare(_fixture(FamilyView.RECONCILIATION)))
    check = pair_cross_report(buyout, reconciliation)
    assert check.outcome is ReconciliationOutcome.MATCH
    assert check.left_value == check.right_value == Decimal("300.0000")
    assert pair_cross_report(reconciliation, buyout).outcome is ReconciliationOutcome.NOT_CHECKED
    quarantined = derive(_prepare(_fixture(FamilyView.BUYOUT_SUMMARY)), project_number="SYN-0002")
    assert pair_cross_report(quarantined, reconciliation).outcome is (
        ReconciliationOutcome.NOT_CHECKED
    )


def test_the_fixture_bytes_are_protected_from_line_ending_normalization() -> None:
    root = Path(__file__).resolve().parents[2]
    rules = (root / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "tests/fixtures/project_reports/csv/** binary" in rules
    assert (FIXTURES / "rfc" / "crlf.csv").read_bytes().count(b"\r\n") == 2
    assert b"\n" not in (FIXTURES / "rfc" / "cr_only.csv").read_bytes()
    assert (FIXTURES / "rfc" / "bom.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert not (FIXTURES / "rfc" / "no_trailing_terminator.csv").read_bytes().endswith(b"\n")
