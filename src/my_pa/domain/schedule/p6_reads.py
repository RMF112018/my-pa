"""P6 XER S7-4a: the read and capture-selection grammar (pure).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 7.1-7.7
(registry, capture selection, field store, reads over captured fields, limits)
and 10.3-10.5 (strict inputs, disclosure, read shapes) under ADR-023.

Everything here is a value or a pure function over the request: the field-key
grammar (section 7.7, restated from the parser so the parent never imports the
parser front end), which catalogued keys are selectable and which are
`personal`, the value type a key filters by, and the closed filter and sort
grammar -- at most 3 field predicates over `eq`, `in` (at most 50 values),
`lt`, `le`, `gt`, `ge` and `prefix` (text, at most 100 characters), 1 sort key,
and nothing else: no `OR`, no regular expression, no expression language, no
SQL fragment. A refusal is a `P6ReadRequestError` naming the request field,
never its value.

Standard library and `my_pa.domain.schedule` only
(`tests/architecture/test_cpm_full_parser_scope.py`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.p6.catalogue import (
    CATALOGUE,
    CatalogueField,
    EntityKind,
    Tier,
    ValueType,
)

__all__ = [
    "DEFAULT_P6_PAGE_SIZE",
    "MAX_P6_CAPTURED_FIELDS",
    "MAX_P6_CAPTURE_EVENTS",
    "MAX_P6_FIELD_PREDICATES",
    "MAX_P6_IMPORTS_PER_DAY",
    "MAX_P6_IMPORTS_PER_HOUR",
    "MAX_P6_INCLUDED_FIELDS",
    "MAX_P6_IN_VALUES",
    "MAX_P6_PAGE_SIZE",
    "MAX_P6_PREFIX_CHARACTERS",
    "MAX_P6_TEXT_CHARACTERS",
    "P6_FIELD_KEY_PATTERN",
    "P6_SNAPSHOT_QUOTA_BYTES",
    "P6CaptureEvent",
    "P6FieldObservation",
    "P6FieldPredicate",
    "P6FilterOperator",
    "P6PublicationRef",
    "P6ReadRequestError",
    "P6SeriesState",
    "P6Sort",
    "P6SortDirection",
    "P6ValueType",
    "catalogue_field_of",
    "entity_kind_of",
    "is_personal_key",
    "is_selectable_catalogued_key",
    "keys_named",
    "p6_field_keys",
    "p6_included_fields",
    "p6_predicates",
    "p6_sort",
    "value_type_of",
]

#: Section 7.7: the field-key grammar (identical to the parser's
#: `FIELD_KEY_PATTERN`, held equal by `tests/unit/test_schedule_p6_reads_domain.py`).
P6_FIELD_KEY_PATTERN: Final = re.compile(
    r"^(xer:[A-Z][A-Z0-9_]{0,31}\.[A-Za-z][A-Za-z0-9_]{0,63}|udf:[A-Z]{1,16}:.{1,120}|code:.{1,120})$"
)
#: Section 10.3: a read page is 1 to 100 entries.
MAX_P6_PAGE_SIZE: Final = 100
DEFAULT_P6_PAGE_SIZE: Final = 50
#: Section 10.3: at most 50 captured keys to include in an answer.
MAX_P6_INCLUDED_FIELDS: Final = 50
#: Section 7.7: the filter grammar's bounds.
MAX_P6_FIELD_PREDICATES: Final = 3
MAX_P6_IN_VALUES: Final = 50
MAX_P6_PREFIX_CHARACTERS: Final = 100
MAX_P6_TEXT_CHARACTERS: Final = 4_000
#: Section 7.7: captured optional fields per Series; selection events per Series.
MAX_P6_CAPTURED_FIELDS: Final = 300
MAX_P6_CAPTURE_EVENTS: Final = 1_000
#: Section 7.7 (placeholders kept by operator decision 2026-11-23): snapshot
#: bytes per Principal (8 GiB, operator-adjustable by setting) and imports per
#: Principal per hour and per day.
P6_SNAPSHOT_QUOTA_BYTES: Final = 8 * 1024 * 1024 * 1024
MAX_P6_IMPORTS_PER_HOUR: Final = 60
MAX_P6_IMPORTS_PER_DAY: Final = 500
#: A filter's timestamp: P6 times are minute-exact local times (no offset).
_TIMESTAMP: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?\Z")


class P6ReadRequestError(ValueError):
    """A strict-input refusal naming the request field (never its value)."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class P6ValueType(StrEnum):
    """Section 7.3: the one typed value column a captured value fills."""

    TEXT = "text"
    NUMBER = "number"
    TS = "ts"
    FLAG = "flag"


class P6FilterOperator(StrEnum):
    """Section 7.7: the closed filter operators."""

    EQ = "eq"
    IN = "in"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    PREFIX = "prefix"


class P6SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


#: The catalogue by field key (every catalogued field carries a unique key).
_BY_KEY: Final[Mapping[str, CatalogueField]] = {field.field_key: field for field in CATALOGUE}
#: The catalogued value types the generic store keeps as numbers, times and flags.
_NUMBER_TYPES: Final = frozenset({ValueType.ID, ValueType.INT, ValueType.HOURS, ValueType.NUM})


def catalogue_field_of(field_key: str) -> CatalogueField | None:
    """The catalogued field `xer:<TABLE>.<field>` names, or `None` (UDF, code, unknown)."""
    return _BY_KEY.get(field_key)


def value_type_of(field_key: str) -> P6ValueType | None:
    """Section 7.7: the value type the catalogue gives a catalogued `xer:` key.

    `None` for a key the catalogue does not type: a `udf:` key (its type is
    its own file's definition), a `code:` key (text) or an uncatalogued field
    (always text, section 7.7). A predicate over such a key is typed by its
    operand instead (`p6_predicates`).
    """
    field = _BY_KEY.get(field_key)
    if field is None:
        return None
    if field.value_type in _NUMBER_TYPES:
        return P6ValueType.NUMBER
    if field.value_type is ValueType.TS:
        return P6ValueType.TS
    if field.value_type is ValueType.FLAG:
        return P6ValueType.FLAG
    return P6ValueType.TEXT


def is_personal_key(field_key: str) -> bool:
    """Section 7.2: a catalogued field marked `personal` (6.7, 6.10)."""
    field = _BY_KEY.get(field_key)
    return field is not None and field.personal


def is_selectable_catalogued_key(field_key: str) -> bool:
    """Section 7.2: every catalogued O field captured as its own generic-store value.

    N fields and R/T/V fields (always typed columns) are not selectable; nor is
    a UDF or code component (its key is `udf:` / `code:`, not `xer:`).
    """
    field = _BY_KEY.get(field_key)
    return (
        field is not None
        and field.tier in (Tier.OPTIONAL_DEFAULT, Tier.OPTIONAL)
        and field.is_generic_store
    )


def _key(value: object, field: str) -> str:
    if not isinstance(value, str) or P6_FIELD_KEY_PATTERN.fullmatch(value) is None:
        raise P6ReadRequestError(field)
    return value


def p6_field_keys(values: object, *, field: str = "field_keys") -> tuple[str, ...]:
    """`set_captured.field_keys`: at most 300 distinct keys of the 7.7 grammar, sorted.

    Sorted by code point (the stored chain's order); a repeated key is refused,
    never silently merged.
    """
    if not isinstance(values, (list, tuple)) or len(values) > MAX_P6_CAPTURED_FIELDS:
        raise P6ReadRequestError(field)
    keys = [_key(value, field) for value in values]
    if len(set(keys)) != len(keys):
        raise P6ReadRequestError(field)
    return tuple(sorted(keys))


def p6_included_fields(values: object) -> tuple[str, ...] | None:
    """A read's `fields?`: at most 50 distinct captured keys of the 7.7 grammar."""
    if values is None:
        return None
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_P6_INCLUDED_FIELDS:
        raise P6ReadRequestError("fields")
    keys = [_key(value, "fields") for value in values]
    if len(set(keys)) != len(keys):
        raise P6ReadRequestError("fields")
    return tuple(keys)


@dataclass(frozen=True, slots=True)
class P6FieldPredicate:
    """One field predicate: a captured key, a closed operator and typed operand(s)."""

    field_key: str
    operator: P6FilterOperator
    value_type: P6ValueType
    values: tuple[str | Decimal | datetime | bool, ...]


@dataclass(frozen=True, slots=True)
class P6Sort:
    """One sort key: values order by number, then time, then flag, then text, nulls last."""

    field_key: str
    direction: P6SortDirection


def _operand(raw: object, value_type: P6ValueType, operator: P6FilterOperator) -> object:
    """One operand, typed by the key's value type; anything else is refused."""
    if value_type is P6ValueType.FLAG:
        if operator not in (P6FilterOperator.EQ, P6FilterOperator.IN) or type(raw) is not bool:
            raise P6ReadRequestError("filter")
        return raw
    if value_type is P6ValueType.NUMBER:
        if operator is P6FilterOperator.PREFIX or type(raw) not in (int, float):
            raise P6ReadRequestError("filter")
        if isinstance(raw, float) and not math.isfinite(raw):
            raise P6ReadRequestError("filter")
        try:
            number = Decimal(str(raw))
        except InvalidOperation:  # pragma: no cover - a finite JSON number always converts
            raise P6ReadRequestError("filter") from None
        if abs(number) >= Decimal("1e22"):
            raise P6ReadRequestError("filter")
        return number
    if value_type is P6ValueType.TS:
        if (
            operator is P6FilterOperator.PREFIX
            or not isinstance(raw, str)
            or _TIMESTAMP.fullmatch(raw) is None
        ):
            raise P6ReadRequestError("filter")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise P6ReadRequestError("filter") from None
    if not isinstance(raw, str):
        raise P6ReadRequestError("filter")
    limit = (
        MAX_P6_PREFIX_CHARACTERS if operator is P6FilterOperator.PREFIX else MAX_P6_TEXT_CHARACTERS
    )
    if not 1 <= len(raw) <= limit:
        raise P6ReadRequestError("filter")
    return raw


def _operand_type(raw: object) -> P6ValueType:
    """An untyped key's operand type: a JSON boolean, number or string (never a time)."""
    if type(raw) is bool:
        return P6ValueType.FLAG
    if type(raw) in (int, float):
        return P6ValueType.NUMBER
    if isinstance(raw, str):
        return P6ValueType.TEXT
    raise P6ReadRequestError("filter")


def _operator(value: object) -> P6FilterOperator:
    if isinstance(value, str):
        for member in P6FilterOperator:
            if member.value == value:
                return member
    raise P6ReadRequestError("filter")


_PREDICATE_KEYS: Final = frozenset({"field", "op", "value"})


def p6_predicates(raw: object) -> tuple[P6FieldPredicate, ...]:
    """A read's `filter?`: 1 to 3 predicates `{field, op, value}`, combined by AND.

    `in` takes 1 to 50 operands in a list; every other operator exactly one
    operand. The operand type is the key's (section 7.7); `prefix` is text only.
    """
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= MAX_P6_FIELD_PREDICATES:
        raise P6ReadRequestError("filter")
    found: list[P6FieldPredicate] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != _PREDICATE_KEYS:
            raise P6ReadRequestError("filter")
        key = _key(item["field"], "filter")
        operator = _operator(item["op"])
        operand = item["value"]
        listed: tuple[object, ...]
        if operator is P6FilterOperator.IN:
            if not isinstance(operand, (list, tuple)) or not 1 <= len(operand) <= MAX_P6_IN_VALUES:
                raise P6ReadRequestError("filter")
            listed = tuple(operand)
        else:
            listed = (operand,)
        value_type = value_type_of(key)
        if value_type is None:
            types = {_operand_type(value) for value in listed}
            if len(types) != 1:
                raise P6ReadRequestError("filter")
            value_type = types.pop()
        operands = tuple(_operand(value, value_type, operator) for value in listed)
        found.append(
            P6FieldPredicate(
                field_key=key,
                operator=operator,
                value_type=value_type,
                values=operands,  # type: ignore[arg-type]
            )
        )
    return tuple(found)


_SORT_KEYS: Final = frozenset({"field", "direction"})


def p6_sort(raw: object) -> P6Sort | None:
    """A read's `sort?`: exactly 1 captured key and a direction (`asc`, `desc`)."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) - _SORT_KEYS or "field" not in raw:
        raise P6ReadRequestError("sort")
    key = _key(raw["field"], "sort")
    direction = raw.get("direction", P6SortDirection.ASC.value)
    if direction not in (P6SortDirection.ASC.value, P6SortDirection.DESC.value):
        raise P6ReadRequestError("sort")
    return P6Sort(field_key=key, direction=P6SortDirection(direction))


def entity_kind_of(value: object) -> EntityKind | None:
    """`field_values.list`'s optional `entity_kind` (section 7.3), or a refusal."""
    if value is None:
        return None
    if isinstance(value, str):
        for member in EntityKind:
            if member.value == value:
                return member
    raise P6ReadRequestError("entity_kind")


def keys_named(*groups: Sequence[str] | None) -> frozenset[str]:
    """Every key a read names in `fields`, `filter` and `sort` (for the personal gate)."""
    return frozenset(key for group in groups if group for key in group)


# ---- read records (what the P6 read repository answers) --------------------------------


@dataclass(frozen=True, slots=True)
class P6CaptureEvent:
    """One `schedule_p6_capture_events` row (section 7.2), without its provenance pair."""

    event_id: str
    sequence: int
    field_keys: tuple[str, ...]
    include_personal: bool
    catalogue_version: str
    decision_channel: str
    asserting_client_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class P6SeriesState:
    """A Series as the P6 reads and the selection see it (section 7.2)."""

    series_id: str
    project_id: str
    holds_pdf: bool
    last_event: P6CaptureEvent | None


@dataclass(frozen=True, slots=True)
class P6PublicationRef:
    """A P6 publication's identity, effective status, accepted run and selection in force."""

    publication_id: str
    series_id: str
    project_id: str
    source_format: str
    status: str
    accepted_parser_run_id: str | None
    capture_event_id: str | None
    include_personal: bool
    admitted_at: datetime


@dataclass(frozen=True, slots=True)
class P6FieldObservation:
    """One field key's observation across a Series' complete P6 publications (7.4).

    Statistics only, never a value: in how many imports the key was present or
    captured, the newest such publication, and the records / non-empty counts
    the nonempty ratio is computed from (zero records for a key known only from
    its captured values).
    """

    field_key: str
    source_table: str | None
    catalogued: bool
    tier: str | None
    imports_seen: int
    last_seen_publication_id: str
    records: int
    nonempty: int
    entity_kind: str | None
    value_type: str | None
