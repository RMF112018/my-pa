"""The ingestion lifecycle stays consumer-neutral and read-only on the store (WP3a).

* `my_pa.application.ingestion` imports no consumer slice (Manager ruling M5):
  not the communications domain or parser, not the meeting sync domain or
  parser, not the consumers' application modules (the WP3b staging handler
  and the S3 applier included), and no layer of the project-reports consumer
  (WP3P). A consumer reaches it only through the
  injected `IngestConsumerHandler` port;
* the lifecycle calls only `list_directory`, `stat` and `open_download` on a
  `FileWorkspaceStore` (ruling m5), and names no other store method at all;
  the communications rederive (WP4-S3) calls only `stat` and `open_download`.

Both rules are parsed from the source, so a call on a path never executed by a
test is still caught. Each has a planted prove-red below.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Final

from my_pa.contracts.ports import FileWorkspaceStore

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
LIFECYCLE: Final = PACKAGE / "application" / "ingestion.py"
#: The communications rederive (WP4-S3) re-reads snapshot files through the
#: same stores: by known path only, so `stat` and `open_download`, never a listing.
REDERIVE: Final = PACKAGE / "application" / "communications_rederive.py"

#: Module prefixes a consumer-neutral lifecycle may not import.
CONSUMER_SLICES: Final = (
    "my_pa.domain.communications",
    "my_pa.infrastructure.communications",
    "my_pa.application.communications_ingest",
    "my_pa.domain.meeting_sync",
    "my_pa.infrastructure.meeting_sync",
    "my_pa.application.meeting_provider_sync",
    "my_pa.application.meeting_sync_ingest",
    "my_pa.application.meeting_sync_apply",
    "my_pa.domain.pulse",
    "my_pa.application.pulse",
    # WP3P: the project-reports consumer lives under `project_reports`, so the
    # neutral lifecycle may import none of its layers (a prefix match covers the
    # application handler modules `project_reports_*` too).
    "my_pa.domain.project_reports",
    "my_pa.application.project_reports",
    "my_pa.infrastructure.project_reports",
)

#: The store's read path (ruling m5).
ALLOWED_STORE_CALLS: Final = frozenset({"list_directory", "stat", "open_download"})
#: Every other method a `FileWorkspaceStore` has, writes included.
FORBIDDEN_STORE_NAMES: Final = (
    frozenset(
        name
        for name, member in inspect.getmembers(FileWorkspaceStore)
        if not name.startswith("_") and (inspect.isfunction(member) or isinstance(member, property))
    )
    - ALLOWED_STORE_CALLS
)


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _consumer_imports(source: str) -> set[str]:
    return {name for name in _imports(source) if name.startswith(CONSUMER_SLICES)}


def _store_calls(source: str) -> set[str]:
    """Methods called on `self._store` or a bare `store`."""
    called: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func.value
        if (isinstance(target, ast.Attribute) and target.attr == "_store") or (
            isinstance(target, ast.Name) and target.id == "store"
        ):
            called.add(node.func.attr)
    return called


def _forbidden_names(source: str) -> set[str]:
    """Any attribute access naming a store method outside the read path."""
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_STORE_NAMES
    }


def _lifecycle() -> str:
    return LIFECYCLE.read_text(encoding="utf-8")


def test_the_store_has_write_methods_to_forbid() -> None:
    assert {"write_text", "move", "copy", "trash", "mkdir"} <= FORBIDDEN_STORE_NAMES


def test_the_lifecycle_imports_no_consumer_slice() -> None:
    assert _consumer_imports(_lifecycle()) == set()


def test_the_lifecycle_calls_only_the_store_read_path() -> None:
    called = _store_calls(_lifecycle())
    assert called == ALLOWED_STORE_CALLS
    assert _forbidden_names(_lifecycle()) == set()


def test_a_planted_consumer_import_is_caught() -> None:
    planted = _lifecycle() + "\nfrom my_pa.domain.communications.model import Publication\n"
    assert _consumer_imports(planted) == {
        "my_pa.domain.communications.model",
        "my_pa.domain.communications.model.Publication",
    }


def test_a_planted_project_reports_import_is_caught() -> None:
    for planted_module in (
        "my_pa.domain.project_reports.model",
        "my_pa.application.project_reports_ingest",
        "my_pa.infrastructure.project_reports.reader",
    ):
        planted = _lifecycle() + f"\nimport {planted_module}\n"
        assert _consumer_imports(planted) == {planted_module}


def test_a_planted_store_write_is_caught() -> None:
    planted = _lifecycle() + "\n\ndef _planted(store):\n    store.write_text('a', 'b')\n"
    assert "write_text" in _store_calls(planted)
    assert _forbidden_names(planted) == {"write_text"}


def test_the_rederive_calls_only_stat_and_open_download() -> None:
    source = REDERIVE.read_text(encoding="utf-8")
    assert _store_calls(source) == {"stat", "open_download"}
    assert _forbidden_names(source) == set()
