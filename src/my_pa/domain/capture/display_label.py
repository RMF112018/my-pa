"""A capture's list-safe display label, stored as an append-only chain.

This is not capture text. `QC-AC-041` keeps `capture_versions.content` out of
list and search answers; a label is caller-supplied metadata that those answers
may carry because it is not derived from the note and is not a snippet of it.
Empty after normalisation is omitted rather than stored: there is then no row,
and the current label is `None`.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from my_pa.domain.capture.errors import CaptureBoundsError, CaptureError

__all__ = [
    "MAX_DISPLAY_LABEL_CHARACTERS",
    "normalize_display_label",
]

#: Longest one display label may be, counted in Unicode scalars after NFC and
#: strip. A bound is required — an unbounded caller-controlled column is a
#: payload channel — and this one is a title, not a note.
MAX_DISPLAY_LABEL_CHARACTERS: Final = 120

_FORBIDDEN_CATEGORIES: Final = frozenset({"Cc", "Zl", "Zp"})


def normalize_display_label(value: str | None) -> str | None:
    """Return a stored label, or `None` when the caller omitted one.

    NFC then strip, so two spellings of the same title are one title and a
    whitespace-only value is an omission rather than a stored blank. Control
    characters and line/paragraph separators are refused rather than stored:
    a listing title is not a channel for them. Length is counted in Unicode
    scalars of the normalised form.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise CaptureError("a display label must be a string")
    folded = unicodedata.normalize("NFC", value).strip()
    if not folded:
        return None
    if any(unicodedata.category(character) in _FORBIDDEN_CATEGORIES for character in folded):
        raise CaptureError("a display label may not carry control characters")
    if len(folded) > MAX_DISPLAY_LABEL_CHARACTERS:
        raise CaptureBoundsError(
            f"a display label may carry at most {MAX_DISPLAY_LABEL_CHARACTERS} characters"
        )
    return folded
