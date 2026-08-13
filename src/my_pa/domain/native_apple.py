"""Provider-neutral identities and fixed refusal for the Apple bridge plane."""

from __future__ import annotations

from dataclasses import dataclass


class AppleMachineCredentialError(RuntimeError):
    """One fixed refusal for malformed, unknown, mismatched, or revoked credentials."""


@dataclass(frozen=True, slots=True)
class AppleBridgeIdentity:
    credential_id: str
    principal_id: str
    bridge_id: str
