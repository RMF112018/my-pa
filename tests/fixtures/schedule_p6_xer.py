"""Synthetic P6 XER exports for profile `p6_xer_v1` and their intended outcomes (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` section 12
(synthetic fixtures) and acceptance A1-A6. Standard library only: no
randomness, no clock. Every name, code, calendar, label and value here is
invented (`Synthetic Project`, `SYN-1000`); nothing comes from a real export.

Each case is a pure function of its name: `build(name)` returns a
`FixtureCase` with the bytes, the capture selection (None = defaults) and the
`truth` the generator *intends* (outcome, verdict and every issue with code,
severity, table, line and field), written from its own layout and never from
parser output. Golden frame digests (`schedule_p6_xer_goldens.json`) pin the
parser's canonical frame per case; only the explicit `record-goldens`
command below writes them, and no test calls it.

The field lists below are a frozen copy of catalogue `p6-field-catalogue-v1`
(tier per field: R required, T tolerated, O optional, V derived, N never);
the generator keeps its own copy so a catalogue edit cannot silently change
what the fixtures contain.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = 1
GOLDEN_FILE = Path(__file__).resolve().parent / "schedule_p6_xer_goldens.json"

FATAL = "fatal"
WARNING = "warning"
INFO = "info"
COMPLETE = "complete"
FAILED = "failed"
VERDICT_PASS = "pass"  # noqa: S105 - a verdict, not a secret
VERDICT_FINDINGS = "pass_with_findings"
VERDICT_FAIL = "fail"

#: Frozen copy of the catalogue's fields per table (sample order), `name:tier`.
FIELDS: Mapping[str, str] = {
    "TASK": (
        "task_id:R proj_id:R wbs_id:R clndr_id:R phys_complete_pct:T rev_fdbk_flag:O est_wt:O "
        "lock_plan_flag:O auto_compute_act_flag:O complete_pct_type:T task_type:R "
        "duration_type:T status_code:R task_code:R task_name:R rsrc_id:O total_float_hr_cnt:T "
        "free_float_hr_cnt:T remain_drtn_hr_cnt:R act_work_qty:O remain_work_qty:O "
        "target_work_qty:O target_drtn_hr_cnt:R target_equip_qty:O act_equip_qty:O "
        "remain_equip_qty:O cstr_date:R act_start_date:R act_end_date:R late_start_date:T "
        "late_end_date:T expect_end_date:O early_start_date:R early_end_date:R restart_date:T "
        "reend_date:T target_start_date:T target_end_date:T rem_late_start_date:O "
        "rem_late_end_date:O cstr_type:R priority_type:O suspend_date:O resume_date:O "
        "float_path:O float_path_order:O guid:T tmpl_guid:O cstr_date2:T cstr_type2:T "
        "driving_path_flag:O act_this_per_work_qty:O act_this_per_equip_qty:O "
        "external_early_start_date:O external_late_end_date:O cbs_id:O pre_pess_start_date:O "
        "pre_pess_finish_date:O post_pess_start_date:O post_pess_finish_date:O create_date:O "
        "update_date:O create_user:O update_user:O location_id:O control_updates_flag:O "
        "crt_path_num:O "
    ),
    "TASKPRED": (
        "task_pred_id:R task_id:R pred_task_id:R proj_id:R pred_proj_id:R pred_type:R "
        "lag_hr_cnt:R comments:O float_path:O aref:O arls:O "
    ),
    "PROJWBS": (
        "wbs_id:R proj_id:R obs_id:O seq_num:T est_wt:O proj_node_flag:R sum_data_flag:O "
        "status_code:T wbs_short_name:R wbs_name:R phase_id:O parent_wbs_id:R ev_user_pct:O "
        "ev_etc_user_value:O orig_cost:O indep_remain_total_cost:O ann_dscnt_rate_pct:O "
        "dscnt_period_type:O indep_remain_work_qty:O anticip_start_date:O anticip_end_date:O "
        "ev_compute_type:O ev_etc_compute_type:O guid:T tmpl_guid:O plan_open_state:O "
    ),
    "CALENDAR": (
        "clndr_id:R default_flag:T clndr_name:T proj_id:T base_clndr_id:T last_chng_date:O "
        "clndr_type:R day_hr_cnt:T week_hr_cnt:T month_hr_cnt:T year_hr_cnt:T rsrc_private:O "
        "clndr_data:R "
    ),
    "PROJECT": (
        "proj_id:R proj_short_name:R guid:T clndr_id:T last_recalc_date:R plan_start_date:T "
        "plan_end_date:T scd_end_date:T critical_drtn_hr_cnt:T critical_path_type:T "
        "next_data_date:T fy_start_month_num:O rsrc_self_add_flag:O allow_complete_flag:O "
        "rsrc_multi_assign_flag:O checkout_flag:O project_flag:O step_complete_flag:O "
        "cost_qty_recalc_flag:O batch_sum_flag:O name_sep_char:O def_complete_pct_type:O "
        "acct_id:O orig_proj_id:O source_proj_id:O base_type_id:O sum_base_proj_id:O "
        "task_code_base:O task_code_step:O priority_num:O wbs_max_sum_level:O "
        "strgy_priority_num:O last_checksum:O def_cost_per_qty:O add_date:O "
        "last_tasksum_date:O fcst_start_date:O def_duration_type:O task_code_prefix:O "
        "def_qty_type:O add_by_name:O web_local_root_path:O proj_url:O def_rate_type:O "
        "add_act_remain_flag:O act_this_per_link_flag:O def_task_type:O act_pct_link_flag:O "
        "task_code_prefix_flag:O def_rollup_dates_flag:O use_project_baseline_flag:O "
        "rem_target_link_flag:O reset_planned_flag:O allow_neg_act_flag:O sum_assign_level:O "
        "last_fin_dates_id:O last_baseline_update_date:O cr_external_key:O "
        "apply_actuals_date:O fintmpl_id:O last_schedule_date:O matrix_id:O last_level_date:O "
        "hist_interval:O hist_level:O control_updates_flag:O rsrc_role_match_flag:O "
        "px_enable_publication_flag:O publish_spread_assign_level:O px_last_update_date:O "
        "px_priority:O schedule_type:O location_id:O loaded_scope_level:O export_flag:O "
        "new_fin_dates_id:O baselines_to_export:O baseline_names_to_export:O "
        "sync_wbs_heir_flag:O sched_wbs_heir_type:O wbs_heir_levels:O base_proj_id:O "
        "base_proj_id1:O base_proj_id2:O close_period_flag:O sum_refresh_date:O "
        "trsrcsum_loaded:O sumtask_loaded:O "
    ),
    "SCHEDOPTIONS": (
        "sched_calendar_on_relationship_lag:T sched_retained_logic:T "
        "sched_progress_override:T sched_float_type:T sched_open_critical_flag:T "
        "sched_outer_depend_type:T sched_use_expect_end_flag:T sched_lag_early_start_flag:T "
        "sched_use_project_end_date_for_float:T schedoptions_id:O proj_id:O "
        "sched_setplantoforecast:O level_float_thrs_cnt:O level_outer_assign_flag:O "
        "level_outer_assign_priority:O level_over_alloc_pct:O level_within_float_flag:O "
        "level_keep_sched_date_flag:O level_all_rsrc_flag:O "
        "enable_multiple_longest_path_calc:O limit_multiple_longest_path_calc:O "
        "max_multiple_longest_path:O use_total_float_multiple_longest_paths:O "
        "key_activity_for_multiple_longest_paths:O LevelPriorityList:O "
    ),
    "UDFTYPE": (
        "udf_type_id:V table_name:V udf_type_name:V udf_type_label:V logical_data_type:V "
        "super_flag:O indicator_expression:N summary_indicator_expression:N export_flag:O "
    ),
    "UDFVALUE": (
        "udf_type_id:V fk_id:V proj_id:V udf_text:O udf_number:O udf_date:O udf_code_id:O "
    ),
    "ACTVTYPE": (
        "actv_code_type_id:V actv_code_type:V actv_code_type_scope:O actv_short_len:O "
        "seq_num:O proj_id:O wbs_id:O export_flag:O "
    ),
    "ACTVCODE": (
        "actv_code_id:V short_name:O actv_code_name:O parent_actv_code_id:O "
        "actv_code_type_id:O seq_num:O color:O total_assignments:O "
    ),
    "TASKACTV": ("task_id:V actv_code_type_id:V actv_code_id:V proj_id:V "),
    "CURRTYPE": (
        "curr_id:O decimal_digit_cnt:O curr_symbol:O decimal_symbol:O digit_group_symbol:O "
        "pos_curr_fmt_type:O neg_curr_fmt_type:O curr_type:O curr_short_name:O "
        "group_digit_cnt:O base_exch_rate:O "
    ),
    "FINTMPL": ("fintmpl_id:O fintmpl_name:O default_flag:O "),
    "LOCATION": (
        "location_id:O location_name:O location_type:O address_line1:O address_line2:O "
        "address_line3:O city_name:O municipality_name:O state_name:O state_code:O "
        "country_name:O country_code:O postal_code:O longitude:O latitude:O "
    ),
    "NONWORK": ("nonwork_type_id:O seq_num:O nonwork_code:O nonwork_type:O "),
    "OBS": ("obs_id:O parent_obs_id:O guid:O seq_num:O obs_name:O obs_descr:O "),
}

SAMPLE_TABLE_ORDER = (
    "CURRTYPE",
    "FINTMPL",
    "LOCATION",
    "NONWORK",
    "OBS",
    "UDFTYPE",
    "PROJECT",
    "CALENDAR",
    "SCHEDOPTIONS",
    "PROJWBS",
    "ACTVTYPE",
    "TASK",
    "ACTVCODE",
    "TASKPRED",
    "TASKACTV",
    "UDFVALUE",
)
REQUIRED_TABLES = ("PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED")
HEADER = (
    "ERMHDR",
    "26.4",
    "2030-01-08",
    "Project",
    "SYNUSER",
    "Synthetic User",
    "dbxDatabaseNoName",
    "Project Management",
    "USD",
)
CALENDAR_EPOCH = date(1899, 12, 30)


def field_tiers(table: str) -> list[tuple[str, str]]:
    return [
        (item.split(":")[0], item.split(":")[1]) for item in FIELDS[table].split() if ":" in item
    ]


def fields_of(table: str, tiers: str) -> list[str]:
    return [name for name, tier in field_tiers(table) if tier in tiers]


def guid(text: str) -> str:
    """A 22-character GUID text: unpadded base64 of 16 invented bytes (contract 3.3)."""
    raw = text.encode("ascii").ljust(16, b"_")[:16]
    return base64.b64encode(raw).decode("ascii").rstrip("=")


def serial(day: date) -> int:
    return (day - CALENDAR_EPOCH).days


def calendar_blob(
    week: Mapping[int, Sequence[tuple[str, str]]] | None,
    exceptions: Sequence[tuple[date, Sequence[tuple[str, str]]]] = (),
    *,
    extra: str = "",
) -> str:
    """P6 `clndr_data` text: days 1 = Sunday ... 7 = Saturday, `0x7F` pairs between nodes."""

    def intervals(pairs: Sequence[tuple[str, str]]) -> str:
        return "".join(
            f"\x7f\x7f    (0||{index}(s|{start}|f|{finish})())"
            for index, (start, finish) in enumerate(pairs)
        )

    parts = ["(0||CalendarData()("]
    if week is not None:
        parts.append("\x7f\x7f  (0||DaysOfWeek()(")
        for number in range(1, 8):
            parts.append(f"\x7f\x7f   (0||{number}()({intervals(week.get(number, ()))}))")
        parts.append("))")
    parts.append("\x7f\x7f  (0||VIEW(ShowTotal|Y)())")
    parts.append(extra)
    if exceptions:
        parts.append("\x7f\x7f  (0||Exceptions()(")
        for index, (day, pairs) in enumerate(exceptions):
            parts.append(f"\x7f\x7f   (0||{index}(d|{serial(day)})({intervals(pairs)}))")
        parts.append("))")
    parts.append("))")
    return "".join(parts)


WORKDAY = (("08:00", "12:00"), ("13:00", "17:00"))
FIVE_DAY_WEEK: Mapping[int, Sequence[tuple[str, str]]] = dict.fromkeys(range(2, 7), WORKDAY)
BASE_EXCEPTIONS: Sequence[tuple[date, Sequence[tuple[str, str]]]] = (
    (date(2030, 1, 1), ()),
    (date(2030, 1, 12), (("08:00", "12:00"),)),
    (date(2030, 1, 21), ()),
)


@dataclass
class Table:
    name: str
    fields: list[str]
    rows: list[dict[str, str]]


@dataclass
class Model:
    header: list[str]
    tables: list[Table]

    def table(self, name: str) -> Table:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)

    def drop_table(self, name: str) -> None:
        self.tables = [table for table in self.tables if table.name != name]

    def drop_field(self, table: str, name: str) -> None:
        self.table(table).fields.remove(name)

    def insert_after(self, anchor: str, table: Table) -> None:
        index = [item.name for item in self.tables].index(anchor)
        self.tables.insert(index + 1, table)


@dataclass(frozen=True)
class Layout:
    lines: list[str]
    table_line: dict[str, int]
    row_line: dict[tuple[str, int], int]


def layout(model: Model) -> Layout:
    lines = ["\t".join(model.header)]
    table_line: dict[str, int] = {}
    row_line: dict[tuple[str, int], int] = {}
    for table in model.tables:
        lines.append(f"%T\t{table.name}")
        table_line.setdefault(table.name, len(lines))
        lines.append("\t".join(["%F", *table.fields]))
        for index, row in enumerate(table.rows):
            lines.append("\t".join(["%R", *(row.get(name, "") for name in table.fields)]))
            row_line[(table.name, index)] = len(lines)
    lines.append("%E")
    return Layout(lines, table_line, row_line)


def encode(lines: Sequence[str], *, newline: str = "\r\n", encoding: str = "cp1252") -> bytes:
    return (newline.join(lines) + newline).encode(encoding)


type IssueTuple = tuple[str, str, str | None, int | None, str | None]


@dataclass(frozen=True)
class Truth:
    outcome: str
    verdict: str
    issues: tuple[IssueTuple, ...] = ()


@dataclass(frozen=True)
class FixtureCase:
    name: str
    data: bytes
    capture: tuple[str, ...] | None
    truth: Truth


# --- the synthetic project ----------------------------------------------------------------


def _project_rows() -> list[dict[str, str]]:
    return [
        {
            "proj_id": "1001",
            "proj_short_name": "SYN-PRJ",
            "guid": guid("SynProject"),
            "clndr_id": "501",
            "last_recalc_date": "2030-01-07 08:00",
            "plan_start_date": "2030-01-07 08:00",
            "scd_end_date": "2030-01-15 17:00",
            "critical_drtn_hr_cnt": "0",
            "critical_path_type": "CT_TotFloat",
            "fy_start_month_num": "1",
            "add_date": "2029-12-01 09:00",
            "add_by_name": "Synthetic Person",
            "def_duration_type": "DT_FixedDUR2",
            "export_flag": "Y",
        }
    ]


def _calendar_rows() -> list[dict[str, str]]:
    common = {
        "day_hr_cnt": "8",
        "week_hr_cnt": "40",
        "month_hr_cnt": "172",
        "year_hr_cnt": "2000",
        "rsrc_private": "N",
        "last_chng_date": "2029-12-01 09:00",
    }
    return [
        {
            **common,
            "clndr_id": "500",
            "default_flag": "Y",
            "clndr_name": "Synthetic Base Calendar",
            "proj_id": "",
            "base_clndr_id": "",
            "clndr_type": "CA_Base",
            "clndr_data": calendar_blob(FIVE_DAY_WEEK),
        },
        {
            **common,
            "clndr_id": "501",
            "default_flag": "N",
            "clndr_name": "Synthetic Project Calendar",
            "proj_id": "1001",
            "base_clndr_id": "500",
            "clndr_type": "CA_Project",
            "clndr_data": calendar_blob(FIVE_DAY_WEEK, BASE_EXCEPTIONS),
        },
    ]


def _wbs_rows() -> list[dict[str, str]]:
    def row(wbs_id: str, parent: str, short: str, name: str, node: str, seq: str) -> dict[str, str]:
        return {
            "wbs_id": wbs_id,
            "proj_id": "1001",
            "obs_id": "8001",
            "seq_num": seq,
            "proj_node_flag": node,
            "sum_data_flag": "N",
            "status_code": "WS_Open",
            "wbs_short_name": short,
            "wbs_name": name,
            "parent_wbs_id": parent,
            "guid": guid(f"SynWbs{wbs_id}"),
        }

    return [
        row("2001", "9001", "SYN-PRJ", "Synthetic Project", "Y", "0"),
        row("2002", "2001", "A", "Synthetic Area A", "N", "10"),
        row("2003", "2002", "A1", "Synthetic Package A1", "N", "20"),
        row("2004", "2001", "B", "Synthetic Area B", "N", "30"),
    ]


def task_row(
    task_id: str,
    code: str,
    name: str,
    task_type: str,
    wbs_id: str,
    hours: str,
    start: str,
    finish: str,
    **extra: str,
) -> dict[str, str]:
    row = {
        "task_id": task_id,
        "proj_id": "1001",
        "wbs_id": wbs_id,
        "clndr_id": "501",
        "phys_complete_pct": "0",
        "rev_fdbk_flag": "N",
        "est_wt": "1",
        "lock_plan_flag": "N",
        "auto_compute_act_flag": "N",
        "complete_pct_type": "CP_Drtn",
        "task_type": task_type,
        "duration_type": "DT_FixedDUR2",
        "status_code": "TK_NotStart",
        "task_code": code,
        "task_name": name,
        "total_float_hr_cnt": "0",
        "free_float_hr_cnt": "0",
        "remain_drtn_hr_cnt": hours,
        "target_drtn_hr_cnt": hours,
        "late_start_date": start,
        "late_end_date": finish,
        "early_start_date": start,
        "early_end_date": finish,
        "restart_date": start,
        "reend_date": finish,
        "target_start_date": start,
        "target_end_date": finish,
        "priority_type": "PT_Normal",
        "guid": guid(f"SynTask{task_id}"),
        "driving_path_flag": "Y",
        "create_user": "Synthetic Person",
    }
    row.update(extra)
    return row


def _task_rows() -> list[dict[str, str]]:
    return [
        task_row(
            "3001",
            "SYN-1000",
            "Synthetic Start",
            "TT_Mile",
            "2002",
            "0",
            "2030-01-07 08:00",
            "2030-01-07 08:00",
        ),
        task_row(
            "3002",
            "SYN-1010",
            "Synthetic Task One",
            "TT_Task",
            "2003",
            "40",
            "2030-01-07 08:00",
            "2030-01-11 17:00",
            expect_end_date="2030-01-11 17:00",
        ),
        task_row(
            "3003",
            "SYN-1020",
            "Synthetic Task Two",
            "TT_Task",
            "2003",
            "16",
            "2030-01-14 08:00",
            "2030-01-15 17:00",
        ),
        task_row(
            "3004",
            "SYN-1030",
            "Synthetic Finish",
            "TT_FinMile",
            "2004",
            "0",
            "2030-01-15 17:00",
            "2030-01-15 17:00",
        ),
    ]


def pred_row(
    rel_id: str, pred: str, succ: str, kind: str = "PR_FS", lag: str = "0"
) -> dict[str, str]:
    return {
        "task_pred_id": rel_id,
        "task_id": succ,
        "pred_task_id": pred,
        "proj_id": "1001",
        "pred_proj_id": "1001",
        "pred_type": kind,
        "lag_hr_cnt": lag,
        "float_path": "",
    }


def _pred_rows() -> list[dict[str, str]]:
    return [
        pred_row("4001", "3001", "3002"),
        pred_row("4002", "3002", "3003"),
        pred_row("4003", "3003", "3004"),
    ]


def _schedoptions_rows(**changes: str) -> list[dict[str, str]]:
    row = {
        "schedoptions_id": "6001",
        "proj_id": "1001",
        "sched_calendar_on_relationship_lag": "rcal_Predecessor",
        "sched_retained_logic": "Y",
        "sched_progress_override": "N",
        "sched_float_type": "FT_FF",
        "sched_open_critical_flag": "N",
        "sched_outer_depend_type": "SD_Both",
        "sched_use_expect_end_flag": "N",
        "sched_lag_early_start_flag": "N",
        "sched_use_project_end_date_for_float": "N",
        "LevelPriorityList": "priority_type(0), ASC",
    }
    row.update(changes)
    return [row]


def _optional_tables() -> dict[str, list[dict[str, str]]]:
    return {
        "CURRTYPE": [
            {
                "curr_id": "1",
                "decimal_digit_cnt": "2",
                "curr_symbol": "S$",
                "decimal_symbol": ".",
                "digit_group_symbol": ",",
                "curr_type": "Synthetic Dollar",
                "curr_short_name": "SYD",
                "group_digit_cnt": "3",
                "base_exch_rate": "1",
            }
        ],
        "FINTMPL": [{"fintmpl_id": "1", "fintmpl_name": "Synthetic Periods", "default_flag": "Y"}],
        "LOCATION": [
            {
                "location_id": "1",
                "location_name": "Synthetic Site",
                "address_line1": "1 Synthetic Way",
                "city_name": "Synthetic City",
                "country_code": "ZZ",
            }
        ],
        "NONWORK": [
            {
                "nonwork_type_id": "1",
                "seq_num": "1",
                "nonwork_code": "SYN",
                "nonwork_type": "Synthetic",
            }
        ],
        "OBS": [
            {
                "obs_id": "8001",
                "parent_obs_id": "",
                "guid": guid("SynObs"),
                "seq_num": "0",
                "obs_name": "Synthetic Team",
            }
        ],
        "UDFTYPE": [
            {
                "udf_type_id": "5001",
                "table_name": "TASK",
                "udf_type_name": "user_field_1",
                "udf_type_label": "Synthetic Note",
                "logical_data_type": "FT_TEXT",
                "super_flag": "N",
                "indicator_expression": "",
                "summary_indicator_expression": "",
                "export_flag": "Y",
            },
            {
                "udf_type_id": "5002",
                "table_name": "PROJECT",
                "udf_type_name": "user_field_2",
                "udf_type_label": "Synthetic Project Note",
                "logical_data_type": "FT_TEXT",
                "super_flag": "N",
                "export_flag": "Y",
            },
        ],
        "ACTVTYPE": [
            {
                "actv_code_type_id": "7001",
                "actv_short_len": "10",
                "seq_num": "1",
                "actv_code_type": "Synthetic Phase",
                "proj_id": "",
                "wbs_id": "",
                "actv_code_type_scope": "AS_Global",
                "export_flag": "Y",
            }
        ],
        "ACTVCODE": [
            {
                "actv_code_id": "7101",
                "parent_actv_code_id": "",
                "actv_code_type_id": "7001",
                "actv_code_name": "Synthetic Design",
                "short_name": "DES",
                "seq_num": "1",
                "color": "0",
                "total_assignments": "1",
            }
        ],
        "TASKACTV": [
            {
                "task_id": "3002",
                "actv_code_type_id": "7001",
                "actv_code_id": "7101",
                "proj_id": "1001",
            }
        ],
        "UDFVALUE": [
            {
                "udf_type_id": "5001",
                "fk_id": "3002",
                "proj_id": "1001",
                "udf_text": "Synthetic remark",
            },
            {
                "udf_type_id": "5002",
                "fk_id": "1001",
                "proj_id": "1001",
                "udf_text": "Synthetic summary",
            },
        ],
    }


def base_model(level: str) -> Model:
    """`minimal`: required tables, R fields; `standard`: R and T; `full`: every sample table."""
    tiers = {"minimal": "R", "standard": "RT", "full": "RTOVN"}[level]
    rows: dict[str, list[dict[str, str]]] = {
        "PROJECT": _project_rows(),
        "CALENDAR": _calendar_rows(),
        "PROJWBS": _wbs_rows(),
        "TASK": _task_rows(),
        "TASKPRED": _pred_rows(),
    }
    if level == "full":
        rows |= _optional_tables() | {"SCHEDOPTIONS": _schedoptions_rows()}
        order = SAMPLE_TABLE_ORDER
    else:
        order = REQUIRED_TABLES
    tables = [Table(name, fields_of(name, tiers), rows[name]) for name in order]
    return Model(list(HEADER), tables)


def tolerated_missing(model: Model, lay: Layout) -> list[IssueTuple]:
    issues: list[IssueTuple] = []
    for table in model.tables:
        if table.name not in FIELDS:
            continue
        for name in fields_of(table.name, "T"):
            if name not in table.fields:
                issues.append(
                    (
                        "p6_tolerated_field_missing",
                        INFO,
                        table.name,
                        lay.table_line[table.name],
                        name,
                    )
                )
    return issues


def _case(
    name: str,
    model: Model,
    *,
    outcome: str = COMPLETE,
    verdict: str = VERDICT_PASS,
    issues: Callable[[Layout], list[IssueTuple]] | None = None,
    capture: tuple[str, ...] | None = None,
    newline: str = "\r\n",
    encoding: str = "cp1252",
    lines: Callable[[Layout], list[str]] | None = None,
    raw: Callable[[bytes], bytes] | None = None,
) -> FixtureCase:
    lay = layout(model)
    text_lines = lines(lay) if lines is not None else lay.lines
    data = encode(text_lines, newline=newline, encoding=encoding)
    if raw is not None:
        data = raw(data)
    expected = tolerated_missing(model, lay) + (issues(lay) if issues is not None else [])
    return FixtureCase(name, data, capture, Truth(outcome, verdict, tuple(expected)))


# --- cases ----------------------------------------------------------------------------------


def _row_issue(
    code: str, severity: str, table: str, index: int, field_name: str | None
) -> Callable[[Layout], list[IssueTuple]]:
    return lambda lay: [(code, severity, table, lay.row_line[(table, index)], field_name)]


def _std() -> Model:
    return base_model("standard")


def _with(model: Model, table: str, index: int, **changes: str) -> Model:
    model.table(table).rows[index].update(changes)
    return model


def _minimal_valid() -> FixtureCase:
    return _case("minimal_valid", base_model("minimal"))


def _no_optional_tables() -> FixtureCase:
    return _case("no_optional_tables", _std())


def _full_valid() -> FixtureCase:
    return _case("full_valid", base_model("full"))


def _full_selected_capture() -> FixtureCase:
    capture = (
        "xer:TASK.est_wt",
        "xer:TASK.create_user",
        "xer:PROJECT.add_by_name",
        "xer:PROJECT.add_date",
        "xer:LOCATION.city_name",
        "xer:SCHEDOPTIONS.LevelPriorityList",
        "code:Synthetic Phase",
    )
    return _case("full_selected_capture", base_model("full"), capture=capture)


def _unknown_table() -> FixtureCase:
    model = _std()
    model.insert_after(
        "TASKPRED", Table("SYNEXTRA", ["syn_key", "syn_note"], [{"syn_key": "1", "syn_note": "x"}])
    )
    return _case(
        "unknown_table",
        model,
        verdict=VERDICT_FINDINGS,
        issues=lambda lay: [
            ("p6_unknown_table", WARNING, "SYNEXTRA", lay.table_line["SYNEXTRA"], None)
        ],
    )


def _unknown_field_model() -> Model:
    model = _std()
    task = model.table("TASK")
    task.fields += ["syn_extra_field", "9syn-bad"]
    for row in task.rows:
        row["syn_extra_field"] = "Synthetic extra"
        row["9syn-bad"] = "7"
    return model


def _unknown_field_issues(lay: Layout) -> list[IssueTuple]:
    line = lay.table_line["TASK"]
    return [
        ("p6_unknown_field", WARNING, "TASK", line, "syn_extra_field"),
        ("p6_unknown_field_unnamed", WARNING, "TASK", line, None),
    ]


def _unknown_field() -> FixtureCase:
    return _case(
        "unknown_field",
        _unknown_field_model(),
        verdict=VERDICT_FINDINGS,
        issues=_unknown_field_issues,
    )


def _unknown_field_selected() -> FixtureCase:
    return _case(
        "unknown_field_selected",
        _unknown_field_model(),
        verdict=VERDICT_FINDINGS,
        issues=_unknown_field_issues,
        capture=("xer:TASK.syn_extra_field",),
    )


def _missing_tolerated_field() -> FixtureCase:
    model = _std()
    model.drop_field("TASK", "total_float_hr_cnt")
    return _case("missing_tolerated_field", model)


def _missing_required_field() -> FixtureCase:
    model = _std()
    model.drop_field("TASK", "remain_drtn_hr_cnt")
    return _case(
        "missing_required_field",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [
            (
                "p6_required_field_missing",
                FATAL,
                "TASK",
                lay.table_line["TASK"],
                "remain_drtn_hr_cnt",
            )
        ],
    )


def _missing_required_table() -> FixtureCase:
    model = _std()
    model.drop_table("TASKPRED")
    return _case(
        "missing_required_table",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [("p6_required_table_missing", FATAL, "TASKPRED", None, None)],
    )


def _version(name: str, version: str) -> FixtureCase:
    model = _std()
    model.header[1] = version
    return _case(
        name,
        model,
        verdict=VERDICT_FINDINGS,
        issues=lambda lay: [("p6_export_version_untested", WARNING, None, 1, None)],
    )


def _header_invalid() -> FixtureCase:
    model = _std()
    model.header[0] = "ERMHDX"
    return _case(
        "header_invalid",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [("p6_header_invalid", FATAL, None, 1, None)],
    )


def _version_malformed() -> FixtureCase:
    model = _std()
    model.header[1] = "v26"
    return _case(
        "version_malformed",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [("p6_header_invalid", FATAL, None, 1, None)],
    )


def _udf_types() -> FixtureCase:
    model = _std()
    udf_fields = fields_of("UDFTYPE", "RTOVN")
    types = [
        ("5001", "TASK", "Synthetic Note", "FT_TEXT"),
        ("5002", "TASK", "Synthetic Count", "FT_INT"),
        ("5003", "TASK", "Synthetic Ratio", "FT_FLOAT_2_DECIMALS"),
        ("5004", "TASK", "Synthetic Amount", "FT_MONEY"),
        ("5005", "TASK", "Synthetic Start", "FT_START_DATE"),
        ("5006", "PROJWBS", "Synthetic Area Date", "FT_END_DATE"),
        ("5007", "PROJECT", "Synthetic Choice", "FT_STATICTYPE"),
    ]
    model.tables.insert(
        0,
        Table(
            "UDFTYPE",
            udf_fields,
            [
                {
                    "udf_type_id": type_id,
                    "table_name": owner,
                    "udf_type_name": f"user_field_{type_id}",
                    "udf_type_label": label,
                    "logical_data_type": kind,
                    "super_flag": "N",
                    "export_flag": "Y",
                }
                for type_id, owner, label, kind in types
            ],
        ),
    )
    model.insert_after(
        "UDFTYPE",
        Table(
            "UDFCODE",
            ["udf_code_id", "udf_type_id", "seq_num", "short_name", "udf_code_name"],
            [
                {
                    "udf_code_id": "5101",
                    "udf_type_id": "5007",
                    "seq_num": "1",
                    "short_name": "SYN-A",
                    "udf_code_name": "Synthetic choice A",
                },
                {
                    "udf_code_id": "5102",
                    "udf_type_id": "5007",
                    "seq_num": "2",
                    "short_name": "SYN-B",
                    "udf_code_name": "Synthetic choice B",
                },
            ],
        ),
    )
    values = [
        {"udf_type_id": "5001", "fk_id": "3002", "udf_text": "Synthetic remark"},
        {"udf_type_id": "5002", "fk_id": "3002", "udf_number": "12"},
        {"udf_type_id": "5003", "fk_id": "3003", "udf_number": "0.25"},
        {"udf_type_id": "5004", "fk_id": "3003", "udf_number": "-1500.5"},
        {"udf_type_id": "5005", "fk_id": "3002", "udf_date": "2030-01-09 08:00"},
        {"udf_type_id": "5006", "fk_id": "2003", "udf_date": "2030-02-28 17:00"},
        {"udf_type_id": "5007", "fk_id": "1001", "udf_code_id": "5102"},
    ]
    for value in values:
        value["proj_id"] = "1001"
    model.tables.append(Table("UDFVALUE", fields_of("UDFVALUE", "RTOVN"), values))
    return _case("udf_all_types", model)


def _activity_codes() -> FixtureCase:
    model = _std()
    model.insert_after(
        "PROJWBS",
        Table(
            "ACTVTYPE",
            fields_of("ACTVTYPE", "RTOVN"),
            [
                {
                    "actv_code_type_id": "7001",
                    "actv_code_type": "Synthetic Phase",
                    "actv_code_type_scope": "AS_Global",
                }
            ],
        ),
    )
    model.insert_after(
        "TASK",
        Table(
            "ACTVCODE",
            fields_of("ACTVCODE", "RTOVN"),
            [
                {
                    "actv_code_id": "7101",
                    "parent_actv_code_id": "",
                    "actv_code_type_id": "7001",
                    "short_name": "P",
                    "actv_code_name": "Synthetic Phase P",
                },
                {
                    "actv_code_id": "7102",
                    "parent_actv_code_id": "7101",
                    "actv_code_type_id": "7001",
                    "short_name": "P1",
                    "actv_code_name": "Synthetic Step P1",
                },
                {
                    "actv_code_id": "7103",
                    "parent_actv_code_id": "7102",
                    "actv_code_type_id": "7001",
                    "short_name": "P1a",
                    "actv_code_name": "",
                },
            ],
        ),
    )
    model.tables.append(
        Table(
            "TASKACTV",
            fields_of("TASKACTV", "RTOVN"),
            [
                {
                    "task_id": "3002",
                    "actv_code_type_id": "7001",
                    "actv_code_id": "7103",
                    "proj_id": "1001",
                },
                {
                    "task_id": "3003",
                    "actv_code_type_id": "7001",
                    "actv_code_id": "7102",
                    "proj_id": "1001",
                },
            ],
        )
    )
    return _case("activity_codes_parent_chain", model)


def _cross_project() -> FixtureCase:
    model = _std()
    row = pred_row("4004", "99001", "3002")
    row["pred_proj_id"] = "1099"
    model.table("TASKPRED").rows.append(row)
    return _case(
        "cross_project_relationship",
        model,
        issues=_row_issue("p6_external_relationship", WARNING, "TASKPRED", 3, "pred_proj_id"),
    )


def _non_ascii_model() -> Model:
    return _with(_std(), "TASK", 1, task_name="Synthetic Café Task €")


def _cp1252_bytes() -> FixtureCase:
    return _case("cp1252_bytes", _non_ascii_model())


def _utf8_bytes() -> FixtureCase:
    return _case("utf8_bytes", _non_ascii_model(), encoding="utf-8")


def _invalid_bytes() -> FixtureCase:
    return _case(
        "invalid_bytes",
        _non_ascii_model(),
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [("p6_encoding_invalid", FATAL, None, None, None)],
        raw=lambda data: data.replace(b"Synthetic Task Two", b"Synthetic Task \x81Two"),
    )


def _bom_utf8() -> FixtureCase:
    return _case(
        "bom_utf8",
        _std(),
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        encoding="utf-8",
        issues=lambda lay: [("p6_header_invalid", FATAL, None, 1, None)],
        raw=lambda data: b"\xef\xbb\xbf" + data,
    )


def _lf_line_ends() -> FixtureCase:
    return _case("lf_line_ends", _std(), newline="\n")


def _trailing_blank_lines() -> FixtureCase:
    return _case("trailing_blank_lines", _std(), lines=lambda lay: [*lay.lines, "", ""])


def _structure(
    name: str,
    mutate: Callable[[Layout], list[str]],
    where: Callable[[Layout], tuple[int | None, str | None]],
) -> FixtureCase:
    def issues(lay: Layout) -> list[IssueTuple]:
        line, table = where(lay)
        return [("p6_structure_invalid", FATAL, table, line, None)]

    return _case(name, _std(), outcome=FAILED, verdict=VERDICT_FAIL, issues=issues, lines=mutate)


def _structure_cases() -> list[FixtureCase]:
    def insert(lines: list[str], at: int, text: str) -> list[str]:
        return [*lines[: at - 1], text, *lines[at - 1 :]]

    task_line = lambda lay: lay.table_line["TASK"]  # noqa: E731
    return [
        _structure("missing_end", lambda lay: lay.lines[:-1], lambda lay: (None, None)),
        _structure(
            "content_after_end",
            lambda lay: [*lay.lines, "%T\tSYNLATE"],
            lambda lay: (len(lay.lines) + 1, None),
        ),
        _structure(
            "record_before_table", lambda lay: insert(lay.lines, 2, "%R\tx"), lambda lay: (2, None)
        ),
        _structure(
            "record_before_fields",
            lambda lay: insert(lay.lines, task_line(lay) + 1, "%R\tx"),
            lambda lay: (task_line(lay) + 1, "TASK"),
        ),
        _structure(
            "duplicate_table",
            lambda lay: [
                *lay.lines[:-1],
                "%T\tTASKPRED",
                lay.lines[lay.table_line["TASKPRED"]],
                "%E",
            ],
            lambda lay: (len(lay.lines), None),
        ),
        _structure(
            "blank_line_inside", lambda lay: insert(lay.lines, 2, ""), lambda lay: (2, None)
        ),
        _structure(
            "table_without_fields",
            lambda lay: insert(lay.lines, 2, "%T\tSYNEMPTY"),
            lambda lay: (3, "SYNEMPTY"),
        ),
    ]


def _duplicate_field() -> FixtureCase:
    model = _std()
    lay = layout(model)
    fields_line = lay.table_line["TASKPRED"] + 1

    def mutate(lay: Layout) -> list[str]:
        lines = list(lay.lines)
        lines[fields_line - 1] += "\tlag_hr_cnt"
        for index in range(len(model.table("TASKPRED").rows)):
            lines[lay.row_line[("TASKPRED", index)] - 1] += "\t0"
        return lines

    return _case(
        "duplicate_field",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        lines=mutate,
        issues=lambda lay: [("p6_structure_invalid", FATAL, "TASKPRED", fields_line, None)],
    )


def _width_mismatch() -> FixtureCase:
    def mutate(lay: Layout) -> list[str]:
        lines = list(lay.lines)
        at = lay.row_line[("TASK", 1)] - 1
        lines[at] = lines[at].rsplit("\t", 1)[0]
        return lines

    return _case(
        "width_mismatch",
        _std(),
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        lines=mutate,
        issues=_row_issue("p6_record_width_mismatch", FATAL, "TASK", 1, None),
    )


def _calendar_midnight_end() -> FixtureCase:
    week = dict.fromkeys(range(2, 7), (("08:00", "12:00"), ("16:00", "00:00")))
    model = _with(_std(), "CALENDAR", 1, clndr_data=calendar_blob(week, BASE_EXCEPTIONS))
    return _case("calendar_midnight_end", model)


def _calendar_without_week() -> FixtureCase:
    model = _with(_std(), "CALENDAR", 1, clndr_data=calendar_blob(None, BASE_EXCEPTIONS))
    return _case(
        "calendar_without_days_of_week",
        model,
        issues=_row_issue("p6_calendar_base_substituted", WARNING, "CALENDAR", 1, "clndr_data"),
    )


def _activity_missing_calendar() -> FixtureCase:
    model = _with(_std(), "TASK", 2, clndr_id="599")
    return _case(
        "activity_missing_calendar",
        model,
        issues=_row_issue("p6_calendar_missing", WARNING, "TASK", 2, "clndr_id"),
    )


def _calendar_unparseable() -> FixtureCase:
    model = _std()
    _with(model, "CALENDAR", 0, clndr_data="(0||CalendarData()(")
    _with(model, "CALENDAR", 1, clndr_data=calendar_blob({2: (("12:00", "08:00"),)}))
    return _case(
        "calendar_unparseable",
        model,
        issues=lambda lay: [
            (
                "p6_calendar_invalid",
                WARNING,
                "CALENDAR",
                lay.row_line[("CALENDAR", 0)],
                "clndr_data",
            ),
            (
                "p6_calendar_missing",
                WARNING,
                "CALENDAR",
                lay.row_line[("CALENDAR", 1)],
                "clndr_data",
            ),
        ],
    )


def _milestones() -> FixtureCase:
    model = _std()
    _with(model, "TASK", 0, cstr_type="CS_MSOA", cstr_date="2030-01-07 08:00")
    _with(model, "TASK", 3, cstr_type="CS_MEOB", cstr_date="2030-01-18 17:00")
    rows = model.table("TASK").rows
    rows.append(
        task_row(
            "3005",
            "SYN-1040",
            "Synthetic Start Two",
            "TT_Mile",
            "2004",
            "0",
            "2030-01-16 08:00",
            "2030-01-16 08:00",
            cstr_type="CS_MEOA",
            cstr_date="2030-01-16 08:00",
        )
    )
    rows.append(
        task_row(
            "3006",
            "SYN-1050",
            "Synthetic Finish Two",
            "TT_FinMile",
            "2004",
            "0",
            "2030-01-15 17:00",
            "2030-01-15 17:00",
            cstr_type="CS_MSOB",
            cstr_date="2030-01-15 17:00",
            cstr_type2="CS_MEOA",
            cstr_date2="2030-01-14 17:00",
        )
    )
    return _case("milestones_with_constraints", model)


def _rcal_project() -> FixtureCase:
    model = _std()
    model.insert_after(
        "CALENDAR",
        Table(
            "SCHEDOPTIONS",
            fields_of("SCHEDOPTIONS", "RTOVN"),
            _schedoptions_rows(
                sched_calendar_on_relationship_lag="rcal_Project",
                sched_retained_logic="N",
                sched_progress_override="N",
            ),
        ),
    )
    return _case("rcal_project_neither_progress_flag", model)


def _relationship_types() -> FixtureCase:
    model = _std()
    model.table("TASKPRED").rows[:] = [
        pred_row("4001", "3001", "3002", "PR_FS", "0"),
        pred_row("4002", "3002", "3003", "PR_SS", "8"),
        pred_row("4003", "3003", "3004", "PR_FF", "-4"),
        pred_row("4004", "3002", "3004", "PR_SF", "2.5"),
    ]
    return _case("relationship_types_and_lags", model)


def _constraints() -> FixtureCase:
    model = _std()
    rows = model.table("TASK").rows
    tokens = (
        "CS_MSOA",
        "CS_MEOA",
        "CS_MSOB",
        "CS_MEOB",
        "CS_MANDSTART",
        "CS_MANDFIN",
        "CS_MSO",
        "CS_MEO",
        "CS_ALAP",
    )
    for index, token in enumerate(tokens):
        task_id = str(3101 + index)
        rows.append(
            task_row(
                task_id,
                f"SYN-2{index:03d}",
                f"Synthetic Constraint {index}",
                "TT_Task",
                "2004",
                "8",
                "2030-01-08 08:00",
                "2030-01-08 17:00",
                cstr_type=token,
                cstr_date="2030-01-08 08:00",
            )
        )
    _with(model, "TASK", 4, cstr_type2="CS_MEOB", cstr_date2="2030-01-20 17:00")
    return _case("constraints_mapping", model)


def _progress() -> FixtureCase:
    model = _std()
    _with(
        model,
        "TASK",
        1,
        status_code="TK_Complete",
        act_start_date="2030-01-07 08:00",
        act_end_date="2030-01-11 17:00",
        remain_drtn_hr_cnt="0",
    )
    _with(
        model,
        "TASK",
        2,
        status_code="TK_Active",
        act_start_date="2030-01-14 08:00",
        remain_drtn_hr_cnt="8",
    )
    return _case("progress_statuses", model)


def _fatal_row(
    name: str, table: str, index: int, field_name: str | None, code: str, **changes: str
) -> FixtureCase:
    model = _with(_std(), table, index, **changes)
    return _case(
        name,
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=_row_issue(code, FATAL, table, index, field_name),
    )


def _multi_project() -> FixtureCase:
    model = _std()
    second = dict(_project_rows()[0], proj_id="1002", proj_short_name="SYN-PRJ2")
    model.table("PROJECT").rows.append(second)
    return _case(
        "multi_project",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=_row_issue("p6_multiple_projects", FATAL, "PROJECT", 1, None),
    )


def _wbs_cycle() -> FixtureCase:
    model = _std()
    _with(model, "PROJWBS", 1, parent_wbs_id="2003")
    return _case(
        "wbs_cycle",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=_row_issue("p6_wbs_cycle", FATAL, "PROJWBS", 1, "parent_wbs_id"),
    )


def _no_project_node() -> FixtureCase:
    """No `PROJWBS` row is the project node: the issue names the table's `%T` line."""
    model = _with(_std(), "PROJWBS", 0, proj_node_flag="N")
    return _case(
        "no_project_node",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=lambda lay: [
            (
                "p6_structure_invalid",
                FATAL,
                "PROJWBS",
                lay.table_line["PROJWBS"],
                "proj_node_flag",
            )
        ],
    )


def _two_project_nodes() -> FixtureCase:
    """A second project node: the issue names the second node's line."""
    model = _with(_std(), "PROJWBS", 3, proj_node_flag="Y")
    return _case(
        "two_project_nodes",
        model,
        outcome=FAILED,
        verdict=VERDICT_FAIL,
        issues=_row_issue("p6_structure_invalid", FATAL, "PROJWBS", 3, "proj_node_flag"),
    )


def _unknown_enum_tolerated() -> FixtureCase:
    model = _with(_std(), "TASK", 1, duration_type="DT_Synthetic")
    return _case(
        "unknown_enum_tolerated",
        model,
        verdict=VERDICT_FINDINGS,
        issues=_row_issue("p6_unknown_enum_value", WARNING, "TASK", 1, "duration_type"),
    )


def _value_invalid_tolerated() -> FixtureCase:
    model = _with(_std(), "TASK", 1, late_start_date="soon")
    return _case(
        "value_invalid_tolerated",
        model,
        issues=_row_issue("p6_value_invalid", WARNING, "TASK", 1, "late_start_date"),
    )


def _over_length_tolerated() -> FixtureCase:
    model = _with(_std(), "TASK", 1, guid="A" * 23)
    return _case(
        "over_length_tolerated",
        model,
        verdict=VERDICT_FAIL,
        issues=_row_issue("p6_value_invalid", WARNING, "TASK", 1, "guid"),
    )


def _dates_with_seconds() -> FixtureCase:
    model = _with(
        _std(),
        "TASK",
        1,
        early_start_date="2030-01-07 08:00:00",
        early_end_date="2030-01-11 17:00:00",
    )
    return _case("dates_with_seconds", model)


CASES: Mapping[str, Callable[[], FixtureCase]] = {
    "minimal_valid": _minimal_valid,
    "no_optional_tables": _no_optional_tables,
    "full_valid": _full_valid,
    "full_selected_capture": _full_selected_capture,
    "unknown_table": _unknown_table,
    "unknown_field": _unknown_field,
    "unknown_field_selected": _unknown_field_selected,
    "missing_tolerated_field": _missing_tolerated_field,
    "missing_required_field": _missing_required_field,
    "missing_required_table": _missing_required_table,
    "version_8_4": lambda: _version("version_8_4", "8.4"),
    "version_19_12": lambda: _version("version_19_12", "19.12"),
    "header_invalid": _header_invalid,
    "version_malformed": _version_malformed,
    "udf_all_types": _udf_types,
    "activity_codes_parent_chain": _activity_codes,
    "cross_project_relationship": _cross_project,
    "cp1252_bytes": _cp1252_bytes,
    "utf8_bytes": _utf8_bytes,
    "invalid_bytes": _invalid_bytes,
    "bom_utf8": _bom_utf8,
    "lf_line_ends": _lf_line_ends,
    "trailing_blank_lines": _trailing_blank_lines,
    **{case.name: (lambda case=case: case) for case in _structure_cases()},
    "duplicate_field": _duplicate_field,
    "width_mismatch": _width_mismatch,
    "calendar_midnight_end": _calendar_midnight_end,
    "calendar_without_days_of_week": _calendar_without_week,
    "activity_missing_calendar": _activity_missing_calendar,
    "calendar_unparseable": _calendar_unparseable,
    "milestones_with_constraints": _milestones,
    "rcal_project_neither_progress_flag": _rcal_project,
    "relationship_types_and_lags": _relationship_types,
    "constraints_mapping": _constraints,
    "progress_statuses": _progress,
    "duplicate_activity_id": lambda: _fatal_row(
        "duplicate_activity_id",
        "TASK",
        2,
        "task_code",
        "p6_duplicate_activity_id",
        task_code="SYN-1010",
    ),
    "empty_activity_id": lambda: _fatal_row(
        "empty_activity_id", "TASK", 2, "task_code", "p6_duplicate_activity_id", task_code=""
    ),
    "duplicate_task_id": lambda: _fatal_row(
        "duplicate_task_id", "TASK", 2, "task_id", "p6_structure_invalid", task_id="3002"
    ),
    "multi_project": _multi_project,
    "dangling_wbs": lambda: _fatal_row(
        "dangling_wbs", "TASK", 2, "wbs_id", "p6_reference_dangling", wbs_id="2999"
    ),
    "dangling_relationship": lambda: _fatal_row(
        "dangling_relationship",
        "TASKPRED",
        1,
        "pred_task_id",
        "p6_reference_dangling",
        pred_task_id="3999",
    ),
    "wbs_cycle": _wbs_cycle,
    "no_project_node": _no_project_node,
    "two_project_nodes": _two_project_nodes,
    "unknown_enum_required": lambda: _fatal_row(
        "unknown_enum_required",
        "TASK",
        1,
        "task_type",
        "p6_unknown_enum_value",
        task_type="TT_Synthetic",
    ),
    "unknown_enum_tolerated": _unknown_enum_tolerated,
    "value_invalid_required": lambda: _fatal_row(
        "value_invalid_required",
        "TASK",
        1,
        "early_start_date",
        "p6_value_invalid",
        early_start_date="2030-13-01 08:00",
    ),
    "value_invalid_tolerated": _value_invalid_tolerated,
    "over_length_tolerated": _over_length_tolerated,
    "bare_cr_in_value": lambda: _fatal_row(
        "bare_cr_in_value", "TASK", 1, "task_name", "p6_value_invalid", task_name="Synthetic\rTask"
    ),
    "dates_with_seconds": _dates_with_seconds,
}


def build(name: str) -> FixtureCase:
    case = CASES[name]()
    if case.name != name:
        raise ValueError(f"case {name} built as {case.name}")
    return case


# --- caps (acceptance A5): each bound at its limit and one past it --------------------------


def _pad_table(name: str, count: int, width: int = 1) -> Table:
    fields = [f"syn_f{index}" for index in range(width)]
    return Table(name, fields, [{fields[0]: "1"} for _ in range(count)])


#: Contract section 5.4 caps, written down here independently of the parser's limits.
CONTRACT_CAPS: Mapping[str, int] = {
    "file_bytes": 16_777_216,
    "line_bytes": 4_194_304,
    "tables": 128,
    "fields_per_table": 512,
    "total_records": 2_000_000,
    "task_records": 25_000,
    "taskpred_records": 100_000,
    "projwbs_records": 25_000,
    "calendar_records": 1_000,
    "calendar_exceptions": 20_000,
    "udftype_records": 2_000,
    "actvtype_records": 2_000,
    "actvcode_records": 100_000,
    "udfvalue_records": 1_000_000,
    "taskactv_records": 500_000,
    "taskrsrc_records": 500_000,
    "value_characters": 65_536,
    "calendar_data_characters": 1_048_576,
    "calendar_tree_depth": 16,
    "calendar_tree_nodes": 100_000,
    "wbs_depth": 64,
}
#: Bounds whose production size is exercised only by the `slow` test; FAST uses these.
TIGHTENED_CAPS: Mapping[str, int] = {
    "taskpred_records": 40,
    "actvcode_records": 40,
    "udfvalue_records": 40,
    "taskactv_records": 40,
    "taskrsrc_records": 40,
    "total_records": 60,
    # 100,000 nodes fill most of the 1,048,576-character blob; the slow test runs them.
    "calendar_tree_nodes": 100,
}


def cap_case(
    bound: str, past: bool, *, production: bool = False
) -> tuple[bytes, Mapping[str, int]]:
    """Bytes at the `bound` (or one past it) and the limit changes to parse them with.

    Bounds in `TIGHTENED_CAPS` are exercised under that tightened cap unless
    `production` is set (the counting code is the same); every other bound is
    exercised at its production value.
    """
    extra = 1 if past else 0
    tightened = bound in TIGHTENED_CAPS and not production
    cap = TIGHTENED_CAPS[bound] if tightened else CONTRACT_CAPS[bound]
    model = _std()
    limits: dict[str, int] = {}
    if bound == "tables":
        for index in range(128 - 5 + extra):
            model.tables.append(_pad_table(f"SYNT{index:03d}", 0))
    elif bound == "fields_per_table":
        model.tables.append(_pad_table("SYNWIDE", 1, 512 + extra))
    elif bound in {"task_records", "projwbs_records"}:
        table = "TASK" if bound == "task_records" else "PROJWBS"
        rows = model.table(table).rows
        template = rows[-1]
        for index in range(25_000 - len(rows) + extra):
            number = str(10_000 + index)
            if table == "TASK":
                rows.append(dict(template, task_id=number, task_code=f"SYN-9{number}"))
            else:
                rows.append(dict(template, wbs_id=number, wbs_short_name=f"W{number}"))
    elif bound == "calendar_records":
        rows = model.table("CALENDAR").rows
        for index in range(1_000 - len(rows) + extra):
            rows.append(
                dict(rows[0], clndr_id=str(10_000 + index), clndr_data=calendar_blob(FIVE_DAY_WEEK))
            )
    elif bound in {"udftype_records", "actvtype_records"}:
        table = "UDFTYPE" if bound == "udftype_records" else "ACTVTYPE"
        key = "udf_type_id" if table == "UDFTYPE" else "actv_code_type_id"
        label = "udf_type_label" if table == "UDFTYPE" else "actv_code_type"
        rows_ = [
            {
                key: str(10_000 + index),
                label: f"Synthetic {index}",
                "table_name": "TASK",
                "logical_data_type": "FT_TEXT",
            }
            for index in range(2_000 + extra)
        ]
        model.tables.append(Table(table, fields_of(table, "RTOVN"), rows_))
    elif bound in {
        "taskpred_records",
        "actvcode_records",
        "udfvalue_records",
        "taskactv_records",
        "taskrsrc_records",
    }:
        table = {
            "taskpred_records": "TASKPRED",
            "actvcode_records": "ACTVCODE",
            "udfvalue_records": "UDFVALUE",
            "taskactv_records": "TASKACTV",
            "taskrsrc_records": "TASKRSRC",
        }[bound]
        if tightened:
            limits[bound] = cap
        if table == "TASKPRED":
            rows = model.table("TASKPRED").rows
            for index in range(cap - len(rows) + extra):
                rows.append(pred_row(str(50_000 + index), "3001", "3004"))
        else:
            model.tables.append(_pad_table(table, cap + extra))
    elif bound == "total_records":
        if tightened:
            limits["total_records"] = cap
        current = sum(len(table.rows) for table in model.tables)
        model.tables.append(_pad_table("SYNPAD", cap - current + extra))
    elif bound == "calendar_exceptions":
        days = [(date(1901, 1, 1) + _days(index), ()) for index in range(20_000 + extra)]
        _with(model, "CALENDAR", 0, clndr_data=calendar_blob(FIVE_DAY_WEEK, days))
    elif bound == "value_characters":
        model.tables.append(Table("SYNLONG", ["syn_text"], [{"syn_text": "x" * (65_536 + extra)}]))
    elif bound == "calendar_data_characters":
        blob = calendar_blob(FIVE_DAY_WEEK)
        padding = " " * (1_048_576 - len(blob) + extra)
        _with(model, "CALENDAR", 0, clndr_data=blob[:-1] + padding + blob[-1:])
    elif bound == "calendar_tree_depth":
        nested = "(0||SYN()())"
        for _ in range(16 - 2 + extra):
            nested = f"(0||SYN()({nested}))"
        _with(model, "CALENDAR", 0, clndr_data=calendar_blob(FIVE_DAY_WEEK, extra=nested))
    elif bound == "calendar_tree_nodes":
        if tightened:
            limits["calendar_tree_nodes"] = cap
        blob = calendar_blob(FIVE_DAY_WEEK)
        used = blob.count("(0||")
        # 10 characters a node: 100,000 of them stay inside the calendar data cap.
        _with(
            model,
            "CALENDAR",
            0,
            clndr_data=calendar_blob(FIVE_DAY_WEEK, extra="(0||S()())" * (cap - used + extra)),
        )
    elif bound == "wbs_depth":
        rows = model.table("PROJWBS").rows
        parent = "2001"
        for index in range(64 + extra):
            wbs_id = str(20_000 + index)
            rows.append(
                dict(rows[1], wbs_id=wbs_id, parent_wbs_id=parent, wbs_short_name=f"L{index}")
            )
            parent = wbs_id
    elif bound == "line_bytes":
        width = 64
        model.tables.append(Table("SYNLINE", [f"syn_f{index}" for index in range(width)], []))
        lay = layout(model)
        prefix = len("%R") + width  # the tag and one tab before each value
        total = 4_194_304 + extra - prefix
        values = [65_536] * (total // 65_536) + [total % 65_536]
        values = [value for value in values if value][:width]
        values += [0] * (width - len(values))
        row = "\t".join(["%R", *("y" * size for size in values)])
        lines = [*lay.lines[:-1], row, "%E"]
        return encode(lines), limits
    elif bound == "file_bytes":
        lay = layout(model)
        base = encode([*lay.lines[:-1], "%T\tSYNFILE", "%F\tsyn_pad", "%E"])
        room = 16_777_216 + extra - len(base)
        rows: list[str] = []
        while room > 0:
            size = min(65_536, room - len("%R\t\r\n"))
            rows.append("%R\t" + "z" * max(size, 0))
            room -= max(size, 0) + len("%R\t\r\n")
        lines = [*lay.lines[:-1], "%T\tSYNFILE", "%F\tsyn_pad", *rows, "%E"]
        data = encode(lines)
        if len(data) != 16_777_216 + extra:
            raise ValueError("file cap fixture has the wrong size")
        return data, limits
    else:
        raise KeyError(bound)
    return encode(layout(model).lines), limits


def _days(count: int) -> timedelta:
    return timedelta(days=count)


# --- goldens --------------------------------------------------------------------------------


def golden_record(case: FixtureCase) -> dict[str, object]:
    """What the golden file pins for one case (the parser is imported lazily, here only)."""
    from my_pa.domain.schedule.p6 import frame_sha256, parse_xer
    from my_pa.domain.schedule.p6.profile import verdict

    result = parse_xer(case.data, capture=case.capture)
    return {
        "frame_sha256": frame_sha256(result),
        "input_sha256": hashlib.sha256(case.data).hexdigest(),
        "issues": [
            [issue.code.value, issue.severity.value, issue.table, issue.line, issue.field]
            for issue in result.issues
        ],
        "outcome": result.outcome.value,
        "verdict": verdict(result).value,
    }


def record_goldens(path: Path = GOLDEN_FILE) -> Path:
    """Write every case's golden record (explicit command only; no test calls it)."""
    records = {name: golden_record(build(name)) for name in CASES}
    document = {"generator_version": GENERATOR_VERSION, "cases": records}
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schedule_p6_xer")
    parser.add_argument("command", choices=["record-goldens"])
    parser.parse_args(argv)
    print(record_goldens())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
