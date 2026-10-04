"""No Knowledge column can hold a source body (KLP-WP-02, KLP-AC-012).

The Knowledge layer stores identities, closed tokens, digests and bounded
values -- never a message, document, attachment or HTML body, and no deep link
or locator (R6 simplification S-4). The only column that holds external
content is `knowledge_evidence_refs.excerpt`, bounded to 2,048 characters and
redact-only. The other text-bearing columns are exactly:

- `value_text` on assertions and proposals (at most 4,000 characters; the
  asserted value, not source content);
- `qualifier_json` on assertions and proposals (a `date_kind` object only);
- `correction_patch` on review decisions (a JSON object of at most 8,192 octets);
- `private_envelope` / `result_private_envelope` on checkpoints and checkpoint
  requests (opaque, at most 4,096 octets, returned only to the bound client);
- `reason` on review decisions (at most 1,000 characters).

This module reads the live declaration (`tables.py`), which
`tests/schema/test_knowledge_assertion_migration.py` holds equal to the
revision and the matrix. Every other `text`, `text[]` and `jsonb` column of a
`knowledge_*` table must be *structurally bounded*: an anchored regular
expression, a closed set, a length of at most 512 characters, or a foreign key
onto a column that is itself bounded. A new unbounded column fails here
whatever its name.
"""

from __future__ import annotations

import re
from typing import Final

from sqlalchemy import ARRAY, CheckConstraint, ForeignKeyConstraint, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

from my_pa.infrastructure.persistence.tables import METADATA, SCHEMA

#: The only text-bearing Knowledge columns, each with the CHECK text that bounds it.
FREE_TEXT: Final[dict[tuple[str, str], str]] = {
    ("knowledge_evidence_refs", "excerpt"): "char_length(excerpt) BETWEEN 1 AND 2048",
    ("knowledge_assertions", "value_text"): "char_length(value_text) BETWEEN 1 AND 4000",
    ("knowledge_assertion_proposals", "value_text"): "char_length(value_text) BETWEEN 1 AND 4000",
    ("knowledge_assertions", "qualifier_json"): "(qualifier_json - 'date_kind') = '{}'::jsonb",
    ("knowledge_assertion_proposals", "qualifier_json"): (
        "(qualifier_json - 'date_kind') = '{}'::jsonb"
    ),
    ("knowledge_assertion_review_decisions", "correction_patch"): (
        "octet_length(correction_patch::text) <= 8192"
    ),
    ("knowledge_assertion_review_decisions", "reason"): "char_length(reason) BETWEEN 1 AND 1000",
    ("knowledge_discovery_checkpoints", "private_envelope"): (
        "octet_length(private_envelope) BETWEEN 1 AND 4096"
    ),
    ("knowledge_discovery_checkpoint_requests", "result_private_envelope"): (
        "octet_length(result_private_envelope) BETWEEN 1 AND 4096"
    ),
}
#: The one column that may hold external source content, and its ceiling.
EXCERPT: Final = ("knowledge_evidence_refs", "excerpt")
MAX_TOKEN_CHARACTERS: Final = 512
FORBIDDEN_NAMES: Final = re.compile(
    r"body|html|content(?!_hash|_origin)|message|attachment|locator|deep_link|url|uri\b|path"
)


def _knowledge_tables() -> list[Table]:
    return [
        table
        for name, table in sorted(METADATA.tables.items())
        if name.startswith(f"{SCHEMA}.knowledge_")
    ]


def _checks(table: Table, column: str) -> list[str]:
    word = re.compile(rf"\b{column}\b")
    return [
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and word.search(str(constraint.sqltext))
    ]


def _bounded_by_check(table: Table, column: str) -> bool:
    for check in _checks(table, column):
        if re.search(rf"\b{column} ~ '\^[^']*\$'", check):
            return True
        if re.search(rf"\b{column} IN \(", check) or re.search(rf"\b{column} <@ ARRAY\[", check):
            return True
        # A tagged-union discriminator: every branch pins the column to one literal
        # (`owner_ref_kind = 'task' AND owner_ref_id ~ ...` or both NULL).
        if re.search(rf"\({column} IS NULL AND ", check) and re.search(
            rf"\({column} = '\w+' AND ", check
        ):
            return True
        bound = re.search(rf"char_length\({column}\) BETWEEN 1 AND (\d+)", check)
        if bound and int(bound.group(1)) <= MAX_TOKEN_CHARACTERS:
            return True
    return False


def _bounded(table: Table, column: str, seen: frozenset[tuple[str, str]] = frozenset()) -> bool:
    key = (table.name, column)
    if key in seen:
        return False
    if _bounded_by_check(table, column):
        return True
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        for local, element in zip(constraint.column_keys, constraint.elements, strict=True):
            if local == column:
                target = element.column.table
                assert isinstance(target, Table)
                if _bounded(target, element.column.name, seen | {key}):
                    return True
    return False


def _text_bearing(table: Table) -> list[str]:
    return [column.name for column in table.c if isinstance(column.type, Text | JSONB | ARRAY)]


def test_the_scan_reads_all_fourteen_knowledge_tables() -> None:
    names = {table.name for table in _knowledge_tables()}
    assert len(names) == 14
    assert {"knowledge_evidence_refs", "knowledge_assertions"} <= names


def test_the_free_text_columns_are_exactly_the_enumerated_ones_with_their_bounds() -> None:
    """AC-012: every unbounded text-bearing column is on the list, with its bound."""
    unbounded = {
        (table.name, column)
        for table in _knowledge_tables()
        for column in _text_bearing(table)
        if not _bounded(table, column)
    }
    assert unbounded == set(FREE_TEXT)
    for (table_name, column), bound in FREE_TEXT.items():
        table = METADATA.tables[f"{SCHEMA}.{table_name}"]
        assert any(bound in check for check in _checks(table, column)), (table_name, column)


def test_only_the_evidence_excerpt_holds_external_content_and_it_is_redact_only() -> None:
    """The 2,048-character excerpt; a restricted row stores none (AC-012, AC-013)."""
    evidence = METADATA.tables[f"{SCHEMA}.knowledge_evidence_refs"]
    assert "char_length(excerpt) BETWEEN 1 AND 2048" in " ".join(_checks(evidence, "excerpt"))
    assert any(
        "source_classification <> 'restricted_local' OR excerpt IS NULL" in check
        for check in _checks(evidence, "excerpt")
    )
    larger = [
        (table_name, column)
        for (table_name, column), bound in FREE_TEXT.items()
        if (table_name, column) != EXCERPT and "2048" in bound
    ]
    assert larger == []


def test_no_knowledge_column_is_named_for_a_body_or_a_locator() -> None:
    """S-4: no full body, attachment, HTML, deep link or locator column exists."""
    offenders = [
        (table.name, column.name)
        for table in _knowledge_tables()
        for column in table.c
        if FORBIDDEN_NAMES.search(column.name)
    ]
    assert offenders == []


def test_the_boundedness_detector_is_not_vacuous() -> None:
    """A planted unbounded column is reported; a planted bounded one is not."""
    from sqlalchemy import Column, MetaData

    planted = Table(
        "knowledge_planted",
        MetaData(),
        Column("free", Text),
        Column("token", Text),
        Column("long", Text),
        CheckConstraint("token ~ '^[a-z]{1,8}$'", name="token_is_bounded"),
        CheckConstraint("char_length(long) BETWEEN 1 AND 513", name="long_is_bounded"),
    )
    assert not _bounded(planted, "free")
    assert _bounded(planted, "token")
    assert not _bounded(planted, "long")
