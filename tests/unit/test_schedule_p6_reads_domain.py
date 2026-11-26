"""P6 XER S7-4a: the pure read and capture-selection grammar (acceptance D4, D2 caps).

Schedule XER import contract (`docs/architecture/schedule-xer-import-contract.md`)
sections 7.2, 7.7 and 10.3 over `my_pa.domain.schedule.p6_reads`: the field-key
grammar is the parser's, the filter grammar admits exactly the closed operators
with their bounds, the sort takes one key, and the selection takes at most 300
distinct keys. Every value is synthetic.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from my_pa.domain.schedule.p6 import parser
from my_pa.domain.schedule.p6.catalogue import CATALOGUE, EntityKind, Tier
from my_pa.domain.schedule.p6_reads import (
    MAX_P6_CAPTURED_FIELDS,
    MAX_P6_FIELD_PREDICATES,
    MAX_P6_IN_VALUES,
    MAX_P6_INCLUDED_FIELDS,
    MAX_P6_PREFIX_CHARACTERS,
    P6_FIELD_KEY_PATTERN,
    P6FilterOperator,
    P6ReadRequestError,
    P6SortDirection,
    P6ValueType,
    entity_kind_of,
    is_personal_key,
    is_selectable_catalogued_key,
    p6_field_keys,
    p6_included_fields,
    p6_predicates,
    p6_sort,
    value_type_of,
)

TEXT_KEY = "xer:TASK.syn_extra_field"
NUMBER_KEY = "xer:TASK.est_wt"
FLAG_KEY = "xer:TASK.rev_fdbk_flag"


def _refused(field: str, call: object, *args: object) -> None:
    with pytest.raises(P6ReadRequestError) as raised:
        call(*args)  # type: ignore[operator]
    assert raised.value.field == field


def test_the_field_key_grammar_is_the_parsers() -> None:
    assert P6_FIELD_KEY_PATTERN.pattern == parser.FIELD_KEY_PATTERN.pattern


def test_the_catalogue_types_a_key_and_an_untyped_key_is_none() -> None:
    assert value_type_of(NUMBER_KEY) is P6ValueType.NUMBER
    assert value_type_of(FLAG_KEY) is P6ValueType.FLAG
    assert value_type_of("udf:TASK:Synthetic Note") is None
    assert value_type_of(TEXT_KEY) is None


def test_selectable_keys_are_exactly_the_catalogued_optional_generic_store_fields() -> None:
    selectable = {
        field.field_key for field in CATALOGUE if is_selectable_catalogued_key(field.field_key)
    }
    assert selectable
    for field in CATALOGUE:
        if field.field_key in selectable:
            assert field.tier in (Tier.OPTIONAL_DEFAULT, Tier.OPTIONAL)
            assert field.is_generic_store
        else:
            assert field.tier not in (Tier.OPTIONAL_DEFAULT, Tier.OPTIONAL) or not (
                field.is_generic_store
            )
    assert not is_selectable_catalogued_key("xer:TASK.task_code")  # an R field


def test_personal_keys_follow_the_catalogue() -> None:
    assert is_personal_key("xer:TASK.create_user")
    assert not is_personal_key(NUMBER_KEY)
    assert not is_personal_key("udf:TASK:Synthetic Note")


@pytest.mark.parametrize("operator", list(P6FilterOperator))
def test_each_operator_parses(operator: P6FilterOperator) -> None:
    value: object = ["a", "b"] if operator is P6FilterOperator.IN else "Synthetic"
    (predicate,) = p6_predicates([{"field": TEXT_KEY, "op": operator.value, "value": value}])
    assert predicate.operator is operator
    assert predicate.value_type is P6ValueType.TEXT


def test_operands_are_typed_by_the_catalogue() -> None:
    (number,) = p6_predicates([{"field": NUMBER_KEY, "op": "ge", "value": 2.5}])
    assert number.values == (Decimal("2.5"),)
    (flag,) = p6_predicates([{"field": FLAG_KEY, "op": "eq", "value": True}])
    assert flag.values == (True,)
    (stamp,) = p6_predicates(
        [{"field": "xer:PROJECT.add_date", "op": "lt", "value": "2030-01-09T08:00"}]
    )
    assert stamp.values == (datetime(2030, 1, 9, 8, 0),)
    _refused("filter", p6_predicates, [{"field": NUMBER_KEY, "op": "eq", "value": "12"}])
    _refused("filter", p6_predicates, [{"field": NUMBER_KEY, "op": "prefix", "value": 1}])
    _refused("filter", p6_predicates, [{"field": FLAG_KEY, "op": "lt", "value": True}])


def test_an_untyped_key_is_typed_by_one_operand_kind() -> None:
    (count,) = p6_predicates([{"field": "udf:TASK:Synthetic Count", "op": "gt", "value": 3}])
    assert count.value_type is P6ValueType.NUMBER
    _refused(
        "filter",
        p6_predicates,
        [{"field": "udf:TASK:Synthetic Count", "op": "in", "value": [3, "x"]}],
    )


def test_the_filter_bounds() -> None:
    one = {"field": TEXT_KEY, "op": "eq", "value": "x"}
    assert len(p6_predicates([one] * MAX_P6_FIELD_PREDICATES)) == MAX_P6_FIELD_PREDICATES
    _refused("filter", p6_predicates, [one] * (MAX_P6_FIELD_PREDICATES + 1))
    many = [f"v{index}" for index in range(MAX_P6_IN_VALUES)]
    p6_predicates([{"field": TEXT_KEY, "op": "in", "value": many}])
    _refused("filter", p6_predicates, [{"field": TEXT_KEY, "op": "in", "value": [*many, "x"]}])
    prefix = "p" * MAX_P6_PREFIX_CHARACTERS
    p6_predicates([{"field": TEXT_KEY, "op": "prefix", "value": prefix}])
    _refused("filter", p6_predicates, [{"field": TEXT_KEY, "op": "prefix", "value": prefix + "p"}])


@pytest.mark.parametrize(
    "raw",
    [
        [{"field": TEXT_KEY, "op": "regex", "value": ".*"}],
        [{"field": TEXT_KEY, "op": "or", "value": ["a", "b"]}],
        [{"field": TEXT_KEY, "op": "eq", "value": "x", "or": True}],
        [{"field": "SELECT 1", "op": "eq", "value": "x"}],
        [{"field": TEXT_KEY, "op": "eq"}],
        {"field": TEXT_KEY, "op": "eq", "value": "x"},
        [],
        "task_code = 'x'",
    ],
)
def test_anything_outside_the_grammar_is_refused(raw: object) -> None:
    _refused("filter", p6_predicates, raw)


def test_the_sort_takes_one_key_and_a_direction() -> None:
    sort = p6_sort({"field": NUMBER_KEY, "direction": "desc"})
    assert sort is not None
    assert sort.direction is P6SortDirection.DESC
    ascending = p6_sort({"field": NUMBER_KEY})
    assert ascending is not None
    assert ascending.direction is P6SortDirection.ASC
    _refused("sort", p6_sort, {"field": NUMBER_KEY, "direction": "sideways"})
    _refused("sort", p6_sort, {"field": NUMBER_KEY, "then": TEXT_KEY})
    _refused("sort", p6_sort, [{"field": NUMBER_KEY}])


def test_the_selection_bounds_and_order() -> None:
    keys = [f"code:Synthetic {index:03d}" for index in range(MAX_P6_CAPTURED_FIELDS)]
    assert p6_field_keys(list(reversed(keys))) == tuple(sorted(keys))
    assert p6_field_keys([]) == ()
    _refused("field_keys", p6_field_keys, [*keys, "code:one more"])
    _refused("field_keys", p6_field_keys, [TEXT_KEY, TEXT_KEY])
    _refused("field_keys", p6_field_keys, ["not a key"])
    _refused("field_keys", p6_field_keys, "xer:TASK.est_wt")


def test_the_included_fields_bounds() -> None:
    keys = [f"code:Synthetic {index:02d}" for index in range(MAX_P6_INCLUDED_FIELDS)]
    assert p6_included_fields(keys) == tuple(keys)
    assert p6_included_fields(None) is None
    _refused("fields", p6_included_fields, [*keys, "code:one more"])
    _refused("fields", p6_included_fields, [])


def test_the_entity_kind_is_closed() -> None:
    assert entity_kind_of("activity") is EntityKind.ACTIVITY
    assert entity_kind_of(None) is None
    _refused("entity_kind", entity_kind_of, "person")
