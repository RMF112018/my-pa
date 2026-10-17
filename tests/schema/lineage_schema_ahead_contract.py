"""The one home of the record lineage S1 schema-ahead gap (ADR-015, S1 contract 4.3).

The single S1 revision `264310e0416a` restates `capability_is_known` and
`purpose_is_known` with the fourteen S1 capability names and five S1 purposes,
while the domain (`Capability`, `Purpose`) declares them in the S1 application
slice that registers the capabilities. Between the two, every head-equality
test of the audit vocabulary holds the database equal to the domain **union**
the Knowledge gap (`knowledge_schema_ahead_contract`) **union** this gap. The
precedent is the Knowledge revision `6734f039f7a6`, which admitted its
vocabulary ahead of the domain the same way.

`LINEAGE_S1_DECLARED_BY_DOMAIN` is the one switch: the change that declares the
nineteen members flips it to `True`, which empties the gap. The gap is measured,
not trusted: `tests/schema/test_record_lineage_s1_migration.py` holds the
switch equal to what the domain actually declares, so declaring the members
without flipping it (or flipping it early) reddens in FAST. This is a helper
module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

#: Flipped to `True` by the S1 change that declares the members below in
#: `domain/identity/operation.py` and `domain/identity/purpose.py`.
LINEAGE_S1_DECLARED_BY_DOMAIN: Final[bool] = False

S1_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "issues.create",
        "issues.read",
        "issues.list",
        "issues.update",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.memberships.add",
        "issues.memberships.end",
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
        "records.lineage",
        "meetings.notes.versions",
        "meetings.notes.read_version",
    }
)
S1_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "issue_authoring",
        "issue_read",
        "record_lineage_authoring",
        "record_lineage_read",
        "meeting_note_history_read",
    }
)


def lineage_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S1 values of one family the database admits ahead of the domain right now."""
    if LINEAGE_S1_DECLARED_BY_DOMAIN:
        return frozenset()
    return S1_CAPABILITIES if family == "capability" else S1_PURPOSES
