"""The HTTP transport. One module, and it maps rather than decides."""

from __future__ import annotations

from my_pa.adapters.http.app import MAX_REQUEST_BYTES, PATH_TEMPLATE, create_http_app

__all__ = ["MAX_REQUEST_BYTES", "PATH_TEMPLATE", "create_http_app"]
