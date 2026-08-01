"""Identifier quoting, the 63-byte budget, and collision refusal."""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.identifiers import (
    MAX_IDENTIFIER_BYTES,
    IdentifierError,
    Namespace,
    assert_fits,
    neutralise,
    qualify,
    quote,
    shorten,
    target_name,
)


def test_quoting_preserves_reserved_words_and_escapes_quotes() -> None:
    assert quote("column") == '"column"'
    assert quote('od"d') == '"od""d"'
    assert qualify("procore", "procore_ep_rfqs") == '"procore"."procore_ep_rfqs"'


def test_a_name_that_fits_is_returned_unchanged() -> None:
    name = "a" * MAX_IDENTIFIER_BYTES
    assert shorten(name) == name


def test_a_longer_name_is_shortened_to_the_budget() -> None:
    shortened = shorten("b" * 200)
    assert len(shortened.encode("utf-8")) == MAX_IDENTIFIER_BYTES
    assert shortened.startswith("b" * 55)


def test_names_differing_only_after_byte_63_do_not_collide() -> None:
    """Plain truncation would fuse these two; the hash is of the full name."""
    prefix = "cost_impact_request_for_quote_currency_configuration_currency_ex"
    assert len(prefix) > MAX_IDENTIFIER_BYTES
    first = shorten(prefix + "change_rate")
    second = shorten(prefix + "change_ratio")

    assert first[:55] == second[:55]
    assert first != second
    assert len(first.encode("utf-8")) == len(second.encode("utf-8")) == MAX_IDENTIFIER_BYTES


def test_shortening_is_stable_across_calls() -> None:
    name = "revenue_impact_change_order_currency_configuration_base_currency_iso_code"
    assert shorten(name) == shorten(name)


def test_assert_fits_rejects_an_oversized_name() -> None:
    with pytest.raises(IdentifierError, match="over the 63-byte limit"):
        assert_fits("c" * 64)


def test_a_namespace_records_only_the_names_it_changed() -> None:
    namespace = Namespace("schema core")
    namespace.allocate("short_name", "table", "core")
    long_name = "d" * 90

    allocated = namespace.allocate(long_name, "index", "some_table")

    assert allocated != long_name
    assert [rename.original for rename in namespace.renames] == [long_name]
    assert namespace.renames[0].object_kind == "index"


def test_a_namespace_refuses_an_index_that_shadows_a_table() -> None:
    """SQLite allows it; PostgreSQL puts both in one relation namespace per schema."""
    namespace = Namespace("schema core")
    namespace.allocate("orders", "table", "core")

    with pytest.raises(IdentifierError, match="identifier collision"):
        namespace.allocate("orders", "index", "other_table")


def test_a_namespace_refuses_two_shortened_names_that_meet() -> None:
    namespace = Namespace("schema core")
    original = "e" * 90
    namespace.allocate(original, "index", "one_table")

    with pytest.raises(IdentifierError, match="identifier collision"):
        namespace.allocate(original, "index", "another_table")


def test_a_namespace_accepts_the_same_object_twice() -> None:
    namespace = Namespace("schema core")
    first = namespace.allocate("orders", "table", "core")

    assert namespace.allocate("orders", "table", "core") == first


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("hb_project_number", "project_number"),
        ("HB_project_number", "project_number"),
        ("project_hb_number", "project_number"),
        ("project_number_hb", "project_number"),
    ],
)
def test_a_former_employer_token_is_dropped(original: str, expected: str) -> None:
    assert neutralise(original) == expected
    assert target_name(original) == expected


@pytest.mark.parametrize("original", ["hbase_id", "thb_key", "shbx", "project_number"])
def test_a_token_that_merely_contains_the_letters_is_left_alone(original: str) -> None:
    assert neutralise(original) == original


def test_a_neutralised_name_is_recorded_as_a_rename() -> None:
    namespace = Namespace("table construction_project_identity")

    assert namespace.allocate("hb_project_number", "column", "t") == "project_number"
    assert namespace.renames[0].original == "hb_project_number"
