"""Bounded fixture and explicitly admitted local GoodNotes adapters."""

from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    GoodNotesLocalSourceError,
    GoodNotesTranscriptionError,
    ManifestGoodNotesSource,
)

__all__ = [
    "BoundedLocalOCRTranscriber",
    "FixtureGoodNotesSource",
    "FixturePageTranscriber",
    "GoodNotesLocalSourceError",
    "GoodNotesTranscriptionError",
    "ManifestGoodNotesSource",
]
