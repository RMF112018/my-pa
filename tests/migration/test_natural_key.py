"""The natural-key digest.

This hash is what identifies a row everywhere the row itself may not appear: in
`source_key_map`, in `quarantine_records`, and in the provenance column on the
row. Two distinct source rows sharing a digest would let the loader treat one as
a duplicate of the other, so the encoding has to be unambiguous rather than
merely convenient. Needs no database.
"""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.natural_key import NaturalKeyError, hash_values


def test_the_same_tuple_always_hashes_the_same() -> None:
    assert hash_values(["a", 1, 2.5, None]) == hash_values(["a", 1, 2.5, None])


def test_tuples_that_concatenate_alike_hash_differently() -> None:
    """Length-prefixing is the whole point: ('a','bc') is not ('ab','c')."""
    assert hash_values(["a", "bc"]) != hash_values(["ab", "c"])


def test_order_matters() -> None:
    assert hash_values(["a", "b"]) != hash_values(["b", "a"])


def test_a_null_is_not_an_empty_string() -> None:
    """SQLite distinguishes them and OD-009 requires the distinction be preserved."""
    assert hash_values([None]) != hash_values([""])


def test_storage_classes_are_distinguished() -> None:
    assert hash_values([1]) != hash_values(["1"])
    assert hash_values([1]) != hash_values([1.0])


def test_bytes_are_hashed_without_decoding() -> None:
    assert hash_values([b"ab"]) != hash_values(["ab"])


def test_a_type_sqlite_cannot_produce_is_refused() -> None:
    with pytest.raises(NaturalKeyError, match="dict"):
        hash_values([{"a": 1}])
