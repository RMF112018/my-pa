"""CPM Workbench S5a: the frozen `p6_full_v1` Full-Schedule profile.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
section 4 (profile constants and limits). Every geometric constant is integer
millipoints (1 pt = 1000 mpt); every angle test is an exact `Decimal` tangent.
Values marked as synthetic assumptions in the contract (zones, token shapes,
watermark signature) are unverified against a real corpus (contract U-01..U-03);
changing any value here changes parser output and must bump `PARSER_VERSION`.

This module is a pure algorithm module: it never imports `pypdfium2` (only
`infrastructure/schedule/pdf.py` may). The parser stages of contract section 5
(`exclude_profile_non_data` through `parse_full_schedule`) are added here by the
WP-02 parser change; this file holds only the frozen profile, the limits and
the measured-corpus evidence they are derived from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from decimal import Decimal
from fractions import Fraction
from typing import Final

from my_pa.domain.schedule.model import SchedulePublicationStatus

__all__ = [
    "DOCUMENT_TYPE",
    "MEASURED_CORPUS",
    "P6_FULL_V1",
    "PARSER_NAME",
    "PARSER_VERSION",
    "PROCESSING_BUDGET_SECONDS",
    "PRODUCTION_LIMITS",
    "PROFILE_ID",
    "PROFILE_VERSION",
    "FullScheduleProfile",
    "MeasuredCorpus",
    "ScheduleParseLimits",
]

PROFILE_ID: Final = "p6_full_v1"
PROFILE_VERSION: Final = 1
DOCUMENT_TYPE: Final = "full"
PARSER_NAME: Final = "cpm-workbench-full-parser"
#: Bumped whenever identical bytes could produce a different parse result.
PARSER_VERSION: Final = "1"

#: WP-03's handler computes the parse deadline from this; not a limits field.
PROCESSING_BUDGET_SECONDS: Final = 240


@dataclass(frozen=True, slots=True)
class FullScheduleProfile:
    """Every contract section 4 constant, held by the single `P6_FULL_V1`."""

    profile_id: str
    profile_version: int
    document_type: str
    parser_name: str
    parser_version: str
    # 4.2 page geometry
    page_width_mpt: int
    page_height_mpt: int
    page_size_tolerance_mpt: int
    page_origin_tolerance_mpt: int
    # 4.3 x grid
    table_left_mpt: int
    id_name_mpt: int
    name_od_mpt: int
    od_rd_mpt: int
    rd_start_mpt: int
    start_finish_mpt: int
    chart_boundary_mpt: int
    # 4.4 y zones (inclusive data zone; header band is (data_top, header_top])
    data_zone_bottom_mpt: int
    data_zone_top_mpt: int
    header_band_top_mpt: int
    # 4.5 header anchors and metadata grammars
    column_anchor_texts: tuple[str, str, str, str, str, str]
    layout_pattern: re.Pattern[str]
    data_date_pattern: re.Pattern[str]
    run_date_pattern: re.Pattern[str]
    page_signature_pattern: re.Pattern[str]
    title_max_chars: int
    # 4.6 watermark signature
    watermark_text: str
    watermark_box_mpt: tuple[int, int, int, int]
    watermark_edge_tolerance_mpt: int
    watermark_tan_min: Decimal
    watermark_tan_max: Decimal
    near_horizontal_tan: Decimal
    # 4.9 grouping, cells, hierarchy
    row_overlap_ratio: Fraction
    row_max_span_mpt: int
    wrap_pitch_mpt: int
    duplicate_edge_tolerance_mpt: int
    cell_overlap_mpt: int
    indent_tolerance_mpt: int
    indent_min_separation_mpt: int
    regular_font: str
    bold_font: str
    subset_prefix: re.Pattern[str]

    @property
    def grid_mpt(self) -> tuple[int, int, int, int, int, int, int]:
        """The 7 x grid lines, left to right (contract 4.3)."""
        return (
            self.table_left_mpt,
            self.id_name_mpt,
            self.name_od_mpt,
            self.od_rd_mpt,
            self.rd_start_mpt,
            self.start_finish_mpt,
            self.chart_boundary_mpt,
        )


P6_FULL_V1: Final = FullScheduleProfile(
    profile_id=PROFILE_ID,
    profile_version=PROFILE_VERSION,
    document_type=DOCUMENT_TYPE,
    parser_name=PARSER_NAME,
    parser_version=PARSER_VERSION,
    page_width_mpt=1_224_000,
    page_height_mpt=792_000,
    page_size_tolerance_mpt=500,
    page_origin_tolerance_mpt=500,
    table_left_mpt=37_000,
    id_name_mpt=131_000,
    name_od_mpt=435_500,
    od_rd_mpt=467_500,
    rd_start_mpt=498_500,
    start_finish_mpt=559_000,
    chart_boundary_mpt=615_500,
    data_zone_bottom_mpt=95_000,
    data_zone_top_mpt=700_000,
    header_band_top_mpt=724_000,
    column_anchor_texts=("Activity ID", "Activity Name", "OD", "RD", "Start", "Finish"),
    layout_pattern=re.compile(r"^Layout: (?P<value>\S.{0,198})$"),
    data_date_pattern=re.compile(r"^Data Date: (?P<date>\S+)$"),
    run_date_pattern=re.compile(r"^Run Date: (?P<date>\S+)$"),
    page_signature_pattern=re.compile(
        r"^Summary Page (?P<n>[1-9][0-9]{0,2}) of (?P<m>[1-9][0-9]{0,2})$"
    ),
    title_max_chars=300,
    watermark_text="DRAFT",
    watermark_box_mpt=(309_000, 244_000, 872_000, 503_000),
    watermark_edge_tolerance_mpt=12_000,
    watermark_tan_min=Decimal("0.087489"),
    watermark_tan_max=Decimal("11.430052"),
    near_horizontal_tan=Decimal("0.01"),
    row_overlap_ratio=Fraction(1, 2),
    row_max_span_mpt=16_000,
    wrap_pitch_mpt=10_000,
    duplicate_edge_tolerance_mpt=250,
    cell_overlap_mpt=250,
    indent_tolerance_mpt=1_500,
    indent_min_separation_mpt=3_000,
    regular_font="Arial",
    bold_font="Arial,Bold",
    subset_prefix=re.compile(r"^[A-Z]{6}\+"),
)


@dataclass(frozen=True, slots=True)
class ScheduleParseLimits:
    """Contract 4.10 bounds. An instance may only tighten production (D-24)."""

    max_bytes: int = 16_777_216
    max_pages: int = 250
    max_text_objects: int = 250_000
    max_page_objects: int = 1_000_000
    max_text_chars: int = 2_000_000
    max_rows: int = 25_000
    max_issues: int = 50_000
    #: Unreachable at production values (at most 9 row-referencing codes exist);
    #: only an injected limit exercises it.
    max_row_warnings: int = 16
    max_hierarchy_depth: int = 32
    max_cell_evidence_bytes: int = 16_384
    max_form_depth: int = 4

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("schedule parse limits are non-negative integers")
            if value > _PRODUCTION_VALUES[item.name]:
                raise ValueError("schedule parse limits may only tighten production values")


_PRODUCTION_VALUES: Final[dict[str, int]] = {
    item.name: item.default  # type: ignore[misc]
    for item in fields(ScheduleParseLimits)
}

PRODUCTION_LIMITS: Final = ScheduleParseLimits()


@dataclass(frozen=True, slots=True)
class MeasuredCorpus:
    """R2 sections 13.1 and 13.4 measured-corpus facts: documentation, not input.

    Counts and page ordinals only; no filename, byte count, digest, title or
    token of the corpus is held here.
    """

    pages: int
    table_rows: int
    summary_rows: int
    id_bearing_rows: int
    missing_id_rows: int
    page_width_pt: int
    page_height_pt: int
    missing_id_page: int
    od_header_occluded_page: int
    #: Summary RD, activity RD and activity OD date tokens, in that order.
    duration_date_pages: tuple[int, int, int]
    expected_outcome: SchedulePublicationStatus
    indent_centroids_pt: tuple[Decimal, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.summary_rows + self.id_bearing_rows + self.missing_id_rows != self.table_rows:
            raise ValueError("measured corpus rows must partition the table rows")


MEASURED_CORPUS: Final = MeasuredCorpus(
    pages=86,
    table_rows=3408,
    summary_rows=443,
    id_bearing_rows=2964,
    missing_id_rows=1,
    page_width_pt=1224,
    page_height_pt=792,
    missing_id_page=21,
    od_header_occluded_page=37,
    duration_date_pages=(55, 58, 61),
    expected_outcome=SchedulePublicationStatus.REVIEW_REQUIRED,
    indent_centroids_pt=tuple(
        Decimal(v) for v in ("52.57", "56.78", "60.30", "63.88", "67.70", "71.53", "75.35", "79.08")
    ),
)
