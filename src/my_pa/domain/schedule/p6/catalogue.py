"""P6 XER field cross-reference catalogue `p6-field-catalogue-v1` (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` section 6 (and the
table classes of section 5.1). The tables below are the contract's tables
6.3-6.10 cell for cell, and the two optional-field lists of 6.7 and 6.8 name
for name; `render_section` turns them back into the contract's Markdown rows
and a test compares the two, so the contract and this module cannot drift
(acceptance A2). Every `CatalogueField` is derived from those cells by the
rules in `_build`; nothing here reads a file (the domain package may not).

Where the contract states no value type (the 6.7 and 6.8 optional lists, the
6.9 rows without a type column and the 6.10 tables), the type follows the
field name: `*_flag` is `flag`, `*_date` is `ts`, `*_id` (and `*_id1`,
`*_id2`) is `id`, anything else is `text(4000)`. An uncatalogued value is
always text (section 7.7), so this only ever narrows what is accepted.

Pure, standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "CATALOGUE",
    "CATALOGUE_VERSION",
    "DOCUMENTED_TABLES",
    "ENUMERATIONS",
    "OPTIONAL_TABLES",
    "PROJECT_OPTIONAL_FIELDS",
    "REQUIRED_TABLES",
    "SCHEDOPTIONS_OPTIONAL_FIELDS",
    "TABLE_ENTITY",
    "TESTED_VERSION_PREFIX",
    "TOLERATED_TABLES",
    "UDF_OWNERS",
    "CatalogueField",
    "EntityKind",
    "Tier",
    "ValueType",
    "catalogue_field",
    "is_catalogued_table",
    "render_section",
    "table_fields",
]

CATALOGUE_VERSION: Final = "p6-field-catalogue-v1"
#: Section 5.3: the export versions the catalogue was tested against (the sample, 26.x).
TESTED_VERSION_PREFIX: Final = "26."

MINUS: Final = "\u2212"


class Tier(StrEnum):
    """Section 5.1 tiers (`O+`/`O-` are the optional default-capture split of 6.2)."""

    REQUIRED = "R"
    TOLERATED = "T"
    OPTIONAL_DEFAULT = "O+"
    OPTIONAL = "O" + MINUS
    NEVER = "N"
    DERIVED = "V"


class ValueType(StrEnum):
    """Section 6.2 `Type` column."""

    ID = "id"
    TEXT = "text"
    NAME = "name"
    ENUM = "enum"
    FLAG = "flag"
    TS = "ts"
    HOURS = "hours"
    NUM = "num"
    INT = "int"
    BLOB = "blob"


class EntityKind(StrEnum):
    """Section 7.3 entity kinds."""

    PROJECT = "project"
    WBS = "wbs"
    ACTIVITY = "activity"
    RELATIONSHIP = "relationship"
    CALENDAR = "calendar"
    RESOURCE = "resource"
    ASSIGNMENT = "assignment"


#: Section 5.1 table classes.
REQUIRED_TABLES: Final = ("PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED")
TOLERATED_TABLES: Final = (
    "SCHEDOPTIONS",
    "UDFTYPE",
    "UDFVALUE",
    "ACTVTYPE",
    "ACTVCODE",
    "TASKACTV",
    "UDFCODE",
    "RSRC",
    "TASKRSRC",
)

#: Section 6.9: the owners a UDF type may name (`udf:<owner>:<label>`).
UDF_OWNERS: Final[Mapping[str, EntityKind]] = {
    "TASK": EntityKind.ACTIVITY,
    "PROJWBS": EntityKind.WBS,
    "PROJECT": EntityKind.PROJECT,
    "TASKRSRC": EntityKind.ASSIGNMENT,
    "RSRC": EntityKind.RESOURCE,
}

#: Contract section 6.3.
TASK_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Unit", "Tier", "Use", "Target", "Seen"),
    (
        "task_id",
        "Activity/ObjectId",
        "id",
        "—",
        "R",
        "—",
        "`p6_task_id` (provenance; never a cross-version key)",
        "S",
    ),
    (
        "proj_id",
        "Activity/ProjectObjectId",
        "id",
        "—",
        "R",
        "—",
        "derived → must equal `PROJECT.proj_id`",
        "S",
    ),
    (
        "wbs_id",
        "Activity/WBSObjectId",
        "id",
        "—",
        "R",
        "E",
        "`p6_wbs_id`; derived → `wbs_path`",
        "S",
    ),
    ("clndr_id", "Activity/CalendarObjectId", "id", "—", "R", "E", "`p6_calendar_id`", "S"),
    (
        "phys_complete_pct",
        "Activity/PhysicalPercentComplete",
        "num",
        "%",
        "T",
        "Δ",
        "`physical_pct`",
        "S",
    ),
    ("rev_fdbk_flag", "Activity/IsNewFeedback", "flag", "—", "O\u2212", "—", "FS", "S"),
    ("est_wt", "Activity/EstimatedWeight", "num", "—", "O\u2212", "—", "FS", "S"),
    ("lock_plan_flag", "—", "flag", "—", "O\u2212", "—", "FS", "S"),
    (
        "auto_compute_act_flag",
        "Activity/AutoComputeActuals",
        "flag",
        "—",
        "O\u2212",
        "—",
        "FS",
        "S",
    ),
    (
        "complete_pct_type",
        "Activity/PercentCompleteType",
        "enum",
        "—",
        "T",
        "—",
        "`percent_complete_type`",
        "S",
    ),
    ("task_type", "Activity/Type", "enum", "—", "R", "E Δ", "`task_type`", "S"),
    ("duration_type", "Activity/DurationType", "enum", "—", "T", "Δ", "`duration_type`", "S"),
    ("status_code", "Activity/Status", "enum", "—", "R", "E Δ", "`status_code`", "S"),
    (
        "task_code",
        "Activity/Id",
        "text(40)",
        "—",
        "R",
        "E Δ",
        "`activity_id`; Stable Activity key",
        "S",
    ),
    ("task_name", "Activity/Name", "name", "—", "R", "E Δ", "`activity_name`", "S"),
    ("rsrc_id", "Activity/PrimaryResourceObjectId", "id", "—", "O\u2212", "—", "FS", "S"),
    (
        "total_float_hr_cnt",
        "— (absent in XML [S]; `TotalFloat` [D])",
        "hours",
        "h",
        "T",
        "Δ",
        "`total_float_hours`",
        "S",
    ),
    ("free_float_hr_cnt", "— (`FreeFloat` [D])", "hours", "h", "T", "Δ", "`free_float_hours`", "S"),
    (
        "remain_drtn_hr_cnt",
        "Activity/RemainingDuration",
        "hours",
        "h",
        "R",
        "E Δ",
        "`remaining_hours`",
        "S",
    ),
    ("act_work_qty", "Activity/ActualLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    ("remain_work_qty", "Activity/RemainingLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    ("target_work_qty", "Activity/PlannedLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    (
        "target_drtn_hr_cnt",
        "Activity/PlannedDuration",
        "hours",
        "h",
        "R",
        "E Δ",
        "`original_hours`",
        "S",
    ),
    ("target_equip_qty", "Activity/PlannedNonLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    ("act_equip_qty", "Activity/ActualNonLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    ("remain_equip_qty", "Activity/RemainingNonLaborUnits", "num", "h", "O\u2212", "—", "FS", "S"),
    (
        "cstr_date",
        "Activity/PrimaryConstraintDate",
        "ts",
        "—",
        "R (empty allowed)",
        "E Δ",
        "`constraint_date`",
        "S",
    ),
    (
        "act_start_date",
        "Activity/ActualStartDate",
        "ts",
        "—",
        "R (empty allowed)",
        "E Δ",
        "`actual_start`",
        "S",
    ),
    (
        "act_end_date",
        "Activity/ActualFinishDate",
        "ts",
        "—",
        "R (empty allowed)",
        "E Δ",
        "`actual_finish`",
        "S",
    ),
    ("late_start_date", "Activity/LateStartDate", "ts", "—", "T", "Δ", "`late_start`", "S"),
    ("late_end_date", "Activity/LateFinishDate", "ts", "—", "T", "Δ", "`late_finish`", "S"),
    ("expect_end_date", "Activity/ExpectedFinishDate", "ts", "—", "O+", "—", "FS", "S"),
    (
        "early_start_date",
        "Activity/EarlyStartDate",
        "ts",
        "—",
        "R",
        "Δ",
        "`early_start`; derived → `start_at`",
        "S",
    ),
    (
        "early_end_date",
        "Activity/EarlyFinishDate",
        "ts",
        "—",
        "R",
        "Δ",
        "`early_finish`; derived → `finish_at`",
        "S",
    ),
    (
        "restart_date",
        "Activity/RemainingEarlyStartDate",
        "ts",
        "—",
        "T",
        "—",
        "`remaining_early_start`",
        "S",
    ),
    (
        "reend_date",
        "Activity/RemainingEarlyFinishDate",
        "ts",
        "—",
        "T",
        "—",
        "`remaining_early_finish`",
        "S",
    ),
    ("target_start_date", "Activity/PlannedStartDate", "ts", "—", "T", "Δ", "`planned_start`", "S"),
    ("target_end_date", "Activity/PlannedFinishDate", "ts", "—", "T", "Δ", "`planned_finish`", "S"),
    ("rem_late_start_date", "Activity/RemainingLateStartDate", "ts", "—", "O+", "—", "FS", "S"),
    ("rem_late_end_date", "Activity/RemainingLateFinishDate", "ts", "—", "O+", "—", "FS", "S"),
    (
        "cstr_type",
        "Activity/PrimaryConstraintType",
        "enum",
        "—",
        "R (empty allowed)",
        "E Δ",
        "`constraint_type`",
        "S",
    ),
    ("priority_type", "Activity/LevelingPriority", "enum", "—", "O\u2212", "—", "FS", "S"),
    ("suspend_date", "Activity/SuspendDate", "ts", "—", "O+", "—", "FS", "S"),
    ("resume_date", "Activity/ResumeDate", "ts", "—", "O+", "—", "FS", "S"),
    ("float_path", "—", "int", "—", "O\u2212", "—", "FS", "S"),
    ("float_path_order", "—", "int", "—", "O\u2212", "—", "FS", "S"),
    (
        "guid",
        "Activity/GUID",
        "text(22)",
        "—",
        "T",
        "—",
        "`p6_guid` (renumber hint, section 11.3)",
        "S",
    ),
    ("tmpl_guid", "—", "text(22)", "—", "O\u2212", "—", "FS", "S"),
    (
        "cstr_date2",
        "Activity/SecondaryConstraintDate",
        "ts",
        "—",
        "T",
        "E Δ",
        "`constraint2_date`",
        "S",
    ),
    (
        "cstr_type2",
        "Activity/SecondaryConstraintType",
        "enum",
        "—",
        "T",
        "E Δ",
        "`constraint2_type`",
        "S",
    ),
    ("driving_path_flag", "—", "flag", "—", "O+", "—", "FS", "S"),
    (
        "act_this_per_work_qty",
        "Activity/ActualThisPeriodLaborUnits",
        "num",
        "h",
        "O\u2212",
        "—",
        "FS",
        "S",
    ),
    (
        "act_this_per_equip_qty",
        "Activity/ActualThisPeriodNonLaborUnits",
        "num",
        "h",
        "O\u2212",
        "—",
        "FS",
        "S",
    ),
    (
        "external_early_start_date",
        "Activity/ExternalEarlyStartDate",
        "ts",
        "—",
        "O+",
        "—",
        "FS",
        "S",
    ),
    ("external_late_end_date", "Activity/ExternalLateFinishDate", "ts", "—", "O+", "—", "FS", "S"),
    ("cbs_id", "Activity/CBSCode", "id", "—", "O\u2212", "—", "FS", "S"),
    ("pre_pess_start_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("pre_pess_finish_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("post_pess_start_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("post_pess_finish_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("create_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("update_date", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("create_user", "—", "text(255)", "—", "O\u2212 (personal)", "—", "FS", "S"),
    ("update_user", "—", "text(255)", "—", "O\u2212 (personal)", "—", "FS", "S"),
    ("location_id", "Activity/LocationObjectId", "id", "—", "O\u2212", "—", "FS", "S"),
    ("control_updates_flag", "—", "flag", "—", "O\u2212", "—", "FS", "S"),
    ("crt_path_num", "—", "int", "—", "O\u2212", "—", "FS", "S"),
)

#: Contract section 6.4.
TASKPRED_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Unit", "Tier", "Use", "Target", "Seen"),
    ("task_pred_id", "Relationship/ObjectId", "id", "—", "R", "—", "`p6_relationship_id`", "S"),
    (
        "task_id",
        "Relationship/SuccessorActivityObjectId",
        "id",
        "—",
        "R",
        "E Δ",
        "`succ_p6_task_id` → successor row",
        "S",
    ),
    (
        "pred_task_id",
        "Relationship/PredecessorActivityObjectId",
        "id",
        "—",
        "R",
        "E Δ",
        "`pred_p6_task_id` → predecessor row",
        "S",
    ),
    (
        "proj_id",
        "Relationship/SuccessorProjectObjectId",
        "id",
        "—",
        "R",
        "—",
        "derived → `is_external`",
        "S",
    ),
    (
        "pred_proj_id",
        "Relationship/PredecessorProjectObjectId",
        "id",
        "—",
        "R",
        "—",
        "derived → `is_external`",
        "S",
    ),
    ("pred_type", "Relationship/Type", "enum", "—", "R", "E Δ", "`relationship_type`", "S"),
    ("lag_hr_cnt", "Relationship/Lag", "hours", "h", "R", "E Δ", "`lag_hours`", "S"),
    ("comments", "Relationship/Comments", "text(4000)", "—", "O\u2212", "—", "FS", "S"),
    ("float_path", "—", "int", "—", "O\u2212", "—", "FS", "S"),
    ("aref", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
    ("arls", "—", "ts", "—", "O\u2212", "—", "FS", "S"),
)

#: Contract section 6.5.
PROJWBS_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Tier", "Use", "Target", "Seen"),
    ("wbs_id", "WBS/ObjectId", "id", "R", "E", "`p6_wbs_id`", "S"),
    ("proj_id", "WBS/ProjectObjectId", "id", "R", "—", "derived check", "S"),
    ("obs_id", "WBS/OBSObjectId", "id", "O\u2212", "—", "FS", "S"),
    ("seq_num", "WBS/SequenceNumber", "int", "T", "—", "`sequence`", "S"),
    ("est_wt", "WBS/EstimatedWeight", "num", "O\u2212", "—", "FS", "S"),
    ("proj_node_flag", "— (row absent in XML)", "flag", "R", "E", "`is_project_node`", "S"),
    ("sum_data_flag", "—", "flag", "O\u2212", "—", "FS", "S"),
    ("status_code", "WBS/Status", "enum", "T", "—", "`status_code`", "S"),
    ("wbs_short_name", "WBS/Code", "text(40)", "R", "E Δ", "`short_name`", "S"),
    ("wbs_name", "WBS/Name", "name", "R", "E Δ", "`name`", "S"),
    ("phase_id", "—", "id", "O\u2212", "—", "FS", "S"),
    ("parent_wbs_id", "WBS/ParentObjectId", "id", "R", "E", "`parent_p6_wbs_id`", "S"),
    ("ev_user_pct", "WBS/EarnedValueUserPercent", "num", "O\u2212", "—", "FS", "S"),
    ("ev_etc_user_value", "WBS/EarnedValueETCUserValue", "num", "O\u2212", "—", "FS", "S"),
    ("orig_cost", "WBS/OriginalBudget", "num", "O\u2212", "—", "FS", "S"),
    ("indep_remain_total_cost", "WBS/IndependentETCTotalCost", "num", "O\u2212", "—", "FS", "S"),
    ("ann_dscnt_rate_pct", "—", "num", "O\u2212", "—", "FS", "S"),
    ("dscnt_period_type", "—", "enum", "O\u2212", "—", "FS", "S"),
    ("indep_remain_work_qty", "WBS/IndependentETCLaborUnits", "num", "O\u2212", "—", "FS", "S"),
    ("anticip_start_date", "WBS/AnticipatedStartDate", "ts", "O\u2212", "—", "FS", "S"),
    ("anticip_end_date", "WBS/AnticipatedFinishDate", "ts", "O\u2212", "—", "FS", "S"),
    ("ev_compute_type", "WBS/EarnedValueComputeType", "enum", "O\u2212", "—", "FS", "S"),
    ("ev_etc_compute_type", "WBS/EarnedValueETCComputeType", "enum", "O\u2212", "—", "FS", "S"),
    ("guid", "WBS/GUID", "text(22)", "T", "—", "`p6_guid`", "S"),
    ("tmpl_guid", "—", "text(22)", "O\u2212", "—", "FS", "S"),
    ("plan_open_state", "—", "text(255)", "O\u2212", "—", "FS", "S"),
)

#: Contract section 6.6.
CALENDAR_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Tier", "Use", "Target", "Seen"),
    ("clndr_id", "Calendar/ObjectId", "id", "R", "E", "`p6_calendar_id`", "S"),
    ("default_flag", "Calendar/IsDefault", "flag", "T", "—", "`is_default`", "S"),
    ("clndr_name", "Calendar/Name", "name", "T", "—", "`name`", "S"),
    ("proj_id", "Calendar/ProjectObjectId", "id", "T", "—", "`p6_project_id`", "S"),
    (
        "base_clndr_id",
        "Calendar/BaseCalendarObjectId",
        "id",
        "T",
        "E",
        "`base_p6_calendar_id`",
        "S",
    ),
    ("last_chng_date", "—", "ts", "O\u2212", "—", "FS", "S"),
    ("clndr_type", "Calendar/Type", "enum", "R", "—", "`calendar_type`", "S"),
    ("day_hr_cnt", "Calendar/HoursPerDay", "hours", "T", "—", "`hours_per_day`", "S"),
    ("week_hr_cnt", "Calendar/HoursPerWeek", "hours", "T", "—", "`hours_per_week`", "S"),
    ("month_hr_cnt", "Calendar/HoursPerMonth", "hours", "T", "—", "`hours_per_month`", "S"),
    ("year_hr_cnt", "Calendar/HoursPerYear", "hours", "T", "—", "`hours_per_year`", "S"),
    ("rsrc_private", "Calendar/IsPersonal", "flag", "O\u2212", "—", "FS", "S"),
    (
        "clndr_data",
        "Calendar/StandardWorkWeek, Calendar/HolidayOrExceptions",
        "blob",
        "V + R",
        "E",
        "derived → `week`, `exceptions`, `data_sha256`",
        "S",
    ),
)

#: Contract section 6.7.
PROJECT_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Tier", "Use", "Target", "Seen"),
    ("proj_id", "Project/ObjectId", "id", "R", "—", "`p6_project_id`", "S"),
    (
        "proj_short_name",
        "Project/Id",
        "text(40)",
        "R",
        "—",
        "`project_short_name` (Series identity check)",
        "S",
    ),
    ("guid", "Project/GUID", "text(22)", "T", "—", "`project_guid`", "S"),
    (
        "clndr_id",
        "Project/ActivityDefaultCalendarObjectId",
        "id",
        "T",
        "E",
        "`default_p6_calendar_id`",
        "S",
    ),
    ("last_recalc_date", "Project/DataDate", "ts", "R", "E Δ", "`data_date`", "S"),
    ("plan_start_date", "Project/PlannedStartDate", "ts", "T", "—", "`planned_start`", "S"),
    ("plan_end_date", "Project/MustFinishByDate", "ts", "T", "E", "`must_finish_by`", "S"),
    ("scd_end_date", "Project/ScheduledFinishDate", "ts", "T", "Δ", "`scheduled_finish`", "S"),
    (
        "critical_drtn_hr_cnt",
        "Project/CriticalActivityFloatLimit",
        "hours",
        "T",
        "E",
        "`critical_float_hours`",
        "S",
    ),
    (
        "critical_path_type",
        "Project/CriticalActivityPathType",
        "enum",
        "T",
        "—",
        "`critical_path_type`",
        "S",
    ),
    ("next_data_date", "—", "ts", "T", "—", "`next_data_date`", "S"),
    ("(proj node `wbs_name`)", "Project/Name", "name", "V", "—", "derived → `project_name`", "S"),
)

#: Contract section 6.8.
SCHEDOPTIONS_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER field", "XML", "Type", "Tier", "Use", "Target", "Seen"),
    (
        "sched_calendar_on_relationship_lag",
        "ScheduleOptions/RelationshipLagCalendar",
        "enum",
        "T",
        "E",
        "`lag_calendar`",
        "S",
    ),
    (
        "sched_retained_logic",
        "ScheduleOptions/OutOfSequenceScheduleType",
        "flag",
        "T",
        "E",
        "`retained_logic`",
        "S",
    ),
    (
        "sched_progress_override",
        "ScheduleOptions/OutOfSequenceScheduleType",
        "flag",
        "T",
        "E",
        "`progress_override`",
        "S",
    ),
    (
        "sched_float_type",
        "ScheduleOptions/ComputeTotalFloatType",
        "enum",
        "T",
        "—",
        "`float_type`",
        "S",
    ),
    (
        "sched_open_critical_flag",
        "ScheduleOptions/MakeOpenEndedActivitiesCritical",
        "flag",
        "T",
        "—",
        "`open_ends_critical`",
        "S",
    ),
    (
        "sched_outer_depend_type",
        "ScheduleOptions/IgnoreOtherProjectRelationships",
        "enum",
        "T",
        "—",
        "`external_dependencies`",
        "S",
    ),
    (
        "sched_use_expect_end_flag",
        "ScheduleOptions/UseExpectedFinishDates",
        "flag",
        "T",
        "—",
        "`use_expected_finish`",
        "S",
    ),
    (
        "sched_lag_early_start_flag",
        "ScheduleOptions/StartToStartLagCalculationType",
        "flag",
        "T",
        "—",
        "`ss_lag_from_early_start`",
        "S",
    ),
    (
        "sched_use_project_end_date_for_float",
        "ScheduleOptions/CalculateFloatBasedOnFinishDate",
        "flag",
        "T",
        "—",
        "`float_from_project_finish`",
        "S",
    ),
)

#: Contract section 6.9.
UDF_AND_CODE_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("XER table.field", "XML", "Tier", "Target", "Seen"),
    ("UDFTYPE.udf_type_id", "UDFType/ObjectId", "V", "field definition (observed)", "S"),
    (
        "UDFTYPE.table_name",
        "UDFType/SubjectArea",
        "V",
        "owner entity of `udf:<owner>:<label>`",
        "S",
    ),
    ("UDFTYPE.udf_type_name", "—", "V", "stored in observed record only", "S"),
    ("UDFTYPE.udf_type_label", "UDFType/Title", "V", "`<label>` of the field key", "S"),
    (
        "UDFTYPE.logical_data_type",
        "UDFType/DataType",
        "V",
        (
            "value type: `FT_TEXT` [S]; `FT_INT`, `FT_FLOAT_2_DECIMALS`, `FT_MONEY`, "
            "`FT_START_DATE`, `FT_END_DATE`, `FT_STATICTYPE` [D]"
        ),
        "S",
    ),
    ("UDFTYPE.super_flag", "—", "O\u2212", "FS (project entity)", "S"),
    (
        "UDFTYPE.indicator_expression",
        "—",
        "N",
        "none (an executable expression; never evaluated or stored)",
        "S",
    ),
    ("UDFTYPE.summary_indicator_expression", "—", "N", "none (same)", "S"),
    ("UDFTYPE.export_flag", "—", "O\u2212", "FS (project entity)", "S"),
    ("UDFVALUE.udf_type_id", "Activity/UDF/TypeObjectId", "V", "resolves the field key", "S"),
    ("UDFVALUE.fk_id", "(parent element)", "V", "owner entity id", "S"),
    ("UDFVALUE.proj_id", "—", "V", "check", "S"),
    (
        "UDFVALUE.udf_text / udf_number / udf_date / udf_code_id",
        "Activity/UDF/TextValue (`DoubleValue`, `StartDateValue`, `CodeValue` [D])",
        "O+",
        "FS typed value",
        "S (text) / D",
    ),
    (
        "ACTVTYPE.actv_code_type_id",
        "ActivityCodeType/ObjectId",
        "V",
        "resolves `code:<label>`",
        "S",
    ),
    ("ACTVTYPE.actv_code_type", "ActivityCodeType/Name", "V", "`<label>`", "S"),
    (
        "ACTVTYPE.actv_code_type_scope",
        "ActivityCodeType/Scope",
        "O\u2212",
        "FS (project entity)",
        "S",
    ),
    (
        "ACTVTYPE.actv_short_len, seq_num, proj_id, wbs_id, export_flag",
        "ActivityCodeType/Length, SequenceNumber, ProjectObjectId",
        "O\u2212",
        "FS",
        "S",
    ),
    ("ACTVCODE.actv_code_id", "ActivityCode/ObjectId", "V", "code value id", "S"),
    ("ACTVCODE.short_name", "ActivityCode/CodeValue", "O+", "FS value (text)", "S"),
    ("ACTVCODE.actv_code_name", "ActivityCode/Description", "O+", "FS value description", "S"),
    (
        "ACTVCODE.parent_actv_code_id",
        "ActivityCode/ParentObjectId",
        "O+",
        "FS value parent path",
        "S",
    ),
    (
        "ACTVCODE.actv_code_type_id, seq_num, color, total_assignments",
        "CodeTypeObjectId, SequenceNumber, Color",
        "O\u2212",
        "FS",
        "S",
    ),
    (
        "TASKACTV.task_id, actv_code_type_id, actv_code_id, proj_id",
        "Activity/Code/TypeObjectId, ValueObjectId",
        "V",
        "FS row (activity, `code:<label>`)",
        "S",
    ),
    ("UDFCODE.*", "—", "V", "value labels for `FT_STATICTYPE`", "D"),
)

#: Contract section 6.10.
OPTIONAL_TABLE_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    ("Table", "Fields (all [S] unless stated)", "Note"),
    (
        "CURRTYPE",
        (
            "curr_id, decimal_digit_cnt, curr_symbol, decimal_symbol, digit_group_symbol, "
            "pos_curr_fmt_type, neg_curr_fmt_type, curr_type, curr_short_name, "
            "group_digit_cnt, base_exch_rate"
        ),
        "XML `DisplayCurrency/Currency/*` (1 of 17)",
    ),
    ("FINTMPL", "fintmpl_id, fintmpl_name, default_flag", "XML `FinancialPeriodTemplate/*`"),
    (
        "LOCATION",
        (
            "location_id, location_name, location_type, address_line1, address_line2, "
            "address_line3, city_name, municipality_name, state_name, state_code, "
            "country_name, country_code, postal_code, longitude, latitude"
        ),
        "personal/address data; not in XML sample",
    ),
    ("NONWORK", "nonwork_type_id, seq_num, nonwork_code, nonwork_type", "not in XML sample"),
    (
        "OBS",
        "obs_id, parent_obs_id, guid, seq_num, obs_name, obs_descr",
        "personal names; XML `OBS/*`",
    ),
    (
        (
            "ROLES, ACCOUNT, PROJCOST, TASKMEMO, MEMOTYPE, TASKPROC, PCATTYPE, PCATVAL, "
            "PROJPCAT, RCATTYPE, RCATVAL, RSRCRCAT, UMEASURE, SHIFT, SHIFTPER, COSTTYPE, "
            "EXPTYPE"
        ),
        "none listed [D]",
        "entity `project`; catalogued in S7-1 from documentation without fields",
    ),
)


#: Contract section 6.7, "Optional, generic field store (O-, all [S])", in the contract's order.
PROJECT_OPTIONAL_FIELDS: Final = (
    "fy_start_month_num",
    "rsrc_self_add_flag",
    "allow_complete_flag",
    "rsrc_multi_assign_flag",
    "checkout_flag",
    "project_flag",
    "step_complete_flag",
    "cost_qty_recalc_flag",
    "batch_sum_flag",
    "name_sep_char",
    "def_complete_pct_type",
    "acct_id",
    "orig_proj_id",
    "source_proj_id",
    "base_type_id",
    "sum_base_proj_id",
    "task_code_base",
    "task_code_step",
    "priority_num",
    "wbs_max_sum_level",
    "strgy_priority_num",
    "last_checksum",
    "def_cost_per_qty",
    "add_date",
    "last_tasksum_date",
    "fcst_start_date",
    "def_duration_type",
    "task_code_prefix",
    "def_qty_type",
    "add_by_name",
    "web_local_root_path",
    "proj_url",
    "def_rate_type",
    "add_act_remain_flag",
    "act_this_per_link_flag",
    "def_task_type",
    "act_pct_link_flag",
    "task_code_prefix_flag",
    "def_rollup_dates_flag",
    "use_project_baseline_flag",
    "rem_target_link_flag",
    "reset_planned_flag",
    "allow_neg_act_flag",
    "sum_assign_level",
    "last_fin_dates_id",
    "last_baseline_update_date",
    "cr_external_key",
    "apply_actuals_date",
    "fintmpl_id",
    "last_schedule_date",
    "matrix_id",
    "last_level_date",
    "hist_interval",
    "hist_level",
    "control_updates_flag",
    "rsrc_role_match_flag",
    "px_enable_publication_flag",
    "publish_spread_assign_level",
    "px_last_update_date",
    "px_priority",
    "schedule_type",
    "location_id",
    "loaded_scope_level",
    "export_flag",
    "new_fin_dates_id",
    "baselines_to_export",
    "baseline_names_to_export",
    "sync_wbs_heir_flag",
    "sched_wbs_heir_type",
    "wbs_heir_levels",
    "base_proj_id",
    "base_proj_id1",
    "base_proj_id2",
    "close_period_flag",
    "sum_refresh_date",
    "trsrcsum_loaded",
    "sumtask_loaded",
)
#: Section 6.7: the 1:1 XML elements the contract names for optional PROJECT fields.
PROJECT_OPTIONAL_XML: Final[Mapping[str, str]] = {
    "fy_start_month_num": "Project/FiscalYearStartMonth",
    "add_date": "Project/DateAdded",
    "add_by_name": "Project/AddedBy",
}
#: Section 6.7: optional PROJECT fields marked `(personal)`.
PROJECT_PERSONAL_FIELDS: Final = frozenset({"add_by_name"})

#: Contract section 6.8, "Optional (O-, [S])", in the contract's order.
SCHEDOPTIONS_OPTIONAL_FIELDS: Final = (
    "schedoptions_id",
    "proj_id",
    "sched_setplantoforecast",
    "level_float_thrs_cnt",
    "level_outer_assign_flag",
    "level_outer_assign_priority",
    "level_over_alloc_pct",
    "level_within_float_flag",
    "level_keep_sched_date_flag",
    "level_all_rsrc_flag",
    "enable_multiple_longest_path_calc",
    "limit_multiple_longest_path_calc",
    "max_multiple_longest_path",
    "use_total_float_multiple_longest_paths",
    "key_activity_for_multiple_longest_paths",
    "LevelPriorityList",
)

#: Section 6.10 personal markings: LOCATION is address data, OBS carries person names.
OPTIONAL_TABLE_PERSONAL_FIELDS: Final[Mapping[str, frozenset[str]]] = {
    "LOCATION": frozenset(
        {
            "location_name",
            "address_line1",
            "address_line2",
            "address_line3",
            "city_name",
            "municipality_name",
            "state_name",
            "state_code",
            "country_name",
            "country_code",
            "postal_code",
            "longitude",
            "latitude",
        }
    ),
    "OBS": frozenset({"obs_name", "obs_descr"}),
}

#: Enumerations of sections 6.3-6.9: (seen in the sample [S], documented only [D]).
#: An `enum` field absent here has no stated value set and is open (any token).
ENUMERATIONS: Final[Mapping[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]]] = {
    ("TASK", "task_type"): (("TT_Task", "TT_Mile", "TT_FinMile"), ("TT_LOE", "TT_WBS", "TT_Rsrc")),
    ("TASK", "status_code"): (("TK_NotStart",), ("TK_Active", "TK_Complete")),
    ("TASK", "duration_type"): (
        ("DT_FixedDUR2", "DT_FixedRate", "DT_FixedDrtn"),
        ("DT_FixedQty",),
    ),
    ("TASK", "complete_pct_type"): (("CP_Drtn",), ("CP_Units", "CP_Phys")),
    ("TASK", "cstr_type"): (
        ("CS_MEOA", "CS_MEOB"),
        ("CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MEO", "CS_MANDSTART", "CS_MANDFIN", "CS_ALAP"),
    ),
    ("TASK", "cstr_type2"): (
        ("CS_MEOA", "CS_MEOB"),
        ("CS_MSO", "CS_MSOA", "CS_MSOB", "CS_MEO", "CS_MANDSTART", "CS_MANDFIN", "CS_ALAP"),
    ),
    ("TASK", "priority_type"): (("PT_Normal",), ()),
    ("TASKPRED", "pred_type"): (("PR_FS", "PR_SS", "PR_FF"), ("PR_SF",)),
    ("PROJWBS", "status_code"): (("WS_Closed",), ("WS_Open", "WS_Whatif", "WS_Planned")),
    ("CALENDAR", "clndr_type"): (("CA_Base", "CA_Project"), ("CA_Rsrc",)),
    ("SCHEDOPTIONS", "sched_calendar_on_relationship_lag"): (
        ("rcal_Predecessor",),
        ("rcal_Successor", "rcal_24Hour", "rcal_Project"),
    ),
    ("SCHEDOPTIONS", "sched_float_type"): (("FT_FF",), ()),
    ("SCHEDOPTIONS", "sched_outer_depend_type"): (("SD_Both",), ()),
    ("UDFTYPE", "logical_data_type"): (
        ("FT_TEXT",),
        (
            "FT_INT",
            "FT_FLOAT_2_DECIMALS",
            "FT_MONEY",
            "FT_START_DATE",
            "FT_END_DATE",
            "FT_STATICTYPE",
        ),
    ),
}

#: Section 6.10: the tables catalogued from the P6 documentation, without a field list.
DOCUMENTED_TABLES: Final = tuple(name.strip() for name in OPTIONAL_TABLE_ROWS[-1][0].split(","))
#: Section 5.1: every catalogued table that is neither required nor tolerated.
OPTIONAL_TABLES: Final = tuple(
    name
    for name in (*(row[0] for row in OPTIONAL_TABLE_ROWS[1:-1]), *DOCUMENTED_TABLES)
    if name not in TOLERATED_TABLES
)

#: Entity kind of each catalogued table's own fields (sections 6.3-6.10, 7.3).
TABLE_ENTITY: Final[Mapping[str, EntityKind]] = {
    "TASK": EntityKind.ACTIVITY,
    "TASKPRED": EntityKind.RELATIONSHIP,
    "PROJWBS": EntityKind.WBS,
    "CALENDAR": EntityKind.CALENDAR,
    "RSRC": EntityKind.RESOURCE,
    "TASKRSRC": EntityKind.ASSIGNMENT,
}

_SAMPLE_VERSIONS: Final = ("26.4",)
_TYPE_CELL: Final = re.compile(r"^(id|text|name|enum|flag|ts|hours|num|int|blob)(?:\((\d+)\))?$")
_TARGET_COLUMN: Final = re.compile(r"^`([a-z0-9_]+)`")
#: Section 6.2: `name` is normalized display text of at most 2,000 characters.
NAME_MAX_CHARACTERS: Final = 2000
#: Section 7.7: an uncatalogued or untyped value is text of at most 4,000 characters.
TEXT_MAX_CHARACTERS: Final = 4000


@dataclass(frozen=True, slots=True)
class CatalogueField:
    """One catalogued XER field (section 6.1 record)."""

    field_key: str
    table: str
    field: str
    xml: str
    entity_kind: EntityKind
    value_type: ValueType
    max_characters: int | None
    unit: str
    tier: Tier
    required: bool
    empty_allowed: bool
    default_capture: bool
    sample_status: str
    versions_seen: tuple[str, ...]
    engine_use: bool
    delta_use: bool
    target: str
    typed_column: str | None
    personal: bool
    enum_values: frozenset[str] | None

    @property
    def is_typed(self) -> bool:
        """R and T fields, and required V fields, are always read into typed data."""
        return self.tier in {Tier.REQUIRED, Tier.TOLERATED} or self.required

    @property
    def is_optional(self) -> bool:
        return self.tier in {Tier.OPTIONAL_DEFAULT, Tier.OPTIONAL}

    @property
    def is_generic_store(self) -> bool:
        """An optional field captured as its own field-store value (target `FS`)."""
        return self.is_optional and self.target.startswith("FS") and not self.is_component

    @property
    def is_component(self) -> bool:
        """A UDF or activity-code value part (`FS value ...`, `FS typed value`)."""
        return self.target.startswith(("FS value", "FS typed value"))


def _rule_type(field: str) -> tuple[ValueType, int | None]:
    if field.endswith("_flag"):
        return ValueType.FLAG, None
    if field.endswith("_date"):
        return ValueType.TS, None
    if re.search(r"_id[12]?$", field):
        return ValueType.ID, None
    return ValueType.TEXT, TEXT_MAX_CHARACTERS


def _cell_type(cell: str) -> tuple[ValueType, int | None]:
    match = _TYPE_CELL.match(cell)
    if match is None:
        raise ValueError(f"unknown type cell {cell!r}")
    value_type = ValueType(match.group(1))
    if match.group(2) is not None:
        return value_type, int(match.group(2))
    if value_type is ValueType.NAME:
        return value_type, NAME_MAX_CHARACTERS
    return value_type, None


def _cell_tier(cell: str) -> tuple[Tier, bool, bool, bool]:
    """(tier, required, empty allowed, personal) from a Tier cell."""
    personal = "(personal)" in cell
    head = cell.split(" (", 1)[0]
    if head == "V + R":
        return Tier.DERIVED, True, False, personal
    tier = Tier(head)
    empty_allowed = "(empty allowed)" in cell
    return tier, tier is Tier.REQUIRED, empty_allowed, personal


def _enum_values(table: str, field: str, value_type: ValueType) -> frozenset[str] | None:
    if value_type is not ValueType.ENUM and (table, field) not in ENUMERATIONS:
        return None
    seen, documented = ENUMERATIONS.get((table, field), ((), ()))
    if not seen and not documented:
        return None
    return frozenset((*seen, *documented))


def _field(
    table: str,
    field: str,
    *,
    xml: str,
    value_type: ValueType,
    max_characters: int | None,
    unit: str,
    tier_cell: str,
    use: str,
    target: str,
    seen: bool,
    personal: bool = False,
    entity_kind: EntityKind | None = None,
) -> CatalogueField:
    tier, required, empty_allowed, personal_cell = _cell_tier(tier_cell)
    column = _TARGET_COLUMN.match(target)
    if (table, field) in ENUMERATIONS and value_type is ValueType.TEXT:
        value_type, max_characters = ValueType.ENUM, None
    return CatalogueField(
        field_key=f"xer:{table}.{field}",
        table=table,
        field=field,
        xml=xml,
        entity_kind=entity_kind or TABLE_ENTITY.get(table, EntityKind.PROJECT),
        value_type=value_type,
        max_characters=max_characters,
        unit=unit,
        tier=tier,
        required=required,
        empty_allowed=empty_allowed,
        default_capture=tier is Tier.OPTIONAL_DEFAULT,
        sample_status="seen" if seen else "documented",
        versions_seen=_SAMPLE_VERSIONS if seen else (),
        engine_use="E" in use.split(),
        delta_use="Δ" in use.split(),
        target=target,
        typed_column=column.group(1) if column else None,
        personal=personal or personal_cell,
        enum_values=_enum_values(table, field, value_type),
    )


def _typed_table(table: str, rows: tuple[tuple[str, ...], ...]) -> list[CatalogueField]:
    fields: list[CatalogueField] = []
    for row in rows[1:]:
        if len(row) == 8:
            name, xml, type_cell, unit, tier_cell, use, target, seen = row
        else:
            name, xml, type_cell, tier_cell, use, target, seen = row
            unit = "h" if type_cell == "hours" else "—"
        if name.startswith("("):
            continue  # a derived value, not an XER field (6.7: the project node's name)
        value_type, max_characters = _cell_type(type_cell)
        fields.append(
            _field(
                table,
                name,
                xml=xml,
                value_type=value_type,
                max_characters=max_characters,
                unit=unit,
                tier_cell=tier_cell,
                use=use,
                target=target,
                seen=seen == "S",
            )
        )
    return fields


def _optional_list(
    table: str,
    names: tuple[str, ...],
    *,
    xml: Mapping[str, str],
    personal: frozenset[str],
    seen: bool = True,
) -> list[CatalogueField]:
    fields: list[CatalogueField] = []
    for name in names:
        value_type, max_characters = _rule_type(name)
        fields.append(
            _field(
                table,
                name,
                xml=xml.get(name, "—"),
                value_type=value_type,
                max_characters=max_characters,
                unit="—",
                tier_cell=Tier.OPTIONAL.value,
                use="—",
                target="FS",
                seen=seen,
                personal=name in personal,
            )
        )
    return fields


def _udf_and_code_fields() -> list[CatalogueField]:
    fields: list[CatalogueField] = []
    for cell, xml, tier_cell, target, seen in UDF_AND_CODE_ROWS[1:]:
        table, rest = cell.split(".", 1)
        if rest == "*":
            continue  # 6.9 `UDFCODE.*`: every field is a derived value label (wildcard)
        names = [name.strip() for name in re.split(r"[,/]", rest)]
        for name in names:
            value_type, max_characters = _rule_type(name)
            field_seen = seen == "S" or (seen.startswith("S (text)") and name == "udf_text")
            fields.append(
                _field(
                    table,
                    name,
                    xml=xml,
                    value_type=value_type,
                    max_characters=max_characters,
                    unit="—",
                    tier_cell=tier_cell,
                    use="—",
                    target=target,
                    seen=field_seen,
                )
            )
    return fields


def _optional_table_fields() -> list[CatalogueField]:
    fields: list[CatalogueField] = []
    for table, cell, _note in OPTIONAL_TABLE_ROWS[1:-1]:
        names = tuple(name.strip() for name in cell.split(","))
        fields += _optional_list(
            table,
            names,
            xml={},
            personal=OPTIONAL_TABLE_PERSONAL_FIELDS.get(table, frozenset()),
        )
    return fields


def _build() -> tuple[CatalogueField, ...]:
    fields = [
        *_typed_table("TASK", TASK_ROWS),
        *_typed_table("TASKPRED", TASKPRED_ROWS),
        *_typed_table("PROJWBS", PROJWBS_ROWS),
        *_typed_table("CALENDAR", CALENDAR_ROWS),
        *_typed_table("PROJECT", PROJECT_ROWS),
        *_optional_list(
            "PROJECT",
            PROJECT_OPTIONAL_FIELDS,
            xml=PROJECT_OPTIONAL_XML,
            personal=PROJECT_PERSONAL_FIELDS,
        ),
        *_typed_table("SCHEDOPTIONS", SCHEDOPTIONS_ROWS),
        *_optional_list("SCHEDOPTIONS", SCHEDOPTIONS_OPTIONAL_FIELDS, xml={}, personal=frozenset()),
        *_udf_and_code_fields(),
        *_optional_table_fields(),
    ]
    keys = [field.field_key for field in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate catalogue field key")
    return tuple(fields)


#: Every catalogued field, in contract order.
CATALOGUE: Final[tuple[CatalogueField, ...]] = _build()
_BY_KEY: Final[Mapping[tuple[str, str], CatalogueField]] = {
    (field.table, field.field): field for field in CATALOGUE
}
_TABLE_FIELDS: Final[Mapping[str, tuple[CatalogueField, ...]]] = {
    table: tuple(field for field in CATALOGUE if field.table == table)
    for table in dict.fromkeys(field.table for field in CATALOGUE)
}
#: Tables whose every field is a derived value (6.9 `UDFCODE.*`).
WILDCARD_TABLES: Final = frozenset({"UDFCODE"})


def is_catalogued_table(table: str) -> bool:
    return table in REQUIRED_TABLES or table in TOLERATED_TABLES or table in OPTIONAL_TABLES


def catalogue_field(table: str, field: str) -> CatalogueField | None:
    return _BY_KEY.get((table, field))


def table_fields(table: str) -> tuple[CatalogueField, ...]:
    return _TABLE_FIELDS.get(table, ())


_SECTIONS: Final[Mapping[str, tuple[tuple[str, ...], ...]]] = {
    "6.3": TASK_ROWS,
    "6.4": TASKPRED_ROWS,
    "6.5": PROJWBS_ROWS,
    "6.6": CALENDAR_ROWS,
    "6.7": PROJECT_ROWS,
    "6.8": SCHEDOPTIONS_ROWS,
    "6.9": UDF_AND_CODE_ROWS,
    "6.10": OPTIONAL_TABLE_ROWS,
}


def render_section(section: str) -> tuple[str, ...]:
    """The contract's Markdown table rows of `section` (header first, no separator)."""
    return tuple("| " + " | ".join(row) + " |" for row in _SECTIONS[section])
