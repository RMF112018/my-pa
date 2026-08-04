"""The capture-pipeline suite's database fixtures, shared with two neighbours.

`tests/pipeline/conftest.py` defines them; this makes them visible to
`tests/jobs/test_capture_pipeline_recovery.py` and
`tests/search_quality/test_capture_search.py`, which are placed by subject rather
than by fixture and would otherwise each need a second disposable-database
fixture. A second one would be a second place the migration, the truncation, and
the teardown could drift, and the drift would show as a recovery test passing
against a schema the acceptance tests never saw.

Imported here rather than in the test modules because a fixture name at module
scope in a test file is shadowed by every parameter that requests it, which reads
as a redefinition to a linter and as nothing at all to a reader.
"""

from __future__ import annotations

from tests.pipeline.conftest import disposable_database, engine

__all__ = ["disposable_database", "engine"]
