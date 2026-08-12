"""Fail-closed orchestration for optional model proposals."""

from __future__ import annotations

import hashlib
import multiprocessing
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Protocol, cast

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
        provider: StructuredModelProvider | None = None,
        review_router: CanonicalModelReviewRouter | None = None,
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
        if route is not ModelRoutePolicy.DISABLED and (provider is None or review_router is None):
            raise ValueError(
                "an enabled model route requires its provider and canonical Review route"
            )
        self.provider = provider
        self.review_router = review_router
        self.semantic_gate = semantic_gate or SemanticRetrievalGate()
        self.timeout_seconds = timeout_seconds
        self.maximum_proposals = maximum_proposals
        self.maximum_aggregate_bytes = maximum_aggregate_bytes

    def invoke(
        self,
        manifest: ContextManifest,
    ) -> ModelGateOutcome:
        if self.route is ModelRoutePolicy.DISABLED:
            return ModelGateOutcome(state="disabled")
        provider = self.provider
        review_router = self.review_router
        if provider is None or review_router is None:
            return ModelGateOutcome(state="denied", failure_code="model_route_not_composed")
        if provider.provider_id != manifest.provider_id or provider.model_id != manifest.model_id:
            return ModelGateOutcome(state="denied", failure_code="provider_identity_mismatch")
        # This route is intentionally local-only. A manifest disclosure flag is
        # evidence for a future external route, not authority to widen this one.
        if provider.is_external:
            return ModelGateOutcome(state="denied", failure_code="external_disclosure_denied")
        deadline = time.monotonic() + self.timeout_seconds
        state, value = _run_killable(
            _provider_worker,
            (provider, manifest, self.maximum_proposals, self.maximum_aggregate_bytes),
            self.timeout_seconds,
        )
        if state == "timeout":
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
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return ModelGateOutcome(state="unavailable", failure_code="model_timeout")
        state, routed = _run_killable(_router_worker, (review_router, review_bound), remaining)
        if state == "timeout":
            return ModelGateOutcome(state="unavailable", failure_code="review_route_timeout")
        if state != "ok" or not isinstance(routed, tuple):
            return ModelGateOutcome(state="unavailable", failure_code="review_route_unavailable")
        if len(routed) != len(review_bound) or any(
            reference.proposal_id != proposal.proposal_id
            or reference.review_case_id != proposal.review_case_id
            for reference, proposal in zip(routed, review_bound, strict=True)
        ):
            return ModelGateOutcome(state="denied", failure_code="review_route_mismatch")
        return ModelGateOutcome(state="proposed", proposals=routed)


def _run_killable(
    target: Callable[..., None],
    arguments: tuple[object, ...],
    timeout_seconds: float,
) -> tuple[str, object]:
    """Run external/model work in a process that can be forcibly reaped."""
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(*arguments, sender))
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            return ("timeout", ())
        return cast(tuple[str, object], receiver.recv())
    except (EOFError, OSError):
        return ("unavailable", ())
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)


def _provider_worker(
    provider: StructuredModelProvider,
    manifest: ContextManifest,
    maximum_proposals: int,
    maximum_aggregate_bytes: int,
    sender: Connection,
) -> None:
    try:
        proposals: list[ModelProposal] = []
        aggregate_bytes = 0
        for proposal in provider.propose(manifest):
            if not isinstance(proposal, ModelProposal):
                raise ValueError("model output is not a structured proposal")
            proposals.append(proposal)
            aggregate_bytes += _proposal_bytes(proposal)
            if len(proposals) > maximum_proposals or aggregate_bytes > maximum_aggregate_bytes:
                sender.send(("exceeded", ()))
                return
        sender.send(("ok", tuple(proposals)))
    except Exception:
        sender.send(("unavailable", ()))
    finally:
        sender.close()


def _router_worker(
    router: CanonicalModelReviewRouter,
    proposals: tuple[ReviewBoundModelProposal, ...],
    sender: Connection,
) -> None:
    try:
        sender.send(("ok", router.route(proposals)))
    except Exception:
        sender.send(("unavailable", ()))
    finally:
        sender.close()


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
