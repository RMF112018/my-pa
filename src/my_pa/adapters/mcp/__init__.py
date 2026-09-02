"""The MCP transport: the same 112 capabilities, over stdio.

`create_mcp_server` builds the protocol server; `serve_stdio` runs one
connection on standard input and output and returns when the client closes it.
`TOOLS` is the tool list, derived rather than written down.
"""

from __future__ import annotations

from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.server import create_mcp_server, serve_stdio
from my_pa.adapters.mcp.tools import TOOLS

__all__ = [
    "TOOLS",
    "RemoteAccessContext",
    "create_mcp_server",
    "create_remote_mcp_app",
    "serve_stdio",
]
