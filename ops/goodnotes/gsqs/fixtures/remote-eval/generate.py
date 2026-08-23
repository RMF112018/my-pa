"""Deterministic synthetic Partition-B rasters for remote-eval Phase A.

Writes tiny unique 8x8 grayscale PNGs into an explicit output directory.
Gold and labels stay in memory for scoring; they are never written into a
session spool. Invoke with an explicit output path; no-args is fail-closed.
"""

from __future__ import annotations

import argparse
import sys
import zlib
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs import CorpusPartition, Geometry, GoldRegion
from my_pa.application.goodnotes_gsqs_corpus import (
    FIXTURE_SYNTHETIC_NON_PERSONAL,
    CorpusCase,
    LabelProvenance,
    ReviewState,
    SourceLayer,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ManifestCase,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

CASE_COUNT = CASES_PER_REPETITION
CASE_IDS = tuple(f"syn-b-{index:03d}" for index in range(1, CASE_COUNT + 1))
CORPUS_VERSION = "gsqs-remote-eval-synthetic-canary-v1"
GENERATOR_VERSION = "gsqs-remote-eval-synthetic-canary-v1"
ANALYZER_ID = "gsqs-remote-eval-synthetic"
ANALYZER_VERSION = "phase-a"
CONTEXT_GEOMETRY = Geometry(x_min=0.08, y_min=0.08, width=0.84, height=0.10)
SYNTHETIC_SEGMENTS: tuple[dict[str, object], ...] = (
    {
        "kind": "SOURCE_CONTEXT",
        "geometry": {
            "x_min": CONTEXT_GEOMETRY.x_min,
            "y_min": CONTEXT_GEOMETRY.y_min,
            "width": CONTEXT_GEOMETRY.width,
            "height": CONTEXT_GEOMETRY.height,
        },
    },
)


def case_id_for(ordinal: int) -> str:
    if not 1 <= ordinal <= CASE_COUNT:
        raise ValueError("ordinal must be 1..73")
    return CASE_IDS[ordinal - 1]


def gray_png(marker: int) -> bytes:
    width = height = 8
    pixels = bytes((marker + index) % 256 for index in range(width * height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    raw = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def png_for_ordinal(ordinal: int) -> bytes:
    return gray_png(ordinal)


def png_and_manifest_case(ordinal: int) -> tuple[bytes, ManifestCase]:
    case_id = case_id_for(ordinal)
    payload = png_for_ordinal(ordinal)
    return payload, ManifestCase(
        ordinal=ordinal,
        case_id=case_id,
        content_sha256=sha256(payload).hexdigest(),
        byte_length=len(payload),
        staged_filename=f"{case_id}.png",
    )


def manifest_cases() -> tuple[ManifestCase, ...]:
    return tuple(png_and_manifest_case(ordinal)[1] for ordinal in range(1, CASE_COUNT + 1))


def synthetic_gold_region(ordinal: int) -> GoldRegion:
    return GoldRegion(
        region_id=f"src-{ordinal:03d}",
        kind=GoodNotesSegmentKind.SOURCE_CONTEXT,
        geometry=CONTEXT_GEOMETRY,
        transcription=f"SYNTHETIC CONTEXT {ordinal:03d}",
    )


def synthetic_corpus_case(ordinal: int, png_bytes: bytes | None = None) -> CorpusCase:
    payload, manifest = png_and_manifest_case(ordinal)
    page = payload if png_bytes is None else png_bytes
    digest = sha256(page).hexdigest()
    if png_bytes is not None and digest != manifest.content_sha256:
        raise ValueError("png bytes do not match the deterministic canary")
    return CorpusCase(
        case_id=manifest.case_id,
        corpus_version=CORPUS_VERSION,
        content_sha256=digest,
        renderer_name="gsqs-remote-eval-synthetic",
        renderer_version="1",
        render_profile_version="gray-png-8x8-v1",
        fixture_classification=FIXTURE_SYNTHETIC_NON_PERSONAL,
        provenance="SYNTHETIC_CANARY",
        regions=(synthetic_gold_region(ordinal),),
        difficulty=("nominal",),
        scenario="synthetic-canary",
        adversarial=False,
        label_provenance=LabelProvenance.SYNTHETIC_DETERMINISTIC,
        review_state=ReviewState.APPROVED,
        partition=CorpusPartition.B,
        page_bytes=page,
        leakage_group_id=f"lg-{manifest.case_id}",
        source_layer=SourceLayer.SYNTHETIC_REGRESSION,
    )


def synthetic_corpus_cases(
    png_by_id: Mapping[str, bytes] | None = None,
) -> tuple[CorpusCase, ...]:
    cases: list[CorpusCase] = []
    for ordinal in range(1, CASE_COUNT + 1):
        case_id = case_id_for(ordinal)
        payload = None if png_by_id is None else png_by_id.get(case_id)
        cases.append(synthetic_corpus_case(ordinal, payload))
    return tuple(cases)


def synthetic_segments() -> list[dict[str, object]]:
    return [dict(item) for item in SYNTHETIC_SEGMENTS]


def write_rasters(output_dir: Path) -> tuple[ManifestCase, ...]:
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[ManifestCase] = []
    for ordinal in range(1, CASE_COUNT + 1):
        payload, case = png_and_manifest_case(ordinal)
        (dest / case.staged_filename).write_bytes(payload)
        written.append(case)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gsqs-remote-eval-generate",
        description="Write 73 synthetic remote-eval PNG rasters to an explicit directory.",
    )
    parser.add_argument(
        "output_dir",
        help="directory that will receive syn-b-001.png .. syn-b-073.png",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    write_rasters(Path(args.output_dir))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("output_dir is required", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
