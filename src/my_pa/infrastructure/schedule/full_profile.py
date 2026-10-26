"""CPM Workbench S5a: the frozen `p6_full_v1` Full-Schedule profile.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
section 4 (profile constants and limits). Every geometric constant is integer
millipoints (1 pt = 1000 mpt); every angle test is an exact `Decimal` tangent.
Values marked as synthetic assumptions in the contract (zones, token shapes,
watermark signature) are unverified against a real corpus (contract U-01..U-03);
changing any value here changes parser output and must bump `PARSER_VERSION`.

This module is a pure algorithm module: it never imports `pypdfium2` (only
`infrastructure/schedule/pdf.py` may). It holds the frozen profile, the limits,
the measured-corpus evidence they are derived from, and the parser stages of
contract section 5 (`exclude_profile_non_data` through `parse_full_schedule`),
which work over the `PdfTextObject`s `pdf.py` extracts using integer
millipoint arithmetic only.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Final

from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ROW_CELL_FIELDS,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleParseCounts,
    ScheduleParseEngine,
    ScheduleParseIssue,
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowType,
    cell_evidence_bytes,
    derive_outcome,
    normalize_activity_id,
    normalize_display_text,
    parse_profile_date,
    parse_profile_duration,
)
from my_pa.infrastructure.schedule.pdf import (
    ParseBudget,
    PdfPageText,
    PdfTextObject,
    ScheduleParseRefusal,
    engine_provenance,
    extract_pdf_text_objects,
)

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
    "AssignedRow",
    "ClassifiedRow",
    "DuplicateResolution",
    "FontClass",
    "FullScheduleProfile",
    "HierarchyAssignment",
    "LabelCase",
    "MeasuredCorpus",
    "PageZones",
    "PdfPhysicalRow",
    "ProfileTextObject",
    "ProfileValidation",
    "ScheduleParseLimits",
    "assign_full_cells",
    "band_of",
    "classify_full_row",
    "collapse_duplicate_objects",
    "exclude_profile_non_data",
    "font_class",
    "group_table_rows_by_overlap",
    "is_near_horizontal",
    "matches_watermark",
    "parse_full_schedule",
    "reconstruct_full_hierarchy",
    "validate_full_profile",
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


# --- shared geometry (contract 4.1-4.6; integer millipoints, doubled centres) --

_X_CENTRE_DOUBLED: Final = 2
_ID_BAND: Final = 0
_NAME_BAND: Final = 1
_OD_BAND: Final = 2
_VALUE_BANDS: Final = frozenset({2, 3, 4, 5})
_LABEL_BANDS: Final = frozenset({_ID_BAND, _NAME_BAND})


class FontClass(Enum):
    """Contract 5.6: style is profile evidence only."""

    REGULAR = "regular"
    BOLD = "bold"
    OTHER = "other"


def _normalized_font(base_name: str, profile: FullScheduleProfile) -> str:
    return profile.subset_prefix.sub("", base_name, count=1)


def font_class(base_name: str, profile: FullScheduleProfile = P6_FULL_V1) -> FontClass:
    name = _normalized_font(base_name, profile)
    if name == profile.regular_font:
        return FontClass.REGULAR
    if name == profile.bold_font:
        return FontClass.BOLD
    return FontClass.OTHER


def band_of(box: ScheduleBox, profile: FullScheduleProfile = P6_FULL_V1) -> int | None:
    """The 0-based column band of a box's x-centre (contract 4.3), else `None`.

    `None` means out of the grid on the left (x-centre < 37.0) or in the chart
    (x-centre >= 615.5). Half-open on the right: `2 * left <= x0 + x1 < 2 * right`.
    """
    doubled = box.x0 + box.x1
    grid = profile.grid_mpt
    if doubled < _X_CENTRE_DOUBLED * grid[0]:
        return None
    for index in range(len(ROW_CELL_FIELDS)):
        if doubled < _X_CENTRE_DOUBLED * grid[index + 1]:
            return index
    return None


def _in_data_zone(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    doubled = box.y0 + box.y1
    return 2 * profile.data_zone_bottom_mpt <= doubled <= 2 * profile.data_zone_top_mpt


def _in_column_header_band(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    doubled = box.y0 + box.y1
    return 2 * profile.data_zone_top_mpt < doubled <= 2 * profile.header_band_top_mpt


def _in_top_band(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    return box.y0 + box.y1 > 2 * profile.header_band_top_mpt


def _in_footer(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    return box.y0 + box.y1 < 2 * profile.data_zone_bottom_mpt


def _left_of_chart(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    return box.x0 + box.x1 < 2 * profile.chart_boundary_mpt


def _area(box: ScheduleBox) -> int:
    return (box.x1 - box.x0) * (box.y1 - box.y0)


def _intersection_area(a: ScheduleBox, b: ScheduleBox) -> int:
    width = min(a.x1, b.x1) - max(a.x0, b.x0)
    height = min(a.y1, b.y1) - max(a.y0, b.y0)
    return width * height if width > 0 and height > 0 else 0


def _x_intersection(a: ScheduleBox, b: ScheduleBox) -> int:
    return max(0, min(a.x1, b.x1) - max(a.x0, b.x0))


Matrix = tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]


def is_near_horizontal(matrix: Matrix, profile: FullScheduleProfile = P6_FULL_V1) -> bool:
    """Contract 4.6.1 on the exact `Decimal` matrix."""
    a, b, c, d = matrix[:4]
    tan = profile.near_horizontal_tan
    return a > 0 and d > 0 and abs(b) <= tan * a and abs(c) <= tan * d


def _watermark_box(box: ScheduleBox, profile: FullScheduleProfile) -> bool:
    tolerance = profile.watermark_edge_tolerance_mpt
    edges = (box.x0, box.y0, box.x1, box.y1)
    return all(
        abs(edge - target) <= tolerance
        for edge, target in zip(edges, profile.watermark_box_mpt, strict=True)
    )


def _watermark_rotation(matrix: Matrix, profile: FullScheduleProfile) -> bool:
    a, b = matrix[0], matrix[1]
    return a > 0 and profile.watermark_tan_min * a <= abs(b) <= profile.watermark_tan_max * a


def matches_watermark(
    text: str, box: ScheduleBox, matrix: Matrix, profile: FullScheduleProfile = P6_FULL_V1
) -> bool:
    """Contract 4.6: text, box, rotation and zone all match the signature."""
    return (
        normalize_display_text(text) == profile.watermark_text
        and _watermark_box(box, profile)
        and _watermark_rotation(matrix, profile)
        and _in_data_zone(box, profile)
        and _left_of_chart(box, profile)
    )


# --- objects after twin resolution ------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileTextObject:
    """A `PdfTextObject` after section 5.4.1: its resolved text and twin.

    `text is None` marks an unknown-text fragment (a twinless suppressed
    object); a suppressed object with a twin carries the twin's text and the
    twin's `object_ordinal`.
    """

    source: PdfTextObject
    text: str | None
    twin: int | None = None

    @property
    def ordinal(self) -> int:
        return self.source.object_ordinal

    @property
    def box(self) -> ScheduleBox:
        return self.source.box

    @property
    def unknown(self) -> bool:
        return self.text is None

    @classmethod
    def of(cls, source: PdfTextObject) -> ProfileTextObject:
        """An unsuppressed object as itself; a suppressed one as unknown text."""
        return cls(source, None if source.suppressed else source.text)


def _pool_key(obj: ProfileTextObject) -> tuple[int, int, int]:
    return (-obj.box.y1, obj.box.x0, obj.ordinal)


# --- 5.3 exclusion ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageZones:
    page_number: int
    metadata_objects: tuple[ProfileTextObject, ...]
    table_objects: tuple[ProfileTextObject, ...]
    chart_excluded: int
    watermark_excluded: int
    #: Suppressed objects outside the chart, in every zone (contract 5.4 step 4).
    suppressed: int


def _twin(
    suppressed: PdfTextObject,
    others: Sequence[PdfTextObject],
    marked: frozenset[int],
    profile: FullScheduleProfile,
) -> PdfTextObject | None:
    """Contract 5.4 step 1: the deterministic twin of a suppressed object."""
    box = suppressed.box
    if _area(box) == 0:
        return None
    marks = [o for o in others if o.object_ordinal in marked and _intersection_area(o.box, box) > 0]
    if marks and _watermark_box(box, profile) and _watermark_rotation(suppressed.matrix, profile):
        candidates = marks
    else:
        zone = _in_data_zone(box, profile)
        candidates = [
            o
            for o in others
            if not o.suppressed
            and o.object_ordinal not in marked
            and _in_data_zone(o.box, profile) == zone
            and _intersection_area(o.box, box) > 0
        ]
    if not candidates or len({normalize_display_text(c.text) for c in candidates}) != 1:
        return None
    return min(candidates, key=lambda c: (-_intersection_area(c.box, box), c.object_ordinal))


def exclude_profile_non_data(page: PdfPageText, profile: FullScheduleProfile) -> PageZones:
    """Contract 5.3: chart, twins, header/footer, watermark, rotation."""
    kept: list[PdfTextObject] = []
    chart = 0
    for obj in page.objects:
        if _in_data_zone(obj.box, profile) and not _left_of_chart(obj.box, profile):
            chart += 1
        else:
            kept.append(obj)
    marked = frozenset(
        o.object_ordinal
        for o in kept
        if not o.suppressed and matches_watermark(o.text, o.box, o.matrix, profile)
    )
    resolved: list[ProfileTextObject] = []
    for obj in kept:
        if not obj.suppressed:
            resolved.append(ProfileTextObject(obj, obj.text))
            continue
        twin = _twin(obj, kept, marked, profile)
        resolved.append(
            ProfileTextObject(obj, None)
            if twin is None
            else ProfileTextObject(obj, twin.text, twin.object_ordinal)
        )
    metadata = tuple(o for o in resolved if not _in_data_zone(o.box, profile))
    table: list[ProfileTextObject] = []
    watermark = 0
    for item in resolved:
        if not _in_data_zone(item.box, profile):
            continue
        if item.text is not None and matches_watermark(
            item.text, item.box, item.source.matrix, profile
        ):
            watermark += 1
            continue
        if not is_near_horizontal(item.source.matrix, profile):
            raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, page.page_number)
        table.append(item)
    return PageZones(
        page_number=page.page_number,
        metadata_objects=metadata,
        table_objects=tuple(table),
        chart_excluded=chart,
        watermark_excluded=watermark,
        suppressed=sum(1 for o in kept if o.suppressed),
    )


# --- 5.4 duplicate collapse ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuplicateResolution:
    kept: tuple[ProfileTextObject, ...]
    #: `(collapsed object, the earliest kept object it collapsed into)`.
    collapsed: tuple[tuple[ProfileTextObject, ProfileTextObject], ...]


def _same_edges(a: ScheduleBox, b: ScheduleBox, profile: FullScheduleProfile) -> bool:
    tolerance = profile.duplicate_edge_tolerance_mpt
    return (
        abs(a.x0 - b.x0) <= tolerance
        and abs(a.y0 - b.y0) <= tolerance
        and abs(a.x1 - b.x1) <= tolerance
        and abs(a.y1 - b.y1) <= tolerance
    )


def collapse_duplicate_objects(
    objects: Iterable[ProfileTextObject], profile: FullScheduleProfile = P6_FULL_V1
) -> DuplicateResolution:
    """Contract 5.4 step 2, in `object_ordinal` order, into the earliest kept object.

    An exact duplicate has the same normalized text, the same prefix-normalized
    base font and every box edge within the duplicate tolerance. Unknown-text
    objects never collapse and are never collapsed into.
    """
    kept: list[ProfileTextObject] = []
    collapsed: list[tuple[ProfileTextObject, ProfileTextObject]] = []
    #: Kept objects by (normalized text, normalized font), in keeping order.
    by_key: dict[tuple[str, str], list[ProfileTextObject]] = {}
    for obj in sorted(objects, key=lambda o: o.ordinal):
        if obj.text is None:
            kept.append(obj)
            continue
        key = (
            normalize_display_text(obj.text),
            _normalized_font(obj.source.font_base_name, profile),
        )
        same = by_key.setdefault(key, [])
        into = next((k for k in same if _same_edges(obj.box, k.box, profile)), None)
        if into is None:
            kept.append(obj)
            same.append(obj)
        else:
            collapsed.append((obj, into))
    return DuplicateResolution(tuple(kept), tuple(collapsed))


# --- 4.5 / 5.2 V11-V13 profile validation ------------------------------------


class _Anchors(Enum):
    EXACT = "exact"
    OCCLUDED = "occluded"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class _PageMetadata:
    anchors: _Anchors
    layout: str | None
    data_date: date | None
    run_date: date | None
    title: str | None
    signature: tuple[int, int] | None

    @property
    def complete(self) -> bool:
        return None not in (self.layout, self.data_date, self.run_date, self.title, self.signature)


@dataclass(frozen=True, slots=True)
class ProfileValidation:
    title: str | None
    data_date: date | None
    run_date: date | None
    #: Page-level issue drafts `(code, page_number, field)`.
    issues: tuple[tuple[ScheduleIssueCode, int | None, ScheduleFieldCode | None], ...]


def _anchor_state(
    objects: Sequence[tuple[str, ScheduleBox]], profile: FullScheduleProfile
) -> _Anchors:
    header = [
        (text, box)
        for text, box in objects
        if _in_column_header_band(box, profile) and _left_of_chart(box, profile)
    ]
    matches = [
        [i for i, (text, box) in enumerate(header) if text == anchor and band_of(box, profile) == b]
        for b, anchor in enumerate(profile.column_anchor_texts)
    ]
    used = {i for found in matches for i in found}
    rest = [header[i] for i in range(len(header)) if i not in used]
    if all(len(found) == 1 for found in matches) and not rest:
        return _Anchors.EXACT
    others_exact = all(len(found) == 1 for b, found in enumerate(matches) if b != _OD_BAND)
    if (
        others_exact
        and len(matches[_OD_BAND]) <= 1
        and len(rest) == 1
        and band_of(rest[0][1], profile) == _OD_BAND
        and parse_profile_date(rest[0][0]) is not None
    ):
        return _Anchors.OCCLUDED
    return _Anchors.MISMATCH


def _one_date(objects: Sequence[tuple[str, ScheduleBox]], pattern: re.Pattern[str]) -> date | None:
    found = [m for text, _box in objects if (m := pattern.fullmatch(text))]
    if len(found) != 1:
        return None
    parsed = parse_profile_date(found[0]["date"])
    return parsed[0] if parsed is not None and parsed[1] is None else None


def _page_metadata(zones: PageZones, profile: FullScheduleProfile) -> _PageMetadata:
    objects = [
        (normalize_display_text(o.text), o.box)
        for o in zones.metadata_objects
        if o.text is not None
        and not o.source.unmapped
        and is_near_horizontal(o.source.matrix, profile)
    ]
    top = [(text, box) for text, box in objects if _in_top_band(box, profile)]
    layouts = [m for text, _box in top if (m := profile.layout_pattern.fullmatch(text))]
    signatures = [
        m
        for text, box in objects
        if _in_footer(box, profile) and (m := profile.page_signature_pattern.fullmatch(text))
    ]
    titled = sorted(
        (
            (text, box)
            for text, box in top
            if _left_of_chart(box, profile)
            and not profile.layout_pattern.fullmatch(text)
            and not profile.data_date_pattern.fullmatch(text)
            and not profile.run_date_pattern.fullmatch(text)
        ),
        key=lambda item: (-item[1].y1, item[1].x0),
    )
    title = " ".join(text for text, _box in titled)
    return _PageMetadata(
        anchors=_anchor_state(objects, profile),
        layout=layouts[0]["value"] if len(layouts) == 1 else None,
        data_date=_one_date(objects, profile.data_date_pattern),
        run_date=_one_date(objects, profile.run_date_pattern),
        title=title if 1 <= len(title) <= profile.title_max_chars else None,
        signature=(
            (int(signatures[0]["n"]), int(signatures[0]["m"])) if len(signatures) == 1 else None
        ),
    )


def validate_full_profile(
    zones: Sequence[PageZones],
    profile: FullScheduleProfile = P6_FULL_V1,
    *,
    expected_data_date: date | None,
) -> ProfileValidation:
    """V11-V13' of contract 5.2 over each page's (collapsed) metadata objects."""
    pages = [_page_metadata(page, profile) for page in zones]
    first = pages[0]
    if (
        first.anchors is _Anchors.MISMATCH
        or not first.complete
        or first.signature is None
        or first.signature[0] != 1
    ):
        raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1)
    issues: list[tuple[ScheduleIssueCode, int | None, ScheduleFieldCode | None]] = []
    count = len(pages)
    for number, page in enumerate(pages, start=1):
        if page.anchors is _Anchors.MISMATCH:
            issues.append((ScheduleIssueCode.HEADER_SIGNATURE_MISMATCH, number, None))
        elif page.anchors is _Anchors.OCCLUDED:
            issues.append(
                (ScheduleIssueCode.HEADER_OD_OCCLUDED, number, ScheduleFieldCode.ORIGINAL_DURATION)
            )
        coherent = (
            page.complete
            and (page.title, page.layout, page.data_date, page.run_date)
            == (first.title, first.layout, first.data_date, first.run_date)
            and page.signature == (number, count)
        )
        if not coherent:
            issues.append((ScheduleIssueCode.PAGE_METADATA_MISMATCH, number, None))
    title = first.title if all(p.title == first.title for p in pages) else None
    data_date = first.data_date if all(p.data_date == first.data_date for p in pages) else None
    run_date = first.run_date if all(p.run_date == first.run_date for p in pages) else None
    if expected_data_date is not None and data_date is not None and data_date != expected_data_date:
        issues.append((ScheduleIssueCode.EXPECTED_DATA_DATE_MISMATCH, None, None))
    return ProfileValidation(title, data_date, run_date, tuple(issues))


# --- 5.5 physical rows -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PdfPhysicalRow:
    page_number: int
    physical_line_ordinal: int
    seed: ProfileTextObject
    #: Ordered by `(x0 + x1, -y1, object_ordinal)`.
    objects: tuple[ProfileTextObject, ...]
    box: ScheduleBox


def _joins_seed(seed: ScheduleBox, obj: ScheduleBox, profile: FullScheduleProfile) -> bool:
    """Contract 5.5 step 3: overlap with the fixed seed interval, ratio 1/2."""
    min_height = min(seed.y1 - seed.y0, obj.y1 - obj.y0)
    if min_height <= 0:
        return False
    intersection = max(0, min(seed.y1, obj.y1) - max(seed.y0, obj.y0))
    ratio = profile.row_overlap_ratio
    return intersection * ratio.denominator >= ratio.numerator * min_height


def _union(boxes: Iterable[ScheduleBox]) -> ScheduleBox:
    items = list(boxes)
    return ScheduleBox(
        min(b.x0 for b in items),
        min(b.y0 for b in items),
        max(b.x1 for b in items),
        max(b.y1 for b in items),
    )


def group_table_rows_by_overlap(
    objects: Iterable[ProfileTextObject],
    *,
    page_number: int,
    profile: FullScheduleProfile = P6_FULL_V1,
) -> tuple[PdfPhysicalRow, ...]:
    """Contract 5.5: fixed-seed bbox-overlap rows; zero-height objects never seed."""
    items = list(objects)
    pool = sorted((o for o in items if o.box.y1 > o.box.y0), key=_pool_key)
    flat = sorted((o for o in items if o.box.y1 == o.box.y0), key=_pool_key)
    groups: list[tuple[ProfileTextObject, list[ProfileTextObject]]] = []
    assigned = [False] * len(pool)
    for index, seed in enumerate(pool):
        if assigned[index]:
            continue
        assigned[index] = True
        members = [seed]
        for other in range(index + 1, len(pool)):
            if not assigned[other] and _joins_seed(seed.box, pool[other].box, profile):
                assigned[other] = True
                members.append(pool[other])
        groups.append((seed, members))
    for obj in flat:
        ordered = sorted(groups, key=lambda group: _pool_key(group[0]))
        host = next(
            (m for s, m in ordered if s.box.y0 <= obj.box.y0 <= s.box.y1),
            None,
        )
        if host is None:
            groups.append((obj, [obj]))
        else:
            host.append(obj)
    groups.sort(key=lambda group: _pool_key(group[0]))
    rows: list[PdfPhysicalRow] = []
    for line, (seed, members) in enumerate(groups, start=1):
        ordered_members = sorted(members, key=lambda o: (o.box.x0 + o.box.x1, -o.box.y1, o.ordinal))
        rows.append(
            PdfPhysicalRow(
                page_number=page_number,
                physical_line_ordinal=line,
                seed=seed,
                objects=tuple(ordered_members),
                box=_union(o.box for o in ordered_members),
            )
        )
    return tuple(rows)


# --- 5.7-5.8 cells ---------------------------------------------------------------


class LabelCase(Enum):
    """Contract 5.7 left-label interpretation of the merged region [37.0, 435.5)."""

    ID_BEARING = "id_bearing"
    SUMMARY = "summary"
    NO_LABEL = "no_label"
    NAME_ONLY = "name_only"
    MIXED = "mixed"


IssueDraft = tuple[ScheduleIssueCode, ScheduleFieldCode | None]


@dataclass(frozen=True, slots=True)
class AssignedRow:
    row: PdfPhysicalRow
    #: The six cells in `ROW_CELL_FIELDS` order.
    cells: tuple[ScheduleCellEvidence, ...]
    original_duration: ScheduleDurationCell
    remaining_duration: ScheduleDurationCell
    start: ScheduleDateCell
    finish: ScheduleDateCell
    label_case: LabelCase
    #: Made `AMBIGUOUS` by sections 5.5-5.7 (classification rule 1).
    row_ambiguous: bool
    issues: tuple[IssueDraft, ...]
    #: The cell field each member object was placed in (`None` = out of grid).
    placement: tuple[tuple[int, ScheduleFieldCode | None], ...]
    #: Real-text objects in the label region, for identity and left edges.
    id_fragments: tuple[ProfileTextObject, ...]
    label_fragments: tuple[ProfileTextObject, ...]


def _label_case(regular_id: bool, bold_id: bool, regular_name: bool, bold_name: bool) -> LabelCase:
    if regular_id and not bold_id and not bold_name:
        return LabelCase.ID_BEARING
    if not regular_id and not regular_name and (bold_id or bold_name):
        return LabelCase.SUMMARY
    if not (regular_id or bold_id or regular_name or bold_name):
        return LabelCase.NO_LABEL
    if regular_name and not regular_id and not bold_id and not bold_name:
        return LabelCase.NAME_ONLY
    return LabelCase.MIXED


def _cells_overlap(fragments: Sequence[ProfileTextObject], profile: FullScheduleProfile) -> bool:
    ordinals = {f.ordinal for f in fragments}
    for i, first in enumerate(fragments):
        # RR1-F04: a suppressed object and its twin in one cell always overlap.
        if first.twin is not None and first.twin in ordinals:
            return True
        for second in fragments[i + 1 :]:
            if _x_intersection(first.box, second.box) > profile.cell_overlap_mpt:
                return True
    return False


def _cell_text(fragments: Sequence[ProfileTextObject]) -> str | None:
    if not fragments:
        return None
    pieces = [normalize_display_text(f.text) for f in fragments if f.text is not None]
    return " ".join(piece for piece in pieces if piece)


def _fragment(obj: ProfileTextObject) -> ScheduleCellFragment:
    return ScheduleCellFragment(
        raw="" if obj.text is None else obj.text,
        box=obj.box,
        font_base_name=obj.source.font_base_name,
        font_size_mpt=obj.source.font_size_mpt,
    )


def assign_full_cells(
    row: PdfPhysicalRow, profile: FullScheduleProfile = P6_FULL_V1
) -> AssignedRow:
    """Contract 5.7-5.8: bands, left-label case, overlap, typed values."""
    issues: list[IssueDraft] = []
    row_ambiguous = False
    if row.box.y1 - row.box.y0 > profile.row_max_span_mpt:
        row_ambiguous = True
        issues.append((ScheduleIssueCode.AMBIGUOUS_CELL, None))
    by_band: dict[int, list[ProfileTextObject]] = {b: [] for b in range(len(ROW_CELL_FIELDS))}
    classes: dict[int, FontClass] = {}
    #: Objects that make whatever cell holds them `AMBIGUOUS` (+ `AMBIGUOUS_CELL`).
    tainting: set[int] = set()
    outside: list[ProfileTextObject] = []
    for obj in row.objects:
        band = band_of(obj.box, profile)
        known = obj.text is not None
        if band is None:
            # Out of the grid: a real-text object makes the row ambiguous; an
            # unknown-text fragment only records the issue (RR3-F02).
            outside.append(obj)
            issues.append((ScheduleIssueCode.AMBIGUOUS_CELL, None))
            row_ambiguous = row_ambiguous or known
            continue
        by_band[band].append(obj)
        cls = font_class(obj.source.font_base_name, profile)
        classes[obj.ordinal] = cls
        if not known or obj.source.unmapped:
            tainting.add(obj.ordinal)
        if known and cls is FontClass.OTHER:
            row_ambiguous = True
            tainting.add(obj.ordinal)

    def real(band: int, cls: FontClass) -> list[ProfileTextObject]:
        return [o for o in by_band[band] if o.text is not None and classes[o.ordinal] is cls]

    regular_id, bold_id = real(_ID_BAND, FontClass.REGULAR), real(_ID_BAND, FontClass.BOLD)
    regular_name, bold_name = real(_NAME_BAND, FontClass.REGULAR), real(_NAME_BAND, FontClass.BOLD)
    case = _label_case(bool(regular_id), bool(bold_id), bool(regular_name), bool(bold_name))
    cell_objects = {band: list(objs) for band, objs in by_band.items()}
    ambiguous_cells: set[int] = set()
    label: list[ProfileTextObject] = []
    if case is LabelCase.SUMMARY:
        # R2 13.4.1: one merged label, never split at 131.0.
        label = sorted([*bold_id, *bold_name], key=lambda o: (o.box.x0, o.ordinal))
        moved = {o.ordinal for o in bold_id}
        cell_objects[_ID_BAND] = [o for o in by_band[_ID_BAND] if o.ordinal not in moved]
        cell_objects[_NAME_BAND] = [*by_band[_NAME_BAND], *bold_id]
    elif case is LabelCase.MIXED:
        row_ambiguous = True
        issues.append((ScheduleIssueCode.AMBIGUOUS_CELL, None))
        ambiguous_cells.update(_LABEL_BANDS)
    elif case is LabelCase.ID_BEARING and len(by_band[_ID_BAND]) > 1:
        ambiguous_cells.add(_ID_BAND)  # D-11: identity is never assembled from pieces
    cells: list[ScheduleCellEvidence] = []
    durations: dict[int, ScheduleDurationCell] = {}
    dates: dict[int, ScheduleDateCell] = {}
    placement: list[tuple[int, ScheduleFieldCode | None]] = []
    for band, field_code in enumerate(ROW_CELL_FIELDS):
        fragments = sorted(cell_objects[band], key=lambda o: (o.box.x0, o.ordinal))
        placement.extend((o.ordinal, field_code) for o in fragments)
        text = _cell_text(fragments)
        state = ScheduleCellState.PUBLISHED_BLANK
        if fragments:
            state = ScheduleCellState.PUBLISHED_VALUE
            if any(o.ordinal in tainting for o in fragments):
                state = ScheduleCellState.AMBIGUOUS
                issues.append((ScheduleIssueCode.AMBIGUOUS_CELL, field_code))
            if _cells_overlap(fragments, profile):
                state = ScheduleCellState.AMBIGUOUS
                issues.append((ScheduleIssueCode.OVERLAPPING_CELL_TEXT, field_code))
            if band in ambiguous_cells:
                state = ScheduleCellState.AMBIGUOUS
        if band in _DURATION_BANDS:
            state, durations[band] = _typed_duration(field_code, state, text, issues)
        elif band in _DATE_BANDS:
            state, dates[band] = _typed_date(field_code, state, text, issues)
        cells.append(
            ScheduleCellEvidence(field_code, state, text, tuple(_fragment(o) for o in fragments))
        )
    placement.extend((o.ordinal, None) for o in outside)
    return AssignedRow(
        row=row,
        cells=tuple(cells),
        original_duration=durations[2],
        remaining_duration=durations[3],
        start=dates[4],
        finish=dates[5],
        label_case=case,
        row_ambiguous=row_ambiguous,
        issues=tuple(issues),
        placement=tuple(placement),
        id_fragments=tuple(regular_id),
        label_fragments=tuple(label),
    )


_DURATION_BANDS: Final = frozenset({2, 3})
_DATE_BANDS: Final = frozenset({4, 5})


def _typed_duration(
    field_code: ScheduleFieldCode,
    state: ScheduleCellState,
    text: str | None,
    issues: list[IssueDraft],
) -> tuple[ScheduleCellState, ScheduleDurationCell]:
    if state is not ScheduleCellState.PUBLISHED_VALUE or text is None:
        return state, ScheduleDurationCell(state, None)
    value = parse_profile_duration(text)
    if value is None:
        issues.append((ScheduleIssueCode.INVALID_DURATION, field_code))
        failed = ScheduleCellState.EXTRACTION_FAILED
        return failed, ScheduleDurationCell(failed, None)
    return state, ScheduleDurationCell(state, value)


def _typed_date(
    field_code: ScheduleFieldCode,
    state: ScheduleCellState,
    text: str | None,
    issues: list[IssueDraft],
) -> tuple[ScheduleCellState, ScheduleDateCell]:
    if state is not ScheduleCellState.PUBLISHED_VALUE or text is None:
        return state, ScheduleDateCell(state, None, None)
    parsed = parse_profile_date(text)
    if parsed is None:
        issues.append((ScheduleIssueCode.INVALID_DATE, field_code))
        failed = ScheduleCellState.EXTRACTION_FAILED
        return failed, ScheduleDateCell(failed, None, None)
    return state, ScheduleDateCell(state, parsed[0], parsed[1])


# --- 5.9-5.10 wrap and classification ---------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    assigned: AssignedRow
    row_ordinal: int
    row_type: ScheduleRowType
    published_activity_id: str | None
    activity_name: str | None
    #: Contract 5.11 left edge (ID fragment or merged label), for eligible rows.
    left_edge: int | None
    issues: tuple[IssueDraft, ...]

    @property
    def row(self) -> PdfPhysicalRow:
        return self.assigned.row


def _is_wrap(
    row: PdfPhysicalRow, previous: PdfPhysicalRow | None, profile: FullScheduleProfile
) -> bool:
    """Contract 5.9 (D-21); unknown-text fragments are ignored by every condition."""
    if previous is None or previous.box.y1 - row.box.y1 >= profile.wrap_pitch_mpt:
        return False
    real = [(o, band_of(o.box, profile)) for o in row.objects if o.text is not None]
    regular_id = any(
        band == _ID_BAND and font_class(o.source.font_base_name, profile) is FontClass.REGULAR
        for o, band in real
    )
    values = any(band in _VALUE_BANDS for _o, band in real)
    label = any(band in _LABEL_BANDS for _o, band in real)
    return not regular_id and not values and label


def classify_full_row(
    assigned: AssignedRow,
    previous: PdfPhysicalRow | None,
    profile: FullScheduleProfile = P6_FULL_V1,
    *,
    row_ordinal: int = 1,
) -> ClassifiedRow:
    """Contract 5.9 then 5.10 (first match wins)."""
    issues = list(assigned.issues)
    ambiguous = ScheduleRowType.AMBIGUOUS

    def result(
        row_type: ScheduleRowType,
        *extra: IssueDraft,
        activity_id: str | None = None,
        name: str | None = None,
        left_edge: int | None = None,
    ) -> ClassifiedRow:
        return ClassifiedRow(
            assigned=assigned,
            row_ordinal=row_ordinal,
            row_type=row_type,
            published_activity_id=activity_id,
            activity_name=name,
            left_edge=left_edge,
            issues=(*issues, *extra),
        )

    if _is_wrap(assigned.row, previous, profile):
        return result(ambiguous, (ScheduleIssueCode.ROW_WRAP_UNSUPPORTED, None))
    if assigned.row_ambiguous:
        return result(ambiguous)
    cells = assigned.cells
    id_cell, name_cell = cells[0], cells[1]
    value = ScheduleCellState.PUBLISHED_VALUE
    blank = ScheduleCellState.PUBLISHED_BLANK
    unknown_cell = (ScheduleIssueCode.AMBIGUOUS_CELL, None)
    case = assigned.label_case
    if case is LabelCase.ID_BEARING:
        if id_cell.state is not value or name_cell.state is not value:
            first = next(c.field for c in (id_cell, name_cell) if c.state is not value)
            return result(ambiguous, (ScheduleIssueCode.AMBIGUOUS_CELL, first))
        id_fragment = assigned.id_fragments[0]
        activity_id = normalize_activity_id(id_fragment.text or "")
        od, rd = assigned.original_duration, assigned.remaining_duration
        row_type = ScheduleRowType.ACTIVITY
        if od.value == 0 and rd.value == 0 and od.state is value and rd.state is value:
            states = {assigned.start.state, assigned.finish.state}
            if states != {value, blank}:
                return result(ambiguous, unknown_cell)
            row_type = ScheduleRowType.MILESTONE
        return result(
            row_type,
            activity_id=activity_id,
            name=name_cell.text,
            left_edge=id_fragment.box.x0,
        )
    values = cells[2:]
    if case is LabelCase.SUMMARY:
        if name_cell.state is ScheduleCellState.AMBIGUOUS:
            return result(ambiguous, unknown_cell)
        if all(c.state is blank for c in values):
            return result(ambiguous, unknown_cell)  # D-32
        return result(
            ScheduleRowType.WBS_SUMMARY,
            name=name_cell.text,
            left_edge=min(o.box.x0 for o in assigned.label_fragments),
        )
    real_values = any(
        o.text is not None and band_of(o.box, profile) in _VALUE_BANDS for o in assigned.row.objects
    )
    if (case is LabelCase.NO_LABEL and real_values) or case is LabelCase.NAME_ONLY:
        missing = (ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID, ScheduleFieldCode.ACTIVITY_ID)
        return result(ambiguous, missing)
    return result(ambiguous, unknown_cell)


# --- 5.11 hierarchy ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HierarchyAssignment:
    row_type: ScheduleRowType
    indent_level: int | None
    parent_row_ordinal: int | None
    hierarchy_path: tuple[str, ...] | None
    ambiguous: bool


_SUMMARY_TYPES: Final = frozenset({ScheduleRowType.WBS_SUMMARY, ScheduleRowType.PROJECT_SUMMARY})
_LINKABLE_TYPES: Final = frozenset({ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE})


def _clusters(edges: Iterable[int], profile: FullScheduleProfile) -> list[list[int]]:
    """Fixed-seed clustering of the sorted left edges (contract 5.11 step 2)."""
    clusters: list[list[int]] = []
    for edge in sorted(edges):
        if clusters and edge - clusters[-1][0] <= profile.indent_tolerance_mpt:
            clusters[-1].append(edge)
        else:
            clusters.append([edge])
    return clusters


def reconstruct_full_hierarchy(
    rows: Sequence[ClassifiedRow],
    profile: FullScheduleProfile,
    limits: ScheduleParseLimits,
) -> tuple[HierarchyAssignment, ...]:
    """Contract 5.11 over the whole publication; one stack across pages."""
    edges = {
        index: row.left_edge
        for index, row in enumerate(rows)
        if row.row_type in _SUMMARY_TYPES | _LINKABLE_TYPES and row.left_edge is not None
    }
    clusters = _clusters(edges.values(), profile)
    if len(clusters) > limits.max_hierarchy_depth:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    centroids = [Fraction(sum(c), len(c)) for c in clusters]
    separation = profile.indent_min_separation_mpt
    determinate_cluster = [
        (i == 0 or centroids[i] - centroids[i - 1] >= separation)
        and (i == len(centroids) - 1 or centroids[i + 1] - centroids[i] >= separation)
        for i in range(len(centroids))
    ]
    rank = {edge: index for index, cluster in enumerate(clusters) for edge in cluster}
    stack: list[tuple[int, int]] = []  # (level, index into rows)
    level_of: dict[int, int] = {}
    determinate: dict[int, bool] = {}
    parent_of: dict[int, int | None] = {}
    for index, row in enumerate(rows):
        if index not in edges:
            continue
        level = rank[edges[index]]
        level_of[index] = level
        summary = row.row_type in _SUMMARY_TYPES
        parent: int | None
        if summary:
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            stack.append((level, index))
        else:
            parent = next((entry for lv, entry in reversed(stack) if lv < level), None)
        parent_of[index] = parent
        if parent is None:
            linked = summary and level == 0
        else:
            linked = level_of[parent] == level - 1 and determinate[parent]
        determinate[index] = determinate_cluster[level] and linked
    assignments: list[HierarchyAssignment] = []
    first_summary = next(
        (i for i, r in enumerate(rows) if i in level_of and r.row_type in _SUMMARY_TYPES), None
    )
    for index, row in enumerate(rows):
        if index not in level_of:
            assignments.append(HierarchyAssignment(row.row_type, None, None, None, False))
            continue
        level = level_of[index]
        row_type = row.row_type
        if not determinate[index]:
            kept_level = level if determinate_cluster[level] else None
            assignments.append(HierarchyAssignment(row_type, kept_level, None, None, True))
            continue
        path: list[str] = []
        cursor = parent_of[index]
        while cursor is not None:
            path.append(rows[cursor].activity_name or "")
            cursor = parent_of[cursor]
        parent = parent_of[index]
        if index == first_summary and level == 0:
            row_type = ScheduleRowType.PROJECT_SUMMARY
        assignments.append(
            HierarchyAssignment(
                row_type,
                level,
                None if parent is None else rows[parent].row_ordinal,
                tuple(reversed(path)),
                False,
            )
        )
    return tuple(assignments)


# --- 5.1 pipeline, 5.12-5.14 identity, issues, bounds -----------------------------


_FIELD_ORDER: Final = {code: index for index, code in enumerate(ScheduleFieldCode)}
_CODE_ORDER: Final = {code: index for index, code in enumerate(ScheduleIssueCode)}

IssueKey = tuple[ScheduleIssueCode, int | None, int | None, ScheduleFieldCode | None]


def _issue_sort_key(key: IssueKey) -> tuple[int, int, int, int]:
    code, page, row, field_code = key
    return (
        page or 0,
        row or 0,
        _CODE_ORDER[code],
        -1 if field_code is None else _FIELD_ORDER[field_code],
    )


def _issue(key: IssueKey) -> ScheduleParseIssue:
    code, page, row, field_code = key
    return ScheduleParseIssue(code, ISSUE_SEVERITY[code], page, row, field_code)


@dataclass(frozen=True, slots=True)
class _Header:
    document_sha256: str
    document_size_bytes: int
    engine: ScheduleParseEngine


def _result(
    header: _Header,
    outcome: SchedulePublicationStatus,
    *,
    issues: tuple[ScheduleParseIssue, ...],
    rows: tuple[ParsedScheduleRow, ...] = (),
    counts: dict[str, int] | None = None,
    validation: ProfileValidation | None = None,
) -> ScheduleParseResult:
    by_type = {t: sum(1 for r in rows if r.row_type is t) for t in ScheduleRowType}
    extra = counts or {}
    return ScheduleParseResult(
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        document_sha256=header.document_sha256,
        document_size_bytes=header.document_size_bytes,
        outcome=outcome,
        published_schedule_title=None if validation is None else validation.title,
        data_date=None if validation is None else validation.data_date,
        run_date=None if validation is None else validation.run_date,
        counts=ScheduleParseCounts(
            pages=extra.get("pages", 0),
            rows=len(rows),
            project_summaries=by_type[ScheduleRowType.PROJECT_SUMMARY],
            wbs_summaries=by_type[ScheduleRowType.WBS_SUMMARY],
            activities=by_type[ScheduleRowType.ACTIVITY],
            milestones=by_type[ScheduleRowType.MILESTONE],
            ambiguous=by_type[ScheduleRowType.AMBIGUOUS],
            chart_objects_excluded=extra.get("chart_objects_excluded", 0),
            watermark_objects_excluded=extra.get("watermark_objects_excluded", 0),
            suppressed_objects=extra.get("suppressed_objects", 0),
            duplicate_objects_collapsed=extra.get("duplicate_objects_collapsed", 0),
            non_embedded_font_objects=extra.get("non_embedded_font_objects", 0),
            issues=len(issues),
            warnings=sum(1 for i in issues if i.severity is ScheduleIssueSeverity.WARNING),
        ),
        rows=rows,
        issues=issues,
        engine=header.engine,
    )


def _failed(header: _Header, refusal: ScheduleParseRefusal) -> ScheduleParseResult:
    """D-16: a failed parse carries no rows and exactly its one refusal issue."""
    page = refusal.page_number if refusal.code is ScheduleIssueCode.UNSUPPORTED_LAYOUT else None
    issue = _issue((refusal.code, page, None, None))
    return _result(header, SchedulePublicationStatus.FAILED, issues=(issue,))


def parse_full_schedule(
    data: bytes,
    *,
    expected_data_date: date | None = None,
    limits: ScheduleParseLimits = PRODUCTION_LIMITS,
    clock: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
) -> ScheduleParseResult:
    """Parse one admitted Full-Schedule PDF (contract 5.1); the only entry point.

    Returns a result for every `bytes` input. Raises only `TypeError` for a
    non-`bytes` argument and lets `MemoryError` (and `BaseException`s such as
    `KeyboardInterrupt`) through; every other condition is a closed issue.
    """
    if not isinstance(data, bytes):
        raise TypeError("parse_full_schedule takes the admitted bytes")
    header = _Header(hashlib.sha256(data).hexdigest(), len(data), engine_provenance())
    budget = ParseBudget(clock, deadline)
    try:
        return _parse(data, header, expected_data_date, limits, budget, P6_FULL_V1)
    except ScheduleParseRefusal as refusal:
        return _failed(header, refusal)
    except MemoryError:
        raise
    except Exception:
        return _failed(header, ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION))


def _parse(
    data: bytes,
    header: _Header,
    expected_data_date: date | None,
    limits: ScheduleParseLimits,
    budget: ParseBudget,
    profile: FullScheduleProfile,
) -> ScheduleParseResult:
    document = extract_pdf_text_objects(data, limits=limits, budget=budget)
    budget.checkpoint()
    counts = {
        "pages": document.page_count,
        "chart_objects_excluded": 0,
        "watermark_objects_excluded": 0,
        "suppressed_objects": 0,
        "duplicate_objects_collapsed": 0,
        "non_embedded_font_objects": sum(
            1 for page in document.pages for o in page.objects if not o.font_embedded
        ),
    }
    keys: list[IssueKey] = []
    zones: list[PageZones] = []
    table_sets: list[DuplicateResolution] = []
    for page in document.pages:
        zone = exclude_profile_non_data(page, profile)
        metadata = collapse_duplicate_objects(zone.metadata_objects, profile)
        table = collapse_duplicate_objects(zone.table_objects, profile)
        counts["chart_objects_excluded"] += zone.chart_excluded
        counts["watermark_objects_excluded"] += zone.watermark_excluded
        counts["suppressed_objects"] += zone.suppressed
        counts["duplicate_objects_collapsed"] += len(metadata.collapsed) + len(table.collapsed)
        keys.extend(
            (ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED, page.page_number, None, None)
            for _ in metadata.collapsed
        )
        zones.append(replace(zone, metadata_objects=metadata.kept))
        table_sets.append(table)
    validation = validate_full_profile(zones, profile, expected_data_date=expected_data_date)
    keys.extend((code, page, None, field_code) for code, page, field_code in validation.issues)
    classified: list[ClassifiedRow] = []
    dimensions: dict[int, tuple[int, int]] = {}
    for page, table in zip(document.pages, table_sets, strict=True):
        budget.checkpoint()
        physical = group_table_rows_by_overlap(
            table.kept, page_number=page.page_number, profile=profile
        )
        if len(classified) + len(physical) > limits.max_rows:
            raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
        dimensions[page.page_number] = (page.width_mpt, page.height_mpt)
        previous: PdfPhysicalRow | None = None
        page_rows: list[ClassifiedRow] = []
        for row in physical:
            assigned = assign_full_cells(row, profile)
            page_rows.append(
                classify_full_row(
                    assigned, previous, profile, row_ordinal=len(classified) + len(page_rows) + 1
                )
            )
            previous = row
        classified.extend(page_rows)
        keys.extend(_collapse_keys(page.page_number, table, page_rows))
    budget.checkpoint()
    hierarchy = reconstruct_full_hierarchy(classified, profile, limits)
    for entry, assignment in zip(classified, hierarchy, strict=True):
        keys.extend(
            (code, entry.row.page_number, entry.row_ordinal, field_code)
            for code, field_code in entry.issues
        )
        if assignment.ambiguous:
            keys.append(
                (
                    ScheduleIssueCode.HIERARCHY_AMBIGUOUS,
                    entry.row.page_number,
                    entry.row_ordinal,
                    ScheduleFieldCode.HIERARCHY,
                )
            )
    keys.extend(_duplicate_id_keys(classified, hierarchy))
    budget.checkpoint()
    unique = sorted(set(keys), key=_issue_sort_key)
    if len(unique) > limits.max_issues:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    issues = tuple(_issue(key) for key in unique)
    rows = tuple(
        _parsed_row(row, assignment, issues, dimensions, limits)
        for row, assignment in zip(classified, hierarchy, strict=True)
    )
    outcome = derive_outcome(issues, rows)
    return _result(header, outcome, issues=issues, rows=rows, counts=counts, validation=validation)


def _collapse_keys(
    page_number: int, table: DuplicateResolution, rows: Sequence[ClassifiedRow]
) -> list[IssueKey]:
    """Table-set collapse warnings carry the kept object's row and cell field."""
    where: dict[int, tuple[int, ScheduleFieldCode | None]] = {}
    for row in rows:
        for ordinal, field_code in row.assigned.placement:
            where[ordinal] = (row.row_ordinal, field_code)
    keys: list[IssueKey] = []
    for _collapsed, kept in table.collapsed:
        row_ordinal, field_code = where[kept.ordinal]
        keys.append(
            (
                ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED,
                page_number,
                row_ordinal,
                field_code,
            )
        )
    return keys


def _duplicate_id_keys(
    rows: Sequence[ClassifiedRow], hierarchy: Sequence[HierarchyAssignment]
) -> list[IssueKey]:
    """Contract 5.12: every occurrence of a repeated published ID; no winner."""
    seen: dict[str, int] = {}
    linkable = [
        row
        for row, assignment in zip(rows, hierarchy, strict=True)
        if assignment.row_type in _LINKABLE_TYPES and row.published_activity_id is not None
    ]
    for row in linkable:
        identity = row.published_activity_id or ""
        seen[identity] = seen.get(identity, 0) + 1
    return [
        (
            ScheduleIssueCode.DUPLICATE_ACTIVITY_ID,
            row.row.page_number,
            row.row_ordinal,
            ScheduleFieldCode.ACTIVITY_ID,
        )
        for row in linkable
        if seen[row.published_activity_id or ""] > 1
    ]


def _parsed_row(
    row: ClassifiedRow,
    assignment: HierarchyAssignment,
    issues: Sequence[ScheduleParseIssue],
    dimensions: dict[int, tuple[int, int]],
    limits: ScheduleParseLimits,
) -> ParsedScheduleRow:
    codes = {i.code for i in issues if i.row_ordinal == row.row_ordinal}
    warning_codes = tuple(code for code in ScheduleIssueCode if code in codes)
    if len(warning_codes) > limits.max_row_warnings:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    assigned = row.assigned
    width, height = dimensions[row.row.page_number]
    linkable = assignment.row_type in _LINKABLE_TYPES
    summary = assignment.row_type in _SUMMARY_TYPES
    parsed = ParsedScheduleRow(
        row_ordinal=row.row_ordinal,
        page_number=row.row.page_number,
        physical_line_ordinal=row.row.physical_line_ordinal,
        row_type=assignment.row_type,
        indent_level=assignment.indent_level,
        parent_row_ordinal=assignment.parent_row_ordinal,
        hierarchy_path=assignment.hierarchy_path,
        published_activity_id=row.published_activity_id if linkable else None,
        activity_name=row.activity_name if linkable or summary else None,
        original_duration=assigned.original_duration,
        remaining_duration=assigned.remaining_duration,
        start=assigned.start,
        finish=assigned.finish,
        box=row.row.box,
        page_width_mpt=width,
        page_height_mpt=height,
        cells=assigned.cells,
        warning_codes=warning_codes,
    )
    if len(cell_evidence_bytes(parsed)) > limits.max_cell_evidence_bytes:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    return parsed
