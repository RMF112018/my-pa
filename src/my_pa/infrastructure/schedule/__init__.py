"""CPM Workbench Full-Schedule parsing (`p6_full_v1`); no logic here.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`.
Re-exports the single entry point `parse_full_schedule`, the frozen profile and
the limits.
"""

from my_pa.infrastructure.schedule.full_profile import (
    P6_FULL_V1,
    PRODUCTION_LIMITS,
    ScheduleParseLimits,
    parse_full_schedule,
)

__all__ = ["P6_FULL_V1", "PRODUCTION_LIMITS", "ScheduleParseLimits", "parse_full_schedule"]
