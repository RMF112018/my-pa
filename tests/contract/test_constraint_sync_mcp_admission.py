from __future__ import annotations

import json
from typing import Any, Final

import pytest

from my_pa.adapters.mcp import TOOLS
from my_pa.adapters.mcp.server import _answer
from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind

SYNC: Final = tuple(
    capability for capability in Capability if capability.value.startswith("constraint_sync.")
)
TOOLS_BY_NAME: Final[dict[str, Any]] = {tool.name: tool for tool in TOOLS}


class _UncalledService:
    def invoke(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("malformed MCP input must not reach the application")


def test_all_seven_sync_tools_are_generated_and_payloads_are_principal_free() -> None:
    assert len(SYNC) == 7
    for capability in SYNC:
        tool = TOOLS_BY_NAME[capability.value]
        payload = tool.input_schema["properties"][PAYLOAD_KEY]
        assert payload["additionalProperties"] is False
        assert "principal_id" not in payload["properties"]


def test_sync_tool_annotations_and_normalized_row_schema_are_bounded() -> None:
    for capability in SYNC:
        annotation = TOOLS_BY_NAME[capability.value].annotations
        assert annotation is not None
        assert annotation.read_only_hint is (
            capability.value
            in {"constraint_sync.state", "constraint_sync.delta", "constraint_sync.conflicts"}
        )
        assert annotation.open_world_hint is False
    rows = TOOLS_BY_NAME["constraint_sync.preview"].input_schema["properties"][PAYLOAD_KEY][
        "properties"
    ]["rows"]
    assert rows["maxItems"] == 100
    properties = rows["items"]["properties"]
    assert set(properties) == {
        "external_row_key",
        "constraint_id",
        "constraint_code",
        "category",
        "description",
        "date_identified",
        "status",
        "bic",
        "responsible",
        "due_date",
        "reference",
        "current_update",
        "completion_date",
    }
    assert not set(properties) & {"cell", "worksheet", "formula", "coordinate"}
    assert properties["external_row_key"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 256,
        "pattern": r"^\S+$",
    }
    acknowledge = TOOLS_BY_NAME["constraint_sync.acknowledge"].input_schema["properties"][
        PAYLOAD_KEY
    ]["properties"]
    assert acknowledge["item_count"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 100,
    }
    action_counts = acknowledge["action_counts"]
    assert action_counts["additionalProperties"] is False
    assert set(action_counts["required"]) == {
        "no_op",
        "import_external",
        "export_canonical",
        "merge",
        "conflict",
    }
    assert all(
        schema == {"type": "integer", "minimum": 0, "maximum": 100}
        for schema in action_counts["properties"].values()
    )
    resolve = TOOLS_BY_NAME["constraint_sync.resolve"].input_schema["properties"][PAYLOAD_KEY][
        "properties"
    ]
    assert resolve["resolution"]["enum"] == [
        "keep_canonical",
        "accept_external",
        "manual_patch",
        "reopen",
    ]
    patch = resolve["manual_patch"]
    assert patch["maxProperties"] == 9
    assert patch["properties"]["description"]["maxLength"] == 4096
    assert patch["properties"]["current_update"]["maxLength"] == 4096
    assert patch["properties"]["reference"]["maxLength"] == 1024
    for name in ("bic", "responsible"):
        assert patch["properties"][name]["maxItems"] == 32
        assert patch["properties"][name]["items"]["properties"]["label"]["maxLength"] == 512


def test_internal_legacy_resolution_is_not_a_public_authoring_value() -> None:
    resolve = TOOLS_BY_NAME["constraint_sync.resolve"].input_schema["properties"][PAYLOAD_KEY][
        "properties"
    ]
    assert "legacy_migrated" not in resolve["resolution"]["enum"]


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("bic", [{"kind": "bogus"}]),
        ("responsible", [{"kind": "unresolved"}]),
        ("bic", "principal"),
        ("responsible", [[{"kind": "principal"}]]),
    ],
)
def test_mcp_refuses_malformed_external_parties_before_application_invocation(
    field: str, malformed: object
) -> None:
    rendered, failed, _image = _answer(
        _UncalledService(),  # type: ignore[arg-type]
        Principal("prn_12345678", PrincipalKind.OPERATOR, authenticated=True),
        Capability.CONSTRAINT_SYNC_PREVIEW.value,
        {
            PAYLOAD_KEY: {
                "project_id": "prj_12345678",
                "external_identity": "book-1",
                "normalization_version": "constraint-sync-v1",
                "rows": [{"external_row_key": "row-1", field: malformed}],
                "idempotency_key": "preview_12345678",
            }
        },
    )
    assert failed is True
    assert json.loads(rendered)["code"] == "invalid_request"
