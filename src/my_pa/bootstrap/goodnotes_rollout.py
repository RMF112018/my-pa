"""Dormant GoodNotes Durable Note Ingestion rollout gates (WP-15).

Process-local flags, all default off. This module **reads** them and reports
which documented activation step the current combination would permit. It does
not ingest, write notes, deliver, call Abacus, mutate NAS, or touch the TBR
Task.

`bootstrap.goodnotes` (bounded OCR/review) and `bootstrap.goodnotes_tbr`
(GN-09 contract) do not read these flags. Turning every gate off leaves those
paths unchanged. Semantic Agent work dispatch reuses
`goodnotes_durable_note_intelligence_enabled`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from my_pa.bootstrap.settings import Settings

__all__ = [
    "ACTIVATION_STEPS",
    "PILOT_ACTIVATED",
    "PRODUCTION_ACTIVATED",
    "GoodNotesRolloutGates",
    "allowed_activation_steps",
    "rollout_gates",
    "rollout_report",
]

PRODUCTION_ACTIVATED: Final = False
PILOT_ACTIVATED: Final = False

ACTIVATION_STEPS: Final[tuple[str, ...]] = (
    "observe-only",
    "page-identity-dry-run",
    "semantic-proposals-without-canonical-note-writes",
    "canonical-writes-with-delivery-disabled",
    "new-only-summary-preview",
    "operator-reviewed-delivery-canary",
    "bounded-scheduled-operation",
    "optional-tbr-bridge",
)


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


def allowed_activation_steps(settings: Settings) -> tuple[str, ...]:
    """Which documented steps the current flags would permit.

    Out-of-order later flags fail closed: they do not unlock a live step.
    The optional Self-Improving optimizer is reported separately and does not
    advance this sequence. This function does not ingest, write, deliver, or
    call Abacus.
    """
    if PRODUCTION_ACTIVATED or PILOT_ACTIVATED:
        return ()
    gates = rollout_gates(settings)
    sequence = (
        gates.durable_note_ingestion,
        gates.semantic_agent_work_dispatch,
        gates.canonical_semantic_writes,
        gates.user_facing_summary_delivery,
        gates.optional_tbr_bridge,
    )
    if not any(sequence):
        return ("observe-only", "page-identity-dry-run")
    if (
        gates.semantic_agent_work_dispatch
        and not gates.canonical_semantic_writes
        and not gates.user_facing_summary_delivery
        and not gates.durable_note_ingestion
        and not gates.optional_tbr_bridge
    ):
        return ("semantic-proposals-without-canonical-note-writes",)
    if (
        gates.semantic_agent_work_dispatch
        and gates.canonical_semantic_writes
        and not gates.user_facing_summary_delivery
        and not gates.durable_note_ingestion
        and not gates.optional_tbr_bridge
    ):
        return (
            "canonical-writes-with-delivery-disabled",
            "new-only-summary-preview",
        )
    if (
        gates.semantic_agent_work_dispatch
        and gates.canonical_semantic_writes
        and gates.user_facing_summary_delivery
        and not gates.durable_note_ingestion
        and not gates.optional_tbr_bridge
    ):
        return ("operator-reviewed-delivery-canary",)
    if (
        gates.durable_note_ingestion
        and gates.semantic_agent_work_dispatch
        and gates.canonical_semantic_writes
        and gates.user_facing_summary_delivery
        and not gates.optional_tbr_bridge
    ):
        return ("bounded-scheduled-operation",)
    if (
        gates.durable_note_ingestion
        and gates.semantic_agent_work_dispatch
        and gates.canonical_semantic_writes
        and gates.user_facing_summary_delivery
        and gates.optional_tbr_bridge
    ):
        return ("optional-tbr-bridge",)
    return ()


def rollout_report(settings: Settings) -> dict[str, object]:
    """Operator-facing dry-run view of the current flags.

    Always reports that this helper itself does not ingest, write notes,
    deliver, or call Abacus. Live transitions remain operator-gated.
    """
    gates = rollout_gates(settings)
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
        "allowed_activation_steps": list(allowed_activation_steps(settings)),
        "ingests": False,
        "writes_canonical_notes": False,
        "delivers": False,
        "calls_abacus": False,
    }
