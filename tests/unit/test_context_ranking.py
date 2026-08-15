"""Pure ranker/packer: order, diversity, truncation, and contradiction flags."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from my_pa.application.context.ranking import rank_and_pack
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.context.prepared import (
    ContextLimitationCode,
    ContextPlane,
    ContradictionCode,
    EvidenceLifecycle,
    PreparedContextEvidence,
    SelectionReasonCode,
    SourceAuthorityClass,
)
from my_pa.domain.source.registry import issue_identifier

PRINCIPAL = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
SOURCE = "src_aaaaaaaaaaaaaaaaaaaaaaaa"
OBJECT = "obj_aaaaaaaaaaaaaaaaaaaaaaaa"
WHEN = datetime(2026, 8, 15, 12, tzinfo=UTC)


def _knowledge(
    *,
    reference_id: str,
    text: str,
    version_id: str,
    source_id: str = SOURCE,
    source_object_id: str = OBJECT,
    knowledge_id: str | None = None,
    reason_codes: tuple[SelectionReasonCode, ...] = (SelectionReasonCode.LEXICAL_STRONG,),
    freshness: datetime | None = WHEN,
) -> PreparedContextEvidence:
    return PreparedContextEvidence(
        reference_id=reference_id,
        principal_id=PRINCIPAL,
        plane=ContextPlane.KNOWLEDGE,
        authority_class=SourceAuthorityClass.ENROLLED_SOURCE,
        lifecycle=EvidenceLifecycle.SOURCE_EVIDENCE,
        text=text,
        freshness=freshness,
        reason_codes=reason_codes,
        source_id=source_id,
        source_object_id=source_object_id,
        source_version_id=version_id,
        knowledge_id=knowledge_id or issue_identifier(IdKind.KNOWLEDGE),
    )


def _capture(
    *,
    reference_id: str,
    text: str,
    capture_id: str,
    version_id: str,
    reason_codes: tuple[SelectionReasonCode, ...] = (SelectionReasonCode.LEXICAL_STRONG,),
    freshness: datetime | None = WHEN,
) -> PreparedContextEvidence:
    return PreparedContextEvidence(
        reference_id=reference_id,
        principal_id=PRINCIPAL,
        plane=ContextPlane.CAPTURE,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CAPTURE,
        lifecycle=EvidenceLifecycle.USER_AUTHORED,
        text=text,
        freshness=freshness,
        reason_codes=reason_codes,
        capture_id=capture_id,
        capture_version_id=version_id,
    )


def _continuity(
    *,
    reference_id: str,
    text: str,
    product_id: str,
    reason_codes: tuple[SelectionReasonCode, ...] = (SelectionReasonCode.ACCEPTED_RECORD,),
    freshness: datetime | None = WHEN,
) -> PreparedContextEvidence:
    return PreparedContextEvidence(
        reference_id=reference_id,
        principal_id=PRINCIPAL,
        plane=ContextPlane.CONTINUITY,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
        lifecycle=EvidenceLifecycle.ACCEPTED,
        text=text,
        freshness=freshness,
        reason_codes=reason_codes,
        product_id=product_id,
    )


def test_exact_identifier_outranks_unrelated_lexical() -> None:
    lexical = _knowledge(
        reference_id="lex-1",
        text="quarterly revenue review",
        version_id=make_identifier(IdKind.VERSION, "lexicalversion00000001"),
        freshness=WHEN + timedelta(days=1),
        reason_codes=(SelectionReasonCode.LEXICAL_STRONG,),
    )
    exact = _capture(
        reference_id="id-1",
        text="a synthetic note",
        capture_id=make_identifier(IdKind.CAPTURE, "hintcapture000000000001"),
        version_id=make_identifier(IdKind.CAPTURE_VERSION, "hintversion00000000001"),
        reason_codes=(SelectionReasonCode.EXACT_IDENTIFIER, SelectionReasonCode.EXPLICIT_SUBJECT),
    )
    packed = rank_and_pack((lexical, exact), max_items=8, max_bytes=32_768)
    assert packed.items[0].reference_id == "id-1"
    assert packed.items[1].reference_id == "lex-1"
    assert "score" not in packed.items[0].to_canonical_dict()
    assert "relevance" not in packed.items[0].to_canonical_dict()


def test_ordering_is_deterministic_for_the_same_inputs() -> None:
    older = _knowledge(
        reference_id="b-old",
        text="alpha",
        version_id=make_identifier(IdKind.VERSION, "olderversion0000000001"),
        freshness=WHEN - timedelta(days=2),
    )
    newer = _knowledge(
        reference_id="a-new",
        text="alpha too",
        version_id=make_identifier(IdKind.VERSION, "newerversion0000000001"),
        source_object_id=make_identifier(IdKind.SOURCE_OBJECT, "otherobject00000000001"),
        freshness=WHEN,
    )
    first = rank_and_pack((older, newer), max_items=8, max_bytes=32_768)
    second = rank_and_pack((newer, older), max_items=8, max_bytes=32_768)
    assert [item.reference_id for item in first.items] == [
        item.reference_id for item in second.items
    ]
    assert first.items[0].reference_id == "a-new"


def test_duplicates_cannot_fill_the_budget() -> None:
    source_id = make_identifier(IdKind.SOURCE, "monopolysource000000001")
    items = tuple(
        _knowledge(
            reference_id=f"dup-{index}",
            text=f"quarterly note {index}",
            version_id=make_identifier(IdKind.VERSION, f"dupversion{index:016d}"),
            source_id=source_id,
            knowledge_id=make_identifier(IdKind.KNOWLEDGE, f"dupknowledge{index:013d}"),
        )
        for index in range(6)
    )
    outsider = _capture(
        reference_id="other",
        text="quarterly outsider",
        capture_id=make_identifier(IdKind.CAPTURE, "outsidecapture00000001"),
        version_id=make_identifier(IdKind.CAPTURE_VERSION, "outsiderversion0000001"),
    )
    packed = rank_and_pack((*items, outsider), max_items=6, max_bytes=32_768)
    from_source = [item for item in packed.items if item.source_id == source_id]
    assert len(from_source) == 2
    assert any(item.reference_id == "other" for item in packed.items)
    assert packed.truncation.is_truncated is True
    assert packed.truncation.reason in {"diversity_budget", "item_budget"}
    assert ContextLimitationCode.RESULT_TRUNCATED in packed.limitations


def test_identical_duplicates_are_dropped_before_packing() -> None:
    version = make_identifier(IdKind.VERSION, "sameversion00000000001")
    knowledge = make_identifier(IdKind.KNOWLEDGE, "sameknowledge000000001")
    first = _knowledge(
        reference_id="keep",
        text="same excerpt",
        version_id=version,
        knowledge_id=knowledge,
    )
    second = _knowledge(
        reference_id="drop",
        text="same excerpt",
        version_id=version,
        knowledge_id=knowledge,
    )
    packed = rank_and_pack((first, second), max_items=8, max_bytes=32_768)
    assert len(packed.items) == 1
    assert packed.items[0].reference_id == "drop" or packed.items[0].reference_id == "keep"
    assert packed.truncation.is_truncated is False


def test_item_budget_truncation_is_disclosed() -> None:
    items = tuple(
        _knowledge(
            reference_id=f"item-{index}",
            text=f"note {index}",
            version_id=make_identifier(IdKind.VERSION, f"itemversion{index:015d}"),
            source_id=make_identifier(IdKind.SOURCE, f"itemsource{index:016d}"),
            source_object_id=make_identifier(IdKind.SOURCE_OBJECT, f"itemobject{index:016d}"),
            knowledge_id=make_identifier(IdKind.KNOWLEDGE, f"itemknowledge{index:012d}"),
        )
        for index in range(4)
    )
    packed = rank_and_pack(items, max_items=2, max_bytes=32_768)
    assert len(packed.items) == 2
    assert packed.truncation.is_truncated is True
    assert packed.truncation.reason == "item_budget"
    assert ContextLimitationCode.RESULT_TRUNCATED in packed.limitations


def test_byte_budget_truncation_is_disclosed() -> None:
    bulky = "quarterly " * 20
    items = tuple(
        _knowledge(
            reference_id=f"byte-{index}",
            text=bulky,
            version_id=make_identifier(IdKind.VERSION, f"byteversion{index:015d}"),
            source_id=make_identifier(IdKind.SOURCE, f"bytesource{index:016d}"),
            source_object_id=make_identifier(IdKind.SOURCE_OBJECT, f"byteobject{index:016d}"),
            knowledge_id=make_identifier(IdKind.KNOWLEDGE, f"byteknowledge{index:012d}"),
        )
        for index in range(4)
    )
    packed = rank_and_pack(items, max_items=16, max_bytes=len(bulky.encode()) + 10)
    assert packed.truncation.is_truncated is True
    assert packed.truncation.reason == "byte_budget"
    assert len(packed.items) == 1


def test_conflicting_versions_are_both_kept_and_flagged() -> None:
    first = _knowledge(
        reference_id="v1",
        text="the north warehouse is open",
        version_id=make_identifier(IdKind.VERSION, "conflictver00000000001"),
        reason_codes=(SelectionReasonCode.LEXICAL_STRONG,),
    )
    second = _knowledge(
        reference_id="v2",
        text="the north warehouse is closed",
        version_id=make_identifier(IdKind.VERSION, "conflictver00000000002"),
        knowledge_id=make_identifier(IdKind.KNOWLEDGE, "conflictkn000000000002"),
        reason_codes=(SelectionReasonCode.LEXICAL_STRONG,),
    )
    packed = rank_and_pack((first, second), max_items=8, max_bytes=32_768)
    assert len(packed.items) == 2
    assert packed.contradictions == (ContradictionCode.CONFLICTING_EVIDENCE,)


def test_conflicting_capture_versions_are_flagged() -> None:
    capture_id = make_identifier(IdKind.CAPTURE, "conflictcap00000000001")
    first = _capture(
        reference_id="c1",
        text="ship on monday",
        capture_id=capture_id,
        version_id=make_identifier(IdKind.CAPTURE_VERSION, "conflictcapver00000001"),
    )
    second = _capture(
        reference_id="c2",
        text="ship on friday",
        capture_id=capture_id,
        version_id=make_identifier(IdKind.CAPTURE_VERSION, "conflictcapver00000002"),
    )
    packed = rank_and_pack((first, second), max_items=8, max_bytes=32_768)
    assert {item.reference_id for item in packed.items} == {"c1", "c2"}
    assert packed.contradictions == (ContradictionCode.CONFLICTING_EVIDENCE,)


def test_missing_freshness_sorts_after_dated_evidence() -> None:
    dated = _knowledge(
        reference_id="dated",
        text="alpha",
        version_id=make_identifier(IdKind.VERSION, "datedversion0000000001"),
        freshness=WHEN,
    )
    undated = _knowledge(
        reference_id="undated",
        text="alpha",
        version_id=make_identifier(IdKind.VERSION, "undatedversion00000001"),
        source_object_id=make_identifier(IdKind.SOURCE_OBJECT, "undatedobject000000001"),
        knowledge_id=make_identifier(IdKind.KNOWLEDGE, "undatedknowledge000001"),
        freshness=None,
    )
    packed = rank_and_pack((undated, dated), max_items=8, max_bytes=32_768)
    assert packed.items[0].reference_id == "dated"
    assert packed.items[1].reference_id == "undated"


def test_plane_order_breaks_ties() -> None:
    shared = (SelectionReasonCode.LEXICAL_STRONG,)
    knowledge = _knowledge(
        reference_id="k",
        text="alpha",
        version_id=make_identifier(IdKind.VERSION, "tieversion000000000001"),
        freshness=WHEN,
        reason_codes=shared,
    )
    capture = _capture(
        reference_id="c",
        text="alpha",
        capture_id=make_identifier(IdKind.CAPTURE, "tiecapture000000000001"),
        version_id=make_identifier(IdKind.CAPTURE_VERSION, "tiecapver000000000001"),
        reason_codes=shared,
    )
    continuity = _continuity(
        reference_id="p",
        text="alpha",
        product_id=make_identifier(IdKind.PROJECT, "tieproject000000000001"),
        reason_codes=shared,
    )
    packed = rank_and_pack(
        (continuity, capture, knowledge),
        max_items=8,
        max_bytes=32_768,
    )
    assert [item.plane for item in packed.items] == [
        ContextPlane.KNOWLEDGE,
        ContextPlane.CAPTURE,
        ContextPlane.CONTINUITY,
    ]
