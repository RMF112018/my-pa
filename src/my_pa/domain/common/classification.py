"""Data classification and cloud eligibility.

Classification alone grants nothing. A disclosure is permitted only when the
principal, purpose, scope, and policy all allow it (`docs/specs`, section 11).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = ["CLASSIFICATION_RANK", "Classification", "classification_max", "is_cloud_eligible"]


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


#: Which classifications are at least as restrictive as which, as a rank: a
#: higher rank is more restrictive. Lifted here by KLP-WP-01 (R6 plan section
#: 5.2) from the private map in `domain.relationship.memory`, which now aliases
#: this one, so the Relationship Memory floor and the Knowledge Assertion
#: effective-class rule cannot disagree about order. The SQL restatement is
#: `knowledge.knowledge_classification_rank(text)` (WP-02); the ranks are equal.
CLASSIFICATION_RANK: Final[Mapping[Classification, int]] = MappingProxyType(
    {
        Classification.SYNTHETIC_TEST: 0,
        Classification.PRIVATE_LOCAL: 1,
        Classification.RESTRICTED_LOCAL: 2,
    }
)


def classification_max(first: Classification, *others: Classification) -> Classification:
    """Return the most restrictive of the given classifications (rank-max).

    Monotonic by construction: adding an operand can only keep or raise the
    result. Fails closed on a value that is not a `Classification` rather than
    ranking an unknown string as harmless.
    """
    result = first
    for candidate in (first, *others):
        if not isinstance(candidate, Classification):
            raise TypeError(
                f"classification_max takes Classification, got {type(candidate).__name__}"
            )
        if CLASSIFICATION_RANK[candidate] > CLASSIFICATION_RANK[result]:
            result = candidate
    return result
