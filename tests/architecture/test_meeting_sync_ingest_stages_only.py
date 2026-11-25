"""The meeting sync ingestion handler stages and never applies (WP3b-S2, Manager ruling D1).

`my_pa.application.meeting_sync_ingest` writes only the staging rows. Applying a
staged publication to Meetings is the applier's (S3), gated by the
reconciliation latch. So the handler module:

* imports none of the Meeting writers: not the Meeting application, not the
  provider sync, not the resolution or binding rules, not the Meeting domain;
* names no unit-of-work plane but `meeting_sync` (no `.meetings`,
  `.meeting_series`, `.meeting_write_requests`, ...): the Meeting rows are out
  of its reach even through the unit of work it is handed.

Both rules are parsed from the source, so a write on a path no test executes
is still caught. Each has a planted prove-red below.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
HANDLER: Final = PACKAGE / "application" / "meeting_sync_ingest.py"

#: Module prefixes of the Meeting writers (and the rules that decide their writes).
MEETING_WRITERS: Final = (
    "my_pa.application.meetings",
    "my_pa.application.meeting_provider_sync",
    "my_pa.domain.meeting_sync.resolution",
    "my_pa.domain.meeting_sync.binding",
    "my_pa.domain.meeting.",
    "my_pa.infrastructure.persistence",
)
#: Writer names that must not appear even if reached another way.
WRITER_NAMES: Final = frozenset({"MeetingApplication", "MeetingProviderSync", "apply_event"})
#: Unit-of-work planes the handler may name: its staging plane only.
ALLOWED_PLANES: Final = frozenset({"meeting_sync"})


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _writer_imports(source: str) -> set[str]:
    return {
        name
        for name in _imports(source)
        if name.startswith(MEETING_WRITERS) or name == "my_pa.domain.meeting"
    }


def _writer_names(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in WRITER_NAMES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in WRITER_NAMES:
            found.add(node.attr)
    return found


def _planes(source: str) -> set[str]:
    """Attributes read off a name `unit` (the unit of work `apply` is handed)."""
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "unit"
    }


def _handler() -> str:
    return HANDLER.read_text(encoding="utf-8")


def test_the_handler_imports_no_meeting_writer() -> None:
    assert _writer_imports(_handler()) == set()
    assert _writer_names(_handler()) == set()


def test_the_handler_reaches_only_the_staging_plane() -> None:
    assert _planes(_handler()) == ALLOWED_PLANES


def test_a_planted_writer_import_is_caught() -> None:
    planted = (
        _handler() + "\nfrom my_pa.application.meeting_provider_sync import MeetingProviderSync\n"
    )
    assert "my_pa.application.meeting_provider_sync" in _writer_imports(planted)
    planted_use = planted + "\nMeetingProviderSync\n"
    assert _writer_names(planted_use) == {"MeetingProviderSync"}


def test_a_planted_meeting_plane_write_is_caught() -> None:
    planted = _handler() + "\n\ndef _planted(unit):\n    unit.meetings.insert(None)\n"
    assert _planes(planted) == ALLOWED_PLANES | {"meetings"}
