"""Filename labels and the report-series key (plan section 6.2).

A filename carries two **labels** and nothing else: an 8-digit publication date
prefix and a saved-report slug (`YYYYMMDD-<slug>.csv`). They label versions and
keep 2 saved reports that share a header signature apart; they never choose an
adapter, a status, a recency, a Project or a filter meaning. A name outside the
pattern, or a prefix that is not a calendar date, has neither label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

__all__ = ["FilenameLabels", "SeriesKey", "filename_labels", "series_key"]

_NAME: Final = re.compile(r"([0-9]{8})-(.+)\.csv", re.DOTALL)


@dataclass(frozen=True, slots=True)
class FilenameLabels:
    date_label: str | None
    slug_label: str | None


@dataclass(frozen=True, slots=True)
class SeriesKey:
    """One saved report of one source: `(source, slug label, header signature)`."""

    ingest_source_id: str
    slug_label: str | None
    header_signature: str


def filename_labels(path: str) -> FilenameLabels:
    """The labels of a file's last path segment, or none of them."""
    name = path.rsplit("/", 1)[-1]
    match = _NAME.fullmatch(name)
    if match is None:
        return FilenameLabels(None, None)
    digits = match.group(1)
    try:
        date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError:
        return FilenameLabels(None, None)
    return FilenameLabels(digits, match.group(2))


def series_key(ingest_source_id: str, path: str, header_signature: str) -> SeriesKey:
    return SeriesKey(ingest_source_id, filename_labels(path).slug_label, header_signature)
