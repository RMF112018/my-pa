"""Server-owned WebAuthn relying-party configuration.

RP ID and allowed origins are exact deployment values. Wildcard, suffix, and
browser-selected identity are refused. Empty production-like origins fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

__all__ = [
    "WebAuthnRelyingParty",
    "WebAuthnRelyingPartyError",
    "parse_allowed_origins",
]

_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})


class WebAuthnRelyingPartyError(ValueError):
    """Relying-party configuration is missing or unsafe."""


def parse_allowed_origins(configured: str) -> tuple[str, ...]:
    """Split a configured origin list. Rejects wildcards and empty members."""
    parts = [item.strip() for item in configured.replace(",", " ").split() if item.strip()]
    if not parts:
        raise WebAuthnRelyingPartyError("at least one allowed origin is required")
    origins: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        if "*" in raw:
            raise WebAuthnRelyingPartyError("wildcard origins are not allowed")
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"}:
            raise WebAuthnRelyingPartyError("origins must be absolute http(s) URLs")
        if not parsed.hostname:
            raise WebAuthnRelyingPartyError("origins must include a hostname")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise WebAuthnRelyingPartyError("origins must not include a path, query, or fragment")
        if parsed.username or parsed.password:
            raise WebAuthnRelyingPartyError("origins must not include userinfo")
        if parsed.scheme == "http" and parsed.hostname not in _LOCAL_HOSTS:
            raise WebAuthnRelyingPartyError("non-local origins must use https")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return tuple(origins)


@dataclass(frozen=True, slots=True)
class WebAuthnRelyingParty:
    """Exact RP ID and origin allow-list. The browser does not choose these."""

    rp_id: str
    rp_name: str
    allowed_origins: tuple[str, ...]

    def __post_init__(self) -> None:
        rp_id = self.rp_id.strip()
        rp_name = self.rp_name.strip()
        if not rp_id:
            raise WebAuthnRelyingPartyError("rp_id is required")
        if "/" in rp_id or "*" in rp_id or ":" in rp_id:
            raise WebAuthnRelyingPartyError("rp_id must be an exact hostname")
        if not rp_name:
            raise WebAuthnRelyingPartyError("rp_name is required")
        if not self.allowed_origins:
            raise WebAuthnRelyingPartyError("at least one allowed origin is required")
        object.__setattr__(self, "rp_id", rp_id)
        object.__setattr__(self, "rp_name", rp_name)

    def accepts_origin(self, origin: str) -> bool:
        """Exact origin match. No suffix or scheme-insensitive fallback."""
        return origin in self.allowed_origins
