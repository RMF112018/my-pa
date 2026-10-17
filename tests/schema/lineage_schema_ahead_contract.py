"""The one home of the record lineage S1 schema-ahead gap (ADR-015, S1 contract 4.3).

The single S1 revision `264310e0416a` restates `capability_is_known` and
`purpose_is_known` with the fourteen S1 capability names and five S1 purposes,
while the domain (`Capability`, `Purpose`) declares them in the S1 application
slice that registers the capabilities. Between the two, every head-equality
test of the audit vocabulary holds the database equal to the domain **union**
the Knowledge gap (`knowledge_schema_ahead_contract`) **union** this gap. The
precedent is the Knowledge revision `6734f039f7a6`, which admitted its
vocabulary ahead of the domain the same way.

The S1 application slices declare the members in turn, so the gap shrinks in
steps rather than all at once. `S1_CAPABILITIES_DECLARED_BY_DOMAIN` and
`S1_PURPOSES_DECLARED_BY_DOMAIN` name exactly the S1 values the domain declares
right now (the Issue plane's names and purposes first); the gap is the
rest. The slice that declares the remaining members adds them here, which
empties the gap and makes `LINEAGE_S1_DECLARED_BY_DOMAIN` true. The gap is
measured, not trusted: `tests/schema/test_record_lineage_s1_migration.py` holds
both declared sets equal to what `Capability` and `Purpose` actually declare,
so declaring a member without listing it here (or listing it early) reddens in
FAST. This is a helper module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

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


#: The S1 capability names `domain/identity/operation.py` declares right now:
#: the Issue plane (`issues.*` without memberships). The `issues.memberships.*`,
#: `records.*` and `meetings.notes.*` names join when they are declared.
S1_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = frozenset(
    {
        "issues.create",
        "issues.read",
        "issues.list",
        "issues.update",
        "issues.project_links.add",
        "issues.project_links.end",
    }
)
#: The S1 purposes `domain/identity/purpose.py` declares right now.
S1_PURPOSES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = frozenset({"issue_authoring", "issue_read"})

#: True exactly when the domain declares every S1 value, so the gap is empty.
LINEAGE_S1_DECLARED_BY_DOMAIN: Final[bool] = (
    S1_CAPABILITIES_DECLARED_BY_DOMAIN == S1_CAPABILITIES
    and S1_PURPOSES_DECLARED_BY_DOMAIN == S1_PURPOSES
)


def lineage_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S1 values of one family the database admits ahead of the domain right now."""
    if family == "capability":
        return S1_CAPABILITIES - S1_CAPABILITIES_DECLARED_BY_DOMAIN
    return S1_PURPOSES - S1_PURPOSES_DECLARED_BY_DOMAIN
