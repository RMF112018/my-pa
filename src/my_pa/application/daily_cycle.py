"""One run of the daily Morning Intelligence cycle: close stale cycles, then begin today's.

ADR-010 amendment of 2026-11-20. The worker plane (`apps/worker.py run --plane
cycles`) decides *when* a run is due (`domain.intelligence.daily_cycle.due`) and
holds the single-flight lock; this module is *what* a run does.

* **Close.** Every `open` or `running` cycle of the Principal dated before the
  run's business date is closed in its own transaction (`close_cycle`). A
  failure is counted, never raised, so one bad cycle neither blocks the others
  nor the begin step. A cycle that failed to close is still open and is found
  again by the next run.
* **Begin.** Always attempted, whatever the close step did, through
  `ApplicationService.invoke` -- the same authorize-and-audit path every local
  caller takes, with the operator Principal, purpose `report_authoring`, local
  transport and no client grant set. The deterministic key makes a repeated
  run for the same date a replay, and `reports.begin_cycle`'s one-open-cycle
  rule makes it converge with a ChatLLM fallback in either order.

The close step has no capability and writes no audit row; the cycle row's
`state`, `finished_at` and `version` and the run's log line are its record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from my_pa.application.commands import BeginIntelligenceCycle
from my_pa.application.intelligence import (
    CycleClosureOutcome,
    IntelligenceStore,
    close_cycle,
    stale_open_cycles,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import CYCLE_MORNING_INTELLIGENCE
from my_pa.domain.intelligence.daily_cycle import (
    SCHEDULED_AUTOMATION_PLATFORM,
    scheduled_idempotency_key,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = ["DailyCycleRun", "DailyCycleRunner"]


@dataclass(frozen=True, slots=True)
class DailyCycleRun:
    """What one run did. Counts, one cycle identifier and one error code; no content."""

    business_date: date
    closed_complete: int = 0
    closed_cancelled: int = 0
    already_closed: int = 0
    close_failed: int = 0
    cycle_run_id: str | None = None
    created: bool = False
    replayed: bool = False
    begin_error: str | None = None

    @property
    def begun(self) -> bool:
        """Whether the begin step produced (or replayed) a cycle for the date."""
        return self.cycle_run_id is not None

    def log_fields(self) -> dict[str, object]:
        """The structured log line. Identifiers, counts and codes only."""
        return {
            "event": "cycle_scheduler.run",
            "business_date": self.business_date.isoformat(),
            "closed_complete": self.closed_complete,
            "closed_cancelled": self.closed_cancelled,
            "already_closed": self.already_closed,
            "close_failed": self.close_failed,
            "cycle_run_id": self.cycle_run_id,
            "created": self.created,
            "replayed": self.replayed,
            "begin_error": self.begin_error,
        }


class DailyCycleRunner:
    """Run the close and begin steps for one business date, as one Principal."""

    def __init__(
        self,
        *,
        service: ApplicationService,
        unit_of_work: Callable[[], UnitOfWork],
        principal: Principal,
        clock: Callable[[], datetime],
    ) -> None:
        self._service = service
        self._unit_of_work = unit_of_work
        self._principal = principal
        self._clock = clock

    def __call__(self, business_date: date) -> DailyCycleRun:
        counts = dict.fromkeys(CycleClosureOutcome, 0)
        failed = 0
        try:
            stale = self._stale(business_date)
        except Exception:
            # Nothing listed is nothing closed; the begin step still runs and
            # the next run lists again.
            stale = ()
            failed += 1
        for stale_id in stale:
            try:
                counts[self._close(stale_id)] += 1
            except Exception:
                failed += 1
        cycle_run_id, created, replayed, error = self._begin(business_date)
        return DailyCycleRun(
            business_date=business_date,
            closed_complete=counts[CycleClosureOutcome.COMPLETE],
            closed_cancelled=counts[CycleClosureOutcome.CANCELLED],
            already_closed=counts[CycleClosureOutcome.ALREADY_CLOSED]
            + counts[CycleClosureOutcome.MISSING],
            close_failed=failed,
            cycle_run_id=cycle_run_id,
            created=created,
            replayed=replayed,
            begin_error=error,
        )

    def _store(self, unit_of_work: UnitOfWork) -> IntelligenceStore:
        return cast(IntelligenceStore, unit_of_work.intelligence_for(self._principal.principal_id))

    def _stale(self, business_date: date) -> tuple[str, ...]:
        with self._unit_of_work() as unit_of_work:
            return stale_open_cycles(
                self._store(unit_of_work),
                principal_id=self._principal.principal_id,
                business_date=business_date,
            )

    def _close(self, cycle_run_id: str) -> CycleClosureOutcome:
        with self._unit_of_work() as unit_of_work:
            return close_cycle(
                self._store(unit_of_work),
                principal_id=self._principal.principal_id,
                cycle_run_id=cycle_run_id,
                at=self._clock(),
            ).outcome

    def _begin(self, business_date: date) -> tuple[str | None, bool, bool, str | None]:
        command = BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date=business_date.isoformat(),
            idempotency_key=scheduled_idempotency_key(business_date),
            automation_platform=SCHEDULED_AUTOMATION_PLATFORM,
        )
        try:
            envelope = self._service.invoke(
                RequestMetadata(
                    request_id=issue_identifier(IdKind.CORRELATION),
                    capability=command.capability,
                    purpose=Purpose.REPORT_AUTHORING,
                    principal_id=self._principal.principal_id,
                    requested_at=self._clock(),
                ),
                command,
                principal=self._principal,
            )
        except Exception:
            # `invoke` returns every classified failure; this is only a
            # composition fault, reported as a code and never as a message.
            return None, False, False, "internal_error"
        if envelope.error is not None:
            return None, False, False, envelope.error.code.value
        result = envelope.result or {}
        cycle_run_id = result.get("cycle_run_id")
        return (
            cycle_run_id if isinstance(cycle_run_id, str) else None,
            bool(result.get("created")),
            bool(result.get("replayed")),
            None,
        )
