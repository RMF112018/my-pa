"""The one home of the Knowledge schema-ahead gap table (KLP-WP-02, R6 section 12.1).

The single Knowledge revision `6734f039f7a6` admits every Knowledge capability,
Purpose, Record Event family, context plane and source authority class at once,
while the domain declares them work package by work package (WP-03 to WP-06).
Between the two, every database closed set the revision touches equals the
domain's closed set **union** exactly one gap row of this table, selected by
`KNOWLEDGE_WP_HEAD`. Every head-equality test imports its gap from here rather
than spelling it, so each later work package's whole edit to the gap is the
one-line bump of `KNOWLEDGE_WP_HEAD` (`"wp03"` ... `"wp06"`), and every row is
empty at `"wp06"` (KLP-AC-109, KLP-AC-132).

The rows are the R6 matrix `schema_ahead_contract_module.rows`, byte for byte;
`tests/schema/test_knowledge_assertion_migration.py` holds them equal. This is a
helper module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

#: The five vocabulary families the Knowledge revision widens ahead of the domain.
GapFamily = Literal[
    "capability", "purpose", "record_event_family", "context_plane", "source_authority_class"
]
KnowledgeWpHead = Literal["wp02", "wp03", "wp04", "wp05", "wp06"]

GAP_FAMILIES: Final[tuple[GapFamily, ...]] = (
    "capability",
    "purpose",
    "record_event_family",
    "context_plane",
    "source_authority_class",
)

#: The latest landed KLP work package. Bumped by WP-03, WP-04, WP-05 and WP-06,
#: each in the same change that declares the members its row stops listing.
KNOWLEDGE_WP_HEAD: Final[KnowledgeWpHead] = "wp03"

_WP02: Final = {
    "capability": frozenset(
        {
            "knowledge.assertions.read",
            "knowledge.assertions.list",
            "knowledge.assertions.search",
            "knowledge.assertions.history",
            "knowledge.assertions.reveal",
            "knowledge.assertions.create",
            "knowledge.assertions.submit",
            "knowledge.discovery.checkpoint",
            "record_events.provenance",
        }
    ),
    "purpose": frozenset(
        {
            "knowledge_assertion_read",
            "knowledge_assertion_authoring",
            "knowledge_assertion_observation",
            "record_event_provenance_read",
        }
    ),
    "record_event_family": frozenset({"knowledge_assertion"}),
    "context_plane": frozenset({"knowledge_assertion"}),
    "source_authority_class": frozenset({"product_owned_knowledge_assertion"}),
}
_WP03: Final = {
    "capability": frozenset(
        {
            "knowledge.assertions.submit",
            "knowledge.discovery.checkpoint",
            "record_events.provenance",
        }
    ),
    "purpose": frozenset({"knowledge_assertion_observation", "record_event_provenance_read"}),
    "record_event_family": frozenset[str](),
    "context_plane": frozenset({"knowledge_assertion"}),
    "source_authority_class": frozenset({"product_owned_knowledge_assertion"}),
}
_WP04: Final = {
    "capability": frozenset({"record_events.provenance"}),
    "purpose": frozenset({"record_event_provenance_read"}),
    "record_event_family": frozenset[str](),
    "context_plane": frozenset({"knowledge_assertion"}),
    "source_authority_class": frozenset({"product_owned_knowledge_assertion"}),
}
_WP05: Final = {
    "capability": frozenset[str](),
    "purpose": frozenset[str](),
    "record_event_family": frozenset[str](),
    "context_plane": frozenset({"knowledge_assertion"}),
    "source_authority_class": frozenset({"product_owned_knowledge_assertion"}),
}
_WP06: Final = {family: frozenset[str]() for family in GAP_FAMILIES}

#: The five-row gap table: for each KLP head, the values per family the database
#: admits that the domain does not yet declare.
GAP_ROWS: Final[Mapping[KnowledgeWpHead, Mapping[str, frozenset[str]]]] = MappingProxyType(
    {
        "wp02": MappingProxyType(_WP02),
        "wp03": MappingProxyType(_WP03),
        "wp04": MappingProxyType(_WP04),
        "wp05": MappingProxyType(_WP05),
        "wp06": MappingProxyType(_WP06),
    }
)


def current_gap() -> Mapping[str, frozenset[str]]:
    """The gap row for `KNOWLEDGE_WP_HEAD`, keyed by family."""
    return GAP_ROWS[KNOWLEDGE_WP_HEAD]


def admitted_ahead(family: GapFamily) -> frozenset[str]:
    """The values of one family the database admits ahead of the domain right now."""
    return current_gap()[family]
