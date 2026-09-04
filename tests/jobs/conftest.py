"""Share the capture-pipeline engine fixture with neighbouring suites.

`tests/pipeline/conftest.py` owns the truncation wrapper. Ordinary current-schema
catalogs come from `tests.db.fixtures`. Importing `engine` here makes that same
wrapper visible to `tests/jobs/test_capture_pipeline_recovery.py`.
"""

from __future__ import annotations

from tests.pipeline.conftest import engine

__all__ = ["engine"]
