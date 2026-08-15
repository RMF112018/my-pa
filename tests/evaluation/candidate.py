"""Evaluation-only standard-library overlap candidate.

This module is not on the application retrieval path. It scores excerpts with
character n-gram overlap and token Jaccard so WP-KC-07 can compare a private
candidate without adding a model or vector dependency. Hyperparameters are
frozen here before the harness numbers are consulted.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Final

__all__ = ["CANDIDATE_MIN_SCORE", "CANDIDATE_NGRAM_SIZE", "merged_overlap_score"]

#: Frozen candidate knobs. Changing one is a new measurement, not a silent tweak.
CANDIDATE_NGRAM_SIZE: Final = 3
CANDIDATE_MIN_SCORE: Final = 0.12
_TOKEN: Final = re.compile(r"[a-z0-9]+")


def _ngrams(text: str, size: int) -> Counter[str]:
    folded = text.casefold()
    if len(folded) < size:
        return Counter({folded: 1} if folded else {})
    return Counter(folded[index : index + size] for index in range(len(folded) - size + 1))


def _vector_overlap(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _token_jaccard(query: str, text: str) -> float:
    left = set(_TOKEN.findall(query.casefold()))
    right = set(_TOKEN.findall(text.casefold()))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def merged_overlap_score(query: str, text: str) -> float:
    """Max of character n-gram overlap and token Jaccard over the same excerpts."""
    ngram = _vector_overlap(
        _ngrams(query, CANDIDATE_NGRAM_SIZE), _ngrams(text, CANDIDATE_NGRAM_SIZE)
    )
    return max(ngram, _token_jaccard(query, text))
