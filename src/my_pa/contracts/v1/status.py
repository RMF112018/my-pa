"""The observable state one `sources.status` subject is in.

`docs/specs` section 9.5 fixes the vocabulary this enum carries. It is a public
contract value — it appears in a `sources.status` result — and it existed
nowhere before, which is why it is added here rather than expressed with one of
the vocabularies that already exist. `CoverageState` answers "how much of a
stated scope reached an outcome", which is a different question and cannot say
`configured`, `running`, or `failed`; `JobState` is persistence's private
lifecycle and is not a public shape.

Two of section 9.5's twelve values are deliberately absent. `cancel_requested`
and `cancelled` describe a cancellation path, and nothing in this build has one:
`infrastructure.persistence.tables.JobState` omits the same two states for the
same reason, and declaring a value nothing can reach would be a promise the
contract cannot keep. They arrive with the code that can produce them.

`complete_for_scope` is the value most easily misread, so the rule section 9.5
attaches to it is restated where it is defined: it is a claim about one bounded
enrollment at one observed snapshot, and never a claim that the physical source
is fully indexed.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["SourceStatusState"]


class SourceStatusState(StrEnum):
    """What a source, enrollment, operation, or object is currently doing."""

    #: The source is configured and may be read; it says nothing about coverage.
    CONFIGURED = "configured"
    #: An enrollment exists and no work has been claimed against it yet.
    ACCEPTED = "accepted"
    #: Work is queued and unclaimed.
    QUEUED = "queued"
    #: A worker holds a lease on the work.
    RUNNING = "running"
    #: Some of the enrolled scope reached an outcome and some has not.
    PARTIALLY_COMPLETE = "partially_complete"
    #: Every eligible object in this bounded scope reached an outcome, at the
    #: observed snapshot. Never a statement about the whole physical source.
    COMPLETE_FOR_SCOPE = "complete_for_scope"
    #: Processing stopped for a security or quality reason.
    QUARANTINED = "quarantined"
    #: The content type is one this build does not read.
    UNSUPPORTED = "unsupported"
    #: The subject could not be observed.
    UNAVAILABLE = "unavailable"
    #: The work exhausted its attempts without succeeding.
    FAILED = "failed"
