"""Quarantine: that processing stopped, and why — never what was in it.

`docs/specs` section 12 lists the triggers and then constrains what may be kept:
"Quarantine stores IDs, safe reason codes, and review state—not unsafe payloads
in logs." `QuarantineRecord` discharges that structurally rather than by
convention. Every field is an opaque identifier, an enumerated code, or a
timestamp, and there is no field a payload could be put in — no bytes, no text,
no excerpt, no locator, no free-text note. Adding one would be the visible,
reviewable act it should be, and `tests/unit/test_quarantine.py` pins the field
set so it cannot arrive unremarked.

The reason is an enumerated code for the same reason `jobs.last_error_code` is:
a free-text column here would be exactly the payload channel section 13 forbids,
because the most natural thing to write into it is the value that caused the
failure.

Review state exists because section 12 requires it, and it has one member for the
same reason `SourceProviderKind` has one: reprocessing "requires explicit bounded
recovery and new operation/audit", and no such path exists yet. A second member
arrives with the operator review that sets it, not before — a state nothing can
reach is a promise the record cannot keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = ["QuarantineReason", "QuarantineRecord", "QuarantineReviewState"]


class QuarantineReason(StrEnum):
    """Why processing stopped, as a safe code.

    These are the triggers of `docs/specs` section 12. Two of that section's
    entries are folded rather than dropped, and the folding is stated here so it
    is reviewable:

    * "link/alias escape or race suspected" is `CONTAINMENT_UNPROVEN`. The
      provider cannot distinguish an escaping alias from one it merely could not
      prove contained, and a code that claimed the difference would assert more
      than the observation supports.
    * "archive/container depth/expansion limit" is `RESOURCE_LIMIT_EXCEEDED`.
      Nothing in the MCV opens an archive, so a dedicated archive code would name
      a mechanism that does not exist.
    """

    CONTAINMENT_UNPROVEN = "containment_unproven"
    MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE = "media_type_conflicts_with_signature"
    PARSER_FAILED = "parser_failed"
    PARSER_TIMED_OUT = "parser_timed_out"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    MALFORMED_INPUT = "malformed_input"
    SOURCE_VERSION_CHANGED = "source_version_changed"
    OUTPUT_NOT_ATTRIBUTABLE_TO_VERSION = "output_not_attributable_to_version"


class QuarantineReviewState(StrEnum):
    """Where a quarantined object stands with the operator.

    One member, because one is reachable. See the module docstring.
    """

    PENDING_REVIEW = "pending_review"


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """One quarantined object, as the record may be disclosed.

    `version_id` is optional and its absence is meaningful: a containment failure
    can happen before any version was observed, and recording a version that was
    never proven would attribute the quarantine to bytes nobody saw.
    """

    quarantine_id: str
    enrollment_id: str
    source_object_id: str
    version_id: str | None
    reason: QuarantineReason
    review_state: QuarantineReviewState
    quarantined_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.quarantine_id, IdKind.KNOWLEDGE)
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        if self.version_id is not None:
            validate_identifier(self.version_id, IdKind.VERSION)
        object.__setattr__(self, "quarantined_at", ensure_utc(self.quarantined_at))
