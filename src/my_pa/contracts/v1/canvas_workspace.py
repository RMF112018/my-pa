"""Public shapes of a canvas workspace overlay.

Two views, one per answer the get/put pair produces. Get returns a stored
overlay or an empty one (version 0, no positions, no timestamp) when nothing
has been saved; put returns a backend-stamped receipt. Models rather than
handler dicts, for the same reason `contracts.v1.capture` gives: the public
answer is a contract.

Positions are a map of entity identifier to a point `{x, y}`. There is no `z`,
scale, or authority field, and a point that carries an extra key is refused.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import AfterValidator, Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "CanvasPointView",
    "CanvasWorkspaceReceiptView",
    "CanvasWorkspaceView",
]


def _finite_number(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a canvas point coordinate must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("a canvas point coordinate must be finite")
    return number


FiniteNumber = Annotated[float, AfterValidator(_finite_number)]


class CanvasPointView(StrictModel):
    """One overlay point: numeric `x`/`y` only."""

    x: FiniteNumber
    y: FiniteNumber


def _require_workspace_subject(focus_entity_id: str | None, scope_entity_id: str | None) -> None:
    if focus_entity_id is None and scope_entity_id is None:
        raise ValueError("at least one of focus_entity_id and scope_entity_id is required")
    if focus_entity_id is not None:
        validate_identifier(focus_entity_id, IdKind.ENTITY)
    if scope_entity_id is not None:
        validate_identifier(scope_entity_id, IdKind.ENTITY)


def _check_positions(positions: dict[str, CanvasPointView]) -> None:
    for entity_id in positions:
        validate_identifier(entity_id, IdKind.ENTITY)


class CanvasWorkspaceView(StrictModel):
    """Get success: a stored overlay, or an empty overlay when none exists."""

    focus_entity_id: str | None
    scope_entity_id: str | None
    version: int = Field(ge=0)
    positions: dict[str, CanvasPointView]
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> CanvasWorkspaceView:
        _require_workspace_subject(self.focus_entity_id, self.scope_entity_id)
        _check_positions(self.positions)
        return self


class CanvasWorkspaceReceiptView(StrictModel):
    """Put success: backend-stamped overlay; `updated_at` is never omitted."""

    focus_entity_id: str | None
    scope_entity_id: str | None
    version: int = Field(ge=0)
    positions: dict[str, CanvasPointView]
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> CanvasWorkspaceReceiptView:
        _require_workspace_subject(self.focus_entity_id, self.scope_entity_id)
        _check_positions(self.positions)
        return self
