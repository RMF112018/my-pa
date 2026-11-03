"""Synthetic Schedule Scenario networks: the contract's golden vectors and builders.

Contract `docs/architecture/schedule-scenarios-contract.md` section 3.12. The
vectors name activities `A`, `B`, ...; an added activity key must be `x:<token>`
(section 2.4), so `A` is written `x:A` here (the order of the keys is
unchanged). "1d" is 480 minutes; `std` is Monday-Friday 08:00-16:00. Every
value is synthetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Final

from my_pa.domain.schedule.scenario.model import (
    ActivityConstraint,
    ActivityKind,
    ActivityProgress,
    CalendarException,
    ConstraintType,
    LagCalendar,
    ProgressPolicy,
    RelationshipType,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioRelationship,
    ScenarioSettings,
    parse_instant,
)

DAY: Final = 480
WORKDAY: Final = ((480, 960),)
STD: Final = ScenarioCalendar("std", (WORKDAY,) * 5 + ((), ()))
C6: Final = ScenarioCalendar("c6", (WORKDAY,) * 6 + ((),))


def at(text: str) -> int:
    """`"01-04 08:00"` -> axis minutes; month 12 is 2026, every other month 2027."""
    month_day, clock = text.split(" ")
    year = "2026" if month_day.startswith("12-") else "2027"
    return parse_instant(f"{year}-{month_day}T{clock}")


def key(name: str) -> str:
    return name if name.startswith(("x:", "sact_")) else f"x:{name}"


def task(
    name: str,
    minutes: int | None,
    *,
    calendar: str | None = None,
    constraints: Sequence[tuple[ConstraintType, str]] = (),
    started: str | None = None,
    finished: str | None = None,
) -> ScenarioActivity:
    progress = None
    if started is not None:
        progress = ActivityProgress(
            actual_start=at(started), actual_finish=None if finished is None else at(finished)
        )
    return ScenarioActivity(
        key=key(name),
        name=f"Activity {name}",
        kind=ActivityKind.TASK,
        original_minutes=minutes,
        remaining_minutes=minutes,
        calendar=calendar,
        constraints=tuple(ActivityConstraint(kind, at(when)) for kind, when in constraints),
        progress=progress,
    )


def milestone(name: str) -> ScenarioActivity:
    return ScenarioActivity(
        key=key(name),
        name=f"Milestone {name}",
        kind=ActivityKind.MILESTONE,
        original_minutes=0,
        remaining_minutes=0,
    )


def link(pred: str, succ: str, kind: str = "FS", lag: int = 0) -> ScenarioRelationship:
    return ScenarioRelationship(key(pred), key(succ), RelationshipType(kind), lag)


def network(
    activities: Sequence[ScenarioActivity],
    relationships: Sequence[ScenarioRelationship] = (),
    *,
    data_date: str = "01-04 00:00",
    calendars: Sequence[ScenarioCalendar] = (STD,),
    default_calendar: str = "std",
    lag_calendar: LagCalendar = LagCalendar.PREDECESSOR,
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC,
    must_finish_by: str | None = None,
    threshold: int = 0,
) -> ScenarioContent:
    return ScenarioContent(
        data_date=parse_instant(data_date) if "T" in data_date else at(data_date),
        settings=ScenarioSettings(
            default_calendar=default_calendar,
            lag_calendar=lag_calendar,
            progress_policy=progress_policy,
            must_finish_by=None if must_finish_by is None else at(must_finish_by),
            critical_float_threshold_minutes=threshold,
        ),
        calendars=tuple(calendars),
        activities=tuple(activities),
        relationships=tuple(relationships),
    )


SNET, FNET, SNLT, FNLT, MSO, MFO = (
    ConstraintType.SNET,
    ConstraintType.FNET,
    ConstraintType.SNLT,
    ConstraintType.FNLT,
    ConstraintType.MSO,
    ConstraintType.MFO,
)


def _g06(lag_calendar: LagCalendar) -> ScenarioContent:
    return network(
        [task("A", DAY, calendar="c6", constraints=[(SNET, "01-08 00:00")]), task("B", DAY)],
        [link("A", "B", "FS", 960)],
        calendars=(STD, C6),
        lag_calendar=lag_calendar,
    )


def _g11(policy: ProgressPolicy) -> ScenarioContent:
    return network(
        [
            task("A", 0, started="01-04 08:00", finished="01-04 16:00"),
            task("B", 2 * DAY, started="01-05 08:00"),
            task("C", DAY),
            task("E", DAY, started="01-05 08:00"),
        ],
        [link("A", "B"), link("B", "C"), link("C", "E")],
        data_date="01-06 00:00",
        progress_policy=policy,
    )


GOLDEN_NETWORKS: Final[dict[str, ScenarioContent]] = {
    "G01": network([task("A", 3 * DAY)]),
    "G02": network(
        [task("A", DAY), task("B", 2 * DAY), task("C", DAY), task("D", DAY)],
        [link("A", "B"), link("B", "D"), link("A", "C"), link("C", "D")],
    ),
    "G03": network(
        [task("A", 3 * DAY), task("B", 2 * DAY), task("C", DAY)],
        [link("A", "B", "SS", 480), link("A", "C", "FF", 480)],
    ),
    "G04": network([task("A", 2 * DAY), task("B", DAY)], [link("A", "B", "FS", -240)]),
    "G05": network([task("A", DAY), task("B", DAY)], [link("A", "B", "SF", 1440)]),
    "G06a": _g06(LagCalendar.PREDECESSOR),
    "G06b": _g06(LagCalendar.SUCCESSOR),
    "G06c": _g06(LagCalendar.TWENTY_FOUR_HOUR),
    "G07": network(
        [task("A", 3 * DAY)],
        calendars=(
            ScenarioCalendar(
                "std", STD.week, (CalendarException(day=date(2027, 1, 5), intervals=()),)
            ),
        ),
    ),
    "G08": network(
        [
            task("A", 2 * DAY),
            task("B", 2 * DAY, constraints=[(FNLT, "01-05 16:00")]),
            task("C", DAY, constraints=[(SNET, "01-06 12:00")]),
        ],
        [link("A", "B")],
    ),
    "G09": network(
        [task("A", 2 * DAY), task("B", DAY, constraints=[(MSO, "01-05 08:00")])],
        [link("A", "B")],
    ),
    "G10": network([task("A", 5 * DAY)], must_finish_by="01-07 16:00"),
    "G11a": _g11(ProgressPolicy.RETAINED_LOGIC),
    "G11b": _g11(ProgressPolicy.PROGRESS_OVERRIDE),
    "G12": network(
        [milestone("M0"), task("A", DAY), milestone("M1")],
        [link("M0", "A"), link("A", "M1")],
    ),
    "G13": network(
        [task("A", DAY), task("B", 2 * DAY), task("C", 2 * DAY), task("E", DAY)],
        [link("A", "B"), link("B", "E"), link("A", "C"), link("C", "E")],
    ),
    "G14": network(
        [task(name, DAY) for name in ("A", "B", "C", "D", "Z")],
        [link("A", "B"), link("B", "C"), link("C", "A"), link("D", "A"), link("C", "Z")],
    ),
    "G15": network(
        [task("A", DAY), task("B", 3 * DAY), task("C", DAY), task("X", DAY), task("E", DAY)],
        [link("A", "B"), link("B", "E"), link("A", "C"), link("C", "X"), link("X", "E")],
    ),
    "G16": network([task("A", None)]),
    "G17": network([task("A", DAY, constraints=[(FNET, "01-06 16:00")])]),
    "G18": network(
        [task("A", 2 * DAY), task("B", DAY, constraints=[(SNLT, "01-05 08:00")])],
        [link("A", "B")],
    ),
    "G19": network([task("A", DAY, constraints=[(MFO, "01-06 16:00")]), task("B", DAY)]),
    "G20": network([task("A", DAY, constraints=[(MSO, "01-04 08:00")])], data_date="01-06 00:00"),
    "G21": network(
        [task("A", DAY, constraints=[(SNET, "01-08 00:00")], started="01-05 08:00")],
        data_date="01-06 00:00",
    ),
    "G22": network(
        [task("A", 2 * DAY, started="01-05 08:00"), task("B", DAY)],
        [link("A", "B", "SS")],
        data_date="01-06 00:00",
    ),
    "G23": network(
        [task("A", DAY), task("B", DAY, started="01-05 08:00")],
        [link("A", "B", "SS")],
        data_date="01-06 00:00",
        progress_policy=ProgressPolicy.PROGRESS_OVERRIDE,
    ),
    "G24": network([task("A", 2 * DAY)], data_date="2099-12-31T00:00"),
}


def maximal_network() -> ScenarioContent:
    """A network at every section 2.10 maximum, built to make the engine work hardest.

    25,000 activities with 66-character keys, 100,000 relationships (a
    24,999-link FS spine plus 75,001 FF/SF links, the types that cost 2
    calendar calls in each pass), 32 calendars with 62 holidays each, an early
    and a late constraint on every not-started activity, and some progress.
    Deterministic: no randomness, only arithmetic on the index.
    """
    count, links = 25_000, 100_000
    calendars = tuple(
        ScenarioCalendar(
            f"cal{index:02d}",
            tuple(
                ((480 + 15 * (index % 4), 960),) if weekday < 5 + index % 2 else ()
                for weekday in range(7)
            ),
            tuple(
                CalendarException(
                    day=date.fromordinal(date(2027, 1, 4 + index % 5).toordinal() + 7 * week),
                    intervals=(),
                )
                for week in range(62)
            ),
        )
        for index in range(32)
    )
    keys = [f"x:{index:06d}" + "k" * 58 for index in range(count)]
    activities = []
    for index, name in enumerate(keys):
        minutes = (0, 60, 120, 240, 480)[index % 5]
        common = {
            "key": name,
            "name": f"Activity {index}",
            "kind": ActivityKind.TASK,
            "original_minutes": minutes,
            "calendar": f"cal{index % 32:02d}",
        }
        if index < 200:
            activities.append(
                ScenarioActivity(
                    **common,  # type: ignore[arg-type]
                    remaining_minutes=minutes,
                    progress=ActivityProgress(actual_start=at("01-04 08:00")),
                )
            )
            continue
        activities.append(
            ScenarioActivity(
                **common,  # type: ignore[arg-type]
                remaining_minutes=minutes,
                constraints=(
                    ActivityConstraint(ConstraintType.FNET, at("01-11 16:00")),
                    ActivityConstraint(ConstraintType.FNLT, parse_instant("2050-12-30T16:00")),
                ),
            )
        )
    relationships = [
        ScenarioRelationship(keys[index], keys[index + 1], RelationshipType.FS, 0)
        for index in range(count - 1)
    ]
    step = 2
    while len(relationships) < links:
        for index in range(count - step):
            if len(relationships) == links:
                break
            kind = RelationshipType.FF if (index + step) % 2 else RelationshipType.SF
            relationships.append(
                ScenarioRelationship(keys[index], keys[index + step], kind, (index % 7 - 3) * 60)
            )
        step += 1
    return network(
        activities,
        relationships,
        data_date="01-06 00:00",
        calendars=calendars,
        default_calendar="cal00",
    )
