"""What a reviewer may decide about a proposal, and nothing else.

A review case is opened for a proposal whose risk class requires one, and every
decision taken on it is appended rather than written over the last. The case
carries no risk class of its own: `capture_review_cases.proposal_id` is `UNIQUE`
and `NOT NULL`, so the proposal's own `risk_class` is one join away and a second
copy would be two writers for one fact — the rule `capture_processing_text`
states for `transformations` and `capture_submissions` for `registered_client_id`.

**Seven dispositions, from
`docs/specs/quick-capture/12_REVIEW_AND_PROMOTION_POLICY.md:129-135`, and this
build reaches five.** `accept`, `correct_and_accept`, `reject`, `defer` and
`mark_unresolved` each move the proposal to the state of the same name. The other
two cannot be written here, for measured reasons rather than for want of wiring:

- `reprocess` — "under an eligible route", and there is exactly one route. No
  model route exists while `P00-OD-006` is open, the deterministic pipeline is a
  function of the immutable version and the pipeline version, and `QC-AC-035`
  requires a replayed stage to return the prior output. A reprocess under this
  build is provably a no-op, so a disposition that claimed one would record a
  decision that changed nothing.
- `escalate` — "to operator-only decision", and `domain.identity.operation`
  restricts exactly one capability to an operator. Under `P00-OD-010` there is a
  single local principal (`D-72`), so there is no non-operator to escalate *from*.

**Declaring the two rather than omitting them is safe here, and it is not safe
everywhere.** `ProposalState` is treated the same way and `ProposalMethod`
deliberately is not: an unwritable `cloud_model` method would let a model output
be filed as deterministic, which is a laundering path, whereas an unwritable
`escalate` cannot launder anything — it is a decision nobody can record, not a
provenance nobody can check. The set is the instrument's own vocabulary of one
act, and a later package that reaches one of them must not have to widen a
frozen constraint to say so.

`O-16` (review thresholds by risk and consequence) and `O-17` remain open
operator decisions. This module implements the specification's recommendation
and the plan discloses that the decisions are unresolved; a green test is not an
operator resolution.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Disposition"]


class Disposition(StrEnum):
    """The seven a reviewer may take. Five are reachable; see the module docstring."""

    ACCEPT = "accept"
    CORRECT_AND_ACCEPT = "correct_and_accept"
    REJECT = "reject"
    DEFER = "defer"
    MARK_UNRESOLVED = "mark_unresolved"
    REPROCESS = "reprocess"
    ESCALATE = "escalate"
