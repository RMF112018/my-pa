"""Immutable, server-owned provenance for authenticated proposal producers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from my_pa.domain.identity.principal import Principal, PrincipalKind

__all__ = ["ProducerOrigin", "ProducerOriginError", "ProducerOriginRegistry"]

_METHODS: Final = frozenset({"deterministic", "rule", "local_model"})
_MAX_ID = 200
_MAX_VERSION = 200


class ProducerOriginError(Exception):
    """The authenticated producer has no exact server registration."""


@dataclass(frozen=True, slots=True)
class ProducerOrigin:
    principal_id: str
    principal_kind: PrincipalKind
    method: str
    method_version: str
    model_id: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not self.principal_id.strip() or len(self.principal_id) > _MAX_ID:
            raise ValueError("producer Principal identifier is invalid")
        if self.method not in _METHODS:
            raise ValueError("producer method is not registered vocabulary")
        if not self.method_version.strip() or len(self.method_version) > _MAX_VERSION:
            raise ValueError("producer method version is required")
        for value in (self.model_id, self.model_version):
            if value is not None and (not value.strip() or len(value) > _MAX_VERSION):
                raise ValueError("producer model identity is invalid")
        model_pair = self.model_id is not None and self.model_version is not None
        if (self.model_id is None) != (self.model_version is None):
            raise ValueError("producer model identity is a pair")
        if (self.method == "local_model") != model_pair:
            raise ValueError("only a local-model producer names an exact model")


class ProducerOriginRegistry:
    """A frozen identity-to-origin map supplied only by composition."""

    def __init__(self, registrations: Mapping[str, ProducerOrigin] | None = None) -> None:
        copied = dict(registrations or {})
        if any(key != origin.principal_id for key, origin in copied.items()):
            raise ValueError("producer registration key must equal its Principal")
        self._registrations = MappingProxyType(copied)

    def resolve(self, principal: Principal) -> ProducerOrigin:
        held = self._registrations.get(principal.principal_id)
        if not principal.authenticated or held is None or held.principal_kind is not principal.kind:
            raise ProducerOriginError
        return held

    @property
    def has_registrations(self) -> bool:
        """Whether this composition can truthfully serve a producer write."""
        return bool(self._registrations)
