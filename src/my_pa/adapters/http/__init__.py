"""The HTTP transport. One module, and it maps rather than decides."""

from __future__ import annotations

from my_pa.adapters.http.app import (
    PATH_TEMPLATE,
    REMOTE_CAPTURE_CAPABILITY,
    REMOTE_CAPTURE_PATH,
    create_http_app,
)

__all__ = [
    "PATH_TEMPLATE",
    "REMOTE_CAPTURE_CAPABILITY",
    "REMOTE_CAPTURE_PATH",
    "create_http_app",
]
