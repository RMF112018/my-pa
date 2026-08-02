"""Text and Markdown extraction: what decodes, what does not, and what it says.

Every byte string here was written for this file. Nothing is drawn from a real
document, and no test asserts on the content of one.

The recurring claim is the one `docs/specs` section 12 makes: an object that did
not become text says so as itself. So each negative below asserts the *status*
and the *reason*, not merely that the text is empty — a test that only checked
for an empty string would pass against the exact defect the section forbids.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    SUPPORTED_MEDIA_TYPES,
    ExtractionOutcome,
    ExtractionStatus,
    extract_text,
)
from my_pa.domain.source.registry import issue_identifier

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Invented for this file.
SYNTHETIC_TEXT = "First invented line.\nSecond invented line.\n"


def _extract(
    *,
    content: bytes = b"invented",
    media_type: str | None = "text/plain",
    is_truncated: bool = False,
    content_version_id: str | None = None,
    max_characters: int = 1 << 22,
) -> ExtractionOutcome:
    version_id = issue_identifier(IdKind.VERSION)
    return extract_text(
        source_id=issue_identifier(IdKind.SOURCE),
        source_object_id=issue_identifier(IdKind.SOURCE_OBJECT),
        observed_version_id=version_id,
        content_version_id=version_id if content_version_id is None else content_version_id,
        media_type=media_type,
        content=content,
        observed_at=OBSERVED_AT,
        processed_at=OBSERVED_AT,
        is_truncated=is_truncated,
        max_characters=max_characters,
    )


@pytest.mark.parametrize("media_type", sorted(SUPPORTED_MEDIA_TYPES))
def test_the_mandatory_baseline_decodes(media_type: str) -> None:
    outcome = _extract(content=SYNTHETIC_TEXT.encode("utf-8"), media_type=media_type)

    assert outcome.status is ExtractionStatus.EXTRACTED
    assert outcome.text == SYNTHETIC_TEXT
    assert outcome.media_type == media_type


def test_the_supported_set_is_exactly_text_and_markdown() -> None:
    """Pinned, because widening it is how a decision-gated type gets extracted."""
    assert sorted(SUPPORTED_MEDIA_TYPES) == ["text/markdown", "text/plain"]


def test_extraction_binds_to_the_observed_version_as_derived_content() -> None:
    """`INV-PKL-003`: derived text carries the extractor, never source authority."""
    outcome = _extract(content=SYNTHETIC_TEXT.encode("utf-8"))

    assert outcome.provenance.trust_level is TrustLevel.SOURCE_BOUND_DERIVED
    assert outcome.provenance.extractor == EXTRACTOR
    assert outcome.provenance.extractor_version == EXTRACTOR_VERSION
    assert outcome.provenance.observed_at == OBSERVED_AT


def test_an_outcome_cannot_claim_source_authority() -> None:
    """The type refuses, so no caller can construct one that lies about trust."""
    extracted = _extract(content=b"invented")
    original = type(extracted.provenance)(
        source_id=extracted.provenance.source_id,
        source_object_id=extracted.provenance.source_object_id,
        version_id=extracted.provenance.version_id,
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        observed_at=OBSERVED_AT,
        processed_at=OBSERVED_AT,
        trust_level=TrustLevel.SOURCE_ORIGINAL,
    )

    with pytest.raises(ValueError, match="never source original"):
        ExtractionOutcome(
            status=ExtractionStatus.EXTRACTED,
            provenance=original,
            media_type="text/plain",
            text="invented",
        )


def test_a_pdf_is_reported_unsupported_and_never_coerced_into_text() -> None:
    """`P00-OD-003` is open. Section 12 requires this to be explicit, not a skip."""
    outcome = _extract(content=b"%PDF-1.7\ninvented", media_type="application/pdf")

    assert outcome.status is ExtractionStatus.UNSUPPORTED
    assert outcome.text is None
    assert outcome.quarantine_reason is None
    assert outcome.media_type == "application/pdf"


def test_an_unidentified_media_type_is_unsupported_rather_than_assumed_to_be_text() -> None:
    """`None` means "not identified here". It does not mean text and it does not
    mean empty."""
    outcome = _extract(content=SYNTHETIC_TEXT.encode("utf-8"), media_type=None)

    assert outcome.status is ExtractionStatus.UNSUPPORTED
    assert outcome.text is None


def test_a_decode_failure_is_a_quarantine_and_not_empty_text() -> None:
    """The specific defect section 12 names: malformed media reported as empty."""
    outcome = _extract(content=b"valid then \xc3\x28 invalid")

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.MALFORMED_INPUT
    assert outcome.text is None


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"%PDF-1.7 invented", id="pdf"),
        pytest.param(b"PK\x03\x04invented", id="zip"),
        pytest.param(b"\x89PNG\r\n\x1a\ninvented", id="png"),
        pytest.param(b"\xff\xd8\xff\xe0invented", id="jpeg"),
        pytest.param(b"\xff\xfei\x00n\x00", id="utf16"),
        pytest.param(b"plain then \x00 a nul", id="embedded-nul"),
    ],
)
def test_bytes_that_contradict_the_declared_media_type_are_quarantined(content: bytes) -> None:
    """A signature conflict is its own trigger and a more precise answer than malformed."""
    outcome = _extract(content=content, media_type="text/plain")

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE


def test_output_bound_to_a_different_version_than_the_one_observed_is_quarantined() -> None:
    """Section 12's last trigger: the output is not attributable to the observation."""
    outcome = _extract(
        content=SYNTHETIC_TEXT.encode("utf-8"),
        content_version_id=issue_identifier(IdKind.VERSION),
    )

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.OUTPUT_NOT_ATTRIBUTABLE_TO_VERSION


def test_attribution_is_checked_before_the_media_type_is_consulted() -> None:
    """A drifted version is not "unsupported PDF"; it is unattributable output.

    Reporting the media type first would file a mid-processing change as a
    routine skip, and the caller would never learn the source moved.
    """
    outcome = _extract(
        content=b"%PDF-1.7",
        media_type="application/pdf",
        content_version_id=issue_identifier(IdKind.VERSION),
    )

    assert outcome.quarantine_reason is QuarantineReason.OUTPUT_NOT_ATTRIBUTABLE_TO_VERSION


def test_output_beyond_the_ceiling_is_a_resource_quarantine() -> None:
    outcome = _extract(content=b"a" * 64, max_characters=32)

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.RESOURCE_LIMIT_EXCEEDED


def test_output_exactly_at_the_ceiling_is_extracted() -> None:
    """The paired negative: the bound must not refuse what it permits."""
    outcome = _extract(content=b"a" * 32, max_characters=32)

    assert outcome.status is ExtractionStatus.EXTRACTED
    assert outcome.character_count == 32


def test_a_byte_order_mark_is_stripped_rather_than_decoded() -> None:
    outcome = _extract(content=b"\xef\xbb\xbfinvented")

    assert outcome.status is ExtractionStatus.EXTRACTED
    assert outcome.text == "invented"


def test_a_read_cut_mid_character_is_not_treated_as_a_damaged_document() -> None:
    """A bounded read that stops inside a multi-byte character is the caller's
    ceiling doing its job, not evidence that the document is malformed.

    The euro sign is three bytes; the read here kept two of them.
    """
    outcome = _extract(content="cost: €".encode()[:-1], is_truncated=True)

    assert outcome.status is ExtractionStatus.EXTRACTED
    assert outcome.text == "cost: "
    assert outcome.is_truncated is True


def test_the_same_broken_tail_is_quarantined_when_the_read_was_complete() -> None:
    """The paired negative, and the reason the truncation flag is load-bearing.

    Identical bytes, not reported as truncated: nothing cut them, so they are a
    document that does not decode, and that is a quarantine.
    """
    outcome = _extract(content="cost: €".encode()[:-1], is_truncated=False)

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.MALFORMED_INPUT


def test_at_most_three_bytes_are_dropped_from_a_truncated_tail() -> None:
    """The repair is bounded, so it cannot swallow content to force a decode."""
    outcome = _extract(content=b"invented\xff\xff\xff\xff\xff", is_truncated=True)

    assert outcome.status is ExtractionStatus.QUARANTINED
    assert outcome.quarantine_reason is QuarantineReason.MALFORMED_INPUT


def test_an_empty_document_extracts_as_empty_text_and_says_so() -> None:
    """Empty is a legitimate document, and it is not a failure.

    This is the other side of the section 12 rule: a failure never looks empty,
    and an empty document is never reported as a failure.
    """
    outcome = _extract(content=b"")

    assert outcome.status is ExtractionStatus.EXTRACTED
    assert outcome.text == ""
    assert outcome.character_count == 0


def test_the_representation_of_an_outcome_never_carries_the_text() -> None:
    """Extracted text is personal data, and `repr` is how it reaches a log.

    The default dataclass representation would put the whole document into any
    log line, assertion message, or debugger frame that touched an outcome.
    """
    private_sentence = "invented private sentence that must not be logged"
    outcome = _extract(content=private_sentence.encode("utf-8"))

    rendered = repr(outcome)
    assert private_sentence not in rendered
    assert "invented" not in rendered
    assert f"characters={len(private_sentence)}" in rendered
    assert outcome.provenance.version_id in rendered


def test_extract_text_reports_rather_than_raises_for_unreadable_content() -> None:
    """A caller must not need an `except` clause to learn a document failed.

    Raising would put the quarantine one swallowed exception away from becoming
    a silent skip.
    """
    assert _extract(content=b"\xff\xfe\x00bad").status is ExtractionStatus.QUARANTINED
    assert _extract(content=b"\x80\x81").status is ExtractionStatus.QUARANTINED


def test_a_quarantined_outcome_cannot_be_given_text() -> None:
    outcome = _extract(content=b"\x80\x81")

    with pytest.raises(ValueError, match="carries no text"):
        ExtractionOutcome(
            status=ExtractionStatus.QUARANTINED,
            provenance=outcome.provenance,
            media_type="text/plain",
            text="invented",
            quarantine_reason=QuarantineReason.MALFORMED_INPUT,
        )


def test_a_quarantined_outcome_cannot_omit_its_reason() -> None:
    outcome = _extract(content=b"\x80\x81")

    with pytest.raises(ValueError, match="reason accompanies"):
        ExtractionOutcome(
            status=ExtractionStatus.QUARANTINED,
            provenance=outcome.provenance,
            media_type="text/plain",
        )


def test_an_extracted_outcome_cannot_name_an_unsupported_media_type() -> None:
    outcome = _extract(content=b"invented")

    with pytest.raises(ValueError, match="supported media type"):
        ExtractionOutcome(
            status=ExtractionStatus.EXTRACTED,
            provenance=outcome.provenance,
            media_type="application/pdf",
            text="invented",
        )
