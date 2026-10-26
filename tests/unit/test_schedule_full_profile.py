"""The frozen `p6_full_v1` profile, its limits and the pure parser stages.

FAST: no PDF. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
section 4 pins every constant here; a value change must bump `PARSER_VERSION`
and edit this file in the same diff. The pure parser stages of contract
section 5 are tested here over hand-built `PdfTextObject` lists whose boxes are
the uniform Type3 metrics of contract 8.2 (`[x, y - 0.2s, x + 0.5ns, y + 0.7s]`).
Grid values below are written as literals on purpose: a profile constant that
moves must fail here, not move the expectation with it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

import pytest

from my_pa.domain.schedule import (
    ScheduleBox,
    ScheduleCellState,
    ScheduleFieldCode,
    ScheduleIssueCode,
    SchedulePublicationStatus,
    ScheduleRowType,
    derive_outcome,
)
from my_pa.infrastructure.schedule import (
    P6_FULL_V1,
    PRODUCTION_LIMITS,
    ScheduleParseLimits,
    parse_full_schedule,
)
from my_pa.infrastructure.schedule.full_profile import (
    DOCUMENT_TYPE,
    MEASURED_CORPUS,
    PARSER_NAME,
    PARSER_VERSION,
    PROCESSING_BUDGET_SECONDS,
    PROFILE_ID,
    PROFILE_VERSION,
    ClassifiedRow,
    HierarchyAssignment,
    MeasuredCorpus,
    PageZones,
    PdfPhysicalRow,
    ProfileTextObject,
    assign_full_cells,
    band_of,
    classify_full_row,
    exclude_profile_non_data,
    group_table_rows_by_overlap,
    matches_watermark,
    reconstruct_full_hierarchy,
    validate_full_profile,
)
from my_pa.infrastructure.schedule.pdf import PdfPageText, PdfTextObject, ScheduleParseRefusal
from tests.fixtures import schedule_full_pdf as gen


def test_profile_constants_are_frozen() -> None:
    profile = P6_FULL_V1
    assert (PROFILE_ID, PROFILE_VERSION, DOCUMENT_TYPE) == ("p6_full_v1", 1, "full")
    assert (PARSER_NAME, PARSER_VERSION) == ("cpm-workbench-full-parser", "1")
    assert (profile.profile_id, profile.profile_version, profile.document_type) == (
        "p6_full_v1",
        1,
        "full",
    )
    assert (profile.parser_name, profile.parser_version) == ("cpm-workbench-full-parser", "1")
    # 4.2 page geometry
    assert (profile.page_width_mpt, profile.page_height_mpt) == (1_224_000, 792_000)
    assert profile.page_size_tolerance_mpt == 500
    assert profile.page_origin_tolerance_mpt == 500
    # 4.3 x grid (R2 section 12.4, exact)
    assert profile.grid_mpt == (37_000, 131_000, 435_500, 467_500, 498_500, 559_000, 615_500)
    # 4.4 y zones
    assert (profile.data_zone_bottom_mpt, profile.data_zone_top_mpt) == (95_000, 700_000)
    assert profile.header_band_top_mpt == 724_000
    # 4.5 anchors and grammars
    assert profile.column_anchor_texts == (
        "Activity ID",
        "Activity Name",
        "OD",
        "RD",
        "Start",
        "Finish",
    )
    assert profile.layout_pattern.pattern == r"^Layout: (?P<value>\S.{0,198})$"
    assert profile.data_date_pattern.pattern == r"^Data Date: (?P<date>\S+)$"
    assert profile.run_date_pattern.pattern == r"^Run Date: (?P<date>\S+)$"
    assert profile.page_signature_pattern.pattern == (
        r"^Summary Page (?P<n>[1-9][0-9]{0,2}) of (?P<m>[1-9][0-9]{0,2})$"
    )
    assert profile.title_max_chars == 300
    # 4.6 watermark
    assert profile.watermark_text == "DRAFT"
    assert profile.watermark_box_mpt == (309_000, 244_000, 872_000, 503_000)
    assert profile.watermark_edge_tolerance_mpt == 12_000
    assert profile.watermark_tan_min == Decimal("0.087489")
    assert profile.watermark_tan_max == Decimal("11.430052")
    assert profile.near_horizontal_tan == Decimal("0.01")
    # 4.9 grouping, cells, hierarchy
    assert profile.row_overlap_ratio == Fraction(1, 2)
    assert profile.row_max_span_mpt == 16_000
    assert profile.wrap_pitch_mpt == 10_000
    assert profile.duplicate_edge_tolerance_mpt == 250
    assert profile.cell_overlap_mpt == 250
    assert profile.indent_tolerance_mpt == 1_500
    assert profile.indent_min_separation_mpt == 3_000
    assert (profile.regular_font, profile.bold_font) == ("Arial", "Arial,Bold")
    assert profile.subset_prefix.pattern == r"^[A-Z]{6}\+"
    assert PROCESSING_BUDGET_SECONDS == 240
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.page_width_mpt = 0  # type: ignore[misc]


def test_profile_grammars_match_the_synthetic_frame() -> None:
    profile = P6_FULL_V1
    assert profile.layout_pattern.fullmatch("Layout: SYN Full")
    assert not profile.layout_pattern.fullmatch("Layout:  SYN Full")
    assert profile.data_date_pattern.fullmatch("Data Date: 04-May-26")
    assert profile.run_date_pattern.fullmatch("Run Date: 11-May-26")
    signature = profile.page_signature_pattern.fullmatch("Summary Page 2 of 86")
    assert signature is not None
    assert (signature["n"], signature["m"]) == ("2", "86")
    assert not profile.page_signature_pattern.fullmatch("Summary Page 0 of 86")
    assert profile.subset_prefix.sub("", "SYNABC+Arial,Bold", count=1) == "Arial,Bold"
    assert profile.subset_prefix.sub("", "SYNAB+Arial", count=1) == "SYNAB+Arial"


def test_watermark_tangents_are_the_decimal_bounds_of_5_and_85_degrees() -> None:
    # tan 5 deg = 0.0874886635..., tan 85 deg = 11.4300523028...: 6 places,
    # correctly rounded; no float trigonometry anywhere in the profile.
    assert P6_FULL_V1.watermark_tan_min == Decimal("0.0874886635").quantize(Decimal("0.000001"))
    assert P6_FULL_V1.watermark_tan_max == Decimal("11.4300523028").quantize(Decimal("0.000001"))
    for value in (
        P6_FULL_V1.watermark_tan_min,
        P6_FULL_V1.watermark_tan_max,
        P6_FULL_V1.near_horizontal_tan,
    ):
        assert isinstance(value, Decimal)


def test_production_limits_are_the_r2_bounds() -> None:
    assert dataclasses.asdict(PRODUCTION_LIMITS) == {
        "max_bytes": 16_777_216,
        "max_pages": 250,
        "max_text_objects": 250_000,
        "max_page_objects": 1_000_000,
        "max_text_chars": 2_000_000,
        "max_rows": 25_000,
        "max_issues": 50_000,
        "max_row_warnings": 16,
        "max_hierarchy_depth": 32,
        "max_cell_evidence_bytes": 16_384,
        "max_form_depth": 4,
    }
    assert ScheduleParseLimits() == PRODUCTION_LIMITS


@pytest.mark.parametrize("name", [f.name for f in dataclasses.fields(ScheduleParseLimits)])
def test_limits_can_only_be_tightened(name: str) -> None:
    production = getattr(PRODUCTION_LIMITS, name)
    tightened = ScheduleParseLimits(**{name: production - 1})
    assert getattr(tightened, name) == production - 1
    with pytest.raises(ValueError, match="only tighten"):
        ScheduleParseLimits(**{name: production + 1})
    with pytest.raises(ValueError, match="non-negative integers"):
        ScheduleParseLimits(**{name: -1})
    with pytest.raises(ValueError, match="non-negative integers"):
        ScheduleParseLimits(**{name: True})


def test_measured_corpus_is_counts_and_ordinals_only() -> None:
    corpus = MEASURED_CORPUS
    assert (corpus.pages, corpus.table_rows, corpus.summary_rows) == (86, 3408, 443)
    assert (corpus.id_bearing_rows, corpus.missing_id_rows) == (2964, 1)
    assert corpus.summary_rows + corpus.id_bearing_rows + corpus.missing_id_rows == 3408
    assert (corpus.page_width_pt, corpus.page_height_pt) == (1224, 792)
    assert (corpus.missing_id_page, corpus.od_header_occluded_page) == (21, 37)
    assert corpus.duration_date_pages == (55, 58, 61)
    assert corpus.expected_outcome is SchedulePublicationStatus.REVIEW_REQUIRED
    assert corpus.indent_centroids_pt == tuple(
        Decimal(v) for v in ("52.57", "56.78", "60.30", "63.88", "67.70", "71.53", "75.35", "79.08")
    )
    gaps = [
        b - a
        for a, b in zip(corpus.indent_centroids_pt, corpus.indent_centroids_pt[1:], strict=False)
    ]
    assert min(gaps) == Decimal("3.52")
    assert min(gaps) * 1000 > P6_FULL_V1.indent_min_separation_mpt
    with pytest.raises(ValueError, match="partition"):
        dataclasses.replace(corpus, missing_id_rows=2)
    assert isinstance(corpus, MeasuredCorpus)


# --- hand-built objects ---------------------------------------------------------

D = Decimal
IDENTITY = (D(1), D(0), D(0), D(1), D(0), D(0))
_ORDINAL = [0]


def _mpt(points: str | Decimal) -> int:
    return int(D(points) * 1000)


def text_object(
    text: str,
    x: str,
    y: str = "600",
    *,
    size: str = "7",
    font: str = "Arial",
    suppressed: bool = False,
    unmapped: bool = False,
    matrix: tuple[Decimal, ...] = IDENTITY,
    box: tuple[int, int, int, int] | None = None,
    ordinal: int | None = None,
) -> PdfTextObject:
    """A text object with the uniform Type3 box of contract 8.2."""
    if ordinal is None:
        _ORDINAL[0] += 1
        ordinal = _ORDINAL[0]
    s = D(size)
    if box is None:
        box = (
            _mpt(x),
            _mpt(D(y) - s * D("0.2")),
            _mpt(D(x) + s * D("0.5") * len(text)),
            _mpt(D(y) + s * D("0.7")),
        )
    return PdfTextObject(
        page_number=1,
        object_ordinal=ordinal,
        text="" if suppressed else text,
        suppressed=suppressed,
        unmapped=unmapped,
        font_base_name=font,
        font_embedded=True,
        font_size_mpt=_mpt(s),
        box=ScheduleBox(*box),
        matrix=matrix,  # type: ignore[arg-type]
    )


def known(
    obj: PdfTextObject, twin: int | None = None, text: str | None = None
) -> ProfileTextObject:
    return ProfileTextObject(obj, obj.text if text is None else text, twin)


def rows_of(*objects: PdfTextObject | ProfileTextObject) -> tuple[PdfPhysicalRow, ...]:
    items = [o if isinstance(o, ProfileTextObject) else ProfileTextObject.of(o) for o in objects]
    return group_table_rows_by_overlap(items, page_number=1)


def classified(*objects: PdfTextObject | ProfileTextObject) -> list[ClassifiedRow]:
    out: list[ClassifiedRow] = []
    previous: PdfPhysicalRow | None = None
    for row in rows_of(*objects):
        out.append(classify_full_row(assign_full_cells(row), previous, row_ordinal=len(out) + 1))
        previous = row
    return out


def activity(
    activity_id: str,
    y: str = "600",
    *,
    x: str = "60.30",
    name: str = "Synthetic activity",
    od: str | None = "10",
    rd: str | None = "5",
    start: str | None = "04-May-26",
    finish: str | None = "15-May-26",
) -> list[PdfTextObject]:
    objs = [text_object(activity_id, x, y), text_object(name, "134", y)]
    if od is not None:
        objs.append(text_object(od, str(D(465) - D("3.5") * len(od)), y))
    if rd is not None:
        objs.append(text_object(rd, str(D(496) - D("3.5") * len(rd)), y))
    if start is not None:
        objs.append(text_object(start, "501", y))
    if finish is not None:
        objs.append(text_object(finish, "562", y))
    return objs


def summary(
    label: str, y: str = "600", *, x: str = "56.78", values: bool = True
) -> list[PdfTextObject]:
    objs = [text_object(label, x, y, size="8", font="Arial,Bold")]
    if values:
        objs += [
            text_object("60", "458", y),
            text_object("40", "489", y),
            text_object("04-May-26", "501", y),
            text_object("31-Jul-26", "562", y),
        ]
    return objs


def issue_set(row: ClassifiedRow) -> set[tuple[ScheduleIssueCode, ScheduleFieldCode | None]]:
    return set(row.issues)


# --- 4.3 grid -------------------------------------------------------------------

GRID_MPT = (37_000, 131_000, 435_500, 467_500, 498_500, 559_000, 615_500)


@pytest.mark.parametrize("line", range(7))
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_cell_band_boundaries_on_every_grid_line(line: int, offset: int) -> None:
    centre = GRID_MPT[line] + offset
    box = ScheduleBox(centre - 1_000, 0, centre + 1_000, 1_000)
    # Half-open on the right: the centre exactly on a line belongs to the band
    # that line opens; left of 37.0 is out of grid, at/after 615.5 is chart.
    expected_index = line - 1 if offset < 0 else line
    expected = expected_index if 0 <= expected_index <= 5 else None
    assert band_of(box) == expected


# --- 4.6 watermark ------------------------------------------------------------------

ROT_7 = (D("0.992546"), D("0.121869"), D("-0.121869"), D("0.992546"), D(0), D(0))
WATERMARK_BOX = (317_000, 252_000, 864_000, 512_000)


def test_watermark_signature_and_ordinary_draft() -> None:
    box = ScheduleBox(*WATERMARK_BOX)
    assert matches_watermark("DRAFT", box, ROT_7)  # type: ignore[arg-type]
    assert matches_watermark(" DRAFT ", box, ROT_7)  # type: ignore[arg-type]
    assert not matches_watermark("Draft", box, ROT_7)  # type: ignore[arg-type]
    # An ordinary horizontal DRAFT cell is never the watermark (R2-AC-011).
    assert not matches_watermark("DRAFT", ScheduleBox(134_000, 598_600, 151_500, 604_900), IDENTITY)
    assert not matches_watermark("DRAFT", box, IDENTITY)
    # Each edge within +-12.0 pt, inclusive; 12.001 pt is outside.
    for edge in range(4):
        for delta, ok in ((12_000 - 8_000, True), (12_001 - 8_000, False)):
            moved = list(WATERMARK_BOX)
            moved[edge] += delta if edge in (0, 1) else -delta
            # WATERMARK_BOX sits 8 pt inside the signature box on every edge.
            moved[edge] = (309_000, 244_000, 872_000, 503_000)[edge] + (
                -(12_000 if ok else 12_001) if edge in (0, 1) else (12_000 if ok else 12_001)
            )
            shifted = ScheduleBox(*moved)
            assert matches_watermark("DRAFT", shifted, ROT_7) is ok, (edge, ok)  # type: ignore[arg-type]


def test_watermark_rotation_uses_decimal_tangents() -> None:
    box = ScheduleBox(*WATERMARK_BOX)

    def rot(a: str, b: str) -> tuple[Decimal, ...]:
        return (D(a), D(b), -D(b), D(a), D(0), D(0))

    # tan 5 deg = 0.087489 (inclusive) and tan 85 deg = 11.430052 (inclusive).
    assert matches_watermark("DRAFT", box, rot("1", "0.087489"))  # type: ignore[arg-type]
    assert not matches_watermark("DRAFT", box, rot("1", "0.087488"))  # type: ignore[arg-type]
    assert matches_watermark("DRAFT", box, rot("1", "11.430052"))  # type: ignore[arg-type]
    assert not matches_watermark("DRAFT", box, rot("1", "11.430053"))  # type: ignore[arg-type]
    assert matches_watermark("DRAFT", box, rot("0.5", "-0.06"))  # type: ignore[arg-type]
    assert not matches_watermark("DRAFT", box, rot("-1", "0.5"))  # type: ignore[arg-type]
    # 7 deg (tan 0.122785) sits inside; the fixture matrix is exact Decimal.
    assert matches_watermark("DRAFT", box, ROT_7)  # type: ignore[arg-type]


# --- 5.3 exclusion and 5.4 twins ------------------------------------------------


def _page(*objects: PdfTextObject) -> PdfPageText:
    return PdfPageText(1, 1_224_000, 792_000, tuple(objects))


def test_exclusion_removes_chart_and_watermark_and_refuses_rotated_table_text() -> None:
    chart = text_object("Synthetic activity", "620", "600")
    mark = text_object("DRAFT", "0", "0", box=WATERMARK_BOX, matrix=ROT_7)
    header = text_object("Layout: SYN Full", "40", "740")
    cell = text_object("SYN-1000", "60.30", "600")
    zones = exclude_profile_non_data(_page(chart, mark, header, cell), P6_FULL_V1)
    assert (zones.chart_excluded, zones.watermark_excluded) == (1, 1)
    assert [o.source for o in zones.metadata_objects] == [header]
    assert [o.source for o in zones.table_objects] == [cell]
    skew = (D("0.999848"), D("0.017452"), D("-0.017452"), D("0.999848"), D(0), D(0))
    rotated = text_object("Synthetic skew", "134", "580", matrix=skew)
    with pytest.raises(ScheduleParseRefusal) as caught:
        exclude_profile_non_data(_page(cell, rotated), P6_FULL_V1)
    assert caught.value.code is ScheduleIssueCode.UNSUPPORTED_LAYOUT
    assert caught.value.page_number == 1
    # A rotated object in the header/footer is ignored, never refused.
    rotated_header = text_object("Synthetic note", "40", "770", matrix=skew)
    assert exclude_profile_non_data(_page(cell, rotated_header), P6_FULL_V1).metadata_objects


# --- 5.5 rows ---------------------------------------------------------------------


def test_rows_group_by_seed_overlap_not_centre_distance() -> None:
    # A 10 pt label whose centre is 3.0 pt above the 7 pt cells' centre still
    # overlaps them by 0.74 of the smaller height: one row (family 3).
    label = text_object("Synthetic Project", "52.57", "602.25", size="10", font="Arial,Bold")
    cells = [text_object("120", "454.5", "600"), text_object("04-May-26", "501", "600")]
    rows = rows_of(label, *cells)
    assert len(rows) == 1
    assert rows[0].seed.source is label
    # Centres 3.0 pt apart but overlap below one half: two rows.
    low = text_object("5", "489", "596.0")
    high = text_object("7", "458", "600")
    assert len(rows_of(high, low)) == 2
    # A 20 pt tall object overlapping a 7 pt seed joins it; the row's span then
    # exceeds 16.0 pt and the row is ambiguous (D-22).
    tall = text_object("X", "300", "600", box=(300_000, 586_000, 303_500, 606_000))
    seed = text_object("SYN-1000", "60.30", "600")
    rows = rows_of(seed, tall, text_object("Synthetic activity", "134", "600"))
    assert len(rows) == 1
    assert rows[0].box.y1 - rows[0].box.y0 == 20_000
    assigned = assign_full_cells(rows[0])
    assert assigned.row_ambiguous
    assert (ScheduleIssueCode.AMBIGUOUS_CELL, None) in assigned.issues


def test_overlap_ratio_boundary_is_one_half() -> None:
    seed = text_object("A", "60", box=(60_000, 600_000, 63_500, 606_000))
    exactly_half = text_object("B", "134", box=(134_000, 597_000, 137_500, 603_000))
    below_half = text_object("C", "200", box=(200_000, 596_999, 203_500, 602_999))
    assert len(rows_of(seed, exactly_half)) == 1
    assert len(rows_of(seed, below_half)) == 2


def test_grouping_compares_to_the_fixed_seed() -> None:
    # b overlaps the seed a by exactly half; c overlaps b fully but a not at
    # all. With no chaining c starts its own row.
    a = text_object("A", "60", box=(60_000, 600_000, 63_500, 606_000))
    b = text_object("B", "134", box=(134_000, 597_000, 137_500, 603_000))
    c = text_object("C", "200", box=(200_000, 594_000, 203_500, 600_000))
    rows = rows_of(a, b, c)
    assert [[o.source for o in r.objects] for r in rows] == [[a, b], [c]]


def test_zero_height_objects_never_seed_and_join_a_containing_seed() -> None:
    seed = text_object("SYN-1000", "60.30", "600")
    ghost = text_object("", "480", "600", suppressed=True, box=(480_000, 600_000, 480_000, 600_000))
    rows = rows_of(ghost, seed)
    assert len(rows) == 1
    assert rows[0].seed.source is seed
    assert {o.source for o in rows[0].objects} == {seed, ghost}


# --- 5.7 cells, 5.10 classification -----------------------------------------------


def _types(rows: Sequence[ClassifiedRow]) -> list[ScheduleRowType]:
    return [r.row_type for r in rows]


def test_classification_precedence() -> None:
    amb = ScheduleRowType.AMBIGUOUS
    cell_none = (ScheduleIssueCode.AMBIGUOUS_CELL, None)
    # rule 2: milestone pattern
    (row,) = classified(*activity("SYN-1", od="0", rd="0", finish=None))
    assert row.row_type is ScheduleRowType.MILESTONE
    (row,) = classified(*activity("SYN-1", od="0", rd="0", start=None))
    assert row.row_type is ScheduleRowType.MILESTONE
    # rule 3: zero durations without the exact date pattern
    (row,) = classified(*activity("SYN-1", od="0", rd="0"))
    assert (row.row_type, issue_set(row)) == (amb, {cell_none})
    (row,) = classified(*activity("SYN-1", od="0", rd="0", start=None, finish=None))
    assert (row.row_type, issue_set(row)) == (amb, {cell_none})
    # rule 4
    (row,) = classified(*activity("SYN-1"))
    assert (row.row_type, row.published_activity_id, row.activity_name) == (
        ScheduleRowType.ACTIVITY,
        "SYN-1",
        "Synthetic activity",
    )
    # rule 5: ID-bearing without a name
    objs = [o for o in activity("SYN-1") if o.text != "Synthetic activity"]
    (row,) = classified(*objs)
    assert (row.row_type, issue_set(row)) == (
        amb,
        {(ScheduleIssueCode.AMBIGUOUS_CELL, ScheduleFieldCode.ACTIVITY_NAME)},
    )
    assert (row.published_activity_id, row.activity_name) == (None, None)
    # rule 6 / 6'
    (row,) = classified(*summary("Synthetic Phase A"))
    assert (row.row_type, row.activity_name) == (ScheduleRowType.WBS_SUMMARY, "Synthetic Phase A")
    assert row.published_activity_id is None
    (row,) = classified(*summary("Synthetic Phase A", values=False))
    assert (row.row_type, issue_set(row)) == (amb, {cell_none})
    # rule 7: values without a label, or a name without an ID
    missing = {(ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID, ScheduleFieldCode.ACTIVITY_ID)}
    (row,) = classified(*activity("SYN-1")[2:])
    assert (row.row_type, issue_set(row)) == (amb, missing)
    (row,) = classified(*activity("SYN-1")[1:2])
    assert (row.row_type, issue_set(row)) == (amb, missing)
    # rule 1 via the mixed left-label case (regular ID with a bold name)
    bold_name = text_object("Synthetic activity", "134", font="Arial,Bold")
    (row,) = classified(text_object("SYN-1", "60.30"), bold_name, *activity("SYN-1")[2:])
    assert row.row_type is amb
    assert cell_none in issue_set(row)
    assert {c.state for c in row.assigned.cells[:2]} == {ScheduleCellState.AMBIGUOUS}
    # rule 1 via an OTHER-font object in a value band (D-10)
    courier = text_object("10", "458", font="Courier")
    (row,) = classified(*activity("SYN-1", od=None), courier)
    assert row.row_type is amb
    assert (ScheduleIssueCode.AMBIGUOUS_CELL, ScheduleFieldCode.ORIGINAL_DURATION) in issue_set(row)
    # rule 1 via real text left of the grid
    (row,) = classified(*activity("SYN-1"), text_object("x", "30"))
    assert row.row_type is amb
    assert cell_none in issue_set(row)
    # rule 8: a summary whose merged label cell is ambiguous
    one = text_object("Synthetic Phase", "56.78", font="Arial,Bold")
    two = text_object("Phase", "80", font="Arial,Bold")
    (row,) = classified(one, two, *summary("x")[1:])
    assert row.row_type is amb
    assert (ScheduleIssueCode.OVERLAPPING_CELL_TEXT, ScheduleFieldCode.ACTIVITY_NAME) in row.issues


def test_merged_bold_label_is_one_name_cell_never_split_at_131() -> None:
    label = text_object(
        "Synthetic Phase A merged summary label", "56.78", size="8", font="Arial,Bold"
    )
    (row,) = classified(label, *summary("x")[1:])
    id_cell, name_cell = row.assigned.cells[:2]
    assert id_cell.state is ScheduleCellState.PUBLISHED_BLANK
    assert name_cell.text == "Synthetic Phase A merged summary label"
    assert row.row_type is ScheduleRowType.WBS_SUMMARY
    assert row.left_edge == 56_780
    # Two bold pieces either side of 131.0 are still one merged label.
    left = text_object("Synthetic", "56.78", size="8", font="Arial,Bold")
    right = text_object("Phase", "140", size="8", font="Arial,Bold")
    (row,) = classified(left, right, *summary("x")[1:])
    assert row.assigned.cells[1].text == "Synthetic Phase"
    assert row.assigned.cells[0].fragments == ()


def test_cell_overlap_threshold_is_250_mpt() -> None:
    first = text_object("Synthetic", "134")  # ends at 165.5 pt
    abut = text_object("activity", "165.25")  # 250 mpt overlap: joined
    (row,) = classified(text_object("SYN-1", "60.30"), first, abut, *activity("SYN-1")[2:])
    assert row.assigned.cells[1].state is ScheduleCellState.PUBLISHED_VALUE
    assert row.activity_name == "Synthetic activity"
    over = text_object("activity", "165.249")  # 251 mpt: overlapping
    (row,) = classified(text_object("SYN-1", "60.30"), first, over, *activity("SYN-1")[2:])
    assert row.assigned.cells[1].state is ScheduleCellState.AMBIGUOUS
    assert (ScheduleIssueCode.OVERLAPPING_CELL_TEXT, ScheduleFieldCode.ACTIVITY_NAME) in row.issues


def test_dates_and_durations_in_cells() -> None:
    (row,) = classified(
        *activity("SYN-1", od="12.5", rd="15-Mar-28", start="11-May-26*", finish="31-Feb-27")
    )
    assigned = row.assigned
    assert str(assigned.original_duration.value) == "12.500"
    assert assigned.remaining_duration.state is ScheduleCellState.EXTRACTION_FAILED
    assert assigned.remaining_duration.value is None
    assert (assigned.start.value.isoformat(), assigned.start.marker) == ("2026-05-11", "*")  # type: ignore[union-attr]
    assert assigned.finish.state is ScheduleCellState.EXTRACTION_FAILED
    assert {
        (ScheduleIssueCode.INVALID_DURATION, ScheduleFieldCode.REMAINING_DURATION),
        (ScheduleIssueCode.INVALID_DATE, ScheduleFieldCode.FINISH),
    } <= issue_set(row)
    assert row.row_type is ScheduleRowType.ACTIVITY


# --- 5.9 wrap -----------------------------------------------------------------------


def test_row_wrap_requires_pitch_below_10pt() -> None:
    def wrap_codes(gap: str) -> list[set[tuple[ScheduleIssueCode, ScheduleFieldCode | None]]]:
        y = str(D(600) - D(gap))
        rows = classified(*activity("SYN-1"), text_object("continued", "134", y))
        return [issue_set(r) for r in rows]

    wrap = (ScheduleIssueCode.ROW_WRAP_UNSUPPORTED, None)
    assert wrap in wrap_codes("8")[1]
    assert wrap in wrap_codes("9.999")[1]
    assert wrap not in wrap_codes("10")[1]
    assert wrap not in wrap_codes("15")[1]
    # A regular ID, or any value, makes the line independent, never a wrap.
    rows = classified(*activity("SYN-1"), *activity("SYN-2", "592"))
    assert _types(rows) == [ScheduleRowType.ACTIVITY] * 2
    rows = classified(
        *activity("SYN-1"), text_object("continued", "134", "592"), text_object("5", "492.5", "592")
    )
    assert wrap not in issue_set(rows[1])
    # Nothing is concatenated onto the predecessor.
    rows = classified(*activity("SYN-1"), text_object("continued", "134", "592"))
    assert rows[0].activity_name == "Synthetic activity"
    assert (rows[1].row_type, rows[1].activity_name) == (ScheduleRowType.AMBIGUOUS, None)


def test_wrap_detects_bold_label_continuations() -> None:
    wrap = (ScheduleIssueCode.ROW_WRAP_UNSUPPORTED, None)
    label = summary("Synthetic Stage with a label", x="60.30")
    continuation = text_object("continued onto a second line", "60.30", "592", font="Arial,Bold")
    rows = classified(*label, continuation)
    assert rows[0].row_type is ScheduleRowType.WBS_SUMMARY
    assert issue_set(rows[1]) == {wrap}
    # At normal pitch it is not a wrap: rule 6' decides (no phantom summary).
    later = text_object("Synthetic Phase B", "60.30", "585", font="Arial,Bold")
    rows = classified(*label, later)
    assert issue_set(rows[1]) == {(ScheduleIssueCode.AMBIGUOUS_CELL, None)}


def test_summary_requires_a_value_cell() -> None:
    (row,) = classified(*summary("Synthetic Phase A", values=False))
    assert row.row_type is ScheduleRowType.AMBIGUOUS
    for value in summary("Synthetic Phase A")[1:]:
        (row,) = classified(summary("Synthetic Phase A", values=False)[0], value)
        assert row.row_type is ScheduleRowType.WBS_SUMMARY, value.text
    # A failed value is still structurally present; the summary never becomes an activity.
    bad = text_object("15-Mar-28", "467.6")
    (row,) = classified(summary("Synthetic Phase A", values=False)[0], bad)
    assert row.row_type is ScheduleRowType.WBS_SUMMARY


# --- 5.11 hierarchy --------------------------------------------------------------------

INDENT = ("52.57", "56.78", "60.30", "63.88", "67.70", "71.53", "75.35", "79.08")


def _ladder(*specs: tuple[str, int, str]) -> list[ClassifiedRow]:
    """(kind, level or x, label/ID) rows, 15 pt apart."""
    objs: list[PdfTextObject] = []
    for index, (kind, level, text) in enumerate(specs):
        y = str(685 - 15 * index)
        x = INDENT[level]
        if kind == "S":
            objs += summary(text, y, x=x)
        else:
            objs += activity(text, y, x=x)
    return classified(*objs)


def _hierarchy(
    rows: Sequence[ClassifiedRow], limits: ScheduleParseLimits = PRODUCTION_LIMITS
) -> tuple[HierarchyAssignment, ...]:
    return reconstruct_full_hierarchy(rows, P6_FULL_V1, limits)


def test_hierarchy_clusters_and_stack() -> None:
    rows = _ladder(
        ("S", 0, "Synthetic Project"),
        ("S", 1, "Synthetic Phase A"),
        ("A", 2, "SYN-1"),
        ("S", 2, "Synthetic Stage 1"),
        ("A", 3, "SYN-2"),
        ("S", 1, "Synthetic Phase A"),
        ("A", 2, "SYN-3"),
    )
    result = _hierarchy(rows)
    assert [(h.row_type, h.indent_level, h.parent_row_ordinal) for h in result] == [
        (ScheduleRowType.PROJECT_SUMMARY, 0, None),
        (ScheduleRowType.WBS_SUMMARY, 1, 1),
        (ScheduleRowType.ACTIVITY, 2, 2),
        (ScheduleRowType.WBS_SUMMARY, 2, 2),
        (ScheduleRowType.ACTIVITY, 3, 4),
        (ScheduleRowType.WBS_SUMMARY, 1, 1),
        (ScheduleRowType.ACTIVITY, 2, 6),
    ]
    assert result[4].hierarchy_path == (
        "Synthetic Project",
        "Synthetic Phase A",
        "Synthetic Stage 1",
    )
    # Repeated label text is two distinct rows; the path names its own ancestor.
    assert result[6].hierarchy_path == ("Synthetic Project", "Synthetic Phase A")
    assert result[0].hierarchy_path == ()
    assert not any(h.ambiguous for h in result)
    # Fixed-seed clustering: 0.6 pt jitter joins, a 1.5 pt spread joins, 1.501 does not.
    jitter = classified(
        *summary("Synthetic Project", "685", x="52.57"), *activity("SYN-1", "670", x="54.07")
    )
    assert [h.indent_level for h in _hierarchy(jitter)] == [0, 0]
    split = classified(
        *summary("Synthetic Project", "685", x="52.57"), *activity("SYN-1", "670", x="54.071")
    )
    assert [h.indent_level for h in _hierarchy(split)] == [None, None]
    # More clusters than the bound fails closed.
    with pytest.raises(ScheduleParseRefusal) as caught:
        _hierarchy(rows, ScheduleParseLimits(max_hierarchy_depth=3))
    assert caught.value.code is ScheduleIssueCode.BOUNDS_EXCEEDED


def test_hierarchy_ambiguity_propagates() -> None:
    # Level-1 centroid 1.83 pt from level 0: both clusters indeterminate, and
    # the determinate level-2 cluster below inherits it through its parent.
    objs = [
        *summary("Synthetic Project", "685", x="52.57"),
        *summary("Synthetic Phase A", "670", x="54.40"),
        *activity("SYN-1", "655", x="60.30"),
    ]
    result = _hierarchy(classified(*objs))
    assert [h.ambiguous for h in result] == [True, True, True]
    assert [h.indent_level for h in result] == [None, None, 2]
    assert all(h.parent_row_ordinal is None and h.hierarchy_path is None for h in result)
    # No project summary is promoted from an indeterminate first summary.
    assert result[0].row_type is ScheduleRowType.WBS_SUMMARY
    # Adjacent centroids exactly 3.0 pt apart are determinate.
    objs = [*summary("Synthetic Project", "685", x="52.57"), *activity("SYN-1", "670", x="55.57")]
    assert [h.ambiguous for h in _hierarchy(classified(*objs))] == [False, False]
    # An activity before any summary has no parent: indeterminate.
    objs = [*activity("SYN-1", "685", x="60.30"), *summary("Synthetic Project", "670", x="52.57")]
    result = _hierarchy(classified(*objs))
    assert [h.ambiguous for h in result] == [True, False]
    assert result[1].row_type is ScheduleRowType.PROJECT_SUMMARY


def test_level_gap_is_hierarchy_ambiguous() -> None:
    rows = _ladder(
        ("S", 0, "Synthetic Project"),
        ("S", 1, "Synthetic Phase A"),
        ("A", 2, "SYN-1"),
        ("A", 3, "SYN-2"),
        ("S", 3, "Synthetic Step"),
        ("A", 4, "SYN-3"),
    )
    result = _hierarchy(rows)
    assert [h.ambiguous for h in result] == [False, False, False, True, True, True]
    assert (result[3].indent_level, result[3].parent_row_ordinal) == (3, None)
    assert result[5].hierarchy_path is None


def test_missing_and_duplicate_ids_force_review_required() -> None:
    for family in ("full_missing_activity_id", "full_duplicate_activity_id"):
        result = parse_full_schedule(gen.build(family, "base").pdf)
        assert result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED
        assert derive_outcome(result.issues, result.rows) is result.outcome
    duplicate = parse_full_schedule(gen.build("full_duplicate_activity_id", "base").pdf)
    flagged = [
        i.row_ordinal for i in duplicate.issues if i.code is ScheduleIssueCode.DUPLICATE_ACTIVITY_ID
    ]
    assert [duplicate.rows[o - 1].published_activity_id for o in flagged] == ["SYN-1100"] * 2


# --- V11-V13 ----------------------------------------------------------------------


def _frame(
    page: int = 1,
    total: int = 1,
    *,
    od: str | None = "OD",
    extra: Sequence[PdfTextObject] = (),
) -> PageZones:
    meta = [
        text_object("Synthetic Project Schedule", "40", "760", size="12", font="Arial,Bold"),
        text_object("Layout: SYN Full", "40", "740"),
        text_object("Data Date: 04-May-26", "300", "740"),
        text_object("Run Date: 11-May-26", "900", "740"),
        text_object(f"Summary Page {page} of {total}", "1000", "40"),
    ]
    for text, x in (
        ("Activity ID", "38.88"),
        ("Activity Name", "134.52"),
        ("OD", "446.63"),
        ("RD", "478.20"),
        ("Start", "520.50"),
        ("Finish", "576.97"),
    ):
        if text == "OD" and od is None:
            continue
        meta.append(text_object(text, x, "710"))
    meta += extra
    return PageZones(page, tuple(known(o) for o in meta), (), 0, 0, 0)


def test_od_occlusion_admits_replaced_and_overlay_only() -> None:
    occluder = text_object("04-May-26", "436", "710")

    def check(page2: PageZones) -> list[tuple[ScheduleIssueCode, int | None, object]]:
        return list(validate_full_profile([_frame(1, 2), page2], expected_data_date=None).issues)

    occluded = (ScheduleIssueCode.HEADER_OD_OCCLUDED, 2, ScheduleFieldCode.ORIGINAL_DURATION)
    assert check(_frame(2, 2, od=None, extra=[occluder])) == [occluded]  # replaced
    assert check(_frame(2, 2, extra=[occluder])) == [occluded]  # overlay
    mismatch = (ScheduleIssueCode.HEADER_SIGNATURE_MISMATCH, 2, None)
    # A non-date occluder, a second extra object, or a date outside the OD band
    # is a header mismatch, not an occlusion.
    assert check(_frame(2, 2, od=None, extra=[text_object("4 days", "436", "710")])) == [mismatch]
    second = text_object("05-May-26", "300", "710")
    assert check(_frame(2, 2, od=None, extra=[occluder, second])) == [mismatch]
    assert check(_frame(2, 2, od=None, extra=[text_object("04-May-26", "470", "710")])) == [
        mismatch
    ]
    assert check(_frame(2, 2, od=None)) == [mismatch]
    # Page 1 may be occluded too; a page-1 mismatch is a refusal.
    result = validate_full_profile([_frame(od=None, extra=[occluder])], expected_data_date=None)
    assert result.issues == (
        (ScheduleIssueCode.HEADER_OD_OCCLUDED, 1, ScheduleFieldCode.ORIGINAL_DURATION),
    )
    with pytest.raises(ScheduleParseRefusal) as caught:
        validate_full_profile([_frame(od=None)], expected_data_date=None)
    assert (caught.value.code, caught.value.page_number) == (
        ScheduleIssueCode.UNSUPPORTED_LAYOUT,
        1,
    )
