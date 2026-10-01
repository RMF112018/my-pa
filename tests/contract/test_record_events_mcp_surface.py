"""WP-RE-06 Phase 6B: `record_events.list` on the MCP surface, and its policy invariants.

FAST. RE-AC-075 and the plan section 8 invariants:

* the tool is published as a read: `read_only_hint` true, never destructive;
* `record_event_read` is not a write purpose, so the remote wrapper classifies
  the capability as a read, the ChatLLM facade kind is `"read"`, and the compact
  gateway files it under the `record_events` feature (G1-MG-009);
* exactly one purpose; not a write, not destructive, not operator-only;
* the ChatLLM policy composes it `ALWAYS`, consistent with `DATA_REQUIRED`;
* it accepts a continuation (`cursor`) and its published payload carries only
  `page_size`, `cursor` and `record_families`.
"""

from __future__ import annotations

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.remote import _WRITE_PURPOSES, is_remote_write
from my_pa.adapters.mcp.tools import TOOLS, payload_schema_for
from my_pa.application.capabilities import _CAPABILITIES_ACCEPTING_A_CONTINUATION
from my_pa.application.commands import ListRecordEvents
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import RecordEventFamily

FEED = Capability.RECORD_EVENTS_LIST


def test_the_tool_is_published_once_as_a_read() -> None:
    (tool,) = [tool for tool in TOOLS if tool.name == "record_events.list"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.description is not None
    assert tool.description.startswith("`record_events.list`")


def test_the_remote_wrapper_classifies_it_as_a_read() -> None:
    assert Purpose.RECORD_EVENT_READ not in _WRITE_PURPOSES
    assert is_remote_write(FEED) is False
    assert facade_kind(FEED) == "read"
    assert feature_label(FEED.value) == "record_events"


def test_the_capability_invariants_of_plan_section_8() -> None:
    assert permitted_purposes(FEED) == frozenset({Purpose.RECORD_EVENT_READ})
    assert not is_write_capability(FEED)
    assert not is_destructive_capability(FEED)
    assert not is_operator_only(FEED)
    policy = CHATLLM_CAPABILITY_POLICY[FEED]
    assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
    assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.ALWAYS


def test_it_accepts_a_continuation_and_publishes_only_its_three_fields() -> None:
    assert FEED in _CAPABILITIES_ACCEPTING_A_CONTINUATION
    schema = payload_schema_for(ListRecordEvents)
    assert set(schema["properties"]) == {"page_size", "cursor", "record_families"}
    assert schema["required"] == []
    assert schema["additionalProperties"] is False
    families = schema["properties"]["record_families"]
    assert families["type"] == "array"
    assert sorted(families["items"]["enum"]) == sorted(family.value for family in RecordEventFamily)
