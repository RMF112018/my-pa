"""Bounded fixture and explicitly admitted local GoodNotes adapters."""

from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    GoodNotesLocalSourceError,
    GoodNotesTranscriptionError,
    LocalGoodNotesObserver,
    ManifestGoodNotesSource,
    NotebookFileObservation,
)
from my_pa.infrastructure.goodnotes.render import MappedPageRenderer, RawRepresentationRenderer

__all__ = [
    "BoundedLocalOCRTranscriber",
    "FixtureGoodNotesSource",
    "FixturePageTranscriber",
    "GoodNotesLocalSourceError",
    "GoodNotesTranscriptionError",
    "LocalGoodNotesObserver",
    "ManifestGoodNotesSource",
    "MappedPageRenderer",
    "NotebookFileObservation",
    "RawRepresentationRenderer",
]
