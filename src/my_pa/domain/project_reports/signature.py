"""The header signature and the header checks (plan sections 4.1 rule 4 and 4.2).

An export is recognised by its ordered header list only. The signature is the
SHA-256 of the compact JSON array of the header cells exactly as decoded: no
trimming, no case folding, order kept, so a reordered, renamed, added or
removed column is a new signature. Slugs and date prefixes are never inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final

from my_pa.domain.project_reports.model import RejectionCode

__all__ = ["SIGNATURE_VERSION", "header_refusal", "header_signature"]

SIGNATURE_VERSION: Final = "pulse_header_signature_v1"


def header_signature(cells: Sequence[str]) -> str:
    """`sha256(utf8(json.dumps(cells, ensure_ascii=False, separators=(",", ":"))))`, hex."""
    if isinstance(cells, str) or not all(type(cell) is str for cell in cells):
        raise TypeError("a header is a sequence of decoded text cells")
    encoded = json.dumps(list(cells), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def header_refusal(cells: Sequence[str]) -> RejectionCode | None:
    """`invalid_header` unless the header is non-empty with unique, non-empty cells."""
    if not cells or any(cell == "" for cell in cells) or len(set(cells)) != len(cells):
        return RejectionCode.INVALID_HEADER
    return None
