"""Schedule Scenarios S6-1: the derived current standard update (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 11.3, vectors
C1-C8. C5-C8 take the effective baseline publications from the section 12
event fold (`baseline_status`), so currency excludes exactly the publications
an approved, eligible, non-revoked Baseline names. Every value is synthetic.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

import pytest

from my_pa.domain.schedule.baselines import (
    BaselineAction,
    BaselineEvent,
    BaselineType,
    baseline_status,
)
from my_pa.domain.schedule.currency import (
    CurrencyPublication,
    CurrentStandardUpdate,
    PublicationOrderKey,
    current_standard_update,
)
from my_pa.domain.schedule.model import SchedulePublicationStatus

COMPLETE: Final = SchedulePublicationStatus.COMPLETE
JAN31: Final = date(2027, 1, 31)
FEB28: Final = date(2027, 2, 28)


def pub(
    name: str,
    data_date: date,
    *,
    status: SchedulePublicationStatus = COMPLETE,
    admitted: int = 0,
    supersedes: str | None = None,
) -> CurrencyPublication:
    return CurrencyPublication(
        publication_id=f"spub_{name}",
        status=status,
        data_date=data_date,
        admitted_at=datetime(2027, 3, 1, 9, admitted),
        supersedes_publication_id=None if supersedes is None else f"spub_{supersedes}",
    )


def _event(seq: int, action: BaselineAction, *, label: str | None = None) -> BaselineEvent:
    return BaselineEvent(
        seq=seq,
        baseline_id="sbl_b1",
        publication_id="spub_B1",
        action=action,
        recorded_at=datetime(2027, 3, 2, 9, seq),
        type=BaselineType.APPROVED_UPDATE,
        label=label,
    )


APPROVED: Final = [_event(1, BaselineAction.APPROVE, label="BL-0")]
REVOKED: Final = [*APPROVED, _event(2, BaselineAction.REVOKE)]
PROPOSED: Final = [_event(1, BaselineAction.PROPOSE)]

#: vector -> (publications, baseline events, expected current, expected ambiguity)
VECTORS: Final = {
    "C1": ([pub("P1", JAN31), pub("P2", JAN31, admitted=5)], [], "spub_P2", True),
    "C2": ([pub("P1", JAN31), pub("P2", JAN31, admitted=5, supersedes="P1")], [], "spub_P2", False),
    "C3": (
        [pub("P1", JAN31), pub("P2", FEB28, status=SchedulePublicationStatus.REVIEW_REQUIRED)],
        [],
        "spub_P1",
        False,
    ),
    "C4": (
        [
            pub("P1", JAN31),
            pub("P2", FEB28, status=SchedulePublicationStatus.FAILED, supersedes="P1"),
        ],
        [],
        "spub_P1",
        False,
    ),
    "C5": ([pub("P1", JAN31), pub("B1", FEB28)], APPROVED, "spub_P1", False),
    "C6": ([pub("B1", FEB28)], APPROVED, None, False),
    "C7": ([pub("P1", JAN31), pub("B1", FEB28)], REVOKED, "spub_B1", False),
    "C8": ([pub("P1", JAN31), pub("B1", FEB28)], PROPOSED, "spub_B1", False),
}


@pytest.mark.parametrize("vector", sorted(VECTORS))
def test_current_standard_update_vectors(vector: str) -> None:
    publications, events, current, ambiguity = VECTORS[vector]
    eligible = {item.publication_id for item in publications if item.eligible}
    views = baseline_status(events, eligible_publication_ids=eligible)
    baselines = {view.publication_id for view in views.values() if view.effective}
    assert current_standard_update(publications, baselines) == CurrentStandardUpdate(
        current, same_data_date_ambiguity=ambiguity
    )


def test_order_key_is_data_date_then_admission_then_id() -> None:
    a = pub("A", JAN31, admitted=5)
    b = pub("B", JAN31, admitted=5)
    c = pub("C", JAN31, admitted=4)
    assert sorted([a, b, c], key=CurrencyPublication.order_key) == [c, a, b]
    assert a.order_key() == PublicationOrderKey(JAN31, datetime(2027, 3, 1, 9, 5), "spub_A")
    assert current_standard_update([a, b, c]).publication_id == "spub_B"


def test_ineligible_publications_are_never_current_and_never_displace() -> None:
    partial = pub("P1", JAN31, status=SchedulePublicationStatus.PARTIAL)
    for status in (
        SchedulePublicationStatus.QUEUED,
        SchedulePublicationStatus.PROCESSING,
        SchedulePublicationStatus.REVIEW_REQUIRED,
        SchedulePublicationStatus.FAILED,
    ):
        late = pub("P2", FEB28, status=status, supersedes="P1")
        assert current_standard_update([partial, late]).publication_id == "spub_P1"
    assert current_standard_update([]) == CurrentStandardUpdate(None, False)
    with pytest.raises(ValueError, match="eligible"):
        CurrencyPublication(
            "spub_X", SchedulePublicationStatus.QUEUED, None, datetime(2027, 1, 1)
        ).order_key()
