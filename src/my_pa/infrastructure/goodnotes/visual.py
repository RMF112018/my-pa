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

import hashlib
import struct
import zlib
from dataclasses import dataclass

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pypdfium2 import PDFIUM_INFO, PYPDFIUM_INFO

from my_pa.domain.goodnotes.models import MAX_GOODNOTES_RASTER_BYTES, PageRender
from my_pa.infrastructure.goodnotes.pdf import jpeg_as_single_page_pdf, open_admitted_pdf

PDFIUM_NORMALIZED_NAME = "pypdfium2"
PDFIUM_NORMALIZED_PROFILE = "pdfium-normalized-v1"
RENDER_SCALE = 2.0
NORMALIZED_LONG_EDGE = 256
PERCEPTUAL_ALGORITHM = "dhash"
PERCEPTUAL_ALGORITHM_VERSION = "1"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_EDGE = 10_000


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
        exact = _raster_digest(pixels, width, height)
        norm_pixels, norm_width, norm_height = _normalize(pixels, width, height)
        normalized = _raster_digest(norm_pixels, norm_width, norm_height)
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
                perceptual_hash=_dhash_hex(pixels, width, height),
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
        _PNG_MAGIC
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _renderer_version() -> str:
    return f"{PYPDFIUM_INFO}+pdfium-{PDFIUM_INFO}"


def _grayscale_raster(page_bytes: bytes) -> tuple[bytes, int, int]:
    if page_bytes.startswith(_PNG_MAGIC):
        return _png_grayscale(page_bytes)
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
    return _nearest_resize(pixels, width, height, out_width, out_height), out_width, out_height


def _nearest_resize(
    pixels: bytes, src_width: int, src_height: int, dst_width: int, dst_height: int
) -> bytes:
    out = bytearray(dst_width * dst_height)
    for y in range(dst_height):
        src_y = min(src_height - 1, (y * src_height) // dst_height)
        src_row = src_y * src_width
        dst_row = y * dst_width
        for x in range(dst_width):
            src_x = min(src_width - 1, (x * src_width) // dst_width)
            out[dst_row + x] = pixels[src_row + src_x]
    return bytes(out)


def _dhash_hex(pixels: bytes, width: int, height: int) -> str:
    sample = _nearest_resize(pixels, width, height, 9, 8)
    bits = 0
    for y in range(8):
        row = y * 9
        for x in range(8):
            bits = (bits << 1) | (1 if sample[row + x] > sample[row + x + 1] else 0)
    return f"{bits:016x}"


def _raster_digest(pixels: bytes, width: int, height: int) -> str:
    return hashlib.sha256(f"{width}\x1f{height}\x1f".encode() + pixels).hexdigest()


def _png_grayscale(payload: bytes) -> tuple[bytes, int, int]:
    if not payload.startswith(_PNG_MAGIC):
        raise ValueError("admitted bytes are not a PNG")
    width = height = bit_depth = color_type = None
    idat = bytearray()
    offset = len(_PNG_MAGIC)
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        tag = payload[offset + 4 : offset + 8]
        data = payload[offset + 8 : offset + 8 + length]
        if offset + 12 + length > len(payload) or len(data) != length:
            raise ValueError("PNG chunk is truncated")
        crc = int.from_bytes(payload[offset + 8 + length : offset + 12 + length], "big")
        if (zlib.crc32(tag + data) & 0xFFFFFFFF) != crc:
            raise ValueError("PNG chunk checksum is invalid")
        if tag == b"IHDR":
            if length != 13:
                raise ValueError("PNG IHDR is invalid")
            width, height, bit_depth, color_type, compression, png_filter, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            if (
                width < 1
                or height < 1
                or width > _MAX_EDGE
                or height > _MAX_EDGE
                or bit_depth != 8
                or compression != 0
                or png_filter != 0
                or interlace != 0
                or color_type not in {0, 2, 4, 6}
            ):
                raise ValueError("PNG raster is not an 8-bit non-interlaced gray or RGB image")
        elif tag == b"IDAT":
            idat.extend(data)
        elif tag == b"IEND":
            break
        offset += 12 + length
    if width is None or height is None or bit_depth is None or color_type is None or not idat:
        raise ValueError("PNG is missing image data")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    try:
        reconstructed = zlib.decompress(bytes(idat))
    except zlib.error as error:
        raise ValueError("PNG image data is not readable") from error
    expected = (stride + 1) * height
    if len(reconstructed) != expected:
        raise ValueError("PNG image data is the wrong size")
    raw = bytearray(stride * height)
    prev = bytes(stride)
    cursor = 0
    for row in range(height):
        filter_type = reconstructed[cursor]
        scan = reconstructed[cursor + 1 : cursor + 1 + stride]
        cursor += 1 + stride
        decoded = _paeth_row(filter_type, scan, prev, channels)
        raw[row * stride : (row + 1) * stride] = decoded
        prev = bytes(decoded)
    if color_type == 0:
        return bytes(raw), width, height
    gray = bytearray(width * height)
    for index in range(width * height):
        base = index * channels
        if color_type == 2:
            red, green, blue = raw[base], raw[base + 1], raw[base + 2]
        elif color_type == 4:
            red = green = blue = raw[base]
        else:
            red, green, blue = raw[base], raw[base + 1], raw[base + 2]
        gray[index] = (77 * red + 150 * green + 29 * blue) >> 8
    return bytes(gray), width, height


def _paeth_row(filter_type: int, scan: bytes, prev: bytes, channels: int) -> bytearray:
    row = bytearray(len(scan))
    if filter_type == 0:
        row[:] = scan
        return row
    for index, value in enumerate(scan):
        left = row[index - channels] if index >= channels else 0
        up = prev[index]
        up_left = prev[index - channels] if index >= channels else 0
        if filter_type == 1:
            row[index] = (value + left) & 0xFF
        elif filter_type == 2:
            row[index] = (value + up) & 0xFF
        elif filter_type == 3:
            row[index] = (value + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            row[index] = (value + _paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise ValueError("PNG filter type is unsupported")
    return row


def _paeth_predictor(left: int, up: int, up_left: int) -> int:
    initial = left + up - up_left
    distance_left = abs(initial - left)
    distance_up = abs(initial - up)
    distance_up_left = abs(initial - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left
