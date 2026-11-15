"""The remote MCP surface's readable-resource seam (files-workspace contract section 17.3).

Two transports meet here and neither imports the other: `adapters/mcp/remote.py`
serves `resources/list`, `resources/templates/list` and `resources/read` and
streams the answer; `adapters/http/files_resources.py` decides what a read may
open and streams its bytes. This module holds only the shapes between them --
no MCP or HTTP type, no decision.

- **Authorization from authentication only.** A source receives the request's
  authenticated identity (`ResourceRequester`: the Principal and the OAuth
  client id the credential resolved to) and the URI, never another field.
- **A refusal is a closed token.** `RemoteResourceRefused.reason` is a reason
  token (`ticket_invalid`, `denied`, `unavailable`, ...); the URI and any path
  stay out of it, because the token is what the JSON-RPC error carries.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from my_pa.domain.identity.principal import Principal

__all__ = [
    "RemoteResourceRefused",
    "RemoteResourceSource",
    "RemoteResourceStream",
    "RemoteResourceTemplate",
    "ResourceRequester",
]


class RemoteResourceRefused(Exception):  # noqa: N818 - a refusal, rendered as JSON-RPC
    """A `resources/read` the source refused; `reason` is a closed token, never a value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RemoteResourceTemplate:
    """One `resources/templates/list` entry (RFC 6570 `uri_template`)."""

    name: str
    uri_template: str
    description: str
    mime_type: str


class ResourceRequester(Protocol):
    """The authenticated identity of one `/mcp` request, as a source may read it."""

    @property
    def principal(self) -> Principal: ...

    @property
    def authenticated_client_id(self) -> str | None: ...


class RemoteResourceStream(Protocol):
    """One opened resource: its byte size, and its bytes streamed once.

    `stream` hands `write` raw pieces whose lengths are multiples of 3 except
    the last (so each base64-encodes on its own), and enforces its own
    deadline and re-checks; raising stops the stream. `aclose` releases
    everything, idempotently, after any outcome.
    """

    size: int
    mime_type: str

    async def stream(self, write: Callable[[bytes], Awaitable[None]]) -> None: ...

    async def aclose(self) -> None: ...


class RemoteResourceSource(Protocol):
    """Readable workspace resources; `open` raises `RemoteResourceRefused`."""

    def templates(self) -> list[RemoteResourceTemplate]: ...

    async def open(self, uri: str, access: ResourceRequester) -> RemoteResourceStream: ...
