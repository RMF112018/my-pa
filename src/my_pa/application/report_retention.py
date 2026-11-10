"""Purge eligibility of one general report under the owner's retention policy (WP05b B6).

`report_purge_eligibility` is the one place the `reports.retention.get`
handler (WP05b W4) computes eligibility: it reads the owner's current policy
(`GeneralReportRepository.retention_policy`) and the report's lifecycle state,
hold cache and lifecycle ledger (`retention_eligibility_inputs`), starts the
clock with the named strategy (`retention_clock_start`), and evaluates the
pure `purge_eligibility` with `now` -- the caller passes the request's
`authorization.at`, never a wall clock read here.

**Informational only.** The clock start is an OPEN OPERATOR DECISION
(isolated as `RetentionClockStart`); nothing consumes the answer to delete
anything, and purge is not implemented. Retention never gates an update,
archive, restore or trash.
"""

from __future__ import annotations

from datetime import datetime

from my_pa.contracts.ports import GeneralReportRepository
from my_pa.domain.reports.custody import (
    PurgeEligibility,
    RetentionClockStart,
    purge_eligibility,
    retention_clock_start,
)

__all__ = ["report_purge_eligibility"]


def report_purge_eligibility(
    repository: GeneralReportRepository,
    report_id: str,
    *,
    principal_id: str,
    now: datetime,
    strategy: RetentionClockStart = RetentionClockStart.MOST_RECENT_TRASH_EVENT,
) -> PurgeEligibility | None:
    """The report's purge eligibility at `now`, or `None` when it is foreign or missing."""
    inputs = repository.retention_eligibility_inputs(report_id, principal_id=principal_id)
    if inputs is None:
        return None
    policy = repository.retention_policy(principal_id=principal_id, history_limit=1)
    return purge_eligibility(
        period=policy.period,
        held=inputs.held,
        lifecycle_state=inputs.lifecycle_state,
        clock_start=retention_clock_start(
            strategy, inputs.lifecycle_state, inputs.lifecycle_events
        ),
        now=now,
        strategy=strategy,
    )
