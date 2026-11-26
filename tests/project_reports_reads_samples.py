"""Synthetic sample payloads for the 5 project-report reads (WP4P-S4).

The transport-parity, negative-evidence and policy suites keep one valid
payload per handler-backed capability. Every id, family and term here is
synthetic; each payload passes its command's own validation (WP4P-W1 design
section 2.4), so a transport reaches authorization and the read switch's
composition check (off in those worlds).
"""

from __future__ import annotations

from typing import Any, Final

from my_pa.application.commands import (
    CompareProjectReports,
    ProjectReportRecordHistory,
    ProjectReportsCatalog,
    ProjectReportsCoverage,
    QueryProjectReports,
)
from my_pa.domain.identity.operation import Capability

__all__ = [
    "PROJECT_REPORTS_READ_CAPABILITIES",
    "project_reports_commands",
    "project_reports_payloads",
]

#: The 5 reads, each withheld unless `MY_PA_PROJECT_REPORTS_ENABLED` is on.
PROJECT_REPORTS_READ_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.PROJECT_REPORTS_CATALOG,
        Capability.PROJECT_REPORTS_QUERY,
        Capability.PROJECT_REPORTS_RECORD_HISTORY,
        Capability.PROJECT_REPORTS_COMPARE,
        Capability.PROJECT_REPORTS_COVERAGE,
    }
)

_SERIES: Final = "prser_" + "0" * 32


def project_reports_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload per read; `tag` (lowercase alphanumeric) marks the suite."""
    project = f"prj_{tag}project01"
    return {
        Capability.PROJECT_REPORTS_CATALOG: {"project_ids": [project]},
        Capability.PROJECT_REPORTS_QUERY: {
            "project_id": project,
            "record_family": "rfis",
            "limit": 5,
        },
        Capability.PROJECT_REPORTS_RECORD_HISTORY: {"record_ids": [f"prrec_{tag}record0001"]},
        Capability.PROJECT_REPORTS_COMPARE: {"series_id": _SERIES},
        Capability.PROJECT_REPORTS_COVERAGE: {"project_ids": [project]},
    }


def project_reports_commands(tag: str) -> dict[Capability, Any]:
    """The same samples as built commands."""
    project = f"prj_{tag}project01"
    return {
        Capability.PROJECT_REPORTS_CATALOG: ProjectReportsCatalog(project_ids=(project,)),
        Capability.PROJECT_REPORTS_QUERY: QueryProjectReports(
            project_id=project, record_family="rfis", limit=5
        ),
        Capability.PROJECT_REPORTS_RECORD_HISTORY: ProjectReportRecordHistory(
            record_ids=(f"prrec_{tag}record0001",)
        ),
        Capability.PROJECT_REPORTS_COMPARE: CompareProjectReports(series_id=_SERIES),
        Capability.PROJECT_REPORTS_COVERAGE: ProjectReportsCoverage(project_ids=(project,)),
    }
