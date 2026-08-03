"""Typed refusals the capture domain raises.

Each names the rule it enforced and never the value it refused. That is the same
discipline `domain.source.enrollment` and `domain.search.query` apply, and it is
what lets `application.errors` classify a refusal into a public code without
having to strip anything out of a message first: there is nothing in one to
strip.
"""

from __future__ import annotations

__all__ = [
    "CaptureBoundsError",
    "CaptureConflictError",
    "CaptureError",
    "EmptyCaptureError",
    "SupersessionError",
]


class CaptureError(Exception):
    """A capture value refused to exist."""


class EmptyCaptureError(CaptureError):
    """The text was absent, empty, or whitespace only.

    Refused rather than stored, and refused rather than normalised into
    something storable: a capture with no content is not a capture, and
    inventing one would be recording that the user wrote something they did not.
    """


class CaptureBoundsError(CaptureError):
    """The text was longer than one capture may carry."""


class SupersessionError(CaptureError):
    """The version number and the predecessor disagree.

    The first version of a capture supersedes nothing and every later one
    supersedes exactly one predecessor. A value that says otherwise would
    describe a chain that forks or one that starts twice.
    """


class CaptureConflictError(CaptureError):
    """An idempotency key is already bound to materially different content.

    Carries the key's *existence* and nothing about what it is bound to. Which
    field differs, and what the stored content is, are both facts about a
    request the caller may not have made.
    """
