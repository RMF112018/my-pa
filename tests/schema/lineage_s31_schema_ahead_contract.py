"""The one home of the record lineage S3.1 schema-ahead gap (ADR-015, S3.1 contract 5.3).

The single S3.1 revision `023f8f7eb499` restates `capability_is_known` with the
four S3.1 capability names (no purpose: S3.1 adds none), under the S1-S4
schema-ahead precedent (`lineage_s4_schema_ahead_contract`): every head-equality
test of the audit vocabulary holds the database equal to the domain **union**
every earlier gap **union** this gap.

The S3.1 registration declares every S3.1 name in the same change that adds the
revision (S3.1 contract section 9, worker N1), so
`S31_CAPABILITIES_DECLARED_BY_DOMAIN` equals the full set, the gap is empty and
`LINEAGE_S31_DECLARED_BY_DOMAIN` is true. The gap is measured, not trusted:
`tests/schema/test_record_lineage_s31_migration.py` holds the declared set equal
to what `Capability` actually declares. This is a helper module, not a test
module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

S31_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "records.associations.confirm",
        "issues.memberships.confirm",
        "issues.project_links.confirm",
        "records.lineage.related",
    }
)
#: S3.1 adds no purpose (S3.1 contract section 7).
S31_PURPOSES: Final[frozenset[str]] = frozenset()

#: The S3.1 capability names `domain/identity/operation.py` declares right now:
#: every one, so the gap is empty.
S31_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S31_CAPABILITIES
S31_PURPOSES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S31_PURPOSES

#: True exactly when the domain declares every S3.1 value, so the gap is empty.
LINEAGE_S31_DECLARED_BY_DOMAIN: Final[bool] = (
    S31_CAPABILITIES_DECLARED_BY_DOMAIN == S31_CAPABILITIES
    and S31_PURPOSES_DECLARED_BY_DOMAIN == S31_PURPOSES
)


def lineage_s31_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S3.1 values of one family the database admits ahead of the domain right now."""
    if family == "capability":
        return S31_CAPABILITIES - S31_CAPABILITIES_DECLARED_BY_DOMAIN
    return S31_PURPOSES - S31_PURPOSES_DECLARED_BY_DOMAIN
