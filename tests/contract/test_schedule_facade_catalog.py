"""CPM Workbench S5b-2: the 7 Schedule names in the catalog and the compact facade (FAST).

Worker and capabilities contract sections 3.5 and 3.13.3 (I7-B), on the S3.1
Part D precedent (`tests/contract/test_lineage_s31_facade_catalog.py`):

* every Schedule capability has a `TOOLS` entry whose description is the
  contract's summary, published under the `schedule` feature;
* the facade kinds are deliberate: 6 `read`, the import `operator` (published
  only by the compact operator tool, which never admits it remotely);
* the tool annotations follow derivation: the reads read-only, the import a
  non-destructive, non-idempotent write;
* describe lists only the eligible Schedule names of a request.

The facade end-to-end rows over a real server are I7-C's
(`tests/integration/test_schedule_compact_facade.py`). Every value is synthetic.
"""

from __future__ import annotations

from typing import Final

import pytest

from my_pa.adapters.mcp.chatllm_gateway import (
    OPERATOR_TOOL,
    READ_TOOL,
    facade_kind,
    facade_tool_names,
    feature_label,
)
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.domain.identity.operation import Capability

#: Contract section 3.5: `name -> (summary, kind)`.
_TABLE: Final[dict[str, tuple[str, str]]] = {
    "schedule_publications.import": (
        "Admit one enrolled schedule PDF version as a publication of a Schedule Series and "
        "queue its parse (attested local operator: CLI or HTTP gateway only).",
        "operator",
    ),
    "schedule_series.list": (
        "List a Project's Schedule Series, newest first, with each one's latest "
        "comparison-eligible update.",
        "read",
    ),
    "schedule_publications.list": (
        "List one Schedule Series' publications, newest admission first, with effective "
        "status and counts.",
        "read",
    ),
    "schedule_publications.read": (
        "Read one schedule publication: source identity, document digest, published "
        "metadata, status, job, parser runs and issue counts by code.",
        "read",
    ),
    "schedule_activities.list": (
        "List one complete or partial publication's activities and milestones in published "
        "schedule order.",
        "read",
    ),
    "schedule_activities.history": (
        "Read one Stable Activity's observations in its Series' complete and partial "
        "publications, oldest Data Date first.",
        "read",
    ),
    "schedule_changes.list": (
        "Compare two publications of one Series and list the exact per-activity changes "
        "from the first to the second.",
        "read",
    ),
}


def test_every_schedule_capability_has_a_catalog_entry() -> None:
    schedule = {
        capability.value for capability in Capability if capability.value.startswith("schedule_")
    }
    assert schedule == set(_TABLE)
    tools = {tool.name: tool for tool in TOOLS}
    for name, (summary, _kind) in sorted(_TABLE.items()):
        assert name in tools, name
        assert tools[name].description == summary, name
        assert feature_label(name) == "schedule", name


@pytest.mark.parametrize("name", sorted(_TABLE))
def test_schedule_facade_kinds_are_deliberate(name: str) -> None:
    capability = Capability(name)
    _summary, kind = _TABLE[name]
    assert facade_kind(capability) == kind
    expected_tool = OPERATOR_TOOL if kind == "operator" else READ_TOOL
    assert expected_tool in facade_tool_names(frozenset({name}))


def test_schedule_tool_annotations_follow_derivation() -> None:
    tools = {tool.name: tool for tool in TOOLS}
    for name, (_summary, kind) in _TABLE.items():
        annotations = tools[name].annotations
        assert annotations is not None
        hints = (
            annotations.read_only_hint,
            annotations.destructive_hint,
            annotations.idempotent_hint,
            annotations.open_world_hint,
        )
        if kind == "read":
            assert hints == (True, False, False, False), name
        else:
            assert hints == (False, False, False, False), name


def test_describe_publishes_no_facade_tool_for_an_empty_schedule_set() -> None:
    assert facade_tool_names(frozenset()) == frozenset()
    reads = frozenset(name for name, (_s, kind) in _TABLE.items() if kind == "read")
    assert OPERATOR_TOOL not in facade_tool_names(reads)
