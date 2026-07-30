"""Building the capability manifest and readiness report.

Phase 01 delivers contracts, not behavior. Every capability is therefore
reported `not_implemented` and readiness is `contracts_only`. These functions
derive that state from the contract itself rather than restating it, so the
manifest cannot drift from the capability set or overstate what exists.
"""

from __future__ import annotations

from my_pa.contracts.v1.capabilities import (
    Availability,
    CapabilityManifest,
    CapabilityStatus,
    ContentTypeStatus,
    EffectiveLimits,
    ReadinessReport,
    ReadinessState,
)
from my_pa.domain.identity.operation import Capability, is_operator_only

__all__ = ["PHASE_01_LIMITS", "build_capability_manifest", "build_readiness_report"]

#: Limits published by Phase 01. They bound the contract, not a running backend.
PHASE_01_LIMITS = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)

#: Media types named by the MCV contract. Markdown and plain text are the
#: mandatory baseline; PDF stays decision-gated until `P00-OD-003` is resolved.
_CONTENT_TYPES: tuple[ContentTypeStatus, ...] = (
    ContentTypeStatus(media_type="text/plain", availability=Availability.NOT_IMPLEMENTED),
    ContentTypeStatus(media_type="text/markdown", availability=Availability.NOT_IMPLEMENTED),
    ContentTypeStatus(media_type="application/pdf", availability=Availability.DECISION_GATED),
)


def build_capability_manifest() -> CapabilityManifest:
    """Return the manifest for the current build."""
    return CapabilityManifest(
        capabilities=tuple(
            CapabilityStatus(
                name=capability,
                availability=Availability.NOT_IMPLEMENTED,
                operator_only=is_operator_only(capability),
            )
            for capability in Capability
        ),
        content_types=_CONTENT_TYPES,
        limits=PHASE_01_LIMITS,
    )


def build_readiness_report(manifest: CapabilityManifest | None = None) -> ReadinessReport:
    """Return readiness derived from `manifest`.

    Counting the manifest rather than asserting a state means the report cannot
    claim readiness the manifest does not support.
    """
    resolved = manifest if manifest is not None else build_capability_manifest()
    implemented = sum(
        1 for status in resolved.capabilities if status.availability is Availability.AVAILABLE
    )
    if implemented == 0:
        state = ReadinessState.CONTRACTS_ONLY
    elif implemented == len(resolved.capabilities):
        state = ReadinessState.READY
    else:
        state = ReadinessState.DEGRADED
    return ReadinessReport(
        state=state,
        implemented_capabilities=implemented,
        limitations=(
            "Phase 01 delivers contracts, policy, identity, and audit primitives only.",
            "No transport, persistence, provider, extraction, or search behavior exists.",
        ),
    )
