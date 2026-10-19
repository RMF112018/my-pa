"""The record lineage S3 pure domain (S3 contract sections 3.4, 4.2, 5 and 10).

FAST: no database, no clock beyond the instants each test states. Worker L1's
part of the crosswalk row: the knowledge cut rules (`domain.lineage.asof`), the
completeness precedence, and the backfill source document against the shared
golden vectors (`tests/fixtures/lineage_backfill_source_vectors.json`, which
`tests/database/test_lineage_backfill_digest_parity.py` holds the SQL functions
to). Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.lineage.asof import (
    COMPLETENESS_PRECEDENCE,
    CutAfterNowError,
    completeness,
    effective_known_at,
    is_known,
    knowledge_cut,
    native_cut,
)
from my_pa.domain.lineage.backfill import (
    PLAN_DOMAIN,
    SOURCE_DOMAIN,
    origin_reference,
    plan_digest,
    reference_token,
    source_digest,
    source_document,
)
from my_pa.domain.lineage.model import InvalidLineageValueError
from my_pa.domain.lineage.vocabulary import LineageCompleteness
from my_pa.domain.lineage_backfill.vocabulary import BackfillSourceKind

VECTORS: Final = (
    Path(__file__).resolve().parents[1] / "fixtures" / ("lineage_backfill_source_vectors.json")
)
NOW: Final = datetime(2026, 10, 19, 12, tzinfo=UTC)
HORIZON: Final = NOW - timedelta(hours=1)


def _vectors() -> dict[str, Any]:
    loaded = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _inputs(vector: dict[str, Any]) -> dict[str, Any]:
    stated = vector["input"]
    return {**stated, "source_kind": BackfillSourceKind(stated["source_kind"])}


# ---- section 3.4: the knowledge cut -------------------------------------------------


def test_known_and_valid_cut_rules() -> None:
    # T_k = min(requested known_at, or now; H): capped at the committed horizon.
    assert effective_known_at(None, now=NOW, horizon=HORIZON) == HORIZON
    earlier = HORIZON - timedelta(minutes=5)
    assert effective_known_at(earlier, now=NOW, horizon=HORIZON) == earlier
    assert effective_known_at(HORIZON + timedelta(minutes=5), now=NOW, horizon=HORIZON) == HORIZON
    # A Principal with no allocator row has no lineage fact.
    assert effective_known_at(None, now=NOW, horizon=None) is None
    # After now is refused, naming the field, before any horizon is consulted.
    with pytest.raises(CutAfterNowError) as late:
        effective_known_at(NOW + timedelta(seconds=1), now=NOW, horizon=None)
    assert late.value.field == "known_at"
    with pytest.raises(CutAfterNowError) as late_valid:
        knowledge_cut(known_at=None, valid_at=NOW + timedelta(seconds=1), now=NOW, horizon=HORIZON)
    assert late_valid.value.field == "valid_at"
    with pytest.raises(CutAfterNowError) as both:
        knowledge_cut(
            known_at=NOW + timedelta(seconds=1),
            valid_at=NOW + timedelta(seconds=1),
            now=NOW,
            horizon=HORIZON,
        )
    assert both.value.field == "known_at"

    # T_v = min(valid_at, T_k), defaulting to T_k; valid_at reported as requested.
    default = knowledge_cut(known_at=None, valid_at=None, now=NOW, horizon=HORIZON)
    assert (default.known_at, default.valid_at, default.lineage_valid_at) == (
        HORIZON,
        HORIZON,
        HORIZON,
    )
    past = HORIZON - timedelta(days=1)
    bounded = knowledge_cut(known_at=None, valid_at=past, now=NOW, horizon=HORIZON)
    assert (bounded.known_at, bounded.valid_at, bounded.lineage_valid_at) == (HORIZON, past, past)
    # A valid_at after the horizon is reported, but the lineage plane is clamped.
    after_horizon = HORIZON + timedelta(minutes=30)
    clamped = knowledge_cut(known_at=None, valid_at=after_horizon, now=NOW, horizon=HORIZON)
    assert clamped.valid_at == after_horizon
    assert clamped.lineage_valid_at == HORIZON
    empty = knowledge_cut(known_at=None, valid_at=past, now=NOW, horizon=None)
    assert (empty.known_at, empty.valid_at, empty.lineage_valid_at) == (None, past, None)

    # N = min(valid_at?, known_at?, read time): never the lineage horizon.
    assert native_cut(known_at=None, valid_at=None, read_time=NOW) == NOW
    assert native_cut(known_at=past, valid_at=None, read_time=NOW) == past
    assert native_cut(known_at=earlier, valid_at=past, read_time=NOW) == past

    # Knowledge of one fact: by its mark against W(T), or by recorded_at pre-S3.
    assert is_known(commit_seq=3, recorded_at=NOW, watermark=3, cut=HORIZON)
    assert not is_known(commit_seq=4, recorded_at=past, watermark=3, cut=HORIZON)
    assert not is_known(commit_seq=1, recorded_at=past, watermark=None, cut=HORIZON)
    assert is_known(commit_seq=None, recorded_at=past, watermark=None, cut=HORIZON)
    assert not is_known(commit_seq=None, recorded_at=NOW, watermark=9, cut=HORIZON)
    assert not is_known(commit_seq=1, recorded_at=past, watermark=1, cut=None)


def test_completeness_precedence() -> None:
    assert COMPLETENESS_PRECEDENCE == (
        LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED,
        LineageCompleteness.UNRESOLVED_AMBIGUITY,
        LineageCompleteness.TRUNCATED_BUDGET,
        LineageCompleteness.RESTRICTED_EVIDENCE,
        LineageCompleteness.PARTIAL_NATIVE_HISTORY,
        LineageCompleteness.COMPLETE,
    )
    assert set(COMPLETENESS_PRECEDENCE) == set(LineageCompleteness)
    assert completeness(()) == (LineageCompleteness.COMPLETE, (LineageCompleteness.COMPLETE,))
    assert completeness([LineageCompleteness.COMPLETE]) == (
        LineageCompleteness.COMPLETE,
        (LineageCompleteness.COMPLETE,),
    )
    state, qualifiers = completeness(
        [
            LineageCompleteness.PARTIAL_NATIVE_HISTORY,
            LineageCompleteness.COMPLETE,
            LineageCompleteness.RESTRICTED_EVIDENCE,
            LineageCompleteness.TRUNCATED_BUDGET,
            LineageCompleteness.RESTRICTED_EVIDENCE,
        ]
    )
    assert state is LineageCompleteness.TRUNCATED_BUDGET
    assert qualifiers == (
        LineageCompleteness.TRUNCATED_BUDGET,
        LineageCompleteness.RESTRICTED_EVIDENCE,
        LineageCompleteness.PARTIAL_NATIVE_HISTORY,
    )
    # A restart outranks everything, and `complete` never rides along.
    every = completeness(list(LineageCompleteness))
    assert every[0] is LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED
    assert LineageCompleteness.COMPLETE not in every[1]
    assert every[1] == COMPLETENESS_PRECEDENCE[:-1]


# ---- sections 4.2 and 5: the backfill source document ------------------------------


def test_backfill_source_document_golden_vectors() -> None:
    loaded = _vectors()
    vectors = loaded["vectors"]
    names = [vector["name"] for vector in vectors]
    assert len(names) == len(set(names)) >= 11
    # Every source kind is exercised.
    assert {vector["input"]["source_kind"] for vector in vectors} == {
        kind.value for kind in BackfillSourceKind
    }
    for vector in vectors:
        document = source_document(**_inputs(vector))
        assert document == vector["document"], vector["name"]
        assert document.isascii(), vector["name"]
        assert json.loads(document)["schema_version"] == 1
        expected = hashlib.sha256(SOURCE_DOMAIN + document.encode("utf-8")).hexdigest()
        assert source_digest(**_inputs(vector)) == expected == vector["digest"], vector["name"]
        reference = vector.get("reference")
        if reference is not None:
            # The stored token, and the digest the document carries, are of the
            # exact stored bytes; the text itself appears nowhere.
            kind, token = origin_reference(reference)
            assert kind.value == vector["input"]["source_kind"], vector["name"]
            assert token == vector["input"]["source_ref"], vector["name"]
            if not reference.isascii() or kind is BackfillSourceKind.WORK_ORIGIN_OTHER:
                assert reference not in document, vector["name"]
            digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
            assert vector["input"]["facts"]["origin_ref_sha256"] == digest

    by_name = {vector["name"]: vector for vector in vectors}
    # R3-F22: a non-ASCII, non-NFC free-text reference is digested as stored --
    # never normalized -- and its NFC form is a different token.
    free = by_name["work_origin_other_non_ascii_non_nfc"]["reference"]
    assert not free.isascii()
    assert unicodedata.normalize("NFC", free) != free
    assert reference_token(free) == "free_text:" + hashlib.sha256(free.encode()).hexdigest()
    assert reference_token(unicodedata.normalize("NFC", free)) != reference_token(free)
    # R3-F27: population by identifier shape, not by prefix.
    assert origin_reference("asrt_not-an-identifier")[0] is BackfillSourceKind.WORK_ORIGIN_OTHER
    assert origin_reference("cap_lineages3vec0001")[0] is (
        BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT
    )
    assert reference_token("mnote_lineages3vec0001").startswith("prefix:mnote:")
    assert all(
        len(vector["input"]["source_ref"]) <= 256 and vector["input"]["source_ref"].isascii()
        for vector in vectors
    )

    # The document refuses what the SQL function could not emit.
    task = _inputs(by_name["task_follow_up"])
    for broken in (
        {**task, "source_family": "commitment"},
        {**task, "facts": {}},
        {**task, "facts": {"commitment_id": "cmt_lineages3vec0001", "extra": 1}},
        {**task, "facts": {"commitment_id": "cmt_lineages3vecé0001"}},
        {**task, "source_ref": ""},
        {**task, "source_ref": "x" * 257},
        {**task, "source_version": 0},
    ):
        with pytest.raises(InvalidLineageValueError):
            source_document(**broken)
    assertion = _inputs(by_name["work_origin_assertion"])
    spans = list(assertion["facts"]["spans"])
    with pytest.raises(InvalidLineageValueError):
        source_document(**{**assertion, "facts": {**assertion["facts"], "spans": spans[::-1]}})

    # The plan digest: domain-separated canonical JSON over the items in order.
    items = [(1, "a" * 64, "native_virtual_proven", "native_follow_up", None)]
    expected_plan = hashlib.sha256(
        PLAN_DOMAIN
        + (
            '{"items":[[1,"' + "a" * 64 + '","native_virtual_proven","native_follow_up",null]],'
            '"run_id":"lbfr_lineages3vec0001","schema_version":1,"validator_version":1}'
        ).encode()
    ).hexdigest()
    assert plan_digest(run_id="lbfr_lineages3vec0001", validator_version=1, items=items) == (
        expected_plan
    )
    with pytest.raises(InvalidLineageValueError):
        plan_digest(run_id="lbfr_lineages3vec0001", validator_version=1, items=items * 2)
