"""Synthetic sample payloads for the 26 Schedule Scenarios S6-3 capabilities.

The transport-parity and negative-evidence suites keep one valid payload per
handler-backed capability. Every identifier here is synthetic and names no row;
each payload passes its command's own validation (schedule-scenarios contract
section 15.5), so a transport reaches authorization and the plane switch.
"""

from __future__ import annotations

from typing import Any, Final

from my_pa.application.commands import (
    ApproveScheduleBaseline,
    CompareScheduleBaseline,
    CreateScheduleCpmRun,
    CreateScheduleScenario,
    CreateScheduleScenarioVersion,
    ListScheduleBaselines,
    ListScheduleCpmRunActivities,
    ListScheduleScenarioActivities,
    ListScheduleScenarioChanges,
    ListScheduleScenarioOutputs,
    ListScheduleScenarioRelationships,
    ListScheduleScenarios,
    ListScheduleSeriesMatchDecisions,
    ProposeScheduleBaseline,
    ReadGoverningScheduleBaseline,
    ReadScheduleBaseline,
    ReadScheduleCpmRun,
    ReadScheduleScenario,
    ReadScheduleScenarioOutput,
    ReadScheduleScenarioVersion,
    ReadScheduleSeriesCurrent,
    RecordScheduleScenarioOutput,
    RejectScheduleBaseline,
    RevokeScheduleBaseline,
    SetGoverningScheduleBaseline,
    WithdrawScheduleBaseline,
)
from my_pa.domain.identity.operation import Capability

__all__ = [
    "SCHEDULE_SCENARIO_CAPABILITIES",
    "SCHEDULE_SCENARIO_COMMAND_TYPES",
    "scenario_commands",
    "scenario_payloads",
]

#: The command class of each of the 26 plane capabilities.
SCHEDULE_SCENARIO_COMMAND_TYPES: Final[dict[Capability, type[Any]]] = {
    Capability.SCHEDULE_SCENARIOS_CREATE: CreateScheduleScenario,
    Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE: CreateScheduleScenarioVersion,
    Capability.SCHEDULE_CPM_RUNS_CREATE: CreateScheduleCpmRun,
    Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD: RecordScheduleScenarioOutput,
    Capability.SCHEDULE_BASELINES_PROPOSE: ProposeScheduleBaseline,
    Capability.SCHEDULE_BASELINES_WITHDRAW: WithdrawScheduleBaseline,
    Capability.SCHEDULE_BASELINES_APPROVE: ApproveScheduleBaseline,
    Capability.SCHEDULE_BASELINES_REJECT: RejectScheduleBaseline,
    Capability.SCHEDULE_BASELINES_REVOKE: RevokeScheduleBaseline,
    Capability.SCHEDULE_BASELINES_SET_GOVERNING: SetGoverningScheduleBaseline,
    Capability.SCHEDULE_SCENARIOS_LIST: ListScheduleScenarios,
    Capability.SCHEDULE_SCENARIOS_READ: ReadScheduleScenario,
    Capability.SCHEDULE_SCENARIO_VERSIONS_READ: ReadScheduleScenarioVersion,
    Capability.SCHEDULE_SCENARIO_VERSIONS_ACTIVITIES: ListScheduleScenarioActivities,
    Capability.SCHEDULE_SCENARIO_VERSIONS_RELATIONSHIPS: ListScheduleScenarioRelationships,
    Capability.SCHEDULE_SCENARIO_VERSIONS_CHANGES: ListScheduleScenarioChanges,
    Capability.SCHEDULE_CPM_RUNS_READ: ReadScheduleCpmRun,
    Capability.SCHEDULE_CPM_RUNS_ACTIVITIES: ListScheduleCpmRunActivities,
    Capability.SCHEDULE_SCENARIO_OUTPUTS_LIST: ListScheduleScenarioOutputs,
    Capability.SCHEDULE_SCENARIO_OUTPUTS_READ: ReadScheduleScenarioOutput,
    Capability.SCHEDULE_SERIES_CURRENT: ReadScheduleSeriesCurrent,
    Capability.SCHEDULE_SERIES_MATCH_DECISIONS: ListScheduleSeriesMatchDecisions,
    Capability.SCHEDULE_BASELINES_LIST: ListScheduleBaselines,
    Capability.SCHEDULE_BASELINES_READ: ReadScheduleBaseline,
    Capability.SCHEDULE_BASELINES_GOVERNING: ReadGoverningScheduleBaseline,
    Capability.SCHEDULE_BASELINES_COMPARE: CompareScheduleBaseline,
}
SCHEDULE_SCENARIO_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    SCHEDULE_SCENARIO_COMMAND_TYPES
)

_WORKWEEK: Final = [[[480, 1020]]] * 5 + [[], []]


def scenario_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload per plane capability; `tag` (alphanumeric) marks the suite."""
    publication = f"spub_{tag}scen0001"
    scenario = f"sscn_{tag}scen0001"
    version = f"sscv_{tag}scen0001"
    run = f"scpm_{tag}scen0001"
    output = f"ssco_{tag}scen0001"
    baseline = f"sbl_{tag}scen0001"
    project = f"prj_{tag}scen0001"
    series = f"sser_{tag}scen0001"
    reason = "Synthetic sample reason"

    def key(name: str) -> str:
        return f"{tag}-{name}-0001"

    return {
        Capability.SCHEDULE_SCENARIOS_CREATE: {
            "from_publication_id": publication,
            "name": "Synthetic scenario",
            "label": "what_if",
            "minutes_per_source_unit": 480,
            "calendars": [{"key": "std", "week": _WORKWEEK, "exceptions": []}],
            "default_calendar": "std",
            "idempotency_key": key("scenario-create"),
        },
        Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE: {
            "scenario_id": scenario,
            "expected_head_version_no": 1,
            "label": "what_if",
            "change_set": [{"op": "data_date.set", "data_date": "2026-05-05T08:00"}],
            "idempotency_key": key("version-create"),
        },
        Capability.SCHEDULE_CPM_RUNS_CREATE: {
            "version_id": version,
            "idempotency_key": key("cpm-run"),
        },
        Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD: {
            "document": {"version_id": version},
            "idempotency_key": key("output-record"),
        },
        Capability.SCHEDULE_BASELINES_PROPOSE: {
            "publication_id": publication,
            "type": "contract",
            "reason": reason,
            "idempotency_key": key("baseline-propose"),
        },
        Capability.SCHEDULE_BASELINES_WITHDRAW: {
            "baseline_id": baseline,
            "reason": reason,
            "idempotency_key": key("baseline-withdraw"),
        },
        Capability.SCHEDULE_BASELINES_APPROVE: {
            "publication_id": publication,
            "type": "contract",
            "approval_reference": "Synthetic NTP 0001",
            "effective_from": "2026-05-04",
            "reason": reason,
            "idempotency_key": key("baseline-approve"),
        },
        Capability.SCHEDULE_BASELINES_REJECT: {
            "baseline_id": baseline,
            "reason": reason,
            "idempotency_key": key("baseline-reject"),
        },
        Capability.SCHEDULE_BASELINES_REVOKE: {
            "baseline_id": baseline,
            "reason": reason,
            "idempotency_key": key("baseline-revoke"),
        },
        Capability.SCHEDULE_BASELINES_SET_GOVERNING: {
            "project_id": project,
            "baseline_id": baseline,
            "expected_governing_baseline_id": None,
            "reason": reason,
            "idempotency_key": key("baseline-governing"),
        },
        Capability.SCHEDULE_SCENARIOS_LIST: {"project_id": project},
        Capability.SCHEDULE_SCENARIOS_READ: {"scenario_id": scenario},
        Capability.SCHEDULE_SCENARIO_VERSIONS_READ: {"version_id": version},
        Capability.SCHEDULE_SCENARIO_VERSIONS_ACTIVITIES: {"version_id": version},
        Capability.SCHEDULE_SCENARIO_VERSIONS_RELATIONSHIPS: {"version_id": version},
        Capability.SCHEDULE_SCENARIO_VERSIONS_CHANGES: {"version_id": version},
        Capability.SCHEDULE_CPM_RUNS_READ: {"cpm_run_id": run},
        Capability.SCHEDULE_CPM_RUNS_ACTIVITIES: {"cpm_run_id": run},
        Capability.SCHEDULE_SCENARIO_OUTPUTS_LIST: {"version_id": version},
        Capability.SCHEDULE_SCENARIO_OUTPUTS_READ: {"output_id": output},
        Capability.SCHEDULE_SERIES_CURRENT: {"series_id": series},
        Capability.SCHEDULE_SERIES_MATCH_DECISIONS: {"project_id": project},
        Capability.SCHEDULE_BASELINES_LIST: {"project_id": project},
        Capability.SCHEDULE_BASELINES_READ: {"baseline_id": baseline},
        Capability.SCHEDULE_BASELINES_GOVERNING: {"project_id": project},
        Capability.SCHEDULE_BASELINES_COMPARE: {
            "baseline_id": baseline,
            "to_publication_id": f"spub_{tag}scen0002",
        },
    }


def scenario_commands(tag: str) -> dict[Capability, Any]:
    """The same samples as built commands."""
    return {
        capability: SCHEDULE_SCENARIO_COMMAND_TYPES[capability](**payload)
        for capability, payload in scenario_payloads(tag).items()
    }
