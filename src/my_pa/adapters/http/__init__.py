"""The HTTP transport. One module, and it maps rather than decides."""

from __future__ import annotations

from my_pa.adapters.http.app import PATH_TEMPLATE, create_http_app

__all__ = ["PATH_TEMPLATE", "create_http_app"]
