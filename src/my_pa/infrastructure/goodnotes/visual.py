"""Pinned pdfium visual page identity. Raw PDF bytes are never the identity.

Profile `pdfium-normalized-v1`:
- rasterize a single-page PDF (or JPEG wrapped as one) at scale 2.0 (144 DPI)
  with path/text/image smoothing disabled and a white fill;
- convert the pinned bitmap to packed 8-bit grayscale;
- exact digest hashes those unnormalized pixels plus width and height;
- normalized digest hashes a nearest-neighbour resize whose long edge is 256;
- perceptual identity is a 64-bit horizontal dHash hex string.

PNG page bytes are decoded with the standard library (no Pillow) into the same
grayscale pipeline. JPEG page bytes are wrapped as a one-page PDF and rasterized
by the same pdfium profile. Empty or invalid input fails closed.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pypdfium2 import PDFIUM_INFO, PYPDFIUM_INFO

from my_pa.domain.goodnotes.models import MAX_GOODNOTES_RASTER_BYTES, PageRender
from my_pa.domain.goodnotes.page_crop import (
    PNG_MAGIC,
    crop_normalized_png,
    dhash_hex,
    grayscale_from_png,
    nearest_resize,
    raster_digest,
)
from my_pa.infrastructure.goodnotes.pdf import jpeg_as_single_page_pdf, open_admitted_pdf

PDFIUM_NORMALIZED_NAME = "pypdfium2"
PDFIUM_NORMALIZED_PROFILE = "pdfium-normalized-v1"
RENDER_SCALE = 2.0
NORMALIZED_LONG_EDGE = 256
PERCEPTUAL_ALGORITHM = "dhash"
PERCEPTUAL_ALGORITHM_VERSION = "1"

__all__ = [
    "PDFIUM_NORMALIZED_NAME",
    "PDFIUM_NORMALIZED_PROFILE",
    "PdfiumNormalizedRenderer",
    "crop_normalized_png",
    "grayscale_png",
    "production_page_renderer",
]


@dataclass(frozen=True, slots=True)
class PdfiumNormalizedRenderer:
    """Production durable-note renderer. Visual identity, not raw representation bytes."""

    name: str = PDFIUM_NORMALIZED_NAME
    profile_version: str = PDFIUM_NORMALIZED_PROFILE

    @property
    def version(self) -> str:
        return _renderer_version()

    def render(self, page_bytes: bytes) -> PageRender:
        render, _png = self.render_png(page_bytes)
        return render

    def render_png(self, page_bytes: bytes) -> tuple[PageRender, bytes]:
        """Pinned visual identity plus the PNG encoding of that grayscale raster."""
        if not page_bytes:
            raise ValueError("a GoodNotes page render requires admitted bytes")
        pixels, width, height = _grayscale_raster(page_bytes)
        exact = raster_digest(pixels, width, height)
        norm_pixels, norm_width, norm_height = _normalize(pixels, width, height)
        normalized = raster_digest(norm_pixels, norm_width, norm_height)
        png = grayscale_png(pixels, width, height)
        if len(png) > MAX_GOODNOTES_RASTER_BYTES:
            raise ValueError("GoodNotes visual raster exceeds the admitted size cap")
        return (
            PageRender(
                exact_render_sha256=exact,
                normalized_render_sha256=normalized,
                renderer_name=self.name,
                renderer_version=self.version,
                render_profile_version=self.profile_version,
                perceptual_hash=dhash_hex(pixels, width, height),
                perceptual_algorithm=PERCEPTUAL_ALGORITHM,
                perceptual_algorithm_version=PERCEPTUAL_ALGORITHM_VERSION,
                width=width,
                height=height,
            ),
            png,
        )


def production_page_renderer() -> PdfiumNormalizedRenderer:
    return PdfiumNormalizedRenderer()


def grayscale_png(pixels: bytes, width: int, height: int) -> bytes:
    """Encode packed 8-bit grayscale pixels as a deterministic non-interlaced PNG."""
    if width < 1 or height < 1 or len(pixels) != width * height:
        raise ValueError("grayscale raster size does not match dimensions")

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    raw = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    return (
        PNG_MAGIC
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _renderer_version() -> str:
    return f"{PYPDFIUM_INFO}+pdfium-{PDFIUM_INFO}"


def _grayscale_raster(page_bytes: bytes) -> tuple[bytes, int, int]:
    if page_bytes.startswith(PNG_MAGIC):
        return grayscale_from_png(page_bytes)
    if page_bytes[:2] == b"\xff\xd8":
        page_bytes = jpeg_as_single_page_pdf(page_bytes)
    return _pdf_grayscale(page_bytes)


def _pdf_grayscale(page_bytes: bytes) -> tuple[bytes, int, int]:
    document = open_admitted_pdf(page_bytes)
    try:
        if len(document) != 1:
            raise ValueError("a visual page render requires a single-page representation")
        page = document[0]
        try:
            bitmap = page.render(
                scale=RENDER_SCALE,
                grayscale=True,
                fill_color=(255, 255, 255, 255),
                no_smoothtext=True,
                no_smoothpath=True,
                no_smoothimage=True,
                draw_annots=True,
            )
            try:
                width = int(bitmap.width)
                height = int(bitmap.height)
                if width < 1 or height < 1:
                    raise ValueError("pdfium produced an empty raster")
                pixels = _packed_grayscale(bitmap)
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()
    return pixels, width, height


def _packed_grayscale(bitmap: pdfium.PdfBitmap) -> bytes:
    width = int(bitmap.width)
    height = int(bitmap.height)
    stride = int(bitmap.stride)
    channels = int(bitmap.n_channels)
    buffer = bytes(bitmap.buffer)
    if width < 1 or height < 1 or channels < 1:
        raise ValueError("pdfium produced an empty raster")
    row_bytes = width * channels
    if stride < row_bytes:
        raise ValueError("pdfium bitmap stride is shorter than a packed row")
    rows = [buffer[origin : origin + row_bytes] for origin in range(0, stride * height, stride)]
    packed = b"".join(rows)
    if channels == 1:
        return packed
    gray = bytearray(width * height)
    for index in range(width * height):
        base = index * channels
        red, green, blue = packed[base], packed[base + 1], packed[base + 2]
        gray[index] = (77 * red + 150 * green + 29 * blue) >> 8
    return bytes(gray)


def _normalize(pixels: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    long_edge = max(width, height)
    if long_edge <= NORMALIZED_LONG_EDGE:
        return pixels, width, height
    if width >= height:
        out_width = NORMALIZED_LONG_EDGE
        out_height = max(1, (height * NORMALIZED_LONG_EDGE) // width)
    else:
        out_height = NORMALIZED_LONG_EDGE
        out_width = max(1, (width * NORMALIZED_LONG_EDGE) // height)
    return nearest_resize(pixels, width, height, out_width, out_height), out_width, out_height
