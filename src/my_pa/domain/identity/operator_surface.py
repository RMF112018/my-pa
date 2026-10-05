"""The local operator surface a request arrived on (KLP-WP-04, R6 section 3.2).

Every surface today authenticates a `PrincipalKind.OPERATOR` principal -- the
CLI, stdio MCP, the HTTP gateway, the remote capture route and every remote MCP
OAuth client -- so `principal.is_operator` distinguishes nothing between them.
`OperatorSurface` is the one server-stamped fact that does: it is set only by the
CLI adapter (`adapters/cli/app.py`) and the HTTP gateway's `invoke` route
(`adapters/http/app.py`), never by any MCP adapter, the remote capture route or
`apps/cli/gsqs_b0.py`. Absent (`None`) is the fail-closed default.

It is Python-only and never persisted, and it is an input to exactly one rule:
`domain.policy.knowledge_review_authority.derive_knowledge_review_authority`.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["OperatorSurface"]


class OperatorSurface(StrEnum):
    """The two local operator surfaces (matrix vocabulary `operator_surface`)."""

    CLI = "cli"
    HTTP_GATEWAY = "http_gateway"
