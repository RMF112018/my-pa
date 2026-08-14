"""Transport-neutral values for the origin OAuth boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["AuthorizationRequest", "OAuthError", "valid_operator_secret"]

_OPERATOR_SECRET = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


def valid_operator_secret(value: str) -> bool:
    """Whether a value has the closed token_urlsafe operator-secret shape."""
    return _OPERATOR_SECRET.fullmatch(value) is not None


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
