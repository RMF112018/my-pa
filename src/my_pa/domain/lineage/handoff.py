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
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.domain.lineage.vocabulary import HandoffHolderKind, HandoffSide

__all__ = ["HandoffHolder", "HandoffSideError", "resolve_handoff"]


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
