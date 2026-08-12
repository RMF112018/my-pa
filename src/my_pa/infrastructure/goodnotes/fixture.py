"""Deterministic adapters for synthetic GoodNotes acceptance evidence.

There is deliberately no filesystem or network adapter here.  The source has an
inventory method and no mutation method; live root admission remains an operator
prerequisite.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.domain.goodnotes.models import RegionBox, SourcePage, TranscribedRegion


@dataclass(frozen=True, slots=True)
class FixtureGoodNotesSource:
    pages: tuple[SourcePage, ...]

    def inventory(self, principal_id: str) -> tuple[SourcePage, ...]:
        return tuple(page for page in self.pages if page.principal_id == principal_id)


@dataclass(frozen=True, slots=True)
class FixturePageTranscriber:
    """UTF-8 fixture transcription, not an OCR quality claim."""

    name: str = "fixture_utf8_region"
    version: str = "1"

    def transcribe(
        self, page: SourcePage, *, timeout_seconds: float | None = None
    ) -> tuple[TranscribedRegion, ...]:
        del timeout_seconds
        text = page.content.decode("utf-8")
        if not text.strip():
            return ()
        return (
            TranscribedRegion(
                box=RegionBox(x=0.05, y=0.05, width=0.9, height=0.9),
                text=text,
                confidence=1.0,
            ),
        )
