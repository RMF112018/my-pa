"""Responsibility handoff holders and the chain rule, record lineage S2 contract section 3.4.

Pure. A handoff moves the next management action on one Commitment, within one
Issue, from one holder to another. The request names only the side the
responsibility leaves (`HandoffSide`); `resolve_handoff` resolves both holders
so a client never supplies an Entity or Principal identifier (R2-F02):

* the **leaving** holder is, for event 1, the Principal or the Commitment's
  current counterparty, as `side` says; for event `n > 1` it is the chain's
  last holder (event `n - 1`'s arriving holder), and `side` must name that
  holder's side, else `HandoffSideError` (`invalid_request` / `from`);
* the **arriving** holder is the Principal when the leaving one is an Entity,
  and the Commitment's **current** counterparty when the leaving one is the
  Principal.

So a counterparty re-pointed from P1 to P1' never wedges the chain: with P1
holding, the next event records P1 -> Principal; with the Principal holding,
Principal -> P1'. A former counterparty can only ever leave.

**S3** (`docs/architecture/record-lineage-s3-contract.md` section 3.3) adds
append-only corrections: a `retime` gives an event a new *current effective
time*; a `void` says it did not happen and is terminal. An event is **live**
when no `void` of it is known. `chain_state` folds an event's known corrections
(in `correction_no` order); the chain then **skips voided events**:
`last_live` is the event the next handoff follows (its arriving holder leaves,
and the new event is effective at or after its current effective time), and
`None` means the S2 event-1 rule applies. Only the last live event can be
voided (`can_void`), and a retime must stay at or after the Commitment's
creation and the previous live event, and at or before the next live event
and its own recording (`retime_in_order`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from my_pa.domain.lineage.vocabulary import (
    HandoffCorrectionAction,
    HandoffHolderKind,
    HandoffSide,
)

__all__ = [
    "ChainEvent",
    "HandoffCorrectionFact",
    "HandoffHolder",
    "HandoffSideError",
    "can_void",
    "chain_state",
    "last_live",
    "resolve_handoff",
    "retime_in_order",
]


class HandoffSideError(ValueError):
    """The request named a side the chain's last holder is not on."""


@dataclass(frozen=True, slots=True)
class HandoffHolder:
    """One holder: the Principal (`entity_id` `None`) or one Entity."""

    kind: HandoffHolderKind
    entity_id: str | None = None

    def __post_init__(self) -> None:
        if (self.kind is HandoffHolderKind.PRINCIPAL) is not (self.entity_id is None):
            raise ValueError("a Principal holder names no Entity; an Entity holder names one")

    @property
    def side(self) -> HandoffSide:
        """The request side this holder is on."""
        return (
            HandoffSide.PRINCIPAL
            if self.kind is HandoffHolderKind.PRINCIPAL
            else HandoffSide.COUNTERPARTY
        )


_PRINCIPAL = HandoffHolder(kind=HandoffHolderKind.PRINCIPAL)


def resolve_handoff(
    side: HandoffSide, *, last_holder: HandoffHolder | None, counterparty_entity_id: str
) -> tuple[HandoffHolder, HandoffHolder]:
    """`(leaving, arriving)` for the next event of one chain.

    `last_holder` is event `n - 1`'s arriving holder, or `None` for event 1;
    `counterparty_entity_id` is the Commitment's counterparty now.
    """
    counterparty = HandoffHolder(kind=HandoffHolderKind.ENTITY, entity_id=counterparty_entity_id)
    if last_holder is None:
        leaving = _PRINCIPAL if side is HandoffSide.PRINCIPAL else counterparty
    else:
        if last_holder.side is not side:
            raise HandoffSideError("the chain's last holder is on the other side")
        leaving = last_holder
    arriving = counterparty if leaving.kind is HandoffHolderKind.PRINCIPAL else _PRINCIPAL
    return leaving, arriving


# --- S3: corrections and the chain that skips voided events --------------------


@dataclass(frozen=True, slots=True)
class HandoffCorrectionFact:
    """One known correction of one event: its number, action and retimed instant."""

    correction_no: int
    action: HandoffCorrectionAction
    corrected_effective_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChainEvent:
    """One event of a chain as known at a cut: voided or live, at its current effective time."""

    sequence_no: int
    effective_at: datetime
    voided: bool
    current_effective_at: datetime


def chain_state(
    sequence_no: int, effective_at: datetime, corrections: Sequence[HandoffCorrectionFact]
) -> ChainEvent:
    """Fold one event's known corrections, in `correction_no` order (section 3.3).

    The current effective time is the latest `retime`'s instant, else the
    event's own; any `void` makes the event voided.
    """
    current = effective_at
    voided = False
    for correction in sorted(corrections, key=lambda fact: fact.correction_no):
        if correction.action is HandoffCorrectionAction.VOID:
            voided = True
        elif correction.corrected_effective_at is not None:
            current = correction.corrected_effective_at
    return ChainEvent(
        sequence_no=sequence_no,
        effective_at=effective_at,
        voided=voided,
        current_effective_at=current,
    )


def last_live(events: Sequence[ChainEvent], *, before: int | None = None) -> ChainEvent | None:
    """The live event with the highest `sequence_no` (below `before` when given), or `None`."""
    live = [
        event
        for event in events
        if not event.voided and (before is None or event.sequence_no < before)
    ]
    return max(live, key=lambda event: event.sequence_no, default=None)


def _next_live(events: Sequence[ChainEvent], after: int) -> ChainEvent | None:
    later = [event for event in events if not event.voided and event.sequence_no > after]
    return min(later, key=lambda event: event.sequence_no, default=None)


def can_void(events: Sequence[ChainEvent], sequence_no: int) -> bool:
    """Only the chain's last live event can be voided, so holder continuity holds."""
    last = last_live(events)
    return last is not None and last.sequence_no == sequence_no


def retime_in_order(
    events: Sequence[ChainEvent],
    sequence_no: int,
    effective_at: datetime,
    *,
    commitment_created_at: datetime,
    recorded_at: datetime,
) -> bool:
    """Whether retiming event `sequence_no` to `effective_at` keeps the chain in order.

    At or after the Commitment's creation and the previous live event's
    current effective time; at or before the next live event's and the
    correction's own recording time.
    """
    if effective_at < commitment_created_at or effective_at > recorded_at:
        return False
    previous = last_live(events, before=sequence_no)
    if previous is not None and effective_at < previous.current_effective_at:
        return False
    following = _next_live(events, sequence_no)
    return following is None or effective_at <= following.current_effective_at
