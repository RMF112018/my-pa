"""The one home of the Schedule Scenarios S6-3 audit vocabulary (contract section 15.13).

Revision B (`b77334135653`) restates `capability_is_known` and
`purpose_is_known` with the 26 plane capability names and the 3 plane
purposes, and the S6-3 package I10-A declares every one of them in the same
change, so there is no schema-ahead gap. Earlier revisions' vocabulary tests
set these names aside as admitted later, exactly as they set aside the CPM
Workbench S5b-2 names. Frozen literals, never derived from the enums they are
checked against. This is a helper module, not a test module: pytest does not
collect it.
"""

from __future__ import annotations

from typing import Final

S63_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "schedule_scenarios.create",
        "schedule_scenario_versions.create",
        "schedule_cpm_runs.create",
        "schedule_scenario_outputs.record",
        "schedule_baselines.propose",
        "schedule_baselines.withdraw",
        "schedule_baselines.approve",
        "schedule_baselines.reject",
        "schedule_baselines.revoke",
        "schedule_baselines.set_governing",
        "schedule_scenarios.list",
        "schedule_scenarios.read",
        "schedule_scenario_versions.read",
        "schedule_scenario_versions.activities",
        "schedule_scenario_versions.relationships",
        "schedule_scenario_versions.changes",
        "schedule_cpm_runs.read",
        "schedule_cpm_runs.activities",
        "schedule_scenario_outputs.list",
        "schedule_scenario_outputs.read",
        "schedule_series.current",
        "schedule_series.match_decisions",
        "schedule_baselines.list",
        "schedule_baselines.read",
        "schedule_baselines.governing",
        "schedule_baselines.compare",
    }
)
S63_PURPOSES: Final[frozenset[str]] = frozenset(
    {"schedule_analysis_authoring", "schedule_analysis_read", "schedule_baseline_approval"}
)
