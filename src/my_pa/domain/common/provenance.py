"""Provenance binding for derived content.

Derived text never replaces original source authority (`INV-PKL-003`). Every
derived record binds the opaque source, object, and version identities it was
produced from, plus the extractor that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = ["Provenance", "TrustLevel"]


class TrustLevel(StrEnum):
    """How much authority a piece of content carries."""

    SOURCE_ORIGINAL = "source_original"
    SOURCE_BOUND_DERIVED = "source_bound_derived"
    MODEL_PROPOSED = "model_proposed"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Immutable binding from derived content back to observed source state."""

    source_id: str
    source_object_id: str
    version_id: str
    extractor: str
    extractor_version: str
    observed_at: datetime
    processed_at: datetime
    trust_level: TrustLevel = TrustLevel.SOURCE_BOUND_DERIVED

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)
        if not self.extractor or not self.extractor_version:
            raise ValueError("extractor and extractor_version are required")
        observed = ensure_utc(self.observed_at)
        processed = ensure_utc(self.processed_at)
        if processed < observed:
            raise ValueError("processed_at cannot precede observed_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "processed_at", processed)
