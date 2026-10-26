"""The client lineage write budgets, record lineage S3.1 (S3.1 contract section 4.8).

Every **non-attested** lineage write -- the 14 open writes and the 2 recorded
Issue writes -- made by a client channel is counted against 2 rolling budgets
of its **writer bucket**, `(decision_channel, asserting_client_id)` (each
remote OAuth client one bucket; every stdio or unstamped local caller the one
`local_unattested` bucket), and 1 budget of the Principal:
`CLIENT_LINEAGE_WRITES_PER_HOUR`, `CLIENT_LINEAGE_WRITES_PER_DAY` and
`PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY`. Reaching any of them answers
`rate_limited` / `lineage_write_budget` and the caller's transaction rolls back,
so nothing is written. The human channel is never counted or limited.

**Where the check runs.** After the commit mark (S3 section 6.2 step 1b) and
after every validation, immediately before a write's first fact row (S3.1
section 6.2 step 7). The mark's allocator row stays locked until commit, so a
Principal's lineage writers serialize there and the counts read here cannot
move before this writer commits: the bound is race-free without a counter
table. Every refusal -- a hidden or absent subject, a transition, evidence or
accepted-lineage refusal -- is answered before this check, so a refusal never
consumes budget, and a replay returns before it and consumes nothing.

The counts are over completed `lineage_write_requests` rows with a client
`decision_channel` (S3.1 section 5.2); this request's own reservation is not
yet completed, so it is not among them.

Nothing here reads a client's declaration of who directed a write: a bound
is the same whatever a client says about that.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from my_pa.application.errors import RateLimitedError, SafeDetail
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.lineage.vocabulary import (
    CLIENT_DECISION_CHANNELS,
    CLIENT_LINEAGE_WRITES_PER_DAY,
    CLIENT_LINEAGE_WRITES_PER_HOUR,
    PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY,
)

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority, LineageProvenance
    from my_pa.contracts.ports import UnitOfWork

__all__ = ["require_client_write_budget"]

_HOUR: Final = timedelta(hours=1)
_DAY: Final = timedelta(hours=24)


def require_client_write_budget(
    uow: UnitOfWork,
    principal_id: str,
    writer: LineageProvenance | LineageAuthority,
    asserting_client_id: str | None,
    at: datetime,
) -> None:
    """Refuse a client write past a section 4.8 bound; the human channel always passes.

    `writer` is the write's derived provenance (or, for the recorded Issue
    writes, its authority pair) and `asserting_client_id` its server-derived
    OAuth client. `at` is the request's authorization instant. The caller
    holds the Principal's commit mark.
    """
    channel = writer.decision_channel.value
    if channel not in CLIENT_DECISION_CHANNELS:
        return
    instant = ensure_utc(at)
    budget = uow.issues.client_write_budget(
        principal_id,
        decision_channel=channel,
        asserting_client_id=asserting_client_id,
        hour_since=instant - _HOUR,
        day_since=instant - _DAY,
    )
    if (
        budget.bucket_hour >= CLIENT_LINEAGE_WRITES_PER_HOUR
        or budget.bucket_day >= CLIENT_LINEAGE_WRITES_PER_DAY
        or budget.principal_day >= PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY
    ):
        raise RateLimitedError(SafeDetail.LINEAGE_WRITE_BUDGET)
