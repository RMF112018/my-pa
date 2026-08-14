"""Transport-neutral values for the origin OAuth boundary."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AuthorizationRequest", "OAuthError"]


class OAuthError(ValueError):
    """A bounded OAuth protocol refusal."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    client_id: str
    client_name: str
    redirect_uri: str
    scope: str
    state: str
    code_challenge: str
    resource: str
