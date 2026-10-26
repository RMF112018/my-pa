"""Synthetic Full-Schedule fixtures: pins, goldens and independent ground truth.

FAST. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 8, 9 and 10.2-10.4. This module pins every generated PDF by SHA-256
and size, proves the generator is deterministic, and checks that each case's
ground truth (written by the generator from its own layout plan, never from
parser output) is internally consistent and representable as domain records.

It then parses every case and holds the parser to two independent standards:
the pinned golden bytes (`GOLDEN_FILE_SHA256`; goldens are regenerated only by
`python -m tests.fixtures.schedule_full_pdf write-goldens` and a regenerated
file fails here until the digest table is edited in the same diff) and the
generator's ground truth, field by field, so the goldens never certify
themselves. The R2 section 39 quality gates are computed over every case.
"""

from __future__ import annotations

import functools
import hashlib
import json
import time
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
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowType,
    canonical_json_bytes,
    derive_outcome,
    parse_result_object,
    parse_result_sha256,
    stable_link_candidates,
)
from my_pa.infrastructure.schedule import ScheduleParseLimits, parse_full_schedule
from my_pa.infrastructure.schedule.full_profile import MEASURED_CORPUS, band_of
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
    ("full_duplicate_text_object", "cross_band"): (
        "caab9c5a42b1cc4d69a9c499820b64e9063f8685e109ed3c6fc4acc6c05a4194",
        9065,
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
    assert len(gen.CASES) == len(set(gen.CASES)) == 77
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


# --- parsing every case (contract 9, 10.2, 10.3) -----------------------------------

#: SHA-256 of every golden file's bytes (contract 9). Regenerating a golden
#: changes its digest and fails `test_golden_files_are_pinned_by_digest` until
#: this table is edited in the same diff.
GOLDEN_FILE_SHA256: Final[dict[str, str]] = {
    "full_valid_2p__base.json": (
        "3f2144c8bfa95ab13d95b6d923b3448c07f17b1a63b84e12eb7bd021c4c01a61"
    ),
    "full_valid_2p__subset_prefix.json": (
        "c3e6e56fe70cf52d0d0dc2d25730411522e9cec9277da94bb6d8a96f341da3e9"
    ),
    "full_valid_2p__zone_edges.json": (
        "8ff9a226a3b207d60a53eabf4d8e16aca002b01d05949ffdcf753b265c0c2f81"
    ),
    "full_valid_2p__split_name.json": (
        "b5b1f4a438c397f58d8a04e1c004672efb758e304388eabc091655505c9e3c0c"
    ),
    "full_valid_2p__id_double_space.json": (
        "0170e03b13f447651c3b3066572dd8505599c7a3caf9828704f7fa1228b67a11"
    ),
    "full_merged_summary_label__base.json": (
        "508d2e477b9c0dc07d7c37c16bb27113fc25248eb86e0441fd64ff23994cb304"
    ),
    "full_merged_summary_label__label_only.json": (
        "ddb3534deb2f8dba5dbb99b4fddd8034b5391b684bc3d20e2f103d7ba3f946e9"
    ),
    "full_summary_vertical_offset__base.json": (
        "7d54850feb8062dbd74ada2935a21bae6ebdeeb60b28bcf8905eacde15550d40"
    ),
    "full_summary_vertical_offset__glyph_metrics.json": (
        "965975a9b265af63026b5f11c58cf135805785b988f0adb0e5d0e6ffeffb778b"
    ),
    "full_summary_zero_zero__base.json": (
        "522ee2f46f1d339b3e07c8f7f5e3b215b2abeefb6bccc2a9db8a5cd0c10d9512"
    ),
    "full_summary_zero_zero__id_both_dates.json": (
        "e8b2c20a08a9e2e4970d692c5cc36b31257475777e902240a97410423c17dadf"
    ),
    "full_nested_hierarchy__base.json": (
        "cf7b5235d765d069f64021e632ad8e885b8684ad2f6277e5a510d8c9b9d8ad01"
    ),
    "full_header_occluded_od__replaced.json": (
        "1f23086eb05781f9dad82dd5fd98708fda659ee450f368a57e5846400be8e1f0"
    ),
    "full_header_occluded_od__overlay.json": (
        "3943855e3d0ee50aeef21893f66f0fd43402424a78d6457531359f5513448caf"
    ),
    "full_header_mismatch__later_page.json": (
        "530e06dad883380e4612adab9a766148200d8148b677c8469adb7d5d97215311"
    ),
    "full_header_mismatch__first_page.json": (
        "3a4e37db3016a5fe9cccb818595d96a0ca2e83a554b8909e6630051d93ad93a9"
    ),
    "full_missing_activity_id__base.json": (
        "2cd8adf50c110df56c1c9fe809492859861882de9a10c92f328a21e80b7f856e"
    ),
    "full_duplicate_activity_id__base.json": (
        "824e66bca6be5ad02adcc540516dbae972374e83a0f689fdd089c8fdb9ce82c2"
    ),
    "full_duration_date_in_rd__base.json": (
        "b1ff6387aafd234518239da82ba15418df6c9e55adb3a2ed2529baef505543a0"
    ),
    "full_duration_date_in_od__base.json": (
        "1b26f91a1f2c8eb42b59b86aeea81de513a7dd03a2f586dd0a28ba2cb9aefbd9"
    ),
    "full_invalid_date__base.json": (
        "7725d68367f682f65f25491c24753a9a9b7df78e7831b143251144f4ef348c8f"
    ),
    "full_chart_duplicates__base.json": (
        "a7be2d74cf57177a27dd63f29729f72e0ca8d47032f340b8c56e6cbc1528e5d6"
    ),
    "full_draft_watermark__signature.json": (
        "d145415a318d9e6c58879ff2d34b02332ba496686c2fe1a2b1a729b0a91936ea"
    ),
    "full_draft_watermark__off_signature.json": (
        "456759fe260e7363f30039ae6ae9dddc0de0b01362badb0a5b8dd6bd2fb7d96a"
    ),
    "full_draft_watermark__slight_skew.json": (
        "0e5f6b7de4acabde3d030b0aa38890bf67adb79a3ccc2c3e8db8d0a84f775d75"
    ),
    "full_draft_watermark__skew_1deg.json": (
        "161f63d0304b96f2759ef7944f1bb24bfa931fc9ed50888097242b3f34d71fc6"
    ),
    "full_draft_watermark__double_draw.json": (
        "5a92c01bf4ef537faa98ca59211982c6f5c304c4f77dcb0ee131e500b740d0a3"
    ),
    "full_duplicate_text_object__base.json": (
        "cc2730a3644ba0e54184c0f6129a0b672c8b862186bd5cc17f8dd6bee4a79ffe"
    ),
    "full_duplicate_text_object__shift_0_5.json": (
        "62fb8def9bd14dca169e897b7822b217d3d031aa824b28bb62e3ff6689541752"
    ),
    "full_duplicate_text_object__bold_over_regular.json": (
        "fc7ae27bae15fda8ce2b8545a3d24c0427aee87c7ceaa23cc6ce714115f580fe"
    ),
    "full_duplicate_text_object__same_text_2pt.json": (
        "a72f15a4480093fd52409debbb5092f093c0283a021d6f5b518d5368d9224d72"
    ),
    "full_duplicate_text_object__under_watermark.json": (
        "0303b85398f0b86169354a8efa5bc08bb6571bca3c0804f51650de5c49a006bb"
    ),
    "full_duplicate_text_object__cross_band.json": (
        "5045d85d2e741fbe9173f53da9c88ff159a0b5d8b47725303d986681d5db7448"
    ),
    "full_overlapping_cell_text__od.json": (
        "7dda5a2e548e6bcdcde8ee4938d7463d23fd16ea97cfc98eff2dbb6f88698479"
    ),
    "full_overlapping_cell_text__id.json": (
        "d30c12c8db7a16b5a3263da3afb7ccf95e3ebb74e19968bb4b02ad1384b55f52"
    ),
    "full_overlapping_cell_text__id_split.json": (
        "357ed16a4857ff34e0be18ddf41d6dfc815cb665514be73de0dc7ec106018bb1"
    ),
    "full_overlapping_cell_text__unmapped.json": (
        "f5b2d1aea17bd2c9d8fa79497ef3919d6f7d91a7c019d088f30a7cbfa844753d"
    ),
    "full_overlapping_cell_text__zero_char_object.json": (
        "b0710fa29a65b6ba2c8c5b00d00d3dce4de96e28aaba7bef1dfbc0247e24fa00"
    ),
    "full_ambiguous_hierarchy__close_centroids.json": (
        "fb7501511d7bd891223b34bd1fe5b09584da9d1812a320b6ced020433cc07ff0"
    ),
    "full_ambiguous_hierarchy__orphan.json": (
        "d6a8f467f25ffd5e9d6b60e0fafd2745cee01827b2765b7f8f845d74a21e5f69"
    ),
    "full_ambiguous_hierarchy__level_gap.json": (
        "50168d37fc3a8a9369b1df80f4f0b9b714a7d2cddbb3b3bc7527cb05c0086a04"
    ),
    "full_row_wrap_unsupported__regular_name.json": (
        "0aacda940b64606f98abfdd556d490a74e6a8699d3e371bd91914e5345de12ea"
    ),
    "full_row_wrap_unsupported__bold_label.json": (
        "2ce2eed658841d1ab80c1a7a1e72fae3ea6a80d4f167659b64946ab3185b5652"
    ),
    "full_multi_page_86_equivalent__base.json": (
        "99a86c666e50030f08a33bc1c548d79b055cc03673232636d3a94c0d843c7ede"
    ),
    "corrupt_pdf__garbage.json": (
        "c3d846e1a37ec1b3512b341e6e3d2a283663a6a255c0a907f03411a95c2c2155"
    ),
    "corrupt_pdf__not_a_pdf.json": (
        "52eb65180ac56ca5a11b89ca86ef2886c54109ae11d340ae80d7e327e67b1b63"
    ),
    "corrupt_pdf__empty.json": ("3eb3e891e49516b4e262111db89fa810ba111013e49b6bae4234c9f5852631ab"),
    "encrypted_pdf__user_password.json": (
        "4e637dbbf257e9fe6474ca02b2f768aa5520dbe4f56f694c96b2f77712496a81"
    ),
    "encrypted_pdf__empty_user_password.json": (
        "a1b2a0a908b675dc284e67460c44fc5d509630ef72fb9e412a2ddd622f652273"
    ),
    "encrypted_pdf__unknown_filter.json": (
        "17aa15e97b72d64c9f2cee1af33a59591af9a305569c4a619329aff46f2c26f9"
    ),
    "image_only_pdf__base.json": (
        "3f9bda465e3f9d77a644ea8a5e11cd2e0139cf761241d29a39054801d82a60eb"
    ),
    "wrong_page_size__letter.json": (
        "16391ab0cd03c8ef78b17e4c49d98f7a49b17e50c717f7069747af4fd85cf917"
    ),
    "wrong_page_size__rotated.json": (
        "58375380bb6a3b63c759e4f6a75e8fbdeafe7e517d74b3393fa636898d89dec6"
    ),
    "wrong_page_size__rotated_180.json": (
        "e53fd8ab1c75ed8c21eea0fb12283c1cda0598a22d37cd0cdb1e4ad341fdfbf0"
    ),
    "wrong_page_size__offset_origin.json": (
        "46864d222b78575dd161a3a0adf64674c0984cd539fe171449f16d3a1ecaca68"
    ),
    "wrong_page_size__zero_pages.json": (
        "32a01d8a3e80a746f31252c6c9d8550167828c3871e40a6b11134a19c74d028f"
    ),
    "page_metadata_mismatch__data_date.json": (
        "bbfecadbf0c68eb2dc6d28276c1f314552e29bd6a32e3be1434304096ed5c613"
    ),
    "page_metadata_mismatch__run_date.json": (
        "31c90fa25771ef178ce45832e66086899bec1d777c7bf31439d681f941651f92"
    ),
    "page_metadata_mismatch__title.json": (
        "cec183f8304ed8ac7b4e8b87e080f46f17cfbb68f4a606a104fd978bb82ea9c2"
    ),
    "page_metadata_mismatch__page_number.json": (
        "20d4b93ad8088040960fecefeedbe67cdc92b2fa84ebaddab4f6d6f73798fdb8"
    ),
    "page_metadata_mismatch__page_total.json": (
        "98c984ce77778f62b66cd73f74f357cdde78697a2abc656f514eec56188e6682"
    ),
    "expected_data_date_mismatch__mismatch.json": (
        "8c8d3ae37cc7b19e101a977165f0726e8c15ede96e101011f2f0d05fa012021c"
    ),
    "expected_data_date_mismatch__match.json": (
        "fb1b9b58a2615d285fda7e2db32beb3e62e1e64fb7697707a6a45e532371617c"
    ),
    "bounds_exceeded__bytes.json": (
        "78c47d4d4dde4fd355f4262e0fb1ce19e302674534e14f78cf4c46f0e5f21b22"
    ),
    "bounds_exceeded__pages.json": (
        "87862566a0c30aa66d36f54430b6620dec40c54b897527032c1a3077222ca8e8"
    ),
    "bounds_exceeded__text_objects.json": (
        "c8a9512a1337e0afc5721e130eb660a1770ad9cb99be02c308cf45ae0324ca4d"
    ),
    "bounds_exceeded__page_objects.json": (
        "992d9f782d497f49057c23a5891c14d5cdc431149524d035a29ffc35a27fcefc"
    ),
    "bounds_exceeded__chars.json": (
        "b93c9709ebc2ab7d9e610ee48376ba147b9dcbd685a018a54efbe4bf37569911"
    ),
    "bounds_exceeded__rows.json": (
        "c400e481cf082f62b387a30cb4da75ae550886e2942f85e656c3a7d5b390151f"
    ),
    "bounds_exceeded__issues.json": (
        "f1791206dc75508a0639860e0dddc9e04db80db54595682e247840d16db9f8af"
    ),
    "bounds_exceeded__row_warnings.json": (
        "385f4abd09054b5c193bacd5ace66063937537d64afee87fff4a97be397b8e9f"
    ),
    "bounds_exceeded__hierarchy_depth.json": (
        "cf74b893b5ebf610f86d2df0e8f3bdb366ef4a61761932698c0604a573ecc9ff"
    ),
    "bounds_exceeded__cell_evidence.json": (
        "7ff60e5fc446be15d970d232d4fbaa392dfe0c2d403672422e052e53d4efce51"
    ),
    "bounds_exceeded__form_text.json": (
        "ed7062302367f03073b4a3911a94765a2c6c87fc5944b94db4f8f8517ac541cd"
    ),
    "bounds_exceeded__form_depth.json": (
        "6cbbb41574865929b822c3bb58beaf54fbff6ea9f9fea7777be57b3a6c4699f5"
    ),
    "bounds_exceeded__time_first.json": (
        "07169fb7cfb2ed9016f1d87ef32b275c511b21a4839ec910d21f39cdc9861a86"
    ),
    "bounds_exceeded__time_mid.json": (
        "ce9a90a6238770e170b89d1185692ae763389465089ff595b501d4b55c5122d8"
    ),
}


@functools.cache
def _parse(family: str, variant: str) -> ScheduleParseResult:
    case = gen.build(family, variant)
    limits = ScheduleParseLimits(**case.limits) if case.limits else ScheduleParseLimits()
    return parse_full_schedule(
        case.pdf,
        expected_data_date=case.expected_data_date,
        limits=limits,
        clock=gen.fake_clock(case.clock_calls_before_expiry),
        deadline=None if case.clock_calls_before_expiry is None else 1.0,
    )


def _golden(family: str, variant: str) -> dict[str, object]:
    data = gen.golden_path(family, variant).read_bytes()
    loaded = json.loads(data)
    assert isinstance(loaded, dict)
    return loaded


def test_golden_directory_holds_exactly_the_registered_cases() -> None:
    names = {path.name for path in gen.GOLDEN_DIRECTORY.iterdir()}
    assert names == {f"{family}__{variant}.json" for family, variant in gen.CASES}
    assert set(GOLDEN_FILE_SHA256) == names


def test_golden_files_are_pinned_by_digest() -> None:
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(gen.GOLDEN_DIRECTORY.iterdir())
    }
    assert actual == GOLDEN_FILE_SHA256


@pytest.mark.parametrize(("family", "variant"), gen.CASES, ids=lambda v: str(v))
def test_every_case_matches_its_golden(family: str, variant: str) -> None:
    case = gen.build(family, variant)
    result = _parse(family, variant)
    golden = _golden(family, variant)
    assert (golden["family"], golden["variant"]) == (family, variant)
    assert golden["generator_version"] == gen.GENERATOR_VERSION
    assert golden["parse_inputs"] == {
        "expected_data_date": (
            None if case.expected_data_date is None else case.expected_data_date.isoformat()
        ),
        "limits": "production" if case.limits is None else dict(case.limits),
    }
    assert (golden["pdf_sha256"], golden["pdf_size_bytes"]) == (case.sha256, len(case.pdf))
    assert result.document_sha256 == case.sha256
    assert golden["result_sha256"] == parse_result_sha256(result)
    issue_counts = Counter(issue.code.value for issue in result.issues)
    assert golden["summary"] == {
        "outcome": result.outcome.value,
        "counts": parse_result_object(result)["counts"],
        "issue_counts": dict(sorted(issue_counts.items())),
    }
    assert golden["linkage"] == {
        "basis": gen.linkage_basis(result.outcome.value),
        "rows": [
            {"row_ordinal": row.row_ordinal, "published_activity_id": row.published_activity_id}
            for row in stable_link_candidates(result)
        ],
    }
    if (family, variant) in gen.RESULTLESS_CASES:
        assert golden["result"] is None
    else:
        assert canonical_json_bytes(parse_result_object(result)) == canonical_json_bytes(
            golden["result"]
        )
    assert "engine" not in golden


def _cell_boxes(row: ParsedScheduleRow) -> tuple[tuple[tuple[int, int, int, int], ...], ...]:
    return tuple(
        tuple((f.box.x0, f.box.y0, f.box.x1, f.box.y1) for f in cell.fragments)
        for cell in row.cells
    )


@pytest.mark.parametrize(("family", "variant"), gen.CASES, ids=lambda v: str(v))
def test_every_case_matches_its_ground_truth(family: str, variant: str) -> None:
    """Parser output equals the generator's intent for every field truth covers."""
    truth = gen.build(family, variant).truth
    result = _parse(family, variant)
    assert result.outcome.value == truth.outcome
    assert (result.published_schedule_title, result.data_date, result.run_date) == (
        truth.title,
        truth.data_date,
        truth.run_date,
    )
    issues = sorted(
        (
            (i.code.value, i.page_number, i.row_ordinal, None if i.field is None else i.field.value)
            for i in result.issues
        ),
        key=str,
    )
    expected_issues = [(code, page, None, fld) for code, page, fld in truth.document_issues]
    for ordinal, row in enumerate(truth.rows, start=1):
        expected_issues += [(code, row.page, ordinal, fld) for code, fld in row.issues]
    assert issues == sorted(expected_issues, key=str)
    if truth.counts is not None:
        assert {name: getattr(result.counts, name) for name in truth.counts} == dict(truth.counts)
    assert len(result.rows) == len(truth.rows)
    for row, want in zip(result.rows, truth.rows, strict=True):
        where = (family, variant, row.row_ordinal)
        assert (row.page_number, row.physical_line_ordinal) == (want.page, want.line), where
        assert row.row_type.value == want.row_type, where
        assert (row.indent_level, row.parent_row_ordinal, row.hierarchy_path) == (
            want.indent_level,
            want.parent,
            want.hierarchy_path,
        ), where
        assert (row.published_activity_id, row.activity_name) == (want.activity_id, want.name)
        assert _duration(*want.original_duration) == row.original_duration, where
        assert _duration(*want.remaining_duration) == row.remaining_duration, where
        assert _date(*want.start) == row.start, where
        assert _date(*want.finish) == row.finish, where
        assert (row.box.x0, row.box.y0, row.box.x1, row.box.y1) == want.box, where
        assert [c.value for c in row.warning_codes] == list(want.warning_codes), where
        assert [(c.field.value, c.state.value, c.text) for c in row.cells] == [
            (c.field, c.state, c.text) for c in want.cells
        ], where
        assert _cell_boxes(row) == tuple(c.boxes for c in want.cells), where


def _truth_link_ids(truth: gen.Truth) -> list[tuple[int, str | None]]:
    return [
        (ordinal, row.activity_id)
        for ordinal, row in enumerate(truth.rows, start=1)
        if row.row_type in (gen.ACTIVITY, gen.MILESTONE)
    ]


def _quality_gates() -> dict[str, list[str]]:
    """R2 section 39 gates over every case: the list of violations per gate."""
    gates: dict[str, list[str]] = {
        name: []
        for name in (
            "id_precision",
            "id_recall",
            "id_exact",
            "stable_false_merge",
            "spurious_link",
            "dropped_id_rows",
            "summary_promotion",
            "name_exact",
            "date_accuracy",
            "duration_accuracy",
            "coerced_invalid",
            "row_type_accuracy",
            "hierarchy_accuracy",
            "hierarchy_ambiguity_explicit",
            "chart_admitted",
            "watermark_admitted",
            "wrap_concatenated",
            "bad_identity_linked",
            "provenance_match",
            "review_required_links",
        )
    }
    summaries = (gen.PROJECT_SUMMARY, gen.WBS_SUMMARY)
    for family, variant in gen.CASES:
        case = gen.build(family, variant)
        truth = case.truth
        result = _parse(family, variant)
        name = case.name
        if result.document_sha256 != case.sha256:
            gates["provenance_match"].append(f"{name} document digest")
        parsed_ids = {
            (row.page_number, row.physical_line_ordinal): row.published_activity_id
            for row in result.rows
            if row.published_activity_id is not None
        }
        true_ids = {
            (row.page, row.line): row.activity_id
            for row in truth.rows
            if row.row_type in (gen.ACTIVITY, gen.MILESTONE)
        }
        for key, value in parsed_ids.items():
            if true_ids.get(key) != value:
                gates["id_precision"].append(f"{name} {key}")
        for key, value in true_ids.items():
            if key not in parsed_ids:
                gates["id_recall"].append(f"{name} {key}")
                gates["dropped_id_rows"].append(f"{name} {key}")
            elif parsed_ids[key] != value:
                gates["id_exact"].append(f"{name} {key}")
        links = stable_link_candidates(result)
        link_ids = [row.published_activity_id for row in links]
        if len(link_ids) != len(set(link_ids)):
            gates["stable_false_merge"].append(name)
        eligible = truth.outcome in (gen.COMPLETE, gen.PARTIAL)
        expected_links = _truth_link_ids(truth) if eligible else []
        if [(row.row_ordinal, row.published_activity_id) for row in links] != expected_links:
            gates["spurious_link"].append(name)
        duplicated = {i for i, n in Counter(true_ids.values()).items() if n > 1}
        missing_rows = {
            ordinal
            for ordinal, row in enumerate(truth.rows, start=1)
            if ("activity_like_row_missing_id", gen.ACTIVITY_ID) in row.issues
        }
        if any(
            row.published_activity_id in duplicated or row.row_ordinal in missing_rows
            for row in links
        ):
            gates["bad_identity_linked"].append(name)
        if result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED and links:
            gates["review_required_links"].append(name)
        for row, want in zip(result.rows, truth.rows, strict=False):
            where = f"{name} row {row.row_ordinal}"
            if want.row_type in summaries and row.row_type in (
                ScheduleRowType.ACTIVITY,
                ScheduleRowType.MILESTONE,
            ):
                gates["summary_promotion"].append(where)
            if row.activity_name != want.name:
                gates["name_exact"].append(where)
            if (row.start, row.finish) != (_date(*want.start), _date(*want.finish)):
                gates["date_accuracy"].append(where)
            durations = (_duration(*want.original_duration), _duration(*want.remaining_duration))
            if (row.original_duration, row.remaining_duration) != durations:
                gates["duration_accuracy"].append(where)
            for cell, true_cell in zip(
                (row.original_duration, row.remaining_duration, row.start, row.finish),
                (want.original_duration, want.remaining_duration, want.start, want.finish),
                strict=True,
            ):
                if true_cell[0] != gen.PUBLISHED_VALUE and cell.value is not None:
                    gates["coerced_invalid"].append(where)
            if row.row_type.value != want.row_type:
                gates["row_type_accuracy"].append(where)
            hierarchy = (row.indent_level, row.parent_row_ordinal, row.hierarchy_path)
            if hierarchy != (want.indent_level, want.parent, want.hierarchy_path):
                gates["hierarchy_accuracy"].append(where)
            flagged = ScheduleIssueCode.HIERARCHY_AMBIGUOUS in row.warning_codes
            if ("hierarchy_ambiguous", gen.HIERARCHY) in want.issues and (
                not flagged or row.hierarchy_path is not None
            ):
                gates["hierarchy_ambiguity_explicit"].append(where)
            for cell in row.cells:
                for fragment in cell.fragments:
                    if band_of(fragment.box) is None:
                        gates["chart_admitted"].append(where)
                    if fragment.raw == "DRAFT" and fragment.box.y1 - fragment.box.y0 > 20_000:
                        gates["watermark_admitted"].append(where)
            if ("row_wrap_unsupported", None) in want.issues:
                previous = result.rows[row.row_ordinal - 2]
                expected_previous = truth.rows[row.row_ordinal - 2].name
                if row.activity_name is not None or previous.activity_name != expected_previous:
                    gates["wrap_concatenated"].append(where)
            if (row.page_number, row.physical_line_ordinal) != (want.page, want.line) or (
                (row.box.x0, row.box.y0, row.box.x1, row.box.y1) != want.box
                or _cell_boxes(row) != tuple(c.boxes for c in want.cells)
            ):
                gates["provenance_match"].append(where)
        if truth.counts is not None:
            if result.counts.chart_objects_excluded != truth.counts["chart_objects_excluded"]:
                gates["chart_admitted"].append(f"{name} chart count")
            excluded = truth.counts["watermark_objects_excluded"]
            if result.counts.watermark_objects_excluded != excluded:
                gates["watermark_admitted"].append(f"{name} watermark count")
    return gates


def test_quality_gates_hold_over_every_case() -> None:
    gates = _quality_gates()
    assert not gates["id_precision"], gates["id_precision"]
    assert not gates["id_recall"], gates["id_recall"]
    assert not gates["id_exact"], gates["id_exact"]
    assert not gates["stable_false_merge"], gates["stable_false_merge"]
    assert not gates["spurious_link"], gates["spurious_link"]
    assert not gates["dropped_id_rows"], gates["dropped_id_rows"]
    assert not gates["summary_promotion"], gates["summary_promotion"]
    assert not gates["name_exact"], gates["name_exact"]
    assert not gates["date_accuracy"], gates["date_accuracy"]
    assert not gates["duration_accuracy"], gates["duration_accuracy"]
    assert not gates["coerced_invalid"], gates["coerced_invalid"]
    assert not gates["row_type_accuracy"], gates["row_type_accuracy"]
    assert not gates["hierarchy_accuracy"], gates["hierarchy_accuracy"]
    assert not gates["hierarchy_ambiguity_explicit"], gates["hierarchy_ambiguity_explicit"]
    assert not gates["chart_admitted"], gates["chart_admitted"]
    assert not gates["watermark_admitted"], gates["watermark_admitted"]
    assert not gates["wrap_concatenated"], gates["wrap_concatenated"]
    assert not gates["bad_identity_linked"], gates["bad_identity_linked"]
    assert not gates["provenance_match"], gates["provenance_match"]
    assert not gates["review_required_links"], gates["review_required_links"]


# --- R2 section 38 assertions (contract 10.2) ---------------------------------------


def test_linkage_is_eligible_only_for_complete_or_partial() -> None:
    for family, variant in gen.CASES:
        result = _parse(family, variant)
        links = stable_link_candidates(result)
        if result.outcome in (
            SchedulePublicationStatus.COMPLETE,
            SchedulePublicationStatus.PARTIAL,
        ):
            assert [r.row_type for r in links] == [
                r.row_type
                for r in result.rows
                if r.row_type in (ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE)
            ]
        else:
            assert links == (), (family, variant)
    assert stable_link_candidates(_parse("full_valid_2p", "base"))
    assert stable_link_candidates(_parse("full_invalid_date", "base"))  # partial
    assert not stable_link_candidates(_parse("full_missing_activity_id", "base"))


def test_merged_summary_label_is_never_an_activity_id() -> None:
    result = _parse("full_merged_summary_label", "base")
    first, second = result.rows[:2]
    assert first.row_type is ScheduleRowType.PROJECT_SUMMARY
    assert second.row_type is ScheduleRowType.WBS_SUMMARY
    for row, label in (
        (first, "Synthetic Project merged label"),
        (second, "Synthetic Phase A merged summary label"),
    ):
        assert (row.published_activity_id, row.activity_name) == (None, label)
        assert row.cells[0].state is ScheduleCellState.PUBLISHED_BLANK
        assert row.cells[0].fragments == ()
        assert [f.raw for f in row.cells[1].fragments] == [label]
    # The label's box crosses the 131.0 boundary and is still one fragment.
    assert first.cells[1].fragments[0].box.x0 < 131_000 < first.cells[1].fragments[0].box.x1
    ids = [r.published_activity_id for r in stable_link_candidates(result)]
    assert ids == ["SYN-1000", "SYN-1001", "SYN-1002"]


def test_vertical_offset_summary_is_one_row() -> None:
    for variant in ("base", "glyph_metrics"):
        result = _parse("full_summary_vertical_offset", variant)
        project = result.rows[0]
        assert project.row_type is ScheduleRowType.PROJECT_SUMMARY
        assert project.activity_name == "Synthetic Project"
        assert str(project.original_duration.value) == "120.000"
        assert project.finish.value == date(2026, 10, 30)
        assert result.counts.rows == 7
        assert result.outcome is SchedulePublicationStatus.COMPLETE


def test_occluded_od_header_parses_and_only_warns() -> None:
    for variant in ("replaced", "overlay"):
        result = _parse("full_header_occluded_od", variant)
        assert result.outcome is SchedulePublicationStatus.COMPLETE
        assert [(i.code, i.page_number, i.field) for i in result.issues] == [
            (ScheduleIssueCode.HEADER_OD_OCCLUDED, 2, ScheduleFieldCode.ORIGINAL_DURATION)
        ]
        assert result.counts.warnings == 1
        page2 = [r for r in result.rows if r.page_number == 2]
        assert [r.original_duration.value for r in page2] == [Decimal("10.000")] * 2


def test_missing_id_row_invents_nothing_and_links_nothing() -> None:
    result = _parse("full_missing_activity_id", "base")
    (row,) = [r for r in result.rows if r.row_type is ScheduleRowType.AMBIGUOUS]
    assert (row.published_activity_id, row.activity_name) == (None, None)
    assert row.cells[0].fragments == () and row.cells[1].fragments == ()
    assert row.warning_codes == (ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID,)
    # Chart text never completes the identity.
    assert all("unidentified" not in (f.raw or "") for c in row.cells for f in c.fragments)
    assert result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED
    assert stable_link_candidates(result) == ()
    assert str(row.original_duration.value) == "6.000"  # evidence is still typed


def test_duration_date_tokens_stay_in_their_cells() -> None:
    rd = _parse("full_duration_date_in_rd", "base")
    for row in rd.rows[1:3]:
        assert row.remaining_duration.state is ScheduleCellState.EXTRACTION_FAILED
        assert row.cells[3].text == "15-Mar-28"
        assert row.start.value == date(2026, 5, 4)  # never shifted into Start
    assert rd.rows[1].row_type is ScheduleRowType.WBS_SUMMARY
    assert rd.rows[2].row_type is ScheduleRowType.ACTIVITY
    od = _parse("full_duration_date_in_od", "base")
    row = od.rows[2]
    assert row.original_duration.state is ScheduleCellState.EXTRACTION_FAILED
    assert row.cells[2].text == "15-Mar-28"
    assert (row.start.value, row.finish.value) == (date(2026, 5, 4), date(2026, 5, 15))
    assert {i.code for i in (*rd.issues, *od.issues)} == {ScheduleIssueCode.INVALID_DURATION}


def _fragments(result: ScheduleParseResult) -> list[ScheduleCellFragment]:
    return [f for row in result.rows for cell in row.cells for f in cell.fragments]


def test_chart_duplicates_contribute_zero_fragments() -> None:
    result = _parse("full_chart_duplicates", "base")
    assert result.outcome is SchedulePublicationStatus.COMPLETE
    assert result.counts.chart_objects_excluded == 18
    assert all(f.box.x0 + f.box.x1 < 2 * 615_500 for f in _fragments(result))
    names = [r.activity_name for r in result.rows]
    assert names == [r.name for r in gen.build("full_chart_duplicates", "base").truth.rows]


def test_watermark_contributes_zero_fragments() -> None:
    for variant, excluded in (("signature", 1), ("slight_skew", 1), ("double_draw", 2)):
        result = _parse("full_draft_watermark", variant)
        assert result.outcome is SchedulePublicationStatus.COMPLETE
        assert result.counts.watermark_objects_excluded == excluded
        drafts = [f for f in _fragments(result) if f.raw == "DRAFT"]
        # Only the ordinary activity named DRAFT survives, as its name cell.
        assert len(drafts) == 1 and drafts[0].font_size_mpt == 7_000
        (row,) = [r for r in result.rows if r.activity_name == "DRAFT"]
        assert row.published_activity_id == "SYN-1003"
    double = _parse("full_draft_watermark", "double_draw")
    assert (double.counts.suppressed_objects, double.counts.duplicate_objects_collapsed) == (1, 0)
    assert not any(
        i.code is ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED for i in double.issues
    )
    for variant in ("off_signature", "skew_1deg"):
        failed = _parse("full_draft_watermark", variant)
        assert [(i.code, i.page_number) for i in failed.issues] == [
            (ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1)
        ]


def test_exact_duplicate_collapses_and_overlap_is_ambiguous() -> None:
    for variant in ("base", "under_watermark"):
        result = _parse("full_duplicate_text_object", variant)
        assert (result.counts.duplicate_objects_collapsed, result.counts.suppressed_objects) == (
            2,
            3,
        )
        (collapsed,) = [
            i for i in result.issues if i.code is ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED
        ]
        row = result.rows[collapsed.row_ordinal - 1]  # type: ignore[operator]
        assert collapsed.field is ScheduleFieldCode.ACTIVITY_NAME
        assert len(row.cells[1].fragments) == 1
        assert row.row_type is ScheduleRowType.ACTIVITY
        od_row = result.rows[collapsed.row_ordinal]  # type: ignore[index]
        assert od_row.cells[2].state is ScheduleCellState.AMBIGUOUS
        assert od_row.cells[2].text == "5 5"
        assert od_row.original_duration.value is None  # never first- or last-write-wins
    assert (
        _parse("full_duplicate_text_object", "under_watermark").counts.watermark_objects_excluded
        == 1
    )
    for variant, outcome in (
        ("shift_0_5", SchedulePublicationStatus.REVIEW_REQUIRED),
        ("bold_over_regular", SchedulePublicationStatus.REVIEW_REQUIRED),
        ("same_text_2pt", SchedulePublicationStatus.PARTIAL),
    ):
        assert _parse("full_duplicate_text_object", variant).outcome is outcome
    # Contract 5.4 step 3 (FR5-F01): a suppressed copy carried into another
    # band never joins that cell's text silently.
    cross = _parse("full_duplicate_text_object", "cross_band")
    assert cross.outcome is SchedulePublicationStatus.REVIEW_REQUIRED
    (row,) = [r for r in cross.rows if r.cells[0].text == "SYN-1090"]
    assert row.row_type is ScheduleRowType.AMBIGUOUS
    assert row.cells[1].state is ScheduleCellState.AMBIGUOUS
    assert [f.raw for f in row.cells[1].fragments] == ["SYN-1090", "Synthetic activity 090"]
    assert [(i.code, i.field) for i in cross.issues if i.row_ordinal == row.row_ordinal] == [
        (ScheduleIssueCode.AMBIGUOUS_CELL, ScheduleFieldCode.ACTIVITY_NAME)
    ]
    assert cross.counts.suppressed_objects == 1
    assert "SYN-1090" not in [r.published_activity_id for r in stable_link_candidates(cross)]
    od = _parse("full_overlapping_cell_text", "od")
    cell = od.rows[3].cells[2]
    assert (cell.state, cell.text) == (ScheduleCellState.AMBIGUOUS, "5 8")
    assert od.rows[3].original_duration.value is None


# --- the 86-page equivalent (R2-AC-037) -----------------------------------------------


def test_86_page_equivalent_reproduces_the_measured_corpus() -> None:
    result = _parse("full_multi_page_86_equivalent", "base")
    corpus = MEASURED_CORPUS
    counts = result.counts
    assert counts.pages == corpus.pages
    assert counts.rows == corpus.table_rows
    assert counts.project_summaries + counts.wbs_summaries == corpus.summary_rows
    assert counts.activities + counts.milestones == corpus.id_bearing_rows
    assert counts.ambiguous == corpus.missing_id_rows
    assert counts.watermark_objects_excluded == corpus.pages
    assert result.outcome is corpus.expected_outcome
    assert {r.page_number for r in result.rows} == set(range(1, 87))
    issues = [(i.code, i.page_number) for i in result.issues]
    assert issues == [
        (ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID, corpus.missing_id_page),
        (ScheduleIssueCode.HEADER_OD_OCCLUDED, corpus.od_header_occluded_page),
        (ScheduleIssueCode.INVALID_DURATION, corpus.duration_date_pages[0]),
        (ScheduleIssueCode.INVALID_DURATION, corpus.duration_date_pages[1]),
        (ScheduleIssueCode.INVALID_DURATION, corpus.duration_date_pages[2]),
    ]
    levels = Counter(r.indent_level for r in result.rows)
    assert set(levels) == {*range(8), None}
    assert stable_link_candidates(result) == ()


def test_86_page_equivalent_parse_time_is_reported() -> None:
    """Reports the parser-only time; asserts only the R2 30 s ceiling (U-09)."""
    pdf = gen.build("full_multi_page_86_equivalent", "base").pdf
    started = time.perf_counter()
    result = parse_full_schedule(pdf)
    elapsed = time.perf_counter() - started
    print(f"86-page-equivalent parse: {elapsed:.2f} s for {result.counts.rows} rows")
    assert result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED
    assert elapsed < 30.0
