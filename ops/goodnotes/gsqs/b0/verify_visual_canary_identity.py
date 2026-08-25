"""Fail-closed identity checks for a GSQS visual-canary ordinal-1 raster.

Stdlib only. Never prints PNG bytes or token values. Used by commissioning
preparation; not part of the evaluator implementation digest.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_CANARY_WIDTH = 1000
MIN_CANARY_HEIGHT = 250


@dataclass(frozen=True)
class PngIdentity:
    path: str
    byte_length: int
    sha256: str
    width: int
    height: int
    bit_depth: int
    color_type: int
    regular_file: bool
    symlink: bool
    text_chunk_count: int


class VisualCanaryIdentityError(ValueError):
    """Ordinal-1 raster identity failed a fail-closed check."""


def inspect_png(path: Path) -> PngIdentity:
    if not path.exists():
        raise VisualCanaryIdentityError(f"missing raster: {path}")
    symlink = path.is_symlink()
    if symlink or not path.is_file():
        raise VisualCanaryIdentityError(f"raster is not a regular file: {path}")
    payload = path.read_bytes()
    if not payload.startswith(PNG_MAGIC):
        raise VisualCanaryIdentityError(f"raster is not a PNG: {path}")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[16:26])
    return PngIdentity(
        path=str(path),
        byte_length=len(payload),
        sha256=sha256(payload).hexdigest(),
        width=width,
        height=height,
        bit_depth=bit_depth,
        color_type=color_type,
        regular_file=True,
        symlink=False,
        text_chunk_count=_text_chunk_count(payload),
    )


def _text_chunk_count(payload: bytes) -> int:
    offset = 8
    count = 0
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        tag = payload[offset + 4 : offset + 8]
        if tag in {b"tEXt", b"zTXt", b"iTXt"}:
            count += 1
        offset += 12 + length
        if tag == b"IEND":
            break
    return count


def first_manifest_case(manifest: Mapping[str, object]) -> Mapping[str, object]:
    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise VisualCanaryIdentityError("manifest has no cases")
    first = cases[0]
    if not isinstance(first, dict):
        raise VisualCanaryIdentityError("manifest case 0 is invalid")
    return first


def require_visual_canary_identity(
    *,
    source: Path,
    staged: Path,
    manifest_path: Path,
    min_width: int = MIN_CANARY_WIDTH,
    min_height: int = MIN_CANARY_HEIGHT,
) -> dict[str, object]:
    source_id = inspect_png(source)
    staged_id = inspect_png(staged)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = first_manifest_case(manifest)
    content_sha256 = case.get("content_sha256")
    byte_length = case.get("byte_length")
    staged_filename = case.get("staged_filename")
    ordinal = case.get("ordinal")
    failures: list[str] = []
    if ordinal not in {1, "1"}:
        failures.append("manifest ordinal 1 is not first")
    if staged_filename != staged.name:
        failures.append("manifest staged_filename does not match staged path")
    if source_id.sha256 != staged_id.sha256:
        failures.append("source SHA does not match staged SHA")
    if staged_id.sha256 != content_sha256:
        failures.append("staged SHA does not match manifest content_sha256")
    if source_id.byte_length != byte_length or staged_id.byte_length != byte_length:
        failures.append("byte_length does not match manifest")
    if staged_id.width < min_width or staged_id.height < min_height:
        failures.append(
            f"ordinal-1 dimensions {staged_id.width}x{staged_id.height} "
            f"below {min_width}x{min_height}"
        )
    if source_id.width != staged_id.width or source_id.height != staged_id.height:
        failures.append("source dimensions do not match staged dimensions")
    if failures:
        raise VisualCanaryIdentityError("; ".join(failures))
    return {
        "source": asdict(source_id),
        "staged": asdict(staged_id),
        "manifest": {
            "case_id": case.get("case_id"),
            "ordinal": ordinal,
            "staged_filename": staged_filename,
            "content_sha256": content_sha256,
            "byte_length": byte_length,
        },
        "min_width": min_width,
        "min_height": min_height,
    }
