"""Neutral GoodNotes source-liveness evidence shared across architecture layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class GoodNotesSourceLiveness(StrEnum):
    """One explicit, non-authorizing observation of a configured source path."""

    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    MISSING = "MISSING"
    REAPPEARED = "REAPPEARED"


@dataclass(frozen=True, slots=True)
class GoodNotesSourceLivenessReceipt:
    """Safe liveness evidence; only AVAILABLE permits ingestion by itself."""

    source_root_id: str
    relative_path: str
    state: GoodNotesSourceLiveness
    checked_at: datetime
    maximum_staleness_seconds: float
    last_seen_at: datetime | None
    current_sha256: str | None
    prior_sha256: str | None
    reappeared_content_changed: bool | None = None

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("the GoodNotes liveness check time must be timezone-aware")
        if self.maximum_staleness_seconds <= 0:
            raise ValueError("the GoodNotes liveness interval must be positive")
        if self.last_seen_at is not None and (
            self.last_seen_at.tzinfo is None or self.last_seen_at.utcoffset() is None
        ):
            raise ValueError("the GoodNotes last-seen time must be timezone-aware")
        if self.state in {GoodNotesSourceLiveness.MISSING, GoodNotesSourceLiveness.STALE}:
            if self.current_sha256 is not None or self.reappeared_content_changed is not None:
                raise ValueError("an unavailable GoodNotes source cannot carry current content")
        elif self.current_sha256 is None:
            raise ValueError("an observed GoodNotes source must carry its current digest")
        if (
            self.state is not GoodNotesSourceLiveness.REAPPEARED
            and self.reappeared_content_changed is not None
        ):
            raise ValueError("only a reappeared GoodNotes source carries continuity evidence")

    @property
    def safe_to_ingest(self) -> bool:
        """Reappearance requires explicit identity reconciliation before reuse."""
        return self.state is GoodNotesSourceLiveness.AVAILABLE
