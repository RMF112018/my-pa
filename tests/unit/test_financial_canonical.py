"""Financial controlled source F-1: canonical serialisation and SHA-256 (contract section 6)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from my_pa.domain.project_controls.financial.canonical import (
    OVERVIEW_SCHEMA,
    SLICE_SCHEMA,
    SOURCE_SCHEMA,
    FinanceDecodeError,
    loads_canonical,
    overview_object,
    overview_sha256,
    period_snapshot,
    source_content_sha256,
    source_version_from_object,
    source_version_object,
)
from my_pa.domain.project_controls.financial.model import PeriodSnapshot
from my_pa.domain.project_controls.financial.reportability import evaluate_financial_overview
from my_pa.domain.schedule.canonical import canonical_json_bytes
from tests.fixtures.financial_domain import VERSIONS, d, scenario

#: The section 8.2 base version's `content_sha256`. The I11-B parser must produce
#: exactly this digest from `syn_at020_owner_budget.csv` (hash parity across the
#: domain-built and the parsed version).
AT020_CONTENT_SHA256 = "ae7b8de3bc2551718b6bf40d3e99457cec6e28e4b8661d4af68529a545a73e07"


def test_content_hash_ignores_row_order() -> None:
    at020 = VERSIONS["at020"]
    shuffled = replace(
        at020,
        account_lines=tuple(reversed(at020.account_lines)),
        change_orders=tuple(reversed(at020.change_orders)),
    )
    assert shuffled != at020
    assert source_content_sha256(shuffled) == source_content_sha256(at020)
    assert source_version_object(shuffled) == source_version_object(at020)
    refs = [line["ref"] for line in source_version_object(shuffled)["account_lines"]]  # type: ignore[attr-defined]
    assert refs == sorted(refs)


def test_content_object_round_trips() -> None:
    for name, version in VERSIONS.items():
        obj = source_version_object(version)
        decoded = source_version_from_object(loads_canonical(canonical_json_bytes(obj)))
        assert source_version_object(decoded) == obj, name
        assert source_content_sha256(decoded) == source_content_sha256(version), name
    at020 = VERSIONS["at020"]
    assert source_version_from_object(source_version_object(at020)) == at020


def test_decode_refuses_unknown_keys_and_numbers() -> None:
    obj = source_version_object(VERSIONS["at020"])
    extra = {**obj, "body_sha256": "0" * 64}
    missing = {k: v for k, v in obj.items() if k != "cost_basis"}
    lines = [dict(line) for line in obj["account_lines"]]  # type: ignore[attr-defined]
    numeric = {**obj, "account_lines": [{**lines[0], "amount": 1000000}, *lines[1:]]}
    unscaled = {**obj, "account_lines": [{**lines[0], "amount": "1000000.00001"}, *lines[1:]]}
    unsorted = {**obj, "account_lines": list(reversed(lines))}
    unknown_enum = {**obj, "perspective": "owner-budget"}
    bad: object
    for bad in (extra, missing, numeric, unscaled, unsorted, unknown_enum, [], "x", None):
        with pytest.raises(FinanceDecodeError) as caught:
            source_version_from_object(bad)
        assert "SYN" not in str(caught.value)
    with pytest.raises(FinanceDecodeError):
        loads_canonical(b'{"amount":1000000.0}')
    with pytest.raises(FinanceDecodeError):
        loads_canonical(b'{"amount":1e6}')


def test_hash_parity_detects_a_changed_amount() -> None:
    at020 = VERSIONS["at020"]
    changed = VERSIONS["version_conflict"]
    assert source_content_sha256(changed) != source_content_sha256(at020)
    obj = source_version_object(at020)
    lines = [dict(line) for line in obj["account_lines"]]  # type: ignore[attr-defined]
    lines[2]["amount"] = "400000.0001"
    readback = source_version_from_object({**obj, "account_lines": lines})
    assert source_content_sha256(readback) != source_content_sha256(at020)
    assert source_content_sha256(source_version_from_object(obj)) == source_content_sha256(at020)


def test_overview_digest_is_deterministic() -> None:
    s01 = scenario(1)
    first = overview_sha256(s01.evaluate())
    assert overview_sha256(s01.evaluate()) == first
    reordered = evaluate_financial_overview(
        s01.request,
        tuple(reversed(s01.designations)),
        tuple(reversed(s01.runs)),
        tuple(reversed(s01.mappings)),
        s01.quarantine,
    )
    assert overview_sha256(reordered) == first
    assert overview_sha256(scenario(5).evaluate()) != first
    obj = overview_object(s01.evaluate())
    assert json.loads(canonical_json_bytes(obj)) == obj
    assert obj["program_reasons"] == [] and obj["quarantined_runs"] == []
    assert (
        first
        == hashlib.sha256(
            OVERVIEW_SCHEMA.encode("ascii") + b"\n" + canonical_json_bytes(obj)
        ).hexdigest()
    )


def test_slice_hash_covers_only_its_project() -> None:
    at020 = VERSIONS["at020"]
    edited = VERSIONS["version_conflict"]  # SYN-L-003 of SYN-P-100 changed
    assert period_snapshot(edited, "SYN-P-100").slice_sha256 != (
        period_snapshot(at020, "SYN-P-100").slice_sha256
    )
    p200_before = period_snapshot(at020, "SYN-P-200")
    p200_after = period_snapshot(edited, "SYN-P-200")
    assert p200_before.source_content_sha256 != p200_after.source_content_sha256
    # The slice object carries the content digest, so compare its project rows only.
    assert (
        p200_before.account_line_count,
        p200_before.change_order_count,
        p200_before.transfer_leg_count,
    ) == (
        p200_after.account_line_count,
        p200_after.change_order_count,
        p200_after.transfer_leg_count,
    )
    same_content = replace(at020, account_lines=tuple(reversed(at020.account_lines)))
    assert period_snapshot(same_content, "SYN-P-200") == p200_before
    assert type(p200_before) is PeriodSnapshot
    assert SLICE_SCHEMA == "my-pa-finance-slice-v1"


def test_canonical_encoder_bytes_are_pinned() -> None:
    vector = {"b": [1, "xé"], "a": None, "c": True, "amount": "-150000.0000"}
    encoded = canonical_json_bytes(vector)
    assert encoded == b'{"a":null,"amount":"-150000.0000","b":[1,"x\\u00e9"],"c":true}'
    digest = hashlib.sha256(SOURCE_SCHEMA.encode("ascii") + b"\n" + encoded).hexdigest()
    assert digest == "319b706495defb281a78a07bf673e09ffa089488d1b1e52b25f59c0ab5d92929"
    assert source_content_sha256(VERSIONS["at020"]) == AT020_CONTENT_SHA256
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float("nan")})


def test_decode_refuses_bool_counts_and_nan() -> None:
    for text in (b"NaN", b'{"a":Infinity}', b"-Infinity", b"1.5", b"1e3", b"\xff", b"{"):
        with pytest.raises(FinanceDecodeError):
            loads_canonical(text)
    assert loads_canonical(b'{"a":[1,"x"]}') == {"a": [1, "x"]}
    with pytest.raises(TypeError):
        loads_canonical("{}")  # type: ignore[arg-type]
    obj = source_version_object(VERSIONS["at020"])
    for key in ("approved_by", "source_system", "period"):
        with pytest.raises(FinanceDecodeError):
            source_version_from_object({**obj, key: True})
    lines = [dict(line) for line in obj["account_lines"]]  # type: ignore[attr-defined]
    with pytest.raises(FinanceDecodeError):
        source_version_from_object({**obj, "account_lines": [{**lines[0], "amount": True}]})
    snapshot = period_snapshot(VERSIONS["at020"], "SYN-P-100")
    with pytest.raises(TypeError):
        replace(snapshot, account_line_count=True)
    assert d("1") == d("1.0000")
