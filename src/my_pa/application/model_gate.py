"""Fail-closed production gate for deferred model and semantic retrieval paths.

The repository has no durable canonical Review router or admitted local model
provider. Keeping an executable provider abstraction here would be dead code and
would falsely imply that model proposals can run. The integrated production gate
therefore has one state: disabled. Structured proposal/provenance contracts stay
in the domain for a future separately authorized implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.domain.modeling.gate import ModelRoutePolicy, SemanticRetrievalGate


@dataclass(frozen=True, slots=True)
class ModelGateOutcome:
    state: str
    failure_code: str | None = None


class BoundedModelGate:
    """An integrated non-execution boundary until real Review routing exists."""

    def __init__(
        self,
        *,
        route: ModelRoutePolicy = ModelRoutePolicy.DISABLED,
        semantic_gate: SemanticRetrievalGate | None = None,
    ) -> None:
        if route is not ModelRoutePolicy.DISABLED:
            raise ValueError(
                "model proposals are deferred until a production local provider and "
                "durable canonical Review router exist"
            )
        self.route = route
        self.semantic_gate = semantic_gate or SemanticRetrievalGate()
        if self.semantic_gate.enabled:
            raise ValueError("semantic retrieval has no production implementation")

    def invoke(self) -> ModelGateOutcome:
        """Refuse without receiving content, a provider, or a persistence port."""
        return ModelGateOutcome(state="disabled", failure_code="model_route_deferred")
