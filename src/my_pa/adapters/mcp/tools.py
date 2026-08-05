"""The tool list, derived from the capability set rather than written down.

An MCP client learns what a server can do from `tools/list`, so that list is a
second statement of the capability set — and a second statement is a second
thing to keep true. Nothing here names a capability, a field, or a schema. The
tools come from `Capability`, each tool's payload shape comes from the command
that capability builds, and the metadata beside the payload comes from
`RequestMetadata`'s own JSON Schema. A new capability with a new command appears
as a new tool with the correct schema, and no one edits this file — which WP-6
exercised: four capabilities were added, and the only change here was a schema
for a field type no earlier command used.

**Why the schema is assembled here and not owned by one model.** A request is
two documents with two owners: `RequestMetadata` validates the envelope, and the
command validates the payload. That split is `adapters/normalization.py`'s and
it is what makes one validation path possible across three transports. The
consequence is that no single object can render the whole input schema, so this
module joins the two halves in exactly the shape `normalize` reads them: the
envelope's fields at the top level, the capability's own fields under
`PAYLOAD_KEY`.

**`capability` is removed from the envelope half deliberately.** A tool call
names its capability in the tool name, and `normalize` refuses a document that
names it again — `RequestMetadata` would receive the argument twice. Publishing
it as an accepted property would advertise a field every request carrying it is
refused for.

**Nothing here reads an authorization rule.** A tool's description is the
command's own docstring summary, which is public documentation. Which purposes
may invoke a capability, and whether it is operator-only, are decided behind
`invoke`; a transport that published them would be a transport holding a copy of
a policy, and the copy is what goes stale.

The list is built at import so that a build whose capability set and command set
disagree fails when the process is composed rather than when a client asks. A
protocol handler is the wrong place to discover that the build is inconsistent.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType, UnionType
from typing import Any, Final, Union, get_args, get_origin, get_type_hints

from mcp.types import Tool

from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.application.commands import Command
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.identity.operation import Capability

__all__ = ["TOOLS", "input_schema_for", "payload_schema_for"]

#: JSON's scalar types, keyed by the Python type a command field declares.
#: `bool` before `int` is not a concern: these are exact keys, and `bool` is a
#: distinct object from `int` however the subclassing goes.
_SCALARS: Mapping[type, str] = MappingProxyType(
    {bool: "boolean", int: "integer", float: "number", str: "string"}
)


def _schema_for(annotation: Any) -> dict[str, Any] | None:  # noqa: ANN401 - a type annotation
    """The JSON Schema for one command field, or `None` for a shape not described here.

    `None` rather than a guess. An unrecognised annotation publishes an
    unconstrained property, which is honest — the field exists and this module
    cannot say what it takes — and
    `test_every_command_field_has_a_described_json_type` is what keeps `None`
    from becoming the normal answer as commands grow.
    """
    if annotation in _SCALARS:
        return {"type": _SCALARS[annotation]}
    if annotation is datetime:
        # A command holds a real `datetime` and `adapters.normalization` is what
        # converts a caller's string into one, exactly as it converts a string
        # into a `Representation`. On the wire it is a string, and JSON Schema
        # has a name for which kind, so this publishes the wire shape rather than
        # the Python type.
        return {"type": "string", "format": "date-time"}
    origin = get_origin(annotation)
    if origin is UnionType or origin is Union:
        optional = [member for member in get_args(annotation) if member is not type(None)]
        return _schema_for(optional[0]) if len(optional) == 1 else None
    if origin is tuple:
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            item = _schema_for(arguments[0])
            return None if item is None else {"type": "array", "items": item}
        return None
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return {"type": "string", "enum": [member.value for member in annotation]}
    return None


def payload_schema_for(command: type) -> dict[str, Any]:
    """The schema of one command's own fields, read off the dataclass.

    A field with no default is required, which is the same rule the constructor
    enforces: `__post_init__` never runs for a field the caller had to supply
    and did not, because the constructor refuses first.
    """
    hints = get_type_hints(command)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(command):
        described = _schema_for(hints[field.name])
        properties[field.name] = {} if described is None else described
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _envelope_schema() -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """`RequestMetadata`'s schema, less the field the tool name already carries."""
    schema = RequestMetadata.model_json_schema()
    properties = {
        name: value for name, value in schema["properties"].items() if name != "capability"
    }
    required = [name for name in schema.get("required", ()) if name != "capability"]
    return properties, required, dict(schema.get("$defs", {}))


def _referenced(definitions: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    """The definitions `document` actually points at.

    Removing `capability` from the envelope leaves `Capability` defined and
    unreferenced, which is a schema that describes something the tool does not
    accept. Pruning by reference rather than by name keeps that true after the
    next contract change.
    """
    rendered = json.dumps(document)
    return {name: value for name, value in definitions.items() if f'"#/$defs/{name}"' in rendered}


def input_schema_for(command: type) -> dict[str, Any]:
    """The complete input schema for the tool serving `command`.

    The envelope at the top level and the command's own fields under
    `PAYLOAD_KEY`, which is the document `normalize` reads. `payload` is
    required only when the command has a field that is.
    """
    properties, required, definitions = _envelope_schema()
    payload = payload_schema_for(command)
    properties[PAYLOAD_KEY] = payload
    if payload["required"]:
        required.append(PAYLOAD_KEY)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    kept = _referenced(definitions, schema)
    if kept:
        schema["$defs"] = kept
    return schema


def _summary(command: type) -> str | None:
    """The command's first documented line, as the tool's description."""
    documentation = command.__doc__
    return documentation.strip().splitlines()[0].strip() if documentation else None


#: Every command there is, by the capability it serves. Read off the union in
#: `application.commands` and each member's own `capability`, so the mapping
#: cannot disagree with the commands it maps.
_COMMANDS: Mapping[Capability, type] = MappingProxyType(
    {member.capability: member for member in get_args(Command.__value__)}
)


def _tools() -> tuple[Tool, ...]:
    """Publish only commands this transport can normalize and dispatch.

    The global capability vocabulary also includes WP-12C's authenticated
    native-host boundary. Those commands remain deliberately unwired here until
    WP-12G; iterating the Command-derived map preserves that separation and
    prevents an import-time KeyError for an enum-valid unavailable capability.
    """
    return tuple(
        Tool(
            name=capability.value,
            description=_summary(_COMMANDS[capability]),
            input_schema=input_schema_for(_COMMANDS[capability]),
        )
        for capability in _COMMANDS
    )


#: The tool list this server publishes. Built at import: see the module
#: docstring for why a build whose capability and command sets disagree should
#: fail at composition rather than at the first `tools/list`.
TOOLS: Final[tuple[Tool, ...]] = _tools()
