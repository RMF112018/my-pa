"""Dormant GoodNotes Durable Note Ingestion rollout gates (WP-15).

Process-local flags, all default off, plus one explicit ordered stage. This
module **reads** them and resolves the single current stage the durable-note
orchestrator may consume. It does not ingest, write notes, deliver, call
Abacus, mutate NAS, or touch the TBR Task.

`bootstrap.goodnotes` (bounded OCR/review) and `bootstrap.goodnotes_tbr`
(GN-09 contract) do not read these flags. Turning every gate off leaves those
paths unchanged. Semantic Agent work dispatch reuses
`goodnotes_durable_note_intelligence_enabled`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from my_pa.bootstrap.settings import GoodNotesRolloutStage, Settings

__all__ = [
    "ACTIVATION_STEPS",
    "PILOT_ACTIVATED",
    "PRODUCTION_ACTIVATED",
    "GoodNotesRolloutGates",
    "RolloutStageError",
    "allowed_activation_steps",
    "current_rollout_stage",
    "rollout_gates",
    "rollout_report",
]

PRODUCTION_ACTIVATED: Final = False
PILOT_ACTIVATED: Final = False

ACTIVATION_STEPS: Final[tuple[str, ...]] = tuple(member.value for member in GoodNotesRolloutStage)

# ingestion, intelligence, canonical writes, user-facing delivery, TBR.
_REQUIRED_PREFIX: Final[dict[GoodNotesRolloutStage, tuple[bool, bool, bool, bool, bool]]] = {
    GoodNotesRolloutStage.OBSERVE_ONLY: (False, False, False, False, False),
    GoodNotesRolloutStage.PAGE_IDENTITY_DRY_RUN: (False, False, False, False, False),
    GoodNotesRolloutStage.SEMANTIC_PROPOSALS_WITHOUT_CANONICAL_NOTE_WRITES: (
        False,
        True,
        False,
        False,
        False,
    ),
    GoodNotesRolloutStage.CANONICAL_WRITES_WITH_DELIVERY_DISABLED: (
        False,
        True,
        True,
        False,
        False,
    ),
    GoodNotesRolloutStage.NEW_ONLY_SUMMARY_PREVIEW: (False, True, True, False, False),
    GoodNotesRolloutStage.OPERATOR_REVIEWED_DELIVERY_CANARY: (False, True, True, True, False),
    GoodNotesRolloutStage.BOUNDED_SCHEDULED_OPERATION: (True, True, True, True, False),
    GoodNotesRolloutStage.OPTIONAL_TBR_BRIDGE: (True, True, True, True, True),
}


class RolloutStageError(ValueError):
    """Impossible or unauthorized rollout combination. Nothing was activated."""


@dataclass(frozen=True, slots=True)
class GoodNotesRolloutGates:
    """The six separable WP-15 gates as this process currently reads them."""

    durable_note_ingestion: bool
    semantic_agent_work_dispatch: bool
    canonical_semantic_writes: bool
    user_facing_summary_delivery: bool
    optional_tbr_bridge: bool
    optional_self_improving_optimizer: bool


def rollout_gates(settings: Settings) -> GoodNotesRolloutGates:
    """Read the six gates. Does not activate any of them."""
    return GoodNotesRolloutGates(
        durable_note_ingestion=settings.goodnotes_durable_note_ingestion_enabled,
        semantic_agent_work_dispatch=settings.goodnotes_durable_note_intelligence_enabled,
        canonical_semantic_writes=settings.goodnotes_canonical_semantic_writes_enabled,
        user_facing_summary_delivery=settings.goodnotes_user_facing_summary_delivery_enabled,
        optional_tbr_bridge=settings.goodnotes_tbr_bridge_enabled,
        optional_self_improving_optimizer=settings.goodnotes_self_improving_optimizer_enabled,
    )


def current_rollout_stage(settings: Settings) -> GoodNotesRolloutStage:
    """The one current stage, or fail closed.

    Boolean gates must be the consistent prefix for the selected stage. A later
    or out-of-order flag does not silently drop to a lower stage. Representing
    or enabling the optional TBR bridge is unauthorized. This function does not
    ingest, write, deliver, call Abacus, or mutate TBR.
    """
    if PRODUCTION_ACTIVATED or PILOT_ACTIVATED:
        raise RolloutStageError("pilot and production stay off")
    gates = rollout_gates(settings)
    stage = settings.goodnotes_rollout_stage
    if stage is GoodNotesRolloutStage.OPTIONAL_TBR_BRIDGE or gates.optional_tbr_bridge:
        raise RolloutStageError("optional TBR bridge is unauthorized")
    actual = (
        gates.durable_note_ingestion,
        gates.semantic_agent_work_dispatch,
        gates.canonical_semantic_writes,
        gates.user_facing_summary_delivery,
        gates.optional_tbr_bridge,
    )
    if actual != _REQUIRED_PREFIX[stage]:
        raise RolloutStageError("rollout flags are not a consistent prefix for the selected stage")
    return stage


def allowed_activation_steps(settings: Settings) -> tuple[str, ...]:
    """The one current stage as a tuple, or empty when the combination fails closed.

    Out-of-order later flags fail closed: they do not unlock a live step.
    The optional Self-Improving optimizer is reported separately and does not
    advance this sequence. This function does not ingest, write, deliver, or
    call Abacus.
    """
    try:
        return (current_rollout_stage(settings).value,)
    except RolloutStageError:
        return ()


def rollout_report(settings: Settings) -> dict[str, object]:
    """Operator-facing dry-run view of the current flags.

    Always reports that this helper itself does not ingest, write notes,
    deliver, or call Abacus. Live transitions remain operator-gated.
    """
    gates = rollout_gates(settings)
    allowed = list(allowed_activation_steps(settings))
    return {
        "production_activated": PRODUCTION_ACTIVATED,
        "pilot_activated": PILOT_ACTIVATED,
        "live_transition_operator_gated": True,
        "gates": {
            "goodnotes_durable_note_ingestion_enabled": gates.durable_note_ingestion,
            "goodnotes_durable_note_intelligence_enabled": gates.semantic_agent_work_dispatch,
            "goodnotes_canonical_semantic_writes_enabled": gates.canonical_semantic_writes,
            "goodnotes_user_facing_summary_delivery_enabled": gates.user_facing_summary_delivery,
            "goodnotes_tbr_bridge_enabled": gates.optional_tbr_bridge,
            "goodnotes_self_improving_optimizer_enabled": gates.optional_self_improving_optimizer,
        },
        "goodnotes_rollout_stage": settings.goodnotes_rollout_stage.value,
        "current_stage": allowed[0] if allowed else None,
        "allowed_activation_steps": allowed,
        "ingests": False,
        "writes_canonical_notes": False,
        "delivers": False,
        "calls_abacus": False,
    }
