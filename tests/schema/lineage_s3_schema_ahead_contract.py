"""The one home of the record lineage S3 schema-ahead gap (ADR-015, S3 contract 4.1).

The single S3 revision `6f1476b8da52` restates `capability_is_known` and
`purpose_is_known` with the eight S3 capability names and the one S3 purpose
(`lineage_backfill`), under the S1 schema-ahead precedent
(`lineage_schema_ahead_contract`, itself on the Knowledge revision
`6734f039f7a6`'s): every head-equality test of the audit vocabulary holds the
database equal to the domain **union** the Knowledge gap **union** the S1 gap
**union** the S2 gap **union** this gap.

The S3 registration declares every S3 name and the purpose in the same change
that adds the revision (S3 contract section 9, worker L1), so
`S3_CAPABILITIES_DECLARED_BY_DOMAIN` and `S3_PURPOSES_DECLARED_BY_DOMAIN` equal
the full sets, the gap is empty and `LINEAGE_S3_DECLARED_BY_DOMAIN` is true. The
gap is measured, not trusted: `tests/schema/test_record_lineage_s3_migration.py`
holds both declared sets equal to what `Capability` and `Purpose` actually
declare, so declaring a member without listing it here (or listing it early)
reddens in FAST. This is a helper module, not a test module: pytest does not
collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

S3_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "records.associations.contest",
        "records.associations.reinstate",
        "records.associations.history",
        "issues.history",
        "issues.timeline",
        "issues.handoffs.correct",
        "records.backfill.plan",
        "records.backfill.report",
    }
)
S3_PURPOSES: Final[frozenset[str]] = frozenset({"lineage_backfill"})

#: The S3 capability names `domain/identity/operation.py` declares right now:
#: every one, so the gap is empty.
S3_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S3_CAPABILITIES
#: The S3 purposes `domain/identity/purpose.py` declares right now: the one.
S3_PURPOSES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S3_PURPOSES

#: True exactly when the domain declares every S3 value, so the gap is empty.
LINEAGE_S3_DECLARED_BY_DOMAIN: Final[bool] = (
    S3_CAPABILITIES_DECLARED_BY_DOMAIN == S3_CAPABILITIES
    and S3_PURPOSES_DECLARED_BY_DOMAIN == S3_PURPOSES
)


def lineage_s3_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S3 values of one family the database admits ahead of the domain right now."""
    if family == "capability":
        return S3_CAPABILITIES - S3_CAPABILITIES_DECLARED_BY_DOMAIN
    return S3_PURPOSES - S3_PURPOSES_DECLARED_BY_DOMAIN
