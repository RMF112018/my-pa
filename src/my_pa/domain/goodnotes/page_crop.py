"""Stdlib grayscale PNG crop identity. Agent geometry is a locator, not truth.

Canonical crop identity is the digest of cropped grayscale pixels. This module
owns the PNG decode and pixel-grid crop so application matching does not import
the pdfium renderer. Blank crops are not visual evidence.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from dataclasses import dataclass

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_EDGE = 10_000
_BLANK_INK_CEILING = 250
_BLANK_INK_FRACTION = 0.005


@dataclass(frozen=True, slots=True)
class GroundedPageCrop:
    """Server-grounded crop of an immutable page raster. Not an Agent claim."""

    digest: str
    dhash: str
    width: int
    height: int
    blank: bool


def grayscale_from_png(payload: bytes) -> tuple[bytes, int, int]:
    if not payload.startswith(PNG_MAGIC):
        raise ValueError("admitted bytes are not a PNG")
    width = height = bit_depth = color_type = None
    idat = bytearray()
    offset = len(PNG_MAGIC)
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


def nearest_resize(
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


def dhash_hex(pixels: bytes, width: int, height: int) -> str:
    sample = nearest_resize(pixels, width, height, 9, 8)
    bits = 0
    for y in range(8):
        row = y * 9
        for x in range(8):
            bits = (bits << 1) | (1 if sample[row + x] > sample[row + x + 1] else 0)
    return f"{bits:016x}"


def raster_digest(pixels: bytes, width: int, height: int) -> str:
    return hashlib.sha256(f"{width}\x1f{height}\x1f".encode() + pixels).hexdigest()


def crop_is_blank(pixels: bytes) -> bool:
    if not pixels:
        return True
    ink = sum(1 for value in pixels if value <= _BLANK_INK_CEILING)
    return ink / len(pixels) < _BLANK_INK_FRACTION


def aligned_crop_box(
    x_min: float,
    y_min: float,
    width: float,
    height: float,
    raster_width: int,
    raster_height: int,
) -> tuple[int, int, int, int]:
    """Clamp a normalized locator onto the pixel grid. Geometry is weak evidence."""
    x0 = min(raster_width - 1, max(0, int(x_min * raster_width)))
    y0 = min(raster_height - 1, max(0, int(y_min * raster_height)))
    x1 = min(raster_width, max(x0 + 1, math.ceil((x_min + width) * raster_width)))
    y1 = min(raster_height, max(y0 + 1, math.ceil((y_min + height) * raster_height)))
    return x0, y0, x1, y1


def crop_normalized_png(
    png: bytes,
    x_min: float,
    y_min: float,
    width: float,
    height: float,
) -> GroundedPageCrop:
    """Crop grayscale pixels from a stored page PNG. Agent crop digests are ignored."""
    pixels, raster_width, raster_height = grayscale_from_png(png)
    x0, y0, x1, y1 = aligned_crop_box(x_min, y_min, width, height, raster_width, raster_height)
    crop_width = x1 - x0
    crop_height = y1 - y0
    cropped = bytearray(crop_width * crop_height)
    for row in range(crop_height):
        source = (y0 + row) * raster_width + x0
        destination = row * crop_width
        cropped[destination : destination + crop_width] = pixels[source : source + crop_width]
    payload = bytes(cropped)
    return GroundedPageCrop(
        digest=raster_digest(payload, crop_width, crop_height),
        dhash=dhash_hex(payload, crop_width, crop_height),
        width=crop_width,
        height=crop_height,
        blank=crop_is_blank(payload),
    )


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
