"""Schedule Scenarios S6-1: the derived current standard update (contract section 11.3).

Per non-intake Series, `E` is the set of publications that

* are effective `complete`/`partial`,
* are **not** the publication of an effective Baseline (approved, eligible,
  not revoked) at read time (section 12), and
* have no effective `complete`/`partial` successor (a publication naming them
  in `supersedes_publication_id`).

`current` is the maximum of `E` by the one order key `(data_date, admitted_at,
publication_id)` (`PublicationOrderKey`, the key the S5b-2 reads use), or null
when `E` is empty; `same_data_date_ambiguity` is true when more than 1 member
of `E` has the maximum Data Date. A `review_required`/`failed` publication is
never current and never displaces one; nothing is hidden or stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple

from my_pa.domain.schedule.model import SchedulePublicationStatus

__all__ = [
    "CurrencyPublication",
    "CurrentStandardUpdate",
    "PublicationOrderKey",
    "current_standard_update",
]

_ELIGIBLE = frozenset({SchedulePublicationStatus.COMPLETE, SchedulePublicationStatus.PARTIAL})


class PublicationOrderKey(NamedTuple):
    """The one publication order: `(data_date, admitted_at, publication_id)`."""

    data_date: date
    admitted_at: datetime
    publication_id: str


@dataclass(frozen=True, slots=True)
class CurrencyPublication:
    """One publication of the Series as currency reads it (status is the effective one)."""

    publication_id: str
    status: SchedulePublicationStatus
    data_date: date | None
    admitted_at: datetime
    supersedes_publication_id: str | None = None

    @property
    def eligible(self) -> bool:
        return self.status in _ELIGIBLE and self.data_date is not None

    def order_key(self) -> PublicationOrderKey:
        if self.data_date is None:
            raise ValueError("only an eligible publication has an order key")
        return PublicationOrderKey(self.data_date, self.admitted_at, self.publication_id)


@dataclass(frozen=True, slots=True)
class CurrentStandardUpdate:
    publication_id: str | None
    same_data_date_ambiguity: bool


def current_standard_update(
    publications: Sequence[CurrencyPublication],
    effective_baseline_publication_ids: Iterable[str] = (),
) -> CurrentStandardUpdate:
    """The Series' current standard update (section 11.3)."""
    baselines = frozenset(effective_baseline_publication_ids)
    superseded = {
        item.supersedes_publication_id
        for item in publications
        if item.eligible and item.supersedes_publication_id is not None
    }
    members = [
        item
        for item in publications
        if item.eligible
        and item.publication_id not in baselines
        and item.publication_id not in superseded
    ]
    if not members:
        return CurrentStandardUpdate(None, same_data_date_ambiguity=False)
    current = max(members, key=CurrencyPublication.order_key)
    latest = current.data_date
    tied = sum(1 for item in members if item.data_date == latest)
    return CurrentStandardUpdate(current.publication_id, same_data_date_ambiguity=tied > 1)
