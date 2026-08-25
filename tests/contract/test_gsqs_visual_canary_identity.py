"""Fail-closed ordinal-1 identity checks for visual canaries."""

from __future__ import annotations

import importlib.util
import json
import sys
import zlib
from hashlib import sha256
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops/goodnotes/gsqs/b0/verify_visual_canary_identity.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_visual_canary_identity", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")


def grayscale_png(width: int, height: int, fill: int = 255) -> bytes:
    pixels = bytes([fill]) * (width * height)
    raw = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_session(
    tmp_path: Path, payload: bytes, *, staged_name: str = "syn-b-001.png"
) -> tuple[Path, Path, Path]:
    source = tmp_path / "source.png"
    staged = tmp_path / "rasters" / staged_name
    manifest = tmp_path / "manifest.json"
    staged.parent.mkdir()
    source.write_bytes(payload)
    staged.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "syn-b-001",
                        "ordinal": 1,
                        "staged_filename": staged_name,
                        "content_sha256": digest,
                        "byte_length": len(payload),
                    }
                ]
            }
        )
    )
    return source, staged, manifest


def test_require_visual_canary_identity_accepts_large_matching_png(tmp_path: Path) -> None:
    module = _load_module()
    payload = grayscale_png(1000, 250)
    source, staged, manifest = _write_session(tmp_path, payload)
    report = module.require_visual_canary_identity(
        source=source, staged=staged, manifest_path=manifest
    )
    assert report["source"]["width"] == 1000
    assert report["source"]["height"] == 250
    assert report["source"]["sha256"] == report["staged"]["sha256"]
    assert report["manifest"]["content_sha256"] == report["staged"]["sha256"]


def test_require_visual_canary_identity_rejects_8x8_fixture(tmp_path: Path) -> None:
    module = _load_module()
    payload = grayscale_png(8, 8)
    source, staged, manifest = _write_session(tmp_path, payload)
    with pytest.raises(module.VisualCanaryIdentityError, match="below 1000x250"):
        module.require_visual_canary_identity(source=source, staged=staged, manifest_path=manifest)
