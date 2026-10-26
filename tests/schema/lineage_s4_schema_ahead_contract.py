"""The one home of the record lineage S4 schema-ahead gap (ADR-015, S4 contract 4.2).

The single S4 revision `c5260943d933` restates `capability_is_known` and
`purpose_is_known` with the seven S4 capability names and the one S4 purpose
(`program_reporting_read`), under the S1-S3 schema-ahead precedent
(`lineage_s3_schema_ahead_contract`): every head-equality test of the audit
vocabulary holds the database equal to the domain **union** every earlier gap
**union** this gap.

The S4 registration declares every S4 name and the purpose in the same change
that adds the revision (S4 contract section 9, worker M1), so
`S4_CAPABILITIES_DECLARED_BY_DOMAIN` and `S4_PURPOSES_DECLARED_BY_DOMAIN` equal
the full sets, the gap is empty and `LINEAGE_S4_DECLARED_BY_DOMAIN` is true. The
gap is measured, not trusted: `tests/schema/test_record_lineage_s4_migration.py`
holds both declared sets equal to what `Capability` and `Purpose` actually
declare. This is a helper module, not a test module: pytest does not collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

S4_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "programs.members.resolve",
        "programs.overview",
        "commitments.v2.read",
        "commitments.v2.list",
        "commitments.v2.search",
        "commitments.v2.waiting_on",
        "reports.manifest",
    }
)
S4_PURPOSES: Final[frozenset[str]] = frozenset({"program_reporting_read"})

#: The S4 capability names `domain/identity/operation.py` declares right now:
#: every one, so the gap is empty.
S4_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S4_CAPABILITIES
#: The S4 purposes `domain/identity/purpose.py` declares right now: the one.
S4_PURPOSES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S4_PURPOSES

#: True exactly when the domain declares every S4 value, so the gap is empty.
LINEAGE_S4_DECLARED_BY_DOMAIN: Final[bool] = (
    S4_CAPABILITIES_DECLARED_BY_DOMAIN == S4_CAPABILITIES
    and S4_PURPOSES_DECLARED_BY_DOMAIN == S4_PURPOSES
)


def lineage_s4_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S4 values of one family the database admits ahead of the domain right now."""
    if family == "capability":
        return S4_CAPABILITIES - S4_CAPABILITIES_DECLARED_BY_DOMAIN
    return S4_PURPOSES - S4_PURPOSES_DECLARED_BY_DOMAIN
