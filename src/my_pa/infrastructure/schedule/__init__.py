"""CPM Workbench Full-Schedule parsing (`p6_full_v1`); no logic here.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`.
Re-exports the frozen profile and limits; the WP-02 parser change adds
`parse_full_schedule` to this re-export list.
"""

from my_pa.infrastructure.schedule.full_profile import (
    P6_FULL_V1,
    PRODUCTION_LIMITS,
    ScheduleParseLimits,
)

__all__ = ["P6_FULL_V1", "PRODUCTION_LIMITS", "ScheduleParseLimits"]
