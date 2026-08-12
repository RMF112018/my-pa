"""Fail-closed orchestration for optional model proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from my_pa.domain.modeling.gate import (
    ContextManifest,
    ModelProposal,
    ModelRoutePolicy,
    SemanticRetrievalGate,
)


class StructuredModelProvider(Protocol):
    provider_id: str
    model_id: str
    is_external: bool

    def propose(self, manifest: ContextManifest) -> tuple[ModelProposal, ...]: ...


@dataclass(frozen=True, slots=True)
class ModelGateOutcome:
    state: str
    proposals: tuple[ModelProposal, ...] = ()
    failure_code: str | None = None


class BoundedModelGate:
    """Models can fail or be denied without affecting deterministic state."""

    def __init__(
        self,
        *,
        route: ModelRoutePolicy = ModelRoutePolicy.DISABLED,
        semantic_gate: SemanticRetrievalGate | None = None,
    ) -> None:
        self.route = route
        self.semantic_gate = semantic_gate or SemanticRetrievalGate()

    def invoke(
        self, provider: StructuredModelProvider, manifest: ContextManifest
    ) -> ModelGateOutcome:
        if self.route is ModelRoutePolicy.DISABLED:
            return ModelGateOutcome(state="disabled")
        if provider.provider_id != manifest.provider_id or provider.model_id != manifest.model_id:
            return ModelGateOutcome(state="denied", failure_code="provider_identity_mismatch")
        if provider.is_external and not manifest.external_disclosure_allowed:
            return ModelGateOutcome(state="denied", failure_code="external_disclosure_denied")
        try:
            proposals = provider.propose(manifest)
            allowed = {item.reference_id for item in manifest.evidence}
            if any(not set(proposal.evidence_reference_ids) <= allowed for proposal in proposals):
                return ModelGateOutcome(state="denied", failure_code="unknown_evidence_reference")
            return ModelGateOutcome(state="proposed", proposals=proposals)
        except Exception:
            # Provider errors are deliberately collapsed: source text, prompts,
            # credentials and remote error bodies are not safe diagnostics.
            return ModelGateOutcome(state="unavailable", failure_code="model_unavailable")
