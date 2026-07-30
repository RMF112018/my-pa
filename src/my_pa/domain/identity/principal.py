"""Principals and their trust.

Authority comes from authenticated context, never from a caller-supplied flag
(`docs/specs`, section 9.6). A principal carries no credential material.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = ["Principal", "PrincipalKind"]


class PrincipalKind(StrEnum):
    """Actors defined by the MCV contract."""

    OPERATOR = "operator"
    GATEWAY = "gateway"
    WORKER = "worker"
    OPERATOR_CLI = "operator_cli"
    SOURCE_PROVIDER_ADAPTER = "source_provider_adapter"
    LOCAL_MODEL_GATEWAY = "local_model_gateway"
    CLOUD_MODEL_PROVIDER = "cloud_model_provider"


#: Kinds that may invoke operator-only capabilities.
_OPERATOR_KINDS: frozenset[PrincipalKind] = frozenset(
    {PrincipalKind.OPERATOR, PrincipalKind.OPERATOR_CLI}
)

#: Kinds that are untrusted output generators and can never carry authority.
_NON_AUTHORITATIVE_KINDS: frozenset[PrincipalKind] = frozenset(
    {PrincipalKind.LOCAL_MODEL_GATEWAY, PrincipalKind.CLOUD_MODEL_PROVIDER}
)


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor.

    `authenticated` records whether the composition root proved this identity.
    An unauthenticated principal is carried so it can be denied and audited, not
    so it can be trusted.
    """

    principal_id: str
    kind: PrincipalKind
    authenticated: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)

    @property
    def is_operator(self) -> bool:
        """Whether this principal may invoke operator-only capabilities."""
        return self.authenticated and self.kind in _OPERATOR_KINDS

    @property
    def may_hold_authority(self) -> bool:
        """Whether this principal can hold any authority at all.

        Model gateways and cloud providers cannot alter facts, authority, policy,
        source, or action state (`ACT-PKL-007`, `ACT-PKL-008`).
        """
        return self.authenticated and self.kind not in _NON_AUTHORITATIVE_KINDS
