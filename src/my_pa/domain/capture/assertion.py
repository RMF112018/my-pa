"""The accepted record a promotion writes, and the states it can hold.

An assertion is what a proposal becomes when a reviewer accepts it. It is the
first canonical record this build produces, and its existence is what makes
`QC-AC-035`'s "or accepted objects" clause non-vacuous — that clause discharged
over an empty set until now, because nothing in `src/` wrote an accepted record.

**Seven states, from
`docs/specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:95`.**
That is the `Assertion` row of the canonical state patterns, and it is not the
`Identity` row on the line below it, which carries a different six.

Five are reachable in this build: `accepted` on promotion, `superseded` when a
later assertion replaces this one, `revalidation_required` when a capture edit
moves a span an accepted record cites (ADR-003 clause 8, and
`docs/specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:107`),
`contradicted` when a second assertion asserts the opposite, and `withdrawn`
when the reviewer takes the acceptance back. `proposed` and `stale` are not:
a proposal that has not been accepted is a `Proposal` and has its own table and
its own `proposed` state, so an assertion in `proposed` would be the same claim
recorded twice under two authorities; and `stale` needs a freshness horizon,
which no specification in this repository sets and no operator decision has
chosen. They are declared rather than omitted for `ProposalState`'s reason —
the set is the canonical vocabulary of one object rather than a list of what
this package happens to write.

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

from enum import StrEnum
from typing import Final

__all__ = ["ACCEPTED_RECORD_TYPE", "AssertionState"]

#: What `capture_proposals.accepted_record_type` holds when an acceptance names
#: an assertion. A bare string rather than a one-member enum: a closed set of one
#: would become a live closed set the `D-81` guard keys by value, and this names
#: a table rather than enumerating a vocabulary. The revision that installs the
#: constraint trigger writes the literal out for itself, so the two are compared
#: rather than shared.
ACCEPTED_RECORD_TYPE: Final = "assertion"


class AssertionState(StrEnum):
    """The canonical seven. Five are reachable here; see the module docstring."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    CONTRADICTED = "contradicted"
    STALE = "stale"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    REVALIDATION_REQUIRED = "revalidation_required"
