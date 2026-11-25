"""Profile `p6_xer_v1`: XER bytes to the typed plain-data parse (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3-7.
`parse_xer` is a pure function of the bytes, the capture selection and the
limits: no clock, no randomness, no IO. Fatal checks run in the section 5.5
order and the parse stops at the first fatal issue (within one check, the
first by line); non-fatal issues are collected. Unknown tables and fields are
observed with statistics only (section 7.4) and reported once (section 5.2).

Decisions this module takes where the contract is silent are listed in the
S7-1 report and in the docstrings of the helpers that take them:

* a repeated entity id (`task_id`, `wbs_id`, `clndr_id`, `task_pred_id`) is
  `p6_structure_invalid` (two rows cannot share a key);
* a non-project WBS row whose parent names no row is `p6_reference_dangling`;
* `wbs_path` holds `wbs_short_name` labels below the project node, and the WBS
  depth bound counts those levels;
* an empty `task_code` is `p6_duplicate_activity_id` (5.5: "repeated or empty").
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

from my_pa.domain.schedule.p6.calendar import (
    CalendarBoundError,
    CalendarData,
    CalendarDataError,
    parse_calendar_data,
)
from my_pa.domain.schedule.p6.catalogue import (
    CATALOGUE,
    CATALOGUE_VERSION,
    REQUIRED_TABLES,
    TESTED_VERSION_PREFIX,
    UDF_OWNERS,
    WILDCARD_TABLES,
    CatalogueField,
    EntityKind,
    Tier,
    ValueType,
    catalogue_field,
    is_catalogued_table,
    table_fields,
)
from my_pa.domain.schedule.p6.model import (
    MAX_LISTED_ISSUES,
    P6_LIMITS,
    PROFILE_ID,
    PROFILE_VERSION,
    Bound,
    CalendarStatus,
    P6Calendar,
    P6Entity,
    P6FieldValue,
    P6Issue,
    P6IssueCode,
    P6Limits,
    P6ObservedField,
    P6ObservedTable,
    P6Outcome,
    P6ParseResult,
    P6Severity,
    P6Value,
)
from my_pa.domain.schedule.p6.reader import RawRead, RawTable, read_xer, safe_name
from my_pa.domain.schedule.p6.values import (
    ReadingStatus,
    has_forbidden_control,
    read_text,
    read_value,
    value_shape,
)

__all__ = ["FIELD_KEY_PATTERN", "default_capture_keys", "parse_xer"]

#: Section 7.7 field key grammar.
FIELD_KEY_PATTERN: Final = re.compile(
    r"^(xer:[A-Z][A-Z0-9_]{0,31}\.[A-Za-z][A-Za-z0-9_]{0,63}|udf:[A-Z]{1,16}:.{1,120}|code:.{1,120})$"
)
_UNKNOWN_TOKEN: Final = re.compile(r"^[A-Za-z]{1,8}_[A-Za-z0-9_]{1,40}$")
_MAX_UNKNOWN_TOKENS: Final = 20
_LABEL_CHARACTERS: Final = 120
_CODE_PATH_LABELS: Final = 8
_CALENDAR_DATA_DOMAIN: Final = b"p6-calendar-data-v1\n"
#: An object id in a generic (V) column: ASCII digits only. `str.isdigit` is not
#: used: it admits superscript and other Unicode digits that `int` either refuses
#: (an uncaught error) or silently converts.
_OBJECT_ID: Final = re.compile(r"[0-9]{1,18}")

#: Entity tables and the field that keys their rows.
_ENTITY_KEY: Final[Mapping[str, str]] = {
    "PROJECT": "proj_id",
    "CALENDAR": "clndr_id",
    "PROJWBS": "wbs_id",
    "TASK": "task_id",
    "TASKPRED": "task_pred_id",
}
_TYPED_TABLES: Final = ("PROJECT", "SCHEDOPTIONS", "CALENDAR", "PROJWBS", "TASK", "TASKPRED")
_KIND: Final[Mapping[str, str]] = {"TT_Mile": "start_milestone", "TT_FinMile": "finish_milestone"}


class _StopError(Exception):
    def __init__(self, issue: P6Issue) -> None:
        super().__init__(issue.code.value)
        self.issue = issue


def _fatal(
    code: P6IssueCode,
    *,
    table: str | None = None,
    line: int | None = None,
    field: str | None = None,
    bound: Bound | None = None,
) -> _StopError:
    return _StopError(
        P6Issue(
            code,
            P6Severity.FATAL,
            table=None if table is None else safe_name(table),
            line=line,
            field=None if field is None else safe_name(field),
            bound=bound,
        )
    )


class _Issues:
    """Issues in discovery order, listed up to `MAX_LISTED_ISSUES`, counted always."""

    def __init__(self) -> None:
        self.listed: list[P6Issue] = []
        self.counts: dict[str, int] = {}

    def add(self, issue: P6Issue) -> None:
        self.counts[issue.code.value] = self.counts.get(issue.code.value, 0) + 1
        if len(self.listed) < MAX_LISTED_ISSUES:
            self.listed.append(issue)

    def warn(
        self,
        code: P6IssueCode,
        *,
        table: str | None = None,
        line: int | None = None,
        field: str | None = None,
        severity: P6Severity = P6Severity.WARNING,
    ) -> None:
        self.add(
            P6Issue(
                code,
                severity,
                table=None if table is None else safe_name(table),
                line=line,
                field=None if field is None else safe_name(field),
            )
        )


@dataclass(frozen=True, slots=True)
class _Row:
    line: int
    index: int
    values: Mapping[str, P6Value]


def default_capture_keys() -> frozenset[str]:
    """The catalogue's default-captured (O+) generic-store keys; UDF and code keys join per file."""
    return frozenset(
        field.field_key
        for field in CATALOGUE
        if field.tier is Tier.OPTIONAL_DEFAULT and field.is_generic_store
    )


def _validate_selection(capture: Collection[str] | None, limits: P6Limits) -> frozenset[str] | None:
    if capture is None:
        return None
    keys = frozenset(capture)
    if len(keys) > limits.captured_fields:
        raise ValueError("capture selection exceeds the captured-field cap")
    for key in keys:
        if not FIELD_KEY_PATTERN.match(key):
            raise ValueError("capture selection holds a malformed field key")
    return keys


class _Mapper:
    def __init__(
        self,
        raw: RawRead,
        limits: P6Limits,
        issues: _Issues,
        selection: frozenset[str] | None,
    ) -> None:
        self.raw = raw
        self.limits = limits
        self.issues = issues
        self.selection = selection
        self.tables: dict[str, RawTable] = {table.name: table for table in raw.tables}
        self.rows: dict[str, list[_Row]] = {}
        self.calendar_data: dict[int, CalendarData | None] = {}
        self.captured_keys: frozenset[str] = frozenset()

    # -- non-fatal observations (5.1, 5.2) -------------------------------------------------

    def observe_unknowns(self) -> None:
        for table in self.raw.tables:
            if not is_catalogued_table(table.name):
                self.issues.warn(P6IssueCode.UNKNOWN_TABLE, table=table.name, line=table.line)
                continue
            if table.name in WILDCARD_TABLES:
                continue
            for name in table.fields:
                if catalogue_field(table.name, name) is not None:
                    continue
                code = (
                    P6IssueCode.UNKNOWN_FIELD
                    if safe_name(name)
                    else P6IssueCode.UNKNOWN_FIELD_UNNAMED
                )
                self.issues.warn(code, table=table.name, line=table.line, field=name)
            for field in table_fields(table.name):
                if field.tier is Tier.TOLERATED and field.field not in table.fields:
                    self.issues.warn(
                        P6IssueCode.TOLERATED_FIELD_MISSING,
                        table=table.name,
                        line=table.line,
                        field=field.field,
                        severity=P6Severity.INFO,
                    )

    # -- fatal stages (5.5) ----------------------------------------------------------------

    def parse_calendar_blobs(self) -> None:
        """Calendar caps are bounds (5.4), so every blob is parsed before later checks."""
        table = self.tables.get("CALENDAR")
        if table is None:
            return
        data_index = table.index("clndr_data")
        id_index = table.index("clndr_id")
        if data_index is None or id_index is None:
            return
        id_field = catalogue_field("CALENDAR", "clndr_id")
        assert id_field is not None  # noqa: S101 - catalogue invariant
        for line, values in table.rows:
            reading = read_value(id_field, values[id_index])
            blob = values[data_index]
            try:
                data = parse_calendar_data(
                    blob,
                    max_depth=self.limits.calendar_tree_depth,
                    max_nodes=self.limits.calendar_tree_nodes,
                    max_exceptions=self.limits.calendar_exceptions,
                )
            except CalendarBoundError as error:
                raise _fatal(
                    P6IssueCode.BOUND_EXCEEDED,
                    table="CALENDAR",
                    line=line,
                    field="clndr_data",
                    bound=error.bound,
                ) from None
            except CalendarDataError:
                data = None
            if data is not None and has_forbidden_control(blob, calendar_data=True):
                data = None  # section 3.2: only 0x7F may join tab among the controls here
            if reading.status is ReadingStatus.OK and isinstance(reading.value, int):
                self.calendar_data.setdefault(reading.value, data)

    def require(self) -> None:
        for name in REQUIRED_TABLES:
            if name not in self.tables:
                raise _fatal(P6IssueCode.REQUIRED_TABLE_MISSING, table=name)
        for name in REQUIRED_TABLES:
            table = self.tables[name]
            for field in table_fields(name):
                if field.required and field.field not in table.fields:
                    raise _fatal(
                        P6IssueCode.REQUIRED_FIELD_MISSING,
                        table=name,
                        line=table.line,
                        field=field.field,
                    )
        project = self.tables["PROJECT"]
        if not project.rows:
            raise _fatal(P6IssueCode.REQUIRED_TABLE_MISSING, table="PROJECT", line=project.line)
        if len(project.rows) > 1:
            raise _fatal(P6IssueCode.MULTIPLE_PROJECTS, table="PROJECT", line=project.rows[1][0])

    def read_typed(self) -> None:
        invalid: list[tuple[int, str, str]] = []
        unknown: list[tuple[int, str, str]] = []
        present = sorted(
            (self.tables[name] for name in _TYPED_TABLES if name in self.tables),
            key=lambda table: table.position,
        )
        for table in present:
            fields = [
                (field, index)
                for field in table_fields(table.name)
                if field.is_typed
                and field.value_type is not ValueType.BLOB
                and (index := table.index(field.field)) is not None
            ]
            rows: list[_Row] = []
            for row_index, (line, values) in enumerate(table.rows):
                typed: dict[str, P6Value] = {}
                for field, index in fields:
                    typed[field.field] = self._typed_value(
                        field, values[index], table.name, line, invalid, unknown
                    )
                rows.append(_Row(line, row_index, typed))
            self.rows[table.name] = rows
        if invalid:
            line, table_name, field_name = min(invalid)
            raise _fatal(P6IssueCode.VALUE_INVALID, table=table_name, line=line, field=field_name)
        if unknown:
            line, table_name, field_name = min(unknown)
            raise _fatal(
                P6IssueCode.UNKNOWN_ENUM_VALUE, table=table_name, line=line, field=field_name
            )

    def _typed_value(
        self,
        field: CatalogueField,
        raw: str,
        table: str,
        line: int,
        invalid: list[tuple[int, str, str]],
        unknown: list[tuple[int, str, str]],
    ) -> P6Value:
        reading = read_value(field, raw)
        status = reading.status
        if status is ReadingStatus.OK:
            return reading.value
        empty_ok = field.empty_allowed or (table, field.field) == ("TASK", "task_code")
        if status is ReadingStatus.EMPTY:
            if field.required and not empty_ok:
                invalid.append((line, table, field.field))
            return None
        if status is ReadingStatus.INVALID:
            if field.required:
                invalid.append((line, table, field.field))
            else:
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table=table, line=line, field=field.field
                )
            return None
        if field.required:
            unknown.append((line, table, field.field))
            return None
        self.issues.warn(P6IssueCode.UNKNOWN_ENUM_VALUE, table=table, line=line, field=field.field)
        return reading.value

    def check_keys(self) -> None:
        """Unique entity keys and Activity IDs (5.5 `p6_duplicate_activity_id`)."""
        for name, key in _ENTITY_KEY.items():
            seen: set[P6Value] = set()
            for row in self.rows.get(name, []):
                value = row.values[key]
                if value in seen:
                    raise _fatal(
                        P6IssueCode.STRUCTURE_INVALID, table=name, line=row.line, field=key
                    )
                seen.add(value)
        codes: set[P6Value] = set()
        for row in self.rows["TASK"]:
            code = row.values["task_code"]
            if code is None or code in codes:
                raise _fatal(
                    P6IssueCode.DUPLICATE_ACTIVITY_ID,
                    table="TASK",
                    line=row.line,
                    field="task_code",
                )
            codes.add(code)

    @property
    def project_id(self) -> P6Value:
        return self.rows["PROJECT"][0].values["proj_id"]

    def check_references(self) -> None:
        project = self.project_id
        wbs_ids = {row.values["wbs_id"] for row in self.rows["PROJWBS"]}
        task_ids = {row.values["task_id"] for row in self.rows["TASK"]}
        dangling: list[tuple[int, str, str]] = []
        for row in self.rows["PROJWBS"]:
            if row.values["proj_id"] != project:
                dangling.append((row.line, "PROJWBS", "proj_id"))
            if (
                row.values["proj_node_flag"] is not True
                and row.values["parent_wbs_id"] not in wbs_ids
            ):
                dangling.append((row.line, "PROJWBS", "parent_wbs_id"))
        for row in self.rows["TASK"]:
            if row.values["proj_id"] != project:
                dangling.append((row.line, "TASK", "proj_id"))
            if row.values["wbs_id"] not in wbs_ids:
                dangling.append((row.line, "TASK", "wbs_id"))
        for row in self.rows["TASKPRED"]:
            if row.values["proj_id"] == project and row.values["task_id"] not in task_ids:
                dangling.append((row.line, "TASKPRED", "task_id"))
            if row.values["pred_proj_id"] == project and row.values["pred_task_id"] not in task_ids:
                dangling.append((row.line, "TASKPRED", "pred_task_id"))
        if dangling:
            line, table, field = min(dangling)
            raise _fatal(P6IssueCode.REFERENCE_DANGLING, table=table, line=line, field=field)

    def wbs_paths(self) -> dict[P6Value, tuple[str, ...]]:
        """Short-name paths below the project node; cycles and the depth bound are fatal."""
        by_id = {row.values["wbs_id"]: row for row in self.rows["PROJWBS"]}
        paths: dict[P6Value, tuple[str, ...]] = {}
        for row in self.rows["PROJWBS"]:
            chain: list[_Row] = []
            on_chain: set[P6Value] = set()
            current: _Row | None = row
            base: tuple[str, ...] = ()
            while current is not None:
                key = current.values["wbs_id"]
                if key in paths:
                    base = paths[key]
                    break
                if key in on_chain:
                    first = min(
                        item.line
                        for item in chain[[c.values["wbs_id"] for c in chain].index(key) :]
                    )
                    raise _fatal(
                        P6IssueCode.WBS_CYCLE, table="PROJWBS", line=first, field="parent_wbs_id"
                    )
                if current.values["proj_node_flag"] is True:
                    paths[key] = ()
                    break
                chain.append(current)
                on_chain.add(key)
                current = by_id.get(current.values["parent_wbs_id"])
            for item in reversed(chain):
                label = item.values["wbs_short_name"]
                base = (*base, str(label))
                if len(base) > self.limits.wbs_depth:
                    raise _fatal(
                        P6IssueCode.BOUND_EXCEEDED,
                        table="PROJWBS",
                        line=item.line,
                        field="parent_wbs_id",
                        bound=Bound.WBS_DEPTH,
                    )
                paths[item.values["wbs_id"]] = base
        return paths

    # -- typed output ----------------------------------------------------------------------

    @staticmethod
    def _columns(table: str, row: _Row) -> list[tuple[str, P6Value | tuple[str, ...]]]:
        return [
            (field.typed_column, row.values.get(field.field))
            for field in table_fields(table)
            if field.is_typed and field.typed_column is not None
        ]

    def calendars(self) -> tuple[P6Calendar, ...]:
        used = {row.values["clndr_id"] for row in self.rows["TASK"]}
        by_id = {row.values["clndr_id"]: row for row in self.rows["CALENDAR"]}
        found: list[P6Calendar] = []
        for row in self.rows["CALENDAR"]:
            key = row.values["clndr_id"]
            assert isinstance(key, int)  # noqa: S101 - R field, checked above
            data = self.calendar_data.get(key)
            status = CalendarStatus.PARSED
            week = None if data is None else data.week
            if data is not None and week is None:
                base = by_id.get(row.values.get("base_clndr_id"))
                base_data = None
                if base is not None and isinstance(base.values["clndr_id"], int):
                    base_data = self.calendar_data.get(base.values["clndr_id"])
                if base_data is not None and base_data.week is not None:
                    week = base_data.week
                    status = CalendarStatus.BASE_SUBSTITUTED
                    self.issues.warn(
                        P6IssueCode.CALENDAR_BASE_SUBSTITUTED,
                        table="CALENDAR",
                        line=row.line,
                        field="clndr_data",
                    )
            if data is None or week is None:
                status = CalendarStatus.INVALID
                self.issues.warn(
                    P6IssueCode.CALENDAR_MISSING if key in used else P6IssueCode.CALENDAR_INVALID,
                    table="CALENDAR",
                    line=row.line,
                    field="clndr_data",
                )
            exceptions = () if data is None or status is CalendarStatus.INVALID else data.exceptions
            week_out = () if week is None or status is CalendarStatus.INVALID else week
            digest = None
            if status is not CalendarStatus.INVALID:
                digest = _calendar_digest(week_out, exceptions)
            found.append(
                P6Calendar(
                    p6_id=key,
                    record_line=row.line,
                    columns=tuple(
                        (column, value)
                        for column, value in self._columns("CALENDAR", row)
                        if not isinstance(value, tuple)
                    ),
                    status=status,
                    used=key in used,
                    week=week_out,
                    exceptions=exceptions,
                    data_sha256=digest,
                )
            )
        known = set(by_id)
        for row in self.rows["TASK"]:
            if row.values["clndr_id"] not in known:
                self.issues.warn(
                    P6IssueCode.CALENDAR_MISSING, table="TASK", line=row.line, field="clndr_id"
                )
        return tuple(found)

    def entities(
        self, paths: Mapping[P6Value, tuple[str, ...]]
    ) -> tuple[P6Entity, tuple[P6Entity, ...], tuple[P6Entity, ...], tuple[P6Entity, ...]]:
        header = self.raw.header
        assert header is not None  # noqa: S101 - a read without a fatal has a header
        project_row = self.rows["PROJECT"][0]
        project_id = self.project_id
        assert isinstance(project_id, int)  # noqa: S101 - R field
        columns = self._columns("PROJECT", project_row)
        options = [
            row
            for row in self.rows.get("SCHEDOPTIONS", [])
            if row.values.get("proj_id") in {None, project_id}
        ]
        option_row = options[0] if options else _Row(0, 0, {})
        columns += self._columns("SCHEDOPTIONS", option_row)
        nodes = [row for row in self.rows["PROJWBS"] if row.values["proj_node_flag"] is True]
        project_name = nodes[0].values["wbs_name"] if len(nodes) == 1 else None
        columns += [
            ("project_name", project_name),
            ("export_version", header.export_version),
            ("export_date", header.export_date),
            ("encoding", header.encoding),
        ]
        project = P6Entity(EntityKind.PROJECT, project_id, project_row.line, tuple(columns))

        wbs: list[P6Entity] = []
        for row in self.rows["PROJWBS"]:
            path = paths[row.values["wbs_id"]]
            wbs_columns = [*self._columns("PROJWBS", row), ("depth", len(path)), ("wbs_path", path)]
            wbs.append(self._entity(EntityKind.WBS, row, "wbs_id", wbs_columns))

        codes = {row.values["task_id"]: row.values["task_code"] for row in self.rows["TASK"]}
        activities: list[P6Entity] = []
        for row in self.rows["TASK"]:
            values = row.values
            start = values["act_start_date"] or values["early_start_date"]
            finish = values["act_end_date"] or values["early_end_date"]
            task_type = values["task_type"]
            activity_columns = [
                *self._columns("TASK", row),
                ("start_at", start),
                ("finish_at", finish),
                ("wbs_path", paths[values["wbs_id"]]),
                ("kind", _KIND.get(str(task_type), "task")),
            ]
            activities.append(self._entity(EntityKind.ACTIVITY, row, "task_id", activity_columns))

        relationships: list[P6Entity] = []
        for row in self.rows["TASKPRED"]:
            values = row.values
            external = (
                values["pred_proj_id"] != values["proj_id"] or values["proj_id"] != project_id
            )
            if external:
                self.issues.warn(
                    P6IssueCode.EXTERNAL_RELATIONSHIP,
                    table="TASKPRED",
                    line=row.line,
                    field="pred_proj_id",
                )
            pred = (
                codes.get(values["pred_task_id"]) if values["pred_proj_id"] == project_id else None
            )
            succ = codes.get(values["task_id"]) if values["proj_id"] == project_id else None
            relationship_columns = [
                *self._columns("TASKPRED", row),
                ("pred_activity_id", pred),
                ("succ_activity_id", succ),
                ("is_external", external),
            ]
            relationships.append(
                self._entity(EntityKind.RELATIONSHIP, row, "task_pred_id", relationship_columns)
            )
        return project, tuple(wbs), tuple(activities), tuple(relationships)

    @staticmethod
    def _entity(
        kind: EntityKind,
        row: _Row,
        key: str,
        columns: list[tuple[str, P6Value | tuple[str, ...]]],
    ) -> P6Entity:
        p6_id = row.values[key]
        assert isinstance(p6_id, int)  # noqa: S101 - R id field
        return P6Entity(kind, p6_id, row.line, tuple(columns))

    # -- capture (7.2, 7.3, 7.7) -----------------------------------------------------------

    def capture(self) -> tuple[P6FieldValue, ...]:
        capture = _Capture(self)
        return capture.run()


def _calendar_digest(
    week: tuple[tuple[tuple[int, int], ...], ...],
    exceptions: tuple[tuple[date, tuple[tuple[int, int], ...]], ...],
) -> str:
    document = {
        "exceptions": [
            {"date": day.isoformat(), "intervals": [list(pair) for pair in intervals]}
            for day, intervals in exceptions
        ],
        "week": [[list(pair) for pair in day] for day in week],
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(_CALENDAR_DATA_DOMAIN + canonical.encode("ascii")).hexdigest()


class _CapReachedError(Exception):
    pass


def _object_id(text: str) -> int | None:
    """`text` as an object id if it is 1 to 18 ASCII digits, else None."""
    return int(text) if _OBJECT_ID.fullmatch(text) else None


class _Capture:
    """Captured optional values in file order: catalogued O fields, selected uncatalogued
    fields, UDF values and activity-code values (sections 6.9, 7.2, 7.3, 7.7)."""

    def __init__(self, mapper: _Mapper) -> None:
        self.mapper = mapper
        self.limits = mapper.limits
        self.issues = mapper.issues
        self.values: list[P6FieldValue] = []
        self.per_entity: dict[tuple[EntityKind, int], int] = {}
        self.ordinals: dict[tuple[EntityKind, int, str], int] = {}
        rows = mapper.rows
        self.tasks = {row.values["task_id"]: row for row in rows["TASK"]}
        self.entity_ids: dict[str, set[P6Value]] = {
            "TASK": set(self.tasks),
            "PROJWBS": {row.values["wbs_id"] for row in rows["PROJWBS"]},
            "PROJECT": {mapper.project_id},
        }
        self.udf_types = self._udf_types()
        self.code_types, self.codes = self._codes()
        self.udf_codes: dict[str, str | None] | None = None
        self.selection = self._selection()

    # -- definitions -----------------------------------------------------------------------

    def _table(self, name: str) -> RawTable | None:
        return self.mapper.tables.get(name)

    @staticmethod
    def _cell(table: RawTable, values: tuple[str, ...], field: str) -> str:
        index = table.index(field)
        return "" if index is None else values[index]

    def _udf_types(self) -> dict[int, tuple[str, str, str]]:
        table = self._table("UDFTYPE")
        found: dict[int, tuple[str, str, str]] = {}
        if table is None:
            return found
        for line, values in table.rows:
            type_id = _object_id(self._cell(table, values, "udf_type_id"))
            owner = self._cell(table, values, "table_name")
            label = read_text(self._cell(table, values, "udf_type_label"), _LABEL_CHARACTERS)
            data_type = self._cell(table, values, "logical_data_type")
            if type_id is None:
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table="UDFTYPE", line=line, field="udf_type_id"
                )
                continue
            if owner not in UDF_OWNERS:
                self.issues.warn(
                    P6IssueCode.UNKNOWN_ENUM_VALUE, table="UDFTYPE", line=line, field="table_name"
                )
                continue
            if label.status is not ReadingStatus.OK or not isinstance(label.value, str):
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table="UDFTYPE", line=line, field="udf_type_label"
                )
                continue
            if data_type not in _UDF_VALUE_FIELD:
                self.issues.warn(
                    P6IssueCode.UNKNOWN_ENUM_VALUE,
                    table="UDFTYPE",
                    line=line,
                    field="logical_data_type",
                )
                continue
            found[type_id] = (owner, label.value, data_type)
        return found

    def _codes(self) -> tuple[dict[int, str], dict[int, tuple[int, str, str | None, int | None]]]:
        types: dict[int, str] = {}
        codes: dict[int, tuple[int, str, str | None, int | None]] = {}
        type_table = self._table("ACTVTYPE")
        if type_table is not None:
            for line, values in type_table.rows:
                type_id = _object_id(self._cell(type_table, values, "actv_code_type_id"))
                label = read_text(
                    self._cell(type_table, values, "actv_code_type"), _LABEL_CHARACTERS
                )
                if type_id is None:
                    self.issues.warn(
                        P6IssueCode.VALUE_INVALID,
                        table="ACTVTYPE",
                        line=line,
                        field="actv_code_type_id",
                    )
                    continue
                if label.status is not ReadingStatus.OK or not isinstance(label.value, str):
                    self.issues.warn(
                        P6IssueCode.VALUE_INVALID,
                        table="ACTVTYPE",
                        line=line,
                        field="actv_code_type",
                    )
                    continue
                types[type_id] = label.value
        code_table = self._table("ACTVCODE")
        if code_table is not None:
            for line, values in code_table.rows:
                code_id = _object_id(self._cell(code_table, values, "actv_code_id"))
                code_type_id = _object_id(self._cell(code_table, values, "actv_code_type_id"))
                short = read_text(
                    self._cell(code_table, values, "short_name"),
                    self.limits.captured_text_characters,
                )
                name = read_text(
                    self._cell(code_table, values, "actv_code_name"),
                    self.limits.captured_text_characters,
                )
                parent_cell = self._cell(code_table, values, "parent_actv_code_id")
                parent = _object_id(parent_cell)
                if (
                    code_id is None
                    or code_type_id is None
                    or short.status is not ReadingStatus.OK
                    or not isinstance(short.value, str)
                    or name.status is ReadingStatus.INVALID
                    or (parent_cell and parent is None)
                ):
                    self.issues.warn(P6IssueCode.VALUE_INVALID, table="ACTVCODE", line=line)
                    continue
                description = name.value if isinstance(name.value, str) else None
                codes[code_id] = (code_type_id, short.value, description, parent)
        return types, codes

    def _selection(self) -> frozenset[str]:
        if self.mapper.selection is not None:
            return self.mapper.selection
        keys = set(default_capture_keys())
        keys |= {f"udf:{owner}:{label}" for owner, label, _ in self.udf_types.values()}
        keys |= {f"code:{label}" for label in self.code_types.values()}
        keys = {key for key in keys if FIELD_KEY_PATTERN.match(key)}
        ordered = sorted(keys)
        if len(ordered) > self.limits.captured_fields:
            self.issues.warn(P6IssueCode.CAPTURE_CAP_REACHED)
            ordered = ordered[: self.limits.captured_fields]
        return frozenset(ordered)

    # -- values ----------------------------------------------------------------------------

    def _add(self, value: P6FieldValue) -> None:
        entity = (value.entity_kind, value.entity_p6_id)
        if (
            self.per_entity.get(entity, 0) + 1 > self.limits.captured_values_per_entity
            or len(self.values) + 1 > self.limits.captured_values
        ):
            self.issues.warn(
                P6IssueCode.CAPTURE_CAP_REACHED, table=value.source_table, line=value.record_line
            )
            raise _CapReachedError
        self.per_entity[entity] = self.per_entity.get(entity, 0) + 1
        self.values.append(value)

    def _ordinal(self, kind: EntityKind, entity_id: int, key: str) -> int:
        slot = (kind, entity_id, key)
        ordinal = self.ordinals.get(slot, 0)
        self.ordinals[slot] = ordinal + 1
        return ordinal

    def _entity(self, table: RawTable, row_index: int) -> tuple[EntityKind, int, str | None, int]:
        """(kind, p6 id, activity id, ordinal base) of a row of `table`."""
        project = self.mapper.project_id
        assert isinstance(project, int)  # noqa: S101 - R field
        key_field = _ENTITY_KEY.get(table.name)
        if key_field is not None and table.name != "PROJECT":
            row = self.mapper.rows[table.name][row_index]
            p6_id = row.values[key_field]
            assert isinstance(p6_id, int)  # noqa: S101 - R field
            activity = row.values["task_code"] if table.name == "TASK" else None
            kind = {
                "TASK": EntityKind.ACTIVITY,
                "TASKPRED": EntityKind.RELATIONSHIP,
                "PROJWBS": EntityKind.WBS,
                "CALENDAR": EntityKind.CALENDAR,
            }[table.name]
            return kind, p6_id, activity if isinstance(activity, str) else None, 0
        # PROJECT has one row; any other table's rows are ordinals of the project entity.
        return EntityKind.PROJECT, project, None, 0 if table.name == "PROJECT" else row_index

    def _typed(self, field: CatalogueField | None, raw: str) -> tuple[ReadingStatus, str, P6Value]:
        if field is None or field.value_type in {ValueType.TEXT, ValueType.NAME}:
            reading = read_text(raw, self.limits.captured_text_characters)
            return reading.status, "text", reading.value
        reading = read_value(field, raw)
        value_type = {
            ValueType.ID: "number",
            ValueType.INT: "number",
            ValueType.HOURS: "number",
            ValueType.NUM: "number",
            ValueType.TS: "ts",
            ValueType.FLAG: "flag",
        }.get(field.value_type, "text")
        return reading.status, value_type, reading.value

    def _plain(self, table: RawTable) -> None:
        catalogued = not (not is_catalogued_table(table.name) or table.name in WILDCARD_TABLES)
        targets: list[tuple[int, str, CatalogueField | None]] = []
        for index, name in enumerate(table.fields):
            field = catalogue_field(table.name, name) if catalogued else None
            key = f"xer:{table.name}.{name}"
            if key not in self.selection:
                continue
            if field is not None and not field.is_generic_store:
                continue
            targets.append((index, key, field))
        for row_index, (line, values) in enumerate(table.rows):
            for index, key, field in targets:
                raw = values[index]
                status, value_type, value = self._typed(field, raw)
                if status is ReadingStatus.EMPTY:
                    continue
                if status is ReadingStatus.INVALID:
                    self.issues.warn(
                        P6IssueCode.VALUE_INVALID,
                        table=table.name,
                        line=line,
                        field=table.fields[index],
                    )
                    continue
                if status is ReadingStatus.UNKNOWN_ENUM:
                    self.issues.warn(
                        P6IssueCode.UNKNOWN_ENUM_VALUE,
                        table=table.name,
                        line=line,
                        field=table.fields[index],
                    )
                kind, entity_id, activity, ordinal = self._entity(table, row_index)
                self._add(
                    P6FieldValue(
                        entity_kind=kind,
                        entity_p6_id=entity_id,
                        activity_id=activity,
                        field_key=key,
                        ordinal=ordinal,
                        value_type=value_type,
                        value=value,
                        code_path=(),
                        description=None,
                        source_table=table.name,
                        record_line=line,
                    )
                )

    def _udf_values(self, table: RawTable) -> None:
        for line, values in table.rows:
            type_id = _object_id(self._cell(table, values, "udf_type_id"))
            definition = None if type_id is None else self.udf_types.get(type_id)
            if definition is None:
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table="UDFVALUE", line=line, field="udf_type_id"
                )
                continue
            owner, label, data_type = definition
            key = f"udf:{owner}:{label}"
            if key not in self.selection:
                continue
            entity_id = _object_id(self._cell(table, values, "fk_id"))
            kind = UDF_OWNERS[owner]
            if entity_id is None or (
                owner in self.entity_ids and entity_id not in self.entity_ids[owner]
            ):
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table="UDFVALUE", line=line, field="fk_id"
                )
                continue
            source_field, value_type = _UDF_VALUE_FIELD[data_type]
            raw = self._cell(table, values, source_field)
            value: P6Value
            if data_type == "FT_STATICTYPE":
                label_value = self._udf_code_label(raw)
                status = ReadingStatus.OK if label_value is not None else ReadingStatus.INVALID
                value = label_value
            else:
                field = catalogue_field("UDFVALUE", source_field)
                status, _, value = self._typed(
                    _as_type(field, value_type) if field is not None else None, raw
                )
            if status is ReadingStatus.EMPTY:
                continue
            if status is not ReadingStatus.OK:
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID, table="UDFVALUE", line=line, field=source_field
                )
                continue
            activity_row = self.tasks.get(entity_id) if owner == "TASK" else None
            activity = activity_row.values["task_code"] if activity_row is not None else None
            self._add(
                P6FieldValue(
                    entity_kind=kind,
                    entity_p6_id=entity_id,
                    activity_id=activity if isinstance(activity, str) else None,
                    field_key=key,
                    ordinal=self._ordinal(kind, entity_id, key),
                    value_type=value_type,
                    value=value,
                    code_path=(),
                    description=None,
                    source_table="UDFVALUE",
                    record_line=line,
                )
            )

    def _udf_code_label(self, raw: str) -> str | None:
        if self.udf_codes is None:
            self.udf_codes = self._index_udf_codes()
        return self.udf_codes.get(raw) if _OBJECT_ID.fullmatch(raw) else None

    def _index_udf_codes(self) -> dict[str, str | None]:
        """`udf_code_id` -> label, built once: a per-value scan is quadratic on hostile input.

        The first row of a repeated id wins, as the scan it replaces did.
        """
        table = self._table("UDFCODE")
        labels: dict[str, str | None] = {}
        if table is None:
            return labels
        id_index, name_index = table.index("udf_code_id"), table.index("short_name")
        if id_index is None:
            return labels
        for _, values in table.rows:
            if values[id_index] in labels:
                continue
            label = read_text(
                "" if name_index is None else values[name_index],
                self.limits.captured_text_characters,
            )
            labels[values[id_index]] = label.value if isinstance(label.value, str) else None
        return labels

    def _code_values(self, table: RawTable) -> None:
        for line, values in table.rows:
            task = _object_id(self._cell(table, values, "task_id"))
            type_id = _object_id(self._cell(table, values, "actv_code_type_id"))
            code_id = _object_id(self._cell(table, values, "actv_code_id"))
            if task is None or type_id is None or code_id is None:
                self.issues.warn(P6IssueCode.VALUE_INVALID, table="TASKACTV", line=line)
                continue
            label = self.code_types.get(type_id)
            code = self.codes.get(code_id)
            row = self.tasks.get(task)
            if label is None or code is None or row is None or code[0] != type_id:
                self.issues.warn(P6IssueCode.VALUE_INVALID, table="TASKACTV", line=line)
                continue
            key = f"code:{label}"
            if key not in self.selection:
                continue
            path = self._code_path(code_id)
            if path is None:
                self.issues.warn(
                    P6IssueCode.VALUE_INVALID,
                    table="ACTVCODE",
                    line=line,
                    field="parent_actv_code_id",
                )
                continue
            activity = row.values["task_code"]
            self._add(
                P6FieldValue(
                    entity_kind=EntityKind.ACTIVITY,
                    entity_p6_id=task,
                    activity_id=activity if isinstance(activity, str) else None,
                    field_key=key,
                    ordinal=self._ordinal(EntityKind.ACTIVITY, task, key),
                    value_type="text",
                    value=code[1],
                    code_path=path,
                    description=code[2],
                    source_table="TASKACTV",
                    record_line=line,
                )
            )

    def _code_path(self, code_id: int) -> tuple[str, ...] | None:
        """Labels from the root code value down to `code_id` (at most 8), or None."""
        labels: list[str] = []
        seen: set[int] = set()
        current: int | None = code_id
        while current is not None:
            if current in seen or len(labels) >= _CODE_PATH_LABELS:
                return None
            seen.add(current)
            code = self.codes.get(current)
            if code is None:
                return None
            labels.append(code[1])
            current = code[3]
        return tuple(reversed(labels))

    def run(self) -> tuple[P6FieldValue, ...]:
        self.mapper.captured_keys = self.selection
        try:
            for table in self.mapper.raw.tables:
                if table.name == "UDFVALUE":
                    self._udf_values(table)
                elif table.name == "TASKACTV":
                    self._code_values(table)
                else:
                    self._plain(table)
        except _CapReachedError:
            pass
        return tuple(self.values)


#: FT_* -> (UDFVALUE field holding the value, field-store value type).
_UDF_VALUE_FIELD: Final[Mapping[str, tuple[str, str]]] = {
    "FT_TEXT": ("udf_text", "text"),
    "FT_INT": ("udf_number", "number"),
    "FT_FLOAT_2_DECIMALS": ("udf_number", "number"),
    "FT_MONEY": ("udf_number", "number"),
    "FT_START_DATE": ("udf_date", "ts"),
    "FT_END_DATE": ("udf_date", "ts"),
    "FT_STATICTYPE": ("udf_code_id", "text"),
}


def _as_type(field: CatalogueField, value_type: str) -> CatalogueField | None:
    """A UDF value is typed by its UDF type, not by the UDFVALUE column's name rule."""
    target = {"number": ValueType.NUM, "ts": ValueType.TS}.get(value_type)
    if target is None:
        return None
    return replace(field, value_type=target, max_characters=None, enum_values=None)


def _observe(
    raw: RawRead, captured: frozenset[str]
) -> tuple[tuple[P6ObservedTable, ...], tuple[P6ObservedField, ...]]:
    tables: list[P6ObservedTable] = []
    fields: list[P6ObservedField] = []
    for table in raw.tables:
        catalogued_table = is_catalogued_table(table.name)
        tables.append(
            P6ObservedTable(
                name=safe_name(table.name),
                position=table.position,
                line=table.line,
                catalogued=catalogued_table,
                records=len(table.rows),
            )
        )
        for position, name in enumerate(table.fields):
            fields.append(_observe_field(table, position, name, captured))
    return tuple(tables), tuple(fields)


def _observe_field(
    table: RawTable,
    position: int,
    name: str,
    captured_keys: frozenset[str],
) -> P6ObservedField:
    field = catalogue_field(table.name, name) if is_catalogued_table(table.name) else None
    wildcard = table.name in WILDCARD_TABLES
    nonempty = 0
    min_length: int | None = None
    max_length: int | None = None
    shapes: dict[str, int] = {}
    unknown_enum = 0
    tokens: set[str] = set()
    over_length = 0
    bound = field.max_characters if field is not None else None
    closed = field.enum_values if field is not None else None
    for _, values in table.rows:
        value = values[position]
        if value == "":
            continue
        nonempty += 1
        length = len(value)
        min_length = length if min_length is None else min(min_length, length)
        max_length = length if max_length is None else max(max_length, length)
        shape = value_shape(value)
        shapes[shape] = shapes.get(shape, 0) + 1
        if bound is not None and length > bound:
            over_length += 1
        if closed is not None and value not in closed:
            unknown_enum += 1
            if _UNKNOWN_TOKEN.match(value) and len(tokens) < _MAX_UNKNOWN_TOKENS:
                tokens.add(value)
    key = f"xer:{table.name}.{name}"
    if field is not None:
        if field.is_typed or field.tier is Tier.DERIVED:
            captured = True
        elif field.tier is Tier.NEVER:
            captured = False
        elif field.is_component:
            captured = any(item.startswith(("udf:", "code:")) for item in captured_keys)
        else:
            captured = key in captured_keys
    else:
        captured = wildcard or key in captured_keys
    return P6ObservedField(
        table=safe_name(table.name),
        table_position=table.position,
        field=safe_name(name),
        position=position,
        field_key=key if field is not None or (safe_name(table.name) and safe_name(name)) else None,
        catalogued=field is not None or wildcard,
        tier=field.tier.value if field is not None else None,
        records=len(table.rows),
        nonempty=nonempty,
        min_length=min_length,
        max_length=max_length,
        shapes=tuple(sorted(shapes.items())),
        unknown_enum=unknown_enum,
        unknown_enum_tokens=tuple(sorted(tokens)),
        over_length=over_length,
        captured=captured,
    )


def _iter_issue_counts(issues: _Issues) -> Iterator[tuple[str, int]]:
    yield from sorted(issues.counts.items())


def parse_xer(
    data: bytes,
    *,
    capture: Collection[str] | None = None,
    limits: P6Limits = P6_LIMITS,
) -> P6ParseResult:
    """Parse XER `data` under profile `p6_xer_v1` (sections 3-7).

    `capture` is the Series' selection of optional field keys (section 7.2);
    None means the catalogue defaults (O+) plus every UDF and activity-code key
    the file defines. Raises `ValueError` only for a malformed selection.
    """
    selection = _validate_selection(capture, limits)
    issues = _Issues()
    raw = read_xer(data, limits)
    if raw.header is not None and not raw.header.export_version.startswith(TESTED_VERSION_PREFIX):
        issues.warn(P6IssueCode.EXPORT_VERSION_UNTESTED, line=1)
    mapper = _Mapper(raw, limits, issues, selection)
    project: P6Entity | None = None
    wbs: tuple[P6Entity, ...] = ()
    activities: tuple[P6Entity, ...] = ()
    relationships: tuple[P6Entity, ...] = ()
    calendars: tuple[P6Calendar, ...] = ()
    field_values: tuple[P6FieldValue, ...] = ()
    outcome = P6Outcome.COMPLETE
    if raw.fatal is not None:
        issues.add(raw.fatal)
        outcome = P6Outcome.FAILED
    else:
        mapper.observe_unknowns()
        try:
            mapper.parse_calendar_blobs()
            mapper.require()
            mapper.read_typed()
            mapper.check_keys()
            mapper.check_references()
            paths = mapper.wbs_paths()
        except _StopError as stop:
            issues.add(stop.issue)
            outcome = P6Outcome.FAILED
        else:
            calendars = mapper.calendars()
            project, wbs, activities, relationships = mapper.entities(paths)
            field_values = mapper.capture()
    tables, observed = _observe(raw, mapper.captured_keys)
    return P6ParseResult(
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        catalogue_version=CATALOGUE_VERSION,
        outcome=outcome,
        header=raw.header,
        issues=tuple(issues.listed),
        issue_counts=tuple(_iter_issue_counts(issues)),
        tables=tables,
        observed_fields=observed,
        project=project,
        wbs=wbs,
        activities=activities,
        relationships=relationships,
        calendars=calendars,
        field_values=field_values,
        captured_keys=tuple(sorted(mapper.captured_keys)),
    )
