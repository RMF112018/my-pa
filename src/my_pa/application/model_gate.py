"""Fail-closed orchestration for optional model proposals."""

from __future__ import annotations

import hashlib
import queue
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, make_identifier, validate_identifier
from my_pa.domain.modeling.gate import (
    ContextManifest,
    ModelProposal,
    ModelRoutePolicy,
    ReviewBoundModelProposal,
    SemanticRetrievalGate,
)


class StructuredModelProvider(Protocol):
    provider_id: str
    model_id: str
    is_external: bool

    def propose(self, manifest: ContextManifest) -> Iterable[ModelProposal]: ...


@dataclass(frozen=True, slots=True)
class CanonicalReviewReference:
    proposal_id: str
    review_case_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)


class CanonicalModelReviewRouter(Protocol):
    """Durably retain model proposals in the existing canonical Review plane."""

    def route(
        self, proposals: tuple[ReviewBoundModelProposal, ...]
    ) -> tuple[CanonicalReviewReference, ...]: ...


@dataclass(frozen=True, slots=True)
class ModelGateOutcome:
    state: str
    proposals: tuple[CanonicalReviewReference, ...] = ()
    failure_code: str | None = None


class BoundedModelGate:
    """Models can fail or be denied without affecting deterministic state."""

    def __init__(
        self,
        *,
        route: ModelRoutePolicy = ModelRoutePolicy.DISABLED,
        semantic_gate: SemanticRetrievalGate | None = None,
        timeout_seconds: float = 30.0,
        maximum_proposals: int = 50,
        maximum_aggregate_bytes: int = 65_536,
    ) -> None:
        if not 0.01 <= timeout_seconds <= 60:
            raise ValueError("model timeout is outside its bound")
        if not 1 <= maximum_proposals <= 100:
            raise ValueError("model proposal count is outside its bound")
        if not 1 <= maximum_aggregate_bytes <= 1_048_576:
            raise ValueError("model proposal bytes are outside their bound")
        self.route = route
        self.semantic_gate = semantic_gate or SemanticRetrievalGate()
        self.timeout_seconds = timeout_seconds
        self.maximum_proposals = maximum_proposals
        self.maximum_aggregate_bytes = maximum_aggregate_bytes

    def invoke(
        self,
        provider: StructuredModelProvider,
        manifest: ContextManifest,
        *,
        review_router: CanonicalModelReviewRouter | None = None,
    ) -> ModelGateOutcome:
        if self.route is ModelRoutePolicy.DISABLED:
            return ModelGateOutcome(state="disabled")
        if provider.provider_id != manifest.provider_id or provider.model_id != manifest.model_id:
            return ModelGateOutcome(state="denied", failure_code="provider_identity_mismatch")
        if provider.is_external and not manifest.external_disclosure_allowed:
            return ModelGateOutcome(state="denied", failure_code="external_disclosure_denied")
        if review_router is None:
            # Model outputs are never returned as free-floating values. Until a
            # caller supplies the existing canonical Review persistence route,
            # the optional model path is disabled before provider invocation.
            return ModelGateOutcome(
                state="denied", failure_code="canonical_review_route_unavailable"
            )
        result: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def invoke_bounded() -> None:
            try:
                proposals: list[ModelProposal] = []
                aggregate_bytes = 0
                for proposal in provider.propose(manifest):
                    if not isinstance(proposal, ModelProposal):
                        raise ValueError("model output is not a structured proposal")
                    proposals.append(proposal)
                    aggregate_bytes += _proposal_bytes(proposal)
                    if (
                        len(proposals) > self.maximum_proposals
                        or aggregate_bytes > self.maximum_aggregate_bytes
                    ):
                        result.put_nowait(("exceeded", ()))
                        return
                result.put_nowait(("ok", tuple(proposals)))
            except Exception:
                # Provider errors are deliberately collapsed: source text,
                # prompts and remote error bodies are not safe diagnostics.
                result.put_nowait(("unavailable", ()))

        threading.Thread(target=invoke_bounded, daemon=True).start()
        try:
            state, value = result.get(timeout=self.timeout_seconds)
        except queue.Empty:
            return ModelGateOutcome(state="unavailable", failure_code="model_timeout")
        if state == "exceeded":
            return ModelGateOutcome(state="denied", failure_code="model_output_exceeded")
        if state != "ok":
            # Provider errors are deliberately collapsed: source text, prompts,
            # credentials and remote error bodies are not safe diagnostics.
            return ModelGateOutcome(state="unavailable", failure_code="model_unavailable")
        proposals = value
        if not isinstance(proposals, tuple):
            return ModelGateOutcome(state="denied", failure_code="model_output_exceeded")
        allowed = {item.reference_id for item in manifest.evidence}
        if any(not set(proposal.evidence_reference_ids) <= allowed for proposal in proposals):
            return ModelGateOutcome(state="denied", failure_code="unknown_evidence_reference")
        review_bound = tuple(
            _review_bound(manifest, provider, proposal, ordinal)
            for ordinal, proposal in enumerate(proposals)
        )
        try:
            routed = review_router.route(review_bound)
        except Exception:
            return ModelGateOutcome(state="unavailable", failure_code="review_route_unavailable")
        if len(routed) != len(review_bound) or any(
            reference.proposal_id != proposal.proposal_id
            or reference.review_case_id != proposal.review_case_id
            for reference, proposal in zip(routed, review_bound, strict=True)
        ):
            return ModelGateOutcome(state="denied", failure_code="review_route_mismatch")
        return ModelGateOutcome(state="proposed", proposals=routed)


def _proposal_bytes(proposal: ModelProposal) -> int:
    return sum(
        len(value.encode())
        for value in (
            proposal.proposal_type,
            proposal.normalized_value,
            *proposal.evidence_reference_ids,
        )
    )


def _review_bound(
    manifest: ContextManifest,
    provider: StructuredModelProvider,
    proposal: ModelProposal,
    ordinal: int,
) -> ReviewBoundModelProposal:
    material = "\x1f".join(
        (
            manifest.principal_id,
            provider.provider_id,
            provider.model_id,
            manifest.prompt_schema_version,
            manifest.policy_version,
            str(ordinal),
            proposal.proposal_type,
            proposal.normalized_value,
            *proposal.evidence_reference_ids,
        )
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:24]
    return ReviewBoundModelProposal(
        proposal_id=make_identifier(IdKind.PROPOSAL, digest),
        review_case_id=make_identifier(
            IdKind.REVIEW_CASE,
            hashlib.sha256(f"review\x1f{material}".encode()).hexdigest()[:24],
        ),
        principal_id=manifest.principal_id,
        provider_id=provider.provider_id,
        model_id=provider.model_id,
        prompt_schema_version=manifest.prompt_schema_version,
        policy_version=manifest.policy_version,
        proposal=proposal,
    )
