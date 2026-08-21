"""Domain failures for the Intelligence Artifact plane.

Messages never carry request values. Classification into public errors happens
in the application layer.
"""

from __future__ import annotations


class IntelligenceCoordinateError(ValueError):
    """Stage, kind, focus area, or source lane is invalid for this cycle."""


class IntelligenceDependencyError(ValueError):
    """Pipeline dependency set is incomplete, duplicated, or incompatible."""


class IntelligenceIdempotencyConflictError(ValueError):
    """Same idempotency key, different mutation-significant fingerprint."""


class IntelligenceVersionConflictError(ValueError):
    """Optimistic version did not match the stored run or cycle."""


class IntelligenceLimitError(ValueError):
    """Body, structured content, or provenance exceeded a published bound."""


class IntelligenceDigestMismatchError(ValueError):
    """Client advisory digest did not match the server-computed digest."""


class IntelligenceStaleReferenceError(ValueError):
    """Named upstream artifact is not the current-ready lineage head."""


class IntelligenceConflictError(ValueError):
    """A current-head or external-run uniqueness conflict."""
