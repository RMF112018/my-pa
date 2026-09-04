"""Share the capture-pipeline engine fixture with neighbouring suites.

`tests/pipeline/conftest.py` owns the truncation wrapper. Ordinary current-schema
catalogs come from `tests.db.fixtures`.
"""

from __future__ import annotations

from tests.pipeline.conftest import engine

__all__ = ["engine"]
