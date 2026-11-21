"""`comms_search_text_v1`: basis selection, html->text, quoted-chain and disclaimer removal."""

from __future__ import annotations

from typing import Any

import pytest

from my_pa.domain.communications.model import NormalizedMessage
from my_pa.domain.communications.search_text import (
    MAX_SEARCH_TEXT_CHARS,
    SEARCH_TEXT_VERSION,
    SearchTextBasis,
    SearchTextFlag,
    derive_search_text,
    html_to_text,
    strip_disclaimer,
    strip_quoted_chain,
)
from my_pa.infrastructure.communications.evidence_v2 import parse_publication
from tests.fixtures.communications_evidence import synthetic as s

B = SearchTextBasis
F = SearchTextFlag


def normalized(*records: dict[str, Any]) -> list[NormalizedMessage]:
    document = s.publication(
        list(records),
        s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h"),
        rich=True,
    )
    publication = parse_publication(s.encode(document)).publication
    assert publication is not None
    messages = [r.message for r in publication.records]
    assert all(m is not None for m in messages)
    return [m for m in messages if m is not None]


def one(record: dict[str, Any]) -> NormalizedMessage:
    (message,) = normalized(record)
    return message


def test_a_withheld_body_yields_no_text() -> None:
    result = derive_search_text(one(s.richen(s.message(1), withheld=True)))
    assert result.version == SEARCH_TEXT_VERSION
    assert result.text is None
    assert result.basis is B.NONE
    assert result.flags == {F.WITHHELD, F.METADATA_ONLY}


def test_a_truncated_body_yields_no_text() -> None:
    record = s.message(1)
    record["body"] = s.body("<p>Partial RFI 174", completeness="truncated_unknown")
    result = derive_search_text(one(record))
    assert result.text is None
    assert result.flags == {F.TRUNCATED, F.METADATA_ONLY}


def test_an_empty_body_yields_no_text() -> None:
    result = derive_search_text(one(s.message(1, content="<p> </p>")))
    assert result.text is None
    assert F.EMPTY in result.flags


def test_unique_body_is_preferred() -> None:
    record = s.richen(s.message(1, content=s.QUOTED_REPLY))
    unique = "<p>Only the new text.</p>"
    record["unique_body"].update(
        {"content": unique, "sha256": s.sha(unique), "utf8_bytes": len(unique.encode())}
    )
    result = derive_search_text(one(record))
    assert result.basis is B.UNIQUE_BODY
    assert result.text == "Only the new text."


def test_verified_producer_text_is_used_when_there_is_no_unique_body() -> None:
    record = s.message(1, content="<p>Body text.</p>")
    record["body_derived_plain_text"] = {
        "derived": True,
        "sha256": s.sha("Producer text."),
        "text": "Producer text.",
    }
    result = derive_search_text(one(record))
    assert result.basis is B.PRODUCER_DERIVED_TEXT
    assert result.text == "Producer text."


def test_producer_text_without_a_digest_is_not_used() -> None:
    record = s.message(1, content="<p>Body text.</p>")
    record["body_derived_plain_text"] = {"derived": True, "text": "Undeclared text."}
    result = derive_search_text(one(record))
    assert result.basis is B.BODY_CONTENT
    assert result.text == "Body text."


def test_null_producer_text_falls_back_to_the_body() -> None:
    record = s.message(1, content="Plain body.", content_type="text")
    record["body_derived_plain_text"] = None
    result = derive_search_text(one(record))
    assert (result.basis, result.text) == (B.BODY_CONTENT, "Plain body.")


def test_quoted_chain_and_disclaimer_are_removed() -> None:
    result = derive_search_text(one(s.message(1, content=s.QUOTED_REPLY)))
    assert result.text == "Please review RFI 174 before Friday.\n\nThanks,\n\nAlpha"
    assert {F.QUOTED_CHAIN_REMOVED, F.DISCLAIMER_REMOVED} <= result.flags
    assert "999" not in (result.text or "")


def test_malicious_html_is_inert_text() -> None:
    result = derive_search_text(one(s.message(1, content=s.MALICIOUS_HTML)))
    text = result.text or ""
    assert "Visible synthetic text." in text
    assert "click here" in text
    for forbidden in ("alert", "fetch", "javascript", "onerror", "color:red", "hidden comment"):
        assert forbidden not in text
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in text  # kept as ordinary, inert text
    assert F.MARKUP_DROPPED in result.flags


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>a</p><p>b</p>", "a\n\nb"),
        ("<div>a</div>b", "a\nb"),
        ("a<br>b<br/>c", "a\nb\nc"),
        ("<p>caf&eacute; &amp; &#x41;&nbsp;&lt;tag&gt;</p>", "café & A <tag>"),
        ("<table><tr><td>x</td><td>y</td></tr></table>", "x y"),
        ("<p>kept</p><blockquote>quoted reply</blockquote>", "kept"),
        ("<p>unclosed <script>var a = '</p>';", "unclosed"),
        ("<p>a   \t b</p>\n\n\n\n<p>c</p>", "a b\n\nc"),
    ],
)
def test_html_to_text(html: str, expected: str) -> None:
    assert html_to_text(html)[0] == expected


@pytest.mark.parametrize(
    "text",
    [
        "New text.\n-----Original Message-----\nFrom: x\nold",
        "New text.\nOn Mon, Nov 16, 2026 at 9:00 AM Bravo <b@example.invalid> wrote:\nold",
        "New text.\nOn Mon, Nov 16, 2026 at 9:00 AM Bravo\n<b@example.invalid> wrote:\nold",
        "New text.\n________________\nFrom: Bravo\nSent: Monday\nTo: Alpha\nSubject: RE: x\nold",
        "New text.\nFrom: Bravo\nDate: Monday\nSubject: x\n\nold",
        "New text.\n> old line one\n>> old line two",
    ],
)
def test_quoted_chain_markers(text: str) -> None:
    stripped, flag = strip_quoted_chain(text)
    assert stripped == "New text."
    assert flag is F.QUOTED_CHAIN_REMOVED


@pytest.mark.parametrize(
    "text",
    [
        "From: the field office we heard nothing.\nThe pour is on schedule.",
        "On Monday the crew starts.\nNothing was written.",
        "Discussing a ratio of 3 > 2 inline is fine.",
    ],
)
def test_quoted_chain_near_misses_are_left_alone(text: str) -> None:
    assert strip_quoted_chain(text) == (text, None)


def test_a_bare_forward_keeps_its_text() -> None:
    text = "-----Original Message-----\nFrom: x\nForwarded content."
    assert strip_quoted_chain(text) == (text, F.QUOTED_CHAIN_RETAINED)


@pytest.mark.parametrize(
    "text",
    [
        "Main text.\n\nCONFIDENTIALITY NOTICE: legal words.",
        "Main text.\n\nIf you are not the intended recipient, delete this.",
        "Main text.\n\nThis email and any attachments are confidential.",
        "Main text.\n\nIf you have received this message in error, tell us.",
        "Main text.\n\nDisclaimer: nothing here is advice.",
        "Main text.\n-- \nAlpha Synthetic\nProject Engineer",
    ],
)
def test_disclaimer_and_signature_markers(text: str) -> None:
    assert strip_disclaimer(text) == ("Main text.", True)


def test_a_disclaimer_first_line_is_never_stripped_to_nothing() -> None:
    text = "This message is confidential: the bid numbers are attached."
    assert strip_disclaimer(text) == (text, False)


def test_a_mention_of_confidential_in_ordinary_prose_is_kept() -> None:
    text = "Main text.\n\nKeep the pricing confidential until Friday."
    assert strip_disclaimer(text) == (text, False)


def test_output_is_capped() -> None:
    content = "word " * (MAX_SEARCH_TEXT_CHARS // 4)
    result = derive_search_text(one(s.message(1, content=content, content_type="text")))
    assert result.text is not None
    assert len(result.text) == MAX_SEARCH_TEXT_CHARS
    assert F.TEXT_CAPPED in result.flags
