"""Deterministic synthetic Gate B page PDFs. No personal handwriting."""

from __future__ import annotations

from collections.abc import Sequence

from my_pa.application.goodnotes_gsqs import Geometry, GoldRegion
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(bodies: list[bytes]) -> bytes:
    parts = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
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
    trailer = (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R /Info {len(bodies)} 0 R >>\n"
        f"startxref\n{cursor}\n%%EOF\n"
    ).encode()
    return b"".join(parts + numbered + xref + [trailer])


def _pdf_xy(geometry: Geometry) -> tuple[float, float, float, float]:
    """Map normalized y-down boxes onto US Letter PDF y-up coordinates."""
    x = 36 + geometry.x_min * 540
    width = geometry.width * 540
    height = geometry.height * 720
    y = 36 + (1.0 - geometry.y_min - geometry.height) * 720
    return x, y, width, height


def synthetic_labeled_page_pdf(
    *,
    case_id: str,
    title: str,
    regions: Sequence[GoldRegion],
    contrast: str = "normal",
    style: str = "typed-and-italic",
) -> bytes:
    fill = b"0.96" if contrast != "low" else b"0.88"
    ink = "0.08" if contrast != "low" else "0.45"
    commands = [f"q {fill.decode()} g 36 36 540 720 re f Q"]
    commands.append("BT /F1 11 Tf 54 730 Td (SYNTHETIC / NON-PERSONAL Gate B GSQS) Tj ET")
    commands.append(f"BT /F1 9 Tf 54 716 Td ({_pdf_literal(case_id)}) Tj ET")
    commands.append(f"BT /F1 10 Tf 54 700 Td ({_pdf_literal(title[:80])}) Tj ET")
    for region in regions:
        x, y, width, height = _pdf_xy(region.geometry)
        if region.kind is GoodNotesSegmentKind.SOURCE_CONTEXT:
            commands.append(
                f"q {ink} {ink} {ink} RG 0.8 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S Q"
            )
            font = "F1"
            size = 14 if style != "agenda" else 12
        else:
            commands.append(
                f"q {ink} {ink} {ink} RG 1.1 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S Q"
            )
            font = "F2" if style != "print-only" else "F1"
            size = 16 if style != "dense" else 11
        text = region.transcription[:90] or "[UNREADABLE]"
        commands.append(
            f"BT /{font} {size} Tf {x + 6:.2f} {y + max(8.0, height - 18):.2f} Td "
            f"({_pdf_literal(text)}) Tj ET"
        )
        if style == "arrow":
            commands.append(
                f"q {ink} {ink} {ink} RG 1 w {x:.2f} {y + height + 8:.2f} m "
                f"{x + 24:.2f} {y + height + 2:.2f} l S Q"
            )
        if style == "crossed-out":
            commands.append(
                f"q 0.7 0.1 0.1 RG 1 w {x:.2f} {y + height:.2f} m {x + width:.2f} {y:.2f} l S Q"
            )
    stream = ("\n".join(commands) + "\n").encode("ascii")
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>"
    )
    info = (
        "<< /Producer (my-pa-gsqs-v1) /Title ("
        + _pdf_literal("SYNTHETIC Gate B GSQS fixture")
        + ") /Subject ("
        + _pdf_literal(case_id)
        + ") >>"
    )
    return _assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page,
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Italic >>",
            info.encode(),
        ]
    )
