"""The MCP transport: the same eight capabilities, over stdio.

`create_mcp_server` builds the protocol server; `serve_stdio` runs one
connection on standard input and output and returns when the client closes it.
`TOOLS` is the tool list, derived rather than written down.
"""

from __future__ import annotations

from my_pa.adapters.mcp.server import create_mcp_server, serve_stdio
from my_pa.adapters.mcp.tools import TOOLS

__all__ = ["TOOLS", "create_mcp_server", "serve_stdio"]
