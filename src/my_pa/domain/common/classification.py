"""Data classification and cloud eligibility.

Classification alone grants nothing. A disclosure is permitted only when the
principal, purpose, scope, and policy all allow it (`docs/specs`, section 11).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Classification", "is_cloud_eligible"]


class Classification(StrEnum):
    """Classifications recognised by the MCV contract."""

    SYNTHETIC_TEST = "synthetic_test"
    PRIVATE_LOCAL = "private_local"
    RESTRICTED_LOCAL = "restricted_local"


def is_cloud_eligible(classification: Classification) -> bool:
    """Return whether `classification` may leave the local trust boundary.

    Defaults to false for everything except explicitly synthetic test data. Real
    local content requires a separate field-level approval that Phase 01 does not
    implement, so no other classification can return true here.
    """
    return classification is Classification.SYNTHETIC_TEST
