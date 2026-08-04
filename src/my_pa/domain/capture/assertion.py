"""The accepted record a promotion writes, and the states it can hold.

An assertion is what a proposal becomes when a reviewer accepts it. It is the
first canonical record this build produces, and its existence is what makes
`QC-AC-035`'s "or accepted objects" clause non-vacuous — that clause discharged
over an empty set until now, because nothing in `src/` wrote an accepted record.

**Seven states, from
`docs/specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:95`.**
That is the `Assertion` row of the canonical state patterns, and it is not the
`Identity` row on the line below it, which carries a different six.

Two are reachable in this build: `accepted` on promotion and
`revalidation_required` when a capture edit moves a span an accepted record
cites (ADR-003 clause 8, and
`docs/specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:107`). No
writer supersedes, contradicts, or withdraws an assertion in this build, and
acceptance is terminal for its review case. `proposed` is also unwritten because
an unaccepted candidate is a `Proposal`, while `stale` needs a freshness horizon
that no specification or operator decision sets. The other five states remain
declared because this is the canonical vocabulary of the object, not a claim
that this package can write them.

**A corrected accept does not overwrite the proposal.** The corrected value is
this record's `normalized_value` while the proposal keeps its own and moves to
`corrected_accepted`, so the two differ visibly and the lineage `QC-AC-022`
protects survives. There is no separate correction record: of the four
correction kinds
`docs/specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:148`
names, this build reaches exactly one — a derived value — and a four-kind table
three of whose kinds nothing can write is the permanently-empty-column defect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.proposal import ProposalType
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = ["ACCEPTED_RECORD_TYPE", "Assertion", "AssertionState", "PromotionReceipt"]

#: What `capture_proposals.accepted_record_type` holds when an acceptance names
#: an assertion. A bare string rather than a one-member enum: a closed set of one
#: would become a live closed set the `D-81` guard keys by value, and this names
#: a table rather than enumerating a vocabulary. The revision that installs the
#: constraint trigger writes the literal out for itself, so the two are compared
#: rather than shared.
ACCEPTED_RECORD_TYPE: Final = "assertion"


class AssertionState(StrEnum):
    """The canonical seven. Two are reachable here; see the module docstring."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    CONTRADICTED = "contradicted"
    STALE = "stale"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    REVALIDATION_REQUIRED = "revalidation_required"


@dataclass(frozen=True, slots=True)
class Assertion:
    """A canonical claim promoted from exactly one reviewed proposal."""

    assertion_id: str
    version_id: str
    proposal_id: str
    decision_id: str
    assertion_type: ProposalType
    state: AssertionState
    accepted_at: datetime
    normalized_value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value, kind in (
            (self.assertion_id, IdKind.ASSERTION),
            (self.version_id, IdKind.CAPTURE_VERSION),
            (self.proposal_id, IdKind.PROPOSAL),
            (self.decision_id, IdKind.REVIEW_DECISION),
        ):
            validate_identifier(value, kind)
        ensure_utc(self.accepted_at)


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    """Safe evidence that one reviewed proposal became an assertion."""

    receipt_id: str
    assertion_id: str
    decision_id: str
    policy_version: str
    issued_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.RECEIPT)
        validate_identifier(self.assertion_id, IdKind.ASSERTION)
        validate_identifier(self.decision_id, IdKind.REVIEW_DECISION)
        ensure_utc(self.issued_at)
