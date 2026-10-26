"""The frozen `p6_full_v1` profile and its limits (contract section 4).

FAST: no PDF. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
section 4 pins every constant here; a value change must bump `PARSER_VERSION`
and edit this file in the same diff. The pure parser stages of contract
section 5 are tested here over hand-built `PdfTextObject` lists by the WP-02
parser change.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from fractions import Fraction

import pytest

from my_pa.domain.schedule import SchedulePublicationStatus
from my_pa.infrastructure.schedule import P6_FULL_V1, PRODUCTION_LIMITS, ScheduleParseLimits
from my_pa.infrastructure.schedule.full_profile import (
    DOCUMENT_TYPE,
    MEASURED_CORPUS,
    PARSER_NAME,
    PARSER_VERSION,
    PROCESSING_BUDGET_SECONDS,
    PROFILE_ID,
    PROFILE_VERSION,
    MeasuredCorpus,
)


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
