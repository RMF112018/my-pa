"""Synthetic Full-Schedule fixtures: determinism, pins and independent ground truth.

FAST. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 8 and 9. This module pins every generated PDF by SHA-256 and size,
proves the generator is deterministic, and checks that each case's ground
truth (written by the generator from its own layout plan, never from parser
output) is internally consistent and representable as domain records. The
parse-versus-golden and parse-versus-truth tests of contract sections 9, 10.2
and 10.3 (`GOLDEN_FILE_SHA256`, `test_every_case_matches_its_golden`,
`test_quality_gates_hold_over_every_case`, ...) are added here by the WP-02
parser change, which also writes the golden files.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleIssueCode,
    ScheduleParseIssue,
    ScheduleRowType,
    derive_outcome,
)
from my_pa.infrastructure.schedule import ScheduleParseLimits
from my_pa.infrastructure.schedule.full_profile import MEASURED_CORPUS
from tests.fixtures import schedule_full_pdf as gen

ROOT: Final = Path(__file__).resolve().parents[2]

#: SHA-256 and byte size of every generated PDF. A generator change that moves
#: a single byte fails here until this table is edited in the same diff.
PDF_PINS: Final[dict[tuple[str, str], tuple[str, int]]] = {
    ("full_valid_2p", "base"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("full_valid_2p", "subset_prefix"): (
        "803e80a9b1b7957750d2bf980ebd97e6978a301bf95a256538b6fcbe3d5da3db",
        13020,
    ),
    ("full_valid_2p", "zone_edges"): (
        "60998969a368c6e2f920c2f9cc7f94d9aeff7ab8b579069f488abc2db6165476",
        14017,
    ),
    ("full_valid_2p", "split_name"): (
        "3d9f24d7c8dd2c3984e0528877f37c71016eded2851baa6c1f9de58419e59020",
        13086,
    ),
    ("full_valid_2p", "id_double_space"): (
        "570fb78c2c196f8d3ac81d67be8dd3863144f63ad9199b9577134f8cb13734b0",
        13014,
    ),
    ("full_merged_summary_label", "base"): (
        "ae21b4420ad9ed5ca9dbb25bce527a756fb5d01f5d164673e3f74091c63ef187",
        9502,
    ),
    ("full_merged_summary_label", "label_only"): (
        "6a0b16bf46dab84404f50d5c41b646415d0407011a1c2e2f4831fd582c015330",
        9593,
    ),
    ("full_summary_vertical_offset", "base"): (
        "62451ee6d14390fd7cc4abbaf0614deeeda87fa9da9f7ace9f4c4d5bbd3f3dfb",
        10368,
    ),
    ("full_summary_vertical_offset", "glyph_metrics"): (
        "a656b080bc243e305ab5c6e6389b27a11987764c9a61fb211466d4a19ed7c7df",
        11350,
    ),
    ("full_summary_zero_zero", "base"): (
        "b7bd72657a5db97703ebbf767ca2aa8a588fd85fc4138cafb9691127d07ecec2",
        8903,
    ),
    ("full_summary_zero_zero", "id_both_dates"): (
        "a9ff7bc8b07c75baa7aa97b5d4e35664e6a63e8ddc85cfb1c64ce0c81764f258",
        9390,
    ),
    ("full_nested_hierarchy", "base"): (
        "0cf87edfd62df75705d113500462532180b77539736ff1f9a4b0820b62158213",
        19756,
    ),
    ("full_header_occluded_od", "replaced"): (
        "822e57350f4ecde99303652c665804685c0ad34203650f5a9f0faf2fa03d1585",
        10823,
    ),
    ("full_header_occluded_od", "overlay"): (
        "a3b7a4b33a525f2ac4f66808578ce6e67e920605fb91daf221aa434d0819f9b4",
        10900,
    ),
    ("full_header_mismatch", "later_page"): (
        "87b6340de0904c3fbf7f996a5bad75e4e1abcae0c0e1790eaac88ef2963603cd",
        10177,
    ),
    ("full_header_mismatch", "first_page"): (
        "57bf1097a912f20ddd3db338180396e9a9bd5585c08ebd54583c6e2eb6daa64b",
        10177,
    ),
    ("full_missing_activity_id", "base"): (
        "f5c31d6957758bfb43d7f5cea7faa19b7acbc49e4b67013e655afac48240000e",
        11234,
    ),
    ("full_duplicate_activity_id", "base"): (
        "e706bfdcad7ed22b8a594e9a57e2a8a8482194bd45602d8ac390da543a7ad3f2",
        9470,
    ),
    ("full_duration_date_in_rd", "base"): (
        "47ac640c0cb1c2da72de2d9f9baf8259e2578b8c0042dbd4b332a28b93b02a2c",
        8999,
    ),
    ("full_duration_date_in_od", "base"): (
        "cb840e81b503f256f7fcea84a468225c451c879dbd785da03252cfcd86fbdff5",
        8989,
    ),
    ("full_invalid_date", "base"): (
        "a77112ea215f49a7bcc198d41fbb11b10b6acb8d1fb3451228a23bf754cb5626",
        9468,
    ),
    ("full_chart_duplicates", "base"): (
        "26cfdf5550af773dfbb17c654e0a1506ee257de308b4dd2ec9ea0dcb11c0f66b",
        11481,
    ),
    ("full_draft_watermark", "signature"): (
        "cb93205eca3e21bdfb1a2102669a65704b3e127687b14b4faf045fae9881567e",
        16856,
    ),
    ("full_draft_watermark", "off_signature"): (
        "9e6a1051c87f9dbd8f462db4854c102da4fef404ced09ee24729ce117b0437d1",
        16856,
    ),
    ("full_draft_watermark", "slight_skew"): (
        "00b0939ee2ac1bf60cdc894a7dc9d54949deaa2ac7cf525e30d9ba3743242277",
        16886,
    ),
    ("full_draft_watermark", "skew_1deg"): (
        "3e2d700a9437099371abb2ab68b3043a08308fad0553966b7136b3574cf1bf19",
        16886,
    ),
    ("full_draft_watermark", "double_draw"): (
        "9e32298fa7a03be606d83859ed8a0221fea0e9f4f0e4dba443883c82592a9c7b",
        16968,
    ),
    ("full_duplicate_text_object", "base"): (
        "e0bd16d476d2b3376fc3bcb3f3232734f562dfc2dba85e6835d20adb89dca0dc",
        9248,
    ),
    ("full_duplicate_text_object", "shift_0_5"): (
        "332030ca76e0a0d7beb62848fd901a39c4f4499320f19b450aa5a2e618957c11",
        8592,
    ),
    ("full_duplicate_text_object", "bold_over_regular"): (
        "5b7852f43261ae064664e012f9f4876ebdba09669606a46f90ec03969a9d076e",
        8590,
    ),
    ("full_duplicate_text_object", "same_text_2pt"): (
        "c06390b237942875000d4bdb515c9beb372f60ff2d8e1f6c1e089583ede23de0",
        9058,
    ),
    ("full_duplicate_text_object", "under_watermark"): (
        "333844bc04bb18e827f2cc1e50918c991baa60b5a4e62a147fb1be4895236996",
        14794,
    ),
    ("full_overlapping_cell_text", "od"): (
        "9a9fa59c56365a2a76f9cdd74500de5af5f4facf451dad29df4516e1aa61fdc6",
        9544,
    ),
    ("full_overlapping_cell_text", "id"): (
        "f2e342a660988c7631f574b6584b977de2545108eb9431cb71887c113267c0af",
        9549,
    ),
    ("full_overlapping_cell_text", "id_split"): (
        "fae8c35e13bc2214037a74d001818b3f388ff267ec0667f2062392d815c831f9",
        9541,
    ),
    ("full_overlapping_cell_text", "unmapped"): (
        "e5d58892355034df9d6281783099e76799c302612774c5a8d14ac28c30e1b9f7",
        11958,
    ),
    ("full_overlapping_cell_text", "zero_char_object"): (
        "2dabe5c0c670b8b68ae740e6d1b0df2bf11051048a4cc4895002e43ec6f15674",
        9544,
    ),
    ("full_ambiguous_hierarchy", "close_centroids"): (
        "6776f23ecf6d6faa15043314f727ee1797c698c3d928b89f5a59e68c54f7dd09",
        8581,
    ),
    ("full_ambiguous_hierarchy", "orphan"): (
        "f678ea6bcda8a3269880b99d2a1a1c8d2cc2ace85ab544c55d6733fa3e5300fc",
        9468,
    ),
    ("full_ambiguous_hierarchy", "level_gap"): (
        "acb1f206745c8a207ea92080817bab51452f7b8ad41411682466065ef448a030",
        9469,
    ),
    ("full_row_wrap_unsupported", "regular_name"): (
        "10d8f848e52c76fe4cbfab6ca3900b15a98505b5cded6f5a177abcc2a421d168",
        9081,
    ),
    ("full_row_wrap_unsupported", "bold_label"): (
        "cf15fd2b104394d07711c8231ca6ac8d4f11a3a0670185295b017e0d3d37a93b",
        9495,
    ),
    ("full_multi_page_86_equivalent", "base"): (
        "db2f8945c8d41611695245de8ba040327b65874899f8f413de7a141dfae8ff3d",
        2619466,
    ),
    ("corrupt_pdf", "garbage"): (
        "e3b29e6f2a90ca79b980c56e2568b195c40bd959b419622684beef16e7a69328",
        81,
    ),
    ("corrupt_pdf", "not_a_pdf"): (
        "07bcbca5e5cff5eadb6a3578850bb9413f9bfd2406d9210b0c25b7f78449889a",
        9,
    ),
    ("corrupt_pdf", "empty"): (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        0,
    ),
    ("encrypted_pdf", "user_password"): (
        "988526ea92a05e5ff5e2e371cad1d72f274c79f51baaeae6671a971d3d9bebff",
        9302,
    ),
    ("encrypted_pdf", "empty_user_password"): (
        "4bd95b82ef75680e6f60c0b47c1a47b7141a8bbbd9ae5e55d2d998c141bed8a2",
        9302,
    ),
    ("encrypted_pdf", "unknown_filter"): (
        "f46879311f930380ca71f52a71df4e531211edeb4b88fd27d4d82c94a1363393",
        9304,
    ),
    ("image_only_pdf", "base"): (
        "39df336be179004e192642d79bc64750cf8e57b241ea2911e6d267cb3b8fe4e9",
        689,
    ),
    ("wrong_page_size", "letter"): (
        "041586848f125bda4494e5cd699b846f7fe6b83590b1253657c5d148b5dd20ae",
        8981,
    ),
    ("wrong_page_size", "rotated"): (
        "663bdce125c415cec544c9d718369b15a3f3a010956ab91c5bd962f694768c34",
        8993,
    ),
    ("wrong_page_size", "rotated_180"): (
        "56fb25b94bc5e72224418bb2f4bcde0deb9a069e4056875f2836c50632ed1352",
        8994,
    ),
    ("wrong_page_size", "offset_origin"): (
        "5a139b195c3f6d3d2409ae461d680e8d27884d716a20a53420434aa9e53a39b3",
        8985,
    ),
    ("wrong_page_size", "zero_pages"): (
        "b7e2733873fd6172ca77d8d3ac762ba95c4297995252be3892682e1921b3d7b1",
        5855,
    ),
    ("page_metadata_mismatch", "data_date"): (
        "65e459af7ad9bd72695fbf8d8699f3913f3a79664632e73ae2479ee7b9c9dbb7",
        10332,
    ),
    ("page_metadata_mismatch", "run_date"): (
        "940009819af8403826550cde7b92f345ce9a00d437b16576f615b587665a661f",
        10332,
    ),
    ("page_metadata_mismatch", "title"): (
        "cb20e341fefd7800da561cca6c7a204a0c4ea36bd10815d1b6bfd5eeedf38dbd",
        10340,
    ),
    ("page_metadata_mismatch", "page_number"): (
        "2e24ecc8a1eac76b81045d91d03b64db104f264f5b2ee4321553947d4f26d83c",
        10332,
    ),
    ("page_metadata_mismatch", "page_total"): (
        "a9915d028596e865c313e1faad3ea14b1ac353fdd706af2f59539ec06f163918",
        10332,
    ),
    ("expected_data_date_mismatch", "mismatch"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("expected_data_date_mismatch", "match"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "bytes"): (
        "b82cfa9ac320b45f63c48dfbadd9e83b137c6054a4891f26675f1c609de4bc01",
        16777217,
    ),
    ("bounds_exceeded", "pages"): (
        "401f525e2201eeea7d62689a97385cbbb79a50579ab569ec9ad25526de145e0b",
        55753,
    ),
    ("bounds_exceeded", "text_objects"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "page_objects"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "chars"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "rows"): (
        "fc85e1335f1862a23aa02e6b8daa6f45d55f2d96f8b96e4554505758db1c9dba",
        8982,
    ),
    ("bounds_exceeded", "issues"): (
        "a77112ea215f49a7bcc198d41fbb11b10b6acb8d1fb3451228a23bf754cb5626",
        9468,
    ),
    ("bounds_exceeded", "row_warnings"): (
        "332030ca76e0a0d7beb62848fd901a39c4f4499320f19b450aa5a2e618957c11",
        8592,
    ),
    ("bounds_exceeded", "hierarchy_depth"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "cell_evidence"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "form_text"): (
        "ce33f957623d88d597ba99655409b261736ec90ace7b3656af95c2685ad36054",
        9268,
    ),
    ("bounds_exceeded", "form_depth"): (
        "5ad537079e56ae7a8d314ecdfd0a93c6e3a02a3ac14566d783edc318c03babed",
        10031,
    ),
    ("bounds_exceeded", "time_first"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
    ("bounds_exceeded", "time_mid"): (
        "47c16cb6da90ce75b292436bf7cdff3157ae88ca599ab37106e52144db09bb8a",
        13013,
    ),
}


def test_the_registry_holds_the_26_r2_families_in_contract_order() -> None:
    assert list(gen.FAMILIES) == [
        "full_valid_2p",
        "full_merged_summary_label",
        "full_summary_vertical_offset",
        "full_summary_zero_zero",
        "full_nested_hierarchy",
        "full_header_occluded_od",
        "full_header_mismatch",
        "full_missing_activity_id",
        "full_duplicate_activity_id",
        "full_duration_date_in_rd",
        "full_duration_date_in_od",
        "full_invalid_date",
        "full_chart_duplicates",
        "full_draft_watermark",
        "full_duplicate_text_object",
        "full_overlapping_cell_text",
        "full_ambiguous_hierarchy",
        "full_row_wrap_unsupported",
        "full_multi_page_86_equivalent",
        "corrupt_pdf",
        "encrypted_pdf",
        "image_only_pdf",
        "wrong_page_size",
        "page_metadata_mismatch",
        "expected_data_date_mismatch",
        "bounds_exceeded",
    ]
    assert len(gen.CASES) == len(set(gen.CASES)) == 76
    assert set(PDF_PINS) == set(gen.CASES)
    assert set(gen.CASES) >= gen.RESULTLESS_CASES


@pytest.mark.parametrize(("family", "variant"), gen.CASES, ids=lambda v: str(v))
def test_generated_pdfs_are_deterministic_and_pinned(family: str, variant: str) -> None:
    builder, _ = gen.FAMILIES[family]
    first = builder(variant).pdf
    second = builder(variant).pdf
    assert first == second
    case = gen.build(family, variant)
    assert case.pdf == first
    assert (case.sha256, len(case.pdf)) == PDF_PINS[(family, variant)]


def test_no_pdf_or_golden_is_written_by_the_generator_at_import_or_build() -> None:
    assert not list((ROOT / "tests").rglob("*.pdf"))
    assert gen.golden_path("full_valid_2p", "base") == (
        ROOT / "tests" / "fixtures" / "schedule_full_goldens" / "full_valid_2p__base.json"
    )


def test_linkage_basis_follows_the_outcome() -> None:
    assert gen.linkage_basis("complete") == gen.linkage_basis("partial") == "eligible"
    assert gen.linkage_basis("review_required") == "review_required"
    assert gen.linkage_basis("failed") == "failed"


def test_fake_clock_expires_after_exactly_k_calls() -> None:
    clock = gen.fake_clock(2)
    assert [clock() for _ in range(4)] == [0.0, 0.0, 10.0, 10.0]
    assert gen.fake_clock(0)() == 10.0
    assert {gen.fake_clock(None)() for _ in range(3)} == {0.0}


def test_bounds_variants_only_tighten_production_limits() -> None:
    for variant, limits in gen.BOUNDS_LIMITS.items():
        case = gen.build("bounds_exceeded", variant)
        assert case.limits == limits
        ScheduleParseLimits(**limits)
    production = [
        case for family, variant in gen.CASES if (case := gen.build(family, variant)).limits is None
    ]
    assert len(production) == len(gen.CASES) - len(gen.BOUNDS_LIMITS)


# --- ground truth -------------------------------------------------------------


def _duration(state: str, value: str | None) -> ScheduleDurationCell:
    return ScheduleDurationCell(ScheduleCellState(state), None if value is None else Decimal(value))


def _date(state: str, value: str | None, marker: str | None) -> ScheduleDateCell:
    return ScheduleDateCell(
        ScheduleCellState(state), None if value is None else date.fromisoformat(value), marker
    )


def _domain_row(ordinal: int, row: gen.TruthRow) -> ParsedScheduleRow:
    cells = tuple(
        ScheduleCellEvidence(
            ScheduleFieldCode(cell.field),
            ScheduleCellState(cell.state),
            cell.text,
            tuple(
                ScheduleCellFragment("x", ScheduleBox(*box), "Arial", 7_000) for box in cell.boxes
            ),
        )
        for cell in row.cells
    )
    return ParsedScheduleRow(
        row_ordinal=ordinal,
        page_number=row.page,
        physical_line_ordinal=row.line,
        row_type=ScheduleRowType(row.row_type),
        indent_level=row.indent_level,
        parent_row_ordinal=row.parent,
        hierarchy_path=row.hierarchy_path,
        published_activity_id=row.activity_id,
        activity_name=row.name,
        original_duration=_duration(*row.original_duration),
        remaining_duration=_duration(*row.remaining_duration),
        start=_date(*row.start),
        finish=_date(*row.finish),
        box=ScheduleBox(*row.box),
        page_width_mpt=1_224_000,
        page_height_mpt=792_000,
        cells=cells,
        warning_codes=tuple(ScheduleIssueCode(code) for code in row.warning_codes),
    )


def _truth_issues(truth: gen.Truth) -> list[ScheduleParseIssue]:
    issues = []
    for code, page, fld in truth.document_issues:
        issue_code = ScheduleIssueCode(code)
        field = None if fld is None else ScheduleFieldCode(fld)
        issues.append(ScheduleParseIssue(issue_code, ISSUE_SEVERITY[issue_code], page, None, field))
    for ordinal, row in enumerate(truth.rows, start=1):
        for code, fld in row.issues:
            issue_code = ScheduleIssueCode(code)
            field = None if fld is None else ScheduleFieldCode(fld)
            issues.append(
                ScheduleParseIssue(issue_code, ISSUE_SEVERITY[issue_code], row.page, ordinal, field)
            )
    return issues


@pytest.mark.parametrize(("family", "variant"), gen.CASES, ids=lambda v: str(v))
def test_ground_truth_is_consistent_and_representable(family: str, variant: str) -> None:
    truth = gen.build(family, variant).truth
    issues = _truth_issues(truth)
    rows = [_domain_row(ordinal, row) for ordinal, row in enumerate(truth.rows, start=1)]
    assert derive_outcome(issues, rows).value == truth.outcome
    if truth.outcome == gen.FAILED:
        assert truth.rows == ()
        assert len(truth.document_issues) == 1
        assert truth.counts is None
        return
    assert truth.counts is not None
    assert truth.counts["rows"] == len(rows)
    assert truth.counts["issues"] == sum(truth.issue_counts.values())
    lines: Counter[int] = Counter()
    previous_page = 0
    for ordinal, row in enumerate(rows, start=1):
        lines[row.page_number] += 1
        assert row.physical_line_ordinal == lines[row.page_number]
        assert row.page_number >= previous_page
        previous_page = row.page_number
        if row.parent_row_ordinal is not None:
            parent = rows[row.parent_row_ordinal - 1]
            assert parent.row_type in (ScheduleRowType.PROJECT_SUMMARY, ScheduleRowType.WBS_SUMMARY)
            assert parent.indent_level is not None and row.indent_level is not None
            assert parent.indent_level == row.indent_level - 1
            assert row.hierarchy_path == (*(parent.hierarchy_path or ()), parent.activity_name)
        if row.row_type is ScheduleRowType.AMBIGUOUS:
            assert (row.indent_level, row.parent_row_ordinal, row.hierarchy_path) == (None,) * 3
        hierarchy_issue = ("hierarchy_ambiguous", gen.HIERARCHY) in truth.rows[ordinal - 1].issues
        determinate = row.row_type is not ScheduleRowType.AMBIGUOUS and not hierarchy_issue
        assert (row.hierarchy_path is not None) == determinate
    assert sum(r.row_type is ScheduleRowType.PROJECT_SUMMARY for r in rows) <= 1
    for row in rows:
        if row.row_type is ScheduleRowType.MILESTONE:
            assert row.original_duration.value == row.remaining_duration.value == Decimal(0)
            assert (row.start.value is None) != (row.finish.value is None)


def test_86_page_truth_reproduces_the_measured_corpus() -> None:
    truth = gen.build("full_multi_page_86_equivalent", "base").truth
    corpus = MEASURED_CORPUS
    counts = truth.counts
    assert counts is not None
    assert counts["pages"] == corpus.pages
    assert counts["rows"] == corpus.table_rows
    assert counts["project_summaries"] + counts["wbs_summaries"] == corpus.summary_rows
    assert counts["project_summaries"] == 1
    assert counts["activities"] + counts["milestones"] == corpus.id_bearing_rows
    assert counts["milestones"] == 64
    assert counts["ambiguous"] == corpus.missing_id_rows
    assert counts["watermark_objects_excluded"] == corpus.pages
    assert counts["chart_objects_excluded"] > corpus.table_rows
    assert truth.outcome == corpus.expected_outcome.value
    per_page = Counter(row.page for row in truth.rows)
    assert [per_page[p] for p in range(1, 87)] == [40] * 54 + [39] * 32
    missing = [r for r in truth.rows if r.row_type == gen.AMBIGUOUS]
    assert [r.page for r in missing] == [corpus.missing_id_page]
    assert truth.document_issues == (
        ("header_od_occluded", corpus.od_header_occluded_page, "original_duration"),
    )
    invalid = [
        (row.page, row.row_type, fld)
        for row in truth.rows
        for code, fld in row.issues
        if code == "invalid_duration"
    ]
    assert invalid == [
        (corpus.duration_date_pages[0], gen.WBS_SUMMARY, "remaining_duration"),
        (corpus.duration_date_pages[1], gen.ACTIVITY, "remaining_duration"),
        (corpus.duration_date_pages[2], gen.ACTIVITY, "original_duration"),
    ]
    assert truth.issue_counts == {
        "activity_like_row_missing_id": 1,
        "header_od_occluded": 1,
        "invalid_duration": 3,
    }
    levels = {row.indent_level for row in truth.rows if row.indent_level is not None}
    assert levels == set(range(8))
    left_edges = {
        row.cells[0].boxes[0][0]
        for row in truth.rows
        if row.row_type in (gen.ACTIVITY, gen.MILESTONE) and row.indent_level == 4
    }
    assert left_edges == {67_700, 68_300}


def test_issue_counts_match_the_contract_family_table() -> None:
    expected = {
        ("full_duplicate_activity_id", "base"): {"duplicate_activity_id": 2},
        ("full_duration_date_in_rd", "base"): {"invalid_duration": 2},
        ("full_duration_date_in_od", "base"): {"invalid_duration": 1},
        ("full_invalid_date", "base"): {"invalid_date": 2},
        ("full_header_occluded_od", "replaced"): {"header_od_occluded": 1},
        ("full_header_occluded_od", "overlay"): {"header_od_occluded": 1},
        ("full_duplicate_text_object", "base"): {
            "duplicate_text_object_collapsed": 1,
            "overlapping_cell_text": 1,
        },
    }
    for key, counts in expected.items():
        assert gen.build(*key).truth.issue_counts == counts, key
    base = gen.build("full_duplicate_text_object", "base").truth.counts
    assert base is not None
    assert (base["duplicate_objects_collapsed"], base["suppressed_objects"]) == (2, 3)
    double = gen.build("full_draft_watermark", "double_draw").truth.counts
    assert double is not None
    assert (double["watermark_objects_excluded"], double["suppressed_objects"]) == (2, 1)
    assert double["duplicate_objects_collapsed"] == 0
