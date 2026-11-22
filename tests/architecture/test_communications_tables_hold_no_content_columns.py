"""The WP3a tables hold no raw body, no raw HTML and no display name (ADR-022 decision 10).

Manager ruling m13. `communication_messages.search_text` is the one text column
the plane stores beyond the subject: the bounded, derived projection of contract
section 6, never the body. The `body_*` columns that do exist describe a body --
its state, digest and byte count -- and never hold it. Read off the declarations
in `tables.py`, which the schema tests prove equal to the revision.
"""

from __future__ import annotations

import re
from typing import Final

from my_pa.infrastructure.persistence.tables import COMMUNICATIONS_INGESTION_TABLES

#: Every column of the twelve tables whose name says `body`, `html`, `name`,
#: `display`, `content` or `raw`, and why it is not content.
_DESCRIBES_CONTENT_WITHOUT_HOLDING_IT: Final = {
    ("communication_messages", "body_state"): "a closed state",
    ("communication_messages", "body_sha256"): "a digest",
    ("communication_messages", "body_utf8_bytes"): "a byte count",
    ("communication_messages", "content_type"): "a closed media kind",
    ("communication_observations", "body_sha256"): "a digest",
    ("communication_observations", "unique_body_sha256"): "a digest",
}

_CONTENT_WORD: Final = re.compile(r"(^|_)(body|html|name|names|display|content|raw)($|_)")


def test_the_twelve_tables_are_the_ones_checked() -> None:
    assert len(COMMUNICATIONS_INGESTION_TABLES) == 12


def test_no_column_holds_a_body_html_or_display_name() -> None:
    flagged = {
        (table.name, column.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for column in table.c
        if _CONTENT_WORD.search(column.name)
    }
    assert flagged == set(_DESCRIBES_CONTENT_WITHOUT_HOLDING_IT)


def test_the_only_free_text_columns_are_the_subject_and_the_derived_search_text() -> None:
    """Every unbounded-by-vocabulary text column, listed, so a new one is argued here."""
    free_text = {
        (table.name, column.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for column in table.c
        if column.name in {"subject", "search_text", "description", "text", "notes", "summary"}
    }
    assert free_text == {
        ("communication_messages", "subject"),
        ("communication_messages", "search_text"),
    }


def test_the_planted_html_column_would_be_caught() -> None:
    """Prove-red for the matcher: content-shaped names are flagged."""
    for name in ("body", "body_html", "raw_body", "display_name", "sender_name", "html"):
        assert _CONTENT_WORD.search(name), name
    for name in ("body_sha256", "subject", "search_text", "sender_address"):
        assert (name in {"body_sha256"}) == bool(_CONTENT_WORD.search(name)), name
