"""Dedicated Apple machine credential and control-route contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Any, Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.native_apple import AppleBridgeIdentity, AppleMachineCredentialError

__all__ = [
    "AppleBridgeCredentialBinding",
    "AppleBridgeIdentity",
    "AppleMachineControl",
    "AppleMachineCredentialError",
    "authenticate_apple_bridge",
]


@dataclass(frozen=True, slots=True)
class AppleBridgeCredentialBinding:
    credential_id: str
    principal_id: str
    bridge_id: str
    secret_sha256: str
    active: bool = True

    def __post_init__(self) -> None:
        if not self.credential_id.startswith("abcred_") or not 15 <= len(self.credential_id) <= 72:
            raise ValueError("Apple bridge credential identifier is invalid")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        if len(self.secret_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.secret_sha256
        ):
            raise ValueError("Apple bridge credential digest must be SHA-256")


def authenticate_apple_bridge(
    presented: str | None, binding: AppleBridgeCredentialBinding
) -> AppleBridgeIdentity:
    """Authenticate only ``AppleBridgeCredential <credential_id>:<secret>``."""
    prefix = "AppleBridgeCredential "
    if presented is None or not presented.startswith(prefix):
        raise AppleMachineCredentialError()
    credential = presented.removeprefix(prefix)
    credential_id, separator, secret = credential.partition(":")
    observed = sha256(secret.encode()).hexdigest()
    if (
        not separator
        or not secret
        or not binding.active
        or not compare_digest(credential_id, binding.credential_id)
        or not compare_digest(observed, binding.secret_sha256)
    ):
        raise AppleMachineCredentialError()
    return AppleBridgeIdentity(binding.credential_id, binding.principal_id, binding.bridge_id)


class AppleMachineControl(Protocol):
    """NAS application boundary used by the two exact HTTP routes."""

    def poll(self, identity: AppleBridgeIdentity) -> Mapping[str, Any] | None: ...

    def admit(
        self, identity: AppleBridgeIdentity, document: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...
