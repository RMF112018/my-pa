"""The knowledge clock's cut rules, record lineage S3 contract section 3.4.

Pure. Every lineage fact row written after the S3 revision carries the commit
mark of its own transaction (`commit_seq`), allocated per Principal from a
row-locked allocator whose committed `last_marked_at` is the **horizon** `H`.
This module states, without reading anything, how a read turns its request
into cuts:

* **known time** -- `T_k = min(requested known_at, or now when omitted; H)`. A
  requested `known_at` after now is `invalid_request` / `known_at`. A Principal
  with no allocator row has no lineage fact: `T_k` is `None` and every lineage
  set is empty.
* **lineage valid time** -- `T_v = min(valid_at, T_k)` (default `T_k`); a
  requested `valid_at` after now is `invalid_request` / `valid_at`. The answer
  reports `valid_at` as requested (or `T_k` when omitted) and
  `lineage_valid_at = T_v`.
* **the native cut** -- `N = min(valid_at?, known_at?, read time)` over the
  values the request supplies: the note-version cut, never the lineage
  horizon (R3-F01, R3-F20).
* **knowledge of one fact** -- a fact with a mark is known at `T` iff its
  `commit_seq <= W(T)`, the largest mark of the Principal whose `marked_at <=
  T`; a fact written before the S3 revision (`commit_seq` null) is known at `T`
  iff its own `recorded_at <= T`.
* **completeness** -- one `complete_state` and every applicable code, ordered
  by section 3's precedence.

Persistence resolves `H` and `W(T)`; the application applies these rules.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.domain.lineage.vocabulary import LineageCompleteness

__all__ = [
    "COMPLETENESS_PRECEDENCE",
    "CutAfterNowError",
    "KnowledgeCut",
    "completeness",
    "effective_known_at",
    "is_known",
    "knowledge_cut",
    "native_cut",
]

#: Section 3's precedence, highest first: the state an answer reports is the
#: first applicable code, and `qualifiers` lists every applicable one in this
#: order. `complete` applies only when nothing else does.
COMPLETENESS_PRECEDENCE: Final[tuple[LineageCompleteness, ...]] = (
    LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED,
    LineageCompleteness.UNRESOLVED_AMBIGUITY,
    LineageCompleteness.TRUNCATED_BUDGET,
    LineageCompleteness.RESTRICTED_EVIDENCE,
    LineageCompleteness.PARTIAL_NATIVE_HISTORY,
    LineageCompleteness.COMPLETE,
)


class CutAfterNowError(ValueError):
    """A requested `known_at` or `valid_at` lies after the server's now.

    `field` names the request field (`known_at` or `valid_at`), which the
    application reports as `invalid_request` with that safe detail.
    """

    def __init__(self, field: str) -> None:
        super().__init__(f"{field} is after now")
        self.field = field


@dataclass(frozen=True, slots=True)
class KnowledgeCut:
    """The cuts one lineage read uses (section 3.4).

    `known_at` is `T_k`; `valid_at` is what the answer reports (the requested
    `valid_at`, else `T_k`); `lineage_valid_at` is `T_v`. All three are `None`
    exactly when the Principal has no lineage fact (no allocator row) and no
    `valid_at` was requested -- with a requested `valid_at`, `valid_at` is
    reported and the two lineage cuts stay `None`.
    """

    known_at: datetime | None
    valid_at: datetime | None
    lineage_valid_at: datetime | None


def _not_after_now(value: datetime | None, now: datetime, field: str) -> None:
    if value is not None and value > now:
        raise CutAfterNowError(field)


def effective_known_at(
    requested: datetime | None, *, now: datetime, horizon: datetime | None
) -> datetime | None:
    """`T_k = min(requested or now, H)`; `None` when the Principal has no horizon."""
    _not_after_now(requested, now, "known_at")
    if horizon is None:
        return None
    return min(requested if requested is not None else now, horizon)


def knowledge_cut(
    *,
    known_at: datetime | None,
    valid_at: datetime | None,
    now: datetime,
    horizon: datetime | None,
) -> KnowledgeCut:
    """`T_k`, the reported `valid_at` and `T_v` for one request (section 3.4).

    `known_at` is checked before `valid_at`, so a request with both after now
    names `known_at`.
    """
    t_k = effective_known_at(known_at, now=now, horizon=horizon)
    _not_after_now(valid_at, now, "valid_at")
    if t_k is None:
        return KnowledgeCut(known_at=None, valid_at=valid_at, lineage_valid_at=None)
    t_v = t_k if valid_at is None else min(valid_at, t_k)
    return KnowledgeCut(
        known_at=t_k, valid_at=valid_at if valid_at is not None else t_k, lineage_valid_at=t_v
    )


def native_cut(
    *, known_at: datetime | None, valid_at: datetime | None, read_time: datetime
) -> datetime:
    """`N = min(valid_at?, known_at?, read time)`: the note-version cut (section 3.4).

    The *requested* values, never `T_k`: a current read (no `known_at`) cuts at
    its read time, so a note saved after the lineage horizon is shown.
    """
    supplied = [value for value in (known_at, valid_at) if value is not None]
    return min([*supplied, read_time])


def is_known(
    *,
    commit_seq: int | None,
    recorded_at: datetime,
    watermark: int | None,
    cut: datetime | None,
) -> bool:
    """Whether one fact row is known at `cut`, whose resolved mark is `watermark`.

    `watermark` is `W(cut)`: the largest mark with `marked_at <= cut`, `None`
    when there is none. A pre-S3 row (`commit_seq` `None`) is known by its own
    `recorded_at`. Nothing is known at a `None` cut.
    """
    if cut is None:
        return False
    if commit_seq is None:
        return recorded_at <= cut
    return watermark is not None and commit_seq <= watermark


def completeness(
    applicable: Iterable[LineageCompleteness],
) -> tuple[LineageCompleteness, tuple[LineageCompleteness, ...]]:
    """`(complete_state, qualifiers)` for the applicable codes (section 3).

    `complete` is never combined with another code: it is the state only when
    no other code applies, and then it is the one qualifier.
    """
    codes = set(applicable) - {LineageCompleteness.COMPLETE}
    if not codes:
        return LineageCompleteness.COMPLETE, (LineageCompleteness.COMPLETE,)
    ordered = tuple(code for code in COMPLETENESS_PRECEDENCE if code in codes)
    return ordered[0], ordered
