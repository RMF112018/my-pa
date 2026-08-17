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
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import (
    MappedPageRenderer,
    PdfiumNormalizedRenderer,
    RawRepresentationRenderer,
    production_page_renderer,
)

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
    "PdfiumNormalizedRenderer",
    "RawRepresentationRenderer",
    "production_page_renderer",
    "split_admitted_pdf",
]
