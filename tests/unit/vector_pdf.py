"""Stdlib vector PDFs for GoodNotes visual-identity tests. No fonts, no images."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    gray: float = 0.0


def vector_pdf(
    pages: tuple[tuple[Rect, ...], ...],
    *,
    producer: str = "my-pa-fixtures",
    comment: str = "",
    dummy_objects: int = 0,
) -> bytes:
    """Build a real PDF using only rectangle fills. Page size is US Letter."""
    if not pages:
        raise ValueError("a vector PDF requires at least one page")
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    page_count = len(pages)
    page_ids = [3 + dummy_objects + index for index in range(page_count)]
    content_ids = [page_ids[-1] + 1 + index for index in range(page_count)]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode()
    bodies: list[bytes] = [catalog, pages_obj]
    for _ in range(dummy_objects):
        bodies.append(b"<< /Unused true >>")
    for _page_id, content_id in zip(page_ids, content_ids, strict=True):
        bodies.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R /Resources << >> >>"
            ).encode()
        )
    for marks in pages:
        stream = _page_stream(marks)
        bodies.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")
    info = f"<< /Producer ({_pdf_literal(producer)}) /Comment ({_pdf_literal(comment)}) >>"
    bodies.append(info.encode())
    return _assemble(bodies, header_comment=comment)


def _page_stream(marks: tuple[Rect, ...]) -> bytes:
    commands = ["q"]
    for mark in marks:
        commands.append(f"{mark.gray:.3f} g")
        commands.append(f"{mark.x:.3f} {mark.y:.3f} {mark.width:.3f} {mark.height:.3f} re")
        commands.append("f")
    commands.append("Q")
    return ("\n".join(commands) + "\n").encode("ascii")


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(bodies: list[bytes], *, header_comment: str) -> bytes:
    parts = [b"%PDF-1.4\n"]
    if header_comment:
        parts.append(b"% " + header_comment.encode("ascii", "strict") + b"\n")
    cursor = sum(len(part) for part in parts)
    numbered: list[bytes] = []
    offsets: list[int] = []
    for index, body in enumerate(bodies, start=1):
        obj = f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        offsets.append(cursor)
        numbered.append(obj)
        cursor += len(obj)
    xref = [f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode()]
    xref.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    info_id = len(bodies)
    trailer = (
        f"trailer<< /Size {len(bodies) + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{cursor}\n%%EOF\n"
    ).encode()
    return b"".join(parts + numbered + xref + [trailer])
