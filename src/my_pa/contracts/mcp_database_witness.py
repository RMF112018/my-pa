"""Ephemeral, non-content evidence for one opt-in MCP status request.

Engine and pool references stay inside the request thread. Only closed booleans, the
effective profile and the application's opaque correlation identifier leave it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from my_pa.contracts.mcp_database_profiles import McpDatabaseProfile
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose


@dataclass(frozen=True)
class McpWitnessBinding:
    """Server-composed eligibility, never parsed from tool arguments."""

    profile: McpDatabaseProfile
    data_engine: object = field(repr=False)
    controls_engine: object = field(repr=False)
    data_pool: object = field(repr=False)
    controls_pool: object = field(repr=False)


@dataclass
class McpDatabaseWitness:
    binding: McpWitnessBinding = field(repr=False)
    _data_begins: int = 0
    _read_only: bool | None = None
    _audit_correlations: list[str] = field(default_factory=list, repr=False)
    _independent_audit: bool = False

    def data_begin(self, engine: object, *, pool: object, read_only: bool) -> None:
        if engine is self.binding.data_engine and pool is self.binding.data_pool:
            self._data_begins += 1
            self._read_only = read_only

    def audit_committed(self, engine: object, correlation_id: str, *, pool: object) -> None:
        self._audit_correlations.append(correlation_id)
        self._independent_audit = (
            engine is not self.binding.data_engine and pool is not self.binding.data_pool
        )

    def metadata(self, correlation_id: str) -> dict[str, object]:
        if (
            self._data_begins != 1
            or self._read_only is None
            or self._audit_correlations != [correlation_id]
            or not self._independent_audit
            or self.binding.controls_engine is self.binding.data_engine
            or self.binding.controls_pool is self.binding.data_pool
            or (self.binding.profile is McpDatabaseProfile.READ_ONLY and not self._read_only)
        ):
            return {}
        validate_identifier(correlation_id, IdKind.CORRELATION)
        return {
            "my_pa_database_witness": {
                "version": 1,
                "correlation_id": correlation_id,
                "effective_profile": self.binding.profile.value,
                "data_role_identity_match": True,
                "database_identity_match": True,
                "transaction_read_only": self._read_only,
                "audit_committed": True,
                "audit_engine_independent": True,
                "control_engine_independent_configured": True,
            }
        }


current_mcp_database_witness: ContextVar[McpDatabaseWitness | None] = ContextVar(
    "mcp_database_witness", default=None
)


def request_witness(
    binding: McpWitnessBinding | None,
    metadata: RequestMetadata,
    principal: Principal,
    transport: CaptureTransport,
    authenticated_client_id: str | None,
) -> McpDatabaseWitness | None:
    """Restrict evidence to the existing authenticated non-content status call."""
    if (
        binding is not None
        and transport is CaptureTransport.REMOTE_CLIENT
        and principal.authenticated
        and authenticated_client_id is not None
        and metadata.capability is Capability.CAPABILITIES_GET
        and metadata.purpose is Purpose.STATUS_OBSERVATION
    ):
        return McpDatabaseWitness(binding)
    return None
