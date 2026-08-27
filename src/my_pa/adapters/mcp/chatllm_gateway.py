"""Compact ChatLLM façade tools published on the existing `/mcp` resource.

Presentation only. Canonical capability names remain the dispatch and
authorization key. This module does not own grants, OAuth, or `invoke`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, Literal

from mcp.types import Tool, ToolAnnotations

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application.errors import InvalidRequestError, SafeDetail, UnsupportedError
from my_pa.domain.identity.operation import Capability, is_destructive_capability, is_operator_only

__all__ = [
    "DESCRIBE_TOOL",
    "OPERATOR_TOOL",
    "PROFILE_VERSION",
    "READ_TOOL",
    "WRITE_TOOL",
    "compact_tools",
    "facade_kind",
    "facade_tool_names",
    "prepare_compact_call",
    "render_describe",
]

PROFILE_VERSION: Final = "chatllm-gateway-v1"
DESCRIBE_TOOL: Final = "my_pa.describe"
READ_TOOL: Final = "my_pa.read"
WRITE_TOOL: Final = "my_pa.write"
OPERATOR_TOOL: Final = "my_pa.operator"

_KINDS: Final = frozenset({"read", "write", "operator"})
_DEFAULT_LIMIT: Final = 25
_MAX_LIMIT: Final = 100
_MAX_QUERY: Final = 200

_FEATURE_BY_FAMILY: Final[Mapping[str, str]] = {
    "capabilities": "system",
    "sources": "sources",
    "knowledge": "knowledge",
    "capture": "capture",
    "review": "review",
    "continuity": "continuity",
    "tasks": "work",
    "commitments": "work",
    "documents": "documents",
    "context": "context",
    "entities": "people",
    "relationship_memory": "people",
    "reports": "reports",
    "goodnotes": "goodnotes",
}

_WRAPPER_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "capability": {"type": "string", "minLength": 1},
        "arguments": {"type": "object"},
    },
    "required": ["capability", "arguments"],
    "additionalProperties": False,
}

_DESCRIBE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "feature": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "enum": sorted(_KINDS)},
        "query": {"type": "string", "minLength": 1, "maxLength": _MAX_QUERY},
        "capability": {"type": "string", "minLength": 1},
        "cursor": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
    },
    "additionalProperties": False,
}

_CANONICAL_TOOLS: Final[Mapping[str, Tool]] = {tool.name: tool for tool in TOOLS}


def facade_kind(capability: Capability) -> Literal["read", "write", "operator"]:
    """Remote-profile kind for one canonical capability."""
    from my_pa.adapters.mcp.remote import is_remote_write

    if is_operator_only(capability):
        return "operator"
    if is_remote_write(capability):
        return "write"
    return "read"


def feature_label(capability_name: str) -> str:
    """Presentation family for an eligible canonical name. Never a grant."""
    family = capability_name.split(".", 1)[0]
    return _FEATURE_BY_FAMILY.get(family, "other")


def facade_tool_names(allowed_canonical: frozenset[str]) -> frozenset[str]:
    """Façade names published for this request's eligible canonical set."""
    if not allowed_canonical:
        return frozenset()
    names = {DESCRIBE_TOOL}
    for raw in allowed_canonical:
        try:
            capability = Capability(raw)
        except ValueError:
            continue
        kind = facade_kind(capability)
        if kind == "read":
            names.add(READ_TOOL)
        elif kind == "write":
            names.add(WRITE_TOOL)
        else:
            names.add(OPERATOR_TOOL)
    return frozenset(names)


def compact_tools(allowed_tools: frozenset[str]) -> tuple[Tool, ...]:
    """Façade Tool objects for the names this request may list."""
    catalog = (
        Tool(
            name=DESCRIBE_TOOL,
            description="Filtered catalog and contract lookup for currently eligible capabilities.",
            input_schema=_DESCRIBE_SCHEMA,
            annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        ),
        Tool(
            name=READ_TOOL,
            description="Invoke one currently eligible non-write, non-operator capability.",
            input_schema=_WRAPPER_SCHEMA,
            annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        ),
        Tool(
            name=WRITE_TOOL,
            description="Invoke one currently eligible write, non-operator capability.",
            input_schema=_WRAPPER_SCHEMA,
            annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
        ),
        Tool(
            name=OPERATOR_TOOL,
            description="Invoke one currently eligible operator-only capability.",
            input_schema=_WRAPPER_SCHEMA,
            annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
        ),
    )
    return tuple(tool for tool in catalog if tool.name in allowed_tools)


def _as_object(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise InvalidRequestError()
    return value


def _parse_wrapper(document: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    extra = set(document) - {"capability", "arguments"}
    if extra:
        raise InvalidRequestError(SafeDetail.NAME)
    raw_name = document.get("capability")
    nested = document.get("arguments")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise InvalidRequestError(SafeDetail.NAME)
    if not isinstance(nested, Mapping):
        raise InvalidRequestError(SafeDetail.PAYLOAD)
    return raw_name, nested


def prepare_compact_call(
    tool_name: str,
    document: Mapping[str, Any] | None,
    *,
    allowed_canonical: frozenset[str],
) -> tuple[str, Mapping[str, Any] | None]:
    """Return the canonical tool name and arguments, or describe sentinels.

    Describe is signalled by returning `DESCRIBE_TOOL` as the name. Execution
    names are canonical capability values. Raises application errors for
    wrapper/kind/eligibility failures before `invoke`.
    """
    document = _as_object(document)
    if tool_name == DESCRIBE_TOOL:
        extra = set(document) - set(_DESCRIBE_SCHEMA["properties"])
        if extra:
            raise InvalidRequestError()
        return DESCRIBE_TOOL, document
    if tool_name not in {READ_TOOL, WRITE_TOOL, OPERATOR_TOOL}:
        raise UnsupportedError()
    target_name, nested = _parse_wrapper(document)
    if target_name not in allowed_canonical:
        raise UnsupportedError()
    try:
        capability = Capability(target_name)
    except ValueError:
        raise UnsupportedError() from None
    expected = {READ_TOOL: "read", WRITE_TOOL: "write", OPERATOR_TOOL: "operator"}[tool_name]
    if facade_kind(capability) != expected:
        raise InvalidRequestError()
    return target_name, nested


def _catalog_item(name: str) -> dict[str, Any]:
    tool = _CANONICAL_TOOLS.get(name)
    try:
        capability = Capability(name)
    except ValueError:
        raise UnsupportedError() from None
    summary = tool.description if tool is not None else None
    return {
        "capability": name,
        "kind": facade_kind(capability),
        "feature": feature_label(name),
        "summary": summary,
        "destructive": is_destructive_capability(capability),
        "idempotent": bool(tool.annotations.idempotent_hint)
        if tool is not None and tool.annotations is not None
        else False,
    }


def render_describe(
    document: Mapping[str, Any] | None, *, allowed_canonical: frozenset[str]
) -> str:
    """JSON catalog or contract lookup, already filtered by `allowed_canonical`."""
    document = _as_object(document)
    extra = set(document) - set(_DESCRIBE_SCHEMA["properties"])
    if extra:
        raise InvalidRequestError()
    feature = document.get("feature")
    kind = document.get("kind")
    query = document.get("query")
    exact = document.get("capability")
    cursor = document.get("cursor")
    limit = document.get("limit", _DEFAULT_LIMIT)
    if feature is not None and (not isinstance(feature, str) or not feature):
        raise InvalidRequestError()
    if kind is not None and kind not in _KINDS:
        raise InvalidRequestError()
    if query is not None and (not isinstance(query, str) or not (1 <= len(query) <= _MAX_QUERY)):
        raise InvalidRequestError(SafeDetail.QUERY)
    if exact is not None and (not isinstance(exact, str) or not exact):
        raise InvalidRequestError(SafeDetail.NAME)
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise InvalidRequestError(SafeDetail.CURSOR)
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= _MAX_LIMIT):
        raise InvalidRequestError(SafeDetail.LIMIT)

    if exact is not None:
        if exact not in allowed_canonical:
            raise UnsupportedError()
        item = _catalog_item(exact)
        tool = _CANONICAL_TOOLS.get(exact)
        schema = None if tool is None else remote_tool_schema(tool.input_schema)
        result = {
            "profile": PROFILE_VERSION,
            "item": item,
            "input_schema": schema,
            "annotations": None
            if tool is None or tool.annotations is None
            else tool.annotations.model_dump(exclude_none=True),
        }
        return json.dumps(result, separators=(",", ":"))

    rows = [_catalog_item(name) for name in allowed_canonical]
    if feature is not None:
        rows = [row for row in rows if row["feature"] == feature]
    if kind is not None:
        rows = [row for row in rows if row["kind"] == kind]
    if query is not None:
        needle = query.casefold()
        rows = [
            row
            for row in rows
            if needle in str(row["capability"]).casefold()
            or needle in str(row["feature"]).casefold()
            or needle in str(row["summary"] or "").casefold()
        ]
    rows.sort(key=lambda row: (str(row["feature"]), str(row["capability"])))
    if cursor is not None:
        start = next(
            (index + 1 for index, row in enumerate(rows) if str(row["capability"]) == cursor),
            None,
        )
        rows = [] if start is None else rows[start:]
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        next_cursor = str(page[-1]["capability"]) if page else None
    return json.dumps(
        {"profile": PROFILE_VERSION, "items": page, "next_cursor": next_cursor},
        separators=(",", ":"),
    )
