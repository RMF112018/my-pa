"""How much of a stated scope has been processed.

Coverage lives in the domain rather than beside the envelope that reports it,
for the same reason `TrustLevel` and `Classification` do: it is a fact about
work that was done, and the envelope is one way of describing that fact rather
than its home. `contracts.v1.disclosure` imports this and re-exports it, so the
public contract is unchanged.

The distinctness of these states is the point. `INV-PKL-007` forbids converting
unavailable, stale, partial, quarantined, or unsupported evidence into empty or
complete, and that rule is only enforceable if the states it names exist
separately in the first place. A boolean "did we index it" would make the rule
unstateable.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["CoverageState"]


class CoverageState(StrEnum):
    """Distinct coverage states; none of them collapses into "empty"."""

    NOT_ENROLLED = "not_enrolled"
    ELIGIBLE = "eligible"
    QUEUED = "queued"
    PROCESSED = "processed"
    PARTIALLY_PROCESSED = "partially_processed"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    SUPERSEDED = "superseded"
