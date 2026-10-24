"""AT-004 / AT-010 (encodings): the record lineage S1 canonical encodings.

`domain/lineage/canonical.py` against the golden vectors in
`tests/fixtures/lineage_canonical_vectors.json` (S1 contract section 5). Every
expected string in that file is hand-written and every digest there is SHA-256
over the domain separator and that hand-written string, so these tests compare
the module with an independent statement of the encoding rather than with
itself. The same file drives `tests/database/test_lineage_canonical_sql_parity.py`,
so the Python and SQL encodings are held to one source. FAST tier; every value
is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.lineage.canonical import (
    DuplicateAnchorIdentityError,
    anchor_identity,
    anchor_object,
    canonical_evidence,
    evidence_set_digest,
    normalized_identity,
    passage_sha256,
    request_digest,
)
from my_pa.domain.lineage.model import EvidenceAnchor, InvalidLineageValueError, RecordRef
from my_pa.domain.lineage.vocabulary import (
    ISSUE_STATES,
    EvidenceRole,
    EvidenceSourceFamily,
    MemberRole,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
)
from my_pa.domain.situation.situation import SituationState

VECTORS: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lineage_canonical_vectors.json"


def _vectors() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return loaded


def _anchor(values: dict[str, Any], role: str | None = None) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily(values["source_family"]),
        source_root_id=values["source_root_id"],
        source_version_kind=SourceVersionKind(values["source_version_kind"]),
        source_version_id=values["source_version_id"],
        source_version_no=values["source_version_no"],
        source_sha256=values["source_sha256"],
        passage_start_cp=values["passage_start_cp"],
        passage_end_cp=values["passage_end_cp"],
        passage_sha256=values["passage_sha256"],
        role=EvidenceRole(role if role is not None else values["role"]),
    )


def _legacy_safe_role(values: dict[str, Any]) -> str:
    """A role every anchor family admits (a legacy root only corroborates)."""
    return "corroborates" if values["source_family"] == "capture" else "origin"


def test_evidence_set_digest_golden_vectors() -> None:
    sets = _vectors()["evidence_sets"]
    assert len(sets) >= 3
    for vector in sets:
        anchors = [_anchor(values) for values in vector["input"]]
        ordered = canonical_evidence(anchors)
        document = {"schema_version": 1, "anchors": [anchor_object(a) for a in ordered]}
        rendered = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert rendered == vector["canonical"], vector["name"]
        assert evidence_set_digest(anchors) == vector["digest"], vector["name"]
        # The digest is over the separator and the canonical bytes, nothing else.
        assert (
            hashlib.sha256(b"lineage-evidence-set-v1\n" + rendered.encode("utf-8")).hexdigest()
            == vector["digest"]
        )
        # Input order never matters.
        assert evidence_set_digest(reversed(anchors)) == vector["digest"], vector["name"]


def test_request_digest_golden_vectors() -> None:
    requests = _vectors()["request_digests"]
    assert len(requests) >= 3
    for vector in requests:
        digest = request_digest(vector["capability"], vector["principal_id"], vector["request"])
        assert digest == vector["digest"], vector["name"]
        assert (
            hashlib.sha256(
                b"lineage-request-v1\n" + vector["canonical"].encode("utf-8")
            ).hexdigest()
            == vector["digest"]
        )


def test_normalized_identity_golden_vectors() -> None:
    links = _vectors()["record_link_identities"]
    assert len(links) >= 3
    for vector in links:
        values = vector["input"]
        identity = normalized_identity(
            kind=RecordLinkKind(values["kind"]),
            relation_type=RelationType(values["relation_type"]),
            from_ref=RecordRef(RecordFamily(values["from_family"]), values["from_id"]),
            to_ref=RecordRef(RecordFamily(values["to_family"]), values["to_id"]),
            member_role=None
            if values["member_role"] is None
            else MemberRole(values["member_role"]),
            context_issue_id=values["context_issue_id"],
        )
        assert identity == vector["expected"], vector["name"]
        assert identity.isascii()


def test_anchor_order_is_total_with_nulls_first() -> None:
    vector = next(
        v
        for v in _vectors()["evidence_sets"]
        if v["name"] == "null_passage_first_then_numeric_start"
    )
    anchors = [_anchor(values) for values in vector["input"]]
    ordered = canonical_evidence(anchors)
    # A whole-version anchor (null passage) sorts before any passage, and the
    # starts compare as integers: 3 before 10, which a string sort would invert.
    assert [a.passage_start_cp for a in ordered] == [None, 3, 10]
    # Every permutation of the input lands in the one order.
    for rotation in range(len(anchors)):
        rotated = anchors[rotation:] + anchors[:rotation]
        assert canonical_evidence(rotated) == ordered
        assert canonical_evidence(reversed(rotated)) == ordered


def test_passage_hash_counts_code_points_not_bytes_or_graphemes() -> None:
    # "é" as one code point (2 UTF-8 bytes), "e" + combining acute as two code
    # points (one grapheme), and an astral emoji (one code point, 4 bytes).
    body = "Café and café \U0001f600 end"
    start, end = body.index("\U0001f600"), body.index("\U0001f600") + 1
    assert passage_sha256(body, start, end) == hashlib.sha256(b"\xf0\x9f\x98\x80").hexdigest()
    combining = body.index("café")
    # Offsets 5 code points long take the combining mark as its own code point.
    assert (
        passage_sha256(body, combining, combining + 5)
        == hashlib.sha256("café".encode()).hexdigest()
    )
    # The body is never normalized: the NFC form of the same passage differs.
    assert (
        passage_sha256(body, combining, combining + 5)
        != hashlib.sha256(unicodedata.normalize("NFC", "café").encode()).hexdigest()
    )
    # Byte offsets are not code-point offsets: the 2-byte "é" shifts them.
    assert passage_sha256(body, 0, 4) == hashlib.sha256("Café".encode()).hexdigest()
    for bad_start, bad_end in ((4, 4), (5, 4), (-1, 2), (0, len(body) + 1)):
        with pytest.raises(InvalidLineageValueError):
            passage_sha256(body, bad_start, bad_end)


def test_request_digest_does_not_nfc_normalize() -> None:
    vectors = {v["name"]: v for v in _vectors()["request_digests"]}
    nfc, nfd = vectors["create_nfc_title"], vectors["create_nfd_title"]
    assert unicodedata.normalize("NFC", nfd["request"]["title"]) == nfc["request"]["title"]
    assert nfc["request"]["title"] != nfd["request"]["title"]
    assert request_digest(nfc["capability"], nfc["principal_id"], nfc["request"]) != request_digest(
        nfd["capability"], nfd["principal_id"], nfd["request"]
    )


def test_anchor_identity_excludes_role() -> None:
    for vector in _vectors()["anchor_identities"]:
        values = vector["input"]
        role = _legacy_safe_role(values)
        first = _anchor(values, role)
        assert anchor_identity(first) == vector["expected"], vector["name"]
        assert '"role"' not in anchor_identity(first)
        assert anchor_object(first)["role"] == role
        other = "contradicts" if role == "corroborates" else "discussion"
        assert anchor_identity(_anchor(values, other)) == anchor_identity(first)


def test_an_evidence_set_repeating_an_anchor_identity_is_refused() -> None:
    """Section 5.1: a shared identity is refused whether or not the roles differ."""
    note = _vectors()["anchor_identities"][0]["input"]
    with pytest.raises(DuplicateAnchorIdentityError):
        canonical_evidence([_anchor(note, "origin"), _anchor(note, "discussion")])
    with pytest.raises(DuplicateAnchorIdentityError):
        evidence_set_digest([_anchor(note, "origin"), _anchor(note, "origin")])


def test_issue_states_are_the_non_terminal_situation_states() -> None:
    """S1 admitted the three non-terminal states; S2 admits `closed`, so all four now."""
    assert frozenset(ISSUE_STATES) == {state.value for state in SituationState}
