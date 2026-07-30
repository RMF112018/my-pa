"""The capability manifest and readiness states.

`capabilities.get` reports what the interface supports and the limits that apply,
without internal topology, library names, paths, hosts, or database detail
(`docs/specs`, section 9.1).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import CONTRACT_VERSION, StrictModel
from my_pa.domain.identity.operation import Capability, is_operator_only

__all__ = [
    "Availability",
    "CapabilityManifest",
    "CapabilityStatus",
    "ContentTypeStatus",
    "EffectiveLimits",
    "ReadinessReport",
    "ReadinessState",
]


class Availability(StrEnum):
    """Whether a capability or media type can be used right now."""

    AVAILABLE = "available"
    DECISION_GATED = "decision_gated"
    UNAVAILABLE = "unavailable"
    NOT_IMPLEMENTED = "not_implemented"


class ReadinessState(StrEnum):
    """Truthful readiness of the running deployment."""

    NOT_IMPLEMENTED = "not_implemented"
    CONTRACTS_ONLY = "contracts_only"
    DEGRADED = "degraded"
    READY = "ready"


class CapabilityStatus(StrictModel):
    """Availability of one public capability."""

    name: Capability
    version: str = CONTRACT_VERSION
    availability: Availability
    operator_only: bool

    @model_validator(mode="after")
    def _check(self) -> CapabilityStatus:
        if self.operator_only != is_operator_only(self.name):
            raise ValueError(f"operator_only for {self.name} contradicts the domain rule")
        return self


class ContentTypeStatus(StrictModel):
    """Availability of one media type."""

    media_type: str = Field(min_length=1, max_length=128)
    availability: Availability


class EffectiveLimits(StrictModel):
    """Limits a caller can rely on. Values are policy-bounded, not advisory."""

    max_page_size: int = Field(gt=0, le=1000)
    default_page_size: int = Field(gt=0, le=1000)
    max_fetch_bytes: int = Field(gt=0)
    max_enrollment_depth: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> EffectiveLimits:
        if self.default_page_size > self.max_page_size:
            raise ValueError("default_page_size cannot exceed max_page_size")
        return self


class CapabilityManifest(StrictModel):
    """The fixed v1 manifest.

    Every capability in the contract appears exactly once. A capability that is
    not implemented is reported as `not_implemented`, never omitted, so a caller
    cannot mistake absence for unavailability.
    """

    contract_version: str = CONTRACT_VERSION
    contract_family: str = "my-pa-public-capabilities"
    capabilities: tuple[CapabilityStatus, ...]
    content_types: tuple[ContentTypeStatus, ...]
    limits: EffectiveLimits

    @model_validator(mode="after")
    def _check(self) -> CapabilityManifest:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version!r}")
        names = [status.name for status in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capability manifest contains duplicates")
        if set(names) != set(Capability):
            missing = sorted(capability.value for capability in set(Capability) - set(names))
            raise ValueError(f"capability manifest is incomplete, missing: {missing}")
        media_types = [status.media_type for status in self.content_types]
        if len(media_types) != len(set(media_types)):
            raise ValueError("content type manifest contains duplicates")
        return self


class ReadinessReport(StrictModel):
    """What the deployment can actually do.

    `implemented_capabilities` counts capabilities reported `available`. A report
    claiming `ready` with none implemented would be untruthful, so it is rejected.
    """

    state: ReadinessState
    contract_version: str = CONTRACT_VERSION
    implemented_capabilities: int = Field(ge=0, le=len(Capability))
    total_capabilities: int = Field(default=len(Capability), ge=len(Capability), le=len(Capability))
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ReadinessReport:
        if self.implemented_capabilities > self.total_capabilities:
            raise ValueError("implemented_capabilities cannot exceed total_capabilities")
        if self.state is ReadinessState.READY and (
            self.implemented_capabilities != self.total_capabilities
        ):
            raise ValueError("state 'ready' requires every capability to be implemented")
        if self.state is ReadinessState.CONTRACTS_ONLY and self.implemented_capabilities != 0:
            raise ValueError("state 'contracts_only' requires no implemented capability")
        return self
