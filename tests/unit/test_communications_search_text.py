"""`comms_search_text_v2` and v1: basis, html->text, quoted-chain and disclaimer removal.

The v1-era cases below run against the current version (v2), which keeps them;
the v2 section at the end pins the anchoring and the v1-prefix property.
"""

from __future__ import annotations

import random
from typing import Any, Final

import pytest

from my_pa.domain.communications.model import NormalizedMessage
from my_pa.domain.communications.search_text import (
    MAX_SEARCH_TEXT_CHARS,
    SEARCH_TEXT_VERSION,
    SEARCH_TEXT_VERSION_V1,
    SEARCH_TEXT_VERSION_V2,
    SIGNATURE_TAIL_LINES,
    SearchTextBasis,
    SearchTextFlag,
    derive_search_text,
    derive_search_text_v1,
    html_to_text,
    normalize_plain_text,
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


@pytest.mark.parametrize(
    "text",
    [
        # R1's probes: body text and its identifiers must survive.
        "Hi Bob,\nPlease see RFI 174; this message includes confidential pricing for the GMP."
        "\nThanks",
        "Hi Bob,\n\nThe GMP is attached. This email covers the confidential pricing."
        "\nCall me.\n\nAlpha",
        "Update\n--\nRFI 174 answered",
    ],
)
def test_ordinary_body_text_is_never_cut_as_a_disclaimer(text: str) -> None:
    assert strip_disclaimer(text) == (text, False)


def test_a_this_message_confidential_paragraph_far_from_the_end_is_kept() -> None:
    body = "\n".join(f"Line {n} of the body." for n in range(SIGNATURE_TAIL_LINES + 1))
    text = f"Hi Bob,\n\nThis message is confidential pricing for the GMP.\n{body}"
    assert strip_disclaimer(text) == (text, False)


def test_a_signature_break_far_from_the_end_never_lifts_the_tail_limit() -> None:
    # Manager ruling on R2's N3: a break counts only inside the trailing region.
    tail = "\n".join(f"Legal line {n}." for n in range(SIGNATURE_TAIL_LINES + 1))
    for rule in ("-----", "__________", "-- "):
        text = f"Main text.\n{rule}\nAlpha\n\nThis email is privileged.\n{tail}"
        assert strip_disclaimer(text) == (text, False), rule


@pytest.mark.parametrize(
    "text",
    [
        # R2's N3 probes: an early break used to cut 33 of 36 lines of body text.
        "Update\n--\nItem one\n\nThis message summarises the confidential GMP pricing\n"
        "for RFI 12.\n" + "\n".join(f"line {i}" for i in range(30)),
        "Notes\n-----\nTable\n\nThis email covers the confidential GMP.\n"
        + "\n".join(f"RFI {i}" for i in range(30)),
    ],
)
def test_an_early_signature_break_never_cuts_later_body_text(text: str) -> None:
    assert strip_disclaimer(text) == (text, False)


@pytest.mark.parametrize("rule", ["-----", "-" * 40])
def test_a_trailing_dash_rule_starts_the_disclaimer_paragraph_under_it(rule: str) -> None:
    # (A trailing `-- ` is itself a cut, at the delimiter: see the marker tests.)
    # Review R3-1: the cut is at the rule, so the body line above it is kept.
    text = f"Main text.\n\nAlpha\n{rule}\nThis email is privileged and confidential."
    assert strip_disclaimer(text) == ("Main text.\n\nAlpha", True)


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        # R3's R3-1 probes: the cut used to walk back through the rule and drop
        # the whole body paragraph above it (1 of 5 and 1 of 34 lines kept).
        (
            "Hi Bob,\n\nPlease review RFI 174 before Friday.\n-----\n"
            "This email is confidential and privileged.",
            "Hi Bob,\n\nPlease review RFI 174 before Friday.",
        ),
        (
            "Hi Bob,\n\n"
            + "\n".join(f"Item RFI {i} answered" for i in range(30))
            + "\n-----\nThis email is confidential and privileged.",
            "Hi Bob,\n\n" + "\n".join(f"Item RFI {i} answered" for i in range(30)),
        ),
    ],
)
def test_a_disclaimer_under_a_dash_rule_never_removes_the_body_above_the_rule(
    text: str, kept: str
) -> None:
    assert strip_disclaimer(text) == (kept, True)


@pytest.mark.parametrize("rule", ["--", "__________", "----"])
def test_only_the_delimiter_or_a_dash_rule_is_a_signature_break(rule: str) -> None:
    text = f"Main text.\n\nAlpha\n{rule}\nThis email is privileged and confidential."
    assert strip_disclaimer(text) == (text, False)


@pytest.mark.parametrize(
    "text",
    [
        # R2's N4 probe: the marker sat mid-paragraph, directly under a greeting.
        "Hi\nIf you are not the intended recipient of the GMP, tell me. RFI 5\nThanks",
        "Hi\n\nPlease read the confidentiality notice in the GMP before RFI 5.\nThanks",
        "Hi\nConfidentiality notice for RFI 5 is attached.\nThanks",
    ],
)
def test_recipient_and_confidentiality_markers_mid_paragraph_are_body_text(text: str) -> None:
    assert strip_disclaimer(text) == (text, False)


@pytest.mark.parametrize(
    "marker",
    ["CONFIDENTIALITY NOTICE: legal words.", "If you are not the intended recipient, delete."],
)
def test_recipient_and_confidentiality_markers_far_from_the_end_are_kept(marker: str) -> None:
    body = "\n".join(f"Line {n} of the body." for n in range(SIGNATURE_TAIL_LINES + 1))
    text = f"Hi Bob,\n\n{marker}\n{body}"
    assert strip_disclaimer(text) == (text, False)


def test_the_information_in_this_email_form_is_a_disclaimer() -> None:
    text = "Main text.\n\nThe information contained in this email is confidential."
    assert strip_disclaimer(text) == ("Main text.", True)


def test_a_signature_delimiter_far_from_the_end_is_ordinary_text() -> None:
    body = "\n".join(f"Line {n}." for n in range(SIGNATURE_TAIL_LINES + 1))
    text = f"Main text.\n-- \n{body}"
    assert strip_disclaimer(text) == (text, False)


def test_the_rfc_3676_delimiter_survives_normalization_and_cuts_the_signature() -> None:
    record = s.message(1, content="Main text.\r\n-- \r\nAlpha Synthetic\r\n", content_type="text")
    result = derive_search_text(one(record))
    assert result.text == "Main text."
    assert F.DISCLAIMER_REMOVED in result.flags
    assert normalize_plain_text("a  \n-- \n--  \nb") == "a\n-- \n--\nb"


def test_output_is_capped() -> None:
    content = "word " * (MAX_SEARCH_TEXT_CHARS // 4)
    result = derive_search_text(one(s.message(1, content=content, content_type="text")))
    assert result.text is not None
    assert len(result.text) == MAX_SEARCH_TEXT_CHARS
    assert F.TEXT_CAPPED in result.flags


# ---- comms_search_text_v2: the two markers anchored (WP4, contract section 6) -----------


def test_v2_is_current_and_v1_stays_callable() -> None:
    assert SEARCH_TEXT_VERSION == SEARCH_TEXT_VERSION_V2 == "comms_search_text_v2"
    assert SEARCH_TEXT_VERSION_V1 == "comms_search_text_v1"
    message = one(s.message(1, content="Main text.\n\nDisclaimer: x.", content_type="text"))
    assert derive_search_text(message).version == SEARCH_TEXT_VERSION_V2
    assert derive_search_text_v1(message).version == SEARCH_TEXT_VERSION_V1
    with pytest.raises(ValueError, match="unknown search text version"):
        strip_disclaimer("x", version="comms_search_text_v9")


#: v1 cut each of these at a line merely holding a marker; v2 keeps the body.
_V1_ONLY_CUTS: Final = (
    # The report's probe: a mid-body line that starts with "Disclaimer", directly
    # under the greeting (not a paragraph start).
    "Hi team,\nDisclaimer language for the contract is attached; please review RFI 12.\n\nThanks",
    # A paragraph-start "Disclaimer" line far from the end (not in the trailing region).
    "Hi team,\n\nDisclaimer wording for RFI 12 is attached.\n"
    + "\n".join(f"Item {n} of the punch list." for n in range(SIGNATURE_TAIL_LINES + 1)),
    # The in-error phrase inside a sentence, on a paragraph-start trailing line.
    "Hi,\n\nPlease note that if you have received this email in error they will resend it."
    "\n\nThanks",
    # The in-error phrase at a line start, but mid-paragraph.
    "Hi,\nIf you have received this message in error, the courier resends RFI 5.\nThanks",
)


@pytest.mark.parametrize("text", _V1_ONLY_CUTS)
def test_v2_keeps_body_text_that_v1_cut_at_an_unanchored_marker(text: str) -> None:
    assert strip_disclaimer(text, version=SEARCH_TEXT_VERSION_V1)[1] is True
    assert strip_disclaimer(text) == (text, False)


@pytest.mark.parametrize(
    "text",
    [
        "Main text.\n\nDisclaimer: nothing here is advice.",
        "Main text.\n\nIf you have received this message in error, tell us.",
        "Main text.\n-----\nDISCLAIMER: synthetic legal words.",
        "Main text.\n\nif you have received this e-mail in error please delete it.",
    ],
)
def test_v2_still_cuts_a_trailing_paragraph_start_marker(text: str) -> None:
    assert strip_disclaimer(text) == ("Main text.", True)
    assert strip_disclaimer(text, version=SEARCH_TEXT_VERSION_V1) == ("Main text.", True)


def test_v2_cuts_a_disclaimer_paragraph_in_a_short_message_a_known_residual() -> None:
    """WP4-R1 F3, accepted as design of record: pinned so the limitation is explicit.

    In a message of at most `SIGNATURE_TAIL_LINES` non-blank lines the whole
    text is the trailing region, so a paragraph that starts with "Disclaimer"
    is cut with the identifiers in it. A change here is a new search-text version.
    """
    text = (
        "Hi team,\n\nDisclaimer language for the contract is attached; please review"
        " RFI 12 and PCO 4 by Friday.\n\nThanks,\nBob"
    )
    assert strip_disclaimer(text) == ("Hi team,", True)


def _fixture_messages() -> list[NormalizedMessage]:
    documents = [builder() for builder in s.COMMITTED.values()]
    documents += [s.lean_publication(), s.rich_publication()]
    documents.append(
        s.publication(
            [
                s.message(n, content=content, content_type="text")
                for n, content in enumerate(
                    (*_V1_ONLY_CUTS, s.QUOTED_REPLY, s.IDENTIFIER_TEXT), start=1
                )
            ],
            s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h"),
            rich=True,
        )
    )
    messages: list[NormalizedMessage] = []
    for document in documents:
        publication = parse_publication(s.encode(document)).publication
        assert publication is not None
        messages += [r.message for r in publication.records if r.message is not None]
    return messages


def test_the_v1_text_is_a_prefix_of_the_v2_text_for_every_fixture_message() -> None:
    messages = _fixture_messages()
    assert len(messages) > 20
    removed = {SEARCH_TEXT_VERSION_V1: 0, SEARCH_TEXT_VERSION_V2: 0}
    for message in messages:
        v1, v2 = derive_search_text_v1(message), derive_search_text(message)
        assert (v1.text is None) == (v2.text is None)
        assert v1.basis is v2.basis
        if v1.text is not None and v2.text is not None:
            assert v2.text.startswith(v1.text)
        assert v1.flags - {F.DISCLAIMER_REMOVED} == v2.flags - {F.DISCLAIMER_REMOVED}
        removed[v1.version] += F.DISCLAIMER_REMOVED in v1.flags
        removed[v2.version] += F.DISCLAIMER_REMOVED in v2.flags
    # The `disclaimer_removed` count never grows, and the fixtures show it shrink.
    assert removed[SEARCH_TEXT_VERSION_V2] < removed[SEARCH_TEXT_VERSION_V1]


_POOL: Final = (
    "Hi Bob,",
    "Please review RFI 174 before Friday.",
    "Disclaimer language for the contract is attached.",
    "Disclaimer: synthetic legal words.",
    "If you have received this message in error, delete it.",
    "Note: if you have received this email in error they resend.",
    "CONFIDENTIALITY NOTICE: synthetic.",
    "This email is confidential and privileged.",
    "If you are not the intended recipient, delete this.",
    "-- ",
    "--",
    "-----",
    "__________",
    "",
    "",
    "Thanks,",
    "Alpha",
)


def test_the_prefix_property_over_generated_variants() -> None:
    """Seeded, so a failure reproduces; every variant is normalized first, as derived."""
    generator = random.Random(20261125)  # noqa: S311 - a reproducible test seed
    checked = 0
    for _ in range(3000):
        lines = [generator.choice(_POOL) for _ in range(generator.randint(1, 30))]
        text = normalize_plain_text("\n".join(lines))
        if not text:
            continue
        v1, cut1 = strip_disclaimer(text, version=SEARCH_TEXT_VERSION_V1)
        v2, cut2 = strip_disclaimer(text, version=SEARCH_TEXT_VERSION_V2)
        assert v2.startswith(v1), text
        assert v1 and v2, text  # never cut to empty
        assert cut1 or not cut2, text  # a v2 cut implies a v1 cut
        checked += 1
    assert checked > 2500
