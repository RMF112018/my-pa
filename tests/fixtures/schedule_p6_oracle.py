"""Synthetic P6 XER exports for the S7-5 engine-vs-P6 oracle (contract sections 11.5, 14).

Every case's P6 numbers (early/late dates, total float, remaining early start)
are written **by hand** from the engine's rules (S6 section 3, contract
section 11.7) on the calendars below; none is produced by running the engine,
so the oracle test is a real check of the engine against an independent
statement of what it should compute. Every name, code and value is invented.

Calendar `501` (the project default) works Monday to Friday 08:00-12:00 and
13:00-17:00 with no exception; calendar `502` works the same hours Monday to
Saturday. Rows are written in a file order that differs from the Activity ID
order on purpose, so a join by row order cannot pass.

Cases:

- `exact`: 4 tasks, a lag, an open end with float; threshold 24 h, so the
  floating task is critical in both; content v1; the oracle shares are 100%.
- `mismatch`: `exact` with P6's early finish of `SYN-2040` planted 60 minutes
  early (the same day), which the oracle must report.
- `milestones`: start and finish milestones (content v2): a start milestone
  after a 17:00 finish is the next working start, a finish milestone stays at
  17:00.
- `rcal_project`: lags on the project calendar while the activities use
  calendar `502` (a fixed lag calendar, content v2).
- `progress`: a complete activity (P6 leaves its late dates empty), an
  in-progress one under retained logic, and a not-started one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from tests.fixtures import schedule_p6_xer as fx

__all__ = ["CASES", "build", "exact_full", "model", "task"]

WORKDAY: Final = (("08:00", "12:00"), ("13:00", "17:00"))
MON_FRI: Final = dict.fromkeys(range(2, 7), WORKDAY)
MON_SAT: Final = dict.fromkeys(range(2, 8), WORKDAY)


def task(
    task_id: str,
    code: str,
    hours: str,
    early: tuple[str, str],
    late: tuple[str, str] | None = None,
    *,
    total_float: str = "0",
    task_type: str = "TT_Task",
    restart: str | None = None,
    **extra: str,
) -> dict[str, str]:
    """A TASK row with P6's own early/late dates, total float and remaining early start."""
    row = fx.task_row(task_id, code, f"Synthetic {code}", task_type, "2003", hours, *early)
    late_start, late_finish = late if late is not None else early
    row.update(
        late_start_date=late_start,
        late_end_date=late_finish,
        total_float_hr_cnt=total_float,
        restart_date=early[0] if restart is None else restart,
        reend_date=early[1],
    )
    row.update(extra)
    return row


def model(
    tasks: list[dict[str, str]],
    preds: list[dict[str, str]],
    *,
    data_date: str = "2030-01-07 08:00",
    threshold: str = "0",
    calendars: Mapping[str, Mapping[int, object]] | None = None,
    level: str = "standard",
    **options: str,
) -> fx.Model:
    """The synthetic model (`standard`, or `full` with every sample table) with these rows."""
    built = fx.base_model(level)
    built.table("PROJECT").rows[0].update(
        last_recalc_date=data_date, critical_drtn_hr_cnt=threshold
    )
    weeks = {"501": MON_FRI, **(calendars or {})}
    rows = built.table("CALENDAR").rows
    base = next(row for row in rows if row["clndr_id"] == "501")
    rows[:] = [row for row in rows if row["clndr_id"] != "501"]
    for clndr_id, week in weeks.items():
        rows.append(
            {
                **base,
                "clndr_id": clndr_id,
                "clndr_name": f"Synthetic Calendar {clndr_id}",
                "clndr_data": fx.calendar_blob(week),  # type: ignore[arg-type]
            }
        )
    built.table("TASK").rows = tasks
    built.table("TASKPRED").rows = preds
    schedoptions = fx._schedoptions_rows(**options)
    if level == "full":
        built.table("SCHEDOPTIONS").rows = schedoptions
    else:
        built.insert_after(
            "CALENDAR",
            fx.Table("SCHEDOPTIONS", fx.fields_of("SCHEDOPTIONS", "RT"), schedoptions),
        )
    return built


def _exact_tasks() -> list[dict[str, str]]:
    # SYN-2010 16 h Mon-Tue; SYN-2020 8 h Wed (FS); SYN-2030 4 h Wed morning (FS, open
    # end: late Fri 13:00-17:00, float 4 + 8 + 8 = 20 h); SYN-2040 8 h Fri after an
    # 8 h lag from SYN-2020 (lag ends Thu 17:00, so it starts Fri 08:00).
    return [
        task(
            "3003",
            "SYN-2030",
            "4",
            ("2030-01-09 08:00", "2030-01-09 12:00"),
            ("2030-01-11 13:00", "2030-01-11 17:00"),
            total_float="20",
        ),
        task("3001", "SYN-2010", "16", ("2030-01-07 08:00", "2030-01-08 17:00")),
        task("3004", "SYN-2040", "8", ("2030-01-11 08:00", "2030-01-11 17:00")),
        task("3002", "SYN-2020", "8", ("2030-01-09 08:00", "2030-01-09 17:00")),
    ]


def _exact_preds() -> list[dict[str, str]]:
    return [
        fx.pred_row("4001", "3001", "3002"),
        fx.pred_row("4002", "3001", "3003"),
        fx.pred_row("4003", "3002", "3004", lag="8"),
    ]


def _exact(level: str = "standard") -> fx.Model:
    return model(_exact_tasks(), _exact_preds(), threshold="24", level=level)


def _mismatch() -> fx.Model:
    built = _exact()
    for row in built.table("TASK").rows:
        if row["task_code"] == "SYN-2040":
            row["early_end_date"] = "2030-01-11 16:00"  # planted: 60 minutes early
    return built


def _milestones() -> fx.Model:
    tasks = [
        task(
            "3004",
            "SYN-3030",
            "0",
            ("2030-01-09 08:00", "2030-01-09 08:00"),
            task_type="TT_Mile",
        ),
        task(
            "3001",
            "SYN-3000",
            "0",
            ("2030-01-07 08:00", "2030-01-07 08:00"),
            task_type="TT_Mile",
        ),
        task(
            "3003",
            "SYN-3020",
            "0",
            ("2030-01-08 17:00", "2030-01-08 17:00"),
            task_type="TT_FinMile",
        ),
        task("3002", "SYN-3010", "16", ("2030-01-07 08:00", "2030-01-08 17:00")),
    ]
    preds = [
        fx.pred_row("4001", "3001", "3002"),
        fx.pred_row("4002", "3002", "3003"),
        fx.pred_row("4003", "3002", "3004"),
    ]
    return model(tasks, preds)


def _rcal_project() -> fx.Model:
    # Both tasks on Mon-Sat calendar 502, lags on the project calendar 501 (Mon-Fri):
    # SYN-4010 16 h Thu-Fri; the 8 h lag skips Saturday and ends Mon 17:00, so SYN-4020
    # starts Tue 08:00. Backward: the lag back from Tue 08:00 is Mon 08:00, whose
    # previous working end on 502 is Sat 17:00: SYN-4010 late Fri 08:00 - Sat 17:00,
    # float 8 h.
    tasks = [
        task(
            "3002",
            "SYN-4020",
            "8",
            ("2030-01-15 08:00", "2030-01-15 17:00"),
            clndr_id="502",
        ),
        task(
            "3001",
            "SYN-4010",
            "16",
            ("2030-01-10 08:00", "2030-01-11 17:00"),
            ("2030-01-11 08:00", "2030-01-12 17:00"),
            total_float="8",
            clndr_id="502",
        ),
    ]
    preds = [fx.pred_row("4001", "3001", "3002", lag="8")]
    return model(
        tasks,
        preds,
        data_date="2030-01-10 08:00",
        calendars={"502": MON_SAT},
        sched_calendar_on_relationship_lag="rcal_Project",
    )


def _progress() -> fx.Model:
    # Data date Wed 08:00. SYN-5010 complete Mon (P6: early = actual, late dates empty,
    # a total float of 0 the engine does not compute for complete work); SYN-5020
    # started Tue, 8 h remaining from the data date (retained logic); SYN-5030 Thu.
    tasks = [
        task(
            "3003",
            "SYN-5030",
            "8",
            ("2030-01-10 08:00", "2030-01-10 17:00"),
        ),
        task(
            "3001",
            "SYN-5010",
            "8",
            ("2030-01-07 08:00", "2030-01-07 17:00"),
            ("", ""),
            restart="",
            status_code="TK_Complete",
            remain_drtn_hr_cnt="0",
            act_start_date="2030-01-07 08:00",
            act_end_date="2030-01-07 17:00",
        ),
        task(
            "3002",
            "SYN-5020",
            "16",
            ("2030-01-08 08:00", "2030-01-09 17:00"),
            ("2030-01-09 08:00", "2030-01-09 17:00"),
            restart="2030-01-09 08:00",
            status_code="TK_Active",
            remain_drtn_hr_cnt="8",
            act_start_date="2030-01-08 08:00",
        ),
    ]
    preds = [fx.pred_row("4001", "3001", "3002"), fx.pred_row("4002", "3002", "3003")]
    return model(tasks, preds, data_date="2030-01-09 08:00")


def exact_full() -> fx.Model:
    """`exact` with every sample table and optional field (for the planted-marker test)."""
    return _exact("full")


CASES: Final[Mapping[str, Callable[[], fx.Model]]] = {
    "exact": _exact,
    "mismatch": _mismatch,
    "milestones": _milestones,
    "rcal_project": _rcal_project,
    "progress": _progress,
}


def build(name: str) -> bytes:
    """The case's XER bytes (cp1252, CRLF)."""
    return fx.encode(fx.layout(CASES[name]()).lines)
