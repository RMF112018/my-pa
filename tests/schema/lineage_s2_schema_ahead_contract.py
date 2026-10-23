"""The one home of the record lineage S2 schema-ahead gap (ADR-015, S2 contract 4.1).

The single S2 revision `d020b532ad7d` restates `capability_is_known` and
`purpose_is_known` with the S2 capability names and the one S2 purpose,
under the S1 schema-ahead precedent (`lineage_schema_ahead_contract`, itself on
the Knowledge revision `6734f039f7a6`'s): every head-equality test of the
audit vocabulary holds the database equal to the domain **union** the
Knowledge gap **union** the S1 gap **union** this gap.

The S2 registration declares every S2 name and the purpose in the same
change that adds the revision (S2 contract section 9, worker K1), so
`S2_CAPABILITIES_DECLARED_BY_DOMAIN` and `S2_PURPOSES_DECLARED_BY_DOMAIN` equal
the full sets, the gap is empty and `LINEAGE_S2_DECLARED_BY_DOMAIN` is true. The
gap is measured, not trusted: `tests/schema/test_record_lineage_s2_migration.py`
holds both declared sets equal to what `Capability` and `Purpose` actually
declare, so declaring a member without listing it here (or listing it early)
reddens in FAST. This is a helper module, not a test module: pytest does not
collect it.
"""

from __future__ import annotations

from typing import Final, Literal

LineageGapFamily = Literal["capability", "purpose"]

S2_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "issues.close",
        "issues.reopen",
        "issues.closure_readiness",
        "issues.memberships.correct",
        "issues.handoffs.record",
        "issues.handoffs.list",
        "issues.work.create_task",
        "issues.work.create_commitment",
    }
)
S2_PURPOSES: Final[frozenset[str]] = frozenset({"issue_work_authoring"})

#: The S2 capability names `domain/identity/operation.py` declares right now:
#: every one, so the gap is empty.
S2_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S2_CAPABILITIES
#: The S2 purposes `domain/identity/purpose.py` declares right now: the one.
S2_PURPOSES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = S2_PURPOSES

#: True exactly when the domain declares every S2 value, so the gap is empty.
LINEAGE_S2_DECLARED_BY_DOMAIN: Final[bool] = (
    S2_CAPABILITIES_DECLARED_BY_DOMAIN == S2_CAPABILITIES
    and S2_PURPOSES_DECLARED_BY_DOMAIN == S2_PURPOSES
)


def lineage_s2_admitted_ahead(family: LineageGapFamily) -> frozenset[str]:
    """The S2 values of one family the database admits ahead of the domain right now."""
    if family == "capability":
        return S2_CAPABILITIES - S2_CAPABILITIES_DECLARED_BY_DOMAIN
    return S2_PURPOSES - S2_PURPOSES_DECLARED_BY_DOMAIN
