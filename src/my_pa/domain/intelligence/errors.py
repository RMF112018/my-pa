"""Domain failures for the Intelligence Artifact plane.

Messages never carry request values. Classification into public errors happens
in the application layer.
"""

from __future__ import annotations

from enum import StrEnum


class DependencyRejection(StrEnum):
    """Why a named pipeline dependency was refused. Names a rule, never a value.

    ``MISSING`` covers an unknown id and another Principal's id alike: the two
    must stay indistinguishable. ``STALE`` covers a dependency that is no longer
    its coordinate's current head, was superseded, or whose own upstream moved.
    """

    MISSING = "missing"
    WRONG_CYCLE = "wrong_cycle"
    WRONG_FOCUS = "wrong_focus"
    WRONG_STAGE = "wrong_stage"
    DUPLICATE_LANE = "duplicate_lane"
    COUNT = "count"
    STALE = "stale"
    PARTIAL_INPUT = "partial_input"


class IntelligenceCoordinateError(ValueError):
    """Stage, kind, focus area, or source lane is invalid for this cycle."""


class IntelligenceDependencyError(ValueError):
    """Pipeline dependency set is incomplete, duplicated, or incompatible.

    ``reason`` is the rule that refused, when the stage reports one.
    """

    def __init__(self, reason: DependencyRejection | None = None) -> None:
        super().__init__("dependency" if reason is None else reason.value)
        self.reason = reason


class IntelligenceIdempotencyConflictError(ValueError):
    """Same idempotency key, different mutation-significant fingerprint."""


class IntelligenceVersionConflictError(ValueError):
    """Optimistic version did not match the stored run or cycle."""


class IntelligenceLimitError(ValueError):
    """Body, structured content, or provenance exceeded a published bound."""


class IntelligenceDigestMismatchError(ValueError):
    """Client advisory digest did not match the server-computed digest."""


class IntelligenceStaleReferenceError(ValueError):
    """Named upstream artifact is not the current-ready lineage head.

    ``reason`` is ``DependencyRejection.STALE`` when a named pipeline dependency
    is the stale reference, and ``None`` for any other stale reference (such as
    ``supersedes_artifact_id`` naming a head that is no longer current).
    """

    def __init__(self, reason: DependencyRejection | None = None) -> None:
        super().__init__("stale" if reason is None else reason.value)
        self.reason = reason


class IntelligenceConflictError(ValueError):
    """A current-head or external-run uniqueness conflict."""
