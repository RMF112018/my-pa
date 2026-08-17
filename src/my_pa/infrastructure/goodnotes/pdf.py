"""Deterministic admitted-PDF page enumeration. Page number is positional only."""

from __future__ import annotations

import io
from collections.abc import Iterator

import pypdfium2 as pdfium  # type: ignore[import-untyped]

_PDF_MAGIC = b"%PDF"


def split_admitted_pdf(payload: bytes) -> tuple[bytes, ...]:
    """Yield one single-page PDF representation per page of an admitted document.

    Page ordinal is the enumeration order. It is weak evidence, not identity.
    Empty or unreadable input fails closed.
    """
    return tuple(_iter_page_pdfs(payload))


def _iter_page_pdfs(payload: bytes) -> Iterator[bytes]:
    document = open_admitted_pdf(payload)
    try:
        if len(document) < 1:
            raise ValueError("an admitted PDF must contain at least one page")
        for index in range(len(document)):
            isolated = pdfium.PdfDocument.new()
            try:
                isolated.import_pages(document, [index])
                buffer = io.BytesIO()
                isolated.save(buffer)
                page_bytes = buffer.getvalue()
            finally:
                isolated.close()
            if not page_bytes:
                raise ValueError("an admitted PDF page representation was empty")
            yield page_bytes
    finally:
        document.close()


def jpeg_as_single_page_pdf(payload: bytes) -> bytes:
    """Wrap JPEG bytes as a one-page PDF so the pinned pdfium rasterizer can decode them."""
    if not payload:
        raise ValueError("a GoodNotes page render requires admitted bytes")
    width, height, components = _jpeg_frame(payload)
    if components == 1:
        colorspace = "/DeviceGray"
    elif components == 3:
        colorspace = "/DeviceRGB"
    else:
        raise ValueError("unsupported JPEG color components")
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace {colorspace} /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(payload)} >>\nstream\n".encode()
        + payload
        + b"\nendstream"
    )
    content = b"q\n612 0 0 792 0 0 cm\n/Im0 Do\nQ\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
        image,
    ]
    return _assemble_pdf(objects)


def open_admitted_pdf(payload: bytes) -> pdfium.PdfDocument:
    if not payload:
        raise ValueError("an admitted PDF is required")
    if not payload.startswith(_PDF_MAGIC):
        raise ValueError("admitted bytes are not a PDF")
    try:
        return pdfium.PdfDocument(payload)
    except pdfium.PdfiumError as error:
        raise ValueError("admitted PDF is not readable") from error


def _jpeg_frame(payload: bytes) -> tuple[int, int, int]:
    if payload[:2] != b"\xff\xd8":
        raise ValueError("admitted bytes are not a JPEG")
    index = 2
    while index + 9 <= len(payload):
        if payload[index] != 0xFF:
            index += 1
            continue
        marker = payload[index + 1]
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xDA:
            break
        if index + 4 > len(payload):
            break
        length = int.from_bytes(payload[index + 2 : index + 4], "big")
        if marker in {0xC0, 0xC1, 0xC2} and length >= 8:
            height = int.from_bytes(payload[index + 5 : index + 7], "big")
            width = int.from_bytes(payload[index + 7 : index + 9], "big")
            components = payload[index + 9]
            if width < 1 or height < 1:
                raise ValueError("JPEG frame dimensions must be positive")
            return width, height, components
        index += 2 + length
    raise ValueError("JPEG has no frame header")


def _assemble_pdf(bodies: list[bytes]) -> bytes:
    parts = [b"%PDF-1.4\n"]
    cursor = len(parts[0])
    offsets: list[int] = []
    numbered: list[bytes] = []
    for index, body in enumerate(bodies, start=1):
        obj = f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        offsets.append(cursor)
        numbered.append(obj)
        cursor += len(obj)
    xref = [f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode()]
    xref.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = (
        f"trailer<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{cursor}\n%%EOF\n"
    ).encode()
    return b"".join(parts + numbered + xref + [trailer])
